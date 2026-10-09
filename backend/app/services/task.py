# -*- coding: utf-8 -*-
"""分析任务服务：任务生命周期、执行状态、工具调用记录、日志。

状态机（需求 §6.2）:
    queued -> running -> success | failed | cancelled

约束: 同一会话同一时刻只允许一个 running/queued 任务。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import HTTPException, status as http_status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AnalysisResult, AnalysisTask, TaskLog, User

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("success", "failed", "cancelled")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------------------
# 创建 / 查询
# ---------------------------------------------------------------------------

def find_active(db: Session, conversation_id: int) -> AnalysisTask | None:
    """取会话内尚未结束的任务。"""
    stmt = (
        select(AnalysisTask)
        .where(
            AnalysisTask.conversation_id == conversation_id,
            AnalysisTask.task_status.in_(ACTIVE_STATUSES),
        )
        .order_by(AnalysisTask.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def create(db: Session, conversation_id: int, user_id: int, input_text: str) -> AnalysisTask:
    """创建任务。若会话已有进行中的任务，返回 409。"""
    running = find_active(db, conversation_id)
    if running is not None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"当前会话已有进行中的分析任务（task_id={running.id}），请等待其完成或先取消",
        )

    task = AnalysisTask(
        conversation_id=conversation_id,
        user_id=user_id,
        input_text=input_text,
        task_status="queued",
        current_step="排队中",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info("会话 #%s 创建分析任务 #%s：%s", conversation_id, task.id, input_text[:60])
    return task


def get_owned(db: Session, user: User, task_id: int) -> AnalysisTask:
    task = db.get(AnalysisTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="任务不存在或无权访问")
    return task


def list_for_conversation(
    db: Session,
    conversation_id: int,
    limit: int = 50,
    status: str | None = None,
) -> list[AnalysisTask]:
    stmt = select(AnalysisTask).where(AnalysisTask.conversation_id == conversation_id)
    if status:
        stmt = stmt.where(AnalysisTask.task_status == status)
    stmt = stmt.order_by(AnalysisTask.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


def list_for_user(db: Session, user_id: int, limit: int = 50, status: str | None = None) -> list[AnalysisTask]:
    """跨会话取当前用户的任务（历史页在没有指定会话时用）。"""
    stmt = select(AnalysisTask).where(AnalysisTask.user_id == user_id)
    if status:
        stmt = stmt.where(AnalysisTask.task_status == status)
    stmt = stmt.order_by(AnalysisTask.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# 状态流转
# ---------------------------------------------------------------------------

def mark_running(db: Session, task: AnalysisTask, step: str = "开始分析") -> None:
    task.task_status = "running"
    task.started_at = datetime.now()
    task.current_step = step
    db.commit()
    logger.info("任务 #%s 开始执行", task.id)


def update_step(db: Session, task: AnalysisTask, step: str) -> None:
    task.current_step = step[:128]
    db.commit()


def mark_success(db: Session, task: AnalysisTask, step: str = "分析完成") -> None:
    task.task_status = "success"
    task.current_step = step[:128]
    task.finished_at = datetime.now()
    task.error_message = None
    db.commit()
    logger.info("任务 #%s 执行成功，耗时 %sms", task.id, task.duration_ms)


def mark_failed(db: Session, task: AnalysisTask, message: str, step: str = "分析失败") -> None:
    task.task_status = "failed"
    task.current_step = step[:128]
    task.error_message = (message or "未知错误")[:2000]
    task.finished_at = datetime.now()
    db.commit()
    logger.warning("任务 #%s 执行失败：%s", task.id, message)


def mark_cancelled(db: Session, task: AnalysisTask) -> None:
    task.task_status = "cancelled"
    task.current_step = "用户取消"
    task.finished_at = datetime.now()
    db.commit()
    logger.info("任务 #%s 被取消", task.id)


def cancel(db: Session, user: User, task_id: int) -> dict:
    """取消任务：终态任务不可取消。"""
    task = get_owned(db, user, task_id)
    if task.task_status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"任务已处于终态（{task.task_status}），无法取消",
        )
    task.task_status = "cancelled"
    task.current_step = "用户取消"
    task.finished_at = datetime.now()
    db.commit()
    add_log(db, task.id, "WARN", "lifecycle", "用户手动取消任务")
    logger.info("用户 %s 取消任务 #%s", user.username, task_id)
    return {"task_id": task.id, "task_status": task.task_status, "message": "任务已取消"}


def cleanup_stale(db: Session, max_age_minutes: int = 30) -> int:
    """把启动前遗留的 running/queued 任务标记为失败（服务重启后无人在跑）。"""
    stale = db.execute(
        select(AnalysisTask).where(AnalysisTask.task_status.in_(ACTIVE_STATUSES))
    ).scalars().all()
    now = datetime.now()
    count = 0
    for task in stale:
        started = task.started_at or task.created_at
        if started and (now - started).total_seconds() > max_age_minutes * 60:
            task.task_status = "failed"
            task.error_message = "服务重启，任务已中断"
            task.current_step = "已中断"
            task.finished_at = now
            count += 1
    if count:
        db.commit()
        logger.warning("启动清理：%s 个残留任务被标记为失败", count)
    return count


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

def add_log(db: Session, task_id: int, level: str, log_type: str, content: str) -> TaskLog:
    """写入任务日志（生命周期 / 工具 / 数据库 / 文件 / 错误）。"""
    log = TaskLog(
        task_id=task_id,
        log_level=level.upper(),
        log_type=log_type,
        log_content=content[:4000],
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def log_tool_call(db: Session, task_id: int, record: dict) -> TaskLog:
    """把一次工具调用记录成结构化日志（log_type='tool'，内容为 JSON）。"""
    log = TaskLog(
        task_id=task_id,
        log_level="INFO",
        log_type="tool",
        log_content=json.dumps(record, ensure_ascii=False),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def tool_calls(db: Session, task_id: int) -> list[dict]:
    """读回某任务的全部工具调用记录（按调用序号）。"""
    stmt = (
        select(TaskLog)
        .where(TaskLog.task_id == task_id, TaskLog.log_type == "tool")
        .order_by(TaskLog.id)
    )
    out: list[dict] = []
    for log in db.execute(stmt).scalars().all():
        try:
            rec = json.loads(log.log_content)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(rec, dict):
            rec.setdefault("started_at", _iso(log.created_at))
            out.append(rec)
    return out


def logs(db: Session, task_id: int, limit: int = 200, log_type: str | None = None) -> list[TaskLog]:
    stmt = select(TaskLog).where(TaskLog.task_id == task_id)
    if log_type:
        stmt = stmt.where(TaskLog.log_type == log_type)
    stmt = stmt.order_by(TaskLog.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------

def _result_id(db: Session, task_id: int) -> int | None:
    return db.execute(
        select(AnalysisResult.id).where(AnalysisResult.task_id == task_id)
    ).scalar_one_or_none()


def detail_dict(db: Session, task: AnalysisTask, *, with_tools: bool = True) -> dict:
    """任务详情（含进度、工具调用链）。"""
    step_total = 0
    step_index = 0
    progress = 0

    # 进度按工具调用数 + 状态估算，供前端进度条使用
    calls = tool_calls(db, task.id) if with_tools else []
    step_total = max(6, len(calls))
    if task.task_status == "queued":
        step_index, progress = 0, 0
    elif task.task_status == "running":
        step_index = min(len(calls), step_total)
        progress = int(step_index / step_total * 100) if step_total else 0
    else:
        step_index, progress = step_total, 100

    return {
        "task_id": task.id,
        "conversation_id": task.conversation_id,
        "user_id": task.user_id,
        "input_text": task.input_text,
        "task_status": task.task_status,
        "current_step": task.current_step,
        "started_at": _iso(task.started_at),
        "finished_at": _iso(task.finished_at),
        "error_message": task.error_message,
        "duration_ms": task.duration_ms,
        "progress": progress,
        "step_index": step_index,
        "step_total": step_total,
        "tool_calls": calls,
        "result_id": _result_id(db, task.id),
        "created_at": _iso(task.created_at),
    }


def list_dict(db: Session, task: AnalysisTask) -> dict:
    return {
        "task_id": task.id,
        "conversation_id": task.conversation_id,
        "input_text": task.input_text,
        "task_status": task.task_status,
        "current_step": task.current_step,
        "progress": 100 if task.task_status in TERMINAL_STATUSES else 0,
        "started_at": _iso(task.started_at),
        "finished_at": _iso(task.finished_at),
        "error_message": task.error_message,
        "result_id": _result_id(db, task.id),
        "created_at": _iso(task.created_at),
    }


def count_by_status(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(AnalysisTask.task_status, func.count(AnalysisTask.id)).group_by(AnalysisTask.task_status)
    ).all()
    out = {s: 0 for s in ("queued", "running", "success", "failed", "cancelled")}
    for status, count in rows:
        out[status] = int(count)
    out["total"] = sum(v for k, v in out.items() if k != "total")
    return out
