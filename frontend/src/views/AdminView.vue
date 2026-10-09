<script setup>
/**
 * 管理控制台（仅 admin 角色可见，路由已做 requiresAdmin 守卫，页面内不再判权限）。
 *
 * 六个标签页：
 *   运行总览   服务信息、计数器、WebSocket、存储、认证中心
 *   配置管理   分组筛选 + 配置表 + 单条编辑（自动热重载）+ 全量热重载与变更回显
 *   功能开关   卡片列表 + el-switch 即时生效（失败回滚）
 *   业务数据源 数据源表 + 启用/停用
 *   场景与工具 预置场景表 + 工具清单表
 *   运行日志   任务 ID / 类型 / 条数筛选 + 本地分页 + 内容详情
 *
 * 数据一次性由 store.loadAll() 拉取（onMounted 只调用一次），日志按需首次进入标签页时加载。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import EmptyState from '@/components/EmptyState.vue'

import { useAdminStore } from '@/store/admin'
import { LOG_TYPE, LOG_LEVEL_TYPE, logTypeLabel } from '@/utils/constants'
import { formatBytes, formatDateTime, formatRelative, formatUptime, truncate } from '@/utils/format'

const store = useAdminStore()

const activeTab = ref('overview')

/* ---------------------------------- 运行总览 --------------------------------- */

const COUNTER_META = [
  { key: 'users', label: '注册用户', icon: 'User' },
  { key: 'conversations_active', label: '活跃会话', icon: 'ChatDotRound' },
  { key: 'messages', label: '消息总数', icon: 'ChatLineSquare' },
  { key: 'attachments', label: '附件数量', icon: 'Paperclip' },
  { key: 'results', label: '分析结果', icon: 'DataAnalysis' },
  { key: 'tasks_total', label: '任务总数', icon: 'Tickets' },
  { key: 'tasks_running', label: '运行中任务', icon: 'Loading', tone: 'warning' },
  { key: 'tasks_success', label: '成功任务', icon: 'CircleCheck', tone: 'success' },
  { key: 'tasks_failed', label: '失败任务', icon: 'CircleClose', tone: 'danger' },
  { key: 'tasks_cancelled', label: '已取消任务', icon: 'Remove', tone: 'info' },
]

const STORAGE_LABELS = {
  uploads: '上传目录',
  exports: '导出目录',
  workspace: '工作区目录',
  total_bytes: '合计占用',
  used_bytes: '已用空间',
  free_bytes: '剩余空间',
  file_count: '文件数量',
}

const refreshingOverview = ref(false)

const counters = computed(() => {
  const source = store.overview?.counters || {}
  return COUNTER_META.map((meta) => ({ ...meta, value: source[meta.key] ?? 0 }))
})

const websocket = computed(() => store.overview?.websocket || null)

function isPlainObject(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

/** 通用标量渲染：数字按 key 猜测是否字节数，布尔转中文，数组顿号连接。 */
function formatScalar(key, value) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number') {
    const k = String(key).toLowerCase()
    if (k.includes('bytes') || k.includes('size')) return formatBytes(value)
    return value.toLocaleString('zh-CN')
  }
  if (Array.isArray(value)) return value.length ? value.join('、') : '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** 已绑定会话：后端可能是数组、对象或纯数量，统一成可渲染的字符串数组。 */
const boundConversations = computed(() => {
  const value = websocket.value?.bound_conversations
  if (Array.isArray(value)) return value.map((v) => String(v))
  if (isPlainObject(value)) return Object.entries(value).map(([k, v]) => `${k}: ${formatScalar(k, v)}`)
  return []
})

const boundConversationCount = computed(() => {
  const value = websocket.value?.bound_conversations
  if (Array.isArray(value)) return value.length
  if (isPlainObject(value)) return Object.keys(value).length
  return Number(value) || 0
})

