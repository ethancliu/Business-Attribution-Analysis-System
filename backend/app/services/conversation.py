# -*- coding: utf-8 -*-
"""会话服务：新增 / 查询 / 更新 / 删除 / 状态管理 / 用户会话隔离。"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import HTTPException, status as http_status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.paths import cleanup_conversation_dirs
from app.models import (
    AnalysisResult,
    AnalysisTask,
    Attachment,
    ContextSummary,
    Conversation,
    Message,
    TaskLog,
    User,
    WebsocketToken,
)

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "新的分析会话"
PREVIEW_LEN = 60


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def get_owned(db: Session, user: User, conversation_id: int, *, allow_deleted: bool = False) -> Conversation:
    """取出属于当前用户的会话；不存在或越权一律返回 404（不泄露他人会话是否存在）。"""
    conv = db.execute(select(Conversation).where(Conversation.id == conversation_id)).scalar_one_or_none()
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="会话不存在或无权访问")
    if not allow_deleted and conv.status == "deleted":
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="会话已删除")
    return conv


def list_for_user(
    db: Session,
    user: User,
    *,
    status_filter: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    """会话列表，按 last_message_at 倒序（无消息的排最后，按创建时间倒序）。"""
    stmt = select(Conversation).where(Conversation.user_id == user.id)

    if status_filter:
        stmt = stmt.where(Conversation.status == status_filter)
    else:
        stmt = stmt.where(Conversation.status.in_(("active", "archived")))

    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(Conversation.title.like(like))

    # MySQL 不支持 NULLS LAST；DESC 排序时 NULL 天然排在最后，与需求一致
    stmt = stmt.order_by(
        Conversation.last_message_at.desc(),
        Conversation.created_at.desc(),
        Conversation.id.desc(),
    )
    convs = db.execute(stmt).scalars().all()
    if not convs:
        return []

    conv_ids = [c.id for c in convs]

    # 消息数
    counts = dict(
        db.execute(
            select(Message.conversation_id, func.count(Message.id))
            .where(Message.conversation_id.in_(conv_ids))
            .group_by(Message.conversation_id)
        ).all()
    )

    # 最后一条消息预览：一次性按会话取最大 seq_no
    last_seq_rows = db.execute(
        select(Message.conversation_id, func.max(Message.seq_no))
        .where(Message.conversation_id.in_(conv_ids))
        .group_by(Message.conversation_id)
    ).all()
    preview: dict[int, str] = {}
    for conv_id, max_seq in last_seq_rows:
        if max_seq is None:
            continue
        row = db.execute(
            select(Message.content, Message.role, Message.message_type)
            .where(Message.conversation_id == conv_id, Message.seq_no == max_seq)
            .limit(1)
        ).first()
        if row:
            text = (row[0] or "").replace("\n", " ").strip()
            if row[1] == "tool" or row[2] in ("tool_call", "tool_result"):
                text = f"[工具] {text}"
            preview[conv_id] = text[:PREVIEW_LEN] + ("…" if len(text) > PREVIEW_LEN else "")

    return [
        {
            "conversation_id": c.id,
            "title": c.title,
            "status": c.status,
            "last_message_at": _iso(c.last_message_at),
            "created_at": _iso(c.created_at),
            "message_count": int(counts.get(c.id, 0)),
            "last_message_preview": preview.get(c.id),
        }
        for c in convs
    ]


# ---------------------------------------------------------------------------
# 新增 / 更新
# ---------------------------------------------------------------------------

def create(db: Session, user: User, title: str | None) -> Conversation:
    clean = (title or "").strip() or DEFAULT_TITLE
    conv = Conversation(user_id=user.id, title=clean[:255], status="active")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    logger.info("用户 %s 创建会话 #%s「%s」", user.username, conv.id, conv.title)
    return conv


def update_title(db: Session, user: User, conversation_id: int, title: str) -> Conversation:
    conv = get_owned(db, user, conversation_id)
    conv.title = title.strip()[:255]
    db.commit()
    db.refresh(conv)
    logger.info("会话 #%s 重命名为「%s」", conv.id, conv.title)
    return conv


def touch_last_message(db: Session, conversation_id: int, when: datetime | None = None) -> None:
    """更新会话的最后消息时间（不提交，由调用方统一提交）。"""
    conv = db.get(Conversation, conversation_id)
    if conv is not None:
        conv.last_message_at = when or datetime.now()


# ---------------------------------------------------------------------------
# 删除（软删除会话 + 硬删除全部关联数据 + 清理物理目录）
# ---------------------------------------------------------------------------

def delete_many(db: Session, user: User, conversation_ids: list[int]) -> dict:
    """批量删除会话。

    级联范围（需求 §6.3）：
        消息记录、附件记录、任务记录（含任务日志）、分析结果记录、上下文摘要记录、
        长连接令牌，以及 uploads/exports/workspace 三个物理目录。
    """
    # 去重并只保留属于当前用户的会话
    wanted = list(dict.fromkeys(conversation_ids))
    owned = db.execute(
        select(Conversation).where(Conversation.id.in_(wanted), Conversation.user_id == user.id)
    ).scalars().all()
    owned_ids = [c.id for c in owned]

    if not owned_ids:
        return {"deleted": 0, "conversation_ids": [], "removed_dirs": [], "removed_files": 0, "freed_bytes": 0}

    logger.info("用户 %s 删除会话 %s，开始级联清理", user.username, owned_ids)

    # --- 数据库级联（显式按依赖顺序删除，避免依赖外层 FK 行为）---
    # 1) 任务日志 -> 2) 分析结果 -> 3) 分析任务
    task_ids = db.execute(
        select(AnalysisTask.id).where(AnalysisTask.conversation_id.in_(owned_ids))
    ).scalars().all()
    if task_ids:
        db.execute(delete(TaskLog).where(TaskLog.task_id.in_(task_ids)))
    db.execute(delete(AnalysisResult).where(AnalysisResult.conversation_id.in_(owned_ids)))
    db.execute(delete(AnalysisTask).where(AnalysisTask.conversation_id.in_(owned_ids)))

    # 4) 附件 -> 5) 消息
    db.execute(delete(Attachment).where(Attachment.conversation_id.in_(owned_ids)))
    db.execute(delete(Message).where(Message.conversation_id.in_(owned_ids)))

    # 6) 上下文摘要 -> 7) 长连接令牌
    db.execute(delete(ContextSummary).where(ContextSummary.conversation_id.in_(owned_ids)))
    db.execute(delete(WebsocketToken).where(WebsocketToken.conversation_id.in_(owned_ids)))

    # 8) 会话本身置为已删除（保留行以符合 status=deleted 枚举语义）
    now = datetime.now()
    for conv in owned:
        conv.status = "deleted"
        conv.updated_at = now

    db.commit()

    # --- 物理目录清理 ---
    removed_dirs: list[str] = []
    removed_files = 0
    freed_bytes = 0
    for conv in owned:
        res = cleanup_conversation_dirs(user.id, conv.id)
        removed_dirs.extend(res.removed_dirs)
        removed_files += res.removed_files
        freed_bytes += res.freed_bytes

    logger.info(
        "会话 %s 删除完成：清理目录 %s 个、文件 %s 个、释放 %s 字节",
        owned_ids, len(removed_dirs), removed_files, freed_bytes,
    )

    return {
        "deleted": len(owned_ids),
        "conversation_ids": owned_ids,
        "removed_dirs": removed_dirs,
        "removed_files": removed_files,
        "freed_bytes": freed_bytes,
    }


def search_titles(db: Session, user: User, keyword: str, limit: int = 20) -> list[Conversation]:
    like = f"%{keyword.strip()}%"
    stmt = (
        select(Conversation)
        .where(
            Conversation.user_id == user.id,
            Conversation.status != "deleted",
            or_(Conversation.title.like(like)),
        )
        .order_by(Conversation.last_message_at.desc(), Conversation.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())
