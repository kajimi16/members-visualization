<template>
  <div class="quarterly-contributors-container">
    <!-- 月份范围选择器 - 始终显示 -->
    <div class="quarter-selector">
      <label>选择月份范围：</label>
      <select v-model="selectedPeriodKey" @change="loadData">
        <option v-for="period in availablePeriods" :key="period.key" :value="period.key">
          {{ period.period_label }}
        </option>
      </select>
      <button
        class="copy-btn"
        :class="{ disabled: !hasContributors, copied: copySuccess }"
        :disabled="!hasContributors"
        :title="hasContributors ? '复制优秀&卓越贡献者名单' : '暂无数据'"
        @click="copyContributorList"
      >
        {{ copySuccess ? '✅ 已复制' : '📋 复制名单' }}
      </button>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-state">
      <div class="loading-spinner"></div>
      <p>正在加载贡献者数据...</p>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="error" class="error-state">
      <p>❌ 加载失败: {{ error }}</p>
      <button @click="initialize" class="retry-btn">重试</button>
    </div>

    <!-- 暂无数据状态 -->
    <div v-else-if="!data" class="empty-state">
      <div class="empty-icon">📭</div>
      <p class="empty-title">暂无数据</p>
      <p class="empty-desc">{{ selectedPeriodLabel }}的数据尚未生成</p>
      <p class="empty-hint">请选择其他月份范围查看</p>
    </div>

    <!-- 内容区域 -->
    <div v-else class="content">
      <!-- 统计概览 -->
      <div class="stats-overview" v-if="data">
        <div class="stat-card">
          <div class="stat-icon">👥</div>
          <div class="stat-content">
            <div class="stat-value">{{ data.meta.total_contributors }}</div>
            <div class="stat-label">总贡献者</div>
            <div class="stat-desc">{{ selectedPeriodLabel }}</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">🏆</div>
          <div class="stat-content">
            <div class="stat-value">{{ data.meta.outstanding_count }}</div>
            <div class="stat-label">卓越贡献者</div>
            <div class="stat-desc">≥{{ data.meta.thresholds.outstanding }}次有效commit</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">⭐</div>
          <div class="stat-content">
            <div class="stat-value">{{ data.meta.excellent_count }}</div>
            <div class="stat-label">优秀贡献者</div>
            <div class="stat-desc">≥{{ data.meta.thresholds.excellent }}次有效commit</div>
          </div>
        </div>
      </div>

      <!-- 卓越贡献者榜单 -->
      <div class="contributors-section" v-if="data && data.contributors.outstanding.length > 0">
        <h2 class="section-title">
          <span class="title-icon">🏆</span>
          卓越贡献者
          <span class="count-badge">{{ data.contributors.outstanding.length }}</span>
        </h2>
        <div class="contributors-grid">
          <ContributorCard
            v-for="contributor in data.contributors.outstanding"
            :key="contributor.username"
            :contributor="contributor"
            level="outstanding"
          />
        </div>
      </div>

      <!-- 优秀贡献者榜单 -->
      <div class="contributors-section" v-if="data && data.contributors.excellent.length > 0">
        <h2 class="section-title">
          <span class="title-icon">⭐</span>
          优秀贡献者
          <span class="count-badge">{{ data.contributors.excellent.length }}</span>
        </h2>
        <div class="contributors-grid">
          <ContributorCard
            v-for="contributor in data.contributors.excellent"
            :key="contributor.username"
            :contributor="contributor"
            level="excellent"
          />
        </div>
      </div>

      <!-- 代码量排行 -->
      <div class="code-ranking-section" v-if="data && codeRanking.length > 0">
        <h2 class="section-title">
          <span class="title-icon">📝</span>
          代码量排行
          <span class="count-badge">{{ codeRanking.length }}</span>
        </h2>
        <p class="section-desc">按有效commit新增行数排行（有效commit：单文件新增 ≥ {{ data.meta.thresholds.valid_commit_threshold }} 行）</p>
        <div class="code-ranking-table-wrapper">
          <table class="code-ranking-table">
            <thead>
              <tr>
                <th>排名</th>
                <th>贡献者</th>
                <th>新增行数</th>
                <th>删除行数</th>
                <th>变更行数</th>
                <th>有效commit</th>
                <th>仓库数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in codeRanking" :key="item.username">
                <td>
                  <span class="rank-badge" :class="`rank-${item.code_rank <= 3 ? item.code_rank : 'other'}`">{{ item.code_rank }}</span>
                </td>
                <td>
                  <a :href="`https://github.com/${item.username}`" target="_blank" rel="noopener" class="user-link">{{ item.username }}</a>
                  <span v-if="!item.verified" class="unverified-tag" title="用户名未能通过GitHub API验证">未验证</span>
                </td>
                <td class="num-cell">{{ formatNumber(item.additions) }}</td>
                <td class="num-cell">{{ formatNumber(item.deletions) }}</td>
                <td class="num-cell">{{ formatNumber(item.changes) }}</td>
                <td class="num-cell">{{ item.valid_commits }}</td>
                <td class="num-cell">{{ item.repos_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 数据更新时间 -->
      <div class="update-info" v-if="data">
        <p>📅 数据生成时间：{{ formatDate(data.meta.generated_at) }}</p>
        <p>💡 有效commit定义：至少包含一个文件新增行数 ≥ {{ data.meta.thresholds.valid_commit_threshold }} 行</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ORG_NAME, ORG_GITHUB_URL, orgDataUrl } from '../utils/org.js'
import { ref, computed, onMounted } from 'vue'
import ContributorCard from './ContributorCard.vue'

// 响应式数据
const loading = ref(true)
const error = ref(null)
const data = ref(null)
const availablePeriods = ref([])
const selectedPeriodKey = ref('')
const copySuccess = ref(false)

const selectedPeriod = computed(() => {
  return availablePeriods.value.find(period => period.key === selectedPeriodKey.value) || null
})

const selectedPeriodLabel = computed(() => {
  return selectedPeriod.value?.period_label || '当前周期'
})

// 是否有优秀或卓越贡献者数据
const hasContributors = computed(() => {
  if (!data.value) return false
  const c = data.value.contributors
  return (c.outstanding && c.outstanding.length > 0) || (c.excellent && c.excellent.length > 0)
})

// 代码量排行（按新增行数，最多50人；旧数据无 ranking 字段时为空）
const codeRanking = computed(() => {
  if (!data.value || !data.value.ranking || !Array.isArray(data.value.ranking.by_code)) return []
  return data.value.ranking.by_code.slice(0, 50)
})

// 格式化大数字（千分位）
const formatNumber = (n) => {
  if (n === null || n === undefined) return '0'
  return Number(n).toLocaleString('zh-CN')
}

// 一键复制贡献者名单
const copyContributorList = async () => {
  if (!hasContributors.value) return

  const outstanding = data.value.contributors.outstanding || []
  const excellent = data.value.contributors.excellent || []

  let text = `${selectedPeriodLabel.value}总贡献者有${data.value.meta.total_contributors}人，卓越贡献者${outstanding.length}人，优秀贡献者${excellent.length}人，优秀&卓越开源贡献者名单如下：`

  if (outstanding.length > 0) {
    text += `\n【卓越贡献者】：${outstanding.map(c => c.username).join('、')}`
  }
  if (excellent.length > 0) {
    text += `\n【优秀贡献者】：${excellent.map(c => c.username).join('、')}`
  }

  try {
    await navigator.clipboard.writeText(text)
    copySuccess.value = true
    setTimeout(() => { copySuccess.value = false }, 2000)
  } catch {
    // fallback
    const textarea = document.createElement('textarea')
    textarea.value = text
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    copySuccess.value = true
    setTimeout(() => { copySuccess.value = false }, 2000)
  }
}

// 格式化日期
const formatDate = (dateString) => {
  return new Date(dateString).toLocaleString('zh-CN')
}

const padMonth = (month) => String(month).padStart(2, '0')

const getDataFilename = (year, startMonth, endMonth) => {
  return `monthly_contributors_${year}_${padMonth(startMonth)}_${padMonth(endMonth)}.json`
}

const getPeriodKey = (period) => {
  return `${period.year}-${padMonth(period.start_month)}-${padMonth(period.end_month)}`
}

const normalizePeriod = (period) => {
  const startMonth = Number(period.start_month)
  const endMonth = Number(period.end_month)
  return {
    ...period,
    year: Number(period.year),
    start_month: startMonth,
    end_month: endMonth,
    filename: period.filename || getDataFilename(period.year, startMonth, endMonth),
    period_label: period.period_label || (startMonth === endMonth
      ? `${period.year}年${startMonth}月`
      : `${period.year}年${startMonth}-${endMonth}月`)
  }
}

const loadPeriodIndex = async () => {
  const basePath = import.meta.env.BASE_URL || '/'
  const indexPath = orgDataUrl('monthly_contributors_index.json')
  const response = await fetch(indexPath)
  if (!response.ok) {
    throw new Error(`数据索引加载失败: HTTP ${response.status}`)
  }

  const periods = await response.json()
  availablePeriods.value = periods
    .map(normalizePeriod)
    .map(period => ({ ...period, key: getPeriodKey(period) }))
    .sort((a, b) => {
      if (b.year !== a.year) return b.year - a.year
      if (b.end_month !== a.end_month) return b.end_month - a.end_month
      return b.start_month - a.start_month
    })

  selectedPeriodKey.value = availablePeriods.value[0]?.key || ''
}

// 加载数据
const loadData = async () => {
  try {
    loading.value = true
    error.value = null
    data.value = null

    if (!selectedPeriod.value) {
      return
    }

    const basePath = import.meta.env.BASE_URL || '/'
    const filename = selectedPeriod.value.filename
    const jsonPath = orgDataUrl(filename)

    const response = await fetch(jsonPath)

    // 检查响应状态
    if (!response.ok) {
      data.value = null
      return
    }

    // 检查content-type是否为JSON
    const contentType = response.headers.get('content-type')
    if (!contentType || !contentType.includes('application/json')) {
      // 服务器返回了HTML页面（如404页面），视为数据不存在
      data.value = null
      return
    }

    data.value = await response.json()
  } catch (err) {
    // JSON解析错误也视为数据不存在
    if (err instanceof SyntaxError) {
      data.value = null
    } else {
      error.value = err.message
      console.error('加载贡献者数据失败:', err)
    }
  } finally {
    loading.value = false
  }
}

const initialize = async () => {
  try {
    loading.value = true
    error.value = null
    await loadPeriodIndex()
    await loadData()
  } catch (err) {
    error.value = err.message
    console.error('加载贡献者数据索引失败:', err)
  } finally {
    loading.value = false
  }
}

// 生命周期
onMounted(initialize)
</script>

<style scoped>
.quarterly-contributors-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
}

