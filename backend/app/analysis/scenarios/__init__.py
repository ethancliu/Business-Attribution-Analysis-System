# -*- coding: utf-8 -*-
"""业务场景包：六大专有场景 + 通用兜底场景 + 意图路由。"""

from app.analysis.scenarios.base import Interpretation, Scenario, Step  # noqa: F401
from app.analysis.scenarios.catalog import CatalogScenario  # noqa: F401
from app.analysis.scenarios.feedback import FeedbackScenario  # noqa: F401
from app.analysis.scenarios.generic import GenericScenario  # noqa: F401
from app.analysis.scenarios.growth import GrowthScenario  # noqa: F401
from app.analysis.scenarios.inventory import InventoryScenario  # noqa: F401
from app.analysis.scenarios.market import MarketScenario  # noqa: F401
from app.analysis.scenarios.refund import RefundScenario  # noqa: F401
from app.analysis.scenarios.registry import (  # noqa: F401
    all_scenarios,
    get_scenario,
    match_scores,
    parse_intent,
    route,
    scenario_metadata,
)

__all__ = [
    "Interpretation",
    "Scenario",
    "Step",
    "all_scenarios",
    "get_scenario",
    "match_scores",
    "parse_intent",
    "route",
    "scenario_metadata",
    "CatalogScenario",
    "FeedbackScenario",
    "GenericScenario",
    "GrowthScenario",
    "InventoryScenario",
    "MarketScenario",
    "RefundScenario",
]
