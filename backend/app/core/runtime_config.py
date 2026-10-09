# -*- coding: utf-8 -*-
"""系统配置内存缓存 + 热更新。

设计:
    - 进程启动时从 `system_configs` 表全量加载到内存字典，后续读取零数据库开销；
    - 管理员修改配置后调用 `POST /api/admin/reload`，本模块重新全量加载并返回差异；
    - 全部业务代码统一通过 `runtime_config.get("xxx.yyy")` 读取，因此热更新对全链路即时生效，
      无需重启后端进程。

线程安全:
    使用可重入锁保护内存字典的替换，读操作基于不可变字典替换（copy-on-write），
    因此并发读不会看到中间状态。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import SystemConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 默认值（数据库不可用时的兜底，保证服务仍能启动）
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, str] = {
    "system.name": "经营多轮归因分析系统",
    "system.version": "1.0.0",
    "system.env": "dev",
    "system.page_size": "20",
    "system.max_upload_mb": "50",
    "system.allow_extensions": "txt,md,csv,json,xlsx,xls,pdf,log",

    "analysis.max_rounds": "20",
    "analysis.tool_timeout_sec": "60",
    "analysis.max_tool_calls": "12",
    "analysis.context_keep_rounds": "4",
    "analysis.summary_trigger_messages": "40",
    "analysis.step_interval_ms": "300",
    "analysis.default_scenario": "auto",

    "auth.authorize_url": "http://localhost:9000/oauth/authorize",
    "auth.token_url": "http://localhost:9000/oauth/token",
    "auth.userinfo_url": "http://localhost:9000/oauth/userinfo",
    "auth.introspect_url": "http://localhost:9000/oauth/introspect",
    "auth.client_id": "jingying-web",
    "auth.client_secret": "jingying-web-secret-2026",
    "auth.redirect_uri": "http://localhost:8000/auth/callback",
    "auth.introspect_cache_sec": "60",

    "storage.upload_dir": "uploads",
    "storage.export_dir": "exports",
    "storage.workspace_dir": "workspace",
    "storage.retention_days": "30",

    "llm.enabled": "false",
    "llm.provider": "openai_compatible",
    "llm.base_url": "",
    "llm.api_key": "",
    "llm.model": "",
    "llm.temperature": "0.2",
    "llm.timeout_sec": "60",

    "feature.enable_shell_tool": "true",
    "feature.enable_file_write": "true",
    "feature.enable_export": "true",
    "feature.enable_ws_stream": "true",
    "feature.enable_multi_turn": "true",
    "feature.maintenance_mode": "false",

    "security.allowed_shell_commands": "echo,dir,type,findstr,python,where",
    "security.sql_readonly": "true",
    "security.sql_row_limit": "2000",
}

# 读取时脱敏的配置键
SECRET_KEYS = {"auth.client_secret", "llm.api_key"}


@dataclass
class Change:
    config_key: str
    old_value: str | None
    new_value: str | None


@dataclass
class ReloadReport:
    total_keys: int = 0
    changed: list[Change] = field(default_factory=list)
    reloaded_groups: list[str] = field(default_factory=lambda: ["all"])
    reloaded_at: datetime = field(default_factory=datetime.now)

    @property
    def changed_count(self) -> int:
        return len(self.changed)


class RuntimeConfig:
    """系统配置的进程内缓存。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, str] = dict(DEFAULTS)
        self._meta: dict[str, dict[str, Any]] = {}
        self._loaded_at: datetime | None = None
        self._source: str = "defaults"

    # ---------------------------------------------------------------- 读
    def get(self, key: str, default: str | None = None) -> str | None:
        return self._data.get(key, DEFAULTS.get(key, default))

    def get_int(self, key: str, default: int = 0) -> int:
        raw = self.get(key)
        if raw is None or raw == "":
            return default
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            logger.warning("配置 %s 的值 %r 不是整数，回退默认值 %s", key, raw, default)
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        raw = self.get(key)
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self.get(key)
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on", "enabled"}

    def get_list(self, key: str, default: list[str] | None = None) -> list[str]:
        raw = self.get(key)
        if not raw:
            return list(default or [])
        return [x.strip() for x in raw.split(",") if x.strip()]

    def all(self) -> dict[str, str]:
        return dict(self._data)

    def meta(self, key: str) -> dict[str, Any]:
        return dict(self._meta.get(key, {}))

    def items(self, group: str | None = None) -> list[dict[str, Any]]:
        out = []
        for k, v in sorted(self._data.items()):
            m = self._meta.get(k, {})
            g = m.get("config_group", k.split(".")[0] if "." in k else "system")
            if group and g != group:
                continue
            out.append(
                {
                    "config_key": k,
                    "config_value": "******" if k in SECRET_KEYS and v else v,
                    "config_group": g,
                    "description": m.get("description"),
                    "updated_at": m.get("updated_at"),
                }
            )
        return out

    def groups(self) -> list[str]:
        gs = set()
        for k in self._data:
            m = self._meta.get(k, {})
            gs.add(m.get("config_group", k.split(".")[0] if "." in k else "system"))
        return sorted(gs)

    @property
    def loaded_at(self) -> datetime | None:
        return self._loaded_at

    @property
    def source(self) -> str:
        return self._source

    # ---------------------------------------------------------------- 写
    def load(self) -> ReloadReport:
        """从数据库全量重新加载配置，返回与当前内存状态的差异。"""
        with self._lock:
            old = dict(self._data)
            new: dict[str, str] = {}
            meta: dict[str, dict[str, Any]] = {}

            try:
                with SessionLocal() as db:
                    rows = db.execute(select(SystemConfig)).scalars().all()
                for r in rows:
                    new[r.config_key] = r.config_value if r.config_value is not None else ""
                    meta[r.config_key] = {
                        "config_group": r.config_group,
                        "description": r.description,
                        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    }
                self._source = "database"
            except Exception as exc:  # noqa: BLE001
                logger.error("配置加载失败，保留上一份内存配置: %s", exc)
                self._source = "database_error"
                report = ReloadReport(total_keys=len(self._data))
                self._loaded_at = datetime.now()
                return report

            # 数据库缺项时用默认值补齐，保证业务读取不会拿到 None
            for k, v in DEFAULTS.items():
                new.setdefault(k, v)

            changes = [
                Change(k, old.get(k), v)
                for k, v in new.items()
                if old.get(k) != v
            ]
            removed = [Change(k, old[k], None) for k in old if k not in new]
            changes.extend(removed)

            # copy-on-write 替换，读方永不看到中间态
            self._data = new
            self._meta = meta
            self._loaded_at = datetime.now()

            if changes:
                logger.info("配置热重载完成：%s 项配置，%s 项发生变化", len(new), len(changes))
                for c in changes:
                    logger.info("  配置变化 %s: %r -> %r", c.config_key, c.old_value, c.new_value)

            return ReloadReport(
                total_keys=len(new),
                changed=sorted(changes, key=lambda c: c.config_key),
                reloaded_at=self._loaded_at,
            )


runtime_config = RuntimeConfig()
