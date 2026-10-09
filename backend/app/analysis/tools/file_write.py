# -*- coding: utf-8 -*-
"""文件写入工具：把中间分析产物写入会话工作区。

安全约束:
    只允许写入 workspace/{user_id}/{conversation_id}/ 之内，
    文件名强制清洗，目录自动创建，写入路径返回入库相对路径。
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime
from typing import Any

from app.analysis.tools.base import Tool, ToolContext, ToolResult, register
from app.core.paths import KIND_WORKSPACE, dir_of, human_size, safe_join, sanitize_filename

logger = logging.getLogger(__name__)


class FileWriteTool(Tool):
    name = "file_write"
    description = "把分析中间产物（明细表、汇总数据、草稿）写入会话工作区，供后续步骤或用户下载"
    signature = {
        "file_name": "文件名（自动清洗，自动加时间戳防重名）",
        "content": "文本内容；若 format=table 则传二维数组",
        "format": "text | json | csv | table",
    }

    def run(
        self,
        ctx: ToolContext,
        file_name: str = "workspace_artifact.txt",
        content: Any = "",
        format: str = "text",
        **_: Any,
    ) -> ToolResult:
        ctx.check_cancel()

        safe_name = sanitize_filename(file_name, fallback="artifact.txt")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem, dot, ext = safe_name.rpartition(".")
        if dot:
            final_name = f"{stem}_{stamp}.{ext}"
        else:
            final_name = f"{safe_name}_{stamp}.txt"

        try:
            target_dir = dir_of(KIND_WORKSPACE, ctx.user_id, ctx.conversation_id)
            target = safe_join(target_dir, final_name)
        except ValueError as exc:
            return ToolResult.failure(f"目标路径不合法：{exc}")

        try:
            if format == "table":
                body = self._table_to_csv(content)
            elif format == "json":
                body = json.dumps(content, ensure_ascii=False, indent=2, default=str)
            elif format == "csv":
                body = self._table_to_csv(content)
            else:
                body = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)

            target.write_text(body, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(f"写入文件失败：{exc}")

        rel = f"{KIND_WORKSPACE}/{ctx.user_id}/{ctx.conversation_id}/{target.name}"
        size = target.stat().st_size
        logger.info("file_write 写入 %s（%s）", rel, human_size(size))

        return ToolResult(
            ok=True,
            summary=f"已写出中间产物 {target.name}（{human_size(size)}）到工作区",
            data={"file_path": rel, "file_name": target.name, "file_size": size},
            rows=len(body.splitlines()),
        )

    @staticmethod
    def _table_to_csv(rows: Any) -> str:
        if not isinstance(rows, list) or not rows:
            return ""
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            if isinstance(row, dict):
                writer.writerow(list(row.values()))
            elif isinstance(row, (list, tuple)):
                writer.writerow(["" if c is None else c for c in row])
            else:
                writer.writerow([row])
        return buf.getvalue()


register(FileWriteTool())
