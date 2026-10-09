# -*- coding: utf-8 -*-
"""认证中心 OAuth2 授权码模式接口。

流程:
    1. 业务系统前端跳转 GET /oauth/authorize
    2. 未登录 -> 返回登录页；已登录 -> 302 回 redirect_uri?code=xxx&state=xxx
    3. 业务系统后端 POST /oauth/token 用 code 换取 access_token / refresh_token
    4. 业务系统后端 POST /oauth/introspect 校验令牌（也可用 GET /oauth/userinfo）
    5. 登出 POST /oauth/logout，吊销该会话下全部令牌
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import (
    gen_code,
    gen_session_id,
    gen_token,
    is_expired,
    now,
    seconds_later,
    verify_password,
)
from app.models import AuthClient, AuthCode, AuthLoginLog, AuthSession, AuthToken, AuthUser
from app.schemas import IntrospectResponse, OkResponse, SessionItem, TokenResponse, UserInfoResponse

router = APIRouter(prefix="/oauth", tags=["认证中心 OAuth2"])

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
templates = Environment(
    loader=FileSystemLoader(str(STATIC_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

SESSION_COOKIE = "auth_sid"


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def write_log(
    db: Session,
    *,
    username: str | None,
    action: str,
    request: Request,
    success: bool,
    message: str = "",
) -> None:
    db.add(
        AuthLoginLog(
            username=username,
            action=action,
            ip=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:500],
            success=1 if success else 0,
            message=message[:500],
        )
    )


def error_page(title: str, detail: str, code: int = 400) -> HTMLResponse:
    return HTMLResponse(
        content=f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{title}</title>
<style>
 body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#0f1523;color:#e6edf7;
      display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
 .box{{background:#182236;border:1px solid #26334d;border-radius:12px;padding:36px 40px;max-width:520px;
      box-shadow:0 16px 48px rgba(0,0,0,.45)}}
 h1{{font-size:18px;margin:0 0 12px}} p{{color:#93a4bf;line-height:1.7;margin:0 0 18px}}
 code{{background:#0b1220;padding:2px 6px;border-radius:4px;color:#7cc4ff}}
 a{{color:#4da3ff;text-decoration:none}}
</style></head><body><div class="box">
<h1>授权失败：{title}</h1><p>{detail}</p>
<p><code>认证中心 {settings.app_version}</code></p>
</div></body></html>""",
        status_code=code,
    )


def pick_redirect(request: Request) -> RedirectResponse:
    """把上游传递的参数原样保留到登录表单里。"""
    return RedirectResponse(url="/oauth/authorize?" + urlencode(dict(request.query_params)), status_code=302)


def issue_code(db: Session, client_id: str, user_id: int, redirect_uri: str, scope: str) -> str:
    code = gen_code()
    db.add(
        AuthCode(
            code=code,
            client_id=client_id,
            user_id=user_id,
            redirect_uri=redirect_uri,
            scope=scope,
            expires_at=seconds_later(settings.auth_code_ttl_sec),
        )
    )
    return code


def get_session_user(db: Session, request: Request) -> tuple[AuthSession, AuthUser] | None:
    """读取 Cookie 中的登录会话，返回 (session, user) 或 None。"""
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    sess = db.execute(select(AuthSession).where(AuthSession.session_id == sid)).scalar_one_or_none()
    if not sess or sess.status != "active" or is_expired(sess.expires_at):
        return None
    user = db.execute(select(AuthUser).where(AuthUser.id == sess.user_id)).scalar_one_or_none()
    if not user or user.status != "active":
        return None
    return sess, user


def resolve_token(db: Session, raw_token: str) -> tuple[AuthToken, AuthUser] | None:
    tok = db.execute(select(AuthToken).where(AuthToken.access_token == raw_token)).scalar_one_or_none()
    if not tok or tok.revoked_at is not None or is_expired(tok.expires_at):
        return None
    user = db.execute(select(AuthUser).where(AuthUser.id == tok.user_id)).scalar_one_or_none()
    if not user or user.status != "active":
        return None
    return tok, user


# ---------------------------------------------------------------------------
# 1. 授权入口
# ---------------------------------------------------------------------------

