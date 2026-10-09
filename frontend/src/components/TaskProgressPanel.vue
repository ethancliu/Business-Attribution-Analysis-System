<script setup>
/**
 * 实时进度模块：长连接状态 + 分析步骤 + 工具调用链。
 * 数据全部来自 WebSocket 推送（见 store/chat.js 的 handleEvent）。
 */
import { computed } from 'vue'

import { WS_STATE } from '@/ws/client'
import { taskStatusMeta } from '@/utils/constants'
import { formatArgs, formatDuration, formatTime, formatPercent } from '@/utils/format'

const props = defineProps({
  live: { type: Object, required: true },
  wsState: { type: String, default: WS_STATE.idle },
  wsError: { type: String, default: '' },
})

const emit = defineEmits(['cancel'])

const status = computed(() => taskStatusMeta(props.live.status))

const wsMeta = computed(() => {
  const map = {
    [WS_STATE.idle]: { type: 'info', text: '未连接' },
    [WS_STATE.connecting]: { type: 'warning', text: '连接中…' },
    [WS_STATE.open]: { type: 'success', text: '已连接' },
    [WS_STATE.reconnecting]: { type: 'warning', text: '重连中…' },
    [WS_STATE.closed]: { type: 'info', text: '已断开' },
    [WS_STATE.error]: { type: 'danger', text: '连接异常' },
  }
  return map[props.wsState] || { type: 'info', text: props.wsState }
})

const runningTool = computed(() => props.live.tools.find((t) => t.status === 'running') || null)

const successCount = computed(() => props.live.tools.filter((t) => t.status === 'success').length)
const failedCount = computed(() => props.live.tools.filter((t) => t.status !== 'running' && t.status !== 'success').length)
</script>

