/** 分析任务接口（docs/API.md §8）。 */

import { http } from './http'

export function getTask(taskId) {
  return http.get(`/api/tasks/${taskId}`)
}

/**
 * 任务列表。
 * 后端支持 conversation_id / status / limit 三个查询参数，返回 { total, items }。
 * 不传 conversation_id 时取当前用户的全部任务。
 */
export function listTasks({ conversationId, status, limit = 50 } = {}) {
  return http.get('/api/tasks', {
    conversation_id: conversationId,
    status,
    limit,
  })
}

export function cancelTask(taskId) {
  return http.post(`/api/tasks/${taskId}/cancel`)
}