/** 存储区：值可能是嵌套对象（uploads/exports/workspace），也可能是扁平标量。 */
const storageEntries = computed(() => {
  const storage = store.overview?.storage || {}
  return Object.entries(storage).map(([key, value]) => {
    const group = isPlainObject(value)
    return {
      key,
      label: STORAGE_LABELS[key] || key,
      group,
      scalar: group ? '' : formatScalar(key, value),
      children: group
        ? Object.entries(value).map(([childKey, childValue]) => ({
            key: childKey,
            label: STORAGE_LABELS[childKey] || childKey,
            text: formatScalar(childKey, childValue),
          }))
        : [],
    }
  })
})

const authOverview = computed(() => store.overview?.auth_center || store.authCenter || null)

async function handleRefreshOverview() {
  refreshingOverview.value = true
  try {
    await store.refreshOverview()
    ElMessage.success('运行总览已刷新')
  } catch (err) {
    ElMessage.error(err?.message || '运行总览刷新失败')
  } finally {
    refreshingOverview.value = false
  }
}

/* ---------------------------------- 配置管理 --------------------------------- */

const reloading = ref(false)
const reloadActive = ref([])

const changedCount = computed(() => store.lastReload?.changed_keys?.length || 0)

async function handleEditConfig(row) {
  try {
    const { value } = await ElMessageBox.prompt(
      `配置项 ${row.config_key}${row.description ? `（${row.description}）` : ''}`,
      '编辑配置值',
      {
        confirmButtonText: '保存并热重载',
        cancelButtonText: '取消',
        inputType: 'textarea',
        inputValue: row.config_value ?? '',
        inputPlaceholder: '请输入新的配置值',
        inputValidator: (val) => (String(val ?? '').trim() ? true : '配置值不能为空'),
      },
    )
    await store.saveConfig(row.config_key, value)
    ElMessage.success(`配置 ${row.config_key} 已保存，已自动热重载，无需重启`)
  } catch (err) {
    // ElMessageBox 取消时 reject 的是字符串 'cancel' / 'close'
    if (err === 'cancel' || err === 'close') return
    ElMessage.error(err?.message || '配置保存失败')
  }
}

async function handleReload() {
  reloading.value = true
  try {
    const res = await store.reload([])
    const total = res?.total_keys ?? 0
    const changed = res?.changed_keys?.length || 0
    if (changed) {
      ElMessage.success(`热重载完成：共 ${total} 项配置，${changed} 项发生变更，已即时生效，无需重启`)
    } else {
      ElMessage.success(`热重载完成：共 ${total} 项配置，配置无变化`)
    }
    reloadActive.value = ['last']
  } catch (err) {
    ElMessage.error(err?.message || '配置热重载失败')
  } finally {
    reloading.value = false
  }
}

/* ---------------------------------- 功能开关 --------------------------------- */

const togglingKey = ref('')

async function handleToggleFeature(row, value) {
  const prev = row.enabled
  row.enabled = value
  togglingKey.value = row.config_key
  try {
    await store.toggleFeature(row.config_key, value)
    ElMessage.success(`「${row.name || row.config_key}」已即时生效`)
  } catch (err) {
    row.enabled = prev
    ElMessage.error(err?.message || '功能开关切换失败，已回滚')
  } finally {
    togglingKey.value = ''
  }
}

/* --------------------------------- 业务数据源 -------------------------------- */

const togglingDatasourceId = ref(null)

async function handleToggleDatasource(row) {
  const nextEnabled = row.status !== 'enabled'
  togglingDatasourceId.value = row.id
  try {
    await store.toggleDatasource(row.id)
    ElMessage.success(`数据源「${row.name}」已${nextEnabled ? '启用' : '停用'}`)
  } catch (err) {
    ElMessage.error(err?.message || '数据源状态切换失败')
  } finally {
    togglingDatasourceId.value = null
  }
}

/* ---------------------------------- 运行日志 --------------------------------- */

const LOG_TYPE_OPTIONS = Object.keys(LOG_TYPE)
const LOG_LIMIT_OPTIONS = [20, 50, 100, 200, 500]

const logFilters = reactive({ taskId: '', logType: '', limit: 50 })
const logLoading = ref(false)
const logLoaded = ref(false)
const logPage = ref(1)
const logPageSize = ref(20)