.loading-state,
.error-state,
.empty-state {
  text-align: center;
  padding: 60px 20px;
}

.empty-icon {
  font-size: 64px;
  margin-bottom: 20px;
}

.empty-title {
  font-size: 20px;
  font-weight: bold;
  color: var(--vp-c-text-1);
  margin: 10px 0;
}

.empty-desc {
  font-size: 16px;
  color: var(--vp-c-text-2);
  margin: 8px 0;
}

.empty-hint {
  font-size: 14px;
  color: var(--vp-c-text-3);
  margin: 8px 0;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #f3f3f3;
  border-top: 4px solid #667eea;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 20px;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.retry-btn {
  padding: 8px 16px;
  background: var(--vp-c-brand-1);
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  transition: background-color 0.3s;
}

.retry-btn:hover {
  background: var(--vp-c-brand-2);
}

.quarter-selector {
  background: var(--vp-c-bg-soft);
  padding: 20px;
  border-radius: 12px;
  margin-bottom: 30px;
  display: flex;
  align-items: center;
  gap: 15px;
}

.quarter-selector label {
  font-weight: 500;
  color: var(--vp-c-text-1);
}

.quarter-selector select {
  padding: 8px 12px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 6px;
  background: var(--vp-c-bg);
  color: var(--vp-c-text-1);
  font-size: 14px;
  cursor: pointer;
}

