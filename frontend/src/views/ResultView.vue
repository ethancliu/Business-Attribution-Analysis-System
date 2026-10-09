<script setup>
/**
 * 分析结果详情页。
 *
 * 路由参数 taskId 定位一个分析任务，展示它的六大模块标准化输出、
 * 结果元信息与运行日志，并支持 md / json / xlsx 三种格式导出。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import ResultModules from '@/components/ResultModules.vue'
import ExportBar from '@/components/ExportBar.vue'
import EmptyState from '@/components/EmptyState.vue'
import { useResultStore } from '@/store/result'
import { getTask } from '@/api/task'
import { taskStatusMeta } from '@/utils/constants'
import { formatDateTime, formatDuration, formatPercent } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const results = useResultStore()

const taskId = computed(() => Number(route.params.taskId))
const task = ref(null)
const taskLoading = ref(false)
const logDialogVisible = ref(false)
const activeLog = ref(null)

const result = computed(() => results.cache[taskId.value] || null)
const loading = computed(() => results.loadingTaskId === taskId.value)
const statusMeta = computed(() => taskStatusMeta(task.value?.task_status))

async function loadTask() {
  if (!taskId.value) return
  taskLoading.value = true
  try {
    task.value = await getTask(taskId.value)
  } catch (err) {
    ElMessage.error(err?.message || '任务详情加载失败')
  } finally {
    taskLoading.value = false
  }
}

async function loadResult() {
  if (!taskId.value) return
  try {
    await results.load(taskId.value)
  } catch {
    // 404 表示任务还没产出结果，页面会给出空态提示
  }
}

onMounted(() => {
  loadTask()
  loadResult()
})

watch(taskId, () => {
  task.value = null
  loadTask()
  loadResult()
})

function openLogDialog(row) {
  activeLog.value = row
  logDialogVisible.value = true
}

function prettyLog(content) {
  try {
    return JSON.stringify(JSON.parse(content), null, 2)
  } catch {
    return content
  }
}

function backToWorkspace() {
  const conv = task.value?.conversation_id
  router.push({ name: 'workspace', query: conv ? { conversation_id: conv } : {} })
}
</script>

<template>
  <div class="jy-page result-page">
    <header class="page-head">
      <div>
        <h1 class="jy-page-title">
          分析结果详情
          <el-tag v-if="taskId" size="small" type="info" effect="plain">任务 #{{ taskId }}</el-tag>
          <el-tag size="small" :type="statusMeta.type" effect="light">{{ statusMeta.label }}</el-tag>
        </h1>
        <p class="jy-page-desc">
          六大模块标准化输出：问题定义、关键指标、证据链、归因结论、待补充数据、下一步行动建议。
        </p>
      </div>
      <div class="page-actions">
        <el-button @click="backToWorkspace">
          <el-icon><Back /></el-icon>
          回到工作台
        </el-button>
        <ExportBar v-if="result" :result="result" />
      </div>
    </header>

    <el-card v-loading="taskLoading" class="meta-card" shadow="never">
      <template v-if="task">
        <div class="meta-grid">
          <div class="meta-item">
            <span class="meta-label">原始提问</span>
            <span class="meta-value">{{ task.input_text }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">当前步骤</span>
            <span class="meta-value">{{ task.current_step || '—' }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">进度</span>
            <span class="meta-value">
              {{ formatPercent(task.progress) }}（{{ task.step_index }}/{{ task.step_total }} 步）
            </span>
          </div>
          <div class="meta-item">
            <span class="meta-label">耗时</span>
            <span class="meta-value">{{ formatDuration(task.duration_ms) }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">开始时间</span>
            <span class="meta-value">{{ formatDateTime(task.started_at || task.created_at) }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">结束时间</span>
            <span class="meta-value">{{ formatDateTime(task.finished_at) }}</span>
          </div>
          <div v-if="task.error_message" class="meta-item meta-item--error">
            <span class="meta-label">失败原因</span>
            <span class="meta-value">{{ task.error_message }}</span>
          </div>
        </div>
      </template>
      <el-skeleton v-else :rows="2" animated />
    </el-card>

    <div v-loading="loading" class="main">
      <ResultModules v-if="result" :result="result" />

      <EmptyState
        v-else-if="!loading"
        icon="DataAnalysis"
        title="该任务尚未生成分析结果"
        :description="
          task?.task_status === 'failed'
            ? `任务执行失败：${task.error_message || '未知原因'}`
            : '分析完成后会自动生成六大模块结果，请稍后再试。'
        "
      />
    </div>

    <el-card v-if="task?.tool_calls?.length" class="logs-card" shadow="never">
      <template #header>
        <div class="logs-head">
          <span class="logs-title">工具调用链（{{ task.tool_calls.length }} 次）</span>
          <span class="jy-muted">点任意一行查看完整记录</span>
        </div>
      </template>
      <el-table :data="task.tool_calls" size="small" @row-click="openLogDialog">
        <el-table-column prop="seq" label="#" width="50" align="center" />
        <el-table-column prop="tool_name" label="工具" width="150" />
        <el-table-column label="入参" min-width="220">
          <template #default="{ row }">
            <span class="jy-mono args">{{ JSON.stringify(row.tool_args || {}) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="summary" label="结果摘要" min-width="260" show-overflow-tooltip />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'success' ? 'success' : 'danger'" effect="plain">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100" align="right">
          <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="logDialogVisible" title="工具调用记录" width="720px">
      <template v-if="activeLog">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="序号">{{ activeLog.seq }}</el-descriptions-item>
          <el-descriptions-item label="工具">{{ activeLog.tool_name }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ activeLog.status }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ formatDuration(activeLog.duration_ms) }}</el-descriptions-item>
          <el-descriptions-item label="开始">{{ formatDateTime(activeLog.started_at) }}</el-descriptions-item>
          <el-descriptions-item label="结束">{{ formatDateTime(activeLog.finished_at) }}</el-descriptions-item>
        </el-descriptions>
        <div class="log-block">
          <div class="log-block-title">入参</div>
          <pre class="jy-pre-wrap jy-mono">{{ prettyLog(JSON.stringify(activeLog.tool_args || {})) }}</pre>
        </div>
        <div class="log-block">
          <div class="log-block-title">结果摘要</div>
          <pre class="jy-pre-wrap">{{ activeLog.summary || '（无）' }}</pre>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.result-page {
  max-width: 1180px;
  margin: 0 auto;
  width: 100%;
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.jy-page-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.meta-card {
  margin-bottom: 18px;
  border: 1px solid var(--jy-border-light);
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 10px 24px;
}

.meta-item {
  display: flex;
  gap: 10px;
  font-size: 13px;
  min-width: 0;
}

.meta-label {
  flex: 0 0 72px;
  color: var(--jy-text-secondary);
}

.meta-value {
  flex: 1;
  min-width: 0;
  color: var(--jy-text);
  word-break: break-word;
}

.meta-item--error .meta-value {
  color: var(--jy-danger);
}

.main {
  min-height: 200px;
}

.logs-card {
  margin-top: 18px;
  border: 1px solid var(--jy-border-light);
}

.logs-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.logs-title {
  font-weight: 600;
}

.args {
  font-size: 12px;
  color: var(--jy-text-secondary);
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.log-block {
  margin-top: 14px;
}

.log-block-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--jy-text-regular);
}

.log-block pre {
  margin: 0;
  background: var(--jy-bg);
  padding: 10px 12px;
  border-radius: var(--jy-radius-sm);
  font-size: 12px;
  line-height: 1.7;
  max-height: 320px;
  overflow: auto;
}
</style>
