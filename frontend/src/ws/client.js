/**
 * 分析长连接客户端。
 *
 * 后端约定（docs/API.md §10）:
 *   - 握手令牌是一次性的：每次（重）连都必须先调 POST /api/chat/ws-token 换新令牌
 *   - 服务端在令牌被消费后才 accept，重放同一个令牌会被 4001 关闭
 *   - 连接建立后服务端先回 connected，再把该会话最近一轮报文补发一遍（带 replayed 标记）
 *   - 报文是平铺结构：{ type, ts, task_id, conversation_id, ...业务字段 }
 *
 * 因此本模块负责：取令牌 -> 建连 -> 心跳 -> 断线自动重连（换新令牌）-> 把报文交给上层。
 * 这里刻意不依赖 Vue，方便单独测试。
 */

const HEARTBEAT_MS = 25000
const MAX_BACKOFF_MS = 15000

/** 连接状态机。 */
export const WS_STATE = {
  idle: 'idle',
  connecting: 'connecting',
  open: 'open',
  reconnecting: 'reconnecting',
  closed: 'closed',
  error: 'error',
}

export function resolveWsUrl(token) {
  const base = import.meta.env.VITE_WS_BASE
  if (base) {
    return `${base.replace(/\/$/, '')}/api/chat/ws/chat?websocket_token=${encodeURIComponent(token)}`
  }
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${scheme}//${window.location.host}/api/chat/ws/chat?websocket_token=${encodeURIComponent(token)}`
}

export class AnalysisSocket {
  /**
   * @param {object} options
   * @param {number} options.conversationId
   * @param {() => Promise<{websocket_token: string}>} options.tokenProvider 取一次性令牌
   * @param {(payload: object) => void} [options.onEvent]      收到任意报文
   * @param {(state: string, detail?: object) => void} [options.onStateChange]
   * @param {boolean} [options.autoReconnect]
   */
  constructor({ conversationId, tokenProvider, onEvent, onStateChange, autoReconnect = true }) {
    this.conversationId = conversationId
    this.tokenProvider = tokenProvider
    this.onEvent = onEvent || (() => {})
    this.onStateChange = onStateChange || (() => {})
    this.autoReconnect = autoReconnect

    this.ws = null
    this.state = WS_STATE.idle
    this.closedByUser = false
    this.attempts = 0
    this.heartbeatTimer = null
    this.reconnectTimer = null
    this.connectPromise = null
  }

  _setState(state, detail) {
    this.state = state
    this.onStateChange(state, detail)
  }

  /** 建立连接（幂等：已在连接中或已连上时直接返回）。 */
  connect() {
    if (this.state === WS_STATE.open) return Promise.resolve()
    if (this.connectPromise) return this.connectPromise

    this.closedByUser = false
    this._setState(WS_STATE.connecting)

    this.connectPromise = this._open()
      .catch((err) => {
        this._setState(WS_STATE.error, { message: err?.message || '长连接建立失败' })
        this._scheduleReconnect()
      })
      .finally(() => {
        this.connectPromise = null
      })

    return this.connectPromise
  }

  async _open() {
    const { websocket_token: token } = await this.tokenProvider()
    if (this.closedByUser) return

    const url = resolveWsUrl(token)
    const ws = new WebSocket(url)
    this.ws = ws

    ws.onopen = () => {
      this.attempts = 0
      this._setState(WS_STATE.open)
      this._startHeartbeat()
    }

    ws.onmessage = (event) => {
      let payload
      try {
        payload = JSON.parse(event.data)
      } catch {
        return
      }
      if (!payload || typeof payload.type !== 'string') return
      if (payload.type === 'pong') return
      this.onEvent(payload)
    }

    ws.onerror = () => {
      // 具体原因由 onclose 统一处理（浏览器不暴露握手失败细节）
    }

    ws.onclose = (event) => {
      this._stopHeartbeat()
      this.ws = null
      if (this.closedByUser) {
        this._setState(WS_STATE.closed)
        return
      }
      this._setState(WS_STATE.closed, { code: event.code, reason: event.reason })
      // 4001 令牌无效 / 4003 无权限：换新令牌重试仍可能失败，但重试一次成本很低
      this._scheduleReconnect(event.code)
    }
  }

  _startHeartbeat() {
    this._stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, HEARTBEAT_MS)
  }

  _stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  _scheduleReconnect(code) {
    if (!this.autoReconnect || this.closedByUser) return
    if (this.reconnectTimer) return

    // 4003 是权限问题（例如会话已被删除），重连只会一直失败，直接放弃
    if (code === 4003) return

    this.attempts += 1
    const delay = Math.min(1000 * 2 ** (this.attempts - 1), MAX_BACKOFF_MS)
    this._setState(WS_STATE.reconnecting, { attempt: this.attempts, delay })
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }

  send(payload) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload))
      return true
    }
    return false
  }

  /** 主动关闭：不再自动重连。 */
  close() {
    this.closedByUser = true
    this._stopHeartbeat()
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      try {
        this.ws.close(1000, 'client_close')
      } catch {
        /* 忽略关闭异常 */
      }
      this.ws = null
    }
    this._setState(WS_STATE.closed)
  }

  get isOpen() {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN
  }
}
