# -*- coding: utf-8 -*-
"""数据库查询工具：对业务库执行只读 SQL，产出可回溯的证据。

安全约束:
    1. 只允许单条 SELECT / WITH 语句，禁止分号拼接
    2. 禁用一切写操作与 DDL 关键字
    3. 表名白名单（只允许 biz_* 与核心只读表）
    4. 强制 LIMIT 上限，避免大结果集拖垮服务
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.analysis.tools.base import Tool, ToolContext, ToolResult, register
from app.core.runtime_config import runtime_config

logger = logging.getLogger(__name__)

MAX_ROWS = 500
DEFAULT_ROWS = 100


def row_limit() -> int:
    """单次查询返回行数上限，取自运行时配置 security.sql_row_limit。"""
    return max(1, min(runtime_config.get_int("security.sql_row_limit", 2000), MAX_ROWS))

# 禁用关键字（词边界匹配）
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|grant|revoke|"
    r"load_file|outfile|dumpfile|information_schema|mysql\.|performance_schema|"
    r"sleep|benchmark|lock\s+tables|set\s+@|call|handler)\b",
    re.IGNORECASE,
)

_ALLOWED_TABLES = re.compile(
    r"\b(biz_[a-z_]+|analysis_tasks|analysis_results|messages|attachments|"
    r"conversations|system_configs|task_logs|context_summaries)\b",
    re.IGNORECASE,
)

_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)


def validate_sql(sql: str) -> str:
    """校验并规范化 SQL，返回规范化后的语句。校验失败抛 ValueError。"""
    raw = (sql or "").strip()
    if not raw:
        raise ValueError("SQL 不能为空")

    # 去掉注释，防止用注释绕过关键字检查
    raw = re.sub(r"/\*.*?\*/", " ", raw, flags=re.DOTALL)
    raw = re.sub(r"--[^\n]*", " ", raw)
    raw = re.sub(r"#[^\n]*", " ", raw)
    stripped = raw.strip().rstrip(";").strip()

    if ";" in stripped:
        raise ValueError("只允许执行单条语句，禁止分号拼接")

    if not re.match(r"^(select|with)\b", stripped, re.IGNORECASE):
        raise ValueError("只允许执行 SELECT / WITH 查询")

    hit = _FORBIDDEN.search(stripped)
    if hit:
        raise ValueError(f"SQL 中含被禁用的关键字：{hit.group(0)}")

    tables = {t.lower() for t in _TABLE_REF.findall(stripped)}
    illegal = {t for t in tables if not t.startswith("biz_") and t not in {
        "analysis_tasks", "analysis_results", "messages", "attachments",
        "conversations", "system_configs", "task_logs", "context_summaries",
    }}
    if illegal:
        raise ValueError(f"查询了未授权的数据表：{', '.join(sorted(illegal))}")

    if not _ALLOWED_TABLES.search(stripped):
        raise ValueError("未识别到任何授权数据表")

    return stripped


def _normalize(value: Any) -> Any:
    """把 Decimal / date 等类型转成可 JSON 序列化的值。"""
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def run_query(ctx: ToolContext, sql: str, limit: int = DEFAULT_ROWS) -> tuple[list[dict], int]:
    """执行只读查询，返回 (行列表, 行数)。"""
    safe_sql = validate_sql(sql)
    cap = min(int(limit or DEFAULT_ROWS), row_limit())
    cap = max(1, cap)

    # 若语句没有 LIMIT，则在外层包一层限制
    if not re.search(r"\blimit\b", safe_sql, re.IGNORECASE):
        safe_sql = f"{safe_sql} LIMIT {cap}"

    ctx.check_cancel()
    rows = ctx.db.execute(text(safe_sql)).mappings().all()
    out = [{k: _normalize(v) for k, v in dict(r).items()} for r in rows]
    logger.debug("db_query 返回 %s 行：%s", len(out), safe_sql[:160])
    return out, len(out)


class DbQueryTool(Tool):
    name = "db_query"
    description = "对业务数据仓库执行只读 SQL 查询，返回结构化结果行，用作归因证据"
    signature = {
        "sql": "只读 SELECT/WITH 语句，只能查询 biz_* 业务表",
        "limit": "最大返回行数，默认 100，上限 500",
    }

    def run(self, ctx: ToolContext, sql: str = "", limit: int = DEFAULT_ROWS, **_: Any) -> ToolResult:
        try:
            rows, count = run_query(ctx, sql, limit)
        except ValueError as exc:
            return ToolResult.failure(f"SQL 未通过安全校验：{exc}")

        if not rows:
            return ToolResult(ok=True, summary="查询无结果", data=[], rows=0)

        preview_keys = list(rows[0].keys())[:6]
        first = rows[0]
        preview = "；".join(f"{k}={first[k]}" for k in preview_keys)
        summary = f"返回 {count} 行数据，字段 {', '.join(preview_keys)}。示例：{preview}"

        return ToolResult(ok=True, summary=summary, data=rows, rows=count)


register(DbQueryTool())
