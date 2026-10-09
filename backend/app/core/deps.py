# -*- coding: utf-8 -*-
"""FastAPI 依赖：登录态解析、当前用户识别、权限管控。"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import AuthCenterError, TokenInfo, auth_client
from app.models import User

logger = logging.getLogger(__name__)


def extract_token(request: Request) -> str | None:
    """从 Cookie 或 Authorization 头中取出访问令牌。

    优先 Cookie（浏览器场景），其次 Bearer 头（curl / Postman 调试场景）。
    """
    token = request.cookies.get(settings.cookie_name)
    if token:
        return token
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def upsert_user_from_token(db: Session, info: TokenInfo) -> User:
    """把认证中心用户同步为业务库 users 记录（首次登录自动注册）。"""
    external_id = str(info.sub)
    user = db.execute(select(User).where(User.external_user_id == external_id)).scalar_one_or_none()

    if user is None:
        user = User(
            external_user_id=external_id,
            username=info.username or f"user_{external_id}",
            display_name=info.display_name or info.username or f"用户{external_id}",
            role=info.role or "analyst",
            status="active",
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # 并发首登时另一个请求已插入，回滚后重新查询
            db.rollback()
            user = db.execute(select(User).where(User.external_user_id == external_id)).scalar_one()
        else:
            db.refresh(user)
            logger.info("已同步认证中心用户到业务库: %s (external_user_id=%s)", user.username, external_id)
    else:
        changed = False
        for attr, value in (
            ("username", info.username),
            ("display_name", info.display_name),
            ("role", info.role),
        ):
            if value and getattr(user, attr) != value:
                setattr(user, attr, value)
                changed = True
        if changed:
            db.commit()

    return user


def get_token_info(request: Request) -> TokenInfo:
    """校验令牌并返回内省结果。"""
    token = extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录：请求未携带访问令牌",
        )
    try:
        info = auth_client.introspect(token)
    except AuthCenterError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"认证中心不可用，无法校验登录态：{exc}",
        ) from exc

    if not info.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录态已失效，请重新登录",
        )
    request.state.token_info = info
    request.state.access_token = token
    return info


def get_current_user(
    request: Request,
    info: TokenInfo = Depends(get_token_info),
    db: Session = Depends(get_db),
) -> User:
    """当前登录用户（业务库记录）。"""
    user = upsert_user_from_token(db, info)
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"账号状态为 {user.status}，已被禁止访问",
        )
    request.state.user = user
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """要求系统管理员角色。"""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该操作仅系统管理员可执行",
        )
    return user