const pagedLogs = computed(() => {
  const start = (logPage.value - 1) * logPageSize.value
  return store.logs.slice(start, start + logPageSize.value)
})

async function queryLogs() {
  logLoading.value = true
  try {
    await store.loadLogs({
      taskId: logFilters.taskId.trim() || undefined,
      logType: logFilters.logType || undefined,
      limit: Number(logFilters.limit) || 50,
    })
    logPage.value = 1
    logLoaded.value = true
  } catch (err) {
    ElMessage.error(err?.message || '运行日志加载失败')
  } finally {
    logLoading.value = false
  }
}

function handleLogSizeChange(size) {
  logPageSize.value = size
  logPage.value = 1
}

function logLevelType(level) {
  return LOG_LEVEL_TYPE[String(level || '').toUpperCase()] || 'info'
}

/** 工具调用日志的 log_content 是 JSON 字符串，尽量格式化成多行。 */
function formatLogContent(log) {
  const raw = log?.log_content ?? ''
  if (log?.log_type !== 'tool') return String(raw)
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return String(raw)
  }
}

const logDetail = reactive({ visible: false, title: '', text: '' })

function openLogDetail(row) {
  logDetail.title = `日志详情 · #${row.log_id ?? '—'}（${logTypeLabel(row.log_type)} / ${row.log_level || '—'}）`
  logDetail.text = formatLogContent(row)
  logDetail.visible = true
}

/* ----------------------------------- 生命周期 --------------------------------- */

onMounted(async () => {
  try {
    await store.loadAll()
  } catch (err) {
    ElMessage.error(err?.message || '管理数据加载失败')
  }
})

// 日志不在 loadAll 的范围内，首次进入该标签页时按需加载一次
watch(activeTab, (tab) => {
  if (tab === 'logs' && !logLoaded.value && !logLoading.value) queryLogs()
})
</script>

