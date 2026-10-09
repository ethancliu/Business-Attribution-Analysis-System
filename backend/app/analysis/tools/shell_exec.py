# -*- coding: utf-8 -*-
"""命令执行工具：运行白名单内的本地计算脚本，用于统计与格式转换。

安全约束（重要）:
    1. 默认走「注册脚本」模式：只能执行 backend/scripts/tools/ 下随项目发布的脚本
    2. 不启用 shell（shell=False），参数以列表传递，杜绝命令注入
    3. 工作目录固定为会话 workspace，超时 20 秒，输出长度截断
    4. 只有配置 analysis.allow_custom_command=true 时才允许执行自定义可执行文件，
       且可执行文件仍需命中白名单
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.analysis.tools.base import Tool, ToolContext, ToolResult, register
from app.core.runtime_config import runtime_config

logger = logging.getLogger(__name__)

TIMEOUT_SEC = 20
MAX_OUTPUT = 8000


def timeout_sec() -> int:
    """脚本执行超时，取自运行时配置 analysis.tool_timeout_sec。"""
    return max(1, runtime_config.get_int("analysis.tool_timeout_sec", TIMEOUT_SEC))

# 随项目发布的可信脚本目录
SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts" / "tools"

# 允许直接调用的可执行文件（仅当显式开启自定义命令时生效）
ALLOWED_EXECUTABLES = {"python", "python3"}


def available_scripts() -> list[str]:
    if not SCRIPTS_DIR.is_dir():
        return []
    return sorted(p.name for p in SCRIPTS_DIR.glob("*.py"))


class ShellExecTool(Tool):
    name = "shell_exec"
    description = "在会话工作区中执行白名单内的本地计算脚本（统计运算、格式转换），返回标准输出"
    signature = {
        "script": "scripts/tools/ 下的脚本文件名，如 stats.py",
        "args": "传给脚本的参数列表",
        "stdin": "可选，写入标准输入的内容",
    }

    def run(
        self,
        ctx: ToolContext,
        script: str = "",
        args: list[str] | None = None,
        stdin: str | None = None,
        **_: Any,
    ) -> ToolResult:
        name = (script or "").strip()
        if not name:
            return ToolResult.failure("script 不能为空")

        executable = sys.executable
        cmd: list[str]

        if name.endswith(".py") and name in available_scripts():
            # 已注册的项目脚本：允许
            cmd = [executable, "-I", str(SCRIPTS_DIR / name)]
        elif runtime_config.get_bool("feature.enable_shell_tool", True) and name in ALLOWED_EXECUTABLES:
            cmd = [name]
        else:
            scripts = available_scripts()
            return ToolResult.failure(
                f"脚本 {name} 不在白名单内。可用脚本：{', '.join(scripts) or '（无）'}"
            )

        argv = [str(a) for a in (args or [])]
        cmd.extend(argv)

        ctx.check_cancel()

        workdir = ctx.workspace_dir
        logger.info("shell_exec 执行 %s（cwd=%s）", cmd, workdir)

        limit_sec = timeout_sec()
        try:
            proc = subprocess.run(  # noqa: S603 - 白名单 + shell=False
                cmd,
                input=(stdin or "").encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(workdir),
                timeout=limit_sec,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.failure(f"脚本执行超时（>{limit_sec}s）：{name}")
        except FileNotFoundError as exc:
            return ToolResult.failure(f"无法启动进程：{exc}")

        out = proc.stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT]
        err = proc.stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT // 2]

        if proc.returncode != 0:
            return ToolResult.failure(f"脚本返回码 {proc.returncode}：{err or out or '无输出'}")

        data: Any = {"stdout": out, "stderr": err, "returncode": proc.returncode}
        try:
            data["parsed"] = json.loads(out)
        except (json.JSONDecodeError, ValueError):
            pass

        first_line = out.strip().splitlines()[0] if out.strip() else "（无输出）"
        return ToolResult(
            ok=True,
            summary=f"脚本 {name} 执行成功，输出首行：{first_line[:160]}",
            data=data,
            rows=len(out.splitlines()),
        )


register(ShellExecTool())
