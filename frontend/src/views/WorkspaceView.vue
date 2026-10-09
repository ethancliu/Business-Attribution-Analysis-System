<script setup>
/**
 * 分析工作台（主页面）。
 *
 * 三栏布局：
 *   左  会话管理模块（ConversationList）
 *   中  消息流模块（MessageStream）+ 提问输入（AskComposer）
 *   右  实时进度模块（TaskProgressPanel）+ 附件模块（AttachmentPanel）
 *
 * 提问后由 WebSocket 推送驱动右侧进度与中间气泡的流式文本；
 * 分析完成后可从气泡或右侧直接打开六大模块结果抽屉。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import ConversationList from '@/components/ConversationList.vue'
import MessageStream from '@/components/MessageStream.vue'
import TaskProgressPanel from '@/components/TaskProgressPanel.vue'
import AttachmentPanel from '@/components/AttachmentPanel.vue'
import AskComposer from '@/components/AskComposer.vue'
import ResultModules from '@/components/ResultModules.vue'
import ExportBar from '@/components/ExportBar.vue'
import EmptyState from '@/components/EmptyState.vue'

import { useConversationStore } from '@/store/conversation'
import { useChatStore } from '@/store/chat'
import { useResultStore } from '@/store/result'
import { WS_STATE } from '@/ws/client'

const route = useRoute()
const router = useRouter()

const conversations = useConversationStore()
const chat = useChatStore()
const results = useResultStore()

const attachmentRefresh = ref(0)
const drawerVisible = ref(false)
const drawerTaskId = ref(null)
const rightTab = ref('progress')

const drawerResult = computed(() =>
  drawerTaskId.value ? results.cache[drawerTaskId.value] || null : null,
)
const drawerLoading = computed(() => results.loadingTaskId === drawerTaskId.value)

const wsStateText = computed(() => {
  const map = {
    [WS_STATE.idle]: '未连接',
    [WS_STATE.connecting]: '连接中',
    [WS_STATE.open]: '已连接',
    [WS_STATE.reconnecting]: '重连中',
    [WS_STATE.closed]: '已断开',
    [WS_STATE.error]: '连接异常',
  }
  return map[chat.wsState] || chat.wsState
})

onMounted(async () => {
  if (!conversations.items.length) await conversations.load()

  // 支持 /?conversation_id=3 直接进入某个会话（历史页跳转过来）
  const wanted = Number(route.query.conversation_id)
  const target = wanted && conversations.items.some((c) => c.conversation_id === wanted)
    ? wanted
    : conversations.currentId || conversations.items[0]?.conversation_id

  if (target) selectConversation(target)
})

onBeforeUnmount(() => {
  chat.closeSocket()
})

async function selectConversation(id) {
  if (!id) return
  if (route.query.conversation_id !== String(id)) {
    router.replace({ name: 'workspace', query: { ...route.query, conversation_id: id } })
  }
  await chat.open(id)
}

async function handleSend({ content, attachmentIds }) {
  try {
    await chat.send(content, attachmentIds)
    conversations.patch(chat.conversationId, {
      last_message_preview: content.slice(0, 60),
      last_message_at: new Date().toISOString(),
    })
    attachmentRefresh.value += 1
    rightTab.value = 'progress'
  } catch (err) {
    ElMessage.error(err?.message || '提问发送失败')
  }
}

async function handleCancel() {
  try {
    const res = await chat.cancelCurrent()
    ElMessage.info(res?.message || '已请求取消分析')
  } catch (err) {
    ElMessage.error(err?.message || '取消失败')
  }
}

async function openResult(taskId) {
  drawerTaskId.value = taskId
  drawerVisible.value = true
  try {
    await results.load(taskId)
  } catch (err) {
    ElMessage.error(err?.message || '结果加载失败')
  }
}

function gotoResultPage() {
  if (!drawerTaskId.value) return
  drawerVisible.value = false
  router.push({ name: 'result', params: { taskId: drawerTaskId.value } })
}

function askAgain() {
  // 在输入框里回填一个追问示例，引导多轮
  ElMessage.info('可在下方输入框继续追问，系统会沿用本轮的场景与上下文')
}
</script>

<template>
  <div class="workspace">
    <ConversationList @select="selectConversation" />

    <section class="center">
      <header class="center-head">
        <div class="center-title">
          <span class="title-text">
            {{ conversations.current?.title || '未选择会话' }}
          </span>
          <el-tag v-if="chat.conversationId" size="small" type="info" effect="plain">
            会话 #{{ chat.conversationId }}
          </el-tag>
          <el-tag size="small" :type="chat.wsState === WS_STATE.open ? 'success' : 'info'" effect="plain" round>
            长连接 {{ wsStateText }}
          </el-tag>
        </div>
        <div class="center-meta">
          <span v-if="conversations.current?.message_count !== undefined">
            共 {{ conversations.current?.message_count ?? 0 }} 条消息
          </span>
        </div>
      </header>

      <EmptyState
        v-if="!chat.conversationId"
        icon="ChatDotRound"
        title="请选择或新建一个会话"
        description="会话是分析的上下文边界：同一会话内的多次提问会共享历史与场景，支持多轮追问。"
      />

      <template v-else>
        <MessageStream
          :messages="chat.messages"
          :live="chat.live"
          :loading="chat.loadingMessages"
          :has-more="chat.hasMore"
          @load-more="chat.loadMore()"
          @open-result="openResult"
        />

        <AskComposer
          :conversation-id="chat.conversationId"
          :sending="chat.sending"
          :analyzing="chat.isAnalyzing"
          @send="handleSend"
          @cancel="handleCancel"
          @uploaded="attachmentRefresh += 1"
        />
      </template>
    </section>

    <aside class="right">
      <el-tabs v-model="rightTab" class="right-tabs">
        <el-tab-pane label="实时进度" name="progress">
          <TaskProgressPanel
            :live="chat.live"
            :ws-state="chat.wsState"
            :ws-error="chat.wsError"
            @cancel="handleCancel"
          />
          <div v-if="chat.live.resultId" class="quick-result">
            <el-button type="primary" @click="openResult(chat.live.taskId)">
              <el-icon><DataAnalysis /></el-icon>
              查看本轮六大模块结果
            </el-button>
            <el-button @click="askAgain">继续追问</el-button>
          </div>
        </el-tab-pane>

        <el-tab-pane name="attachment">
          <template #label>
            附件
            <el-badge
              v-if="attachmentRefresh"
              is-dot
              class="hidden-badge"
            />
          </template>
          <AttachmentPanel :conversation-id="chat.conversationId" :refresh-key="attachmentRefresh" />
        </el-tab-pane>
      </el-tabs>
    </aside>

    <el-drawer v-model="drawerVisible" size="62%" :title="`分析结果 · 任务 #${drawerTaskId ?? ''}`">
      <div v-loading="drawerLoading" class="drawer-body">
        <template v-if="drawerResult">
          <div class="drawer-head">
            <ExportBar :result="drawerResult" size="small" />
            <el-button size="small" @click="gotoResultPage">
              在独立页面打开
              <el-icon><Right /></el-icon>
            </el-button>
          </div>
          <ResultModules :result="drawerResult" />
        </template>
        <EmptyState
          v-else
          icon="DataAnalysis"
          title="结果尚未生成"
          description="分析任务完成后会自动生成六大模块结果。"
        />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.workspace {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: stretch;
  background: var(--jy-bg);
}

.center {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.center-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 20px;
  background: var(--jy-bg-card);
  border-bottom: 1px solid var(--jy-border);
}

.center-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.title-text {
  font-size: 15px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 420px;
}

.center-meta {
  font-size: 12px;
  color: var(--jy-text-secondary);
  white-space: nowrap;
}

.right {
  width: 420px;
  flex: 0 0 420px;
  border-left: 1px solid var(--jy-border);
  background: var(--jy-bg-card);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.right-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 0 14px 14px;
}

.right-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.right-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}

.quick-result {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.hidden-badge {
  margin-left: 4px;
  vertical-align: middle;
}

.drawer-body {
  min-height: 200px;
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px dashed var(--jy-border);
}

@media (max-width: 1500px) {
  .right {
    width: 360px;
    flex-basis: 360px;
  }
}
</style>