@router.get("/authorize", summary="授权入口：跳转登录页或直接下发授权码")
def authorize(
    request: Request,
    response_type: str = Query("code", description="固定为 code"),
    client_id: str = Query(..., description="客户端ID"),
    redirect_uri: str = Query(..., description="回调地址"),
    scope: str = Query("openid profile", description="授权范围"),
    state: str = Query("", description="防 CSRF 随机串，原样回传"),
    db: Session = Depends(get_db),
):
    client = db.execute(select(AuthClient).where(AuthClient.client_id == client_id)).scalar_one_or_none()
    if not client or client.status != "active":
        write_log(db, username=None, action="authorize", request=request, success=False, message="客户端不存在或已停用")
        db.commit()
        return error_page("客户端无效", f"未找到启用状态的客户端 <code>{client_id}</code>。", 401)

    if not client.allows_redirect(redirect_uri):
        # 回调地址非法时绝不重定向，防止开放重定向漏洞
        write_log(db, username=None, action="authorize", request=request, success=False,
                  message=f"回调地址未注册: {redirect_uri}")
        db.commit()
        return error_page(
            "回调地址未注册",
            f"<code>{redirect_uri}</code> 不在客户端 <code>{client_id}</code> 的注册回调列表中。<br>"
            f"已注册：<code>{client.redirect_uris}</code>",
            400,
        )

    if response_type != "code":
        return error_page("不支持的授权类型", "本认证中心仅支持 <code>response_type=code</code>（授权码模式）。", 400)

    # 已有登录态 -> 直接下发授权码
    signed = get_session_user(db, request)
    if signed:
        _sess, user = signed
        code = issue_code(db, client_id, user.id, redirect_uri, scope)
        write_log(db, username=user.username, action="authorize", request=request, success=True,
                  message="已登录，直接签发授权码")
        db.commit()
        sep = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(url=f"{redirect_uri}{sep}{urlencode({'code': code, 'state': state})}", status_code=302)

    # 未登录 -> 渲染登录页
    tpl = templates.get_template("login.html")
    html = tpl.render(
        client_name=client.client_name,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        state=state,
        app_version=settings.app_version,
        auth_url=str(request.url),
        demo_accounts=[
            {"username": "analyst", "password": "Analyst@123", "role": "分析用户"},
            {"username": "zhangyun", "password": "Zhang@123", "role": "分析用户"},
            {"username": "admin", "password": "Admin@123", "role": "系统管理员"},
        ],
        error="",
    )
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# 2. 登录并签发授权码
# ---------------------------------------------------------------------------

@router.post("/login", summary="提交账号口令，建立登录会话并回跳带回授权码")
def login(
    request: Request,
    username: str = Form(..., description="登录账号"),
    password: str = Form(..., description="登录口令"),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    scope: str = Form("openid profile"),
    state: str = Form(""),
    db: Session = Depends(get_db),
):
    client = db.execute(select(AuthClient).where(AuthClient.client_id == client_id)).scalar_one_or_none()
    if not client or client.status != "active":
        return error_page("客户端无效", f"未找到启用状态的客户端 <code>{client_id}</code>。", 401)
    if not client.allows_redirect(redirect_uri):
        return error_page("回调地址未注册", f"<code>{redirect_uri}</code> 未注册。", 400)

    user = db.execute(select(AuthUser).where(AuthUser.username == username)).scalar_one_or_none()

    def reject(msg: str) -> HTMLResponse:
        write_log(db, username=username, action="login", request=request, success=False, message=msg)
        db.commit()
        tpl = templates.get_template("login.html")
        return HTMLResponse(
            content=tpl.render(
                client_name=client.client_name,
                client_id=client_id,
                redirect_uri=redirect_uri,
                scope=scope,
                state=state,
                app_version=settings.app_version,
                auth_url=str(request.url),
                demo_accounts=[
                    {"username": "analyst", "password": "Analyst@123", "role": "分析用户"},
                    {"username": "zhangyun", "password": "Zhang@123", "role": "分析用户"},
                    {"username": "admin", "password": "Admin@123", "role": "系统管理员"},
                ],
                error=msg,
            ),
            status_code=401,
        )

    if not user:
        return reject("账号或口令不正确")
    if user.status != "active":
        return reject(f"账号状态为 {user.status}，无法登录")
    if not verify_password(password, user.salt, user.password_hash):
        return reject("账号或口令不正确")

    # 建立登录会话
    session_id = gen_session_id()
    db.add(
        AuthSession(
            session_id=session_id,
            user_id=user.id,
            client_id=client_id,
            ip=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:500],
            status="active",
            expires_at=seconds_later(settings.session_ttl_sec),
        )
    )
    user.last_login_at = now()

    code = issue_code(db, client_id, user.id, redirect_uri, scope)
    write_log(db, username=user.username, action="login", request=request, success=True,
              message=f"登录成功，会话 {session_id}")
    db.commit()

    sep = "&" if "?" in redirect_uri else "?"
    resp = RedirectResponse(url=f"{redirect_uri}{sep}{urlencode({'code': code, 'state': state})}", status_code=302)
    resp.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=settings.session_ttl_sec,
        httponly=True,
        samesite="lax",
    )
    return resp


# ---------------------------------------------------------------------------
# 3. 令牌换取
# ---------------------------------------------------------------------------

