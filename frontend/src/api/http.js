/**
 * 统一 HTTP 客户端。
 *
 * 后端约定（docs/API.md）:
 *   - 成功响应直接返回业务字段，没有 code/message/data 外壳
 *   - 失败响应统一是 { "detail": "..." }
 *   - 登录态走 HttpOnly Cookie，前端不需要（也不能）读令牌
 *
 * 因此本模块只做三件事：拼查询串、归一化错误、把 401 抛给上层跳登录。
 */

const API_BASE = import.meta.env.VITE_API_BASE || ''

/** 业务错误：带上 HTTP 状态码，方便调用方区分 401/403/404。 */
export class ApiError extends Error {
  constructor(message, status, url) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.url = url
  }
}

export function buildQuery(params) {
  if (!params) return ''
  const usp = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    usp.append(key, String(value))
  })
  const qs = usp.toString()
  return qs ? `?${qs}` : ''
}

async function parseError(response) {
  let detail = `请求失败（HTTP ${response.status}）`
  try {
    const text = await response.text()
    if (text) {
      try {
        const data = JSON.parse(text)
        if (typeof data?.detail === 'string') detail = data.detail
        else if (data?.detail) detail = JSON.stringify(data.detail)
      } catch {
        detail = text.slice(0, 300)
      }
    }
  } catch {
    /* 读取响应体失败时保留默认提示 */
  }
  return detail
}

/**
 * @param {string} path  形如 /api/chat/ls
 * @param {object} [options]
 * @param {string} [options.method]
 * @param {object} [options.query]   查询参数
 * @param {any}    [options.body]    JSON 请求体
 * @param {FormData} [options.form]  表单请求体（附件上传）
 * @param {AbortSignal} [options.signal]
 */
export async function request(path, options = {}) {
  const { method = 'GET', query, body, form, signal, raw = false } = options
  const url = `${API_BASE}${path}${buildQuery(query)}`

  const init = {
    method,
    credentials: 'include',
    signal,
    headers: {},
  }

  if (form) {
    init.body = form
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }

  let response
  try {
    response = await fetch(url, init)
  } catch (err) {
    if (err?.name === 'AbortError') throw err
    throw new ApiError('无法连接到后端服务，请确认服务已启动', 0, url)
  }

  if (!response.ok) {
    throw new ApiError(await parseError(response), response.status, url)
  }

  if (raw) return response
  if (response.status === 204) return null

  const type = response.headers.get('content-type') || ''
  if (type.includes('application/json')) return response.json()
  return response.blob()
}

export const http = {
  get: (path, query, options = {}) => request(path, { ...options, method: 'GET', query }),
  post: (path, body, options = {}) => request(path, { ...options, method: 'POST', body }),
  del: (path, query, options = {}) => request(path, { ...options, method: 'DELETE', query }),
  raw: (path, options = {}) => request(path, { ...options, raw: true }),
}

/** 触发浏览器下载：优先沿用服务端 Content-Disposition 里的文件名。 */
export async function downloadFile(path, query, fallbackName = 'download') {
  const response = await http.raw(path, { query })
  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') || ''
  let filename = fallbackName
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  if (star) filename = decodeURIComponent(star[1])
  else if (plain) filename = plain[1]

  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(objectUrl)
  return filename
}
