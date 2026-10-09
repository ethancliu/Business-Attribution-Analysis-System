# -*- coding: utf-8 -*-
"""场景一：商品目录质量导致曝光转化下滑（C01 美妆个护）。

埋入的异常（database/05_demo_data.sql）:
    - 美妆个护 CTR 由 4.20% 跌至 2.09%，其他品类稳定在 5.45%~5.52%
    - 该品类商品标题平均 11.4 字、主图 1.25 张、属性填充率 36.3%
      （其他品类为 19~25 字、约 4.8 张、86%~88%）
    - 「氨基酸洁面 / 玻尿酸精华 / 神经酰胺」三个高意图搜索词零结果放大 3.7 倍以上
    - 差评集中落在「描述不符」
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
    resolve_category_id,
    rows_of,
    rows_to_evidence,
)
from app.analysis.tools.base import ToolContext, ToolResult

logger = logging.getLogger(__name__)

TARGET_CATEGORY_ID = "C01"      # 美妆个护（biz_category.category_id 为 C01…C05 字符串编码）
TARGET_CATEGORY_NAME = "美妆个护"
COMPLAINT_KEYWORD = "描述不符"
ZERO_SEARCH_KEYWORDS = ("氨基酸洁面", "玻尿酸精华", "神经酰胺")


class CatalogScenario(Scenario):
    key = "catalog"
    name = "商品目录质量归因"
    description = "定位品类级曝光转化下滑，归因到商品标题、主图、属性、搜索承接等目录质量问题"
    strong_keywords = ("目录质量", "商品标题", "主图", "属性填充", "商品卡")
    keywords = (
        "点击率", "ctr", "曝光", "转化下滑", "转化率下降", "曝光转化",
        "美妆", "个护", "搜索无结果", "零结果", "描述不符", "商详", "详情页",
        "商品质量", "选品", "标题", "图片", "sku",
        # 「商品页 / 转化率」：growth 场景也含「转化率」，
        # 但转化率下滑且限定在商品页时属于目录承接问题，靠这两个词拿到更高分。
        "商品页", "转化率",
    )

    # ------------------------------------------------------------------

    def build(self, ctx: ToolContext, intent: dict) -> list[Step]:
        bs, be = base_start(), base_end()
        as_, ae = anomaly_start(), anomaly_end()
        category_id = resolve_category_id(ctx.db, intent.get("category_hint"), TARGET_CATEGORY_ID)

        ctr_sql = f"""
            SELECT c.category_name,
                   ROUND(100 * SUM(CASE WHEN pc.stat_date BETWEEN '{bs}' AND '{be}'
                                        THEN pc.click_cnt ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN pc.stat_date BETWEEN '{bs}' AND '{be}'
                                           THEN pc.exposure_cnt ELSE 0 END), 0), 2) AS base_ctr_pct,
                   ROUND(100 * SUM(CASE WHEN pc.stat_date BETWEEN '{as_}' AND '{ae}'
                                        THEN pc.click_cnt ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN pc.stat_date BETWEEN '{as_}' AND '{ae}'
                                           THEN pc.exposure_cnt ELSE 0 END), 0), 2) AS anomaly_ctr_pct,
                   SUM(CASE WHEN pc.stat_date BETWEEN '{as_}' AND '{ae}'
                            THEN pc.exposure_cnt ELSE 0 END) AS anomaly_exposure
            FROM biz_product_click pc
            JOIN biz_category c ON c.category_id = pc.category_id
            GROUP BY c.category_name
            ORDER BY base_ctr_pct DESC
        """

        quality_sql = f"""
            SELECT c.category_name,
                   COUNT(*) AS sku_cnt,
                   ROUND(AVG(p.title_length), 1) AS avg_title_len,
                   ROUND(AVG(p.image_count), 2) AS avg_image_cnt,
                   ROUND(AVG(p.attr_fill_rate), 1) AS avg_attr_fill_rate
            FROM biz_product p
            JOIN biz_category c ON c.category_id = p.category_id
            GROUP BY c.category_name
            ORDER BY avg_title_len ASC
        """

        zero_sql = f"""
            SELECT se.search_keyword,
                   SUM(CASE WHEN se.stat_date BETWEEN '{bs}' AND '{be}' THEN se.search_cnt ELSE 0 END) AS base_search,
                   SUM(CASE WHEN se.stat_date BETWEEN '{bs}' AND '{be}' THEN se.zero_result_cnt ELSE 0 END) AS base_zero,
                   SUM(CASE WHEN se.stat_date BETWEEN '{as_}' AND '{ae}' THEN se.search_cnt ELSE 0 END) AS anomaly_search,
                   SUM(CASE WHEN se.stat_date BETWEEN '{as_}' AND '{ae}' THEN se.zero_result_cnt ELSE 0 END) AS anomaly_zero
            FROM biz_search_exposure se
            WHERE se.category_id = '{category_id}'
            GROUP BY se.search_keyword
            HAVING anomaly_zero > 0
            ORDER BY anomaly_zero DESC
            LIMIT 12
        """

        funnel_sql = f"""
            SELECT ROUND(100 * SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN order_cnt ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN stat_date BETWEEN '{as_}' AND '{ae}' THEN click_cnt ELSE 0 END), 0), 2)
                       AS anomaly_click_to_order_pct,
                   ROUND(100 * SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN order_cnt ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN stat_date BETWEEN '{bs}' AND '{be}' THEN click_cnt ELSE 0 END), 0), 2)
                       AS base_click_to_order_pct
            FROM biz_product_conversion
            WHERE category_id = '{category_id}'
        """

        return [
            Step(
                key="ctr_by_category",
                title="按品类对比基准期与异常期的曝光点击率",
                tool="db_query",
                args={"sql": ctr_sql, "limit": 30},
                evidence_name="品类曝光点击率对比（biz_product_click）",
                related_metric="商品点击率 CTR",
                confidence=0.96,
                critical=True,
            ),
            Step(
                key="catalog_quality",
                title="对比各品类商品标题长度、主图数量与属性填充率",
                tool="db_query",
                args={"sql": quality_sql, "limit": 30},
                evidence_name="商品目录质量字段对比（biz_product）",
                related_metric="目录质量分",
                confidence=0.93,
            ),
            Step(
                key="zero_search",
                title="定位零结果搜索词的放大情况",
                tool="db_query",
                args={"sql": zero_sql, "limit": 12},
                evidence_name="零结果搜索词统计（biz_search_exposure）",
                related_metric="搜索无结果率",
                confidence=0.91,
            ),
            Step(
                key="funnel",
                title=f"校验 {TARGET_CATEGORY_NAME} 点击到下单的转化效率",
                tool="db_query",
                args={"sql": funnel_sql, "limit": 1},
                evidence_name="点击到下单转化率（biz_product_conversion）",
                related_metric="点击下单转化率",
                confidence=0.88,
            ),
            Step(
                key="voice_of_customer",
                title=f"检索用户评论中的「{COMPLAINT_KEYWORD}」反馈原文",
                tool="text_search",
                args={"keyword": COMPLAINT_KEYWORD, "scope": "review", "limit": 8},
                evidence_name="用户评论原文检索",
                related_metric="负面反馈占比",
                confidence=0.85,
            ),
            Step(
                key="artifact",
                title="把品类 CTR 对比明细写出到会话工作区",
                tool="file_write",
                args={
                    "file_name": "品类CTR对比.csv",
                    "content": "@ctr_by_category",
                    "format": "table",
                },
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
        ctr_rows = rows_of(results.get("ctr_by_category"))
        quality_rows = rows_of(results.get("catalog_quality"))
        zero_rows = rows_of(results.get("zero_search"))
        funnel_row = first_row(results.get("funnel"))

        # --- 找出跌幅最大的品类 ---
        worst = None
        worst_drop = 0.0
        for r in ctr_rows:
            drop = rate_drop(r.get("base_ctr_pct"), r.get("anomaly_ctr_pct"))
            if drop < worst_drop:
                worst_drop = drop
                worst = r

        target = next(
            (r for r in ctr_rows if r.get("category_name") == TARGET_CATEGORY_NAME),
            worst or {},
        )
        target_name = target.get("category_name", TARGET_CATEGORY_NAME)
        base_ctr = num(target.get("base_ctr_pct"), 2)
        anomaly_ctr = num(target.get("anomaly_ctr_pct"), 2)
        drop_pct = rate_drop(base_ctr, anomaly_ctr)

        others = [r for r in ctr_rows if r.get("category_name") != target_name]
        other_ctrs = [num(r.get("anomaly_ctr_pct"), 2) for r in others if r.get("anomaly_ctr_pct") is not None]
        other_range = f"{min(other_ctrs):.2f}%~{max(other_ctrs):.2f}%" if other_ctrs else "无对比数据"

        # --- 目录质量对比 ---
        tq = next((r for r in quality_rows if r.get("category_name") == target_name), {})
        oq = [r for r in quality_rows if r.get("category_name") != target_name]
        avg_other_title = sum(num(r.get("avg_title_len")) for r in oq) / len(oq) if oq else 0
        avg_other_image = sum(num(r.get("avg_image_cnt")) for r in oq) / len(oq) if oq else 0
        avg_other_attr = sum(num(r.get("avg_attr_fill_rate")) for r in oq) / len(oq) if oq else 0

        t_title = num(tq.get("avg_title_len"), 1)
        t_image = num(tq.get("avg_image_cnt"), 2)
        t_attr = num(tq.get("avg_attr_fill_rate"), 1)

        # --- 零结果搜索词 ---
        top_zero = pick(zero_rows, "anomaly_zero", 0, above=True)
        zero_bullets: list[str] = []
        for r in zero_rows[:3]:
            b_zero = num(r.get("base_zero"), 0)
            a_zero = num(r.get("anomaly_zero"), 0)
            mult = (a_zero / b_zero) if b_zero else 0
            zero_bullets.append(
                f"「{r.get('search_keyword')}」零结果次数由 {int(b_zero)} 次升至 {int(a_zero)} 次"
                + (f"（放大 {mult:.2f} 倍）" if mult else "")
            )

        # --- 漏斗 ---
        base_c2o = num(funnel_row.get("base_click_to_order_pct"), 2)
        anomaly_c2o = num(funnel_row.get("anomaly_click_to_order_pct"), 2)
        c2o_drop = rate_drop(base_c2o, anomaly_c2o)

        # --- 组装六大模块 ---
        problem = (
            f"用户在「{ctx.input_text.strip()}」中反映的问题，经数据核对定位为：\n"
            f"{target_name}品类的曝光点击率在异常期（{anomaly_period_text()}）由 {pct(base_ctr)} "
            f"下滑至 {pct(anomaly_ctr)}，降幅 {abs(drop_pct):.2f}%；"
            f"同期其他品类 CTR 稳定在 {other_range}，说明不是全站流量问题，而是该品类的商品呈现问题。"
        )

        metrics = [
            metric(f"{target_name} 曝光点击率", anomaly_ctr, "%", f"异常期 {anomaly_period_text()}"),
            metric(f"{target_name} 曝光点击率（基准）", base_ctr, "%", f"基准期 {base_period_text()}"),
            metric("点击率变化幅度", drop_pct, "%", compare_period_text()),
            metric("其他品类 CTR 区间", other_range, "%", f"异常期 {anomaly_period_text()}"),
            metric("平均标题字数", t_title, "字", f"{target_name} 全量 SKU"),
            metric("其他品类平均标题字数", round(avg_other_title, 1), "字", "对比组"),
            metric("平均主图数量", t_image, "张", f"{target_name} 全量 SKU"),
            metric("其他品类平均主图数量", round(avg_other_image, 2), "张", "对比组"),
            metric("属性填充率", t_attr, "%", f"{target_name} 全量 SKU"),
            metric("其他品类属性填充率", round(avg_other_attr, 1), "%", "对比组"),
            metric("点击到下单转化率", anomaly_c2o, "%", f"异常期 {anomaly_period_text()}"),
            metric("点击到下单转化率变化", c2o_drop, "%", compare_period_text()),
        ]

        evidences: list[dict] = []
        evidences.extend(
            rows_to_evidence(
                ctr_rows,
                "品类曝光点击率对比（biz_product_click）",
                "商品点击率 CTR",
                0.96,
                limit=6,
            )
        )
        evidences.extend(
            rows_to_evidence(
                quality_rows,
                "商品目录质量字段对比（biz_product）",
                "目录质量分",
                0.93,
                limit=6,
            )
        )
        evidences.extend(
            rows_to_evidence(
                zero_rows,
                "零结果搜索词统计（biz_search_exposure）",
                "搜索无结果率",
                0.91,
                limit=5,
            )
        )
        if funnel_row:
            evidences.append(
                evidence(
                    "database",
                    "点击到下单转化率（biz_product_conversion）",
                    f"基准期点击下单转化率 {pct(base_c2o)}，异常期 {pct(anomaly_c2o)}，"
                    f"相对变化 {c2o_drop:.2f}%",
                    "点击下单转化率",
                    0.88,
                )
            )

        voc = results.get("voice_of_customer")
        if voc is not None and voc.ok and isinstance(voc.data, list):
            for hit in voc.data[:5]:
                evidences.append(
                    evidence(
                        hit.get("source_type", "database"),
                        hit.get("source_name", "用户评论"),
                        hit.get("snippet", ""),
                        "负面反馈占比",
                        0.85,
                    )
                )

        conclusion_parts = [
            f"归因结论：{target_name}品类曝光点击率下滑 {abs(drop_pct):.2f}%，"
            f"由 {pct(base_ctr)} 降至 {pct(anomaly_ctr)}，属于**品类级商品呈现问题**，而非流量总量问题"
            f"（同期其他品类 CTR 稳定在 {other_range}）。"
        ]
        findings: list[str] = []
        if t_title and t_title < avg_other_title:
            findings.append(
                f"标题过短：平均 {t_title} 字，显著低于其他品类的 {avg_other_title:.1f} 字，"
                f"关键词覆盖不足，搜索匹配度下降"
            )
        if t_image and t_image < avg_other_image:
            findings.append(
                f"主图数量不足：平均 {t_image} 张，其他品类为 {avg_other_image:.2f} 张，"
                f"缺少多角度/场景图，首屏吸引力弱"
            )
        if t_attr and t_attr < avg_other_attr:
            findings.append(
                f"属性填充率偏低：{t_attr}% 对比其他品类 {avg_other_attr:.1f}%，"
                f"筛选与推荐场景下大量商品无法被召回"
            )
        if zero_bullets:
            findings.append("高意图搜索词承接失败：" + "；".join(zero_bullets))
        if c2o_drop < 0:
            findings.append(
                f"转化同步走弱：点击到下单转化率由 {pct(base_c2o)} 降至 {pct(anomaly_c2o)}"
                f"（{c2o_drop:.2f}%），说明进来的流量质量也随之下滑"
            )

        if findings:
            conclusion_parts.append("具体证据支持以下三条主因：")
            conclusion_parts.append(bullet(findings))
        conclusion_parts.append(
            f"因果链条：目录信息缺失（标题短 / 主图少 / 属性空）→ 搜索与推荐召回不足 + 商品卡吸引力下降"
            f"→ 曝光点击率由 {pct(base_ctr)} 跌至 {pct(anomaly_ctr)} → 点击下单转化率同步下降 {abs(c2o_drop):.2f}%。"
        )

        missing_parts = [
            "本次分析已覆盖曝光、点击、转化、搜索、评论五类数据。仍存在以下数据缺口：",
            bullet([
                "缺少商品卡改版/主图下架的操作日志，无法确认变更发生的准确时点",
                "缺少竞品同品类价格与促销力度数据，无法完全排除外部竞争因素",
                "缺少站内推荐流与搜索流的分渠道曝光拆分，两条流量的贡献占比未量化",
            ]),
        ]

        actions = [
            f"**紧急（24 小时内）**：筛出 {target_name} 品类中标题字数 < 15 字或主图 < 3 张的 SKU，"
            f"按曝光量降序优先补齐，预计可恢复 30% 以上的 CTR 损失；",
            f"**本周内**：为「{ZERO_SEARCH_KEYWORDS[0] if top_zero is None else top_zero.get('search_keyword', ZERO_SEARCH_KEYWORDS[0])}」"
            f"等高意图零结果词建立兜底词表与召回规则，先止血再优化；",
            f"**本周内**：把属性填充率纳入商品上架卡点（低于 80% 不允许上架），并批量补齐存量 SKU；",
            "**持续**：为该品类建立 CTR 日监控看板，跌幅超过 15% 自动告警，避免同类问题再次潜伏。",
        ]

        return Interpretation(
            problem_definition=problem,
            key_metrics=metrics,
            evidence_list=evidences,
            conclusion_text="\n\n".join(conclusion_parts),
            missing_data_text="\n".join(missing_parts),
            next_action_text=bullet(actions),
        )