def _issue_token_pair(db: Session, client: AuthClient, user: AuthUser, session_id: str, scope: str) -> TokenResponse:
    access = gen_token("at_")
    refresh = gen_token("rt_")
    db.add(
        AuthToken(
            access_token=access,
            refresh_token=refresh,
            client_id=client.client_id,
            user_id=user.id,
            session_id=session_id,
            scope=scope,
            expires_at=seconds_later(settings.access_token_ttl_sec),
            refresh_expires_at=seconds_later(settings.refresh_token_ttl_sec),
        )
    )
    return TokenResponse(
        access_token=access,
        expires_in=settings.access_token_ttl_sec,
        refresh_token=refresh,
        scope=scope,
        session_id=session_id,
    )


@router.post("/token", summary="用授权码或刷新令牌换取访问令牌")
def token(
    request: Request,
    grant_type: str = Form(..., description="authorization_code 或 refresh_token"),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    refresh_token: str | None = Form(None),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
    db: Session = Depends(get_db),
):
    # 兼容 HTTP Basic 客户端认证
    if not client_id or not client_secret:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("basic "):
            import base64

            try:
                raw = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
                client_id, client_secret = raw.split(":", 1)
            except Exception:  # noqa: BLE001
                pass

    client = db.execute(select(AuthClient).where(AuthClient.client_id == client_id)).scalar_one_or_none()
    if not client or client.status != "active" or client.client_secret != client_secret:
        write_log(db, username=None, action="token", request=request, success=False, message="客户端认证失败")
        db.commit()
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_client", "error_description": "客户端认证失败"},
        )

    if grant_type == "authorization_code":
        if not code:
            return JSONResponse(status_code=400, content={"error": "invalid_request", "error_description": "缺少 code"})
        row = db.execute(select(AuthCode).where(AuthCode.code == code)).scalar_one_or_none()
        if not row:
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "授权码不存在"})
        if row.consumed_at is not None:
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "授权码已被使用"})
        if is_expired(row.expires_at):
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "授权码已过期"})
        if row.client_id != client.client_id:
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "授权码与客户端不匹配"})
        if redirect_uri and row.redirect_uri.rstrip("/") != redirect_uri.rstrip("/"):
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "回调地址不一致"})

        user = db.execute(select(AuthUser).where(AuthUser.id == row.user_id)).scalar_one_or_none()
        if not user or user.status != "active":
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "用户不可用"})

        row.consumed_at = now()

        # 复用该用户在此客户端下最近的活跃会话
        sess = db.execute(
            select(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.status == "active")
            .order_by(AuthSession.id.desc())
        ).scalars().first()
        session_id = sess.session_id if sess and not is_expired(sess.expires_at) else gen_session_id()
        if not (sess and not is_expired(sess.expires_at)):
            db.add(
                AuthSession(
                    session_id=session_id,
                    user_id=user.id,
                    client_id=client.client_id,
                    ip=client_ip(request),
                    user_agent=(request.headers.get("user-agent") or "")[:500],
                    status="active",
                    expires_at=seconds_later(settings.session_ttl_sec),
                )
            )

        result = _issue_token_pair(db, client, user, session_id, row.scope)
        write_log(db, username=user.username, action="token", request=request, success=True, message="授权码换取令牌成功")
        db.commit()
        return result

    if grant_type == "refresh_token":
        if not refresh_token:
            return JSONResponse(status_code=400, content={"error": "invalid_request", "error_description": "缺少 refresh_token"})
        old = db.execute(select(AuthToken).where(AuthToken.refresh_token == refresh_token)).scalar_one_or_none()
        if not old or old.revoked_at is not None or is_expired(old.refresh_expires_at):
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "刷新令牌无效或已过期"})
        user = db.execute(select(AuthUser).where(AuthUser.id == old.user_id)).scalar_one_or_none()
        if not user or user.status != "active":
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "用户不可用"})
        old.revoked_at = now()
        result = _issue_token_pair(db, client, user, old.session_id, old.scope)
        write_log(db, username=user.username, action="refresh", request=request, success=True, message="刷新令牌成功")
        db.commit()
        return result

    return JSONResponse(
        status_code=400,
        content={"error": "unsupported_grant_type", "error_description": f"不支持的 grant_type: {grant_type}"},
    )


# ---------------------------------------------------------------------------
# 4. 令牌校验 / 用户信息
# ---------------------------------------------------------------------------

def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少 Authorization 头")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authorization 头格式应为 Bearer <token>")
    return parts[1].strip()


@router.get("/userinfo", response_model=UserInfoResponse, summary="获取当前令牌对应的用户信息")
def userinfo(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
):
    raw = _bearer(authorization)
    found = resolve_token(db, raw)
    if not found:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    tok, user = found
    return UserInfoResponse(
        sub=str(user.id),
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        email=user.email,
        scope=tok.scope,
    )


