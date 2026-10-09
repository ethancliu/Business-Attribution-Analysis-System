# -*- coding: utf-8 -*-
"""结果生成工具：把六模块内容渲染成标准报告并落盘。

六大模块（需求 §13）:
    问题定义 / 关键指标 / 证据链 / 结论 / 缺失数据 / 下一步行动建议
"""

from __future__ import annotations

import logging
from typing import Any

from app.analysis.tools.base import Tool, ToolContext, ToolResult, register
from app.analysis.tools.file_write import FileWriteTool

logger = logging.getLogger(__name__)


def render_report(
    *,
    problem_definition: str,
    key_metrics: list[dict],
    evidence_list: list[dict],
    conclusion_text: str,
    missing_data_text: str | None,
    next_action_text: str | None,
    meta: dict | None = None,
) -> str:
    """渲染标准化 markdown 报告（六模块）。"""
    lines: list[str] = ["# 经营归因分析报告", ""]

    if meta:
        for k, v in meta.items():
            lines.append(f"- {k}：{v}")
        lines.append("")

    lines += ["## 一、问题定义", "", problem_definition or "（未提供）", ""]

    lines += ["## 二、关键指标", ""]
    if key_metrics:
        lines += ["| 指标名称 | 指标值 | 单位 | 统计口径/周期 |", "| --- | --- | --- | --- |"]
        for m in key_metrics:
            lines.append(
                f"| {m.get('metric_name', '')} | {m.get('metric_value', '')} | "
                f"{m.get('metric_unit', '')} | {m.get('metric_period', '')} |"
            )
    else:
        lines.append("（无关键指标）")
    lines.append("")

    lines += ["## 三、证据链", ""]
    if evidence_list:
        for i, e in enumerate(evidence_list, 1):
            try:
                conf = f"{float(e.get('confidence', 0)) * 100:.0f}%"
            except (TypeError, ValueError):
                conf = str(e.get("confidence", ""))
            lines.append(f"### 证据 {i}｜{e.get('source_name', '')}")
            lines.append("")
            lines.append(f"- 来源类型：{e.get('source_type', '')}")
            lines.append(f"- 关联指标：{e.get('related_metric', '')}")
            lines.append(f"- 置信度：{conf}")
            lines.append("")
            lines.append(f"{e.get('evidence_text', '')}")
            lines.append("")
    else:
        lines += ["（未采集到证据）", ""]

    lines += ["## 四、结论", "", conclusion_text or "（未提供）", ""]
    lines += ["## 五、数据缺口", "", missing_data_text or "（本次分析所需数据完整）", ""]
    lines += ["## 六、下一步行动建议", "", next_action_text or "（未提供）", ""]
    lines += ["---", "", "*本报告由经营多轮归因分析系统自动生成，全部结论可回溯至上方证据链。*"]

    return "\n".join(lines)


class ResultGenerateTool(Tool):
    name = "result_generate"
    description = "按标准六模块格式生成分析报告，写入会话 exports 目录并返回报告文本"
    signature = {
        "problem_definition": "问题定义",
        "key_metrics": "关键指标列表",
        "evidence_list": "证据链列表",
        "conclusion_text": "归因结论",
        "missing_data_text": "数据缺口说明",
        "next_action_text": "下一步行动建议",
    }

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        ctx.check_cancel()

        problem_definition = str(kwargs.get("problem_definition") or "")
        key_metrics = list(kwargs.get("key_metrics") or [])
        evidence_list = list(kwargs.get("evidence_list") or [])
        conclusion_text = str(kwargs.get("conclusion_text") or "")
        missing_data_text = kwargs.get("missing_data_text")
        next_action_text = kwargs.get("next_action_text")

        markdown = render_report(
            problem_definition=problem_definition,
            key_metrics=key_metrics,
            evidence_list=evidence_list,
            conclusion_text=conclusion_text,
            missing_data_text=missing_data_text,
            next_action_text=next_action_text,
            meta=kwargs.get("meta"),
        )

        # 同步把报告落到会话工作区（exports 由结果服务统一导出）
        try:
            writer = FileWriteTool()
            writer.run(
                ctx,
                file_name=f"分析报告草稿_任务{ctx.task_id}.md",
                content=markdown,
                format="text",
            )
        except Exception as exc:  # noqa: BLE001 - 草稿落盘失败不影响主流程
            logger.warning("报告草稿写入工作区失败：%s", exc)

        logger.info("结果生成完成：指标 %s 项，证据 %s 条", len(key_metrics), len(evidence_list))

        return ToolResult(
            ok=True,
            summary=f"已生成标准报告：关键指标 {len(key_metrics)} 项、证据 {len(evidence_list)} 条、"
                    f"结论 {len(conclusion_text)} 字",
            data={
                "problem_definition": problem_definition,
                "key_metrics": key_metrics,
                "evidence_list": evidence_list,
                "conclusion_text": conclusion_text,
                "missing_data_text": missing_data_text,
                "next_action_text": next_action_text,
                "result_markdown": markdown,
            },
            rows=len(markdown.splitlines()),
        )


register(ResultGenerateTool())
