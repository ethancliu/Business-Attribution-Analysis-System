# -*- coding: utf-8 -*-
"""认证中心自管理接口（供系统管理员维护认证中心配置时调用）。

统一使用请求头 `X-Admin-Key` 鉴权，密钥见 settings.admin_api_key。
业务系统后端的「认证配置」页面通过代理调用这些接口。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import gen_salt, hash_password, now
from app.models import AuthClient, AuthCode, AuthLoginLog, AuthSession, AuthToken, AuthUser
from app.schemas import OkResponse

router = APIRouter(prefix="/admin", tags=["认证中心管理"])


def require_admin(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")) -> None:
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="X-Admin-Key 无效")


def _dt(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


@router.get("/overview", summary="认证中心总览统计", dependencies=[Depends(require_admin)])
def overview(db: Session = Depends(get_db)):
    def count(model, *where):
        stmt = select(func.count()).select_from(model)
        if where:
            stmt = stmt.where(*where)
        return db.execute(stmt).scalar_one()

    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "database": settings.db_name,
        "token_policy": {
            "auth_code_ttl_sec": settings.auth_code_ttl_sec,
            "access_token_ttl_sec": settings.access_token_ttl_sec,
            "refresh_token_ttl_sec": settings.refresh_token_ttl_sec,
            "session_ttl_sec": settings.session_ttl_sec,
        },
        "counters": {
            "clients": count(AuthClient),
            "users": count(AuthUser),
            "active_users": count(AuthUser, AuthUser.status == "active"),
            "sessions_active": count(AuthSession, AuthSession.status == "active"),
            "tokens_issued": count(AuthToken),
            "tokens_alive": count(AuthToken, AuthToken.revoked_at.is_(None), AuthToken.expires_at > now()),
            "codes_issued": count(AuthCode),
            "login_logs": count(AuthLoginLog),
        },
    }


@router.get("/clients", summary="认证中心客户端列表", dependencies=[Depends(require_admin)])
def clients(db: Session = Depends(get_db)):
    rows = db.execute(select(AuthClient).order_by(AuthClient.id)).scalars().all()
    return [
        {
            "client_id": c.client_id,
            "client_name": c.client_name,
            "redirect_uris": c.redirect_uri_list(),
            "scope": c.scope,
            "status": c.status,
            "created_at": _dt(c.created_at),
            "updated_at": _dt(c.updated_at),
        }
        for c in rows
    ]


@router.post("/clients/{client_id}/toggle", response_model=OkResponse,
             summary="启停认证中心客户端", dependencies=[Depends(require_admin)])
def toggle_client(client_id: str, db: Session = Depends(get_db)):
    c = db.execute(select(AuthClient).where(AuthClient.client_id == client_id)).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="客户端不存在")
    c.status = "disabled" if c.status == "active" else "active"
    db.commit()
    return OkResponse(message=f"客户端 {client_id} 状态已切换为 {c.status}")


@router.get("/users", summary="认证中心用户列表", dependencies=[Depends(require_admin)])
def users(db: Session = Depends(get_db)):
    rows = db.execute(select(AuthUser).order_by(AuthUser.id)).scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "email": u.email,
            "role": u.role,
            "status": u.status,
            "last_login_at": _dt(u.last_login_at),
            "created_at": _dt(u.created_at),
        }
        for u in rows
    ]


@router.post("/users/{username}/reset-password", response_model=OkResponse,
             summary="重置用户口令", dependencies=[Depends(require_admin)])
def reset_password(username: str, new_password: str = Query(..., min_length=6), db: Session = Depends(get_db)):
    u = db.execute(select(AuthUser).where(AuthUser.username == username)).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    u.salt = gen_salt()
    u.password_hash = hash_password(new_password, u.salt)
    db.commit()
    return OkResponse(message=f"用户 {username} 口令已重置")


@router.post("/users/{username}/toggle", response_model=OkResponse,
             summary="启用/停用用户", dependencies=[Depends(require_admin)])
def toggle_user(username: str, db: Session = Depends(get_db)):
    u = db.execute(select(AuthUser).where(AuthUser.username == username)).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    u.status = "disabled" if u.status == "active" else "active"
    db.commit()
    return OkResponse(message=f"用户 {username} 状态已切换为 {u.status}")


@router.post("/sessions/{session_id}/kick", response_model=OkResponse,
             summary="强制下线指定会话", dependencies=[Depends(require_admin)])
def kick_session(session_id: str, db: Session = Depends(get_db)):
    sess = db.execute(select(AuthSession).where(AuthSession.session_id == session_id)).scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    sess.status = "kicked"
    sess.logout_at = now()
    tokens = db.execute(select(AuthToken).where(AuthToken.session_id == session_id)).scalars().all()
    for t in tokens:
        if t.revoked_at is None:
            t.revoked_at = now()
    db.commit()
    return OkResponse(message=f"会话 {session_id} 已强制下线，吊销令牌 {len(tokens)} 个")


@router.get("/logs", summary="认证操作日志查询", dependencies=[Depends(require_admin)])
def logs(
    username: str | None = Query(None),
    action: str | None = Query(None),
    success: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    stmt = select(AuthLoginLog).order_by(AuthLoginLog.id.desc()).limit(limit)
    if username:
        stmt = stmt.where(AuthLoginLog.username == username)
    if action:
        stmt = stmt.where(AuthLoginLog.action == action)
    if success is not None:
        stmt = stmt.where(AuthLoginLog.success == (1 if success else 0))
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": r.id,
            "username": r.username,
            "action": r.action,
            "ip": r.ip,
            "success": bool(r.success),
            "message": r.message,
            "created_at": _dt(r.created_at),
        }
        for r in rows
    ]


@router.post("/cleanup", response_model=OkResponse, summary="清理过期授权码与令牌",
             dependencies=[Depends(require_admin)])
def cleanup(db: Session = Depends(get_db)):
    from sqlalchemy import delete

    now_ts = now()
    codes = db.execute(delete(AuthCode).where(AuthCode.expires_at < now_ts)).rowcount
    tokens = db.execute(
        delete(AuthToken).where(AuthToken.expires_at < now_ts, AuthToken.revoked_at.is_not(None))
    ).rowcount
    sessions = db.execute(
        delete(AuthSession).where(AuthSession.expires_at < now_ts, AuthSession.status != "active")
    ).rowcount
    db.commit()
    return OkResponse(
        message=f"清理完成：授权码 {codes} 条、令牌 {tokens} 条、会话 {sessions} 条"
    )