@router.post("/introspect", response_model=IntrospectResponse, summary="令牌内省（业务系统后端调用）")
def introspect(
    token: str = Form(..., description="待校验的访问令牌"),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
    db: Session = Depends(get_db),
):
    if client_id and client_secret:
        client = db.execute(select(AuthClient).where(AuthClient.client_id == client_id)).scalar_one_or_none()
        if not client or client.client_secret != client_secret:
            return IntrospectResponse(active=False)

    found = resolve_token(db, token)
    if not found:
        return IntrospectResponse(active=False)
    tok, user = found
    return IntrospectResponse(
        active=True,
        sub=str(user.id),
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        email=user.email,
        scope=tok.scope,
        client_id=tok.client_id,
        session_id=tok.session_id,
        exp=int(tok.expires_at.timestamp()),
        iat=int(tok.created_at.timestamp()) if tok.created_at else None,
    )


# ---------------------------------------------------------------------------
# 5. 令牌吊销 / 登出
# ---------------------------------------------------------------------------

@router.post("/revoke", response_model=OkResponse, summary="吊销单个访问令牌")
def revoke(
    request: Request,
    token: str = Form(...),
    db: Session = Depends(get_db),
):
    tok = db.execute(select(AuthToken).where(AuthToken.access_token == token)).scalar_one_or_none()
    if tok and tok.revoked_at is None:
        tok.revoked_at = now()
        write_log(db, username=None, action="revoke", request=request, success=True, message="令牌已吊销")
        db.commit()
    return OkResponse(status="ok", message="令牌已吊销")


@router.post("/logout", response_model=OkResponse, summary="登出：吊销会话及其下全部令牌")
def logout(
    request: Request,
    session_id: str | None = Form(None),
    db: Session = Depends(get_db),
):
    sid = session_id
    if not sid:
        signed = get_session_user(db, request)
        if signed:
            sid = signed[0].session_id
    if not sid:
        auth = request.headers.get("authorization")
        if auth:
            try:
                tok = db.execute(
                    select(AuthToken).where(AuthToken.access_token == _bearer(auth))
                ).scalar_one_or_none()
                if tok:
                    sid = tok.session_id
            except HTTPException:
                pass

    if not sid:
        return OkResponse(status="ok", message="无可登出的会话")

    sess = db.execute(select(AuthSession).where(AuthSession.session_id == sid)).scalar_one_or_none()
    username = None
    if sess:
        sess.status = "logout"
        sess.logout_at = now()
        u = db.execute(select(AuthUser).where(AuthUser.id == sess.user_id)).scalar_one_or_none()
        username = u.username if u else None

    tokens = db.execute(select(AuthToken).where(AuthToken.session_id == sid)).scalars().all()
    for t in tokens:
        if t.revoked_at is None:
            t.revoked_at = now()

    write_log(db, username=username, action="logout", request=request, success=True,
              message=f"会话 {sid} 已登出，吊销令牌 {len(tokens)} 个")
    db.commit()

    resp = JSONResponse(content={"status": "ok", "message": f"已登出，吊销令牌 {len(tokens)} 个"})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ---------------------------------------------------------------------------
# 6. 会话查询（用户会话全生命周期管理）
# ---------------------------------------------------------------------------

@router.get("/sessions", response_model=list[SessionItem], summary="查询登录会话列表")
def list_sessions(
    username: str | None = Query(None, description="按账号过滤"),
    status_filter: str | None = Query(None, alias="status", description="按状态过滤 active/logout/expired/kicked"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(AuthSession).order_by(AuthSession.id.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(AuthSession.status == status_filter)
    rows = db.execute(stmt).scalars().all()

    users = {u.id: u for u in db.execute(select(AuthUser)).scalars().all()}
    items: list[SessionItem] = []
    for s in rows:
        u = users.get(s.user_id)
        if username and (not u or u.username != username):
            continue
        items.append(
            SessionItem(
                session_id=s.session_id,
                user_id=s.user_id,
                username=u.username if u else None,
                display_name=u.display_name if u else None,
                client_id=s.client_id,
                ip=s.ip,
                user_agent=s.user_agent,
                status=s.status,
                expires_at=s.expires_at.isoformat() if s.expires_at else None,
                logout_at=s.logout_at.isoformat() if s.logout_at else None,
                created_at=s.created_at.isoformat() if s.created_at else None,
            )
        )
    return items


@router.get("/healthz", summary="认证中心健康检查")
def healthz(db: Session = Depends(get_db)):
    db.execute(select(AuthUser.id).limit(1))
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "database": settings.db_name,
        "time": datetime.now().isoformat(timespec="seconds"),
    }
