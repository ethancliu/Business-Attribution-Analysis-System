# -*- coding: utf-8 -*-
"""工具基类与执行上下文。

设计要点:
    - 每个工具声明 name / description / 参数签名，执行返回结构化 ToolResult
    - 工具只通过 ToolContext 访问外部世界（数据库、文件、配置），便于审计与替换
    - 所有工具都必须支持取消（ctx.check_cancel()）
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.paths import KIND_WORKSPACE, dir_of
from app.core.runtime_config import runtime_config


class TaskCancelled(Exception):
    """任务被用户取消，引擎据此退出并落库 cancelled。"""


@dataclass
class ToolContext:
    """一次任务执行期间的共享上下文。"""

    db: Session
    task_id: int
    conversation_id: int
    user_id: int
    input_text: str
    cancel_event: threading.Event | None = None
    step_index: int = 0
    cache: dict[str, Any] = field(default_factory=dict)

    def check_cancel(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise TaskCancelled("任务已被用户取消")

    @property
    def workspace_dir(self) -> Path:
        return dir_of(KIND_WORKSPACE, self.user_id, self.conversation_id)

    @property
    def data_root(self) -> Path:
        return settings.data_path

    def cfg(self, key: str, default: Any = None) -> Any:
        return runtime_config.get(key, default)


@dataclass
class ToolResult:
    """工具执行结果。"""

    ok: bool
    summary: str = ""
    data: Any = None
    rows: int = 0
    error: str | None = None
    evidence: list[dict] = field(default_factory=list)

    @staticmethod
    def failure(message: str) -> "ToolResult":
        return ToolResult(ok=False, summary=message, error=message)


class Tool:
    """工具基类。子类实现 run()。"""

    name: str = "tool"
    description: str = ""
    # 参数说明，用于文档与前端工具卡片展示
    signature: dict[str, str] = {}

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:  # pragma: no cover - 抽象
        raise NotImplementedError

    def safe_run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        """带取消检查与异常兜底的执行入口。"""
        ctx.check_cancel()
        try:
            return self.run(ctx, **kwargs)
        except TaskCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - 工具失败应降级而非炸掉整个任务
            return ToolResult.failure(f"工具 {self.name} 执行失败：{exc}")


# 全局工具注册表
_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    _REGISTRY[tool.name] = tool
    return tool


def get_tool(name: str) -> Tool:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise LookupError(f"未注册的工具：{name}") from exc


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def tool_metadata() -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "signature": t.signature}
        for t in _REGISTRY.values()
    ]


# 供场景使用的便捷类型
StepRunner = Callable[[ToolContext], ToolResult]
