# -*- coding: utf-8 -*-
"""认证中心对接客户端 + 令牌内省缓存。

设计:
    - 访问令牌为 opaque token，无法本地校验，必须调用认证中心 /oauth/introspect；
    - 为避免每个请求都打一次认证中心，内省结果按令牌做 TTL 缓存（默认 60 秒，
      由配置 auth.introspect_cache_sec 控制）；
    - 登出时主动清除该令牌的缓存，保证即时失效。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class TokenInfo:
    """内省结果。"""

    active: bool
    sub: str | None = None
    username: str | None = None
    display_name: str | None = None
    role: str | None = None
    email: str | None = None
    scope: str | None = None
    client_id: str | None = None
    session_id: str | None = None
    exp: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class TokenCache:
    """带 TTL 的令牌内省缓存（线程安全）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: dict[str, tuple[float, TokenInfo]] = {}

    def get(self, token: str) -> TokenInfo | None:
        with self._lock:
            hit = self._store.get(token)
        if not hit:
            return None
        expire_at, info = hit
        if time.time() > expire_at:
            with self._lock:
                self._store.pop(token, None)
            return None
        return info

    def put(self, token: str, info: TokenInfo, ttl_sec: int) -> None:
        with self._lock:
            self._store[token] = (time.time() + max(1, ttl_sec), info)
            # 顺带清理已过期条目，避免长跑内存增长
            if len(self._store) > 512:
                now = time.time()
                for k in [k for k, (exp, _) in self._store.items() if exp < now]:
                    self._store.pop(k, None)

    def drop(self, token: str) -> None:
        with self._lock:
            self._store.pop(token, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._store)


token_cache = TokenCache()


class AuthCenterError(RuntimeError):
    """认证中心调用失败。"""


class AuthCenterClient:
    """认证中心 HTTP 客户端（OAuth2 授权码模式）。"""

    def __init__(self) -> None:
        self._timeout = httpx.Timeout(settings.auth_http_timeout_sec)

    # ------------------------------------------------------------ 授权
    def build_authorize_url(self, state: str, scope: str | None = None) -> str:
        params = {
            "response_type": "code",
            "client_id": settings.auth_client_id,
            "redirect_uri": settings.auth_redirect_uri,
            "scope": scope or settings.auth_scope,
            "state": state,
        }
        return str(httpx.URL(settings.auth_authorize_url, params=params))

    # ------------------------------------------------------------ 令牌
    def exchange_code(self, code: str) -> dict[str, Any]:
        """用授权码换取访问令牌。"""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.auth_redirect_uri,
            "client_id": settings.auth_client_id,
            "client_secret": settings.auth_client_secret,
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(settings.auth_token_url, data=data)
        except httpx.HTTPError as exc:
            raise AuthCenterError(f"无法连接认证中心令牌接口: {exc}") from exc

        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("error_description") or body.get("detail") or str(body)
            except Exception:  # noqa: BLE001
                detail = resp.text[:300]
            raise AuthCenterError(f"换取令牌失败（{resp.status_code}）：{detail}")
        return resp.json()

    def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.auth_client_id,
            "client_secret": settings.auth_client_secret,
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(settings.auth_token_url, data=data)
        except httpx.HTTPError as exc:
            raise AuthCenterError(f"无法连接认证中心令牌接口: {exc}") from exc
        if resp.status_code >= 400:
            raise AuthCenterError(f"刷新令牌失败（{resp.status_code}）")
        return resp.json()

    # ------------------------------------------------------------ 校验
    def introspect(self, token: str, use_cache: bool = True) -> TokenInfo:
        """令牌内省。带 TTL 缓存；认证中心不可用时，若缓存中有未过期结果则继续沿用。"""
        ttl = settings.auth_introspect_cache_sec
        if use_cache:
            cached = token_cache.get(token)
            if cached is not None:
                return cached

        data = {
            "token": token,
            "client_id": settings.auth_client_id,
            "client_secret": settings.auth_client_secret,
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(settings.auth_introspect_url, data=data)
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("令牌内省请求失败: %s", exc)
            raise AuthCenterError(f"认证中心不可用: {exc}") from exc
        except ValueError as exc:
            raise AuthCenterError(f"认证中心返回内容无法解析: {exc}") from exc

        info = TokenInfo(
            active=bool(body.get("active")),
            sub=body.get("sub"),
            username=body.get("username"),
            display_name=body.get("display_name"),
            role=body.get("role"),
            email=body.get("email"),
            scope=body.get("scope"),
            client_id=body.get("client_id"),
            session_id=body.get("session_id"),
            exp=body.get("exp"),
            raw=body,
        )
        if use_cache:
            token_cache.put(token, info, ttl)
        return info

    # ------------------------------------------------------------ 登出
    def logout(self, token: str) -> None:
        """吊销令牌。失败不抛出，避免阻断本地登出。"""
        token_cache.drop(token)
        try:
            with httpx.Client(timeout=self._timeout) as client:
                client.post(settings.auth_logout_url, data={"session_id": ""}, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            logger.warning("调用认证中心登出失败（本地登录态已清除）: %s", exc)

    # ------------------------------------------------------------ 管理
    def admin_call(self, path: str, method: str = "GET", **kwargs) -> Any:
        """调用认证中心自管理接口，需 X-Admin-Key。"""
        url = f"{settings.auth_admin_url}/{path.lstrip('/')}"
        headers = {"X-Admin-Key": "jingying-auth-admin-2026"}
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.request(method, url, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise AuthCenterError(f"认证中心管理接口调用失败: {exc}") from exc

    def health(self) -> tuple[bool, str]:
        url = f"{settings.auth_base_url.rstrip('/')}/oauth/healthz"
        try:
            with httpx.Client(timeout=httpx.Timeout(3.0)) as client:
                resp = client.get(url)
            if resp.status_code == 200:
                body = resp.json()
                return True, f"{body.get('service')} v{body.get('version')}"
            return False, f"HTTP {resp.status_code}"
        except httpx.HTTPError as exc:
            return False, str(exc)


auth_client = AuthCenterClient()
