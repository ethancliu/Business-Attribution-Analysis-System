# -*- coding: utf-8 -*-
"""场景二：渠道投放效率恶化（CH03 信息流渠道 ROAS 崩塌）。

埋入的异常（database/05_demo_data.sql）:
    - 社媒-信息流渠道 ROAS 由 5.92 跌至 1.58
    - 同期花费基本持平（44.91 万 -> 46.13 万），排除「预算缩减」解释
    - 点击率下降而 CPC 上升，指向素材老化与流量质量下滑
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
    money,
    num,
    pct,
    pick,
    rate_drop,
    rows_of,
    rows_to_evidence,
)
from app.analysis.tools.base import ToolContext, ToolResult

logger = logging.getLogger(__name__)

TARGET_CHANNEL = "社媒-信息流"


class MarketScenario(Scenario):
    key = "market"
    name = "渠道投放效率归因"
    description = "定位渠道 ROAS / 投放效率恶化，区分「预算问题」与「流量质量与素材问题」"
    strong_keywords = ("roas", "投放", "广告", "渠道效率", "roi", "信息流", "竞价")
    keywords = (
        "渠道", "花费", "预算", "投放效率", "获客成本", "cac", "cpc", "cpm", "转化成本",
        "流量质量", "素材", "千次曝光", "拉新", "广告费", "推广",
    )

    # ------------------------------------------------------------------

    def build(self, ctx: ToolContext, intent: dict) -> list[Step]:
        bs, be = base_start(), base_end()
        as_, ae = anomaly_start(), anomaly_end()

        roas_sql = f"""
            SELECT ch.channel_name,
                   ch.channel_type,
                   ROUND(SUM(CASE WHEN d.stat_date BETWEEN '{bs}' AND '{be}' THEN d.spend ELSE 0 END), 2)
                       AS base_spend,
                   ROUND(SUM(CASE WHEN d.stat_date BETWEEN '{as_}' AND '{ae}' THEN d.spend ELSE 0 END), 2)
                       AS anomaly_spend,
                   ROUND(SUM(CASE WHEN d.stat_date BETWEEN '{bs}' AND '{be}' THEN s.gmv ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN d.stat_date BETWEEN '{bs}' AND '{be}' THEN d.spend ELSE 0 END), 0), 2)
                       AS base_roas,
                   ROUND(SUM(CASE WHEN d.stat_date BETWEEN '{as_}' AND '{ae}' THEN s.gmv ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN d.stat_date BETWEEN '{as_}' AND '{ae}' THEN d.spend ELSE 0 END), 0), 2)
                       AS anomaly_roas
            FROM biz_channel ch
            LEFT JOIN (
                SELECT channel_id, stat_date,
                       SUM(spend) AS spend, SUM(impression) AS impression,
                       SUM(click) AS click, SUM(new_customer) AS new_customer
                FROM biz_ad_delivery GROUP BY channel_id, stat_date
            ) d ON d.channel_id = ch.channel_id
            LEFT JOIN (
                SELECT channel_id, stat_date,
                       SUM(gmv) AS gmv, SUM(pay_amount) AS pay_amount, SUM(order_cnt) AS order_cnt
                FROM biz_sales_summary GROUP BY channel_id, stat_date
            ) s ON s.channel_id = ch.channel_id AND s.stat_date = d.stat_date
            GROUP BY ch.channel_name, ch.channel_type
            ORDER BY anomaly_roas ASC
        """

        efficiency_sql = f"""
            SELECT ch.channel_name,
                   ROUND(100 * SUM(CASE WHEN d.stat_date BETWEEN '{bs}' AND '{be}' THEN d.click ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN d.stat_date BETWEEN '{bs}' AND '{be}' THEN d.impression ELSE 0 END), 0), 3)
                       AS base_ctr_pct,
                   ROUND(100 * SUM(CASE WHEN d.stat_date BETWEEN '{as_}' AND '{ae}' THEN d.click ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN d.stat_date BETWEEN '{as_}' AND '{ae}' THEN d.impression ELSE 0 END), 0), 3)
                       AS anomaly_ctr_pct,
                   ROUND(SUM(CASE WHEN d.stat_date BETWEEN '{bs}' AND '{be}' THEN d.spend ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN d.stat_date BETWEEN '{bs}' AND '{be}' THEN d.click ELSE 0 END), 0), 2)
                       AS base_cpc,
                   ROUND(SUM(CASE WHEN d.stat_date BETWEEN '{as_}' AND '{ae}' THEN d.spend ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN d.stat_date BETWEEN '{as_}' AND '{ae}' THEN d.click ELSE 0 END), 0), 2)
                       AS anomaly_cpc,
                   ROUND(SUM(CASE WHEN d.stat_date BETWEEN '{bs}' AND '{be}' THEN d.spend ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN d.stat_date BETWEEN '{bs}' AND '{be}' THEN d.new_customer ELSE 0 END), 0), 2)
                       AS base_cac,
                   ROUND(SUM(CASE WHEN d.stat_date BETWEEN '{as_}' AND '{ae}' THEN d.spend ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN d.stat_date BETWEEN '{as_}' AND '{ae}' THEN d.new_customer ELSE 0 END), 0), 2)
                       AS anomaly_cac
            FROM biz_channel ch
            LEFT JOIN biz_ad_delivery d ON d.channel_id = ch.channel_id
            GROUP BY ch.channel_name
            ORDER BY anomaly_cac DESC
        """

        deal_sql = f"""
            SELECT ch.channel_name,
                   SUM(CASE WHEN s.stat_date BETWEEN '{bs}' AND '{be}' THEN s.order_cnt ELSE 0 END) AS base_order_cnt,
                   SUM(CASE WHEN s.stat_date BETWEEN '{as_}' AND '{ae}' THEN s.order_cnt ELSE 0 END) AS anomaly_order_cnt,
                   ROUND(SUM(CASE WHEN s.stat_date BETWEEN '{bs}' AND '{be}' THEN s.gmv ELSE 0 END), 2) AS base_gmv,
                   ROUND(SUM(CASE WHEN s.stat_date BETWEEN '{as_}' AND '{ae}' THEN s.gmv ELSE 0 END), 2) AS anomaly_gmv,
                   ROUND(SUM(CASE WHEN s.stat_date BETWEEN '{as_}' AND '{ae}' THEN s.refund_amount ELSE 0 END), 2)
                       AS anomaly_refund_amount
            FROM biz_channel ch
            LEFT JOIN biz_sales_summary s ON s.channel_id = ch.channel_id
            GROUP BY ch.channel_name
            ORDER BY anomaly_gmv ASC
        """

        return [
            Step(
                key="roas_by_channel",
                title="按渠道对比 ROAS 与投放花费（基准期 vs 异常期）",
                tool="db_query",
                args={"sql": roas_sql, "limit": 30},
                evidence_name="分渠道 ROAS 与花费对比（biz_ad_delivery + biz_sales_summary）",
                related_metric="渠道 ROAS",
                confidence=0.96,
                critical=True,
            ),
            Step(
                key="traffic_efficiency",
                title="拆解各渠道点击率、CPC 与单客获取成本",
                tool="db_query",
                args={"sql": efficiency_sql, "limit": 30},
                evidence_name="渠道流量效率指标（biz_ad_delivery）",
                related_metric="点击率 / CPC / CAC",
                confidence=0.93,
            ),
            Step(
                key="deal_quality",
                title="核对各渠道成交规模与退款金额",
                tool="db_query",
                args={"sql": deal_sql, "limit": 30},
                evidence_name="渠道成交与退款（biz_sales_summary）",
                related_metric="渠道 GMV / 退款额",
                confidence=0.9,
            ),
            Step(
                key="method_knowledge",
                title="检索知识库中关于 ROAS 诊断的分析口径",
                tool="text_search",
                args={"keyword": "ROAS", "scope": "knowledge", "limit": 5},
                evidence_name="知识库方法论检索",
                related_metric="分析方法论",
                confidence=0.8,
            ),
            Step(
                key="artifact",
                title="把分渠道 ROAS 对比写出到会话工作区",
                tool="file_write",
                args={"file_name": "分渠道ROAS对比.csv", "content": "@roas_by_channel", "format": "table"},
                evidence_name="分析中间产物",
                related_metric="分析过程留痕",
                confidence=0.8,
            ),
        ]

    # ------------------------------------------------------------------

    def interpret(
        self,
        ctx: ToolContext,
        intent: dict,
        results: dict[str, ToolResult],
        steps: list[Step],
    ) -> Interpretation:
        roas_rows = rows_of(results.get("roas_by_channel"))
        eff_rows = rows_of(results.get("traffic_efficiency"))
        deal_rows = rows_of(results.get("deal_quality"))

        worst = pick(roas_rows, "anomaly_roas", 0, above=False) or {}
        channel = worst.get("channel_name", TARGET_CHANNEL)

        base_roas = num(worst.get("base_roas"))
        anomaly_roas = num(worst.get("anomaly_roas"))
        roas_drop = rate_drop(base_roas, anomaly_roas)
        base_spend = num(worst.get("base_spend"))
        anomaly_spend = num(worst.get("anomaly_spend"))
        spend_change = rate_drop(base_spend, anomaly_spend)

        eff = next((r for r in eff_rows if r.get("channel_name") == channel), {})
        base_ctr = num(eff.get("base_ctr_pct"), 3)
        anomaly_ctr = num(eff.get("anomaly_ctr_pct"), 3)
        base_cpc = num(eff.get("base_cpc"))
        anomaly_cpc = num(eff.get("anomaly_cpc"))
        base_cac = num(eff.get("base_cac"))
        anomaly_cac = num(eff.get("anomaly_cac"))

        deal = next((r for r in deal_rows if r.get("channel_name") == channel), {})
        base_gmv = num(deal.get("base_gmv"))
        anomaly_gmv = num(deal.get("anomaly_gmv"))
        gmv_drop = rate_drop(base_gmv, anomaly_gmv)

        healthy = [
            r for r in roas_rows
            if r.get("channel_name") != channel and num(r.get("anomaly_roas")) > 0
        ]
        healthy_roas = [num(r.get("anomaly_roas")) for r in healthy]
        healthy_range = (
            f"{min(healthy_roas):.2f}~{max(healthy_roas):.2f}" if healthy_roas else "无对比数据"
        )

        problem = (
            f"针对「{ctx.input_text.strip()}」，先把问题界定为可验证的量化问题：\n"
            f"渠道「{channel}」的投放回报率 ROAS 在异常期（{anomaly_period_text()}）"
            f"由 {base_roas:.2f} 下滑至 {anomaly_roas:.2f}（相对变化 {roas_drop:.2f}%），"
            f"而同期投放花费仅变化 {spend_change:.2f}%（{money(base_spend)} → {money(anomaly_spend)}）。"
            f"因此问题不是「预算被砍」，而是「同样的钱买不到同样的成交」。"
        )

        metrics = [
            metric(f"{channel} ROAS", anomaly_roas, "倍", f"异常期 {anomaly_period_text()}"),
            metric(f"{channel} ROAS（基准）", base_roas, "倍", f"基准期 {base_period_text()}"),
            metric("ROAS 相对变化", roas_drop, "%", compare_period_text()),
            metric("投放花费变化", spend_change, "%", compare_period_text()),
            metric("异常期投放花费", anomaly_spend, "元", f"异常期 {anomaly_period_text()}"),
            metric("渠道点击率", anomaly_ctr, "%", compare_period_text()),
            metric("渠道点击率（基准）", base_ctr, "%", f"基准期 {base_period_text()}"),
            metric("单次点击成本 CPC", anomaly_cpc, "元", f"异常期 {anomaly_period_text()}"),
            metric("单次点击成本 CPC（基准）", base_cpc, "元", f"基准期 {base_period_text()}"),
            metric("新客获取成本 CAC", anomaly_cac, "元", f"异常期 {anomaly_period_text()}"),
            metric("新客获取成本 CAC（基准）", base_cac, "元", f"基准期 {base_period_text()}"),
            metric("渠道 GMV", anomaly_gmv, "元", f"异常期 {anomaly_period_text()}"),
            metric("其他渠道 ROAS 区间", healthy_range, "倍", f"异常期 {anomaly_period_text()}"),
        ]

        evidences: list[dict] = []
        evidences.extend(
            rows_to_evidence(
                roas_rows,
                "分渠道 ROAS 与花费对比（biz_ad_delivery + biz_sales_summary）",
                "渠道 ROAS",
                0.96,
                limit=6,
            )
        )
        evidences.extend(
            rows_to_evidence(
                eff_rows,
                "渠道流量效率指标（biz_ad_delivery）",
                "点击率 / CPC / CAC",
                0.93,
                limit=5,
            )
        )
        evidences.extend(
            rows_to_evidence(
                deal_rows,
                "渠道成交与退款（biz_sales_summary）",
                "渠道 GMV / 退款额",
                0.9,
                limit=5,
            )
        )
        evidences.append(
            evidence(
                "database",
                "渠道 ROAS 变化结论",
                f"花费 {money(base_spend)} → {money(anomaly_spend)}（{spend_change:+.2f}%），"
                f"GMV {money(base_gmv)} → {money(anomaly_gmv)}（{gmv_drop:+.2f}%），"
                f"ROAS {base_roas:.2f} → {anomaly_roas:.2f}（{roas_drop:+.2f}%）。"
                f"花费基本持平而 GMV 大幅下降，说明问题出在流量质量与转化效率，不是预算规模。",
                "渠道 GMV",
                0.95,
            )
        )

        kb = results.get("method_knowledge")
        if kb is not None and kb.ok and isinstance(kb.data, list):
            for hit in kb.data[:3]:
                evidences.append(
                    evidence(
                        "knowledge",
                        hit.get("source_name", "知识库"),
                        hit.get("snippet", ""),
                        "分析方法论",
                        0.8,
                    )
                )

        findings: list[str] = []
        if anomaly_ctr and base_ctr and anomaly_ctr < base_ctr:
            findings.append(
                f"点击率下滑：{pct(base_ctr, 3)} → {pct(anomaly_ctr, 3)}"
                f"（{rate_drop(base_ctr, anomaly_ctr):.2f}%），素材吸引力下降或人群定向漂移"
            )
        if anomaly_cpc and base_cpc and anomaly_cpc > base_cpc:
            findings.append(
                f"点击成本上升：CPC {base_cpc:.2f} 元 → {anomaly_cpc:.2f} 元"
                f"（+{rate_drop(base_cpc, anomaly_cpc):.2f}%），竞价环境或定向竞争加剧"
            )
        if anomaly_cac and base_cac and anomaly_cac > base_cac:
            findings.append(
                f"获客成本上升：CAC {base_cac:.2f} 元 → {anomaly_cac:.2f} 元"
                f"（+{rate_drop(base_cac, anomaly_cac):.2f}%），新客质量下降明显"
            )
        if gmv_drop < 0:
            findings.append(
                f"成交规模下滑：GMV {money(base_gmv)} → {money(anomaly_gmv)}（{gmv_drop:.2f}%）"
            )

        conclusion = "\n\n".join([
            f"归因结论：渠道「{channel}」的投放效率恶化是**流量质量与素材效率问题**，不是预算问题。"
            f"花费仅变化 {spend_change:+.2f}%，但 ROAS 从 {base_roas:.2f} 跌到 {anomaly_roas:.2f}"
            f"（{roas_drop:+.2f}%）；同期其他渠道 ROAS 仍在 {healthy_range} 的正常区间，"
            f"说明平台整体流量没有系统性贬值，问题集中在单一渠道的投放执行。",
            "具体证据支持以下判断：" if findings else "",
            bullet(findings),
            f"因果链条：素材老化 / 定向漂移 → 点击率 {pct(base_ctr, 3)} 降至 {pct(anomaly_ctr, 3)}、"
            f"CPC 升至 {anomaly_cpc:.2f} 元 → 单客获取成本由 {base_cac:.2f} 元升至 {anomaly_cac:.2f} 元 "
            f"→ 同样花费换来的 GMV 由 {money(base_gmv)} 降至 {money(anomaly_gmv)} → ROAS 崩塌。",
        ])

        missing = "\n".join([
            "以下数据缺口会限制结论的精度：",
            bullet([
                "缺少分广告计划的素材维度数据（素材上线时间、素材版本、投放人群包），无法定位到具体素材",
                "缺少竞品同期投放强度数据，无法量化竞价环境变化的影响权重",
                f"缺少「{channel}」渠道的落地页转化率埋点，无法区分「点击进来了不买」与「根本没点进来」",
            ]),
        ])

        actions = bullet([
            f"**紧急（24 小时内）**：暂停「{channel}」中 CPA 高于 {anomaly_cac:.0f} 元且近 7 日无转化的广告计划，"
            f"先止住无效消耗（按当前效率测算，可减少约 15% 的浪费花费）；",
            "**3 天内**：对该渠道做素材疲劳度排查，替换点击率低于渠道均值 70% 的素材，"
            "并重启 2~3 组历史高点击素材做 A/B 对照；",
            "**3 天内**：复核定向人群包，比对基准期的高价值人群与当前投放人群的重合度，"
            "重合度低于 60% 需重建人群包；",
            f"**一周内**：为该渠道设置 ROAS 熔断线（低于 {max(base_roas * 0.5, 1.5):.2f} 自动降预算 30% 并告警），"
            "避免再次出现「花了半个月才发现 ROI 已经腰斩」；",
            "**持续**：把 ROAS、CPC、CAC 三项指标纳入渠道日报，与 GMV 同屏监控。",
        ])

        return Interpretation(
            problem_definition=problem,
            key_metrics=metrics,
            evidence_list=evidences,
            conclusion_text=conclusion,
            missing_data_text=missing,
            next_action_text=actions,
        )
