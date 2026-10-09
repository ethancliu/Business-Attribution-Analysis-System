<script setup>
/**
 * 历史会话页。
 *
 * 单页把「全部会话」拉平成一张可检索、可批量操作的表格：
 *   顶部  标题 + 新建会话
 *   工具条 关键字搜索（防抖）/ 状态筛选 / 刷新 / 批量删除
 *   表格  多选、标题（点击进工作台）、状态、消息数、最后消息预览、活跃时间、创建时间、操作
 *   展开行 按需拉取该会话下的分析任务，展示进度与结果入口
 *
 * 数据全部走 useConversationStore（列表/新建/改名/删除），
 * 会话任务用 api/task 的 listTasks 按 conversation_id 懒加载；本页不修改任何既有文件。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import EmptyState from '@/components/EmptyState.vue'
import { useConversationStore } from '@/store/conversation'
import { listTasks } from '@/api/task'
import { CONVERSATION_STATUS, taskStatusMeta } from '@/utils/constants'
import {
  formatBytes,
  formatDateTime,
  formatDuration,
  formatPercent,
  formatRelative,
  truncate,
} from '@/utils/format'

const router = useRouter()
const store = useConversationStore()

const tableRef = ref(null)
const selectedRows = ref([])

/** 展开行缓存：{ [conversation_id]: { loading, loaded, error, items } } */
const taskMap = ref({})

const selectedIds = computed(() => selectedRows.value.map((row) => row.conversation_id))

/** 状态筛选：全部 -> null，其余直接透传给 store.statusFilter。 */
const statusModel = computed({
  get: () => store.statusFilter || 'all',
  set: (value) => {
    store.statusFilter = value === 'all' ? null : value
    store.load()
  },
})

function conversationStatusMeta(status) {
  return CONVERSATION_STATUS[status] || { label: status || '未知', type: 'info' }
}

function progressStatus(taskStatus) {
  if (taskStatus === 'success') return 'success'
  if (taskStatus === 'failed') return 'exception'
  if (taskStatus === 'cancelled') return 'warning'
  return ''
}

/** 耗时：优先 started_at -> finished_at，缺一端就交给 formatDuration 显示占位。 */
function taskDuration(task) {
  if (!task.started_at || !task.finished_at) return null
  const start = new Date(task.started_at).getTime()
  const end = new Date(task.finished_at).getTime()
  if (Number.isNaN(start) || Number.isNaN(end)) return null
  return end - start
}

onMounted(() => {
  store.load()
})

// --- 工具条 ---------------------------------------------------------------

let searchTimer = null
function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => store.load(), 300)
}

function handleRefresh() {
  taskMap.value = {}
  store.load()
  ElMessage.success('已刷新')
}

// --- 新建 / 打开 ----------------------------------------------------------

async function handleCreate() {
  try {
    const conv = await store.create()
    ElMessage.success(`已创建会话「${conv.title}」`)
    router.push({ name: 'workspace', query: { conversation_id: conv.conversation_id } })
  } catch (err) {
    ElMessage.error(err?.message || '新建会话失败')
  }
}

function openWorkspace(conv) {
  store.select(conv.conversation_id)
  router.push({ name: 'workspace', query: { conversation_id: conv.conversation_id } })
}

function openResult(taskId) {
  router.push({ name: 'result', params: { taskId } })
}

// --- 重命名 / 删除 --------------------------------------------------------

