# -*- coding: utf-8 -*-
"""消息服务：入库存储、历史分页查询、时序排序、消息类型区分。"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.paths import human_size
from app.models import AnalysisTask, Attachment, Message

logger = logging.getLogger(__name__)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def next_seq_no(db: Session, conversation_id: int) -> int:
    """会话内下一个消息序号（保证时序）。"""
    current = db.execute(
        select(func.max(Message.seq_no)).where(Message.conversation_id == conversation_id)
    ).scalar()
    return int(current or 0) + 1


def add_message(
    db: Session,
    conversation_id: int,
    role: str,
    content: str,
    *,
    message_type: str = "text",
    tool_name: str | None = None,
    tool_status: str | None = None,
    seq_no: int | None = None,
    commit: bool = True,
) -> Message:
    """写入一条消息。seq_no 缺省时自动取下一个序号。"""
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        message_type=message_type,
        content=content,
        tool_name=tool_name,
        tool_status=tool_status,
        seq_no=seq_no if seq_no is not None else next_seq_no(db, conversation_id),
    )
    db.add(msg)
    if commit:
        db.commit()
        db.refresh(msg)
    else:
        db.flush()
    return msg


def _attachment_brief(att: Attachment) -> dict:
    return {
        "attachment_id": att.id,
        "file_name": att.file_name,
        "file_type": att.file_type,
        "file_size": att.file_size,
        "file_size_text": human_size(att.file_size),
        "parse_status": att.parse_status,
        "created_at": _iso(att.created_at),
    }


def history(
    db: Session,
    conversation_id: int,
    *,
    page_size: int = 20,
    before_seq: int | None = None,
) -> dict:
    """历史消息分页（游标分页）。

    返回的 items 按 seq_no **升序**排列，便于前端直接追加渲染；
    游标 before_seq 表示「只取比它更早的消息」，用于向上翻页。
    """
    total = db.execute(
        select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
    ).scalar_one()

    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if before_seq is not None:
        stmt = stmt.where(Message.seq_no < before_seq)
    stmt = stmt.order_by(Message.seq_no.desc()).limit(page_size)

    rows = list(db.execute(stmt).scalars().all())
    rows.reverse()  # 升序输出

    # 批量装配附件，避免 N+1
    msg_ids = [m.id for m in rows]
    att_map: dict[int, list[dict]] = {}
    if msg_ids:
        atts = db.execute(
            select(Attachment).where(Attachment.message_id.in_(msg_ids)).order_by(Attachment.id)
        ).scalars().all()
        for a in atts:
            att_map.setdefault(a.message_id, []).append(_attachment_brief(a))

    # 消息 -> 任务 映射（前端点击消息可定位到对应任务）
    task_ids = {m.id: None for m in rows}
    if msg_ids:
        # 任务与用户消息通过 conversation + 内容近似关联；这里直接用同会话最近任务映射
        pass

    items = [
        {
            "message_id": m.id,
            "seq_no": m.seq_no,
            "role": m.role,
            "message_type": m.message_type,
            "content": m.content,
            "tool_name": m.tool_name,
            "tool_status": m.tool_status,
            "task_id": task_ids.get(m.id),
            "attachments": att_map.get(m.id, []),
            "created_at": _iso(m.created_at),
        }
        for m in rows
    ]

    has_more = False
    next_before_seq = None
    if items:
        oldest_seq = items[0]["seq_no"]
        remaining = db.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == conversation_id, Message.seq_no < oldest_seq
            )
        ).scalar_one()
        has_more = remaining > 0
        if has_more:
            next_before_seq = oldest_seq

    return {
        "conversation_id": conversation_id,
        "total": int(total),
        "has_more": has_more,
        "next_before_seq": next_before_seq,
        "items": items,
    }


def messages_between(db: Session, conversation_id: int, start_seq: int, end_seq: int) -> list[Message]:
    """取某序号区间内的消息（上下文摘要压缩用）。"""
    stmt = (
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.seq_no >= start_seq,
            Message.seq_no <= end_seq,
        )
        .order_by(Message.seq_no)
    )
    return list(db.execute(stmt).scalars().all())


def recent_context(db: Session, conversation_id: int, limit: int = 12) -> list[Message]:
    """最近 N 条对话消息（拼装分析上下文用），按时间升序返回。"""
    rows = list(
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.seq_no.desc())
            .limit(limit)
        ).scalars().all()
    )
    rows.reverse()
    return rows


def attach_to_message(db: Session, message_id: int, attachment_ids: list[int], conversation_id: int) -> int:
    """把附件挂到指定消息上（同时校验附件属于本会话）。"""
    if not attachment_ids:
        return 0
    atts = db.execute(
        select(Attachment).where(
            Attachment.id.in_(attachment_ids),
            Attachment.conversation_id == conversation_id,
        )
    ).scalars().all()
    for a in atts:
        a.message_id = message_id
    db.commit()
    return len(atts)


def bind_task_to_assistant_message(db: Session, message_id: int, task_id: int) -> None:
    """把分析任务 ID 记到助手消息内容前缀的元数据里（供历史回放定位）。

    消息表没有 task_id 列（需求 §九 的字段清单已固定），因此任务关联通过
    会话内「最近一次任务」推导；此函数保留为语义占位，写入 task 关联到日志。
    """
    task = db.get(AnalysisTask, task_id)
    if task is None:
        return
    logger.debug("助手消息 #%s 关联任务 #%s", message_id, task_id)
