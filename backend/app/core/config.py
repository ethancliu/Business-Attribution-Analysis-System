# -*- coding: utf-8 -*-
"""后端服务基础设施配置（进程级，改动需重启）。

业务配置（可热更新）不在这里，而在 app/core/runtime_config.py 中从
数据库 system_configs 表加载，管理员改完调 /api/admin/reload 即时生效。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 服务 ----
    app_name: str = "经营多轮归因分析系统"
    app_version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True
    # 后端对外可达地址，用于拼接回调地址
    public_base_url: str = "http://localhost:8000"
    # 前端地址，登录回调完成后跳转至此
    frontend_base_url: str = "http://localhost:5173"

    # ---- 业务数据库 ----
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = "root"
    db_name: str = "analysis_sys"
    db_charset: str = "utf8mb4"

    # ---- 认证中心 ----
    auth_base_url: str = "http://localhost:9000"
    auth_client_id: str = "jingying-web"
    auth_client_secret: str = "jingying-web-secret-2026"
    auth_redirect_uri: str = "http://localhost:8000/auth/callback"
    auth_scope: str = "openid profile analysis"
    # 令牌内省结果缓存秒数
    auth_introspect_cache_sec: int = 60
    # 调用认证中心的 HTTP 超时
    auth_http_timeout_sec: int = 10
    # 认证中心未显式返回 expires_in 时的兜底有效期（秒）
    auth_token_ttl_hint: int = 7200

    # ---- 存储根目录 ----
    data_dir: str = "data"

    # ---- CORS ----
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000,"
        "http://localhost:4173,http://127.0.0.1:4173"
    )

    # ---- Cookie ----
    cookie_name: str = "jy_access_token"
    refresh_cookie_name: str = "jy_refresh_token"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    @property
    def database_url(self) -> str:
        from urllib.parse import quote_plus

        pwd = quote_plus(self.db_password)
        return (
            f"mysql+pymysql://{self.db_user}:{pwd}@{self.db_host}:{self.db_port}"
            f"/{self.db_name}?charset={self.db_charset}"
        )

    @property
    def data_path(self) -> Path:
        """存储根目录绝对路径。"""
        p = Path(self.data_dir)
        return p if p.is_absolute() else (BASE_DIR / p)

    @property
    def upload_root(self) -> Path:
        return self.data_path / "uploads"

    @property
    def export_root(self) -> Path:
        return self.data_path / "exports"

    @property
    def workspace_root(self) -> Path:
        return self.data_path / "workspace"

    @property
    def knowledge_root(self) -> Path:
        return BASE_DIR / "knowledge"

    @property
    def auth_authorize_url(self) -> str:
        return f"{self.auth_base_url.rstrip('/')}/oauth/authorize"

    @property
    def auth_token_url(self) -> str:
        return f"{self.auth_base_url.rstrip('/')}/oauth/token"

    @property
    def auth_userinfo_url(self) -> str:
        return f"{self.auth_base_url.rstrip('/')}/oauth/userinfo"

    @property
    def auth_introspect_url(self) -> str:
        return f"{self.auth_base_url.rstrip('/')}/oauth/introspect"

    @property
    def auth_logout_url(self) -> str:
        return f"{self.auth_base_url.rstrip('/')}/oauth/logout"

    @property
    def auth_admin_url(self) -> str:
        return f"{self.auth_base_url.rstrip('/')}/admin"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
