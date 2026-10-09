# -*- coding: utf-8 -*-
"""对话编排：一轮提问 = 一条用户消息 + 一个分析任务 + 一条助手消息。

流程（需求 §6.1）:
    1. 校验会话归属，确保同一会话没有进行中的任务
    2. 落库用户消息（含附件关联）
    3. 创建分析任务（queued）
    4. 创建助手占位消息
    5. 提交后投递到后台线程池执行分析引擎
    6. 引擎全程通过 WebSocket 推送 message_start / tool_start / ... / done
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.runtime_config import runtime_config
from app.models import User
from app.services import attachment as attachment_service
from app.services import conversation as conversation_service
from app.services import message as message_service
from app.services import task as task_service

logger = logging.getLogger(__name__)

AUTO_TITLE_LEN = 24

# ---------------------------------------------------------------------------
# 后台执行器与取消登记
# ---------------------------------------------------------------------------

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()

_cancel_events: dict[int, threading.Event] = {}
_cancel_lock = threading.Lock()


def get_executor() -> ThreadPoolExecutor:
    """惰性创建线程池（大小来自运行时配置 system.max_concurrent_tasks）。"""
    global _executor
    with _executor_lock:
        if _executor is None:
            size = max(1, runtime_config.get_int("system.max_concurrent_tasks", 4))
            _executor = ThreadPoolExecutor(max_workers=size, thread_name_prefix="analysis")
            logger.info("分析任务线程池已创建，最大并发 %s", size)
        return _executor


def shutdown_executor(wait: bool = False) -> None:
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=wait, cancel_futures=True)
            _executor = None
            logger.info("分析任务线程池已关闭")


def register_task(task_id: int) -> threading.Event:
    ev = threading.Event()
    with _cancel_lock:
        _cancel_events[task_id] = ev
    return ev


def cancel_event(task_id: int) -> None:
    """置位取消标记，引擎会在下一个检查点退出。"""
    with _cancel_lock:
        ev = _cancel_events.get(task_id)
    if ev is not None:
        ev.set()
        logger.info("任务 #%s 已收到取消信号", task_id)


def is_cancelled(task_id: int) -> bool:
    with _cancel_lock:
        ev = _cancel_events.get(task_id)
    return ev is not None and ev.is_set()


def unregister_task(task_id: int) -> None:
    with _cancel_lock:
        _cancel_events.pop(task_id, None)


# ---------------------------------------------------------------------------
# 一轮对话
# ---------------------------------------------------------------------------

def send_message(db: Session, user: User, conversation_id: int, content: str, attachment_ids: list[int]) -> dict:
    """提交一轮提问，返回 {user_message_id, assistant_message_id, task_id, ...}。"""
    conv = conversation_service.get_owned(db, user, conversation_id)

    # 1) 创建任务（内部会拒绝并发的进行中任务）
    task = task_service.create(db, conv.id, user.id, content)
    task_service.add_log(db, task.id, "INFO", "lifecycle", f"收到提问：{content[:200]}")

    # 2) 用户消息
    user_msg = message_service.add_message(
        db, conv.id, role="user", content=content, message_type="text", commit=False
    )
    message_service.attach_to_message(db, user_msg.id, attachment_ids, conv.id)
    db.commit()
    db.refresh(user_msg)

    # 3) 助手占位消息（立即出现在历史里，等待流式内容填充）
    assistant_msg = message_service.add_message(
        db, conv.id, role="assistant", content="", message_type="text", commit=True
    )

    # 4) 会话元信息：首轮提问自动命名
    if conv.title in (conversation_service.DEFAULT_TITLE, "", None):
        conv.title = _auto_title(content)
    conv.last_message_at = datetime.now()
    db.commit()

    # 5) 投递后台执行
    ev = register_task(task.id)
    try:
        get_executor().submit(_run, task.id, assistant_msg.id, user_msg.id, ev)
    except RuntimeError as exc:  # 线程池已关闭
        unregister_task(task.id)
        task_service.mark_failed(db, task, f"分析调度失败：{exc}")
        raise

    logger.info(
        "会话 #%s 第 %s 轮提问已提交：task=#%s user_msg=#%s assistant_msg=#%s",
        conv.id, "", task.id, user_msg.id, assistant_msg.id,
    )

    return {
        "conversation_id": conv.id,
        "user_message_id": user_msg.id,
        "assistant_message_id": assistant_msg.id,
        "task_id": task.id,
        "task_status": task.task_status,
        "created_at": user_msg.created_at.isoformat() if user_msg.created_at else None,
    }


def _auto_title(content: str) -> str:
    flat = " ".join((content or "").split())
    if len(flat) <= AUTO_TITLE_LEN:
        return flat or conversation_service.DEFAULT_TITLE
    return flat[:AUTO_TITLE_LEN] + "…"


def _run(task_id: int, assistant_message_id: int, user_message_id: int, cancel_ev: threading.Event) -> None:
    """线程池入口：独立 session 执行分析引擎，结束后清理登记。"""
    from app.analysis.engine import run_task  # 延迟导入，避免循环依赖

    try:
        run_task(
            task_id=task_id,
            assistant_message_id=assistant_message_id,
            user_message_id=user_message_id,
            cancel_event=cancel_ev,
        )
    except Exception as exc:  # noqa: BLE001 - 兜底，防止线程静默死亡
        logger.exception("任务 #%s 执行时抛出未捕获异常", task_id)
        try:
            from app.core.db import session_scope
            from app.models import AnalysisTask
            from app.services import task as ts
            from app.ws import emitter

            with session_scope() as db:
                task = db.get(AnalysisTask, task_id)
                if task is not None and task.task_status not in ts.TERMINAL_STATUSES:
                    ts.mark_failed(db, task, f"内部错误：{exc}")
                    emitter.error(task.conversation_id, task_id, f"内部错误：{exc}", "internal")
        except Exception:  # noqa: BLE001 - 兜底逻辑本身失败时仅记录
            logger.exception("任务 #%s 失败状态回写也失败了", task_id)
    finally:
        unregister_task(task_id)


def cancel(db: Session, user: User, task_id: int) -> dict:
    """对外取消接口：置位线程标记 + 落库状态。"""
    out = task_service.cancel(db, user, task_id)
    cancel_event(task_id)
    return out
