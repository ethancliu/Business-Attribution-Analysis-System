# -*- coding: utf-8 -*-
"""认证中心配置。所有配置项均可通过环境变量或 .env 覆盖。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 服务 ----
    app_name: str = "经营多轮归因分析系统-认证中心"
    app_version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = 9000
    debug: bool = True

    # ---- 数据库 ----
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = "root"
    db_name: str = "analysis_auth"
    db_charset: str = "utf8mb4"

    # ---- 令牌策略 ----
    auth_code_ttl_sec: int = 300           # 授权码有效期 5 分钟
    access_token_ttl_sec: int = 7200       # 访问令牌 2 小时
    refresh_token_ttl_sec: int = 604800    # 刷新令牌 7 天
    session_ttl_sec: int = 43200           # 登录会话 12 小时

    # ---- 管理接口 ----
    admin_api_key: str = "jingying-auth-admin-2026"

    # ---- CORS ----
    cors_origins: str = "*"

    @property
    def database_url(self) -> str:
        from urllib.parse import quote_plus

        pwd = quote_plus(self.db_password)
        return (
            f"mysql+pymysql://{self.db_user}:{pwd}@{self.db_host}:{self.db_port}"
            f"/{self.db_name}?charset={self.db_charset}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
