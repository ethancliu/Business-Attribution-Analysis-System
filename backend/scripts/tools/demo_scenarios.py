# -*- coding: utf-8 -*-
"""跑通 DEMO 用的 6 个业务场景：真实走 OAuth 登录 -> 提问 -> 轮询任务 -> 取六大模块结果。

前置：认证中心(9000) 与 后端(8000) 已启动。

用法（在 backend/ 目录下）:
    .venv\\Scripts\\python.exe -X utf8 scripts\\tools\\demo_scenarios.py

产物：
    backend/data/_demo_dump/scenario_1.json .. scenario_6.json   （原始结果 JSON）
    backend/data/_demo_dump/followup_reuse.json                  （场景1会话的追问）
    backend/data/_demo_dump/followup_suggested.json              （任务书示例追问，另开会话复现）

只做调用与取数，不改写任何接口返回内容。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import httpx  # noqa: E402

BACKEND = os.environ.get("DEMO_BACKEND", "http://localhost:8000")
AUTH = os.environ.get("DEMO_AUTH", "http://localhost:9000")

ANALYST = ("analyst", "Analyst@123")
ADMIN = ("admin", "Admin@123")

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DUMP_DIR = BACKEND_ROOT / "data" / "_demo_dump"

POLL_INTERVAL = 0.5
POLL_TIMEOUT = 120.0

QUESTIONS = [
    "美妆个护类目点击率腰斩，从 4.2% 掉到 2.1%，问题出在哪？",
    "信息流渠道 ROAS 从 5.9 掉到 1.6，投放预算没变，问题出在哪？",
    "用户主要在抱怨什么？差评有没有集中爆发的点？",
    "我的商品页转化率最近掉得厉害，帮我看看是什么原因？",
    "9 月下半月整体 GMV 环比下滑，是哪些因素导致的？",
    "这次促销活动的效果为什么不如预期？",
]

FOLLOWUP_REUSE = "那这个问题严重吗？需要马上处理吗？"
FOLLOWUP_SUGGESTED = "那库存和履约方面有没有影响？"


# ---------------------------------------------------------------------------
# 认证（照搬 scripts/e2e_check.py 的 OAuth 授权码流程）
# ---------------------------------------------------------------------------

def _backend_redirect_uri(authorize_location: str) -> str:
    try:
        got = (parse_qs(urlparse(authorize_location).query).get("redirect_uri") or [""])[0]
    except ValueError:
        got = ""
    return got or f"{BACKEND}/auth/callback"


def _as_backend_path(url: str) -> str:
    src = urlparse(url)
    dst = urlparse(BACKEND)
    return urlunparse(src._replace(scheme=dst.scheme, netloc=dst.netloc))


def login(client: httpx.Client, username: str, password: str) -> dict:
    r = client.get(f"{BACKEND}/auth/login", follow_redirects=False)
    if r.status_code != 302:
        raise RuntimeError(f"/auth/login 期望 302，实际 {r.status_code}")
    redirect_uri = _backend_redirect_uri(r.headers.get("location", ""))
    state = client.cookies.get("jy_oauth_state")
    if not state:
        raise RuntimeError("未下发 jy_oauth_state Cookie")
    r = client.post(
        f"{AUTH}/oauth/login",
        data={
            "username": username,
            "password": password,
            "client_id": "jingying-web",
            "redirect_uri": redirect_uri,
            "scope": "openid profile analysis",
            "state": state,
        },
        follow_redirects=False,
    )
    if r.status_code != 302:
        raise RuntimeError(f"登录提交期望 302，实际 {r.status_code}（口令是否正确？）")
    r = client.get(_as_backend_path(r.headers.get("location", "")), follow_redirects=False)
    if not client.cookies.get("jy_access_token"):
        raise RuntimeError("/auth/callback 未下发 jy_access_token Cookie")
    me = client.get(f"{BACKEND}/api/auth/me")
    if me.status_code != 200:
        raise RuntimeError(f"/api/auth/me 期望 200，实际 {me.status_code}")
    return me.json()


# ---------------------------------------------------------------------------
# 业务调用
# ---------------------------------------------------------------------------

def create_conversation(client: httpx.Client, title: str) -> int:
    r = client.post(f"{BACKEND}/api/chat/create", json={"title": title})
    if r.status_code != 200:
        raise RuntimeError(f"新建会话失败：{r.status_code} {r.text[:200]}")
    return r.json()["conversation_id"]


def send_question(client: httpx.Client, conversation_id: int, content: str) -> dict:
    r = client.post(
        f"{BACKEND}/api/chat/send",
        json={"conversation_id": conversation_id, "content": content},
    )
    if r.status_code != 200:
        raise RuntimeError(f"提问失败：{r.status_code} {r.text[:300]}")
    return r.json()


def poll_task(client: httpx.Client, task_id: int) -> tuple[dict, float]:
    t0 = time.time()
    detail: dict = {}
    while time.time() - t0 < POLL_TIMEOUT:
        r = client.get(f"{BACKEND}/api/tasks/{task_id}")
        if r.status_code == 200:
            detail = r.json()
            if detail.get("task_status") in ("success", "failed", "cancelled"):
                return detail, time.time() - t0
        time.sleep(POLL_INTERVAL)
    raise RuntimeError(f"任务 {task_id} 轮询超时（{POLL_TIMEOUT}s），最后状态 {detail.get('task_status')}")


def fetch_result(client: httpx.Client, task_id: int) -> dict | None:
    r = client.get(f"{BACKEND}/api/results/{task_id}")
    if r.status_code != 200:
        return None
    return r.json()


def fetch_logs(admin: httpx.Client, task_id: int, log_type: str) -> list[dict]:
    r = admin.get(
        f"{BACKEND}/api/admin/logs",
        params={"task_id": task_id, "log_type": log_type, "limit": 50},
    )
    if r.status_code != 200:
        return []
    return r.json().get("items", [])


def export_size(client: httpx.Client, result_id: int, fmt: str) -> dict:
    r = client.get(
        f"{BACKEND}/api/results/download",
        params={"result_id": result_id, "format": fmt},
    )
    return {
        "status_code": r.status_code,
        "bytes": len(r.content) if r.status_code == 200 else None,
        "content_type": r.headers.get("content-type", ""),
        "magic": r.content[:4].hex() if r.content else None,
    }


def scenario_from_logs(admin: httpx.Client, task_id: int) -> dict:
    lifecycle = fetch_logs(admin, task_id, "lifecycle")
    llm = fetch_logs(admin, task_id, "llm")
    route_line = next(
        (i["log_content"] for i in lifecycle if i["log_content"].startswith("场景路由|")),
        "",
    )
    route_score_line = next(
        (i["log_content"] for i in llm if "场景路由得分" in i["log_content"]),
        "",
    )
    parts = route_line.split("|")
    return {
        "route_log_line": route_line,
        "scenario_key": parts[1].strip() if len(parts) > 1 else "",
        "scenario_name": parts[2].strip() if len(parts) > 2 else "",
        "route_score_log": route_score_line,
        "lifecycle_logs": [i["log_content"] for i in lifecycle],
    }


def module_sizes(result: dict) -> dict:
    metrics = result.get("key_metrics") or []
    evidence = result.get("evidence_list") or []
    return {
        "problem_definition_chars": len(str(result.get("problem_definition") or "")),
        "key_metrics_count": len(metrics),
        "evidence_list_count": len(evidence),
        "conclusion_text_chars": len(str(result.get("conclusion_text") or "")),
        "missing_data_text_chars": len(str(result.get("missing_data_text") or "")),
        "next_action_text_chars": len(str(result.get("next_action_text") or "")),
        "result_markdown_chars": len(str(result.get("result_markdown") or "")),
    }


# ---------------------------------------------------------------------------
# 单轮执行
# ---------------------------------------------------------------------------

def run_turn(client: httpx.Client, admin: httpx.Client, conversation_id: int, content: str) -> dict:
    sent = send_question(client, conversation_id, content)
    task_id = sent["task_id"]
    detail, poll_seconds = poll_task(client, task_id)
    result = fetch_result(client, task_id) if detail.get("task_status") == "success" else None
    route = scenario_from_logs(admin, task_id)

    exports = {}
    if result is not None:
        for fmt in ("md", "json", "xlsx"):
            exports[fmt] = export_size(client, result["result_id"], fmt)

    record = {
        "input_text": content,
        "conversation_id": conversation_id,
        "task_id": task_id,
        "task_status": detail.get("task_status"),
        "error_message": detail.get("error_message"),
        "duration_ms": detail.get("duration_ms"),
        "poll_seconds": round(poll_seconds, 2),
        "tool_call_count": len(detail.get("tool_calls") or []),
        "tool_calls": detail.get("tool_calls") or [],
        "result_id": detail.get("result_id"),
        "result": result,
        "module_sizes": module_sizes(result) if result else None,
        "exports": exports,
        "route": route,
        "sent_at": sent.get("created_at"),
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return record


def run_followup(
    client: httpx.Client,
    admin: httpx.Client,
    conversation_id: int,
    content: str,
    dump_name: str,
) -> dict:
    record = run_turn(client, admin, conversation_id, content)
    (DUMP_DIR / dump_name).write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return record


# ---------------------------------------------------------------------------

def main() -> int:
    DUMP_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=60, follow_redirects=False) as client, \
            httpx.Client(timeout=60, follow_redirects=False) as admin_client:
        me = login(client, *ANALYST)
        admin_me = login(admin_client, *ADMIN)
        print(f"[登录] 分析用户 {me['display_name']}（{me['username']} / {me['role']}），"
              f"管理员 {admin_me['display_name']}（{admin_me['role']}）")

        summary_rows = []

        for idx, question in enumerate(QUESTIONS, start=1):
            conv_id = create_conversation(client, f"DEMO场景{idx}")
            record = run_turn(client, admin_client, conv_id, question)
            (DUMP_DIR / f"scenario_{idx}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
            ms = record["module_sizes"] or {}
            ex = record["exports"]
            print(
                f"[场景{idx}] {record['task_status']} | {record['duration_ms']}ms | "
                f"conv={conv_id} task={record['task_id']} | "
                f"场景={record['route']['scenario_key']}（{record['route']['scenario_name']}） | "
                f"工具={record['tool_call_count']}次 | "
                f"问题定义={ms.get('problem_definition_chars', 0)}字 / "
                f"指标={ms.get('key_metrics_count', 0)}条 / "
                f"证据={ms.get('evidence_list_count', 0)}条 / "
                f"结论={ms.get('conclusion_text_chars', 0)}字 / "
                f"缺口={ms.get('missing_data_text_chars', 0)}字 / "
                f"建议={ms.get('next_action_text_chars', 0)}字 | "
                f"导出 md={ex.get('md', {}).get('bytes')} json={ex.get('json', {}).get('bytes')} "
                f"xlsx={ex.get('xlsx', {}).get('bytes')}"
            )
            summary_rows.append({
                "idx": idx,
                "question": question,
                "conversation_id": conv_id,
                "task_id": record["task_id"],
                "task_status": record["task_status"],
                "duration_ms": record["duration_ms"],
                "scenario_key": record["route"]["scenario_key"],
                "scenario_name": record["route"]["scenario_name"],
                "tool_call_count": record["tool_call_count"],
                "module_sizes": ms,
                "exports": {k: v.get("bytes") for k, v in ex.items()},
            })

        # ---------------- 多轮追问：场景 1 的会话 ----------------
        conv1 = summary_rows[0]["conversation_id"]
        fu_reuse = run_followup(client, admin_client, conv1, FOLLOWUP_REUSE, "followup_reuse.json")
        print(
            f"[追问-复用] conv={conv1} task={fu_reuse['task_id']} status={fu_reuse['task_status']} | "
            f"场景={fu_reuse['route']['scenario_key']} | {fu_reuse['route']['route_log_line']}"
        )
        print(f"    route_score_log: {fu_reuse['route']['route_score_log']}")

        # ---------------- 任务书示例追问：另开会话复现 ----------------
        conv_x = create_conversation(client, "DEMO追问示例")
        run_turn(client, admin_client, conv_x, QUESTIONS[0])
        fu_sug = run_followup(client, admin_client, conv_x, FOLLOWUP_SUGGESTED, "followup_suggested.json")
        print(
            f"[追问-示例] conv={conv_x} task={fu_sug['task_id']} status={fu_sug['task_status']} | "
            f"场景={fu_sug['route']['scenario_key']} | {fu_sug['route']['route_log_line']}"
        )

        (DUMP_DIR / "_summary.json").write_text(
            json.dumps(summary_rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

    print(f"\n[done] dump 目录：{DUMP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
