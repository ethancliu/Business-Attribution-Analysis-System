# -*- coding: utf-8 -*-
"""场景注册与意图路由。

路由策略:
    1. 对用户问题做关键词计分（强特征词权重 3，普通词权重 1）
    2. 得分最高且大于 0 的场景胜出
    3. 全部为 0 分时走通用场景
    4. 命中多个场景时，取分数最高者；同分则按注册顺序（越专有越靠前）
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.analysis.scenarios.base import Scenario
from app.analysis.scenarios.catalog import CatalogScenario
from app.analysis.scenarios.feedback import FeedbackScenario
from app.analysis.scenarios.generic import GenericScenario
from app.analysis.scenarios.growth import GrowthScenario
from app.analysis.scenarios.inventory import InventoryScenario
from app.analysis.scenarios.market import MarketScenario
from app.analysis.scenarios.refund import RefundScenario

logger = logging.getLogger(__name__)

# 注册顺序 = 优先级（专有场景在前，通用场景兜底）
_SCENARIO_CLASSES: tuple[type[Scenario], ...] = (
    CatalogScenario,
    MarketScenario,
    InventoryScenario,
    FeedbackScenario,
    RefundScenario,
    GrowthScenario,
    GenericScenario,
)

_INSTANCES: dict[str, Scenario] = {cls.key: cls() for cls in _SCENARIO_CLASSES}

# 意图中可识别的实体（用于把问题里的限定条件传给场景）
_CATEGORY_HINT = re.compile(r"(美妆|个护|服装|食品|家居|数码|母婴|运动)")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_DAYS = re.compile(r"(\d{1,2})\s*(?:月|月份)")
_DATE_RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*[~至到-]\s*(\d{4}-\d{2}-\d{2})")


def all_scenarios() -> list[Scenario]:
    return list(_INSTANCES.values())


def scenario_metadata() -> list[dict]:
    """给管理控制台与文档用的场景清单。"""
    return [
        {
            "key": s.key,
            "name": s.name,
            "description": s.description,
            "strong_keywords": list(s.strong_keywords),
            "keywords": list(s.keywords),
            "is_fallback": s.key == "generic",
        }
        for s in _INSTANCES.values()
    ]


def get_scenario(key: str) -> Scenario:
    return _INSTANCES.get(key) or _INSTANCES["generic"]


def parse_intent(text: str) -> dict[str, Any]:
    """从问题文本中抽取限定条件（品类 / 阈值 / 时间 / 关键词）。"""
    raw = text or ""
    intent: dict[str, Any] = {"raw": raw}

    cat = _CATEGORY_HINT.search(raw)
    if cat:
        intent["category_hint"] = cat.group(1)

    pct = _PERCENT.search(raw)
    if pct:
        intent["threshold_pct"] = float(pct.group(1))

    rng = _DATE_RANGE.search(raw)
    if rng:
        intent["date_start"], intent["date_end"] = rng.group(1), rng.group(2)

    # 检索关键词：取文本中最长的中文片段作为文本检索词
    zh_chunks = re.findall(r"[一-龥]{2,}", raw)
    if zh_chunks:
        intent["keyword"] = max(zh_chunks, key=len)[:12]

    return intent


def route(text: str) -> tuple[Scenario, dict[str, Any], list[dict]]:
    """路由到场景，返回 (场景实例, 意图, 得分明细)。"""
    scores: list[dict] = []
    best: Scenario | None = None
    best_score = -1

    for cls in _SCENARIO_CLASSES:
        score = cls.match_score(text)
        scores.append({"key": cls.key, "name": cls.name, "score": score})
        if score > best_score:
            best_score = score
            best = cls

    if best is None or best_score <= 0:
        best = GenericScenario
        logger.info("问题未命中专有场景，走通用体检路径：%s", (text or "")[:60])
    else:
        logger.info("问题路由到场景「%s」（得分 %s）：%s", best.name, best_score, (text or "")[:60])

    scenario = _INSTANCES[best.key]
    intent = parse_intent(text)
    intent["scenario_key"] = scenario.key
    intent["scenario_name"] = scenario.name
    intent["route_scores"] = sorted(scores, key=lambda x: x["score"], reverse=True)

    return scenario, intent, scores


def match_scores(text: str) -> list[dict]:
    return [
        {"key": cls.key, "name": cls.name, "score": cls.match_score(text)}
        for cls in _SCENARIO_CLASSES
    ]
