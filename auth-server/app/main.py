# -*- coding: utf-8 -*-
"""经营多轮归因分析系统 —— 认证中心服务入口。

启动:
    cd auth-server
    uv run uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload

接口文档:
    Swagger UI  http://localhost:9000/docs
    ReDoc       http://localhost:9000/redoc
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text

from app.api import admin, oauth
from app.core.config import settings
from app.core.db import engine

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("auth-server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动自检：确认认证库表结构就绪
    try:
        with engine.connect() as conn:
            n_users = conn.execute(text("SELECT COUNT(*) FROM auth_users")).scalar_one()
            n_clients = conn.execute(text("SELECT COUNT(*) FROM auth_clients")).scalar_one()
        logger.info("认证库连接成功 (%s)：用户 %s 个，客户端 %s 个", settings.db_name, n_users, n_clients)
        if n_users == 0:
            logger.warning("认证库无用户，请先执行 database/01_auth_schema.sql")
    except Exception as exc:  # noqa: BLE001
        logger.error("认证库自检失败：%s", exc)
        logger.error("请确认 MySQL 已启动且已执行 database/01_auth_schema.sql")

    logger.info("认证中心已启动 -> http://%s:%s", settings.host, settings.port)
    logger.info("授权入口   -> http://localhost:%s/oauth/authorize", settings.port)
    yield
    logger.info("认证中心已停止")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "经营多轮归因分析系统 —— 统一认证中心。\n\n"
        "实现 OAuth2 授权码模式：授权入口 → 登录 → 授权码 → 令牌换取 → 令牌内省 → 登出吊销，"
        "并提供登录会话全生命周期管理与认证操作日志。"
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(oauth.router)
app.include_router(admin.router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    return HTMLResponse(
        content=f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{settings.app_name}</title>
<style>
 body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#0d1421;color:#e6edf7;
      display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
 .box{{background:#162032;border:1px solid #26334d;border-radius:14px;padding:36px 44px;
      box-shadow:0 20px 60px rgba(0,0,0,.5);max-width:620px}}
 h1{{font-size:19px;margin:0 0 6px}}
 .v{{color:#5d6f8c;font-size:12px;margin-bottom:24px}}
 a{{display:block;color:#4da3ff;text-decoration:none;padding:9px 12px;border-radius:8px;
    background:#0e1726;margin-bottom:8px;font-size:13.5px}}
 a:hover{{background:#122036}}
 code{{color:#7cc4ff}}
</style></head><body><div class="box">
<h1>{settings.app_name}</h1>
<div class="v">v{settings.app_version} · 端口 {settings.port}</div>
<a href="/docs">接口文档 Swagger UI &nbsp;<code>/docs</code></a>
<a href="/oauth/authorize?client_id=jingying-web&amp;redirect_uri=http://localhost:8000/auth/callback&amp;response_type=code&amp;scope=openid%20profile&amp;state=demo">发起一次授权登录 &nbsp;<code>/oauth/authorize</code></a>
<a href="/oauth/sessions">登录会话列表 &nbsp;<code>/oauth/sessions</code></a>
<a href="/oauth/healthz">健康检查 &nbsp;<code>/oauth/healthz</code></a>
</div></body></html>"""
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("未处理异常 %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "server_error",
            "error_description": str(exc),
            "path": request.url.path,
            "time": datetime.now().isoformat(timespec="seconds"),
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
