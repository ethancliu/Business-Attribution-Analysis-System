# -*- coding: utf-8 -*-
"""后端自检脚本：不依赖 HTTP 服务，直接验证分析引擎的完整链路。

检查项:
    1. 运行时配置是否全部可从数据库加载
    2. 场景路由是否把典型问题分派到预期场景
    3. 每个场景步骤链里的 SQL 是否真的能在业务库上跑通
    4. 六大模块是否都产出非空内容
    5. 七个工具是否都已注册

用法（在 backend/ 目录下）:
    .venv\\Scripts\\python.exe -X utf8 scripts\\selfcheck.py
    .venv\\Scripts\\python.exe -X utf8 scripts\\selfcheck.py --scenario catalog
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import traceback
from pathlib import Path

# 允许以 `python scripts/selfcheck.py` 方式直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.analysis import scenarios as scenario_pkg  # noqa: E402
from app.analysis.tools import ToolContext, get_tool, tool_metadata  # noqa: E402
from app.analysis.tools.base import TaskCancelled  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.core.runtime_config import runtime_config  # noqa: E402

# 每个场景配一个贴近真实运营提问的问题
CASES: list[tuple[str, str]] = [
    ("catalog", "美妆个护类目最近转化率掉得厉害，是不是商品卡和主图有问题？"),
    ("market", "信息流渠道 ROAS 从 5.9 掉到 1.6，投放预算没变，问题出在哪？"),
    ("inventory", "最近缺货和库存积压同时出现，周转是不是恶化了？"),
    ("feedback", "商品差评突然变多，评分也掉了，用户主要在抱怨什么？"),
    ("refund", "退款率升高了，是商品质量问题还是物流问题？"),
    ("growth", "9 月下半月 GMV 整体下滑，帮我拆一下是流量还是转化的问题"),
    ("generic", "帮我看看整体经营情况有没有异常"),
]

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

failures: list[str] = []


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def bad(msg: str) -> None:
    failures.append(msg)
    print(f"  {RED}✗{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}!{RESET} {msg}")


# ---------------------------------------------------------------------------
# 1. 配置
# ---------------------------------------------------------------------------

def check_config() -> None:
    print("\n[1] 运行时配置")
    report = runtime_config.load()
    print(f"  配置来源：{runtime_config.source}，键数：{report.total_keys}")
    if runtime_config.source != "database":
        bad(f"配置来源不是数据库而是 {runtime_config.source}，热重载将不可用")
        return

    expected = [
        "system.name", "system.env", "system.max_upload_mb", "system.allow_extensions",
        "system.max_concurrent_tasks", "websocket.token_ttl_sec",
        "analysis.base_period_start", "analysis.base_period_end",
        "analysis.anomaly_period_start", "analysis.anomaly_period_end",
        "analysis.context_keep_rounds", "analysis.summary_trigger_messages",
        "analysis.tool_timeout_sec", "security.sql_row_limit", "feature.enable_shell_tool",
    ]
    missing = [k for k in expected if runtime_config.get(k) is None]
    if missing:
        bad(f"以下配置键在 system_configs 中不存在：{missing}")
    else:
        ok(f"{len(expected)} 个关键配置键全部命中数据库")


# ---------------------------------------------------------------------------
# 2. 路由
# ---------------------------------------------------------------------------

def check_routing() -> list[tuple[str, str]]:
    print("\n[2] 场景路由")
    selected: list[tuple[str, str]] = []
    for expect_key, question in CASES:
        scenario, intent, scores = scenario_pkg.route(question)
        top = ", ".join(f"{s['key']}={s['score']}" for s in scores[:3])
        if scenario.key == expect_key:
            ok(f"{expect_key:<10} ← 「{question[:26]}…」  {DIM}{top}{RESET}")
            selected.append((expect_key, question))
        else:
            bad(f"「{question[:26]}…」期望 {expect_key}，实际 {scenario.key}  {top}")
    return selected


# ---------------------------------------------------------------------------
# 3. 工具注册
# ---------------------------------------------------------------------------

def check_tools() -> None:
    print("\n[3] 工具注册表")
    names = [t["name"] for t in tool_metadata()]
    expected = ["db_query", "file_read", "file_write", "text_search", "shell_exec", "result_generate"]
    absent = [n for n in expected if n not in names]
    if absent:
        bad(f"未注册的工具：{absent}")
    else:
        ok(f"已注册 {len(names)} 个工具：{', '.join(names)}")


# ---------------------------------------------------------------------------
# 4. 场景步骤链（真实执行 SQL）
# ---------------------------------------------------------------------------

def run_scenario(key: str, question: str) -> None:
    print(f"\n[4] 场景执行：{key}")
    scenario, intent, _ = scenario_pkg.route(question)

    with session_scope() as db:
        ctx = ToolContext(
            db=db,
            task_id=0,
            conversation_id=0,
            user_id=1,
            input_text=question,
            cancel_event=threading.Event(),
        )
        try:
            steps = scenario.build(ctx, intent)
        except Exception as exc:  # noqa: BLE001
            bad(f"build 失败：{exc}")
            traceback.print_exc()
            return

        print(f"  {DIM}意图：{ {k: v for k, v in intent.items() if k not in ('raw', 'route_scores')} }{RESET}")
        print(f"  步骤链（{len(steps)} 步）：")

        results = {}
        for i, step in enumerate(steps, start=1):
            ctx.step_index = i
            try:
                # 与引擎 _resolve_args 一致：@step_key 替换为前序产出
                args = {}
                for k, v in (step.args or {}).items():
                    if isinstance(v, str) and v.startswith("@"):
                        prev = results.get(v[1:])
                        args[k] = prev.data if prev is not None and prev.ok else []
                    else:
                        args[k] = v

                tool = get_tool(step.tool)
                result = tool.safe_run(ctx, **args)
                results[step.key] = result
            except TaskCancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                bad(f"步骤 {i}「{step.title}」异常：{exc}")
                traceback.print_exc()
                continue

            if result.ok:
                n = len(result.data) if isinstance(result.data, list) else "—"
                ok(f"{i}. {step.title} [{step.tool}] 行数={n} — {result.summary}")
            else:
                flag = "关键步骤" if step.critical else "非关键"
                bad(f"{i}. {step.title} [{step.tool}]（{flag}）失败：{result.error}")

        # 解释
        try:
            interp = scenario.interpret(ctx, intent, results, steps)
        except Exception as exc:  # noqa: BLE001
            bad(f"interpret 失败：{exc}")
            traceback.print_exc()
            return

        modules = {
            "模块1 问题定义": interp.problem_definition,
            "模块2 关键指标": interp.key_metrics,
            "模块3 证据列表": interp.evidence_list,
            "模块4 归因结论": interp.conclusion_text,
            "模块5 待补充数据": interp.missing_data_text,
            "模块6 下一步建议": interp.next_action_text,
        }
        for name, value in modules.items():
            if not value:
                bad(f"{name} 为空")
            elif isinstance(value, (list, dict)):
                ok(f"{name}：{len(value)} 条")
            else:
                ok(f"{name}：{len(str(value))} 字")

        # 报告生成
        try:
            gen = get_tool("result_generate").safe_run(
                ctx,
                problem_definition=interp.problem_definition,
                key_metrics=interp.key_metrics,
                evidence_list=interp.evidence_list,
                conclusion_text=interp.conclusion_text,
                missing_data_text=interp.missing_data_text,
                next_action_text=interp.next_action_text,
                meta={"场景": scenario.name},
            )
            if gen.ok:
                md = (gen.data or {}).get("result_markdown", "") if isinstance(gen.data, dict) else ""
                ok(f"报告生成：{len(md)} 字 markdown")
                missing_heads = [
                    h for h in ("## 一、问题定义", "## 二、关键指标", "## 三、证据链",
                                "## 四、结论", "## 五、数据缺口", "## 六、下一步行动建议")
                    if h not in md
                ]
                if missing_heads:
                    bad(f"报告缺少模块标题：{missing_heads}")
            else:
                bad(f"报告生成失败：{gen.error}")
        except Exception as exc:  # noqa: BLE001
            bad(f"报告生成异常：{exc}")
            traceback.print_exc()


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="后端分析链路自检")
    parser.add_argument("--scenario", default=None, help="只跑指定场景")
    args = parser.parse_args()

    print("=" * 78)
    print("经营多轮归因分析系统 —— 后端自检")
    print("=" * 78)

    check_config()

    if args.scenario:
        cases = [(k, q) for k, q in CASES if k == args.scenario]
        if not cases:
            print(f"{RED}未知场景：{args.scenario}（可选：{[k for k, _ in CASES]}）{RESET}")
            return 2
        check_tools()
        for key, question in cases:
            run_scenario(key, question)
    else:
        check_tools()
        check_routing()
        for key, question in CASES:
            run_scenario(key, question)

    print("\n" + "=" * 78)
    if failures:
        print(f"{RED}自检失败：{len(failures)} 项{RESET}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"{GREEN}自检通过{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
