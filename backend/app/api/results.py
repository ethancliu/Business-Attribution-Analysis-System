# -*- coding: utf-8 -*-
"""分析结果接口：按任务取结构化结果 / 下载导出文件。"""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models import User
from app.services import result as result_service
from app.services import task as task_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["results"])


# 注意：字面量路径必须注册在 /api/results/{task_id} 之前，
# 否则 "download" 会被当成 task_id 去解析成 int 而返回 422。
@router.get("/api/results/download", summary="下载分析结果文件（md / json / xlsx）")
def download_result(
    result_id: int = Query(..., description="结果 ID"),
    format: str = Query(default="md", description="md / json / xlsx"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = result_service.get_owned(db, user, result_id)
    task = task_service.get_owned(db, user, result.task_id)

    fmt = result_service.normalize_format(format)
    try:
        path = result_service.resolve_export_file(result, fmt, task, db)
    except Exception as exc:  # noqa: BLE001
        logger.exception("结果 #%s 导出失败", result_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"结果文件导出失败：{exc}",
        ) from exc

    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="结果文件不存在")

    filename = quote(path.name)
    return FileResponse(
        path,
        media_type=result_service.MEDIA_TYPES.get(fmt, "application/octet-stream"),
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/api/results/{result_id}/download", summary="下载结果文件（与上面等价的别名路径）")
def download_result_alias(
    result_id: int,
    format: str = Query(default="md", description="md / json / xlsx"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """兼容 docs/API.md §8.1 示例中的 download_url 形态。"""
    return download_result(result_id=result_id, format=format, user=user, db=db)


@router.get("/api/results/{task_id}", summary="按任务获取结构化分析结果（六大模块）")
def get_result(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    task = task_service.get_owned(db, user, task_id)
    result = result_service.get_by_task(db, task.id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该任务尚未生成分析结果",
        )
    return result_service.to_dict(result, task)
