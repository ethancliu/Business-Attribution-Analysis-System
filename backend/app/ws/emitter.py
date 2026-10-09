# -*- coding: utf-8 -*-
"""长连接报文构造与推送。

把需求 §12 规定的 8 种报文类型收敛成 8 个函数，供分析引擎调用。
每个函数都可从**任意线程**调用（内部走 manager.push 的线程安全通道）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.ws.manager import manager

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().isoformat()


def emit(conversation_id: int, msg_type: str, task_id: int | None = None, **payload: Any) -> int:
    """构造并推送一条长连接报文。返回接收方连接数。"""
    body: dict[str, Any] = {"type": msg_type, "ts": _now()}
    if task_id is not None:
        body["task_id"] = task_id
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    body.update(payload)
    n = manager.push(conversation_id, body)
    logger.debug("WS -> %s task=%s 推送至 %s 条连接", msg_type, task_id, n)
    return n


# ---------------------------------------------------------------------------
# 1. message_start —— 分析开始
# ---------------------------------------------------------------------------

def message_start(
    conversation_id: int,
    task_id: int,
    message_id: int,
    user_message_id: int,
    input_text: str,
    scenario: str,
    step_total: int,
) -> int:
    return emit(
        conversation_id,
        "message_start",
        task_id=task_id,
        message_id=message_id,
        user_message_id=user_message_id,
        input_text=input_text,
        scenario=scenario,
        step_total=step_total,
    )


# ---------------------------------------------------------------------------
# 2. message_delta —— 文本增量输出
# ---------------------------------------------------------------------------

def message_delta(conversation_id: int, task_id: int, delta_text: str, seq: int = 0) -> int:
    return emit(conversation_id, "message_delta", task_id=task_id, delta_text=delta_text, seq=seq)


# ---------------------------------------------------------------------------
# 3. tool_start —— 工具开始执行
# ---------------------------------------------------------------------------

def tool_start(
    conversation_id: int,
    task_id: int,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_call_seq: int,
) -> int:
    return emit(
        conversation_id,
        "tool_start",
        task_id=task_id,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_call_seq=tool_call_seq,
    )


# ---------------------------------------------------------------------------
# 4. tool_finish —— 工具执行完成
# ---------------------------------------------------------------------------

def tool_finish(
    conversation_id: int,
    task_id: int,
    tool_name: str,
    tool_call_seq: int,
    status: str,
    tool_result_summary: str,
    duration_ms: int,
    rows: int | None = None,
) -> int:
    payload: dict[str, Any] = {
        "tool_name": tool_name,
        "tool_call_seq": tool_call_seq,
        "status": status,
        "tool_result_summary": tool_result_summary,
        "duration_ms": duration_ms,
    }
    if rows is not None:
        payload["rows"] = rows
    return emit(conversation_id, "tool_finish", task_id=task_id, **payload)


# ---------------------------------------------------------------------------
# 5. task_status —— 任务状态变更
# ---------------------------------------------------------------------------

def task_status(
    conversation_id: int,
    task_id: int,
    status: str,
    current_step: str,
    progress: int,
    step_index: int,
    step_total: int,
) -> int:
    return emit(
        conversation_id,
        "task_status",
        task_id=task_id,
        task_status=status,
        current_step=current_step,
        progress=progress,
        step_index=step_index,
        step_total=step_total,
    )


# ---------------------------------------------------------------------------
# 6. result_ready —— 结构化结果生成完成
# ---------------------------------------------------------------------------

def result_ready(conversation_id: int, task_id: int, result_id: int, download_url: str) -> int:
    return emit(
        conversation_id,
        "result_ready",
        task_id=task_id,
        result_id=result_id,
        download_url=download_url,
    )


# ---------------------------------------------------------------------------
# 7. error —— 任务执行失败
# ---------------------------------------------------------------------------

def error(
    conversation_id: int,
    task_id: int,
    error_message: str,
    error_stage: str = "analysis",
) -> int:
    return emit(
        conversation_id,
        "error",
        task_id=task_id,
        error_message=error_message,
        error_stage=error_stage,
    )


# ---------------------------------------------------------------------------
# 8. done —— 本轮分析彻底结束
# ---------------------------------------------------------------------------

def done(
    conversation_id: int,
    task_id: int,
    task_status: str,
    finished_at: str,
    duration_ms: int | None = None,
) -> int:
    payload: dict[str, Any] = {"task_status": task_status, "finished_at": finished_at}
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    return emit(conversation_id, "done", task_id=task_id, **payload)
