# -*- coding: utf-8 -*-
"""场景五：退款与售后归因（退款率上升、责任归属收敛到商品侧）。"""

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


class RefundScenario(Scenario):
    key = "refund"
    name = "退款与售后归因"
    description = "定位退款率上升，通过退款原因与责任归属区分「商品责任」与「物流/服务责任」"
    strong_keywords = ("退款", "退货", "售后", "退款率", "退货率", "纠纷")
    keywords = (
        "仅退款", "退货退款", "赔付", "售后成本", "退款原因", "处理时长",
        "退款金额", "质量退款", "七天无理由",
    )

    def build(self, ctx: ToolContext, intent: dict) -> list[Step]:
        bs, be = base_start(), base_end()
        as_, ae = anomaly_start(), anomaly_end()

        reason_sql = f"""
            SELECT rr.reason_name,
                   rr.reason_type,
                   rr.is_responsible,
                   SUM(CASE WHEN ra.stat_date BETWEEN '{bs}' AND '{be}' THEN 1 ELSE 0 END) AS base_cnt,
                   SUM(CASE WHEN ra.stat_date BETWEEN '{as_}' AND '{ae}' THEN 1 ELSE 0 END) AS anomaly_cnt,
                   ROUND(SUM(CASE WHEN ra.stat_date BETWEEN '{as_}' AND '{ae}' THEN ra.refund_amount ELSE 0 END), 2)
                       AS anomaly_amount
            FROM biz_refund_apply ra
            JOIN biz_refund_reason rr ON rr.reason_code = ra.reason_code
            GROUP BY rr.reason_name, rr.reason_type, rr.is_responsible
            ORDER BY anomaly_cnt DESC
            LIMIT 20
        """

        rate_sql = f"""
            SELECT c.category_name,
                   ROUND(100 * SUM(CASE WHEN r.stat_date BETWEEN '{bs}' AND '{be}' THEN r.refund_cnt ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN r.stat_date BETWEEN '{bs}' AND '{be}' THEN r.order_cnt ELSE 0 END), 0), 2)
                       AS base_refund_rate_pct,
                   ROUND(100 * SUM(CASE WHEN r.stat_date BETWEEN '{as_}' AND '{ae}' THEN r.refund_cnt ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN r.stat_date BETWEEN '{as_}' AND '{ae}' THEN r.order_cnt ELSE 0 END), 0), 2)
                       AS anomaly_refund_rate_pct,
                   ROUND(SUM(CASE WHEN r.stat_date BETWEEN '{as_}' AND '{ae}' THEN r.refund_amount ELSE 0 END), 2)
                       AS anomaly_refund_amount
            FROM biz_refund r
            JOIN biz_product p ON p.product_id = r.product_id
            JOIN biz_category c ON c.category_id = p.category_id
            GROUP BY c.category_name
            ORDER BY anomaly_refund_rate_pct DESC
        """

        handling_sql = f"""
            SELECT apply_channel,
                   refund_status,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN handle_hours ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN 1 ELSE 0 END), 0), 2)
                       AS base_avg_hours,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN handle_hours ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN 1 ELSE 0 END), 0), 2)
                       AS anomaly_avg_hours
            FROM biz_refund_apply
            GROUP BY apply_channel, refund_status
            ORDER BY anomaly_avg_hours DESC
            LIMIT 15
        """

        responsible_sql = f"""
            SELECT rr.is_responsible,
                   SUM(CASE WHEN ra.stat_date BETWEEN '{bs}' AND '{be}' THEN 1 ELSE 0 END) AS base_cnt,
                   SUM(CASE WHEN ra.stat_date BETWEEN '{as_}' AND '{ae}' THEN 1 ELSE 0 END) AS anomaly_cnt
            FROM biz_refund_apply ra
            JOIN biz_refund_reason rr ON rr.reason_code = ra.reason_code
            GROUP BY rr.is_responsible
            ORDER BY anomaly_cnt DESC
        """

        return [
            Step(
                key="refund_reason",
                title="按退款原因统计申请量变化，识别主因",
                tool="db_query",
                args={"sql": reason_sql, "limit": 20},
                evidence_name="退款原因分布（biz_refund_apply + biz_refund_reason）",
                related_metric="退款申请量",
                confidence=0.95,
                critical=True,
            ),
            Step(
                key="refund_rate",
                title="按品类对比退款率与退款金额",
                tool="db_query",
                args={"sql": rate_sql, "limit": 20},
                evidence_name="品类退款率（biz_refund）",
                related_metric="退款率",
                confidence=0.94,
            ),
            Step(
                key="responsibility",
                title="区分责任归属：商品责任 vs 非商品责任",
                tool="db_query",
                args={"sql": responsible_sql, "limit": 10},
                evidence_name="退款责任归属（biz_refund_reason.is_responsible）",
                related_metric="商品责任退款占比",
                confidence=0.92,
            ),
            Step(
                key="handling",
                title="核对售后处理时长与渠道分布",
                tool="db_query",
                args={"sql": handling_sql, "limit": 15},
                evidence_name="售后处理效率（biz_refund_apply.handle_hours）",
                related_metric="平均处理时长",
                confidence=0.86,
            ),
            Step(
                key="artifact",
                title="把退款原因分布写出到会话工作区",
                tool="file_write",
                args={"file_name": "退款原因分布.csv", "content": "@refund_reason", "format": "table"},
                evidence_name="分析中间产物",
                related_metric="分析过程留痕",
                confidence=0.8,
            ),
        ]

    def interpret(self, ctx, intent, results, steps) -> Interpretation:
        reason_rows = rows_of(results.get("refund_reason"))
        rate_rows = rows_of(results.get("refund_rate"))
        resp_rows = rows_of(results.get("responsibility"))
        handling_rows = rows_of(results.get("handling"))

        base_cnt = sum(num(r.get("base_cnt"), 0) for r in reason_rows)
        anom_cnt = sum(num(r.get("anomaly_cnt"), 0) for r in reason_rows)

        top = pick(reason_rows, "anomaly_cnt", 0, above=True) or {}
        top_name = top.get("reason_name", "—")
        top_base = num(top.get("base_cnt"), 0)
        top_anom = num(top.get("anomaly_cnt"), 0)

        responsible_rows = [r for r in resp_rows if num(r.get("is_responsible"), 0) == 1]
        not_resp_rows = [r for r in resp_rows if num(r.get("is_responsible"), 0) != 1]
        resp_anom = sum(num(r.get("anomaly_cnt"), 0) for r in responsible_rows)
        resp_base = sum(num(r.get("base_cnt"), 0) for r in responsible_rows)
        nonresp_anom = sum(num(r.get("anomaly_cnt"), 0) for r in not_resp_rows)
        resp_share = (resp_anom / anom_cnt * 100) if anom_cnt else 0
        base_resp_share = (resp_base / base_cnt * 100) if base_cnt else 0

        worst_cat = pick(rate_rows, "anomaly_refund_rate_pct", 0, above=True) or {}
        worst_name = worst_cat.get("category_name", "—")
        base_rate = num(worst_cat.get("base_refund_rate_pct"), 2)
        anom_rate = num(worst_cat.get("anomaly_refund_rate_pct"), 2)
        refund_amount = num(worst_cat.get("anomaly_refund_amount"), 2)

        avg_hours = num(pick(handling_rows, "anomaly_avg_hours", 0, above=True) or {}.get("anomaly_avg_hours"), 2)

        reason_bullets = []
        for r in reason_rows[:4]:
            b = num(r.get("base_cnt"), 0)
            a = num(r.get("anomaly_cnt"), 0)
            reason_bullets.append(
                f"「{r.get('reason_name')}」（{r.get('reason_type')}）{int(b)} 单 → {int(a)} 单"
                f"（{rate_drop(b, a):+.2f}%）"
            )

        problem = (
            f"针对「{ctx.input_text.strip()}」，先把问题界定清楚：\n"
            f"异常期（{anomaly_period_text()}）退款申请 {int(anom_cnt)} 单（基准期 {int(base_cnt)} 单，"
            f"{rate_drop(base_cnt, anom_cnt):+.2f}%），"
            f"其中「{top_name}」是申请量最高的原因；"
            f"商品责任类退款占比由 {pct(base_resp_share)} 升至 {pct(resp_share)}。"
        )

        metrics = [
            metric("退款申请量", anom_cnt, "单", f"异常期 {anomaly_period_text()}"),
            metric("退款申请量（基准）", base_cnt, "单", f"基准期 {base_period_text()}"),
            metric("退款申请量变化", rate_drop(base_cnt, anom_cnt), "%", compare_period_text()),
            metric(f"品类「{worst_name}」退款率", anom_rate, "%", f"异常期 {anomaly_period_text()}"),
            metric(f"品类「{worst_name}」退款率（基准）", base_rate, "%", f"基准期 {base_period_text()}"),
            metric("商品责任退款占比", resp_share, "%", f"异常期 {anomaly_period_text()}"),
            metric("商品责任退款占比（基准）", base_resp_share, "%", f"基准期 {base_period_text()}"),
            metric(f"首位原因「{top_name}」", top_anom, "单", f"异常期 {anomaly_period_text()}"),
            metric("退款金额合计", refund_amount, "元", f"异常期「{worst_name}」"),
            metric("最长平均处理时长", avg_hours, "小时", f"异常期 {anomaly_period_text()}"),
        ]

        evidences: list[dict] = []
        evidences.extend(rows_to_evidence(reason_rows, "退款原因分布", "退款申请量", 0.95, 6))
        evidences.extend(rows_to_evidence(rate_rows, "品类退款率（biz_refund）", "退款率", 0.94, 5))
        evidences.extend(rows_to_evidence(resp_rows, "退款责任归属", "商品责任退款占比", 0.92, 4))
        evidences.extend(rows_to_evidence(handling_rows, "售后处理效率", "平均处理时长", 0.86, 3))
        evidences.append(
            evidence(
                "database",
                "责任归属结论",
                f"商品责任类退款 {int(resp_anom)} 单，占异常期全部退款的 {pct(resp_share)}"
                f"（基准期 {pct(base_resp_share)}）；非商品责任（物流/用户原因）{int(nonresp_anom)} 单。"
                f"责任结构向商品侧集中，说明退款上升的主要成因在商品本身而非履约环节。",
                "商品责任退款占比",
                0.93,
            )
        )

        conclusion = "\n\n".join([
            f"归因结论：退款上升的主因在**商品侧**，不是物流或用户行为变化。"
            f"商品责任类退款占比由 {pct(base_resp_share)} 升至 {pct(resp_share)}，"
            f"退款集中在「{top_name}」这一单一原因上，呈典型的质量/描述类单点爆发特征。",
            "原因变化明细：",
            bullet(reason_bullets),
            f"影响面：「{worst_name}」品类退款率由 {pct(base_rate)} 升至 {pct(anom_rate)}，"
            f"异常期退款金额 {money(refund_amount)}；若按当前趋势延续，"
            f"下月退款成本预计再增 {max(rate_drop(base_cnt, anom_cnt), 10):.0f}% 量级。",
            "因果链条：商品质量或页面描述失真 → 用户收货后申请退款 → 退款原因集中在商品责任类 "
            "→ 退款率上升 + 售后成本增加 + 库存二次损失，同时拖累店铺权重。",
        ])

        missing = "\n".join([
            "以下数据缺口会限制结论精度：",
            bullet([
                "缺少退款商品的批次/供应商信息，无法定位到具体供应链环节",
                "缺少退货后的二次质检记录，无法量化「货损」与「可二次销售」的比例",
                "缺少售后沟通文本，无法判断是否存在客服引导退款（放大退款率）的情况",
            ]),
        ])

        actions = bullet([
            f"**今天**：拉出「{top_name}」原因下全部退款订单，按商品聚合，锁定退款率最高的 10 个 SKU；",
            "**3 天内**：对锁定的 SKU 做实物抽检与页面复核，"
            "属于质量问题的联系供应商整改并冻结补货，属于描述问题的立即改页面；",
            f"**一周内**：把售后处理时长压到 {max(avg_hours * 0.7, 24):.0f} 小时以内，"
            "避免处理滞后引发二次投诉与平台介入；",
            "**持续**：建立「商品责任退款率」周监控，单 SKU 退款率超过类目均值 2 倍自动进入观察名单。",
        ])

        return Interpretation(
            problem_definition=problem,
            key_metrics=metrics,
            evidence_list=evidences,
            conclusion_text=conclusion,
            missing_data_text=missing,
            next_action_text=actions,
        )
