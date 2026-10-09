# -*- coding: utf-8 -*-
"""多轮上下文服务：历史消息装配、超长对话摘要压缩、上下文记忆复用。

多轮归因的关键（需求 §6.1）:
    第二轮提问必须能复用第一轮的问题定义、指标口径与结论，
    而不是把每一轮当成孤立的新问题。
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.runtime_config import runtime_config
from app.models import ContextSummary, Message

logger = logging.getLogger(__name__)

SUMMARY_MARK = "【历史摘要】"


# ---------------------------------------------------------------------------
# 摘要压缩
# ---------------------------------------------------------------------------

def latest_summary(db: Session, conversation_id: int) -> ContextSummary | None:
    stmt = (
        select(ContextSummary)
        .where(ContextSummary.conversation_id == conversation_id)
        .order_by(ContextSummary.end_seq_no.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def coverage(db: Session, conversation_id: int) -> tuple[int, int]:
    """返回 (消息总数, 已被摘要覆盖的最大序号)。"""
    total = db.execute(
        select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
    ).scalar_one()
    last = db.execute(
        select(func.max(ContextSummary.end_seq_no)).where(
            ContextSummary.conversation_id == conversation_id
        )
    ).scalar()
    return int(total), int(last or 0)


def _extractive_summary(messages: list[Message], max_chars: int = 1200) -> str:
    """抽取式摘要：保留每轮的用户问题与助手结论首段，丢弃过程噪音。

    演示环境不依赖外部大模型，因此用确定性规则压缩；
    接入真实 LLM 时只需替换本函数（见 app/analysis/llm.py）。
    """
    lines: list[str] = []
    for m in messages:
        text = (m.content or "").strip()
        if not text:
            continue
        if m.role == "user":
            lines.append(f"- 用户提问：{_oneline(text, 120)}")
        elif m.role == "assistant" and m.message_type in ("text", "result"):
            lines.append(f"- 分析结论：{_oneline(text, 220)}")
        # 工具调用类消息不进摘要，避免噪音
    body = "\n".join(lines)
    if len(body) > max_chars:
        body = body[:max_chars] + "…"
    return body or "（本段对话无可摘要内容）"


def _oneline(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


def maybe_summarize(db: Session, conversation_id: int) -> ContextSummary | None:
    """当未覆盖消息数超过阈值时生成/更新一段摘要。

    阈值来自运行时配置 analysis.summary_trigger_messages（默认 40）。
    """
    threshold = runtime_config.get_int("analysis.summary_trigger_messages", 40)
    if threshold <= 0:
        return None

    total, covered = coverage(db, conversation_id)
    keep_recent = runtime_config.get_int("analysis.context_keep_rounds", 4) * 2

    pending = total - covered
    # 未覆盖的消息里，最近 keep_recent 条保留原文，只压缩更早的部分
    if pending <= threshold:
        return None

    end_seq = None
    cutoff_index = pending - keep_recent
    if cutoff_index <= 0:
        return None

    rows = list(
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.seq_no > covered)
            .order_by(Message.seq_no)
            .limit(cutoff_index)
        ).scalars().all()
    )
    if not rows:
        return None
    end_seq = rows[-1].seq_no

    text = _extractive_summary(rows)
    summary = ContextSummary(
        conversation_id=conversation_id,
        start_seq_no=rows[0].seq_no,
        end_seq_no=end_seq,
        summary_text=text,
    )
    db.add(summary)
    db.commit()
    db.refresh(summary)
    logger.info(
        "会话 #%s 生成上下文摘要 #%s（seq %s-%s，压缩 %s 条消息）",
        conversation_id, summary.id, summary.start_seq_no, summary.end_seq_no, len(rows),
    )
    return summary


# ---------------------------------------------------------------------------
# 上下文装配
# ---------------------------------------------------------------------------

def build_context(db: Session, conversation_id: int, current_input: str) -> dict:
    """装配本轮分析的上下文。

    返回:
        {
          "summary_text": 历史摘要（若有），
          "recent_turns": [{role, content}, ...] 最近若干轮原文，
          "prompt_context": 直接可注入提示词的字符串，
          "turn_index": 第几轮提问,
          "history_questions": 历史用户提问列表，
          "prior_conclusions": 历史分析结论列表（供指标口径复用）,
        }
    """
    window_turns = runtime_config.get_int("analysis.context_keep_rounds", 4)
    limit = max(window_turns * 2, 4)

    summary = latest_summary(db, conversation_id)
    covered = summary.end_seq_no if summary else 0

    rows = list(
        db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.seq_no > covered,
            )
            .order_by(Message.seq_no.desc())
            .limit(limit)
        ).scalars().all()
    )
    rows.reverse()

    recent_turns = [
        {"role": m.role, "content": (m.content or "").strip(), "message_type": m.message_type}
        for m in rows
        if m.role in ("user", "assistant") and (m.content or "").strip()
    ]

    history_questions = [t["content"] for t in recent_turns if t["role"] == "user"]
    prior_conclusions = [t["content"] for t in recent_turns if t["role"] == "assistant"]

    total_questions = db.execute(
        select(func.count(Message.id)).where(
            Message.conversation_id == conversation_id, Message.role == "user"
        )
    ).scalar_one()

    parts: list[str] = []
    if summary is not None:
        parts.append(f"{SUMMARY_MARK}\n{summary.summary_text}")
    if recent_turns:
        lines = []
        for t in recent_turns:
            who = "用户" if t["role"] == "user" else "系统"
            lines.append(f"{who}：{t['content']}")
        parts.append("【最近对话】\n" + "\n".join(lines))
    parts.append(f"【本轮问题】\n{current_input}")

    prompt_context = "\n\n".join(parts)

    return {
        "summary_text": summary.summary_text if summary else None,
        "recent_turns": recent_turns,
        "prompt_context": prompt_context,
        "turn_index": int(total_questions) + 1,
        "history_questions": history_questions,
        "prior_conclusions": prior_conclusions,
        "covered_seq": covered,
    }


def is_follow_up(db: Session, conversation_id: int, current_input: str) -> bool:
    """判断本轮是否为「追问」（多轮归因的关键分支）。

    规则：会话中已存在用户提问，且本轮问题较短或含指代词。
    """
    prior = db.execute(
        select(func.count(Message.id)).where(
            Message.conversation_id == conversation_id, Message.role == "user"
        )
    ).scalar_one()
    if prior == 0:
        return False

    markers = ("它", "这个", "上述", "刚才", "那", "再", "继续", "进一步", "具体", "为什么", "还有", "另外")
    text = (current_input or "").strip()
    if len(text) <= 20:
        return True
    return any(m in text for m in markers)


def clear_summaries(db: Session, conversation_id: int) -> int:
    """清空会话摘要（供「重新开始分析」使用）。"""
    rows = db.execute(
        select(ContextSummary).where(ContextSummary.conversation_id == conversation_id)
    ).scalars().all()
    for r in rows:
        db.delete(r)
    db.commit()
    logger.info("会话 #%s 清空 %s 条上下文摘要", conversation_id, len(rows))
    return len(rows)


def summary_stats(db: Session, conversation_id: int) -> dict:
    total, covered = coverage(db, conversation_id)
    count = db.execute(
        select(func.count(ContextSummary.id)).where(ContextSummary.conversation_id == conversation_id)
    ).scalar_one()
    return {
        "message_total": total,
        "summarized_upto_seq": covered,
        "summary_count": int(count),
        "unsummarized": max(total - covered, 0),
    }
