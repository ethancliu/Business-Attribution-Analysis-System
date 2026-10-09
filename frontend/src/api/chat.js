/** 会话与消息接口（docs/API.md §4 / §5 / §6）。 */

import { http } from './http'

export function createConversation(title) {
  return http.post('/api/chat/create', { title: title || null })
}

export function updateConversation(conversationId, title) {
  return http.post('/api/chat/update', { conversation_id: conversationId, title })
}

export function deleteConversations(conversationIds) {
  return http.post('/api/chat/delete', { conversation_ids: conversationIds })
}

/** 会话列表。status 支持 active / archived；keyword 按标题模糊匹配。 */
export function listConversations({ status, keyword } = {}) {
  return http.get('/api/chat/ls', { status, keyword })
}

/**
 * 会话历史消息（游标分页）：按 seq_no 倒序取，返回 items / has_more / next_before_seq。
 * 前端展示时需自行 reverse 成正序。
 */
export function listMessages(conversationId, { pageSize = 20, beforeSeq } = {}) {
  return http.get(`/api/chat/ls/${conversationId}`, {
    page_size: pageSize,
    before_seq: beforeSeq,
  })
}

/** 发送提问，触发后台分析任务；返回 task_id，随后由 WebSocket 推送进度。 */
export function sendMessage(conversationId, content, attachmentIds = []) {
  return http.post('/api/chat/send', {
    conversation_id: conversationId,
    content,
    attachment_ids: attachmentIds,
  })
}

/** 申请一次性长连接令牌（每次建连/重连都要重新申请）。 */
export function createWsToken(conversationId) {
  return http.post('/api/chat/ws-token', { conversation_id: conversationId })
}