<template>
  <section class="progress jy-card">
    <header class="head">
      <div class="head-left">
        <el-icon class="icon"><DataLine /></el-icon>
        <span class="title">分析进度</span>
        <el-tag v-if="live.taskId" size="small" type="info" effect="plain">任务 #{{ live.taskId }}</el-tag>
        <el-tag size="small" :type="status.type" effect="light">{{ status.label }}</el-tag>
      </div>
      <div class="head-right">
        <el-tag size="small" :type="wsMeta.type" effect="plain" round>{{ wsMeta.text }}</el-tag>
        <el-button
          v-if="live.streaming"
          size="small"
          type="danger"
          plain
          @click="emit('cancel')"
        >
          取消分析
        </el-button>
      </div>
    </header>

    <el-alert
      v-if="wsError"
      class="alert"
      type="warning"
      :closable="false"
      show-icon
      :title="`长连接异常：${wsError}；正在自动重连，重连后会自动补发本轮报文`"
    />

    <template v-if="live.taskId">
      <div class="meta">
        <div class="meta-item">
          <span class="meta-label">识别场景</span>
          <span class="meta-value">{{ live.scenario || '待识别' }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">当前步骤</span>
          <span class="meta-value">{{ live.currentStep || '—' }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">步骤进度</span>
          <span class="meta-value">
            {{ live.stepIndex }}/{{ live.stepTotal || '—' }}
            <template v-if="runningTool"> · 执行 {{ runningTool.name }}</template>
          </span>
        </div>
        <div class="meta-item">
          <span class="meta-label">工具调用</span>
          <span class="meta-value">
            {{ live.tools.length }} 次
            <span v-if="successCount" class="ok">成功 {{ successCount }}</span>
            <span v-if="failedCount" class="fail">失败 {{ failedCount }}</span>
          </span>
        </div>
      </div>

      <el-progress
        class="bar"
        :percentage="live.progress"
        :status="live.status === 'failed' ? 'exception' : live.status === 'success' ? 'success' : undefined"
        :stroke-width="10"
        :text-inside="false"
        :format="formatPercent"
      />

      <el-alert
        v-if="live.errorMessage"
        class="alert"
        type="error"
        :closable="false"
        show-icon
        :title="live.errorMessage"
      />

      <div v-if="live.tools.length" class="tools">
        <div class="tools-title">工具调用链</div>
        <div
          v-for="tool in live.tools"
          :key="tool.seq"
          class="tool"
          :class="`tool--${tool.status}`"
        >
          <div class="tool-seq">{{ tool.seq }}</div>
          <div class="tool-body">
            <div class="tool-line">
              <span class="tool-name">{{ tool.name }}</span>
              <el-tag
                size="small"
                effect="plain"
                :type="tool.status === 'success' ? 'success' : tool.status === 'running' ? 'warning' : 'danger'"
              >
                {{ tool.status === 'success' ? '成功' : tool.status === 'running' ? '执行中' : tool.status }}
              </el-tag>
              <span v-if="tool.durationMs" class="tool-duration">{{ formatDuration(tool.durationMs) }}</span>
              <span v-if="tool.rows !== null && tool.rows !== undefined" class="tool-rows">
                {{ tool.rows }} 行
              </span>
            </div>
            <div v-if="formatArgs(tool.args)" class="tool-args jy-mono">
              {{ formatArgs(tool.args) }}
            </div>
            <div v-if="tool.summary" class="tool-summary">{{ tool.summary }}</div>
          </div>
        </div>
      </div>

      <div v-if="live.finishedAt" class="finish-line">
        <el-icon><CircleCheck /></el-icon>
        本轮分析于 {{ formatTime(live.finishedAt) }} 结束
        <template v-if="live.durationMs">，总耗时 {{ formatDuration(live.durationMs) }}</template>
      </div>
    </template>

    <div v-else class="idle">
      尚未发起分析。提问后这里会实时展示场景识别、步骤推进与每一次工具调用。
    </div>
  </section>
</template>

<style scoped>
.progress {
  padding: 14px 16px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.head-left,
.head-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.icon {
  color: var(--jy-brand);
}

.title {
  font-size: 14px;
  font-weight: 600;
}

.alert {
  margin-top: 10px;
}

.meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 8px 16px;
  margin: 12px 0 10px;
}

.meta-item {
  display: flex;
  gap: 8px;
  font-size: 13px;
  min-width: 0;
}

.meta-label {
  color: var(--jy-text-secondary);
  flex: 0 0 60px;
}

.meta-value {
  color: var(--jy-text);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ok {
  color: var(--jy-success);
  margin-left: 6px;
}

.fail {
  color: var(--jy-danger);
  margin-left: 6px;
}

.bar {
  margin-bottom: 6px;
}

.tools {
  margin-top: 14px;
  border-top: 1px dashed var(--jy-border);
  padding-top: 12px;
}

.tools-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--jy-text-regular);
  margin-bottom: 8px;
}

.tool {
  display: flex;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--jy-border-light);
}

.tool:last-child {
  border-bottom: none;
}

.tool-seq {
  flex: 0 0 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--jy-brand-soft);
  color: var(--jy-brand);
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.tool--running .tool-seq {
  background: #fdf3e2;
  color: var(--jy-warning);
}

.tool-body {
  flex: 1;
  min-width: 0;
}

.tool-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.tool-name {
  font-size: 13px;
  font-weight: 500;
  font-family: Consolas, 'Courier New', monospace;
}

.tool-duration,
.tool-rows {
  font-size: 12px;
  color: var(--jy-text-secondary);
}

.tool-args {
  font-size: 12px;
  color: var(--jy-text-secondary);
  margin-top: 3px;
  word-break: break-all;
}

.tool-summary {
  font-size: 12px;
  color: var(--jy-text-regular);
  margin-top: 3px;
  line-height: 1.6;
}

.finish-line {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  font-size: 12px;
  color: var(--jy-success);
}

.idle {
  padding: 18px 0 6px;
  color: var(--jy-text-secondary);
  font-size: 13px;
  line-height: 1.8;
}
</style>
