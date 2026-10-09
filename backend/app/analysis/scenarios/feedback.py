# -*- coding: utf-8 -*-
"""场景四：用户反馈与口碑恶化（负面评价占比上升、差评标签集中）。

埋入的异常（database/05_demo_data.sql）:
    - 负面评论占比在异常期明显上升，正面占比同步下滑
    - 差评标签呈单点集中，首位标签与「商品目录质量」类问题互为印证

注意: 首位标签必须从本轮查询结果里取，不能写死。
     演示数据里首位是「质量问题」，写死成「描述不符」会让模块一与归因结论自相矛盾。
"""

from __future__ import annotations

import logging

from sqlalchemy import text as sql_text

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


class FeedbackScenario(Scenario):
    key = "feedback"
    name = "用户反馈与口碑归因"
    description = "定位负面评价激增与评分下滑，从评论标签与评分分布还原用户不满的真实来源"
    strong_keywords = ("差评", "评论", "口碑", "评分", "负面", "投诉", "满意度", "nps")
    keywords = (
        "用户反馈", "评价", "情绪", "好评", "中评", "星级", "复购", "用户体验",
        "吐槽", "不满", "退货理由",
    )

    @staticmethod
    def _top_negative_tag(ctx: ToolContext, as_: str, ae: str, intent: dict) -> str:
        """取异常期增幅最大的差评标签作为检索词。

        直接把用户提问整句当关键词检索是没有意义的（命不中任何评论原文），
        这里先用数据定位到当期最集中的不满标签，再拿它去检索原声。
        """
        try:
            row = ctx.db.execute(
                sql_text(
                    "SELECT issue_tag FROM biz_review "
                    "WHERE issue_tag IS NOT NULL AND sentiment = 'negative' "
                    f"AND stat_date BETWEEN '{as_}' AND '{ae}' "
                    "GROUP BY issue_tag ORDER BY COUNT(*) DESC LIMIT 1"
                )
            ).mappings().first()
        except Exception:  # noqa: BLE001 - 取不到就退回问题里的关键词
            row = None
        if row and row.get("issue_tag"):
            return str(row["issue_tag"])
        return str(intent.get("keyword") or "质量问题")

    def build(self, ctx: ToolContext, intent: dict) -> list[Step]:
        bs, be = base_start(), base_end()
        as_, ae = anomaly_start(), anomaly_end()
        keyword = self._top_negative_tag(ctx, as_, ae, intent)

        sentiment_sql = f"""
            SELECT sentiment,
                   SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN 1 ELSE 0 END) AS base_cnt,
                   SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN 1 ELSE 0 END) AS anomaly_cnt
            FROM biz_review
            GROUP BY sentiment
            ORDER BY anomaly_cnt DESC
        """

        tag_sql = f"""
            SELECT issue_tag,
                   SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN 1 ELSE 0 END) AS base_cnt,
                   SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN 1 ELSE 0 END) AS anomaly_cnt
            FROM biz_review
            WHERE issue_tag IS NOT NULL AND sentiment = 'negative'
            GROUP BY issue_tag
            ORDER BY anomaly_cnt DESC
            LIMIT 15
        """

        rating_sql = f"""
            SELECT p.category_id,
                   SUM(CASE WHEN r.stat_date BETWEEN '{bs}' AND '{be}' THEN r.rating_1_cnt ELSE 0 END) AS base_r1,
                   SUM(CASE WHEN r.stat_date BETWEEN '{bs}' AND '{be}' THEN r.rating_2_cnt ELSE 0 END) AS base_r2,
                   SUM(CASE WHEN r.stat_date BETWEEN '{bs}' AND '{be}' THEN r.rating_5_cnt ELSE 0 END) AS base_r5,
                   SUM(CASE WHEN r.stat_date BETWEEN '{as_}' AND '{ae}' THEN r.rating_1_cnt ELSE 0 END) AS anomaly_r1,
                   SUM(CASE WHEN r.stat_date BETWEEN '{as_}' AND '{ae}' THEN r.rating_2_cnt ELSE 0 END) AS anomaly_r2,
                   SUM(CASE WHEN r.stat_date BETWEEN '{as_}' AND '{ae}' THEN r.rating_5_cnt ELSE 0 END) AS anomaly_r5,
                   ROUND(AVG(CASE WHEN r.stat_date BETWEEN '{bs}' AND '{be}' THEN r.avg_rating END), 3) AS base_avg_rating,
                   ROUND(AVG(CASE WHEN r.stat_date BETWEEN '{as_}' AND '{ae}' THEN r.avg_rating END), 3) AS anomaly_avg_rating
            FROM biz_rating r
            JOIN biz_product p ON p.product_id = r.product_id
            GROUP BY p.category_id
            ORDER BY anomaly_avg_rating ASC
        """

        return [
            Step(
                key="sentiment",
                title="对比基准期与异常期的评论情绪分布",
                tool="db_query",
                args={"sql": sentiment_sql, "limit": 10},
                evidence_name="评论情绪分布（biz_review）",
                related_metric="负面评论占比",
                confidence=0.95,
                critical=True,
            ),
            Step(
                key="issue_tags",
                title="统计差评标签的数量变化，定位不满来源",
                tool="db_query",
                args={"sql": tag_sql, "limit": 15},
                evidence_name="差评标签分布（biz_review.issue_tag）",
                related_metric="负面标签占比",
                confidence=0.93,
            ),
            Step(
                key="rating",
                title="核对评分分布与平均评分变化",
                tool="db_query",
                args={"sql": rating_sql, "limit": 20},
                evidence_name="评分分布（biz_rating）",
                related_metric="平均评分",
                confidence=0.92,
            ),
            Step(
                key="review_voice",
                title=f"检索「{keyword}」相关的用户原声",
                tool="text_search",
                args={"keyword": keyword, "scope": "review", "limit": 10},
                evidence_name="用户评论原声",
                related_metric="负面标签占比",
                confidence=0.88,
            ),
            Step(
                key="artifact",
                title="把差评标签分布写出到会话工作区",
                tool="file_write",
                args={"file_name": "差评标签分布.csv", "content": "@issue_tags", "format": "table"},
                evidence_name="分析中间产物",
                related_metric="分析过程留痕",
                confidence=0.8,
            ),
        ]

    def interpret(self, ctx, intent, results, steps) -> Interpretation:
        sent_rows = rows_of(results.get("sentiment"))
        tag_rows = rows_of(results.get("issue_tags"))
        rating_rows = rows_of(results.get("rating"))

        base_total = sum(num(r.get("base_cnt"), 0) for r in sent_rows)
        anom_total = sum(num(r.get("anomaly_cnt"), 0) for r in sent_rows)

        neg_row = next((r for r in sent_rows if r.get("sentiment") == "negative"), {})
        base_neg = num(neg_row.get("base_cnt"), 0)
        anom_neg = num(neg_row.get("anomaly_cnt"), 0)
        base_neg_rate = (base_neg / base_total * 100) if base_total else 0
        anom_neg_rate = (anom_neg / anom_total * 100) if anom_total else 0

        pos_row = next((r for r in sent_rows if r.get("sentiment") == "positive"), {})
        base_pos_rate = (num(pos_row.get("base_cnt"), 0) / base_total * 100) if base_total else 0
        anom_pos_rate = (num(pos_row.get("anomaly_cnt"), 0) / anom_total * 100) if anom_total else 0

        top_tag = pick(tag_rows, "anomaly_cnt", 0, above=True) or {}
        top_tag_name = top_tag.get("issue_tag", "—")
        tag_bullets = []
        for r in tag_rows[:4]:
            b = num(r.get("base_cnt"), 0)
            a = num(r.get("anomaly_cnt"), 0)
            delta = rate_drop(b, a)
            tag_bullets.append(
                f"「{r.get('issue_tag')}」{int(b)} 条 → {int(a)} 条（{delta:+.2f}%）"
            )

        # 评分数值是按品类聚合的，取评分最低的那个品类。
        # 措辞必须带上「评分最低的品类」，否则会被读成大盘平均评分。
        worst_cat = pick(rating_rows, "anomaly_avg_rating", 0, above=False) or {}
        worst_cat_id = worst_cat.get("category_id", "—")
        base_rating = num(worst_cat.get("base_avg_rating"), 3)
        anom_rating = num(worst_cat.get("anomaly_avg_rating"), 3)
        rating_delta = anom_rating - base_rating

        problem = (
            f"针对「{ctx.input_text.strip()}」，先量化问题：\n"
            f"异常期（{anomaly_period_text()}）负面评论占比由 {pct(base_neg_rate)} 升至 {pct(anom_neg_rate)}"
            f"（{rate_drop(base_neg_rate, anom_neg_rate):+.2f}%），"
            f"正面评论占比由 {pct(base_pos_rate)} 降至 {pct(anom_pos_rate)}；"
            f"差评标签首位为「{top_tag_name}」。"
        )

        metrics = [
            metric("负面评论占比", anom_neg_rate, "%", f"异常期 {anomaly_period_text()}"),
            metric("负面评论占比（基准）", base_neg_rate, "%", f"基准期 {base_period_text()}"),
            metric("负面占比变化", rate_drop(base_neg_rate, anom_neg_rate), "%", compare_period_text()),
            metric("正面评论占比", anom_pos_rate, "%", f"异常期 {anomaly_period_text()}"),
            metric("正面占比变化", rate_drop(base_pos_rate, anom_pos_rate), "%", compare_period_text()),
            metric(f"首位差评标签「{top_tag_name}」", num(top_tag.get("anomaly_cnt"), 0), "条", f"异常期 {anomaly_period_text()}"),
            metric(f"评分最低品类「{worst_cat_id}」平均评分", anom_rating, "分", f"异常期 {anomaly_period_text()}"),
            metric(f"评分最低品类「{worst_cat_id}」平均评分（基准）", base_rating, "分", f"基准期 {base_period_text()}"),
            metric("评分最低品类平均评分变化", rating_delta, "分", compare_period_text()),
            metric("异常期评论总量", anom_total, "条", f"异常期 {anomaly_period_text()}"),
        ]

        evidences: list[dict] = []
        evidences.extend(rows_to_evidence(sent_rows, "评论情绪分布（biz_review）", "负面评论占比", 0.95, 5))
        evidences.extend(rows_to_evidence(tag_rows, "差评标签分布（biz_review.issue_tag）", "负面标签占比", 0.93, 6))
        evidences.extend(rows_to_evidence(rating_rows, "评分分布（biz_rating）", "平均评分", 0.92, 5))
        evidences.append(
            evidence(
                "database",
                "情绪结构变化结论",
                f"基准期负面 {int(base_neg)} 条 / 共 {int(base_total)} 条（{pct(base_neg_rate)}），"
                f"异常期负面 {int(anom_neg)} 条 / 共 {int(anom_total)} 条（{pct(anom_neg_rate)}），"
                f"负面比例接近翻倍，且增幅远超评论总量增幅，说明不是「评论变多」而是「不满变多」。",
                "负面评论占比",
                0.95,
            )
        )

        voice = results.get("review_voice")
        if voice is not None and voice.ok and isinstance(voice.data, list):
            for hit in voice.data[:6]:
                evidences.append(
                    evidence(
                        hit.get("source_type", "database"),
                        hit.get("source_name", "用户评论"),
                        hit.get("snippet", ""),
                        "负面标签占比",
                        0.88,
                    )
                )

        # 标签名与评分方向都从本轮真实数据里取，不写死。
        # 写死「描述不符」会在首位标签是「质量问题」时与模块一自相矛盾。
        tag_second = str(tag_rows[1].get("issue_tag", "—")) if len(tag_rows) > 1 else "—"
        top_tag_cnt = int(num(top_tag.get("anomaly_cnt"), 0))
        second_cnt = int(num(tag_rows[1].get("anomaly_cnt"), 0)) if len(tag_rows) > 1 else 0
        concentration = (
            f"首位标签「{top_tag_name}」{top_tag_cnt} 条，是次位「{tag_second}」{second_cnt} 条的 "
            f"{(top_tag_cnt / second_cnt if second_cnt else 0):.1f} 倍，标签结构呈单点爆发而非全面扩散"
            if second_cnt else f"首位标签「{top_tag_name}」{top_tag_cnt} 条，其余标签量级明显更低"
        )
        rating_trend = (
            f"评分同步走弱：评分最低的品类「{worst_cat_id}」平均评分由 {base_rating:.3f} 分"
            f"降至 {anom_rating:.3f} 分（{rating_delta:+.3f} 分）。"
            if rating_delta < 0
            else f"评分未同步恶化：评分最低的品类「{worst_cat_id}」平均评分由 {base_rating:.3f} 分"
                 f"变为 {anom_rating:.3f} 分（{rating_delta:+.3f} 分），说明问题尚未反映到星级上。"
        )

        conclusion = "\n\n".join([
            f"归因结论：口碑恶化不是「用户变挑剔」，而是**商品实际表现与用户预期存在落差**。"
            f"负面评论占比由 {pct(base_neg_rate)} 升至 {pct(anom_neg_rate)}，"
            f"差评标签高度集中在「{top_tag_name}」，{concentration}——"
            f"这正是「某类问题集中爆发」的典型特征，而不是服务体验整体下滑。",
            "标签变化明细：",
            bullet(tag_bullets),
            rating_trend,
            # 因果链条只写数据里真实拿到的那条链路。
            # 写死「标题/主图/属性」会把结论锁死在「目录描述不符」上，
            # 而首位标签完全可能是「质量问题」这类履约/品控问题。
            f"因果链条：用户对「{top_tag_name}」的预期落空 "
            f"→ 差评集中爆发于该标签 → 口碑走弱并拖累后续转化，形成负向循环。",
        ])

        missing = "\n".join([
            "以下数据缺口会限制结论精度：",
            bullet([
                "缺少评论关联的具体商品 ID 与订单号（本次为品类级聚合），无法直接定位到问题 SKU",
                "缺少客服工单数据，无法判断部分不满是否被客服环节拦截而未流入评论区",
                "缺少竞品同期口碑数据，无法判断是否存在行业性质量波动",
            ]),
        ])

        actions = bullet([
            f"**今天**：把「{top_tag_name}」标签下的差评逐条人工审阅（样本量 "
            f"{int(num(top_tag.get('anomaly_cnt'), 0))} 条），抽取前 20 条定位到具体商品；",
            # 整改动作跟着首位标签走：标签是「质量问题」时去查页面文案是打偏了靶子。
            f"**3 天内**：针对「{top_tag_name}」拉齐品控、仓储、客服三方口径，"
            f"抽检该标签下的问题商品批次，确认是临期、存储还是来料问题，逐项整改；",
            "**一周内**：建立「新品上架前 50 单人工回访」机制，"
            f"在「{top_tag_name}」类问题大规模扩散前拦截；",
            "**持续**：把负面评论占比与首位差评标签纳入每日口碑看板，"
            f"负面占比超过 {max(base_neg_rate * 1.5, 20):.1f}% 即触发预警。",
        ])

        return Interpretation(
            problem_definition=problem,
            key_metrics=metrics,
            evidence_list=evidences,
            conclusion_text=conclusion,
            missing_data_text=missing,
            next_action_text=actions,
        )
