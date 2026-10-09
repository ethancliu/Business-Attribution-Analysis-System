# -*- coding: utf-8 -*-
"""会话与消息接口：新建 / 删除 / 改名 / 列表 / 历史 / 发送提问 / 长连接令牌。"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.runtime_config import runtime_config
from app.models import User, WebsocketToken
from app.schemas import (
    ConversationCreateRequest,
    ConversationDeleteRequest,
    ConversationUpdateRequest,
    SendMessageRequest,
    WsTokenRequest,
)
from app.services import chat as chat_service
from app.services import conversation as conversation_service
from app.services import message as message_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------

@router.post("/api/chat/create", summary="新建会话")
def create_conversation(
    payload: ConversationCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = conversation_service.create(db, user, payload.title)
    return {
        "conversation_id": conv.id,
        "title": conv.title,
        "status": conv.status,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
    }


@router.post("/api/chat/delete", summary="批量删除会话（级联删除关联数据与文件目录）")
def delete_conversations(
    payload: ConversationDeleteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return conversation_service.delete_many(db, user, payload.conversation_ids)


@router.post("/api/chat/update", summary="修改会话名称")
def update_conversation(
    payload: ConversationUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = conversation_service.update_title(db, user, payload.conversation_id, payload.title)
    return {
        "conversation_id": conv.id,
        "title": conv.title,
        "status": conv.status,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
    }


@router.get("/api/chat/ls", summary="获取会话列表")
def list_conversations(
    status_filter: str | None = Query(default=None, alias="status"),
    keyword: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items = conversation_service.list_for_user(db, user, status_filter=status_filter, keyword=keyword)
    return {"total": len(items), "items": items}


@router.get("/api/chat/ls/{conversation_id}", summary="获取会话历史消息")
def conversation_history(
    conversation_id: int,
    page_size: int = Query(default=20, ge=1, le=100),
    before_seq: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = conversation_service.get_owned(db, user, conversation_id)
    data = message_service.history(db, conv.id, page_size=page_size, before_seq=before_seq)
    data["title"] = conv.title
    data["status"] = conv.status
    return data


# ---------------------------------------------------------------------------
# 发送提问
# ---------------------------------------------------------------------------

@router.post("/api/chat/send", summary="发送提问消息并触发分析任务")
def send_message(
    payload: SendMessageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return chat_service.send_message(
        db,
        user,
        payload.conversation_id,
        payload.content,
        payload.attachment_ids,
    )


# ---------------------------------------------------------------------------
# 长连接令牌
# ---------------------------------------------------------------------------

@router.post("/api/chat/ws-token", summary="获取长连接令牌（一次性）")
def ws_token(
    payload: WsTokenRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = conversation_service.get_owned(db, user, payload.conversation_id)

    ttl = runtime_config.get_int("websocket.token_ttl_sec", 300)
    token = f"ws_{secrets.token_urlsafe(32)}"
    expires_at = datetime.now() + timedelta(seconds=ttl)

    row = WebsocketToken(
        user_id=user.id,
        conversation_id=conv.id,
        token=token,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()

    logger.info("为用户 %s 签发会话 #%s 的长连接令牌（%s 秒有效）", user.username, conv.id, ttl)
    return {
        "websocket_token": token,
        "expires_in": ttl,
        "expires_at": expires_at.isoformat(),
        "conversation_id": conv.id,
    }
