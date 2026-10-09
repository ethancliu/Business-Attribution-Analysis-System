# -*- coding: utf-8 -*-
"""场景基类：把一次归因分析拆成可执行的步骤链。

一个场景回答三件事:
    1. 这个问题属于哪类业务（match_score 关键词路由）
    2. 要跑哪些步骤、每步调什么工具（build）
    3. 跑完的数据说明了什么（interpret -> 六大模块）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.analysis.tools.base import ToolContext, ToolResult


@dataclass
class Step:
    """一个分析步骤 = 一次工具调用。"""

    key: str
    title: str
    tool: str
    args: dict = field(default_factory=dict)
    # 该步骤产出证据的展示名（写入证据链 source_name）
    evidence_name: str = ""
    related_metric: str = ""
    confidence: float = 0.9
    # 失败是否中断整个任务（关键步骤失败则中断）
    critical: bool = False


@dataclass
class Interpretation:
    """六大模块的最终产物。"""

    problem_definition: str
    key_metrics: list[dict]
    evidence_list: list[dict]
    conclusion_text: str
    missing_data_text: str | None = None
    next_action_text: str | None = None


class Scenario:
    """业务场景基类。"""

    key: str = "generic"
    name: str = "通用经营归因"
    description: str = ""
    # 命中关键词（任一出现即计分）
    keywords: tuple[str, ...] = ()
    # 强特征词（命中权重更高）
    strong_keywords: tuple[str, ...] = ()

    # ------------------------------------------------------------------
    # 路由
    # ------------------------------------------------------------------

    @classmethod
    def match_score(cls, text: str) -> int:
        """按关键词命中数计分，强特征词权重 3。"""
        lowered = (text or "").lower()
        score = 0
        for kw in cls.strong_keywords:
            if kw.lower() in lowered:
                score += 3
        for kw in cls.keywords:
            if kw.lower() in lowered:
                score += 1
        return score

    # ------------------------------------------------------------------
    # 步骤链
    # ------------------------------------------------------------------

    def build(self, ctx: ToolContext, intent: dict) -> list[Step]:  # pragma: no cover - 抽象
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 解释
    # ------------------------------------------------------------------

    def interpret(
        self,
        ctx: ToolContext,
        intent: dict,
        results: dict[str, ToolResult],
        steps: list[Step],
    ) -> Interpretation:  # pragma: no cover - 抽象
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    @staticmethod
    def ok(results: dict[str, ToolResult], key: str) -> bool:
        r = results.get(key)
        return bool(r is not None and r.ok)

    @staticmethod
    def get(results: dict[str, ToolResult], key: str) -> ToolResult | None:
        return results.get(key)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Scenario {self.key}>"