.copy-btn {
  margin-left: auto;
  padding: 8px 16px;
  border: 1px solid var(--vp-c-brand-1);
  border-radius: 6px;
  background: var(--vp-c-bg);
  color: var(--vp-c-brand-1);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.copy-btn:hover:not(.disabled) {
  background: var(--vp-c-brand-1);
  color: white;
}

.copy-btn.disabled {
  border-color: var(--vp-c-divider);
  color: var(--vp-c-text-3);
  cursor: not-allowed;
  opacity: 0.5;
}

.copy-btn.copied {
  border-color: var(--vp-c-green-1);
  color: var(--vp-c-green-1);
}

.stats-overview {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 15px;
  margin-bottom: 40px;
}

.stat-card {
  background: var(--vp-c-bg-soft);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  transition: transform 0.3s, box-shadow 0.3s;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.stat-icon {
  font-size: 36px;
  line-height: 1;
}

.stat-content {
  flex: 1;
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: var(--vp-c-brand-1);
  line-height: 1.2;
}

.stat-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--vp-c-text-1);
  margin-top: 2px;
}

.stat-desc {
  font-size: 11px;
  color: var(--vp-c-text-2);
  margin-top: 2px;
}

.contributors-section {
  margin-bottom: 50px;
}

.section-title {
  font-size: 24px;
  font-weight: bold;
  color: var(--vp-c-text-1);
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-icon {
  font-size: 28px;
}

.count-badge {
  background: var(--vp-c-brand-1);
  color: white;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 14px;
  font-weight: normal;
}

.contributors-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
}

