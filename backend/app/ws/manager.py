# -*- coding: utf-8 -*-
"""会话级 WebSocket 连接管理。

关键设计——跨线程推送:
    分析任务在**后台线程**中执行（避免阻塞事件循环），而 WebSocket 发送是异步的。
    因此本模块在启动时捕获主事件循环，任务线程通过
    `asyncio.run_coroutine_threadsafe()` 把报文投递回主循环发送。

关键设计——迟到补发:
    一次分析只跑几百毫秒，客户端完全可能「任务已启动、连接才建立」，
    或分析中途刷新页面。因此每个会话缓存最近一轮的全部报文，
    新连接接入时先补发一遍（带 replayed 标记），前端据此立即还原完整进度。

关闭码约定（docs/API.md §10.1）:
    1000 正常关闭 / 4001 令牌无效 / 4003 无权限 / 1011 服务端异常
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

CLOSE_NORMAL = 1000
CLOSE_INVALID_TOKEN = 4001
CLOSE_FORBIDDEN = 4003
CLOSE_SERVER_ERROR = 1011

# 单个会话保留的报文上限（一轮分析约 30 条，留足冗余）
BUFFER_MAX = 400
# 缓存报文的会话数上限，防止长期运行内存无界增长
BUFFER_MAX_CONVERSATIONS = 200


class Connection:
    """单条 WebSocket 连接。"""

    __slots__ = ("ws", "conversation_id", "user_id", "connected_at", "sent_count")

    def __init__(self, ws: WebSocket, conversation_id: int, user_id: int) -> None:
        self.ws = ws
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.connected_at = datetime.now()
        self.sent_count = 0


class ConnectionManager:
    """按 conversation_id 分组的连接池。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._connections: dict[int, list[Connection]] = defaultdict(list)
        self._buffers: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._total_connections = 0

    # ------------------------------------------------------------- 生命周期
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """由应用启动钩子调用，捕获主事件循环。"""
        self._loop = loop
        logger.info("WebSocket 管理器已绑定事件循环")

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    async def connect(self, ws: WebSocket, conversation_id: int, user_id: int) -> Connection:
        conn = Connection(ws, conversation_id, user_id)
        with self._lock:
            self._connections[conversation_id].append(conn)
            self._total_connections += 1
        logger.info("WebSocket 已连接: conversation=%s user=%s (当前 %s 条)", conversation_id, user_id, self.count(conversation_id))
        return conn

    def disconnect(self, conn: Connection) -> None:
        with self._lock:
            bucket = self._connections.get(conn.conversation_id)
            if not bucket:
                return
            self._connections[conn.conversation_id] = [c for c in bucket if c is not conn]
            if not self._connections[conn.conversation_id]:
                self._connections.pop(conn.conversation_id, None)
        logger.info("WebSocket 已断开: conversation=%s user=%s", conn.conversation_id, conn.user_id)

    # ------------------------------------------------------------- 查询
    def count(self, conversation_id: int | None = None) -> int:
        with self._lock:
            if conversation_id is None:
                return sum(len(v) for v in self._connections.values())
            return len(self._connections.get(conversation_id, []))

    @property
    def total_connections(self) -> int:
        return self._total_connections

    def bound_conversations(self) -> list[int]:
        with self._lock:
            return sorted(self._connections.keys())

    # ------------------------------------------------------------- 发送
    async def send_to_conversation(self, conversation_id: int, payload: dict[str, Any]) -> int:
        """向订阅了某会话的全部连接推送报文，返回成功条数。"""
        with self._lock:
            targets = list(self._connections.get(conversation_id, []))
        if not targets:
            return 0

        ok = 0
        for conn in targets:
            try:
                await conn.ws.send_json(payload)
                conn.sent_count += 1
                ok += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("WebSocket 推送失败，移除连接 conversation=%s: %s", conversation_id, exc)
                self.disconnect(conn)
        return ok

    def push(self, conversation_id: int, payload: dict[str, Any]) -> int:
        """**线程安全**推送入口，供后台分析任务线程调用。

        无论有没有在线连接，报文都会先进入该会话的回放缓存，
        这样连接晚到的客户端也能补齐整轮进度。

        返回已排入事件循环的连接数；无事件循环或无线程上下文时返回 0。
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            logger.debug("事件循环不可用，跳过 WebSocket 推送")
            return 0

        with self._lock:
            self._remember(conversation_id, payload)
            n = len(self._connections.get(conversation_id, []))
        if n == 0:
            return 0

        try:
            asyncio.run_coroutine_threadsafe(self.send_to_conversation(conversation_id, payload), loop)
        except RuntimeError as exc:
            logger.warning("投递 WebSocket 报文失败: %s", exc)
            return 0
        return n

    # ------------------------------------------------------------- 回放缓存
    def _remember(self, conversation_id: int, payload: dict[str, Any]) -> None:
        """把报文写入回放缓存（调用方须持有锁）。"""
        if conversation_id not in self._buffers and len(self._buffers) >= BUFFER_MAX_CONVERSATIONS:
            self._buffers.pop(next(iter(self._buffers)), None)
        buf = self._buffers[conversation_id]
        # message_start 代表新一轮分析开始，此时丢弃上一轮的缓存
        if payload.get("type") == "message_start":
            buf.clear()
        buf.append(payload)
        if len(buf) > BUFFER_MAX:
            del buf[:-BUFFER_MAX]

    async def replay(self, conn: Connection) -> int:
        """把该会话最近一轮的报文补发给刚建立的连接，返回补发条数。

        客户端可能晚于任务启动才连上，或页面在分析中途刷新；
        补发让其立即还原出完整进度，而不是空等到下一轮分析。
        """
        with self._lock:
            buffered = list(self._buffers.get(conn.conversation_id, []))
        if not buffered:
            return 0

        sent = 0
        for payload in buffered:
            try:
                await conn.ws.send_json({**payload, "replayed": True})
                conn.sent_count += 1
                sent += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("补发报文失败，移除连接 conversation=%s: %s", conn.conversation_id, exc)
                self.disconnect(conn)
                break
        if sent:
            logger.info("已向 conversation=%s 补发 %s 条本轮报文", conn.conversation_id, sent)
        return sent

    def buffered_count(self, conversation_id: int) -> int:
        with self._lock:
            return len(self._buffers.get(conversation_id, []))

    async def close_all(self, code: int = CLOSE_NORMAL, reason: str = "server_shutdown") -> None:
        with self._lock:
            all_conns = [c for bucket in self._connections.values() for c in bucket]
            self._connections.clear()
        for conn in all_conns:
            try:
                await conn.ws.close(code=code, reason=reason)
            except Exception:  # noqa: BLE001
                pass
        logger.info("已关闭全部 WebSocket 连接：%s 条", len(all_conns))


manager = ConnectionManager()
