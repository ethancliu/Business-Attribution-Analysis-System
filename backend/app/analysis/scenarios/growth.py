# -*- coding: utf-8 -*-
"""场景六：大盘经营下滑归因（GMV 下滑、流量与转化双降）。

归因框架：先把 GMV 拆成「流量 × 转化率 × 客单价」三因子，
再逐步下钻到渠道 / 品类 / 用户结构，最后定位到可控动作。
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
    pick_loss,
    rate_drop,
    rows_of,
    rows_to_evidence,
)
from app.analysis.tools.base import ToolContext, ToolResult

logger = logging.getLogger(__name__)


def _structure_phrase(label: str, name: str, base: float, anom: float, drop: float, loss: float) -> str:
    """按实际方向描述结构下钻结果。

    减量为正才说「降至」与「绝对减量」，否则如实写成没有出现绝对减量，
    避免把逆势上涨的渠道/品类写成「失血」。
    """
    if loss > 0:
        return f"{label}「{name}」由 {money(base)} 降至 {money(anom)}（{drop:+.2f}%），绝对减量 {money(loss)}"
    return f"{label}「{name}」由 {money(base)} 变为 {money(anom)}（{drop:+.2f}%），本期未出现绝对减量"


class GrowthScenario(Scenario):
    key = "growth"
    name = "大盘经营下滑归因"
    description = "GMV 三因子拆解（流量 × 转化 × 客单价）并下钻到渠道与品类"
    strong_keywords = ("gmv", "销售额", "营业额", "大盘", "整体下滑", "业绩", "营收", "成交额")
    keywords = (
        "下滑", "下降", "跌", "环比", "同比", "订单量", "客单价", "流量",
        "转化率", "复购", "为什么降", "经营分析", "业绩下滑",
    )

    def build(self, ctx: ToolContext, intent: dict) -> list[Step]:
        bs, be = base_start(), base_end()
        as_, ae = anomaly_start(), anomaly_end()

        overview_sql = f"""
            SELECT ROUND(SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN gmv ELSE 0 END), 2) AS base_gmv,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN gmv ELSE 0 END), 2) AS anomaly_gmv,
                   SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN order_cnt ELSE 0 END) AS base_order_cnt,
                   SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN order_cnt ELSE 0 END) AS anomaly_order_cnt,
                   SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN active_user ELSE 0 END) AS base_active_user,
                   SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN active_user ELSE 0 END) AS anomaly_active_user,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN refund_amount ELSE 0 END), 2)
                       AS anomaly_refund_amount
            FROM biz_sales_summary
        """

        traffic_sql = f"""
            SELECT ROUND(SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN pv ELSE 0 END), 0) AS base_pv,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN pv ELSE 0 END), 0) AS anomaly_pv,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN visit_cnt ELSE 0 END), 0) AS base_visit,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN visit_cnt ELSE 0 END), 0) AS anomaly_visit,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN duration_sec ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN visit_cnt ELSE 0 END), 0), 1)
                       AS base_avg_duration,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN duration_sec ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN visit_cnt ELSE 0 END), 0), 1)
                       AS anomaly_avg_duration
            FROM biz_visit_event
        """

        cart_sql = f"""
            SELECT ROUND(SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN add_cart_cnt ELSE 0 END), 0) AS base_add_cart,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN add_cart_cnt ELSE 0 END), 0) AS anomaly_add_cart,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN abandon_cnt ELSE 0 END), 0) AS base_abandon,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN abandon_cnt ELSE 0 END), 0) AS anomaly_abandon,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN cart_amount ELSE 0 END), 2) AS base_cart_amount,
                   ROUND(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN cart_amount ELSE 0 END), 2) AS anomaly_cart_amount
            FROM biz_cart_event
        """

        # 下单转化率必须用同一张表里的「点击 → 下单」漏斗，分子分母口径才一致。
        # biz_visit_event 是按客户聚合的访问表（每客户每天一行），
        # 用它当分母会算出订单数大于访问次数的荒谬转化率。
        funnel_sql = f"""
            SELECT SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN click_cnt ELSE 0 END) AS base_click,
                   SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN click_cnt ELSE 0 END) AS anomaly_click,
                   SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN cart_cnt ELSE 0 END) AS base_cart,
                   SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN cart_cnt ELSE 0 END) AS anomaly_cart,
                   SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN order_cnt ELSE 0 END) AS base_order,
                   SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN order_cnt ELSE 0 END) AS anomaly_order
            FROM biz_product_conversion
        """

        channel_sql = f"""
            SELECT ch.channel_name,
                   ROUND(SUM(CASE WHEN s.stat_date BETWEEN '{bs}' AND '{be}' THEN s.gmv ELSE 0 END), 2) AS base_gmv,
                   ROUND(SUM(CASE WHEN s.stat_date BETWEEN '{as_}' AND '{ae}' THEN s.gmv ELSE 0 END), 2) AS anomaly_gmv,
                   SUM(CASE WHEN s.stat_date BETWEEN '{as_}' AND '{ae}' THEN s.order_cnt ELSE 0 END) AS anomaly_order_cnt
            FROM biz_channel ch
            LEFT JOIN biz_sales_summary s ON s.channel_id = ch.channel_id
            GROUP BY ch.channel_name
            ORDER BY anomaly_gmv ASC
        """

        category_sql = f"""
            SELECT c.category_name,
                   ROUND(SUM(CASE WHEN r.stat_date BETWEEN '{bs}' AND '{be}' THEN r.sale_amount ELSE 0 END), 2) AS base_amount,
                   ROUND(SUM(CASE WHEN r.stat_date BETWEEN '{as_}' AND '{ae}' THEN r.sale_amount ELSE 0 END), 2) AS anomaly_amount,
                   SUM(CASE WHEN r.stat_date BETWEEN '{as_}' AND '{ae}' THEN r.sale_qty ELSE 0 END) AS anomaly_qty
            FROM biz_sales r
            JOIN biz_category c ON c.category_id = r.category_id
            GROUP BY c.category_name
            ORDER BY anomaly_amount ASC
        """

        return [
            Step(
                key="overview",
                title="汇总大盘 GMV、订单量与活跃用户，计算整体变化",
                tool="db_query",
                args={"sql": overview_sql, "limit": 1},
                evidence_name="大盘经营总览（biz_sales_summary）",
                related_metric="GMV",
                confidence=0.96,
                critical=True,
            ),
            Step(
                key="traffic",
                title="核对流量规模与访问深度（PV / 访问次数 / 停留时长）",
                tool="db_query",
                args={"sql": traffic_sql, "limit": 1},
                evidence_name="流量规模与深度（biz_visit_event）",
                related_metric="流量 PV",
                confidence=0.94,
            ),
            Step(
                key="cart",
                title="拆解加购与购物车放弃率，定位转化断层",
                tool="db_query",
                args={"sql": cart_sql, "limit": 1},
                evidence_name="加购与放弃行为（biz_cart_event）",
                related_metric="购物车放弃率",
                confidence=0.92,
            ),
            Step(
                key="funnel",
                title="按「点击 → 加购 → 下单」漏斗核算下单转化率",
                tool="db_query",
                args={"sql": funnel_sql, "limit": 1},
                evidence_name="下单漏斗（biz_product_conversion）",
                related_metric="下单转化率",
                confidence=0.93,
            ),
            Step(
                key="channel",
                title="按渠道拆分 GMV 变化，定位失血渠道",
                tool="db_query",
                args={"sql": channel_sql, "limit": 20},
                evidence_name="分渠道 GMV 变化（biz_sales_summary）",
                related_metric="渠道 GMV",
                confidence=0.93,
            ),
            Step(
                key="category",
                title="按品类拆分销售额变化，定位失血品类",
                tool="db_query",
                args={"sql": category_sql, "limit": 20},
                evidence_name="分品类销售额变化（biz_sales）",
                related_metric="品类销售额",
                confidence=0.93,
            ),
            Step(
                key="artifact",
                title="把分渠道 GMV 变化写出到会话工作区",
                tool="file_write",
                args={"file_name": "分渠道GMV变化.csv", "content": "@channel", "format": "table"},
                evidence_name="分析中间产物",
                related_metric="分析过程留痕",
                confidence=0.8,
            ),
        ]

    def interpret(self, ctx, intent, results, steps) -> Interpretation:
        ov = first_row(results.get("overview"))
        tv = first_row(results.get("traffic"))
        cv = first_row(results.get("cart"))
        channel_rows = rows_of(results.get("channel"))
        category_rows = rows_of(results.get("category"))

        base_gmv = num(ov.get("base_gmv"))
        anom_gmv = num(ov.get("anomaly_gmv"))
        gmv_drop = rate_drop(base_gmv, anom_gmv)

        base_orders = num(ov.get("base_order_cnt"))
        anom_orders = num(ov.get("anomaly_order_cnt"))
        order_drop = rate_drop(base_orders, anom_orders)

        base_aov = (base_gmv / base_orders) if base_orders else 0
        anom_aov = (anom_gmv / anom_orders) if anom_orders else 0
        aov_drop = rate_drop(base_aov, anom_aov)

        base_pv = num(tv.get("base_pv"))
        anom_pv = num(tv.get("anomaly_pv"))
        pv_drop = rate_drop(base_pv, anom_pv)

        # ---- 三因子拆解只允许使用 biz_sales_summary 这一张表 ----
        # GMV = 活跃用户 × (订单/活跃用户) × (GMV/订单)
        # 三个因子同源，相乘才能精确还原 GMV 降幅；换成跨表取数
        # （例如拿另一张漏斗表的订单数当分子），拆出来的百分比相乘就对不上 GMV，
        # 结论无法自证，也没法解释给业务方看。
        base_active = num(ov.get("base_active_user"))
        anom_active = num(ov.get("anomaly_active_user"))
        traffic_drop = rate_drop(base_active, anom_active)

        base_cvr = (base_orders / base_active * 100) if base_active else 0
        anom_cvr = (anom_orders / anom_active * 100) if anom_active else 0
        cvr_drop = rate_drop(base_cvr, anom_cvr)

        base_visit = num(tv.get("base_visit"))
        anom_visit = num(tv.get("anomaly_visit"))
        visit_drop = rate_drop(base_visit, anom_visit)

        # 商品点击与加购漏斗来自 biz_product_conversion，与上面的销售汇总表口径不同，
        # 仅作下钻参考，不参与三因子恒等式。
        fn = first_row(results.get("funnel"))
        base_click = num(fn.get("base_click"))
        anom_click = num(fn.get("anomaly_click"))
        click_drop = rate_drop(base_click, anom_click)

        base_abandon_rate = (
            num(cv.get("base_abandon"), 0) / num(cv.get("base_add_cart"), 1) * 100
            if num(cv.get("base_add_cart"), 0) else 0
        )
        anom_abandon_rate = (
            num(cv.get("anomaly_abandon"), 0) / num(cv.get("anomaly_add_cart"), 1) * 100
            if num(cv.get("anomaly_add_cart"), 0) else 0
        )

        # 「失血」看的是绝对减量（基准期 − 异常期），不是期末余额最低。
        # 按期末余额挑会选到本来就体量小的对象，还会把逆势上涨的品类写成「失血」。
        worst_channel = pick_loss(channel_rows, "base_gmv", "anomaly_gmv") or {}
        channel_name = worst_channel.get("channel_name", "—")
        ch_base = num(worst_channel.get("base_gmv"))
        ch_anom = num(worst_channel.get("anomaly_gmv"))
        ch_drop = rate_drop(ch_base, ch_anom)
        ch_loss = ch_base - ch_anom
        ch_contribution = (ch_loss / (base_gmv - anom_gmv) * 100) if (base_gmv - anom_gmv) else 0

        worst_cat = pick_loss(category_rows, "base_amount", "anomaly_amount") or {}
        cat_name = worst_cat.get("category_name", "—")
        cat_base = num(worst_cat.get("base_amount"))
        cat_anom = num(worst_cat.get("anomaly_amount"))
        cat_drop = rate_drop(cat_base, cat_anom)
        cat_loss = cat_base - cat_anom

        # 标签随实际方向走：减量为正才叫「失血」，逆势上涨的如实写成「逆势上涨」
        loss_label_channel = "失血渠道" if ch_loss > 0 else "逆势上涨渠道"
        loss_label_cat = "失血品类" if cat_loss > 0 else "逆势上涨品类"

        # 三因子贡献拆解：三因子相乘应当还原 GMV 变化，这里显式算出来以便自证。
        factors = [
            ("流量（活跃用户数）", traffic_drop),
            ("转化率（下单/活跃用户）", cvr_drop),
            ("客单价", aov_drop),
        ]
        factor_bullets = [f"{name}：{delta:+.2f}%" for name, delta in factors]
        main_factor = max(factors, key=lambda x: abs(x[1]))[0]
        reconstructed = (
            (1 + traffic_drop / 100) * (1 + cvr_drop / 100) * (1 + aov_drop / 100) - 1
        ) * 100

        # 减量最大的两个渠道合计解释了多少整体降幅——渠道级明细与 GMV 同表，
        # 加总等于大盘，这条「集中度」论断是可以直接核对的。
        losses = sorted(
            (num(r.get("base_gmv")) - num(r.get("anomaly_gmv")), r) for r in channel_rows
        )
        top_losses = [(loss, row) for loss, row in reversed(losses) if loss > 0][:2]
        top2_loss = sum(loss for loss, _ in top_losses)
        top2_names = "、".join(f"「{row.get('channel_name')}」" for _, row in top_losses)
        gmv_loss_total = base_gmv - anom_gmv
        top2_share = (top2_loss / gmv_loss_total * 100) if gmv_loss_total else 0

        problem = (
            f"针对「{ctx.input_text.strip()}」，先把大盘问题拆成可归因的结构：\n"
            f"异常期（{anomaly_period_text()}）GMV 由 {money(base_gmv)} 降至 {money(anom_gmv)}"
            f"（{gmv_drop:+.2f}%），订单量 {int(base_orders)} → {int(anom_orders)}（{order_drop:+.2f}%），"
            f"客单价 {base_aov:.2f} 元 → {anom_aov:.2f} 元（{aov_drop:+.2f}%）。"
            f"按「流量 × 转化率 × 客单价」三因子拆解，主导因子是 **{main_factor}**。"
        )

        metrics = [
            metric("GMV", anom_gmv, "元", f"异常期 {anomaly_period_text()}"),
            metric("GMV（基准）", base_gmv, "元", f"基准期 {base_period_text()}"),
            metric("GMV 变化", gmv_drop, "%", compare_period_text()),
            metric("订单量", anom_orders, "单", f"异常期 {anomaly_period_text()}"),
            metric("订单量变化", order_drop, "%", compare_period_text()),
            metric("客单价", anom_aov, "元", f"异常期 {anomaly_period_text()}"),
            metric("客单价变化", aov_drop, "%", compare_period_text()),
            metric("访问次数 PV", anom_pv, "次", f"异常期 {anomaly_period_text()}"),
            metric("PV 变化", pv_drop, "%", compare_period_text()),
            metric("活跃用户数", anom_active, "人", f"异常期 {anomaly_period_text()}"),
            metric("活跃用户数变化", traffic_drop, "%", compare_period_text()),
            metric("访问次数", anom_visit, "次", f"异常期 {anomaly_period_text()}"),
            metric("访问次数变化", visit_drop, "%", compare_period_text()),
            metric("下单转化率（下单/活跃用户）", anom_cvr, "%", f"异常期 {anomaly_period_text()}"),
            metric("下单转化率变化", cvr_drop, "%", compare_period_text()),
            metric("购物车放弃率", anom_abandon_rate, "%", f"异常期 {anomaly_period_text()}"),
            metric("商品点击量（漏斗表）", anom_click, "次", f"异常期 {anomaly_period_text()}"),
            metric("商品点击量变化", click_drop, "%", compare_period_text()),
            metric(f"{loss_label_channel}「{channel_name}」GMV 变化", ch_drop, "%", compare_period_text()),
            metric(f"{loss_label_cat}「{cat_name}」销售额变化", cat_drop, "%", compare_period_text()),
        ]

        evidences: list[dict] = [
            evidence(
                "database",
                "大盘经营总览（biz_sales_summary）",
                "；".join(f"{k} = {v}" for k, v in ov.items()),
                "GMV",
                0.96,
            ),
            evidence(
                "database",
                "流量规模与深度（biz_visit_event）",
                "；".join(f"{k} = {v}" for k, v in tv.items()),
                "流量 PV",
                0.94,
            ),
            evidence(
                "database",
                "加购与放弃行为（biz_cart_event）",
                "；".join(f"{k} = {v}" for k, v in cv.items()),
                "购物车放弃率",
                0.92,
            ),
            evidence(
                "database",
                "三因子拆解结论",
                f"GMV = 活跃用户 × 转化率 × 客单价，三因子同取 biz_sales_summary 单表口径："
                f"流量 {traffic_drop:+.2f}% × 转化率 {cvr_drop:+.2f}% × 客单价 {aov_drop:+.2f}% "
                f"⇒ 还原 GMV 变化 {reconstructed:+.2f}%（实际 {gmv_drop:+.2f}%，尾差为四舍五入）。"
                f"主导因子为{main_factor}，"
                f"说明本轮下滑的主要矛盾{'在用户规模端' if main_factor.startswith('流量') else '在承接转化端' if main_factor.startswith('转化') else '在货品结构端'}。",
                "GMV",
                0.94,
            ),
        ]
        evidences.extend(rows_to_evidence(channel_rows, "分渠道 GMV 变化", "渠道 GMV", 0.93, 6))
        evidences.extend(rows_to_evidence(category_rows, "分品类销售额变化", "品类销售额", 0.93, 6))

        # 转化率与客单价都没恶化时，结论必须说清「问题不在承接端」，
        # 否则（订单量 -25.5%）很容易被读成转化出了问题。
        intact = (
            f"值得注意的是，转化率（{cvr_drop:+.2f}%）与客单价（{aov_drop:+.2f}%）本期均未恶化，"
            f"下滑几乎全部由用户规模收缩贡献——进店的人少了，但来的人买得并不比以前差。"
            if cvr_drop >= 0 and aov_drop >= 0
            else "转化率与客单价中至少一项同步走弱，说明除规模因素外，承接端也存在问题。"
        )

        conclusion = "\n\n".join([
            f"归因结论：大盘 GMV 下滑 {abs(gmv_drop):.2f}%，三因子拆解后主导因子是 **{main_factor}**。",
            "三因子变化明细（同取 biz_sales_summary 单表口径）：",
            bullet(factor_bullets),
            f"校验：三因子相乘还原 GMV 变化 {reconstructed:+.2f}%，与实际 {gmv_drop:+.2f}% 一致（尾差为四舍五入）。",
            intact,
            "结构下钻："
            + _structure_phrase("渠道维度", channel_name, ch_base, ch_anom, ch_drop, ch_loss)
            + f"，占整体 GMV 减量的 {abs(ch_contribution):.1f}%，是减量最大的渠道；"
            + _structure_phrase("品类维度（销售额口径）", cat_name, cat_base, cat_anom, cat_drop, cat_loss)
            + "，是减量最大的品类。"
            + (
                f"减量最大的两个渠道 {top2_names} 合计占整体减量的 {top2_share:.1f}%，"
                f"降幅高度集中，不属于全盘性流失。"
                if top2_names else ""
            ),
            f"补充信号：购物车放弃率由 {pct(base_abandon_rate)} 变为 {pct(anom_abandon_rate)}，"
            + ("放弃率上升，说明用户「想买但没买成」，需要重点检查价格、库存与结算体验。"
               if anom_abandon_rate > base_abandon_rate
               else "放弃率下降，说明下单链路本身没有恶化，问题更多在上游流量与货品结构。"),
            "因果链条：用户规模收缩 → 订单量与 GMV 同步下滑；"
            f"但降幅集中在 {top2_names or '少数渠道'}，且转化率与客单价基本持稳，"
            "说明这不是「全盘走弱」，而是可被定点修复的结构性问题。",
        ])

        missing = "\n".join([
            "以下数据缺口会限制结论精度：",
            bullet([
                "本次三因子拆解只使用 biz_sales_summary（成交口径）："
                "访问/点击等行为表与 biz_sales 品类明细表的统计覆盖范围都与成交汇总不同，"
                "跨表比率不可交叉相乘、明细合计也不等于大盘 GMV，故仅作下钻参考",
                "缺少分日粒度的大促/活动日历，无法剥离促销节奏造成的自然波动",
                "缺少新老客拆分（本次仅有活跃用户总数），无法判断是拉新乏力还是老客流失",
                "缺少竞品与本行业大盘数据，无法量化外部环境的影响权重",
            ]),
        ])

        actions = bullet([
            f"**今天**：对{loss_label_channel}「{channel_name}」与{loss_label_cat}「{cat_name}」做专项复盘，"
            f"确认是「主动调整」还是「异常流失」；",
            "**3 天内**：若为异常流失，按归因链逐项排查——流量端查投放与自然搜索，"
            "转化端查价格带、库存与商详，货品端查上下架与缺货；",
            "**一周内**：把「GMV = 流量 × 转化率 × 客单价」三因子看板固化为日报，"
            "任一因子环比波动超过 10% 自动归因提示；",
            "**持续**：对每个渠道与品类设置 GMV 贡献占比的红线，"
            "单一渠道占比超过 40% 时启动分散化投放，降低单点依赖风险。",
        ])

        return Interpretation(
            problem_definition=problem,
            key_metrics=metrics,
            evidence_list=evidences,
            conclusion_text=conclusion,
            missing_data_text=missing,
            next_action_text=actions,
        )
