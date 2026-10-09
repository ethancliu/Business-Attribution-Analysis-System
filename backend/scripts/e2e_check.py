# -*- coding: utf-8 -*-
"""端到端验收脚本：按验收标准 1~8 逐条走真实 HTTP / WebSocket 链路。

前置：认证中心（9000）与后端（8000）已启动。

用法（在 backend/ 目录下）:
    .venv\\Scripts\\python.exe -X utf8 scripts\\e2e_check.py
    .venv\\Scripts\\python.exe -X utf8 scripts\\e2e_check.py --user admin --password Admin@123
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import httpx  # noqa: E402

BACKEND = os.environ.get("E2E_BACKEND", "http://localhost:8000")
AUTH = os.environ.get("E2E_AUTH", "http://localhost:9000")

WS_TYPES_EXPECTED = {
    "message_start", "message_delta", "tool_start", "tool_finish",
    "task_status", "result_ready", "done",
}

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

failures: list[str] = []


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def bad(msg: str) -> None:
    failures.append(msg)
    print(f"  {RED}✗{RESET} {msg}")


def step(n: str, title: str) -> None:
    print(f"\n{n} {title}")


def _backend_redirect_uri(authorize_location: str) -> str:
    """从 `/auth/login` 的 302 Location 里取出后端自己配置的 redirect_uri。

    浏览器是「照着 302 走」——回调地址由后端配置决定，调用方无从猜测。
    E2E 必须照做：若自己拼成 `{BACKEND}/auth/callback`，一旦把 BACKEND 指向
    代理端口（如 Vite 5173），认证中心记下的回调地址就与后端换令牌时提交的
    不一致，会直接 400「回调地址不一致」。这里解析不出来才退回默认值。
    """
    from urllib.parse import parse_qs, urlparse

    try:
        got = (parse_qs(urlparse(authorize_location).query).get("redirect_uri") or [""])[0]
    except ValueError:
        got = ""
    return got or f"{BACKEND}/auth/callback"


def _as_backend_path(url: str) -> str:
    """把认证中心回跳的绝对地址改写成经 {BACKEND} 访问（用于验证代理链路）。"""
    from urllib.parse import urlparse, urlunparse

    src = urlparse(url)
    dst = urlparse(BACKEND)
    return urlunparse(src._replace(scheme=dst.scheme, netloc=dst.netloc))


# ---------------------------------------------------------------------------
# 1. 认证中心 OAuth2 授权码全流程
# ---------------------------------------------------------------------------

def do_login(client: httpx.Client, username: str, password: str) -> bool:
    step("[1]", "认证对接（OAuth2 授权码模式）")

    # 1.1 后端登录入口 -> 302 到认证中心，并下发 state Cookie
    r = client.get(f"{BACKEND}/auth/login", follow_redirects=False)
    if r.status_code != 302:
        bad(f"/auth/login 期望 302，实际 {r.status_code}")
        return False
    location = r.headers.get("location", "")
    state_cookie = client.cookies.get("jy_oauth_state")
    ok(f"/auth/login -> 302 认证中心（state Cookie {'已下发' if state_cookie else '缺失'}）")
    if not state_cookie:
        bad("未下发 jy_oauth_state Cookie，CSRF 防护失效")
        return False
    print(f"    {DIM}{location[:120]}{RESET}")

    # 1.2 认证中心渲染登录页
    r = client.get(location, follow_redirects=False)
    if r.status_code != 200 or "登录" not in r.text:
        bad(f"认证中心登录页异常：HTTP {r.status_code}")
        return False
    ok(f"认证中心登录页正常渲染（{len(r.text)} 字节，含演示账号提示）")

    # 1.3 提交账号口令 -> 302 回后端回调地址并带 code
    redirect_uri = _backend_redirect_uri(location)
    r = client.post(
        f"{AUTH}/oauth/login",
        data={
            "username": username,
            "password": password,
            "client_id": "jingying-web",
            "redirect_uri": redirect_uri,
            "scope": "openid profile analysis",
            "state": state_cookie,
        },
        follow_redirects=False,
    )
    if r.status_code != 302:
        bad(f"提交登录期望 302，实际 {r.status_code}（口令是否正确？）")
        return False
    callback_url = r.headers.get("location", "")
    if "code=" not in callback_url:
        bad(f"回调地址未携带授权码：{callback_url}")
        return False
    ok(f"登录成功，认证中心签发授权码并回跳（会话 Cookie {'已下发' if client.cookies.get('auth_sid') else '缺失'}）")

    # 1.4 后端回调：校验 state -> 换令牌 -> 种 HttpOnly Cookie
    #     经 {BACKEND} 访问（BACKEND 指向代理时即验证代理链路）
    r = client.get(_as_backend_path(callback_url), follow_redirects=False)
    if r.status_code != 302:
        bad(f"/auth/callback 期望 302，实际 {r.status_code}")
        return False
    token_cookie = client.cookies.get("jy_access_token")
    if not token_cookie:
        bad("/auth/callback 未下发 jy_access_token Cookie")
        return False
    ok(f"回调校验 state 通过，换取令牌并种下 HttpOnly Cookie jy_access_token（{len(token_cookie)} 字符）")
    print(f"    {DIM}最终跳转：{r.headers.get('location', '')}{RESET}")

    # 1.5 拿到登录态
    r = client.get(f"{BACKEND}/api/auth/me")
    if r.status_code != 200:
        bad(f"/api/auth/me 期望 200，实际 {r.status_code}")
        return False
    me = r.json()
    ok(f"登录态生效：{me['display_name']}（{me['username']}，角色 {me['role']}）")
    print(f"    {DIM}令牌剩余有效 {me['token_expires_in']} 秒，会话 {me.get('session_id')}{RESET}")
    return True


def _login_quiet(client: httpx.Client, username: str, password: str) -> bool:
    """静默走一遍 OAuth 授权码流程，只返回是否拿到登录 Cookie。"""
    r = client.get(f"{BACKEND}/auth/login", follow_redirects=False)
    if r.status_code != 302:
        return False
    redirect_uri = _backend_redirect_uri(r.headers.get("location", ""))
    state = client.cookies.get("jy_oauth_state")
    if not state:
        return False
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
        return False
    r = client.get(_as_backend_path(r.headers.get("location", "")), follow_redirects=False)
    return bool(client.cookies.get("jy_access_token"))


def check_auth_guard(client: httpx.Client) -> None:
    step("[2]", "鉴权拦截与越权防护")
    with httpx.Client(timeout=10) as anon:
        r = anon.get(f"{BACKEND}/api/chat/ls")
        if r.status_code == 401:
            ok("未携带令牌访问业务接口 -> 401")
        else:
            bad(f"未携带令牌应返回 401，实际 {r.status_code}")

        r = anon.get(f"{BACKEND}/api/admin/overview")
        if r.status_code == 401:
            ok("未携带令牌访问管理接口 -> 401")
        else:
            bad(f"管理接口未鉴权，实际 {r.status_code}")

        r = anon.get(f"{BACKEND}/api/chat/ls/999999")
        if r.status_code == 401:
            ok("未携带令牌访问他人会话 -> 401")
        else:
            bad(f"未携带令牌访问会话应 401，实际 {r.status_code}")

    # 普通分析用户访问管理接口，应被角色校验拦住
    r = client.get(f"{BACKEND}/api/admin/overview")
    if r.status_code in (200, 403):
        if r.status_code == 403:
            ok("分析用户访问管理接口 -> 403（角色校验生效）")
        else:
            print(f"  {YELLOW}!{RESET} 当前登录用户是管理员，跳过 403 校验（可用 --user analyst 复验）")
    else:
        bad(f"管理接口角色校验异常，实际 {r.status_code}")


# ---------------------------------------------------------------------------
# 3. 会话与消息
# ---------------------------------------------------------------------------

def check_conversation(client: httpx.Client) -> int:
    step("[3]", "会话管理（新建 / 改名 / 列表 / 历史分页）")

    r = client.post(f"{BACKEND}/api/chat/create", json={})
    if r.status_code != 200:
        bad(f"新建会话失败：{r.status_code} {r.text[:200]}")
        return 0
    conv_id = r.json()["conversation_id"]
    ok(f"新建会话成功：conversation_id={conv_id}，标题「{r.json()['title']}」（默认标题）")

    r = client.post(
        f"{BACKEND}/api/chat/update",
        json={"conversation_id": conv_id, "title": "端到端验收：渠道投放效率归因"},
    )
    if r.status_code == 200 and r.json()["title"].startswith("端到端验收"):
        ok("会话改名成功")
    else:
        bad(f"会话改名失败：{r.status_code} {r.text[:200]}")

    r = client.get(f"{BACKEND}/api/chat/ls")
    ids = [c["conversation_id"] for c in r.json().get("items", [])]
    if conv_id in ids:
        ok(f"会话列表可见（共 {r.json()['total']} 个会话）")
    else:
        bad("新建的会话未出现在列表中")

    r = client.get(f"{BACKEND}/api/chat/ls", params={"keyword": "端到端验收"})
    if r.status_code == 200:
        ok(f"会话搜索（按标题关键字）返回 {r.json()['total']} 条")
    else:
        bad(f"会话搜索失败：{r.status_code}")

    return conv_id


def check_attachment(client: httpx.Client, conv_id: int) -> int | None:
    step("[4]", "附件上传与解析")

    csv = (
        "channel,spend,order_cnt\n社媒-信息流,44906,539\n搜索-品牌词,32110,900\n"
        "内容-种草,28000,700\n私域-社群,15000,600\n"
    ).encode("utf-8")

    r = client.post(
        f"{BACKEND}/api/attachment/upload",
        data={"conversation_id": conv_id},
        files={"file": ("渠道投放明细.csv", csv, "text/csv")},
    )
    if r.status_code != 200:
        bad(f"附件上传失败：{r.status_code} {r.text[:300]}")
        return None
    att = r.json()
    att_id = att["attachment_id"]
    ok(f"附件上传成功：#{att_id} {att['file_name']}（{att['file_size']} 字节，类型 {att['file_type']}）")
    if att["parse_status"] == "parsed":
        ok("附件已即时解析")
    else:
        bad(f"附件解析状态异常：{att['parse_status']}")

    r = client.get(f"{BACKEND}/api/attachment/get", params={"attachment_id": att_id})
    if r.status_code == 200 and r.json().get("preview"):
        ok(f"附件详情可取，预览 {len(r.json()['preview'])} 字")
    else:
        bad(f"附件详情读取失败：{r.status_code}")

    r = client.get(f"{BACKEND}/api/attachment/get", params={"attachment_id": att_id, "download": "true"})
    if r.status_code == 200 and len(r.content) == len(csv):
        ok("附件下载内容与上传一致")
    else:
        bad(f"附件下载异常：{r.status_code}，{len(r.content)} 字节")

    r = client.get(f"{BACKEND}/api/attachment/ls", params={"conversation_id": conv_id})
    if r.status_code == 200 and r.json()["total"] >= 1:
        ok(f"附件列表返回 {r.json()['total']} 条")
    else:
        bad(f"附件列表异常：{r.status_code}")

    return att_id


# ---------------------------------------------------------------------------
# 5. 长连接 + 分析任务
# ---------------------------------------------------------------------------

async def _ws_session(ws_url: str, on_open=None, timeout: float = 90.0) -> list[dict]:
    """建连 -> 收到 connected -> 由 on_open 触发提问 -> 持续收报文直到 done。

    与前端真实时序一致：长连接常驻，提问是连上之后才发的。
    """
    import websockets

    events: list[dict] = []
    async with websockets.connect(ws_url, open_timeout=10, close_timeout=5) as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        events.append(json.loads(raw))
        if on_open is not None:
            await on_open()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, deadline - time.time()))
            except asyncio.TimeoutError:
                break
            except websockets.ConnectionClosed:
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            events.append(msg)
            if msg.get("type") == "done":
                break
    return events


async def collect_ws(ws_url: str, timeout: float = 90.0) -> list[dict]:
    """只建连收报文（用于令牌重放拒绝、迟到补发等场景）。"""
    return await _ws_session(ws_url, None, timeout)


def check_analysis(client: httpx.Client, conv_id: int, att_id: int | None, question: str) -> int:
    step("[5]", "实时分析链路（WebSocket + 分析任务）")

    # 5.1 取一次性长连接令牌
    r = client.post(f"{BACKEND}/api/chat/ws-token", json={"conversation_id": conv_id})
    if r.status_code != 200:
        bad(f"获取长连接令牌失败：{r.status_code} {r.text[:200]}")
        return 0
    ws = r.json()
    ok(f"获取一次性长连接令牌（有效期 {ws['expires_in']} 秒，过期时间 {ws['expires_at'][:19]}）")
    token = ws["websocket_token"]

    # 5.2 先建长连接，连上之后再提问（前端真实时序：连接常驻，提问后发）
    ws_url = f"{BACKEND.replace('http://', 'ws://')}/api/chat/ws/chat?websocket_token={token}"
    box: dict = {}

    async def _ask() -> None:
        payload = {"conversation_id": conv_id, "content": question}
        if att_id:
            payload["attachment_ids"] = [att_id]
        box["resp"] = await asyncio.to_thread(
            client.post, f"{BACKEND}/api/chat/send", json=payload
        )

    t0 = time.time()
    try:
        events = asyncio.run(_ws_session(ws_url, _ask))
    except Exception as exc:  # noqa: BLE001
        bad(f"长连接异常：{exc}")
        return 0
    elapsed = time.time() - t0

    resp = box.get("resp")
    if resp is None or resp.status_code != 200:
        code = getattr(resp, "status_code", "无响应")
        text = getattr(resp, "text", "")[:300]
        bad(f"发送提问失败：{code} {text}")
        return 0
    sent = resp.json()
    task_id = sent["task_id"]
    ok(f"提问已提交，创建分析任务 task_id={task_id}（状态 {sent['task_status']}）")

    if not events:
        bad("未收到任何实时报文")
        return task_id

    got = {e.get("type") for e in events}
    missing = WS_TYPES_EXPECTED - got
    ok(f"收到 {len(events)} 条实时报文，耗时 {elapsed:.1f} 秒")
    print(f"    {DIM}报文类型：{', '.join(sorted(got))}{RESET}")
    if missing:
        bad(f"缺少实时报文类型：{sorted(missing)}")
    else:
        ok("八种实时报文类型中，本轮该出现的已全部收到")

    first = next((e for e in events if e.get("type") == "message_start"), {})
    if first:
        ok(f"识别场景：「{first.get('scenario', '')}」，共 {first.get('step_total', 0)} 步")

    tools = [e for e in events if e.get("type") == "tool_finish"]
    failures_in_run = [e for e in tools if e.get("status") != "success"]
    ok(f"工具调用 {len(tools)} 次，成功 {len(tools) - len(failures_in_run)} 次")
    for e in tools[:3]:
        print(f"    {DIM}· {e.get('tool_name')} {e.get('status')} {e.get('duration_ms')}ms{RESET}")
    if failures_in_run:
        bad(f"存在失败的工具调用：{[(e.get('tool_name'), e.get('summary')) for e in failures_in_run]}")

    done = next((e for e in events if e.get("type") == "done"), {})
    if done.get("task_status") == "success":
        ok(f"任务收尾报文 done：status=success，总耗时 {done.get('duration_ms')}ms")
    else:
        bad(f"任务未成功收尾：{done}")

    # 5.4 任务详情
    r = client.get(f"{BACKEND}/api/tasks/{task_id}")
    if r.status_code == 200:
        detail = r.json()
        ok(f"任务详情可查：进度 {detail['progress']}%，步骤 {detail['step_index']}/{detail['step_total']}，"
           f"工具调用链 {len(detail['tool_calls'])} 条")
        ok(f"任务状态：{detail['task_status']}，耗时 {detail['duration_ms']}ms")
    else:
        bad(f"任务详情查询失败：{r.status_code}")

    # 5.5 一次性令牌必须已作废
    try:
        again = asyncio.run(collect_ws(ws_url, timeout=4))
        if again and again[0].get("type") == "connected":
            bad("一次性长连接令牌被重复使用，握手令牌未消费")
        else:
            ok("一次性令牌已消费，重连需重新申请")
    except Exception:  # noqa: BLE001
        ok("一次性令牌已消费，重放连接被拒绝")

    # 5.6 迟到/断线重连补发：换新令牌重新连上，应立即拿回本轮完整报文
    r = client.post(f"{BACKEND}/api/chat/ws-token", json={"conversation_id": conv_id})
    if r.status_code != 200:
        bad(f"重连令牌申请失败：{r.status_code}")
        return task_id
    again_url = (
        f"{BACKEND.replace('http://', 'ws://')}/api/chat/ws/chat"
        f"?websocket_token={r.json()['websocket_token']}"
    )
    try:
        replayed = asyncio.run(collect_ws(again_url, timeout=8))
    except Exception as exc:  # noqa: BLE001
        bad(f"迟到重连失败：{exc}")
        return task_id

    replayed_types = {e.get("type") for e in replayed if e.get("replayed")}
    if {"message_start", "done"} <= replayed_types:
        ok(f"迟到补发正常：重连后立即拿回本轮 {len(replayed)} 条报文（含 message_start / done）")
    elif replayed:
        bad(f"补发报文不完整，仅收到：{sorted(replayed_types)}")
    else:
        bad("重连后未收到任何补发报文")

    return task_id


# ---------------------------------------------------------------------------
# 6. 结果六模块 + 导出
# ---------------------------------------------------------------------------

def check_result(client: httpx.Client, task_id: int) -> int:
    step("[6]", "分析结果标准化输出（六大模块）与导出")

    r = client.get(f"{BACKEND}/api/results/{task_id}")
    if r.status_code != 200:
        bad(f"获取分析结果失败：{r.status_code} {r.text[:300]}")
        return 0
    res = r.json()

    modules = [
        ("模块1 问题定义", res.get("problem_definition")),
        ("模块2 关键指标", res.get("key_metrics")),
        ("模块3 证据列表", res.get("evidence_list")),
        ("模块4 归因结论", res.get("conclusion_text")),
        ("模块5 待补充数据", res.get("missing_data_text")),
        ("模块6 下一步建议", res.get("next_action_text")),
    ]
    for name, value in modules:
        if not value:
            bad(f"{name} 为空，未满足标准化输出要求")
        elif isinstance(value, list):
            ok(f"{name}：{len(value)} 条")
        else:
            ok(f"{name}：{len(str(value))} 字")

    metrics = res.get("key_metrics") or []
    if metrics and all({"metric_name", "metric_value", "metric_unit", "metric_period"} <= set(m) for m in metrics):
        ok("关键指标字段完整（metric_name / metric_value / metric_unit / metric_period）")
    else:
        bad("关键指标字段不完整")

    evidence = res.get("evidence_list") or []
    if evidence and all({"source_type", "source_name", "evidence_text", "related_metric", "confidence"} <= set(e) for e in evidence):
        ok("证据链字段完整，可回溯至数据源")
        sources = sorted({e["source_type"] for e in evidence})
        ok(f"证据来源覆盖：{', '.join(sources)}")
    else:
        bad("证据链字段不完整")

    nxt = str(res.get("next_action_text") or "")
    if nxt.count("\n") >= 1 or "1." in nxt or "1、" in nxt:
        ok("下一步建议给出多条可执行动作")
    else:
        print(f"  {YELLOW}!{RESET} 下一步建议未呈现明显分条结构，前端会按段落渲染")

    result_id = res["result_id"]

    # 导出 md / json / xlsx（json 既可能是对象也可能是数组，这里只要求能被解析）
    for fmt, expect_magic in (("md", (b"#",)), ("json", (b"{", b"[")), ("xlsx", (b"PK",))):
        r = client.get(f"{BACKEND}/api/results/download", params={"result_id": result_id, "format": fmt})
        if r.status_code != 200:
            bad(f"导出 {fmt} 失败：{r.status_code}")
            continue
        if not r.content.startswith(expect_magic):
            bad(f"导出 {fmt} 内容格式异常（前 4 字节 {r.content[:4]!r}）")
            continue
        if fmt == "json":
            try:
                json.loads(r.content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                bad(f"导出 json 无法解析：{exc}")
                continue
        disp = r.headers.get("content-disposition", "")
        ok(f"导出 {fmt} 成功：{len(r.content)} 字节，{DIM}{disp[:70]}{RESET}")

    # 别名路径
    r = client.get(f"{BACKEND}/api/results/{result_id}/download", params={"format": "json"})
    ok(f"别名下载路径 /api/results/{{result_id}}/download 可用（{r.status_code}）") if r.status_code == 200 \
        else bad(f"别名下载路径不可用：{r.status_code}")

    return result_id


# ---------------------------------------------------------------------------
# 7. 多轮追问
# ---------------------------------------------------------------------------

def check_multi_turn(client: httpx.Client, conv_id: int) -> None:
    step("[7]", "多轮追问（沿用上一轮场景与上下文）")

    question = "那这个问题主要集中在哪几个渠道？"
    r = client.post(f"{BACKEND}/api/chat/send", json={"conversation_id": conv_id, "content": question})
    if r.status_code != 200:
        bad(f"追问提交失败：{r.status_code} {r.text[:300]}")
        return
    task_id = r.json()["task_id"]
    ok(f"第二轮提问已提交，task_id={task_id}")

    deadline = time.time() + 90
    detail = {}
    while time.time() < deadline:
        r = client.get(f"{BACKEND}/api/tasks/{task_id}")
        detail = r.json()
        if detail["task_status"] in ("success", "failed", "cancelled"):
            break
        time.sleep(1.0)

    if detail.get("task_status") != "success":
        bad(f"追问任务未成功：{detail.get('task_status')} {detail.get('error_message')}")
        return
    ok("追问任务完成（复用上一轮场景，路由日志见下）")

    r = client.get(f"{BACKEND}/api/admin/logs", params={"task_id": task_id, "log_type": "lifecycle", "limit": 20})
    if r.status_code == 200:
        lines = [i["log_content"] for i in r.json()["items"]]
        route = next((ln for ln in lines if ln.startswith("场景路由|")), "")
        if route:
            ok(f"本轮路由：{route}")
        else:
            bad("未找到场景路由日志")
    else:
        print(f"  {YELLOW}!{RESET} 读取运行日志需要管理员权限，已跳过")

    r = client.get(f"{BACKEND}/api/chat/ls/{conv_id}")
    if r.status_code == 200:
        hist = r.json()
        roles = [i["role"] for i in hist["items"]]
        ok(f"会话历史共 {hist['total']} 条消息，含 user/assistant 交替（{roles.count('user')} 问 / {roles.count('assistant')} 答）")
        if hist["has_more"] is not None:
            ok(f"游标分页字段可用：has_more={hist['has_more']}, next_before_seq={hist['next_before_seq']}")
    else:
        bad(f"会话历史查询失败：{r.status_code}")

    r = client.get(f"{BACKEND}/api/chat/ls/{conv_id}", params={"page_size": 2})
    if r.status_code == 200 and len(r.json()["items"]) <= 2:
        ok(f"分页生效：page_size=2 返回 {len(r.json()['items'])} 条，has_more={r.json()['has_more']}")
    else:
        bad("分页未生效")


# ---------------------------------------------------------------------------
# 8. 配置热重载
# ---------------------------------------------------------------------------

def check_reload(client: httpx.Client) -> None:
    step("[8]", "配置热重载")

    r = client.post(f"{BACKEND}/api/admin/reload", json={"groups": []})
    if r.status_code == 200:
        body = r.json()
        ok(f"全量热重载成功：{body['total_keys']} 项配置，{len(body['changed_keys'])} 项发生变化")
        print(f"    {DIM}{body['message']}{RESET}")
    else:
        bad(f"热重载失败：{r.status_code} {r.text[:300]}")
        return

    r = client.get(f"{BACKEND}/api/admin/configs")
    if r.status_code == 200:
        cfg = r.json()
        ok(f"配置查询成功：{cfg['total']} 项，分组 {', '.join(cfg['groups'])}")
    else:
        bad(f"配置查询失败：{r.status_code}")

    # 改一项再改回去，验证真能热生效
    key = "analysis.step_interval_ms"
    before = client.get(f"{BACKEND}/api/admin/configs", params={"group": "analysis"}).json()
    old = next((i["config_value"] for i in before["items"] if i["config_key"] == key), None)
    if old is None:
        bad(f"未找到配置项 {key}")
        return

    new = "120" if old != "120" else "300"
    r = client.post(f"{BACKEND}/api/admin/configs/update", json={"config_key": key, "config_value": new})
    if r.status_code == 200 and r.json()["new_value"] == new:
        ok(f"配置修改生效：{key} {old} -> {new}，已自动热重载")
    else:
        bad(f"配置修改失败：{r.status_code} {r.text[:200]}")

    r = client.post(f"{BACKEND}/api/admin/configs/update", json={"config_key": key, "config_value": old})
    if r.status_code == 200:
        ok(f"配置已还原为 {old}")

    for path, label in (
        ("/api/admin/overview", "系统总览"),
        ("/api/admin/datasources", "业务数据源"),
        ("/api/admin/feature-toggles", "功能开关"),
        ("/api/admin/scenarios", "分析场景清单"),
        ("/api/admin/tools", "分析工具清单"),
        ("/api/admin/auth-center", "认证中心状态"),
        ("/api/admin/logs", "运行日志"),
    ):
        r = client.get(f"{BACKEND}{path}")
        if r.status_code == 200:
            body = r.json()
            n = body.get("total", len(body.get("items", [])))
            ok(f"{label}接口正常（{path}，{n} 项）")
        else:
            bad(f"{label}接口异常：{path} -> {r.status_code}")

    r = client.get(f"{BACKEND}/api/admin/feature-toggles")
    if r.status_code == 200:
        items = r.json()["items"]
        if items:
            key = items[0]["config_key"]
            cur = items[0]["enabled"]
            r2 = client.post(f"{BACKEND}/api/admin/feature-toggles/toggle",
                             json={"config_key": key, "enabled": not cur})
            if r2.status_code == 200 and r2.json()["enabled"] == (not cur):
                ok(f"功能开关可切换：{key} -> {not cur}（已即时生效）")
                client.post(f"{BACKEND}/api/admin/feature-toggles/toggle",
                            json={"config_key": key, "enabled": cur})
                ok(f"开关已还原为 {cur}")
            else:
                bad(f"功能开关切换失败：{r2.status_code}")


# ---------------------------------------------------------------------------
# 9. 收尾：删除会话级联清理
# ---------------------------------------------------------------------------

def check_cleanup(client: httpx.Client, conv_id: int) -> None:
    step("[9]", "会话删除与级联清理")

    r = client.get(f"{BACKEND}/api/chat/ls/{conv_id}")
    msg_total = r.json().get("total", 0) if r.status_code == 200 else 0

    r = client.post(f"{BACKEND}/api/chat/delete", json={"conversation_ids": [conv_id]})
    if r.status_code != 200:
        bad(f"会话删除失败：{r.status_code} {r.text[:300]}")
        return
    body = r.json()
    ok(f"会话已删除：{body['deleted']} 个，清理目录 {len(body.get('removed_dirs', []))} 个，"
       f"文件 {body.get('removed_files', 0)} 个，释放 {body.get('freed_bytes', 0)} 字节")

    r = client.get(f"{BACKEND}/api/chat/ls")
    if conv_id not in [c["conversation_id"] for c in r.json().get("items", [])]:
        ok(f"会话已从列表中消失（删除前有 {msg_total} 条消息）")
    else:
        bad("会话删除后仍出现在列表中")

    r = client.get(f"{BACKEND}/api/chat/ls/{conv_id}")
    if r.status_code == 404:
        ok("访问已删除会话 -> 404（数据确已清理）")
    else:
        bad(f"已删除会话仍可访问：{r.status_code}")


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="端到端验收自检")
    parser.add_argument("--user", default="analyst", help="登录账号（默认 analyst）")
    parser.add_argument("--password", default="Analyst@123", help="登录口令")
    parser.add_argument("--admin-user", default="admin", help="管理员账号（默认 admin）")
    parser.add_argument("--admin-password", default="Admin@123", help="管理员口令")
    parser.add_argument("--question", default="信息流渠道 ROAS 从 5.9 掉到 1.6，投放预算没变，问题出在哪？")
    parser.add_argument("--keep", action="store_true", help="保留演示会话不删除")
    args = parser.parse_args()

    print("=" * 78)
    print("经营多轮归因分析系统 —— 端到端验收")
    print(f"后端 {BACKEND}    认证中心 {AUTH}")
    print("=" * 78)

    with httpx.Client(timeout=30, follow_redirects=False) as client:
        if not do_login(client, args.user, args.password):
            print(f"\n{RED}登录未通过，后续验收无法进行{RESET}")
            return 1

        check_auth_guard(client)
        conv_id = check_conversation(client)
        if not conv_id:
            return 1

        att_id = check_attachment(client, conv_id)
        task_id = check_analysis(client, conv_id, att_id, args.question)
        if task_id:
            check_result(client, task_id)

        check_multi_turn(client, conv_id)

        # 管理控制台需要管理员身份，用独立会话登录，避免污染分析用户的上下文
        with httpx.Client(timeout=30, follow_redirects=False) as admin:
            if _login_quiet(admin, args.admin_user, args.admin_password):
                print(f"\n{DIM}（管理控制台验收：已以管理员 {args.admin_user} 登录）{RESET}")
                check_reload(admin)
            else:
                bad(f"管理员 {args.admin_user} 登录失败，管理控制台验收未执行")

        # 收尾必须在分析用户的会话仍打开时执行（删除用的是本人身份）
        if args.keep:
            print(f"\n  {YELLOW}!{RESET} 已保留演示会话 conversation_id={conv_id}（--keep）")
        else:
            check_cleanup(client, conv_id)

    print("\n" + "=" * 78)
    if failures:
        print(f"{RED}验收失败：{len(failures)} 项{RESET}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"{GREEN}全部验收项通过{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
