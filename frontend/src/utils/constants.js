/**
 * 枚举字典：后端返回的都是英文枚举值，前端统一在这里映射成中文与配色。
 * 需求 §12 的八种长连接报文类型也在这里登记，供进度面板与帮助页复用。
 */

export const TASK_STATUS = {
  queued: { label: '排队中', type: 'info' },
  running: { label: '分析中', type: 'primary' },
  success: { label: '已完成', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'warning' },
}

export const TASK_TERMINAL = ['success', 'failed', 'cancelled']

export function taskStatusMeta(status) {
  return TASK_STATUS[status] || { label: status || '未知', type: 'info' }
}

export const CONVERSATION_STATUS = {
  active: { label: '进行中', type: 'success' },
  archived: { label: '已归档', type: 'info' },
  deleted: { label: '已删除', type: 'danger' },
}

export const MESSAGE_ROLE = {
  user: { label: '我', type: 'primary' },
  assistant: { label: '分析助手', type: 'success' },
  tool: { label: '工具', type: 'info' },
  system: { label: '系统', type: 'warning' },
}

export const MESSAGE_TYPE = {
  text: '文本',
  tool_call: '工具调用',
  tool_result: '工具结果',
  error: '错误',
}

export const PARSE_STATUS = {
  pending: { label: '待解析', type: 'info' },
  parsing: { label: '解析中', type: 'primary' },
  success: { label: '已解析', type: 'success' },
  failed: { label: '解析失败', type: 'danger' },
}

export function parseStatusMeta(status, fallbackText) {
  if (fallbackText) {
    const meta = PARSE_STATUS[status] || { label: fallbackText, type: 'info' }
    return { ...meta, label: fallbackText }
  }
  return PARSE_STATUS[status] || { label: status || '未知', type: 'info' }
}

/** 证据来源类型（需求 §13 证据链标准字段 source_type）。 */
export const SOURCE_TYPE = {
  database: { label: '业务数据库', color: '#4b6bfb' },
  file: { label: '工作区文件', color: '#17a673' },
  search: { label: '文本检索', color: '#e6a23c' },
  shell: { label: '脚本执行', color: '#8a91a3' },
  attachment: { label: '上传附件', color: '#9b59d0' },
  knowledge: { label: '知识库', color: '#0ea5b7' },
}

export function sourceTypeMeta(type) {
  return SOURCE_TYPE[type] || { label: type || '未知来源', color: '#8a91a3' }
}

/** 置信度分档：>=0.8 高、>=0.6 中、其余低。 */
export function confidenceLevel(value) {
  const num = Number(value)
  if (Number.isNaN(num)) return { label: '未知', type: 'info', percent: 0 }
  if (num >= 0.8) return { label: '高', type: 'success', percent: Math.round(num * 100) }
  if (num >= 0.6) return { label: '中', type: 'warning', percent: Math.round(num * 100) }
  return { label: '低', type: 'danger', percent: Math.round(num * 100) }
}

export const LOG_TYPE = {
  lifecycle: '生命周期',
  tool: '工具调用',
  database: '数据库',
  file: '文件',
  error: '错误',
  llm: '模型推理',
}

export function logTypeLabel(type) {
  return LOG_TYPE[type] || type || '其他'
}

export const LOG_LEVEL_TYPE = {
  DEBUG: 'info',
  INFO: 'info',
  WARN: 'warning',
  WARNING: 'warning',
  ERROR: 'danger',
  CRITICAL: 'danger',
}

/** 需求 §12：服务端 -> 客户端的八种报文类型。 */
export const WS_MESSAGE_TYPES = [
  { type: 'message_start', label: '分析开始', desc: '识别场景、步骤总数，前端据此开启流式气泡' },
  { type: 'message_delta', label: '文本增量', desc: '流式思考文本，逐段追加到当前助手消息' },
  { type: 'tool_start', label: '工具开始', desc: '某次工具调用的开始，展示工具名与入参' },
  { type: 'tool_finish', label: '工具结束', desc: '工具执行结果摘要、行数、耗时' },
  { type: 'task_status', label: '状态变更', desc: '任务状态、当前步骤、进度百分比' },
  { type: 'result_ready', label: '结果就绪', desc: '六大模块结果落库，携带 result_id 与下载地址' },
  { type: 'error', label: '执行失败', desc: '任务失败时的错误信息与出错阶段' },
  { type: 'done', label: '本轮结束', desc: '终态收尾，前端据此收口并放开输入' },
]

export const ROLE_LABEL = {
  analyst: '分析人员',
  admin: '系统管理员',
}

export function roleLabel(role) {
  return ROLE_LABEL[role] || role || '未知角色'
}

/** 演示场景的推荐提问，登录页与工作台空态共用。 */
export const DEMO_QUESTIONS = [
  '美妆个护类目点击率腰斩，从 4.2% 掉到 2.1%，问题出在哪？',
  '信息流渠道 ROAS 从 5.9 掉到 1.6，投放预算没变，问题出在哪？',
  '用户主要在抱怨什么？差评有没有集中爆发的点？',
  '我的商品页转化率最近掉得厉害，帮我看看是什么原因？',
  '9 月下半月整体 GMV 环比下滑，是哪些因素导致的？',
  '这次促销活动的效果为什么不如预期？',
]