.update-info {
  text-align: center;
  padding: 20px;
  background: var(--vp-c-bg-soft);
  border-radius: 8px;
  color: var(--vp-c-text-2);
  font-size: 14px;
  margin-top: 40px;
}

.update-info p {
  margin: 5px 0;
}

.code-ranking-section {
  margin-bottom: 50px;
}

.section-desc {
  color: var(--vp-c-text-2);
  font-size: 13px;
  margin: -10px 0 16px;
}

.code-ranking-table-wrapper {
  background: var(--vp-c-bg-soft);
  border-radius: 12px;
  padding: 8px;
  overflow-x: auto;
}

.code-ranking-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.code-ranking-table th {
  text-align: left;
  padding: 10px 12px;
  color: var(--vp-c-text-2);
  font-weight: 500;
  border-bottom: 1px solid var(--vp-c-divider);
  white-space: nowrap;
}

.code-ranking-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--vp-c-divider);
  white-space: nowrap;
}

.code-ranking-table tbody tr:last-child td {
  border-bottom: none;
}

.code-ranking-table tbody tr:hover {
  background: var(--vp-c-bg);
}

.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  font-size: 13px;
  font-weight: bold;
  color: white;
}

.rank-badge.rank-1 {
  background: #f5a623;
}

.rank-badge.rank-2 {
  background: #9aa0a6;
}

.rank-badge.rank-3 {
  background: #c98a4b;
}

.rank-badge.rank-other {
  background: var(--vp-c-divider);
  color: var(--vp-c-text-2);
}

.user-link {
  color: var(--vp-c-brand-1);
  text-decoration: none;
}

.user-link:hover {
  text-decoration: underline;
}

.unverified-tag {
  margin-left: 6px;
  font-size: 11px;
  color: var(--vp-c-text-3);
  border: 1px solid var(--vp-c-divider);
  border-radius: 4px;
  padding: 1px 5px;
}

.num-cell {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--vp-c-text-1);
}

@media (max-width: 768px) {
  .quarterly-contributors-container {
    padding: 15px;
  }

  .quarter-selector {
    flex-direction: column;
    align-items: stretch;
  }

  .stats-overview {
    grid-template-columns: 1fr;
  }

  .contributors-grid {
    grid-template-columns: 1fr;
  }
}
</style>
