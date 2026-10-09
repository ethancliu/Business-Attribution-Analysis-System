# -*- coding: utf-8 -*-
"""认证中心请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    """POST /oauth/token 成功响应（OAuth2 标准字段）。"""

    access_token: str = Field(description="访问令牌")
    token_type: str = Field(default="Bearer", description="令牌类型")
    expires_in: int = Field(description="访问令牌剩余有效秒数")
    refresh_token: str | None = Field(default=None, description="刷新令牌")
    scope: str = Field(description="授权范围")
    session_id: str = Field(description="登录会话ID")


class IntrospectResponse(BaseModel):
    """POST /oauth/introspect 响应。

    active=false 时其余字段全部缺省；active=true 时返回业务系统所需的身份信息。
    """

    active: bool = Field(description="令牌是否有效")
    sub: str | None = Field(default=None, description="用户唯一标识（auth_users.id）")
    username: str | None = None
    display_name: str | None = None
    role: str | None = None
    email: str | None = None
    scope: str | None = None
    client_id: str | None = None
    session_id: str | None = None
    exp: int | None = Field(default=None, description="过期时间戳（秒）")
    iat: int | None = Field(default=None, description="签发时间戳（秒）")


class UserInfoResponse(BaseModel):
    """GET /oauth/userinfo 响应。"""

    sub: str
    username: str
    display_name: str
    role: str
    email: str | None = None
    scope: str


class SessionItem(BaseModel):
    """登录会话条目。"""

    session_id: str
    user_id: int
    username: str | None = None
    display_name: str | None = None
    client_id: str
    ip: str | None = None
    user_agent: str | None = None
    status: str
    expires_at: str | None = None
    logout_at: str | None = None
    created_at: str | None = None


class OkResponse(BaseModel):
    status: str = "ok"
    message: str = ""
