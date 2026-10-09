# -*- coding: utf-8 -*-
"""把 _demo_dump 下的原始 JSON 提取成便于撰写 DEMO 文档的紧凑文本。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DUMP_DIR = BACKEND_ROOT / "data" / "_demo_dump"
OUT = DUMP_DIR / "_extract.txt"

ROWS_RE = re.compile(r"返回\s*(\d+)\s*行")
HIT_RE = re.compile(r"命中\s*(\d+)\s*处")


def rows_of(summary: str) -> str:
    if not summary:
        return "-"
    m = ROWS_RE.search(summary)
    if m:
        return m.group(1)
    m = HIT_RE.search(summary)
    if m:
        return f"{m.group(1)}(命中)"
    if summary.startswith("已写出"):
        return "-"
    if summary.startswith("已生成"):
        return "-"
    return "-"


def args_brief(tool: str, args: dict) -> str:
    if tool == "db_query":
        sql = " ".join(str(args.get("sql", "")).split())
        return (sql[:110] + "…") if len(sql) > 110 else sql
    if tool == "text_search":
        return f'keyword={args.get("keyword")} scope={args.get("scope")} limit={args.get("limit")}'
    if tool == "file_write":
        return f'file_name={args.get("file_name")} format={args.get("format")} content=@前序步骤'
    if tool == "result_generate":
        return f'scene={args.get("scene")} metrics={args.get("metrics")} evidence={args.get("evidence")}'
    return json.dumps(args, ensure_ascii=False)[:110]


def dump_one(path: Path) -> str:
    rec = json.loads(path.read_text(encoding="utf-8"))
    lines: list[str] = []
    lines.append("=" * 100)
    lines.append(f"### {path.name}")
    lines.append(f"提问: {rec['input_text']}")
    lines.append(
        f"conv={rec['conversation_id']} task={rec['task_id']} status={rec['task_status']} "
        f"result_id={rec['result_id']} poll={rec['poll_seconds']}s"
    )
    lifecycle = rec["route"]["lifecycle_logs"]
    finish = next((x for x in lifecycle if x.startswith("任务完成")), "")
    lines.append(f"完成日志: {finish}")
    lines.append(f"路由日志: {rec['route']['route_log_line']}")
    lines.append(f"路由得分: {rec['route']['route_score_log']}")
    lines.append("")
    lines.append("-- 工具调用链 --")
    for c in rec["tool_calls"]:
        lines.append(
            f"{c['seq']} | {c['tool_name']} | {c['status']} | {c['duration_ms']}ms | "
            f"rows={rows_of(c.get('summary',''))} | {args_brief(c['tool_name'], c.get('tool_args') or {})}"
        )
        lines.append(f"    summary: {c.get('summary','')}")
    lines.append("")
    lines.append("-- 导出字节 --")
    for fmt, info in rec["exports"].items():
        lines.append(f"{fmt}: status={info['status_code']} bytes={info['bytes']} ct={info['content_type']}")
    lines.append("")
    res = rec.get("result")
    if not res:
        lines.append(f"!! 无结果。error_message={rec.get('error_message')}")
        return "\n".join(lines)

    lines.append("-- 模块1 问题定义 --")
    lines.append(res["problem_definition"])
    lines.append("")
    lines.append("-- 模块2 关键指标 --")
    for m in res["key_metrics"]:
        lines.append(f"{m['metric_name']} | {m['metric_value']} | {m['metric_unit']} | {m['metric_period']}")
    lines.append("")
    lines.append("-- 模块3 证据列表 --")
    for i, e in enumerate(res["evidence_list"], 1):
        lines.append(
            f"{i} | {e['source_name']} | {e['source_type']} | conf={e['confidence']} | "
            f"metric={e['related_metric']} | {e['evidence_text']}"
        )
    lines.append("")
    lines.append("-- 模块4 结论 --")
    lines.append(res["conclusion_text"])
    lines.append("")
    lines.append("-- 模块5 待补充数据 --")
    lines.append(res["missing_data_text"] or "")
    lines.append("")
    lines.append("-- 模块6 下一步建议 --")
    lines.append(res["next_action_text"] or "")
    lines.append("")
    lines.append(f"result_file_path: {res['result_file_path']}")
    lines.append(f"created_at: {res['created_at']}")
    lines.append(f"module_sizes: {json.dumps(rec['module_sizes'], ensure_ascii=False)}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    files = [f"scenario_{i}.json" for i in range(1, 7)]
    files += ["followup_reuse.json", "followup_suggested.json"]
    out = []
    for name in files:
        p = DUMP_DIR / name
        if p.is_file():
            out.append(dump_one(p))
    text = "\n".join(out)
    OUT.write_text(text, encoding="utf-8")
    print(f"[ok] {OUT} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
