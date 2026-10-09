<script setup>
/**
 * 消息流模块：渲染一轮轮问答。
 * 助手消息支持流式追加（message_delta），并在结果就绪后给出「查看完整结果」入口。
 */
import { computed, nextTick, ref, watch } from 'vue'

import { MESSAGE_ROLE, taskStatusMeta } from '@/utils/constants'
import { formatBytes, formatTime, formatArgs } from '@/utils/format'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  live: { type: Object, required: true },
  loading: { type: Boolean, default: false },
  hasMore: { type: Boolean, default: false },
})

const emit = defineEmits(['load-more', 'open-result'])

const scroller = ref(null)

const roleMeta = (role) => MESSAGE_ROLE[role] || { label: role, type: 'info' }

/** 正在流式输出的那条助手消息：给它加上光标。 */
const streamingMessageId = computed(() => {
  if (!props.live.streaming) return null
  return props.live.assistantMessageId
})

const liveStatus = computed(() => taskStatusMeta(props.live.status))

function scrollToBottom() {
  nextTick(() => {
    const el = scroller.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

watch(
  () => [props.messages.length, props.live.streamText],
  () => scrollToBottom(),
)

function onScroll(event) {
  if (event.target.scrollTop <= 4 && props.hasMore) emit('load-more')
}

defineExpose({ scrollToBottom })
</script>

<template>
  <div ref="scroller" v-loading="loading" class="stream" @scroll="onScroll">
    <div v-if="hasMore" class="stream-more" @click="emit('load-more')">
      <el-icon><Top /></el-icon> 上滑或点击加载更早的消息
    </div>

    <div
      v-for="msg in messages"
      :key="msg.message_id"
      class="msg"
      :class="`msg--${msg.role}`"
    >
      <div class="avatar" :class="`avatar--${msg.role}`">
        {{ msg.role === 'user' ? '我' : msg.role === 'tool' ? '工' : 'AI' }}
      </div>

      <div class="body">
        <div class="bubble-head">
          <span class="who">{{ roleMeta(msg.role).label }}</span>
          <span v-if="msg.tool_name" class="tool-name jy-mono">
            {{ msg.tool_name }}
            <el-tag v-if="msg.tool_status" size="small" effect="plain">
              {{ msg.tool_status }}
            </el-tag>
          </span>
          <span class="time">{{ formatTime(msg.created_at) }}</span>
        </div>

        <div class="bubble" :class="{ 'bubble--empty': !msg.content }">
          <div v-if="msg.content" class="content jy-pre-wrap">{{ msg.content }}</div>
          <div v-else-if="streamingMessageId === msg.message_id" class="content jy-muted">
            正在分析……
          </div>
          <div v-else class="content jy-muted">（本轮未产生文本内容）</div>

          <span v-if="streamingMessageId === msg.message_id" class="cursor" />

          <div v-if="msg.attachments?.length" class="attachments">
            <el-tag
              v-for="att in msg.attachments"
              :key="att.attachment_id"
              size="small"
              effect="plain"
              type="info"
            >
              <el-icon><Paperclip /></el-icon>
              {{ att.file_name }}（{{ formatBytes(att.file_size) }}）
            </el-tag>
          </div>
        </div>

        <!-- 该轮分析的结果入口：任务终态后出现在助手消息下方 -->
        <div
          v-if="msg.role === 'assistant' && msg.task_id && live.taskId === msg.task_id && live.resultId"
          class="result-entry"
        >
          <el-button type="primary" link @click="emit('open-result', live.taskId)">
            <el-icon><DataAnalysis /></el-icon>
            查看六大模块完整结果
          </el-button>
          <el-tag size="small" :type="liveStatus.type" effect="light">
            任务 {{ liveStatus.label }}
          </el-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stream {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 20px 8px;
  scroll-behavior: smooth;
}

.stream-more {
  text-align: center;
  font-size: 12px;
  color: var(--jy-text-secondary);
  padding: 6px;
  cursor: pointer;
}

.stream-more:hover {
  color: var(--jy-brand);
}

.msg {
  display: flex;
  gap: 10px;
  margin-bottom: 18px;
}

.msg--user {
  flex-direction: row-reverse;
}

.avatar {
  flex: 0 0 32px;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  background: var(--jy-brand-soft);
  color: var(--jy-brand);
}

.avatar--user {
  background: #e9f7f1;
  color: var(--jy-success);
}

.avatar--tool {
  background: #f2f3f7;
  color: var(--jy-text-secondary);
}

.body {
  max-width: min(760px, 78%);
  min-width: 0;
}

.msg--user .body {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.bubble-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--jy-text-placeholder);
  margin-bottom: 4px;
}

.msg--user .bubble-head {
  flex-direction: row-reverse;
}

.who {
  color: var(--jy-text-secondary);
  font-weight: 500;
}

.bubble {
  position: relative;
  background: var(--jy-bg-card);
  border: 1px solid var(--jy-border-light);
  border-radius: var(--jy-radius);
  padding: 10px 14px;
  box-shadow: var(--jy-shadow);
  min-width: 60px;
}

.msg--user .bubble {
  background: var(--jy-brand);
  border-color: var(--jy-brand);
  color: #fff;
}

.msg--user .bubble .jy-muted {
  color: rgba(255, 255, 255, 0.8);
}

.content {
  font-size: 14px;
  line-height: 1.75;
}

.cursor {
  display: inline-block;
  width: 7px;
  height: 15px;
  background: var(--jy-brand);
  margin-left: 3px;
  vertical-align: text-bottom;
  animation: blink 1s steps(2, start) infinite;
}

@keyframes blink {
  to {
    visibility: hidden;
  }
}

.attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.result-entry {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}
</style>
