/**
 * 对话与实时分析状态（消息流模块 + 实时进度模块）。
 *
 * 一次提问的完整链路：
 *   POST /api/chat/send 创建任务 -> WebSocket 推送 message_start / tool_start / ...
 *   -> message_delta 流式文本 -> result_ready -> done
 *
 * 八种报文的处理都集中在 handleEvent()，页面只需读 live 状态即可渲染进度面板。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import * as chatApi from '@/api/chat'
import { getTask, cancelTask } from '@/api/task'
import { AnalysisSocket, WS_STATE } from '@/ws/client'
import { TASK_TERMINAL } from '@/utils/constants'

function emptyLive() {
  return {
    taskId: null,
    userMessageId: null,
    assistantMessageId: null,
    scenario: '',
    stepTotal: 0,
    stepIndex: 0,
    progress: 0,
    currentStep: '',
    status: '',
    resultId: null,
    downloadUrl: '',
    errorMessage: '',
    startedAt: null,
    finishedAt: null,
    durationMs: null,
    tools: [],
    streaming: false,
    streamText: '',
    inputText: '',
    replayed: false,
  }
}

export const useChatStore = defineStore('chat', () => {
  const conversationId = ref(null)
  const messages = ref([])
  const loadingMessages = ref(false)
  const loadingMore = ref(false)
  const hasMore = ref(false)
  const nextBeforeSeq = ref(null)
  const sending = ref(false)
  const live = ref(emptyLive())
  const wsState = ref(WS_STATE.idle)
  const wsError = ref('')

  let socket = null

  const isAnalyzing = computed(
    () => live.value.streaming || (live.value.taskId && !TASK_TERMINAL.includes(live.value.status)),
  )
  const hasLiveData = computed(
    () => !!live.value.taskId && (live.value.tools.length > 0 || !!live.value.streamText),
  )

  // -------------------------------------------------------------------------
  // 历史消息
  // -------------------------------------------------------------------------

  /** 切换会话：清空并重新拉历史，随后建立长连接。 */
  async function open(targetId) {
    if (conversationId.value === targetId) return
    closeSocket()
    conversationId.value = targetId
    messages.value = []
    live.value = emptyLive()
    if (!targetId) return

    await loadMessages()
    await resumeLatestTask()
    connectSocket()
  }

  async function loadMessages() {
    if (!conversationId.value) return
    loadingMessages.value = true
    try {
      const data = await chatApi.listMessages(conversationId.value, { pageSize: 30 })
      // 后端按 seq_no 倒序返回，前端展示需要正序
      messages.value = (data.items || []).slice().reverse()
      hasMore.value = !!data.has_more
      nextBeforeSeq.value = data.next_before_seq ?? null
    } finally {
      loadingMessages.value = false
    }
  }

  /** 上滑加载更早的消息。 */
  async function loadMore() {
    if (!conversationId.value || !hasMore.value || loadingMore.value) return
    loadingMore.value = true
    try {
      const data = await chatApi.listMessages(conversationId.value, {
        pageSize: 30,
        beforeSeq: nextBeforeSeq.value,
      })
      const older = (data.items || []).slice().reverse()
      messages.value = [...older, ...messages.value]
      hasMore.value = !!data.has_more
      nextBeforeSeq.value = data.next_before_seq ?? null
    } finally {
      loadingMore.value = false
    }
  }

  /**
   * 页面刷新后可能有一个仍在跑的任务：先用任务详情把进度补上，
   * 随后建连时服务端还会补发整轮报文，界面不会落空。
   */
  async function resumeLatestTask() {
    const withTask = messages.value.filter((m) => m.task_id && m.role === 'assistant')
    const last = withTask[withTask.length - 1]
    if (!last) return
    try {
      const task = await getTask(last.task_id)
      applyTaskSnapshot(task, last)
    } catch {
      // 任务查询失败不影响历史浏览
    }
  }

  function applyTaskSnapshot(task, message) {
    live.value = {
      ...emptyLive(),
      taskId: task.task_id,
      assistantMessageId: message?.message_id ?? null,
      scenario: task.current_step?.replace(/^已识别场景：/, '') || '',
      stepTotal: task.step_total || 0,
      stepIndex: task.step_index || 0,
      progress: task.progress || 0,
      currentStep: task.current_step || '',
      status: task.task_status || '',
      resultId: task.result_id ?? null,
      errorMessage: task.error_message || '',
      startedAt: task.started_at || null,
      finishedAt: task.finished_at || null,
      durationMs: task.duration_ms ?? null,
      streaming: !TASK_TERMINAL.includes(task.task_status),
      tools: (task.tool_calls || []).map((t) => ({
        seq: t.seq,
        name: t.tool_name,
        args: t.tool_args || {},
        status: t.status,
        summary: t.summary || '',
        durationMs: t.duration_ms || 0,
        rows: null,
      })),
    }
  }

  // -------------------------------------------------------------------------
  // 长连接
  // -------------------------------------------------------------------------

  function connectSocket() {
    if (!conversationId.value) return
    closeSocket()
    wsError.value = ''
    socket = new AnalysisSocket({
      conversationId: conversationId.value,
      tokenProvider: () => chatApi.createWsToken(conversationId.value),
      onEvent: (payload) => {
        // 切换会话后旧连接的尾包可能迟到，按会话号过滤
        if (payload.conversation_id && payload.conversation_id !== conversationId.value) return
        handleEvent(payload)
      },
      onStateChange: (state, detail) => {
        wsState.value = state
        if (state === WS_STATE.error || state === WS_STATE.closed) {
          wsError.value = detail?.message || ''
        }
        if (state === WS_STATE.open) wsError.value = ''
      },
    })
    socket.connect()
  }

  /** 主动断开（离开会话或页面卸载时调用）。 */
  function closeSocket() {
    if (socket) {
      socket.close()
      socket = null
    }
    wsState.value = WS_STATE.closed
  }

  // -------------------------------------------------------------------------
  // 发送提问
  // -------------------------------------------------------------------------

  async function send(content, attachmentIds = []) {
    if (!conversationId.value) throw new Error('请先选择或新建会话')
    sending.value = true
    try {
      const res = await chatApi.sendMessage(conversationId.value, content, attachmentIds)
      live.value = {
        ...emptyLive(),
        taskId: res.task_id,
        userMessageId: res.user_message_id,
        assistantMessageId: res.assistant_message_id,
        inputText: content,
        status: res.task_status,
        streaming: true,
        startedAt: new Date().toISOString(),
      }
      // 用户消息与助手占位消息立即上屏，不等服务端报文
      messages.value = [
        ...messages.value,
        {
          message_id: res.user_message_id,
          seq_no: Number.MAX_SAFE_INTEGER - 1,
          role: 'user',
          message_type: 'text',
          content,
          attachments: [],
          created_at: res.created_at,
          task_id: null,
        },
        {
          message_id: res.assistant_message_id,
          seq_no: Number.MAX_SAFE_INTEGER,
          role: 'assistant',
          message_type: 'text',
          content: '',
          attachments: [],
          created_at: res.created_at,
          task_id: res.task_id,
        },
      ]
      if (!socket) connectSocket()
      return res
    } finally {
      sending.value = false
    }
  }

  async function cancelCurrent() {
    if (!live.value.taskId) return null
    const res = await cancelTask(live.value.taskId)
    live.value.status = res.task_status
    live.value.streaming = false
    return res
  }

  // -------------------------------------------------------------------------
  // 八种报文的处理（需求 §12）
  // -------------------------------------------------------------------------

  function handleEvent(payload) {
    const type = payload.type

    // 补发报文说明是「重连 / 晚到」，此时从零重建，避免与已有状态重复累加
    if (payload.replayed && type === 'message_start') {
      const keep = { userMessageId: live.value.userMessageId, assistantMessageId: live.value.assistantMessageId }
      live.value = { ...emptyLive(), ...keep, replayed: true }
    }

    switch (type) {
      case 'message_start':
        return onMessageStart(payload)
      case 'message_delta':
        return onMessageDelta(payload)
      case 'tool_start':
        return onToolStart(payload)
      case 'tool_finish':
        return onToolFinish(payload)
      case 'task_status':
        return onTaskStatus(payload)
      case 'result_ready':
        return onResultReady(payload)
      case 'error':
        return onError(payload)
      case 'done':
        return onDone(payload)
      default:
        return undefined
    }
  }

  function onMessageStart(p) {
    live.value.taskId = p.task_id
    live.value.scenario = p.scenario || ''
    live.value.stepTotal = p.step_total || 0
    live.value.assistantMessageId = p.message_id ?? live.value.assistantMessageId
    live.value.userMessageId = p.user_message_id ?? live.value.userMessageId
    live.value.inputText = p.input_text || live.value.inputText
    live.value.status = 'running'
    live.value.streaming = true
    live.value.startedAt = p.ts || live.value.startedAt
    live.value.streamText = ''
    live.value.tools = []
    live.value.progress = Math.max(live.value.progress, 2)
  }

  function onMessageDelta(p) {
    live.value.streamText += p.delta_text || ''
    // 同步写入对应助手消息，列表里就能看到逐字输出
    const target = findAssistantMessage(p.message_id || live.value.assistantMessageId)
    if (target) target.content = live.value.streamText
  }

  function onToolStart(p) {
    live.value.tools = [
      ...live.value.tools.filter((t) => t.seq !== p.tool_call_seq),
      {
        seq: p.tool_call_seq,
        name: p.tool_name,
        args: p.tool_args || {},
        status: 'running',
        summary: '',
        durationMs: 0,
        rows: null,
      },
    ]
  }

  function onToolFinish(p) {
    live.value.tools = live.value.tools.map((t) =>
      t.seq === p.tool_call_seq
        ? {
            ...t,
            name: p.tool_name || t.name,
            status: p.status || 'success',
            summary: p.tool_result_summary || '',
            durationMs: p.duration_ms || 0,
            rows: p.rows ?? null,
          }
        : t,
    )
  }

  function onTaskStatus(p) {
    if (p.task_id && p.task_id !== live.value.taskId) live.value.taskId = p.task_id
    if (typeof p.progress === 'number') live.value.progress = p.progress
    if (typeof p.step_index === 'number') live.value.stepIndex = p.step_index
    if (typeof p.step_total === 'number' && p.step_total) live.value.stepTotal = p.step_total
    if (p.current_step) live.value.currentStep = p.current_step
    if (p.task_status) live.value.status = p.task_status
  }

  function onResultReady(p) {
    live.value.resultId = p.result_id ?? null
    live.value.downloadUrl = p.download_url || ''
    live.value.progress = 100
  }

  function onError(p) {
    live.value.errorMessage = p.error_message || '分析执行失败'
    live.value.status = 'failed'
    live.value.streaming = false
  }

  function onDone(p) {
    live.value.status = p.task_status || 'success'
    live.value.streaming = false
    live.value.finishedAt = p.finished_at || null
    if (typeof p.duration_ms === 'number') live.value.durationMs = p.duration_ms
    live.value.progress = 100
    // 收尾后以服务端落库的正文为准，保证刷新前后内容一致
    refreshAssistantMessage()
  }

  function findAssistantMessage(messageId) {
    if (messageId) {
      const byId = messages.value.find((m) => m.message_id === messageId)
      if (byId) return byId
    }
    return messages.value.find((m) => m.role === 'assistant' && m.task_id === live.value.taskId)
  }

  async function refreshAssistantMessage() {
    if (!conversationId.value) return
    try {
      const data = await chatApi.listMessages(conversationId.value, { pageSize: 4 })
      const latest = (data.items || []).filter((m) => m.message_id === live.value.assistantMessageId)
      if (!latest.length) return
      const fresh = latest[0]
      const target = findAssistantMessage(fresh.message_id)
      if (target && fresh.content) target.content = fresh.content
    } catch {
      // 拉取失败就沿用流式文本，不影响主流程
    }
  }

  function resetLive() {
    live.value = emptyLive()
  }

  function clear() {
    closeSocket()
    conversationId.value = null
    messages.value = []
    hasMore.value = false
    nextBeforeSeq.value = null
    live.value = emptyLive()
  }

  return {
    conversationId,
    messages,
    loadingMessages,
    loadingMore,
    hasMore,
    nextBeforeSeq,
    sending,
    live,
    wsState,
    wsError,
    isAnalyzing,
    hasLiveData,
    open,
    loadMessages,
    loadMore,
    resumeLatestTask,
    connectSocket,
    closeSocket,
    send,
    cancelCurrent,
    handleEvent,
    resetLive,
    clear,
  }
})
