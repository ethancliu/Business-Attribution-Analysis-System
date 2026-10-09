# -*- coding: utf-8 -*-
"""场景层公共工具：周期常量、数值格式化、指标与证据构造。

统计口径（与 database/05_demo_data.sql 一致）:
    基准期  2026-09-01 ~ 2026-09-15
    异常期  2026-09-16 ~ 2026-09-30
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text as sql_text

from app.core.runtime_config import runtime_config


def base_start() -> str:
    return str(runtime_config.get("analysis.base_period_start", "2026-09-01"))


def base_end() -> str:
    return str(runtime_config.get("analysis.base_period_end", "2026-09-15"))


def anomaly_start() -> str:
    return str(runtime_config.get("analysis.anomaly_period_start", "2026-09-16"))


def anomaly_end() -> str:
    return str(runtime_config.get("analysis.anomaly_period_end", "2026-09-30"))


def base_period_text() -> str:
    return f"{base_start()} ~ {base_end()}"


def anomaly_period_text() -> str:
    return f"{anomaly_start()} ~ {anomaly_end()}"


def compare_period_text() -> str:
    return f"基准期 {base_period_text()} vs 异常期 {anomaly_period_text()}"


# ---------------------------------------------------------------------------
# 品类解析
# ---------------------------------------------------------------------------

CATEGORY_ID_FALLBACK = "C01"    # 美妆个护，六个演示场景的主对象


def resolve_category_id(db, hint: str | None, default: str = CATEGORY_ID_FALLBACK) -> str:
    """把问题里的品类提示（如「美妆」）解析成 biz_category.category_id。

    品类 ID 在业务库中是 C01…C05 形态的字符串，不能当数字用；
    这里统一走数据库查询，避免把编码写死在场景里。
    """
    if not hint:
        return default
    try:
        row = db.execute(
            sql_text(
                "SELECT category_id FROM biz_category "
                "WHERE category_name LIKE :kw AND status = 'active' "
                "ORDER BY level ASC, category_id ASC LIMIT 1"
            ),
            {"kw": f"%{hint}%"},
        ).mappings().first()
    except Exception:  # noqa: BLE001 - 解析失败退回默认品类
        return default
    return str(row["category_id"]) if row else default


# ---------------------------------------------------------------------------
# 数值格式化
# ---------------------------------------------------------------------------

def num(value: Any, digits: int = 2, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return round(float(value), digits)
    except (TypeError, ValueError):
        return default


def money(value: Any) -> str:
    """金额格式化：超过一万改用「万元」。"""
    v = num(value, 2)
    if abs(v) >= 10000:
        return f"{v / 10000:.2f} 万元"
    return f"{v:.2f} 元"


def pct(value: Any, digits: int = 2) -> str:
    return f"{num(value, digits)}%"


def rate_drop(base: Any, current: Any) -> float:
    """相对变化率（%）。基准为 0 时返回 0。"""
    b = num(base, 6)
    c = num(current, 6)
    if b == 0:
        return 0.0
    return round((c - b) / b * 100, 2)


def ratio(base: Any, current: Any) -> float:
    """倍数比（异常期 / 基准期）。"""
    b = num(base, 6)
    c = num(current, 6)
    if b == 0:
        return 0.0
    return round(c / b, 2)


# ---------------------------------------------------------------------------
# 指标 / 证据构造
# ---------------------------------------------------------------------------

def metric(name: str, value: Any, unit: str = "", period: str = "") -> dict:
    """构造一条关键指标（需求 §13 模块二）。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"
    else:
        text = str(value)
    return {
        "metric_name": name,
        "metric_value": text,
        "metric_unit": unit,
        "metric_period": period or compare_period_text(),
    }


def evidence(
    source_type: str,
    source_name: str,
    evidence_text: str,
    related_metric: str,
    confidence: float = 0.9,
) -> dict:
    """构造一条证据（需求 §13 模块三）。

    source_type: database / file / search / shell / attachment / knowledge
    """
    return {
        "source_type": source_type,
        "source_name": source_name,
        "evidence_text": evidence_text,
        "related_metric": related_metric,
        "confidence": round(max(0.0, min(float(confidence), 1.0)), 2),
    }


def rows_to_evidence(
    rows: list[dict],
    source_name: str,
    related_metric: str,
    confidence: float = 0.9,
    limit: int = 5,
) -> list[dict]:
    """把查询结果行批量转成证据条目（文本化，便于阅读与回溯）。"""
    out: list[dict] = []
    for r in rows[:limit]:
        text = "；".join(f"{k} = {v}" for k, v in r.items())
        out.append(evidence("database", source_name, text, related_metric, confidence))
    return out


def first_row(result: Any) -> dict:
    """安全取出工具结果的第一行。"""
    data = getattr(result, "data", None)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {}


def rows_of(result: Any) -> list[dict]:
    data = getattr(result, "data", None)
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def pick(rows: list[dict], key: str, value: float, *, above: bool = True) -> dict | None:
    """在结果集中挑出指定字段最大/最小的那一行。"""
    if not rows:
        return None
    try:
        ordered = sorted(rows, key=lambda r: num(r.get(key), 6), reverse=above)
    except (TypeError, ValueError):
        return rows[0]
    return ordered[0]


def pick_loss(rows: list[dict], base_key: str, anomaly_key: str) -> dict | None:
    """挑出绝对减量最大的一行（基准期 − 异常期）。

    「失血对象」应当按减量排，而不是按期末余额排：按余额排会选到本来就体量小的对象，
    还可能选到逆势上涨的行，把「上涨」写成「失血」。
    """
    if not rows:
        return None
    return max(rows, key=lambda r: num(r.get(base_key)) - num(r.get(anomaly_key)))


def bullet(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items if i)
