# -*- coding: utf-8 -*-
"""管理控制台接口：配置热重载、配置查看与修改、运行日志、系统总览、数据源与功能开关。

全部接口要求 role == admin（依赖 require_admin）。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis import scenarios as scenario_pkg
from app.analysis.tools import tool_metadata
from app.core.config import settings
from app.core.db import get_db
from app.core.deps import require_admin
from app.core.paths import storage_stats
from app.core.runtime_config import SECRET_KEYS, runtime_config
from app.core.security import auth_client
from app.models import (
    AnalysisResult,
    AnalysisTask,
    Attachment,
    Conversation,
    DataSource,
    Message,
    SystemConfig,
    TaskLog,
    User,
)
from app.schemas import ConfigUpdateRequest, DataSourceToggleRequest, FeatureToggleRequest, ReloadRequest
from app.services import task as task_service
from app.ws.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

_STARTED_AT = time.time()

# 归入功能开关分组配置的键前缀
FEATURE_PREFIX = "feature."


# ---------------------------------------------------------------------------
# 配置热重载
# ---------------------------------------------------------------------------

@router.post("/api/admin/reload", summary="配置热重载")
def reload_config(
    payload: ReloadRequest | None = Body(default=None),
    admin: User = Depends(require_admin),
) -> dict:
    groups = list(payload.groups) if payload and payload.groups else []

    report = runtime_config.load()

    changed = report.changed
    if groups:
        changed = [c for c in changed if c.config_key.split(".")[0] in groups]

    logger.info(
        "管理员 %s 触发配置热重载，分组=%s，总键 %s，变化 %s 项",
        admin.username, groups or ["all"], report.total_keys, len(changed),
    )

    return {
        "status": "ok",
        "message": (
            f"配置热重载完成，共 {report.total_keys} 项配置，"
            f"{len(changed)} 项发生变化，已即时生效（无需重启服务）"
        ),
        "reloaded_groups": groups or ["all"],
        "total_keys": report.total_keys,
        "changed_keys": [
            {"config_key": c.config_key, "old_value": c.old_value, "new_value": c.new_value}
            for c in changed
        ],
        "reloaded_at": report.reloaded_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# 配置查看 / 修改
# ---------------------------------------------------------------------------

@router.get("/api/admin/configs", summary="查看系统配置")
def list_configs(
    group: str | None = Query(default=None, description="按分组过滤"),
    admin: User = Depends(require_admin),
) -> dict:
    items = runtime_config.items(group)
    return {
        "total": len(items),
        "groups": runtime_config.groups(),
        "items": items,
    }


@router.post("/api/admin/configs/update", summary="修改系统配置")
def update_config(
    payload: ConfigUpdateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    row = db.execute(
        select(SystemConfig).where(SystemConfig.config_key == payload.config_key)
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"配置项不存在：{payload.config_key}",
        )

    old_value = row.config_value
    row.config_value = payload.config_value
    db.commit()

    # 写库后立即热重载，保证内存配置与数据库一致
    runtime_config.load()

    masked = payload.config_key in SECRET_KEYS
    logger.info(
        "管理员 %s 修改配置 %s：%r -> %r",
        admin.username, payload.config_key,
        "******" if masked else old_value,
        "******" if masked else payload.config_value,
    )

    return {
        "status": "ok",
        "config_key": payload.config_key,
        "old_value": "******" if masked else old_value,
        "new_value": "******" if masked else payload.config_value,
        "need_reload": False,
        "message": "配置已写入数据库并完成热重载，新值已生效",
    }


# ---------------------------------------------------------------------------
# 运行日志
# ---------------------------------------------------------------------------

@router.get("/api/admin/logs", summary="查询系统运行日志")
def list_logs(
    task_id: int | None = Query(default=None),
    log_level: str | None = Query(default=None, description="DEBUG/INFO/WARN/ERROR"),
    log_type: str | None = Query(default=None, description="lifecycle/llm/tool/db/file/error"),
    limit: int = Query(default=100, ge=1, le=500),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(TaskLog)
    if task_id is not None:
        stmt = stmt.where(TaskLog.task_id == task_id)
    if log_level:
        stmt = stmt.where(TaskLog.log_level == log_level.upper())
    if log_type:
        stmt = stmt.where(TaskLog.log_type == log_type)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = list(db.execute(stmt.order_by(TaskLog.id.desc()).limit(limit)).scalars().all())

    return {
        "total": int(total),
        "items": [
            {
                "log_id": r.id,
                "task_id": r.task_id,
                "log_level": r.log_level,
                "log_type": r.log_type,
                "log_content": r.log_content,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# 系统总览
# ---------------------------------------------------------------------------

@router.get("/api/admin/overview", summary="系统运行状态总览")
def overview(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    def count(model, *criteria) -> int:
        stmt = select(func.count()).select_from(model)
        if criteria:
            stmt = stmt.where(*criteria)
        return int(db.execute(stmt).scalar_one())

    task_counts = task_service.count_by_status(db)

    reachable, message = auth_client.health()

    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "env": runtime_config.get("system.env", "dev"),
        "server_time": datetime.now().isoformat(),
        "uptime_sec": int(time.time() - _STARTED_AT),
        "counters": {
            "users": count(User),
            "conversations_active": count(Conversation, Conversation.status == "active"),
            "messages": count(Message),
            "attachments": count(Attachment),
            "tasks_total": task_counts.get("total", 0),
            "tasks_running": task_counts.get("running", 0) + task_counts.get("queued", 0),
            "tasks_success": task_counts.get("success", 0),
            "tasks_failed": task_counts.get("failed", 0),
            "tasks_cancelled": task_counts.get("cancelled", 0),
            "results": count(AnalysisResult),
        },
        "websocket": {
            "total_connections": manager.total_connections,
            "active_connections": manager.count(),
            "bound_conversations": manager.bound_conversations(),
            "loop_bound": manager.loop is not None,
        },
        "storage": storage_stats(),
        "auth_center": {
            "reachable": reachable,
            "message": message,
            "base_url": settings.auth_base_url,
            "introspect_cache_size": 0,
        },
    }


# ---------------------------------------------------------------------------
# 业务数据源
# ---------------------------------------------------------------------------

@router.get("/api/admin/datasources", summary="业务数据源列表")
def list_datasources(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    rows = list(db.execute(select(DataSource).order_by(DataSource.id)).scalars().all())
    return {
        "total": len(rows),
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "ds_type": r.ds_type,
                "host": r.host,
                "port": r.port,
                "db_name": r.db_name,
                "status": r.status,
                "description": r.description,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
    }


@router.post("/api/admin/datasources/toggle", summary="启用 / 停用业务数据源")
def toggle_datasource(
    payload: DataSourceToggleRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(DataSource, payload.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据源不存在")

    row.status = "disabled" if row.status == "enabled" else "enabled"
    db.commit()
    logger.info("管理员 %s 将数据源「%s」置为 %s", admin.username, row.name, row.status)

    return {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "message": f"数据源「{row.name}」已{'启用' if row.status == 'enabled' else '停用'}",
    }


# ---------------------------------------------------------------------------
# 功能开关
# ---------------------------------------------------------------------------

@router.get("/api/admin/feature-toggles", summary="功能开关列表")
def list_feature_toggles(admin: User = Depends(require_admin)) -> dict:
    items = []
    for item in runtime_config.items():
        key = item["config_key"]
        if not key.startswith(FEATURE_PREFIX):
            continue
        items.append({
            "config_key": key,
            "name": item.get("description") or key[len(FEATURE_PREFIX):],
            "enabled": str(item.get("config_value", "")).lower() in ("true", "1", "yes", "on"),
            "description": item.get("description"),
        })
    return {"total": len(items), "items": items}


@router.post("/api/admin/feature-toggles/toggle", summary="切换功能开关")
def toggle_feature(
    payload: FeatureToggleRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    if not payload.config_key.startswith(FEATURE_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"功能开关的配置键必须以 {FEATURE_PREFIX} 开头",
        )

    row = db.execute(
        select(SystemConfig).where(SystemConfig.config_key == payload.config_key)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="功能开关不存在")

    row.config_value = "true" if payload.enabled else "false"
    db.commit()
    runtime_config.load()

    logger.info("管理员 %s 将开关 %s 置为 %s", admin.username, payload.config_key, payload.enabled)
    return {
        "status": "ok",
        "config_key": payload.config_key,
        "enabled": payload.enabled,
        "message": f"开关已{'开启' if payload.enabled else '关闭'}并即时生效",
    }


# ---------------------------------------------------------------------------
# 认证中心状态
# ---------------------------------------------------------------------------

@router.get("/api/admin/auth-center", summary="认证中心状态")
def auth_center_status(admin: User = Depends(require_admin)) -> dict:
    reachable, message = auth_client.health()

    secret = settings.auth_client_secret
    masked = f"{secret[:4]}****{secret[-4:]}" if len(secret) > 8 else "******"

    overview: dict = {}
    if reachable:
        try:
            data = auth_client.admin_call("overview")
            if isinstance(data, dict):
                overview = data
        except Exception as exc:  # noqa: BLE001
            logger.warning("获取认证中心总览失败：%s", exc)

    return {
        "reachable": reachable,
        "authorize_url": settings.auth_authorize_url,
        "token_url": settings.auth_token_url,
        "userinfo_url": settings.auth_userinfo_url,
        "introspect_url": settings.auth_introspect_url,
        "client_id": settings.auth_client_id,
        "client_secret_masked": masked,
        "redirect_uri": settings.auth_redirect_uri,
        "introspect_cache_sec": settings.auth_introspect_cache_sec,
        "overview": overview,
        "message": message,
    }


# ---------------------------------------------------------------------------
# 场景与工具元信息（便于前端与管理端展示系统能力）
# ---------------------------------------------------------------------------

@router.get("/api/admin/scenarios", summary="已注册的分析场景清单")
def list_scenarios(admin: User = Depends(require_admin)) -> dict:
    items = scenario_pkg.scenario_metadata()
    return {"total": len(items), "items": items}


@router.get("/api/admin/tools", summary="已注册的分析工具清单")
def list_tools(admin: User = Depends(require_admin)) -> dict:
    items = tool_metadata()
    return {"total": len(items), "items": items}
