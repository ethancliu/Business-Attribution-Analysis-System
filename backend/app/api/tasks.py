# -*- coding: utf-8 -*-
"""分析任务接口：详情 / 列表 / 取消。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models import User
from app.services import chat as chat_service
from app.services import conversation as conversation_service
from app.services import task as task_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


@router.get("/api/tasks/{task_id}", summary="获取任务详情（含工具调用链与进度）")
def task_detail(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    task = task_service.get_owned(db, user, task_id)
    return task_service.detail_dict(db, task)


@router.get("/api/tasks", summary="获取任务列表")
def task_list(
    conversation_id: int | None = Query(default=None, description="按会话过滤"),
    status: str | None = Query(
        default=None,
        description="按任务状态过滤：queued / running / success / failed / cancelled",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if conversation_id is not None:
        conv = conversation_service.get_owned(db, user, conversation_id)
        rows = task_service.list_for_conversation(db, conv.id, limit=limit, status=status)
    else:
        rows = task_service.list_for_user(db, user.id, limit=limit, status=status)

    return {"total": len(rows), "items": [task_service.list_dict(db, t) for t in rows]}


@router.post("/api/tasks/{task_id}/cancel", summary="取消分析任务")
def cancel_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return chat_service.cancel(db, user, task_id)