<template>
  <div v-loading="store.loading" class="admin-page">
    <header class="page-head">
      <div>
        <h1 class="jy-page-title">管理控制台</h1>
        <p class="jy-page-desc">
          配置热重载、功能开关、业务数据源、场景与工具清单、运行日志的集中运维入口。
        </p>
      </div>
      <div v-if="store.overview" class="head-meta">
        <el-tag size="small" effect="plain">{{ store.overview.service || '服务' }}</el-tag>
        <el-tag size="small" type="info" effect="plain">v{{ store.overview.version || '—' }}</el-tag>
        <el-tag size="small" type="info" effect="plain">{{ store.overview.env || '—' }}</el-tag>
        <el-tag size="small" type="success" effect="plain">
          已运行 {{ formatUptime(store.overview.uptime_sec) }}
        </el-tag>
        <span class="head-time jy-muted">服务器时间 {{ formatDateTime(store.overview.server_time) }}</span>
      </div>
    </header>

    <el-tabs v-model="activeTab" class="admin-tabs">
      <!-- ============================ 1. 运行总览 ============================ -->
      <el-tab-pane label="运行总览" name="overview">
        <div class="section-head">
          <span class="section-title">服务运行状况</span>
          <el-button :loading="refreshingOverview" size="small" @click="handleRefreshOverview">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>

        <EmptyState
          v-if="!store.overview"
          icon="Monitor"
          title="暂无运行数据"
          description="未能获取到服务总览，请确认后端服务是否正常。"
        >
          <el-button type="primary" :loading="refreshingOverview" @click="handleRefreshOverview">
            重新获取
          </el-button>
        </EmptyState>

        <template v-else>
          <div class="counter-grid">
            <div
              v-for="item in counters"
              :key="item.key"
              class="counter-card jy-card"
              :class="item.tone ? `counter-card--${item.tone}` : ''"
            >
              <div class="counter-head">
                <span class="counter-label">{{ item.label }}</span>
                <el-icon class="counter-icon"><component :is="item.icon" /></el-icon>
              </div>
              <div class="counter-value">{{ item.value }}</div>
              <div class="counter-key jy-mono jy-muted">{{ item.key }}</div>
            </div>
          </div>

          <div class="panel-grid">
            <section class="panel jy-card">
              <header class="panel-head">
                <el-icon class="panel-icon"><Connection /></el-icon>
                <span class="panel-title">WebSocket</span>
              </header>
              <div v-if="websocket" class="kv-list">
                <div class="kv">
                  <span class="kv-label">活跃连接</span>
                  <span class="kv-value">{{ websocket.active_connections ?? 0 }}</span>
                </div>
                <div class="kv">
                  <span class="kv-label">累计连接</span>
                  <span class="kv-value">{{ websocket.total_connections ?? 0 }}</span>
                </div>
                <div class="kv">
                  <span class="kv-label">已绑定会话</span>
                  <span class="kv-value">{{ boundConversationCount }} 个</span>
                </div>
                <div class="kv">
                  <span class="kv-label">事件循环绑定</span>
                  <span class="kv-value">
                    <el-tag size="small" effect="plain" :type="websocket.loop_bound ? 'success' : 'info'">
                      {{ websocket.loop_bound ? '已绑定' : '未绑定' }}
                    </el-tag>
                  </span>
                </div>
              </div>
              <div v-if="boundConversations.length" class="tag-wrap">
                <el-tag
                  v-for="conv in boundConversations"
                  :key="conv"
                  size="small"
                  effect="plain"
                  type="info"
                >
                  会话 {{ conv }}
                </el-tag>
              </div>
              <div v-else-if="websocket" class="jy-muted panel-empty">当前没有长连接绑定到会话。</div>
              <EmptyState v-else icon="Connection" title="暂无长连接数据" />
            </section>

            <section class="panel jy-card">
              <header class="panel-head">
                <el-icon class="panel-icon"><Coin /></el-icon>
                <span class="panel-title">存储</span>
              </header>
              <div v-if="storageEntries.length" class="storage-list">
                <div v-for="entry in storageEntries" :key="entry.key" class="storage-item">
                  <div class="storage-row">
                    <span class="kv-label">{{ entry.label }}</span>
                    <span v-if="!entry.group" class="kv-value">{{ entry.scalar }}</span>
                  </div>
                  <div v-if="entry.group" class="storage-sub">
                    <div v-for="child in entry.children" :key="child.key" class="storage-row storage-row--sub">
                      <span class="kv-label">{{ child.label }}</span>
                      <span class="kv-value">{{ child.text }}</span>
                    </div>
                  </div>
                </div>
              </div>
              <EmptyState v-else icon="Coin" title="暂无存储数据" />
            </section>

            <section class="panel jy-card">
              <header class="panel-head">
                <el-icon class="panel-icon"><Lock /></el-icon>
                <span class="panel-title">认证中心</span>
                <el-tag
                  v-if="authOverview"
                  size="small"
                  effect="plain"
                  :type="authOverview.reachable ? 'success' : 'danger'"
                >
                  {{ authOverview.reachable ? '可达' : '不可达' }}
                </el-tag>
              </header>
              <template v-if="authOverview">
                <el-alert
                  v-if="authOverview.message"
                  class="panel-alert"
                  :closable="false"
                  show-icon
                  :type="authOverview.reachable ? 'success' : 'warning'"
                  :title="authOverview.message"
                />
                <div class="kv-list">
                  <div class="kv">
                    <span class="kv-label">服务地址</span>
                    <span class="kv-value jy-mono">{{ authOverview.base_url || '—' }}</span>
                  </div>
                  <div v-if="authOverview.introspect_cache_size !== undefined" class="kv">
                    <span class="kv-label">内省缓存条数</span>
                    <span class="kv-value">{{ authOverview.introspect_cache_size }}</span>
                  </div>
                  <div v-if="authOverview.introspect_cache_sec !== undefined" class="kv">
                    <span class="kv-label">内省缓存秒数</span>
                    <span class="kv-value">{{ authOverview.introspect_cache_sec }} 秒</span>
                  </div>
                </div>
              </template>
              <EmptyState v-else icon="Lock" title="暂无认证中心数据" />
            </section>
          </div>
        </template>
      </el-tab-pane>

      <!-- ============================ 2. 配置管理 ============================ -->
      <el-tab-pane label="配置管理" name="configs">
        <div class="section-head">
          <div class="group-filter">
            <span class="filter-label">配置分组</span>
            <el-radio-group v-model="store.activeGroup" size="small">
              <el-radio-button :value="''">全部</el-radio-button>
              <el-radio-button v-for="g in store.configGroups" :key="g" :value="g">{{ g }}</el-radio-button>
            </el-radio-group>
          </div>
          <el-button type="primary" :loading="reloading" @click="handleReload">
            <el-icon><Refresh /></el-icon>
            全量热重载
          </el-button>
        </div>

        <el-alert
          class="tip-alert"
          type="info"
          :closable="false"
          show-icon
          title="修改任意配置项后后端会立即热重载，无需重启服务。"
        />

        <el-collapse v-if="store.lastReload" v-model="reloadActive" class="reload-panel">
          <el-collapse-item name="last">
            <template #title>
              <span class="reload-title">
                <el-icon><Clock /></el-icon>
                最近一次热重载 · {{ formatDateTime(store.lastReload.reloaded_at) }}
                <el-tag size="small" effect="plain" type="info">
                  配置总数 {{ store.lastReload.total_keys ?? 0 }}
                </el-tag>
                <el-tag size="small" effect="plain" :type="changedCount ? 'warning' : 'success'">
                  变更 {{ changedCount }} 项
                </el-tag>
                <span class="jy-muted">{{ formatRelative(store.lastReload.reloaded_at) }}</span>
              </span>
            </template>

            <div v-if="changedCount" class="changed-list">
              <div v-for="change in store.lastReload.changed_keys" :key="change.config_key" class="changed-item">
                <div class="changed-key jy-mono">{{ change.config_key }}</div>
                <div class="changed-diff">
                  <span class="changed-old">{{ truncate(change.old_value, 90) || '（空）' }}</span>
                  <el-icon class="changed-arrow"><Right /></el-icon>
                  <span class="changed-new">{{ truncate(change.new_value, 90) || '（空）' }}</span>
                </div>
              </div>
            </div>
            <div v-else class="jy-muted">本次重载没有任何配置项发生变化。</div>

            <div v-if="store.lastReload.message" class="jy-muted reload-message">
              服务端返回：{{ store.lastReload.message }}
            </div>
          </el-collapse-item>
        </el-collapse>

        <el-table
          v-if="store.filteredConfigs.length"
          class="data-table"
          :data="store.filteredConfigs"
          border
          stripe
          size="small"
          row-key="config_key"
        >
          <el-table-column prop="config_key" label="配置键" min-width="220">
            <template #default="{ row }">
              <span class="jy-mono">{{ row.config_key }}</span>
            </template>
          </el-table-column>
          <el-table-column label="配置值" min-width="220">
            <template #default="{ row }">
              <el-tooltip :content="String(row.config_value ?? '')" placement="top" :show-after="400">
                <span class="jy-mono">{{ truncate(row.config_value, 60) || '（空）' }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="分组" width="140">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" type="info">{{ row.config_group || '未分组' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="说明" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="jy-muted">{{ row.description || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="更新时间" width="170">
            <template #default="{ row }">
              <span>{{ formatDateTime(row.updated_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="handleEditConfig(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
        <EmptyState
          v-else
          icon="Setting"
          title="没有匹配的配置项"
          description="当前分组下没有配置数据，可切换到「全部」查看。"
        />
      </el-tab-pane>

      <!-- ============================ 3. 功能开关 ============================ -->
      <el-tab-pane label="功能开关" name="toggles">
        <div class="section-head">
          <span class="section-title">功能开关（切换后即时生效）</span>
          <span class="jy-muted">共 {{ store.featureToggles.length }} 项</span>
        </div>

        <div v-if="store.featureToggles.length" class="toggle-grid">
          <div v-for="item in store.featureToggles" :key="item.config_key" class="toggle-card jy-card">
            <div class="toggle-main">
              <div class="toggle-name">
                {{ item.name || item.config_key }}
                <el-tag size="small" effect="plain" :type="item.enabled ? 'success' : 'info'">
                  {{ item.enabled ? '已开启' : '已关闭' }}
                </el-tag>
              </div>
              <div class="toggle-key jy-mono jy-muted">{{ item.config_key }}</div>
              <div class="toggle-desc">{{ item.description || '暂无说明' }}</div>
            </div>
            <el-switch
              :model-value="item.enabled"
              :loading="togglingKey === item.config_key"
              inline-prompt
              active-text="开"
              inactive-text="关"
              @change="handleToggleFeature(item, $event)"
            />
          </div>
        </div>
        <EmptyState v-else icon="SwitchButton" title="暂无功能开关" />
      </el-tab-pane>

      <!-- =========================== 4. 业务数据源 =========================== -->
      <el-tab-pane label="业务数据源" name="datasources">
        <div class="section-head">
          <span class="section-title">业务数据源</span>
          <span class="jy-muted">共 {{ store.datasources.length }} 个</span>
        </div>

        <el-table
          v-if="store.datasources.length"
          class="data-table"
          :data="store.datasources"
          border
          stripe
          size="small"
          row-key="id"
        >
          <el-table-column prop="name" label="名称" min-width="160" />
          <el-table-column label="类型" width="120">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" type="info">{{ row.ds_type || '—' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="主机:端口" min-width="200">
            <template #default="{ row }">
              <span class="jy-mono">{{ row.host || '—' }}:{{ row.port ?? '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="库名" min-width="140">
            <template #default="{ row }">
              <span class="jy-mono">{{ row.db_name || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="row.status === 'enabled' ? 'success' : 'info'">
                {{ row.status === 'enabled' ? '已启用' : '已停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="说明" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="jy-muted">{{ row.description || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="更新时间" width="150">
            <template #default="{ row }">
              <el-tooltip :content="formatDateTime(row.updated_at)" placement="top">
                <span class="jy-muted">{{ formatRelative(row.updated_at) }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                size="small"
                :type="row.status === 'enabled' ? 'danger' : 'primary'"
                :loading="togglingDatasourceId === row.id"
                @click="handleToggleDatasource(row)"
              >
                {{ row.status === 'enabled' ? '停用' : '启用' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <EmptyState v-else icon="Coin" title="暂无业务数据源" />
      </el-tab-pane>

      <!-- ========================== 5. 场景与工具 ========================== -->
      <el-tab-pane label="场景与工具" name="scenarios">
        <div class="section-head">
          <span class="section-title">预置业务场景</span>
          <span class="jy-muted">共 {{ store.scenarios.length }} 个</span>
        </div>

        <el-table
          v-if="store.scenarios.length"
          class="data-table"
          :data="store.scenarios"
          border
          stripe
          size="small"
          row-key="key"
        >
          <el-table-column label="Key" width="180">
            <template #default="{ row }">
              <span class="jy-mono">{{ row.key }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="180" />
          <el-table-column label="说明" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="jy-muted">{{ row.description || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="强关键词" min-width="260">
            <template #default="{ row }">
              <div v-if="row.strong_keywords?.length" class="tag-wrap">
                <el-tag
                  v-for="word in row.strong_keywords"
                  :key="word"
                  size="small"
                  effect="plain"
                  type="danger"
                >
                  {{ word }}
                </el-tag>
              </div>
              <span v-else class="jy-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="普通关键词" min-width="260">
            <template #default="{ row }">
              <div v-if="row.keywords?.length" class="tag-wrap">
                <el-tag v-for="word in row.keywords" :key="word" size="small" effect="plain" type="info">
                  {{ word }}
                </el-tag>
              </div>
              <span v-else class="jy-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="兜底场景" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.is_fallback" size="small" type="warning" effect="plain">兜底</el-tag>
              <span v-else class="jy-muted">—</span>
            </template>
          </el-table-column>
        </el-table>
        <EmptyState v-else icon="Compass" title="暂无预置场景" />

        <div class="section-head section-head--gap">
          <span class="section-title">可用工具清单</span>
          <span class="jy-muted">共 {{ store.tools.length }} 个</span>
        </div>

        <el-table
          v-if="store.tools.length"
          class="data-table"
          :data="store.tools"
          border
          stripe
          size="small"
          row-key="name"
        >
          <el-table-column label="工具名" width="220">
            <template #default="{ row }">
              <span class="jy-mono">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="说明" min-width="280" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="jy-muted">{{ row.description || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="签名" min-width="320" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="jy-mono tool-signature">{{ row.signature || '—' }}</span>
            </template>
          </el-table-column>
        </el-table>
        <EmptyState v-else icon="Tools" title="暂无工具" />
      </el-tab-pane>

      <!-- ============================ 6. 运行日志 ============================ -->
      <el-tab-pane label="运行日志" name="logs">
        <div class="log-filter jy-card">
          <div class="filter-item">
            <span class="filter-label">任务 ID</span>
            <el-input
              v-model="logFilters.taskId"
              size="small"
              clearable
              placeholder="按任务 ID 精确筛选"
              @keyup.enter="queryLogs"
            />
          </div>
          <div class="filter-item">
            <span class="filter-label">日志类型</span>
            <el-select v-model="logFilters.logType" size="small" clearable placeholder="全部类型">
              <el-option
                v-for="type in LOG_TYPE_OPTIONS"
                :key="type"
                :label="logTypeLabel(type)"
                :value="type"
              />
            </el-select>
          </div>
          <div class="filter-item">
            <span class="filter-label">条数上限</span>
            <el-select v-model="logFilters.limit" size="small">
              <el-option v-for="n in LOG_LIMIT_OPTIONS" :key="n" :label="`${n} 条`" :value="n" />
            </el-select>
          </div>
          <el-button type="primary" size="small" :loading="logLoading" @click="queryLogs">
            <el-icon><Search /></el-icon>
            查询
          </el-button>
          <span class="filter-summary jy-muted">当前 {{ store.logs.length }} 条</span>
        </div>

        <el-table
          v-if="pagedLogs.length"
          v-loading="logLoading"
          class="data-table"
          :data="pagedLogs"
          border
          stripe
          size="small"
        >
          <el-table-column label="时间" width="160">
            <template #default="{ row }">
              <span>{{ formatDateTime(row.created_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="级别" width="100">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="logLevelType(row.log_level)">
                {{ row.log_level || '—' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              {{ logTypeLabel(row.log_type) }}
            </template>
          </el-table-column>
          <el-table-column label="任务 ID" width="100">
            <template #default="{ row }">
              <span class="jy-mono">{{ row.task_id ?? '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="内容" min-width="420" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="log-content" @click="openLogDetail(row)">{{ row.log_content || '—' }}</span>
            </template>
          </el-table-column>
        </el-table>
        <EmptyState
          v-else
          icon="Document"
          title="暂无运行日志"
          description="调整筛选条件后点击「查询」，或等待任务产生日志。"
        />

        <div v-if="store.logs.length" class="log-pager">
          <el-pagination
            v-model:current-page="logPage"
            :page-size="logPageSize"
            :total="store.logs.length"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next, jumper"
            background
            size="small"
            @size-change="handleLogSizeChange"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="logDetail.visible" :title="logDetail.title" width="720px">
      <pre class="log-detail jy-mono jy-pre-wrap">{{ logDetail.text || '（空内容）' }}</pre>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin-page {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px 32px;
  background: var(--jy-bg);
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.head-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.head-time {
  font-size: 12px;
}

.admin-tabs {
  margin-top: 4px;
}

/* 段落标题与工具条 */
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.section-head--gap {
  margin-top: 26px;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--jy-text);
}

.group-filter {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}

.filter-label {
  font-size: 12px;
  color: var(--jy-text-secondary);
  white-space: nowrap;
}

.tip-alert {
  margin-bottom: 12px;
}

/* 计数器栅格 */
.counter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(178px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.counter-card {
  padding: 14px 16px;
  border-left: 3px solid var(--jy-brand);
}

.counter-card--warning {
  border-left-color: var(--jy-warning);
}

.counter-card--danger {
  border-left-color: var(--jy-danger);
}

.counter-card--success {
  border-left-color: var(--jy-success);
}

.counter-card--info {
  border-left-color: var(--jy-info);
}

.counter-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.counter-label {
  font-size: 13px;
  color: var(--jy-text-regular);
}

.counter-icon {
  color: var(--jy-text-placeholder);
}

.counter-value {
  margin-top: 6px;
  font-size: 26px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--jy-text);
  font-variant-numeric: tabular-nums;
}

.counter-card--warning .counter-value {
  color: var(--jy-warning);
}

.counter-card--danger .counter-value {
  color: var(--jy-danger);
}

.counter-card--success .counter-value {
  color: var(--jy-success);
}

.counter-key {
  margin-top: 2px;
  font-size: 11px;
}

/* 三张详情面板 */
.panel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
}

.panel {
  padding: 14px 16px;
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.panel-icon {
  color: var(--jy-brand);
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  flex: 1;
}

.panel-alert {
  margin-bottom: 10px;
}

.panel-empty {
  font-size: 12px;
}

.kv-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.kv,
.storage-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
}

.kv-label {
  color: var(--jy-text-secondary);
  white-space: nowrap;
}

.kv-value {
  color: var(--jy-text);
  text-align: right;
  word-break: break-all;
  min-width: 0;
}

.storage-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.storage-item {
  border-bottom: 1px dashed var(--jy-border-light);
  padding-bottom: 10px;
}

.storage-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.storage-sub {
  margin-top: 6px;
  padding-left: 12px;
  border-left: 2px solid var(--jy-border-light);
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.storage-row--sub .kv-label,
.storage-row--sub .kv-value {
  font-size: 12px;
}

.tag-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.panel .tag-wrap {
  margin-top: 12px;
}

/* 热重载结果 */
.reload-panel {
  margin-bottom: 14px;
  border-top: none;
}

.reload-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--jy-text);
  flex-wrap: wrap;
}

.reload-message {
  margin-top: 10px;
  font-size: 12px;
}

.changed-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.changed-item {
  padding: 8px 10px;
  background: var(--jy-bg-hover);
  border-radius: var(--jy-radius-sm);
}

.changed-key {
  font-size: 12px;
  font-weight: 600;
  color: var(--jy-text);
  margin-bottom: 4px;
}

.changed-diff {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  flex-wrap: wrap;
}

.changed-old {
  color: var(--jy-danger);
  text-decoration: line-through;
}

.changed-new {
  color: var(--jy-success);
  font-weight: 500;
}

.changed-arrow {
  color: var(--jy-text-placeholder);
}

/* 表格与开关卡片 */
.data-table {
  width: 100%;
}

.data-table :deep(.el-table__cell) {
  vertical-align: middle;
}

.toggle-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 12px;
}

.toggle-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
}

.toggle-main {
  min-width: 0;
}

.toggle-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--jy-text);
}

.toggle-key {
  margin-top: 2px;
  font-size: 11px;
}

.toggle-desc {
  margin-top: 6px;
  font-size: 12px;
  color: var(--jy-text-secondary);
  line-height: 1.6;
}

.tool-signature {
  font-size: 12px;
  color: var(--jy-text-regular);
}

/* 日志筛选与详情 */
.log-filter {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.filter-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-item :deep(.el-input),
.filter-item :deep(.el-select) {
  width: 172px;
}

.filter-summary {
  font-size: 12px;
  margin-left: auto;
}

.log-content {
  cursor: pointer;
  color: var(--jy-text);
}

.log-content:hover {
  color: var(--jy-brand);
}

.log-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.log-detail {
  margin: 0;
  max-height: 56vh;
  overflow: auto;
  padding: 12px 14px;
  background: var(--jy-bg-hover);
  border-radius: var(--jy-radius-sm);
  font-size: 12px;
  color: var(--jy-text-regular);
}
</style>
