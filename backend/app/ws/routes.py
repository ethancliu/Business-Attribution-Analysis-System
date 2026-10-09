# -*- coding: utf-8 -*-
"""WebSocket 接入点。

握手流程（需求 §12）:
    1. 前端先调用 POST /api/chat/ws-token 取得一次性令牌
    2. 用 ws://host/api/chat/ws/chat?websocket_token=xxx 建连
    3. 服务端校验令牌（未消费、未过期、归属一致、会话归属一致）
    4. 消费令牌（consumed_at），登记连接到会话分组
    5. 先回 connected，再补发该会话最近一轮的报文（连接晚到 / 页面刷新也能还原进度）
    6. 之后所有分析进度都由服务端主动推送

关闭码:
    1000 正常 / 4001 令牌无效或已消费 / 4003 无权限 / 1011 服务端异常
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.db import session_scope
from app.models import Conversation, WebsocketToken
from app.ws.manager import (
    CLOSE_FORBIDDEN,
    CLOSE_INVALID_TOKEN,
    CLOSE_NORMAL,
    CLOSE_SERVER_ERROR,
    manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

WS_PATH = "/api/chat/ws/chat"


def _extract_token(websocket: WebSocket) -> str | None:
    """令牌既支持 query 参数，也支持 Sec-WebSocket-Protocol 子协议头。"""
    token = websocket.query_params.get("websocket_token") or websocket.query_params.get("token")
    if token:
        return token.strip()
    proto = websocket.headers.get("sec-websocket-protocol")
    if proto:
        for part in proto.split(","):
            candidate = part.strip()
            if candidate.startswith("bearer."):
                return candidate[len("bearer."):]
    return None


def _pick_subprotocol(websocket: WebSocket) -> str | None:
    """只回选客户端真正提供过的子协议。

    RFC 6455 要求服务端不得选定客户端未提供的子协议，否则浏览器会直接断开；
    因此这里只有客户端提供了 bearer.<token> 时才回 "bearer"，否则不带子协议接受。
    """
    proto = websocket.headers.get("sec-websocket-protocol") or ""
    offered = [p.strip() for p in proto.split(",") if p.strip()]
    for candidate in offered:
        if candidate.startswith("bearer."):
            return candidate
    if "bearer" in offered:
        return "bearer"
    return None


@router.websocket(WS_PATH)
async def chat_socket(websocket: WebSocket) -> None:
    token = _extract_token(websocket)

    if not token:
        await websocket.close(code=CLOSE_INVALID_TOKEN, reason="缺少长连接令牌")
        return

    # ---- 校验令牌 ----
    try:
        with session_scope() as db:
            row = db.execute(
                select(WebsocketToken).where(WebsocketToken.token == token)
            ).scalar_one_or_none()

            if row is None:
                await websocket.close(code=CLOSE_INVALID_TOKEN, reason="令牌不存在")
                return
            if row.consumed_at is not None:
                await websocket.close(code=CLOSE_INVALID_TOKEN, reason="令牌已被使用")
                return
            if row.expires_at < datetime.now():
                await websocket.close(code=CLOSE_INVALID_TOKEN, reason="令牌已过期")
                return

            conv = db.get(Conversation, row.conversation_id)
            if conv is None or conv.user_id != row.user_id or conv.status == "deleted":
                await websocket.close(code=CLOSE_FORBIDDEN, reason="无权订阅该会话")
                return

            user_id = row.user_id
            conversation_id = row.conversation_id

            # 消费令牌：一次性，重连必须换新令牌
            row.consumed_at = datetime.now()
            db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("WebSocket 握手校验失败")
        await websocket.close(code=CLOSE_SERVER_ERROR, reason=f"服务端异常：{exc}")
        return

    # ---- 建立连接 ----
    await websocket.accept(subprotocol=_pick_subprotocol(websocket))
    conn = await manager.connect(websocket, conversation_id, user_id)

    try:
        await websocket.send_json({
            "type": "connected",
            "ts": datetime.now().isoformat(),
            "conversation_id": conversation_id,
            "user_id": user_id,
            "message": "长连接已建立，分析进度将实时推送",
        })

        # 补齐「连接晚于任务启动」和「分析中途刷新页面」两种情况：
        # 把该会话最近一轮的报文原样补发一遍（带 replayed 标记）
        await manager.replay(conn)

        while True:
            payload = await websocket.receive_json()
            msg_type = (payload or {}).get("type")

            if msg_type == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "ts": datetime.now().isoformat(),
                    "conversation_id": conversation_id,
                })
            elif msg_type == "subscribe":
                # 前端切换会话时无需重连，直接复用当前连接（会话已在握手时固定）
                await websocket.send_json({
                    "type": "subscribed",
                    "ts": datetime.now().isoformat(),
                    "conversation_id": conversation_id,
                })
            else:
                logger.debug("忽略客户端报文：%s", msg_type)

    except WebSocketDisconnect:
        logger.info("客户端断开：conversation=%s user=%s", conversation_id, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("WebSocket 异常：%s", exc)
    finally:
        manager.disconnect(conn)


# 供 main.py 参考的导出
__all__ = ["router", "WS_PATH", "CLOSE_NORMAL", "CLOSE_INVALID_TOKEN", "CLOSE_FORBIDDEN", "CLOSE_SERVER_ERROR"]
