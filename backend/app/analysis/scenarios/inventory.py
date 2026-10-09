# -*- coding: utf-8 -*-
"""场景三：库存健康度与履约（缺货放大、库存积压、周转恶化）。"""

from __future__ import annotations

import logging

from app.analysis.scenarios.base import Interpretation, Scenario, Step
from app.analysis.scenarios.common import (
    anomaly_end,
    anomaly_period_text,
    anomaly_start,
    base_end,
    base_period_text,
    base_start,
    bullet,
    compare_period_text,
    evidence,
    metric,
    num,
    pct,
    pick,
    rate_drop,
    rows_of,
    rows_to_evidence,
)
from app.analysis.tools.base import ToolContext, ToolResult

logger = logging.getLogger(__name__)


class InventoryScenario(Scenario):
    key = "inventory"
    name = "库存与履约归因"
    description = "定位缺货、库存积压与周转恶化，区分「卖不动」与「供不上」"
    strong_keywords = ("库存", "缺货", "断货", "积压", "周转", "履约", "补货", "备货")
    keywords = (
        "在库", "安全库存", "售罄", "滞销", "仓库", "入库", "出库", "发货",
        "现货率", "可售", "sku 断货", "供给",
    )

    def build(self, ctx: ToolContext, intent: dict) -> list[Step]:
        bs, be = base_start(), base_end()
        as_, ae = anomaly_start(), anomaly_end()

        shortage_sql = f"""
            SELECT c.category_name,
                   COUNT(DISTINCT CASE WHEN i.stat_date BETWEEN '{bs}' AND '{be}'
                                       AND i.available_qty < i.safety_stock_qty
                                       THEN i.product_id END) AS base_shortage_sku,
                   COUNT(DISTINCT CASE WHEN i.stat_date BETWEEN '{as_}' AND '{ae}'
                                       AND i.available_qty < i.safety_stock_qty
                                       THEN i.product_id END) AS anomaly_shortage_sku,
                   COUNT(DISTINCT CASE WHEN i.stat_date BETWEEN '{as_}' AND '{ae}'
                                       THEN i.product_id END) AS total_sku
            FROM biz_inventory i
            JOIN biz_product p ON p.product_id = i.product_id
            JOIN biz_category c ON c.category_id = p.category_id
            GROUP BY c.category_name
            ORDER BY anomaly_shortage_sku DESC
        """

        turnover_sql = f"""
            SELECT c.category_name,
                   ROUND(AVG(i.on_hand_qty), 0) AS avg_on_hand_qty,
                   ROUND(AVG(i.locked_qty), 0) AS avg_locked_qty,
                   ROUND(AVG(s.avg_daily_sale), 2) AS avg_daily_sale,
                   ROUND(AVG(i.on_hand_qty) / NULLIF(AVG(s.avg_daily_sale), 0), 1) AS days_of_supply
            FROM biz_inventory i
            JOIN biz_product p ON p.product_id = i.product_id
            JOIN biz_category c ON c.category_id = p.category_id
            LEFT JOIN biz_sales s ON s.product_id = i.product_id AND s.stat_date = i.stat_date
            WHERE i.stat_date BETWEEN '{as_}' AND '{ae}'
            GROUP BY c.category_name
            ORDER BY days_of_supply DESC
        """

        detail_sql = f"""
            SELECT p.product_id,
                   p.product_name,
                   c.category_name,
                   i.stat_date,
                   i.on_hand_qty,
                   i.available_qty,
                   i.safety_stock_qty,
                   i.in_transit_qty
            FROM biz_inventory i
            JOIN biz_product p ON p.product_id = i.product_id
            JOIN biz_category c ON c.category_id = p.category_id
            WHERE i.stat_date = '{ae}'
              AND i.available_qty < i.safety_stock_qty
            ORDER BY (i.safety_stock_qty - i.available_qty) DESC
            LIMIT 12
        """

        flow_sql = f"""
            SELECT outbound_type,
                   SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN outbound_qty ELSE 0 END) AS base_qty,
                   SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN outbound_qty ELSE 0 END) AS anomaly_qty
            FROM biz_outbound
            GROUP BY outbound_type
            ORDER BY anomaly_qty DESC
        """

        return [
            Step(
                key="shortage",
                title="按品类统计低于安全库存的 SKU 数量变化",
                tool="db_query",
                args={"sql": shortage_sql, "limit": 20},
                evidence_name="品类缺货 SKU 统计（biz_inventory）",
                related_metric="缺货 SKU 数",
                confidence=0.95,
                critical=True,
            ),
            Step(
                key="turnover",
                title="计算各品类库存可支撑天数（周转效率）",
                tool="db_query",
                args={"sql": turnover_sql, "limit": 20},
                evidence_name="库存周转与可支撑天数（biz_inventory + biz_sales）",
                related_metric="库存可支撑天数",
                confidence=0.92,
            ),
            Step(
                key="shortage_detail",
                title="拉出异常期末缺口最大的商品明细",
                tool="db_query",
                args={"sql": detail_sql, "limit": 12},
                evidence_name="缺货商品明细（biz_inventory + biz_product）",
                related_metric="单 SKU 缺口",
                confidence=0.9,
            ),
            Step(
                key="flow",
                title="核对出库结构与流向变化",
                tool="db_query",
                args={"sql": flow_sql, "limit": 20},
                evidence_name="出库结构（biz_outbound）",
                related_metric="出库量",
                confidence=0.85,
            ),
            Step(
                key="artifact",
                title="把缺货缺口明细写出到会话工作区",
                tool="file_write",
                args={"file_name": "缺货缺口明细.csv", "content": "@shortage_detail", "format": "table"},
                evidence_name="分析中间产物",
                related_metric="分析过程留痕",
                confidence=0.8,
            ),
        ]

    def interpret(self, ctx, intent, results, steps) -> Interpretation:
        shortage_rows = rows_of(results.get("shortage"))
        turnover_rows = rows_of(results.get("turnover"))
        detail_rows = rows_of(results.get("shortage_detail"))
        flow_rows = rows_of(results.get("flow"))

        total_base_short = sum(num(r.get("base_shortage_sku"), 0) for r in shortage_rows)
        total_anom_short = sum(num(r.get("anomaly_shortage_sku"), 0) for r in shortage_rows)
        total_sku = max((num(r.get("total_sku"), 0) for r in shortage_rows), default=0)
        base_rate = (total_base_short / total_sku * 100) if total_sku else 0
        anom_rate = (total_anom_short / total_sku * 100) if total_sku else 0

        worst = pick(shortage_rows, "anomaly_shortage_sku", 0, above=True) or {}
        worst_name = worst.get("category_name", "主要品类")

        # 积压：可支撑天数过高
        overstock = pick(turnover_rows, "days_of_supply", 0, above=True) or {}
        overstock_days = num(overstock.get("days_of_supply"), 1)
        overstock_cat = overstock.get("category_name", "—")

        # 缺货：可支撑天数过低
        understock = pick(turnover_rows, "days_of_supply", 0, above=False) or {}
        understock_days = num(understock.get("days_of_supply"), 1)
        understock_cat = understock.get("category_name", "—")

        problem = (
            f"针对「{ctx.input_text.strip()}」，把问题界定为库存健康度问题：\n"
            f"异常期（{anomaly_period_text()}）低于安全库存的 SKU 占比由 {pct(base_rate)} 升至 {pct(anom_rate)}，"
            f"缺货 SKU 数从 {int(total_base_short)} 个增至 {int(total_anom_short)} 个，"
            f"其中「{worst_name}」缺口最大。"
        )

        metrics = [
            metric("低于安全库存 SKU 数", total_anom_short, "个", f"异常期 {anomaly_period_text()}"),
            metric("低于安全库存 SKU 数（基准）", total_base_short, "个", f"基准期 {base_period_text()}"),
            metric("缺货 SKU 占比", anom_rate, "%", f"异常期 {anomaly_period_text()}"),
            metric("缺货 SKU 占比变化", rate_drop(base_rate, anom_rate), "%", compare_period_text()),
            metric(f"{overstock_cat} 库存可支撑天数", overstock_days, "天", "积压最严重品类"),
            metric(f"{understock_cat} 库存可支撑天数", understock_days, "天", "缺货最严重品类"),
        ]

        evidences: list[dict] = []
        evidences.extend(rows_to_evidence(shortage_rows, "品类缺货 SKU 统计（biz_inventory）", "缺货 SKU 数", 0.95, 6))
        evidences.extend(rows_to_evidence(turnover_rows, "库存周转与可支撑天数", "库存可支撑天数", 0.92, 5))
        evidences.extend(rows_to_evidence(detail_rows, "缺货商品明细", "单 SKU 缺口", 0.9, 5))
        evidences.extend(rows_to_evidence(flow_rows, "出库结构（biz_outbound）", "出库量", 0.85, 4))

        conclusion = "\n\n".join([
            f"归因结论：本次问题呈现「结构性失衡」——总量不缺，但结构错配。"
            f"缺货 SKU 占比由 {pct(base_rate)} 升至 {pct(anom_rate)}，"
            f"同时「{overstock_cat}」的库存可支撑天数高达 {overstock_days:.1f} 天（严重积压），"
            f"而「{understock_cat}」仅 {understock_days:.1f} 天（随时断货）。",
            "具体表现：",
            bullet([
                f"缺货集中在「{worst_name}」，异常期有 {int(num(worst.get('anomaly_shortage_sku'), 0))} 个 SKU 低于安全库存；",
                f"积压最严重的是「{overstock_cat}」，平均在库 {int(num(overstock.get('avg_on_hand_qty'), 0))} 件，"
                f"按当前日均销量需 {overstock_days:.1f} 天才能消化；",
                f"出库结构以 {flow_rows[0].get('outbound_type') if flow_rows else '正常出库'} 为主，"
                f"说明货在动，但动到了错误的品类上。",
            ]),
            "因果链条：补货策略未按动销分层 → 畅销品补货不及时、滞销品持续入库 "
            "→ 畅销品缺货损失销售机会，滞销品占用现金与仓容 → 整体周转效率下降、履约体验变差。",
        ])

        missing = "\n".join([
            "以下数据缺口会限制结论精度：",
            bullet([
                "缺少采购在途订单的预计到货时间（biz_inventory.in_transit_qty 只有数量没有到货日）",
                "缺少缺货期间的「缺货损失金额」埋点，无法量化直接销售损失",
                "缺少仓库维度的人力与产能数据，无法区分「无货」与「有货但发不出」",
            ]),
        ])

        actions = bullet([
            f"**今天**：按「日均销量 × 30 天」重算安全库存，把「{worst_name}」中缺口最大的 "
            f"{min(len(detail_rows), 5)} 个 SKU 立刻加急补货；",
            f"**3 天内**：对「{overstock_cat}」启动促销/捆绑清库，目标把可支撑天数压到 45 天以内；",
            "**一周内**：建立 ABC 分层补货规则——A 类品（贡献 70% 销量）安全库存上浮 30%、"
            "补货周期缩短至 3 天；C 类品改为小批量高频补货，禁止大批量入库；",
            "**持续**：上线「缺货 SKU 数 / 库存可支撑天数」双指标日监控，任一品类可支撑天数低于 7 天或高于 90 天自动告警。",
        ])

        return Interpretation(
            problem_definition=problem,
            key_metrics=metrics,
            evidence_list=evidences,
            conclusion_text=conclusion,
            missing_data_text=missing,
            next_action_text=actions,
        )
