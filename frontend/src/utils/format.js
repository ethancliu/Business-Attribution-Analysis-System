/** 展示层格式化工具：时间、体积、耗时、文本截断。 */

function pad(n) {
  return String(n).padStart(2, '0')
}

export function toDate(value) {
  if (!value) return null
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/** 2026-10-08 14:35 */
export function formatDateTime(value) {
  const d = toDate(value)
  if (!d) return '—'
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 14:35:01 */
export function formatTime(value) {
  const d = toDate(value)
  if (!d) return '—'
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 刚刚 / 5 分钟前 / 3 小时前 / 2 天前 / 具体日期 */
export function formatRelative(value) {
  const d = toDate(value)
  if (!d) return '—'
  const diff = Date.now() - d.getTime()
  if (diff < 0) return formatDateTime(value)
  const minute = 60 * 1000
  const hour = 60 * minute
  const day = 24 * hour
  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 7 * day) return `${Math.floor(diff / day)} 天前`
  return formatDateTime(value)
}

export function formatBytes(bytes) {
  const num = Number(bytes)
  if (!num || num < 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = num
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i += 1
  }
  return `${value >= 100 || i === 0 ? Math.round(value) : value.toFixed(1)} ${units[i]}`
}

export function formatDuration(ms) {
  const num = Number(ms)
  if (!num || num < 0) return '—'
  if (num < 1000) return `${Math.round(num)} ms`
  if (num < 60 * 1000) return `${(num / 1000).toFixed(1)} s`
  const minutes = Math.floor(num / 60000)
  const seconds = Math.round((num % 60000) / 1000)
  return `${minutes} 分 ${seconds} 秒`
}

export function formatUptime(seconds) {
  const num = Math.floor(Number(seconds) || 0)
  const day = Math.floor(num / 86400)
  const hour = Math.floor((num % 86400) / 3600)
  const minute = Math.floor((num % 3600) / 60)
  if (day) return `${day} 天 ${hour} 小时`
  if (hour) return `${hour} 小时 ${minute} 分`
  if (minute) return `${minute} 分`
  return `${num} 秒`
}

export function truncate(text, len = 60) {
  const flat = String(text ?? '').replace(/\s+/g, ' ').trim()
  return flat.length > len ? `${flat.slice(0, len)}…` : flat
}

/** 把 { a: 1, b: 'x' } 渲染成紧凑的一行入参，用于工具调用展示。 */
export function formatArgs(args) {
  if (!args || typeof args !== 'object') return ''
  const parts = Object.entries(args)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => {
      const text = typeof v === 'string' ? v : JSON.stringify(v)
      return `${k}=${truncate(text, 40)}`
    })
  return parts.join('  ')
}

export function formatPercent(value) {
  const num = Number(value)
  if (Number.isNaN(num)) return '—'
  return `${Math.round(num)}%`
}
