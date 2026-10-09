# -*- coding: utf-8 -*-
"""认证接口：跳转认证中心、处理回调、查询登录态、登出。"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user, get_token_info
from app.core.security import AuthCenterError, TokenInfo, auth_client
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

STATE_COOKIE = "jy_oauth_state"
STATE_TTL_SEC = 600


@router.get("/auth/login", summary="跳转认证中心发起授权登录")
def login(request: Request) -> RedirectResponse:
    """生成 state 并 302 到认证中心的授权页。"""
    state = secrets.token_urlsafe(24)
    url = auth_client.build_authorize_url(state)

    resp = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    resp.set_cookie(
        STATE_COOKIE,
        state,
        max_age=STATE_TTL_SEC,
        httponly=True,
        samesite="lax",
        path="/",
    )
    logger.info("发起授权登录，跳转认证中心：%s", url)
    return resp


@router.get("/auth/callback", summary="处理授权回调，换取令牌并建立登录态")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """接收授权码，换取访问令牌，写入 HttpOnly Cookie，然后跳回前端。"""
    frontend = settings.frontend_base_url.rstrip("/")

    if error:
        logger.warning("认证中心返回错误：%s", error)
        return RedirectResponse(f"{frontend}/login?error={error}", status_code=status.HTTP_302_FOUND)

    if not code:
        return RedirectResponse(f"{frontend}/login?error=missing_code", status_code=status.HTTP_302_FOUND)

    expected_state = request.cookies.get(STATE_COOKIE)
    if not expected_state or not state or not secrets.compare_digest(expected_state, state):
        logger.warning("授权 state 校验失败（可能为 CSRF 或 Cookie 丢失）")
        return RedirectResponse(f"{frontend}/login?error=state_mismatch", status_code=status.HTTP_302_FOUND)

    try:
        payload = auth_client.exchange_code(code)
    except AuthCenterError as exc:
        logger.error("换取令牌失败：%s", exc)
        return RedirectResponse(f"{frontend}/login?error=token_exchange_failed", status_code=status.HTTP_302_FOUND)

    access_token = payload.get("access_token")
    if not access_token:
        logger.error("认证中心未返回 access_token：%s", payload)
        return RedirectResponse(f"{frontend}/login?error=no_access_token", status_code=status.HTTP_302_FOUND)

    expires_in = int(payload.get("expires_in") or settings.auth_token_ttl_hint)

    resp = RedirectResponse(f"{frontend}/", status_code=status.HTTP_302_FOUND)
    resp.set_cookie(
        settings.cookie_name,
        access_token,
        max_age=expires_in,
        httponly=True,
        samesite="lax",
        path="/",
        secure=settings.cookie_secure,
    )
    if payload.get("refresh_token"):
        resp.set_cookie(
            settings.refresh_cookie_name,
            payload["refresh_token"],
            max_age=int(payload.get("refresh_expires_in") or 604800),
            httponly=True,
            samesite="lax",
            path="/",
            secure=settings.cookie_secure,
        )
    resp.delete_cookie(STATE_COOKIE, path="/")
    logger.info("登录成功，已写入访问令牌 Cookie（有效期 %s 秒）", expires_in)
    return resp


@router.get("/api/auth/me", summary="获取当前登录用户")
def me(
    request: Request,
    user: User = Depends(get_current_user),
    info: TokenInfo = Depends(get_token_info),
) -> dict:
    remaining = 0
    if info.exp:
        remaining = max(0, int(info.exp - datetime.now().timestamp()))
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "status": user.status,
        "avatar_text": user.avatar_text,
        "token_expires_in": remaining,
        "session_id": info.session_id,
    }


@router.post("/api/auth/logout", summary="登出")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(settings.cookie_name)
    if not token:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()

    if token:
        auth_client.logout(token)  # 失败不阻断本地登出

    response.delete_cookie(settings.cookie_name, path="/")
    response.delete_cookie(settings.refresh_cookie_name, path="/")
    logger.info("用户已登出")
    return {"status": "ok", "message": "已成功登出"}