async function handleRename(conv) {
  let title
  try {
    const { value } = await ElMessageBox.prompt('请输入新的会话标题', '重命名会话', {
      inputValue: conv.title,
      inputPattern: /\S/,
      inputErrorMessage: '标题不能为空',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    title = value.trim()
  } catch {
    return
  }
  try {
    await store.rename(conv.conversation_id, title)
    ElMessage.success('已重命名')
  } catch (err) {
    ElMessage.error(err?.message || '重命名失败')
  }
}

const DELETE_WARNING =
  '删除会级联清理该会话下的消息、任务（含任务日志）、分析结果、附件记录，以及 uploads/exports/workspace 下的物理文件，且不可恢复。确认删除？'

async function removeAndReport(ids) {
  const res = await store.remove(ids)
  const freed = formatBytes(res?.freed_bytes)
  ElMessage.success(
    `已删除 ${res?.deleted ?? 0} 个会话，清理物理文件 ${res?.removed_files ?? 0} 个，释放 ${freed}`,
  )
  selectedRows.value = []
  tableRef.value?.clearSelection()
  taskMap.value = {}
}

async function handleDelete(conv) {
  try {
    await ElMessageBox.confirm(`删除会话「${conv.title}」。${DELETE_WARNING}`, '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await removeAndReport([conv.conversation_id])
  } catch (err) {
    ElMessage.error(err?.message || '删除失败')
  }
}

async function handleBatchDelete() {
  const ids = selectedIds.value
  if (!ids.length) return
  const titles = selectedRows.value.map((r) => `「${r.title}」`).join('、')
  try {
    await ElMessageBox.confirm(`将删除 ${ids.length} 个会话：${titles}。${DELETE_WARNING}`, '批量删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await removeAndReport(ids)
  } catch (err) {
    ElMessage.error(err?.message || '删除失败')
  }
}

function handleSelectionChange(rows) {
  selectedRows.value = rows
}

// --- 展开行：按需加载会话任务 ---------------------------------------------

function tasksOf(convId) {
  return taskMap.value[convId]
}

async function loadTasks(conversationId, force = false) {
  const cached = taskMap.value[conversationId]
  if (cached?.loaded && !force) return

  taskMap.value = {
    ...taskMap.value,
    [conversationId]: {
      loading: true,
      loaded: false,
      error: '',
      items: cached?.items || [],
    },
  }
  try {
    const data = await listTasks({ conversationId })
    taskMap.value = {
      ...taskMap.value,
      [conversationId]: { loading: false, loaded: true, error: '', items: data?.items || [] },
    }
  } catch (err) {
    taskMap.value = {
      ...taskMap.value,
      [conversationId]: {
        loading: false,
        loaded: true,
        error: err?.message || '任务加载失败',
        items: [],
      },
    }
  }
}

function handleExpandChange(row, expandedRows) {
  const list = Array.isArray(expandedRows) ? expandedRows : []
  const isExpanded = list.some((r) => r.conversation_id === row.conversation_id)
  if (isExpanded) loadTasks(row.conversation_id)
}
</script>

<template>
  <div class="history jy-page">
    <header class="page-head">
      <div>
        <h1 class="jy-page-title">历史会话</h1>
        <p class="jy-page-desc">
          检索、重命名或批量清理历史会话，展开任意一行可查看该会话下的分析任务。
        </p>
      </div>
      <el-button type="primary" :loading="store.creating" @click="handleCreate">
        <el-icon><Plus /></el-icon>
        新建会话
      </el-button>
    </header>

    <div class="toolbar jy-card">
      <el-input
        v-model="store.keyword"
        class="toolbar-search"
        placeholder="按标题搜索会话"
        clearable
        @input="onSearchInput"
        @clear="store.load()"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <el-select v-model="statusModel" class="toolbar-status" placeholder="状态">
        <el-option label="全部状态" value="all" />
        <el-option label="进行中" value="active" />
        <el-option label="已归档" value="archived" />
      </el-select>

      <div class="toolbar-spacer" />

      <el-button :loading="store.loading" @click="handleRefresh">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
      <el-button
        type="danger"
        plain
        :disabled="!selectedIds.length"
        @click="handleBatchDelete"
      >
        <el-icon><Delete /></el-icon>
        批量删除<span v-if="selectedIds.length">（{{ selectedIds.length }}）</span>
      </el-button>
    </div>

    <div class="table-card jy-card">
      <el-table
        ref="tableRef"
        v-loading="store.loading"
        :data="store.items"
        row-key="conversation_id"
        class="history-table"
        @selection-change="handleSelectionChange"
        @expand-change="handleExpandChange"
      >
        <el-table-column type="selection" width="46" />
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-body" v-loading="tasksOf(row.conversation_id)?.loading">
              <div v-if="tasksOf(row.conversation_id)?.error" class="expand-error">
                <el-alert
                  :title="tasksOf(row.conversation_id).error"
                  type="error"
                  :closable="false"
                  show-icon
                />
              </div>

              <EmptyState
                v-else-if="tasksOf(row.conversation_id)?.loaded && !tasksOf(row.conversation_id).items.length"
                icon="FolderOpened"
                title="该会话暂无分析任务"
                description="在工作台向这个会话提问后，任务会自动登记到这里。"
              />

              <el-table
                v-else-if="tasksOf(row.conversation_id)?.items.length"
                :data="tasksOf(row.conversation_id).items"
                size="small"
                class="task-table"
              >
                <el-table-column label="任务 ID" width="110">
                  <template #default="{ row: task }">
                    <span class="jy-mono">#{{ task.task_id }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="提问内容" min-width="240" show-overflow-tooltip>
                  <template #default="{ row: task }">
                    {{ truncate(task.input_text, 80) || '—' }}
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="100">
                  <template #default="{ row: task }">
                    <el-tag size="small" :type="taskStatusMeta(task.task_status).type" effect="plain">
                      {{ taskStatusMeta(task.task_status).label }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="进度" width="170">
                  <template #default="{ row: task }">
                    <el-progress
                      :percentage="task.progress || 0"
                      :status="progressStatus(task.task_status)"
                      :format="formatPercent"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="耗时" width="110">
                  <template #default="{ row: task }">
                    {{ formatDuration(taskDuration(task)) }}
                  </template>
                </el-table-column>
                <el-table-column label="开始 / 结束时间" width="260">
                  <template #default="{ row: task }">
                    <div class="task-time">
                      <span>{{ formatDateTime(task.started_at) }}</span>
                      <span class="task-time-sep">→</span>
                      <span>{{ formatDateTime(task.finished_at) }}</span>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="120" fixed="right">
                  <template #default="{ row: task }">
                    <el-button
                      v-if="task.result_id"
                      link
                      type="primary"
                      size="small"
                      @click="openResult(task.task_id)"
                    >
                      <el-icon><DataAnalysis /></el-icon>
                      查看结果
                    </el-button>
                    <span v-else class="jy-muted task-no-result">暂无结果</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="会话标题" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <button type="button" class="title-link" @click="openWorkspace(row)">
              {{ row.title || '未命名会话' }}
            </button>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="conversationStatusMeta(row.status).type" effect="plain">
              {{ conversationStatusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="消息数" width="90" align="right">
          <template #default="{ row }">
            <span class="jy-mono">{{ row.message_count ?? 0 }}</span>
          </template>
        </el-table-column>

        <el-table-column label="最后消息预览" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="jy-muted">{{ row.last_message_preview || '暂无消息' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="最后活跃" width="140">
          <template #default="{ row }">
            {{ formatRelative(row.last_message_at || row.created_at) }}
          </template>
        </el-table-column>

        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>

        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openWorkspace(row)">打开</el-button>
            <el-button link size="small" @click="handleRename(row)">
              <el-icon><EditPen /></el-icon>
              重命名
            </el-button>
            <el-button link type="danger" size="small" @click="handleDelete(row)">
              <el-icon><Delete /></el-icon>
              删除
            </el-button>
          </template>
        </el-table-column>

        <template #empty>
          <EmptyState
            icon="ChatDotRound"
            title="还没有历史会话"
            :description="store.keyword || store.statusFilter
              ? '当前筛选条件下没有匹配的会话，换个关键字或状态再试试。'
              : '新建一个会话，然后提出你的第一个经营问题，这里会自动留存记录。'"
          >
            <el-button type="primary" @click="handleCreate">
              <el-icon><Plus /></el-icon>
              新建会话
            </el-button>
          </EmptyState>
        </template>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.history {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 0;
}

.page-head .jy-page-title {
  margin-bottom: 4px;
}

.page-head .jy-page-desc {
  margin-bottom: 0;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
}

.toolbar-search {
  width: 280px;
  max-width: 40vw;
}

.toolbar-status {
  width: 130px;
}

.toolbar-spacer {
  flex: 1;
}

.table-card {
  flex: 1;
  min-height: 0;
  padding: 4px;
  overflow: hidden;
}

.history-table {
  width: 100%;
}

.title-link {
  padding: 0;
  border: none;
  background: transparent;
  color: var(--jy-brand);
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  text-align: left;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.title-link:hover {
  color: var(--jy-brand-dark);
  text-decoration: underline;
}

.expand-body {
  padding: 8px 12px 12px 56px;
  min-height: 60px;
}

.task-table {
  border-radius: var(--jy-radius-sm);
  overflow: hidden;
}

.task-time {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--jy-text-secondary);
  white-space: nowrap;
}

.task-time-sep {
  color: var(--jy-text-placeholder);
}

.task-no-result {
  font-size: 12px;
}

.expand-error {
  max-width: 640px;
}

@media (max-width: 1200px) {
  .toolbar-search {
    width: 200px;
  }
}
</style>
