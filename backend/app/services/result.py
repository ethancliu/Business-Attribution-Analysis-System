# -*- coding: utf-8 -*-
"""分析结果服务：六大模块标准化输出的落库、渲染、导出与下载。

标准化输出格式（需求 §13）六个模块:
    1. 问题定义      problem_definition
    2. 关键指标      key_metrics_json
    3. 证据链        evidence_list_json
    4. 结论          conclusion_text
    5. 缺失数据      missing_data_text
    6. 下一步行动建议 next_action_text
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.paths import KIND_EXPORT, abs_path, dir_of, safe_join
from app.models import AnalysisResult, AnalysisTask, User

logger = logging.getLogger(__name__)

FORMAT_MARKDOWN = "markdown"
FORMAT_EXCEL = "excel"
FORMAT_JSON = "json"

VALID_FORMATS = (FORMAT_MARKDOWN, FORMAT_EXCEL, FORMAT_JSON)

# 前端/文档里使用的简写 -> 内部格式名
FORMAT_ALIASES = {
    "md": FORMAT_MARKDOWN,
    "markdown": FORMAT_MARKDOWN,
    "json": FORMAT_JSON,
    "xlsx": FORMAT_EXCEL,
    "excel": FORMAT_EXCEL,
}


def normalize_format(fmt: str | None) -> str:
    """把 md / xlsx 等简写归一到内部格式名。"""
    key = (fmt or "md").strip().lower()
    resolved = FORMAT_ALIASES.get(key)
    if resolved is None:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的导出格式：{fmt}（可选 md / json / xlsx）",
        )
    return resolved

MEDIA_TYPES = {
    FORMAT_MARKDOWN: "text/markdown; charset=utf-8",
    FORMAT_EXCEL: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    FORMAT_JSON: "application/json; charset=utf-8",
}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------

def save(
    db: Session,
    task: AnalysisTask,
    *,
    problem_definition: str,
    key_metrics: list[dict],
    evidence_list: list[dict],
    conclusion_text: str,
    missing_data_text: str | None,
    next_action_text: str | None,
) -> AnalysisResult:
    """写入分析结果（六模块），并同步生成 markdown 与落盘文件。"""
    existing = db.execute(
        select(AnalysisResult).where(AnalysisResult.task_id == task.id)
    ).scalar_one_or_none()
    if existing is not None:
        db.delete(existing)
        db.commit()

    result = AnalysisResult(
        task_id=task.id,
        conversation_id=task.conversation_id,
        problem_definition=problem_definition,
        key_metrics_json=key_metrics,
        evidence_list_json=evidence_list,
        conclusion_text=conclusion_text,
        missing_data_text=missing_data_text,
        next_action_text=next_action_text,
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    markdown = render_markdown(result, task)
    result.result_markdown = markdown
    db.commit()

    # 生成导出文件（markdown + excel），失败不影响主流程
    try:
        path = export_file(db, result, task, FORMAT_MARKDOWN)
        result.result_file_path = path
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("结果 #%s 导出 markdown 失败: %s", result.id, exc)

    logger.info("任务 #%s 生成分析结果 #%s", task.id, result.id)
    return result


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def render_markdown(result: AnalysisResult, task: AnalysisTask | None = None) -> str:
    """按六模块渲染标准 markdown 报告。"""
    lines: list[str] = []
    lines.append(f"# 经营归因分析报告")
    lines.append("")
    if task is not None:
        lines.append(f"- 任务编号：#{task.id}")
        lines.append(f"- 分析问题：{task.input_text}")
        lines.append(f"- 完成时间：{_iso(task.finished_at) or _iso(result.created_at) or ''}")
    else:
        lines.append(f"- 结果编号：#{result.id}")
        lines.append(f"- 生成时间：{_iso(result.created_at) or ''}")
    lines.append("")

    # 一、问题定义
    lines.append("## 一、问题定义")
    lines.append("")
    lines.append(result.problem_definition or "（未提供）")
    lines.append("")

    # 二、关键指标
    lines.append("## 二、关键指标")
    lines.append("")
    metrics = result.key_metrics
    if metrics:
        lines.append("| 指标名称 | 指标值 | 单位 | 统计口径/周期 |")
        lines.append("| --- | --- | --- | --- |")
        for m in metrics:
            lines.append(
                f"| {m.get('metric_name', '')} | {m.get('metric_value', '')} | "
                f"{m.get('metric_unit', '')} | {m.get('metric_period', '')} |"
            )
    else:
        lines.append("（无关键指标）")
    lines.append("")

    # 三、证据链
    lines.append("## 三、证据链")
    lines.append("")
    evidences = result.evidence_list
    if evidences:
        for i, e in enumerate(evidences, 1):
            conf = e.get("confidence", 0)
            try:
                conf_text = f"{float(conf) * 100:.0f}%"
            except (TypeError, ValueError):
                conf_text = str(conf)
            lines.append(f"### 证据 {i}｜{e.get('source_name', '')}")
            lines.append("")
            lines.append(f"- 来源类型：{e.get('source_type', '')}")
            lines.append(f"- 关联指标：{e.get('related_metric', '')}")
            lines.append(f"- 置信度：{conf_text}")
            lines.append(f"- 证据内容：{e.get('evidence_text', '')}")
            lines.append("")
    else:
        lines.append("（未采集到证据）")
        lines.append("")

    # 四、结论
    lines.append("## 四、结论")
    lines.append("")
    lines.append(result.conclusion_text or "（未提供）")
    lines.append("")

    # 五、缺失数据
    lines.append("## 五、数据缺口")
    lines.append("")
    lines.append(result.missing_data_text or "（本次分析所需数据完整）")
    lines.append("")

    # 六、下一步行动建议
    lines.append("## 六、下一步行动建议")
    lines.append("")
    lines.append(result.next_action_text or "（未提供）")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*本报告由经营多轮归因分析系统自动生成，结论均可回溯至上方证据链。*")
    return "\n".join(lines)


def render_text_summary(result: AnalysisResult) -> str:
    """对话气泡用的精简文本（结论 + 首要建议）。"""
    parts = [result.conclusion_text.strip()]
    if result.next_action_text:
        parts.append("")
        parts.append("下一步：" + result.next_action_text.strip())
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------

def export_file(db: Session, result: AnalysisResult, task: AnalysisTask, fmt: str) -> str:
    """导出到 exports/{user_id}/{conversation_id}/，返回入库相对路径。"""
    fmt = normalize_format(fmt)

    user_id = task.user_id
    conversation_id = task.conversation_id
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if fmt == FORMAT_MARKDOWN:
        filename = f"分析报告_任务{task.id}_{stamp}.md"
        content = result.result_markdown or render_markdown(result, task)
        target_dir = dir_of(KIND_EXPORT, user_id, conversation_id)
        target = safe_join(target_dir, _safe(filename))
        target.write_text(content, encoding="utf-8")
        return f"{KIND_EXPORT}/{user_id}/{conversation_id}/{target.name}"

    if fmt == FORMAT_JSON:
        filename = f"分析结果_任务{task.id}_{stamp}.json"
        payload = to_dict(result, task, with_markdown=False)
        target_dir = dir_of(KIND_EXPORT, user_id, conversation_id)
        target = safe_join(target_dir, _safe(filename))
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        return f"{KIND_EXPORT}/{user_id}/{conversation_id}/{target.name}"

    # Excel：指标 / 证据 / 结论 三个工作表
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    filename = f"分析结果_任务{task.id}_{stamp}.xlsx"
    wb = Workbook()

    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="4B6BFB")
    wrap = Alignment(wrap_text=True, vertical="top")

    ws1 = wb.active
    ws1.title = "关键指标"
    ws1.append(["指标名称", "指标值", "单位", "统计口径/周期"])
    for m in result.key_metrics:
        ws1.append([
            m.get("metric_name", ""),
            m.get("metric_value", ""),
            m.get("metric_unit", ""),
            m.get("metric_period", ""),
        ])

    ws2 = wb.create_sheet("证据链")
    ws2.append(["序号", "来源类型", "来源名称", "关联指标", "置信度", "证据内容"])
    for i, e in enumerate(result.evidence_list, 1):
        ws2.append([
            i,
            e.get("source_type", ""),
            e.get("source_name", ""),
            e.get("related_metric", ""),
            e.get("confidence", ""),
            e.get("evidence_text", ""),
        ])

    ws3 = wb.create_sheet("结论与建议")
    ws3.append(["模块", "内容"])
    ws3.append(["问题定义", result.problem_definition])
    ws3.append(["结论", result.conclusion_text])
    ws3.append(["数据缺口", result.missing_data_text or ""])
    ws3.append(["下一步行动建议", result.next_action_text or ""])

    for ws in (ws1, ws2, ws3):
        for cell in ws[1]:
            cell.font = head_font
            cell.fill = head_fill
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = wrap
        for col in ws.columns:
            letter = col[0].column_letter
            width = max((len(str(c.value)) for c in col if c.value is not None), default=10)
            ws.column_dimensions[letter].width = min(max(width + 4, 14), 60)

    target_dir = dir_of(KIND_EXPORT, user_id, conversation_id)
    target = safe_join(target_dir, _safe(filename))
    wb.save(target)
    wb.close()

    return f"{KIND_EXPORT}/{user_id}/{conversation_id}/{target.name}"


def _safe(filename: str) -> str:
    from app.core.paths import sanitize_filename

    return sanitize_filename(filename)


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def get_owned(db: Session, user: User, result_id: int) -> AnalysisResult:
    result = db.get(AnalysisResult, result_id)
    if result is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="分析结果不存在")
    task = db.get(AnalysisTask, result.task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="分析结果不存在或无权访问")
    return result


def get_by_task(db: Session, task_id: int) -> AnalysisResult | None:
    return db.execute(
        select(AnalysisResult).where(AnalysisResult.task_id == task_id)
    ).scalar_one_or_none()


def list_for_conversation(db: Session, conversation_id: int) -> list[AnalysisResult]:
    stmt = (
        select(AnalysisResult)
        .where(AnalysisResult.conversation_id == conversation_id)
        .order_by(AnalysisResult.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


def download_url(result_id: int, fmt: str = "md") -> str:
    """结果文件下载地址（docs/API.md §8.2）。"""
    base = settings.public_base_url.rstrip("/")
    return f"{base}/api/results/download?result_id={result_id}&format={fmt}"


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------

def to_dict(result: AnalysisResult, task: AnalysisTask | None = None, *, with_markdown: bool = True) -> dict:
    """转成 API 响应字典（字段与 docs/API.md §11 一致）。"""
    return {
        "result_id": result.id,
        "task_id": result.task_id,
        "conversation_id": result.conversation_id,
        "problem_definition": result.problem_definition,
        "key_metrics": result.key_metrics,
        "evidence_list": result.evidence_list,
        "conclusion_text": result.conclusion_text,
        "missing_data_text": result.missing_data_text,
        "next_action_text": result.next_action_text,
        "result_markdown": result.result_markdown if with_markdown else None,
        "result_file_path": result.result_file_path,
        "download_url": download_url(result.id, FORMAT_MARKDOWN),
        "created_at": _iso(result.created_at),
    }


def resolve_export_file(result: AnalysisResult, fmt: str, task: AnalysisTask, db: Session) -> Path:
    """取得导出文件路径；不存在则按需生成。"""
    if fmt == FORMAT_MARKDOWN and result.result_file_path:
        try:
            p = abs_path(result.result_file_path)
            if p.is_file():
                return p
        except ValueError:
            pass
    rel = export_file(db, result, task, fmt)
    return abs_path(rel)
