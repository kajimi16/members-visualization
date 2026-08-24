# 📊 OSS Insight 统计

<script setup>
import OrgStatsCards from './.vitepress/theme/stats/OrgStatsCards.vue'
</script>

以下数据来自 [OSS Insight](https://next.ossinsight.io/analyze/Silver-yiyangyiyang)，展示 Silver-yiyangyiyang 组织的各项统计指标。点击卡片可跳转查看详细分析。

<OrgStatsCards :selector-only="true" />

## ⭐ 受欢迎程度

<OrgStatsCards :show-period-selector="false" group="popularity" />

## 👥 参与者分析

<OrgStatsCards :show-period-selector="false" group="participants" />

## 🤝 参与度分析

<OrgStatsCards :show-period-selector="false" group="engagement" />

## 📈 生产力分析

<OrgStatsCards :show-period-selector="false" group="productivity" />
