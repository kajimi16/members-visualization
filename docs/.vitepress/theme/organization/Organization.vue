<script setup>
import { ORG_NAME, ORG_GITHUB_URL, orgDataUrl } from '../utils/org.js'
import { ref, onMounted } from 'vue'
import OrganizationTable from './OrganizationTable.vue'

const organizationData = ref([]);
const loading = ref(false)
const error = ref(null)

const loadData = async () => {
    const basePath = import.meta.env.BASE_URL || '/'
    const commitsPath = orgDataUrl('organization_datasource.json')
    const response = await fetch(commitsPath)
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
    }
    const source = await response.json()
    return source.top10KnowledgeSharingOrganizationInfo
}

onMounted(async () => {
    try {
        loading.value = true
        error.value = null
        organizationData.value = await loadData()
    } catch (err) {
        error.value = err.message
    } finally {
        loading.value = false
    }
})
</script>

<template>
    <div class="wrapper">
        <div v-if="loading" class="loading">
            <p>正在加载数据...</p>
        </div>

        <div v-else-if="error" class="error">
            <p>加载数据时出错: {{ error }}</p>
        </div>

        <OrganizationTable :organization-data="organizationData" />
    </div>
</template>

<style scoped>
.wrapper {
    width: 100%;
    padding: 20px 0;
}

.chart {
    width: 100%;
    height: 600px;
}

.loading,
.error {
    text-align: center;
    padding: 60px;
    font-size: 18px;
    border-radius: 12px;
    margin: 20px 0;
}

.error {
    color: #e74c3c;
    background: #fdf2f2;
    border: 1px solid #fecaca;
}

.loading {
    color: #3498db;
    background: #f0f9ff;
    border: 1px solid #bae6fd;
}
</style>
