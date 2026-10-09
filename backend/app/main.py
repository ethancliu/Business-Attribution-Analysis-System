# -*- coding: utf-8 -*-
"""后端服务入口。

启动顺序（lifespan）:
    1. 确保 uploads / exports / workspace 目录就绪
    2. 绑定 WebSocket 管理器到主事件循环（分析线程跨线程推送的前提）
    3. 从 system_configs 加载热更新配置
    4. 清理上次进程遗留的 running/queued 任务

关闭顺序:
    1. 关闭全部 WebSocket 连接
    2. 等待分析线程池退出
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api import admin, attachment, auth, chat, results, tasks
from app.core.config import settings
from app.core.db import ping, session_scope
from app.core.paths import ensure_dirs
from app.core.runtime_config import runtime_config
from app.core.security import auth_client
from app.services import chat as chat_service
from app.services import task as task_service
from app.ws import routes as ws_routes
from app.ws.manager import manager

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-38s | %(message)s"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format=LOG_FORMAT,
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # 第三方库日志降噪
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


setup_logging()
logger = logging.getLogger("app.main")

_STARTED_AT = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 78)
    logger.info("启动 %s v%s（环境 %s）", settings.app_name, settings.app_version, runtime_config.get("system.env", "dev"))

    # 1) 存储目录
    ensure_dirs()

    # 2) 绑定事件循环（分析任务在后台线程中执行，需要回到主循环推送报文）
    manager.bind_loop(asyncio.get_running_loop())

    # 3) 加载热更新配置
    report = runtime_config.load()
    logger.info("配置加载完成：来源=%s，共 %s 项", runtime_config.source, report.total_keys)

    # 4) 数据库连通性
    if ping():
        logger.info("业务数据库连通正常：%s:%s/%s", settings.db_host, settings.db_port, settings.db_name)
    else:
        logger.error("业务数据库连接失败，请检查 .env 中的数据库配置")

    # 5) 清理上次进程遗留的任务
    try:
        with session_scope() as db:
            task_service.cleanup_stale(db, max_age_minutes=1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("残留任务清理失败：%s", exc)

    logger.info("服务地址：http://localhost:%s  接口文档：/docs  长连接：%s", settings.port, ws_routes.WS_PATH)
    logger.info("=" * 78)

    try:
        yield
    finally:
        logger.info("正在关闭服务……")
        await manager.close_all()
        chat_service.shutdown_executor(wait=False)
        logger.info("服务已关闭，运行时长 %s 秒", int(time.time() - _STARTED_AT))


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "经营多轮归因分析系统后端服务。\n\n"
        "- 认证：对接独立认证中心（OAuth2 授权码模式），访问令牌为 opaque token\n"
        "- 分析：六大预置业务场景 + 通用兜底场景，全部结论可回溯至证据链\n"
        "- 实时：分析过程通过 WebSocket 推送 message_start / tool_start / ... / done\n"
        "- 存储：uploads / exports / workspace 三级目录，删除会话时级联清理"
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# ---------------- 路由 ----------------
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(attachment.router)
app.include_router(tasks.router)
app.include_router(results.router)
app.include_router(admin.router)
app.include_router(ws_routes.router)


# ---------------- 异常处理 ----------------
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """把参数校验错误转成统一的可读提示。"""
    details = []
    for err in exc.errors():
        loc = " -> ".join(str(x) for x in err.get("loc", []) if x != "body")
        details.append(f"{loc}: {err.get('msg')}")
    return JSONResponse(
        status_code=422,
        content={"detail": "请求参数校验失败；" + "；".join(details)},
    )


@app.exception_handler(SQLAlchemyError)
async def db_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception("数据库异常：%s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"数据库操作失败：{exc.__class__.__name__}"},
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常：%s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"服务端内部错误：{exc}"},
    )


# ---------------- 基础端点 ----------------
@app.get("/", tags=["system"], summary="服务根路径")
def root() -> dict:
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "websocket": ws_routes.WS_PATH,
        "time": datetime.now().isoformat(),
    }


@app.get("/healthz", tags=["system"], summary="健康检查")
def healthz() -> dict:
    db_ok = ping()
    auth_ok, auth_msg = auth_client.health()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "websocket_connections": manager.count(),
        "uptime_sec": int(time.time() - _STARTED_AT),
        "config_source": runtime_config.source,
        "auth_center": {"reachable": auth_ok, "message": auth_msg},
        "time": datetime.now().isoformat(),
    }


@app.get("/api/config/public", tags=["system"], summary="前端可读的公开配置")
def public_config() -> dict:
    """把前端需要但不敏感的运行时配置暴露出去（无需登录）。"""
    return {
        "system_name": runtime_config.get("system.name", settings.app_name),
        "version": settings.app_version,
        "env": runtime_config.get("system.env", "dev"),
        "websocket_path": ws_routes.WS_PATH,
        "upload_max_mb": runtime_config.get_int("system.max_upload_mb", 50),
        "allowed_upload_ext": runtime_config.get_list(
            "system.allow_extensions",
            ["txt", "md", "csv", "json", "xlsx", "xls", "pdf", "log"],
        ),
        "analysis_window": {
            "base_period": f"{runtime_config.get('analysis.base_period_start', '2026-09-01')} ~ "
                           f"{runtime_config.get('analysis.base_period_end', '2026-09-15')}",
            "anomaly_period": f"{runtime_config.get('analysis.anomaly_period_start', '2026-09-16')} ~ "
                              f"{runtime_config.get('analysis.anomaly_period_end', '2026-09-30')}",
        },
    }


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info",
    )
