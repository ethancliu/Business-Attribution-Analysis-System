# -*- coding: utf-8 -*-
"""文本检索工具：在知识库、用户评论、上传文本中检索关键词。

三类语料（按顺序检索，结果带来源标记，便于在证据链里标注出处）:
    1. knowledge/  经营分析方法论知识库（markdown）
    2. biz_review  用户评论原文（数据库）
    3. 上传的文本类附件
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text as sql_text

from app.analysis.tools.base import Tool, ToolContext, ToolResult, register
from app.core.config import settings
from app.core.paths import abs_path

logger = logging.getLogger(__name__)

MAX_HITS = 20
SNIPPET = 160


def _knowledge_dir() -> Path:
    return settings.knowledge_root


def _search_knowledge(keyword: str, limit: int) -> list[dict]:
    root = _knowledge_dir()
    if not root.exists():
        return []
    hits: list[dict] = []
    for path in sorted(root.rglob("*.md")):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        idx = content.find(keyword)
        if idx < 0:
            continue
        start = max(0, idx - SNIPPET // 2)
        snippet = " ".join(content[start:start + SNIPPET].split())
        hits.append({
            "source_type": "knowledge",
            "source_name": f"知识库/{path.name}",
            "snippet": snippet,
        })
        if len(hits) >= limit:
            break
    return hits


def _search_reviews(ctx: ToolContext, keyword: str, limit: int) -> list[dict]:
    sql = """
        SELECT review_id, product_id, sentiment, issue_tag, review_content
        FROM biz_review
        WHERE review_content LIKE :kw OR issue_tag LIKE :kw
        ORDER BY id DESC
        LIMIT :lim
    """
    try:
        rows = ctx.db.execute(
            sql_text(sql), {"kw": f"%{keyword}%", "lim": limit}
        ).mappings().all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("检索评论失败：%s", exc)
        return []
    return [
        {
            "source_type": "database",
            "source_name": f"用户评论 #{r['review_id']}（商品 {r['product_id']}，情绪 {r['sentiment']}，标签 {r['issue_tag']}）",
            "snippet": " ".join((r["review_content"] or "").split())[:SNIPPET],
        }
        for r in rows
    ]


def _search_attachments(ctx: ToolContext, keyword: str, limit: int) -> list[dict]:
    from app.models import Attachment

    hits: list[dict] = []
    atts = ctx.db.query(Attachment).filter(
        Attachment.conversation_id == ctx.conversation_id,
        Attachment.parse_status == "parsed",
    ).all()
    for att in atts:
        if att.file_type not in ("csv", "json", "text"):
            continue
        try:
            path = abs_path(att.file_path)
        except ValueError:
            continue
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        idx = content.find(keyword)
        if idx < 0:
            continue
        start = max(0, idx - SNIPPET // 2)
        hits.append({
            "source_type": "attachment",
            "source_name": f"附件/{att.file_name}",
            "snippet": " ".join(content[start:start + SNIPPET].split()),
        })
        if len(hits) >= limit:
            break
    return hits


class TextSearchTool(Tool):
    name = "text_search"
    description = "在知识库、用户评论、上传文本中检索关键词，定位问题原文与分析方法论"
    signature = {
        "keyword": "检索关键词",
        "scope": "all | knowledge | review | attachment",
        "limit": "最大命中数，默认 10",
    }

    def run(
        self,
        ctx: ToolContext,
        keyword: str = "",
        scope: str = "all",
        limit: int = 10,
        **_: Any,
    ) -> ToolResult:
        kw = (keyword or "").strip()
        if not kw:
            return ToolResult.failure("keyword 不能为空")

        cap = max(1, min(int(limit or 10), MAX_HITS))
        ctx.check_cancel()

        hits: list[dict] = []
        if scope in ("all", "knowledge"):
            hits.extend(_search_knowledge(kw, cap))
        if scope in ("all", "review"):
            hits.extend(_search_reviews(ctx, kw, cap))
        if scope in ("all", "attachment"):
            hits.extend(_search_attachments(ctx, kw, cap))

        hits = hits[:cap]
        if not hits:
            return ToolResult(
                ok=True,
                summary=f"关键词「{kw}」在知识库/评论/附件中均未命中",
                data=[],
                rows=0,
            )

        by_source: dict[str, int] = {}
        for h in hits:
            by_source[h["source_type"]] = by_source.get(h["source_type"], 0) + 1
        dist = "、".join(f"{k} {v} 条" for k, v in by_source.items())
        first = hits[0]
        summary = f"关键词「{kw}」命中 {len(hits)} 处（{dist}）。首条来自 {first['source_name']}：{first['snippet'][:80]}"

        return ToolResult(ok=True, summary=summary, data=hits, rows=len(hits))


register(TextSearchTool())
