# -*- coding: utf-8 -*-
"""兜底场景：未命中任何专有场景时，执行通用经营体检。

通用路径刻意保持「可解释」：先看大盘、再看渠道与品类结构、最后检索方法论与历史上下文，
即使问题超出预置场景，也能给出有数据支撑的初步结论与下一步验证方向。
"""

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
    first_row,
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


class GenericScenario(Scenario):
    key = "generic"
    name = "通用经营体检"
    description = "未命中专有场景时的通用路径：大盘概览 + 渠道结构 + 品类结构 + 方法论检索"
    keywords = ()
    strong_keywords = ()

    def build(self, ctx: ToolContext, intent: dict) -> list[Step]:
        bs, be = base_start(), base_end()
        as_, ae = anomaly_start(), anomaly_end()
        # 通用场景检索的是分析方法论，用「归因」这类稳定术语，
        # 而不是把用户提问整句当关键词（那样命不中任何知识条目）
        keyword = "归因"

        overview_sql = f"""
            SELECT ROUND(SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN gmv ELSE 0 END), 2) AS base_gmv,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN gmv ELSE 0 END), 2) AS anomaly_gmv,
                   SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN order_cnt ELSE 0 END) AS base_order_cnt,
                   SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN order_cnt ELSE 0 END) AS anomaly_order_cnt,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN refund_amount ELSE 0 END), 2) AS base_refund,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN refund_amount ELSE 0 END), 2) AS anomaly_refund
            FROM biz_sales_summary
        """

        channel_sql = f"""
            SELECT ch.channel_name, ch.channel_type,
                   ROUND(SUM(CASE WHEN s.stat_date BETWEEN '{bs}' AND '{be}' THEN s.gmv ELSE 0 END), 2) AS base_gmv,
                   ROUND(SUM(CASE WHEN s.stat_date BETWEEN '{as_}' AND '{ae}' THEN s.gmv ELSE 0 END), 2) AS anomaly_gmv
            FROM biz_channel ch
            LEFT JOIN biz_sales_summary s ON s.channel_id = ch.channel_id
            GROUP BY ch.channel_name, ch.channel_type
            ORDER BY anomaly_gmv DESC
        """

        category_sql = f"""
            SELECT c.category_name,
                   ROUND(SUM(CASE WHEN r.stat_date BETWEEN '{bs}' AND '{be}' THEN r.sale_amount ELSE 0 END), 2) AS base_amount,
                   ROUND(SUM(CASE WHEN r.stat_date BETWEEN '{as_}' AND '{ae}' THEN r.sale_amount ELSE 0 END), 2) AS anomaly_amount,
                   SUM(CASE WHEN r.stat_date BETWEEN '{as_}' AND '{ae}' THEN r.sale_qty ELSE 0 END) AS anomaly_qty
            FROM biz_sales r
            JOIN biz_category c ON c.category_id = r.category_id
            GROUP BY c.category_name
            ORDER BY anomaly_amount DESC
        """

        anomaly_sql = f"""
            SELECT c.category_name,
                   ROUND(AVG(p.title_length), 1) AS avg_title_len,
                   ROUND(AVG(p.image_count), 2) AS avg_image_cnt,
                   ROUND(AVG(p.attr_fill_rate), 1) AS avg_attr_fill
            FROM biz_product p
            JOIN biz_category c ON c.category_id = p.category_id
            GROUP BY c.category_name
            ORDER BY avg_attr_fill ASC
        """

        return [
            Step(
                key="overview",
                title="大盘经营概览（GMV / 订单 / 退款）",
                tool="db_query",
                args={"sql": overview_sql, "limit": 1},
                evidence_name="大盘经营概览（biz_sales_summary）",
                related_metric="GMV",
                confidence=0.94,
                critical=True,
            ),
            Step(
                key="channel",
                title="渠道结构拆分",
                tool="db_query",
                args={"sql": channel_sql, "limit": 20},
                evidence_name="渠道结构（biz_channel + biz_sales_summary）",
                related_metric="渠道 GMV",
                confidence=0.92,
            ),
            Step(
                key="category",
                title="品类结构拆分",
                tool="db_query",
                args={"sql": category_sql, "limit": 20},
                evidence_name="品类结构（biz_sales + biz_category）",
                related_metric="品类销售额",
                confidence=0.92,
            ),
            Step(
                key="quality_scan",
                title="商品目录质量体检（标题 / 主图 / 属性）",
                tool="db_query",
                args={"sql": anomaly_sql, "limit": 20},
                evidence_name="目录质量体检（biz_product）",
                related_metric="目录质量分",
                confidence=0.88,
            ),
            Step(
                key="knowledge",
                title=f"检索知识库中的「{keyword}」分析方法论",
                tool="text_search",
                args={"keyword": keyword, "scope": "knowledge", "limit": 5},
                evidence_name="知识库方法论检索",
                related_metric="分析方法论",
                confidence=0.8,
            ),
        ]

    def interpret(self, ctx, intent, results, steps) -> Interpretation:
        ov = first_row(results.get("overview"))
        channel_rows = rows_of(results.get("channel"))
        category_rows = rows_of(results.get("category"))
        quality_rows = rows_of(results.get("quality_scan"))

        base_gmv = num(ov.get("base_gmv"))
        anom_gmv = num(ov.get("anomaly_gmv"))
        gmv_drop = rate_drop(base_gmv, anom_gmv)
        base_orders = num(ov.get("base_order_cnt"))
        anom_orders = num(ov.get("anomaly_order_cnt"))
        order_drop = rate_drop(base_orders, anom_orders)
        base_refund = num(ov.get("base_refund"))
        anom_refund = num(ov.get("anomaly_refund"))
        refund_change = rate_drop(base_refund, anom_refund)

        top_channel = pick(channel_rows, "anomaly_gmv", 0, above=True) or {}
        worst_channel = pick(channel_rows, "anomaly_gmv", 0, above=False) or {}
        top_category = pick(category_rows, "anomaly_amount", 0, above=True) or {}
        low_quality = pick(quality_rows, "avg_attr_fill", 0, above=False) or {}

        answered = bool(results.get("overview") and results["overview"].ok)

        problem = (
            f"问题界定：用户提出「{ctx.input_text.strip()}」。"
            f"该问题未命中系统预置的六大专有归因场景（商品目录质量 / 渠道投放效率 / 库存履约 / "
            f"用户口碑 / 退款售后 / 大盘下滑），因此系统走通用经营体检路径："
            f"先用大盘、渠道、品类三层结构定位异常区域，再给出进一步验证方向。"
        )

        metrics = [
            metric("GMV", anom_gmv, "元", f"异常期 {anomaly_period_text()}"),
            metric("GMV 变化", gmv_drop, "%", compare_period_text()),
            metric("订单量变化", order_drop, "%", compare_period_text()),
            metric("退款金额变化", refund_change, "%", compare_period_text()),
            metric("最大渠道", top_channel.get("channel_name", "—"), "", "按异常期 GMV"),
            metric("跌幅最大渠道", worst_channel.get("channel_name", "—"), "", "按异常期 GMV"),
            metric("最大品类", top_category.get("category_name", "—"), "", "按异常期销售额"),
            metric("属性填充率最低品类", low_quality.get("category_name", "—"), "", "目录质量体检"),
            metric("该品类属性填充率", num(low_quality.get("avg_attr_fill"), 1), "%", "目录质量体检"),
        ]

        evidences: list[dict] = [
            evidence(
                "database",
                "大盘经营概览（biz_sales_summary）",
                "；".join(f"{k} = {v}" for k, v in ov.items()) or "未取得数据",
                "GMV",
                0.94,
            )
        ]
        evidences.extend(rows_to_evidence(channel_rows, "渠道结构", "渠道 GMV", 0.92, 6))
        evidences.extend(rows_to_evidence(category_rows, "品类结构", "品类销售额", 0.92, 6))
        evidences.extend(rows_to_evidence(quality_rows, "目录质量体检", "目录质量分", 0.88, 5))

        kb = results.get("knowledge")
        if kb is not None and kb.ok and isinstance(kb.data, list):
            for hit in kb.data[:4]:
                evidences.append(
                    evidence("knowledge", hit.get("source_name", "知识库"), hit.get("snippet", ""), "分析方法论", 0.8)
                )

        conclusion = "\n\n".join([
            "结论：本轮走通用体检路径，得出的是**结构性观察**而非确定性归因。",
            bullet([
                f"大盘：GMV 由 {base_gmv:,.2f} 元变为 {anom_gmv:,.2f} 元（{gmv_drop:+.2f}%），"
                f"订单量变化 {order_drop:+.2f}%，退款金额变化 {refund_change:+.2f}%；",
                f"渠道：GMV 最高的是「{top_channel.get('channel_name', '—')}」，"
                f"最低的是「{worst_channel.get('channel_name', '—')}」，渠道间差距明显，"
                f"建议优先复核低贡献渠道的投放与承接效率；",
                f"品类：销售额最高的是「{top_category.get('category_name', '—')}」，"
                f"目录质量最弱的是「{low_quality.get('category_name', '—')}」"
                f"（属性填充率仅 {num(low_quality.get('avg_attr_fill'), 1)}%），"
                f"该品类存在「有货但卖不动」的典型特征。",
            ]),
            "未能给出确定性归因的原因：本轮问题未匹配到预置场景的知识规则，"
            "系统只做了结构性扫描，没有执行场景化的深度下钻（如漏斗拆解、责任归属判定）。",
        ])

        missing = "\n".join([
            "要把结论升级为确定性归因，还需要补充：",
            bullet([
                "更明确的问题边界（具体指标、时间范围、影响对象），以便路由到专有场景做深度下钻",
                "对应的业务明细数据（如订单明细、流量来源明细、操作日志）",
                "若有相关报表或截图，可通过附件上传，系统会纳入证据链一起分析",
            ]),
        ])

        actions = bullet([
            "**建议 1**：把问题改写得更具体，例如「美妆个护品类 9 月下旬点击率为什么从 4.2% 掉到 2.1%」，"
            "系统会自动路由到专有场景并给出确定性归因；",
            "**建议 2**：先针对上方「最低贡献渠道」与「目录质量最弱品类」做一次专项排查；",
            "**建议 3**：上传相关明细文件（CSV/Excel）后再次提问，可显著提升归因精度；",
            "**建议 4**：若属于新业务场景，可把该问题沉淀为新的场景规则，"
            "后续同类问题即可自动完成完整归因。",
        ])

        return Interpretation(
            problem_definition=problem,
            key_metrics=metrics,
            evidence_list=evidences,
            conclusion_text=conclusion,
            missing_data_text=missing,
            next_action_text=actions,
        )
