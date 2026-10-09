# -*- coding: utf-8 -*-
"""分析引擎：一次分析任务的完整执行主流程。

执行阶段:
    1. prepare   准备上下文（多轮记忆 + 历史摘要）
    2. route     场景路由（关键词计分 + 实体抽取）
    3. start     推送 message_start，任务进入 running
    4. run       逐步执行场景步骤链（每步推送 tool_start / tool_finish / task_status）
    5. interpret 由场景产出六大模块解释
    6. generate  生成标准报告（result_generate）
    7. persist   落库分析结果 + 更新助手消息
    8. finish    推送 result_ready / done，任务置为 success

任意阶段出现取消信号，都会走 TaskCancelled 分支并落库 cancelled。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.analysis import scenarios as scenario_pkg
from app.analysis.llm import llm_client
from app.analysis.tools import ToolContext, ToolResult, get_tool
from app.analysis.tools.base import TaskCancelled
from app.core.db import session_scope
from app.models import AnalysisTask, Message, TaskLog
from app.services import context as context_service
from app.services import conversation as conversation_service
from app.services import message as message_service
from app.services import result as result_service
from app.services import task as task_service
from app.ws import emitter

logger = logging.getLogger(__name__)

SCENARIO_LOG_PREFIX = "场景路由|"
STREAM_CHUNK = 48
STREAM_DELAY = 0.012


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _resolve_args(args: dict, results: dict[str, ToolResult]) -> dict:
    """把形如 "@step_key" 的参数替换成前序步骤的真实产出。"""
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and v.startswith("@"):
            key = v[1:]
            prev = results.get(key)
            out[k] = prev.data if prev is not None and prev.ok else []
        else:
            out[k] = v
    return out


def _stream_text(conversation_id: int, task_id: int, text: str) -> None:
    """把文本按小块推送给前端，模拟流式输出。"""
    if not text:
        return
    for i in range(0, len(text), STREAM_CHUNK):
        emitter.message_delta(conversation_id, task_id, text[i:i + STREAM_CHUNK], seq=i)
        time.sleep(STREAM_DELAY)


def previous_scenario_key(db, conversation_id: int, exclude_task_id: int) -> str | None:
    """读取本会话上一次分析使用的场景（多轮追问时复用）。"""
    stmt = (
        select(TaskLog)
        .where(
            TaskLog.log_type == "lifecycle",
            TaskLog.log_content.like(f"{SCENARIO_LOG_PREFIX}%"),
            TaskLog.task_id != exclude_task_id,
        )
        .order_by(TaskLog.id.desc())
        .limit(20)
    )
    for log in db.execute(stmt).scalars().all():
        task = db.get(AnalysisTask, log.task_id)
        if task is not None and task.conversation_id == conversation_id:
            body = log.log_content[len(SCENARIO_LOG_PREFIX):]
            key = body.split("|")[0].strip()
            if key:
                return key
    return None


def _build_tool_context(
    db,
    task: AnalysisTask,
    cancel_event: threading.Event | None,
) -> ToolContext:
    return ToolContext(
        db=db,
        task_id=task.id,
        conversation_id=task.conversation_id,
        user_id=task.user_id,
        input_text=task.input_text,
        cancel_event=cancel_event,
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_task(
    task_id: int,
    assistant_message_id: int,
    user_message_id: int,
    cancel_event: threading.Event | None = None,
) -> None:
    """线程池入口：独立 session 完成一次分析。"""
    started = time.perf_counter()

    with session_scope() as db:
        task = db.get(AnalysisTask, task_id)
        if task is None:
            logger.error("任务 #%s 不存在，忽略本次执行", task_id)
            return

        conversation_id = task.conversation_id
        task_service.mark_running(db, task, "准备分析上下文")
        task_service.add_log(db, task_id, "INFO", "lifecycle", "任务开始执行")

    try:
        with session_scope() as db:
            task = db.get(AnalysisTask, task_id)
            if task is None:
                return
            _execute(db, task, assistant_message_id, user_message_id, cancel_event, started)

    except TaskCancelled:
        with session_scope() as db:
            task = db.get(AnalysisTask, task_id)
            if task is not None and task.task_status not in task_service.TERMINAL_STATUSES:
                task_service.mark_cancelled(db, task)
                task_service.add_log(db, task_id, "WARN", "lifecycle", "任务被取消，已停止执行")
                emitter.error(task.conversation_id, task_id, "任务已被用户取消", "cancelled")
                emitter.done(
                    task.conversation_id,
                    task_id,
                    "cancelled",
                    datetime.now().isoformat(),
                    int((time.perf_counter() - started) * 1000),
                )

    except Exception as exc:  # noqa: BLE001 - 统一落库失败态
        logger.exception("任务 #%s 执行失败", task_id)
        with session_scope() as db:
            task = db.get(AnalysisTask, task_id)
            if task is not None:
                if task.task_status not in task_service.TERMINAL_STATUSES:
                    task_service.mark_failed(db, task, str(exc))
                task_service.add_log(db, task_id, "ERROR", "error", f"任务执行失败：{exc}")
                emitter.error(task.conversation_id, task_id, f"分析失败：{exc}", "analysis")
                emitter.done(
                    task.conversation_id,
                    task_id,
                    task.task_status,
                    datetime.now().isoformat(),
                    int((time.perf_counter() - started) * 1000),
                )


def _execute(
    db,
    task: AnalysisTask,
    assistant_message_id: int,
    user_message_id: int,
    cancel_event: threading.Event | None,
    started: float,
) -> None:
    conversation_id = task.conversation_id

    # ---------------- 1. 准备上下文 ----------------
    ctx = _build_tool_context(db, task, cancel_event)
    ctx.check_cancel()

    turn_ctx = context_service.build_context(db, conversation_id, task.input_text)
    is_follow_up = context_service.is_follow_up(db, conversation_id, task.input_text)

    # ---------------- 2. 场景路由 ----------------
    scenario, intent, scores = scenario_pkg.route(task.input_text)
    if is_follow_up and scenario.key == "generic":
        prev_key = previous_scenario_key(db, conversation_id, task.id)
        if prev_key and prev_key != "generic":
            scenario = scenario_pkg.get_scenario(prev_key)
            intent["scenario_key"] = scenario.key
            intent["scenario_name"] = scenario.name
            intent["reused_from_previous_turn"] = prev_key
            logger.info("多轮追问：沿用上一轮场景「%s」", scenario.name)

    task_service.add_log(
        db, task.id, "INFO", "lifecycle",
        f"{SCENARIO_LOG_PREFIX}{scenario.key}|{scenario.name}|turn={turn_ctx['turn_index']}",
    )
    task_service.add_log(
        db, task.id, "DEBUG", "llm",
        f"场景路由得分：{intent.get('route_scores')}；"
        f"多轮上下文：第 {turn_ctx['turn_index']} 轮，"
        f"历史摘要={'有' if turn_ctx['summary_text'] else '无'}，"
        f"追问={'是' if is_follow_up else '否'}",
    )

    steps = scenario.build(ctx, intent)
    step_total = len(steps) + 2  # 解释 + 报告生成

    # ---------------- 3. 开始推送 ----------------
    emitter.message_start(
        conversation_id,
        task.id,
        assistant_message_id,
        user_message_id,
        task.input_text,
        scenario.name,
        step_total,
    )
    emitter.task_status(conversation_id, task.id, "running", f"已识别场景：{scenario.name}", 5, 1, step_total)

    # ---------------- 4. 执行步骤链 ----------------
    results: dict[str, ToolResult] = {}
    evidence_all: list[dict] = []

    for idx, step in enumerate(steps, start=1):
        ctx.check_cancel()
        task_service.update_step(db, task, step.title)
        emitter.task_status(
            conversation_id, task.id, "running", step.title,
            int(idx / step_total * 100), idx, step_total,
        )

        call_args = _resolve_args(step.args, results)
        emitter.tool_start(conversation_id, task.id, step.tool, call_args, idx)

        t0 = time.perf_counter()
        tool = get_tool(step.tool)
        result = tool.safe_run(ctx, **call_args)
        duration_ms = int((time.perf_counter() - t0) * 1000)

        results[step.key] = result
        ctx.step_index = idx

        emitter.tool_finish(
            conversation_id, task.id, step.tool, idx,
            "success" if result.ok else "failed",
            result.summary or (result.error or ""),
            duration_ms,
            rows=result.rows,
        )

        task_service.log_tool_call(db, task.id, {
            "seq": idx,
            "tool_name": step.tool,
            "tool_args": {k: (v if not isinstance(v, str) or len(v) < 300 else v[:300] + "…") for k, v in call_args.items()},
            "status": "success" if result.ok else "failed",
            "summary": result.summary or (result.error or ""),
            "duration_ms": duration_ms,
            "started_at": datetime.now().isoformat(),
            "finished_at": datetime.now().isoformat(),
            "step_key": step.key,
            "step_title": step.title,
        })
        task_service.add_log(
            db, task.id, "INFO" if result.ok else "WARN", "tool",
            f"[{idx}] {step.title} -> {step.tool} "
            f"{'成功' if result.ok else '失败'}（{duration_ms}ms）：{result.summary or result.error}",
        )

        # 收集证据
        if result.ok:
            if step.evidence_name and isinstance(result.data, list) and result.data:
                from app.analysis.scenarios.common import rows_to_evidence

                evidence_all.extend(
                    rows_to_evidence(
                        [r for r in result.data if isinstance(r, dict)],
                        step.evidence_name,
                        step.related_metric,
                        step.confidence,
                        limit=5,
                    )
                )
            elif step.evidence_name and step.tool in ("text_search",):
                for hit in (result.data or [])[:5]:
                    if isinstance(hit, dict):
                        from app.analysis.scenarios.common import evidence as make_evidence

                        evidence_all.append(
                            make_evidence(
                                hit.get("source_type", "search"),
                                hit.get("source_name", step.evidence_name),
                                hit.get("snippet", ""),
                                step.related_metric,
                                step.confidence,
                            )
                        )
        elif step.critical:
            raise RuntimeError(f"关键步骤失败：{step.title}（{result.error or result.summary}）")

    # ---------------- 5. 解释 ----------------
    ctx.check_cancel()
    task_service.update_step(db, task, "汇总证据并生成归因结论")
    emitter.task_status(
        conversation_id, task.id, "running", "汇总证据并生成归因结论",
        int(len(steps) / step_total * 100), len(steps), step_total,
    )

    interpretation = scenario.interpret(ctx, intent, results, steps)

    # 合并场景自产证据与步骤自动收集的证据（去重）
    merged = _merge_evidence(interpretation.evidence_list, evidence_all)

    conclusion = interpretation.conclusion_text
    if llm_client.enabled:
        conclusion = llm_client.polish(conclusion, scene_hint=scenario.name)
    else:
        task_service.add_log(db, task.id, "DEBUG", "llm", "未启用大模型，结论使用规则模板措辞")

    # ---------------- 6. 生成报告 ----------------
    ctx.check_cancel()
    task_service.update_step(db, task, "生成标准化分析报告")
    emitter.task_status(
        conversation_id, task.id, "running", "生成标准化分析报告",
        int((len(steps) + 1) / step_total * 100), len(steps) + 1, step_total,
    )

    gen_tool = get_tool("result_generate")
    gen_result = gen_tool.safe_run(
        ctx,
        problem_definition=interpretation.problem_definition,
        key_metrics=interpretation.key_metrics,
        evidence_list=merged,
        conclusion_text=conclusion,
        missing_data_text=interpretation.missing_data_text,
        next_action_text=interpretation.next_action_text,
        meta={
            "分析场景": scenario.name,
            "对话轮次": f"第 {turn_ctx['turn_index']} 轮",
            "数据范围": "2026-09-01 ~ 2026-09-30（基准期 09-01~09-15 / 异常期 09-16~09-30）",
        },
    )
    task_service.log_tool_call(db, task.id, {
        "seq": len(steps) + 1,
        "tool_name": "result_generate",
        "tool_args": {"scene": scenario.key, "metrics": len(interpretation.key_metrics), "evidence": len(merged)},
        "status": "success" if gen_result.ok else "failed",
        "summary": gen_result.summary or (gen_result.error or ""),
        "duration_ms": 0,
        "started_at": datetime.now().isoformat(),
        "finished_at": datetime.now().isoformat(),
        "step_key": "result_generate",
        "step_title": "生成标准化分析报告",
    })

    # ---------------- 7. 落库 ----------------
    result = result_service.save(
        db,
        task,
        problem_definition=interpretation.problem_definition,
        key_metrics=interpretation.key_metrics,
        evidence_list=merged,
        conclusion_text=conclusion,
        missing_data_text=interpretation.missing_data_text,
        next_action_text=interpretation.next_action_text,
    )

    summary_text = result_service.render_text_summary(result)
    msg = db.get(Message, assistant_message_id)
    if msg is not None:
        msg.content = summary_text
    conversation_service.touch_last_message(db, conversation_id)
    db.commit()

    # ---------------- 8. 推送与收尾 ----------------
    _stream_text(conversation_id, task.id, summary_text)

    emitter.result_ready(
        conversation_id, task.id, result.id,
        result_service.download_url(result.id),
    )

    task_service.mark_success(db, task)
    task_service.add_log(
        db, task.id, "INFO", "lifecycle",
        f"任务完成：场景「{scenario.name}」，指标 {len(interpretation.key_metrics)} 项，"
        f"证据 {len(merged)} 条，耗时 {int((time.perf_counter() - started) * 1000)}ms",
    )

    # 多轮记忆：必要时压缩历史
    try:
        context_service.maybe_summarize(db, conversation_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("上下文摘要生成失败：%s", exc)

    emitter.done(
        conversation_id, task.id, "success",
        datetime.now().isoformat(),
        int((time.perf_counter() - started) * 1000),
    )

    logger.info(
        "任务 #%s 完成：场景=%s GMV/指标=%s 证据=%s 耗时=%sms",
        task.id, scenario.key, len(interpretation.key_metrics), len(merged),
        int((time.perf_counter() - started) * 1000),
    )


def _merge_evidence(primary: list[dict], extra: list[dict], cap: int = 40) -> list[dict]:
    """合并证据并去重（按 source_name + evidence_text 前 60 字）。"""
    seen: set[str] = set()
    out: list[dict] = []
    for item in list(primary or []) + list(extra or []):
        if not isinstance(item, dict):
            continue
        key = f"{item.get('source_name', '')}|{str(item.get('evidence_text', ''))[:60]}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= cap:
            break
    return out
