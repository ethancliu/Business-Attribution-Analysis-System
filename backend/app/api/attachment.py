# -*- coding: utf-8 -*-
"""附件接口：上传 / 删除 / 详情下载 / 列表。"""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.paths import abs_path
from app.core.runtime_config import runtime_config
from app.models import User
from app.schemas import AttachmentDeleteRequest
from app.services import attachment as attachment_service
from app.services import conversation as conversation_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["attachment"])


@router.post("/api/attachment/upload", summary="上传附件")
async def upload(
    conversation_id: int = Form(..., description="所属会话 ID"),
    file: UploadFile = File(..., description="待上传文件"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = conversation_service.get_owned(db, user, conversation_id)

    content = await file.read()
    max_mb = runtime_config.get_int("system.max_upload_mb", 50)
    if len(content) > max_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件超过大小上限（{max_mb} MB）",
        )
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件内容为空")

    att = attachment_service.save_upload(db, user, conv.id, file.filename or "upload.bin", content)
    return {
        "attachment_id": att.id,
        "conversation_id": att.conversation_id,
        "file_name": att.file_name,
        "file_path": att.file_path,
        "file_type": att.file_type,
        "file_size": att.file_size,
        "parse_status": att.parse_status,
        "created_at": att.created_at.isoformat() if att.created_at else None,
    }


@router.post("/api/attachment/delete", summary="删除附件")
def delete(
    payload: AttachmentDeleteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ids = list(payload.attachment_ids or [])
    if payload.attachment_id is not None:
        ids.append(payload.attachment_id)
    if not ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未提供待删除的附件 ID")
    return attachment_service.delete_many(db, user, ids)


@router.get("/api/attachment/get", summary="获取附件详情；带 download=true 时返回文件流")
def get_attachment(
    attachment_id: int = Query(..., description="附件 ID"),
    download: bool = Query(default=False, description="是否直接下载文件"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    att = attachment_service.get_owned(db, user, attachment_id)

    if download:
        try:
            path = abs_path(att.file_path)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"文件路径非法：{exc}") from exc
        if not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件文件已丢失")
        filename = quote(att.file_name)
        return FileResponse(
            path,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
        )

    return attachment_service.detail(att)


@router.get("/api/attachment/ls", summary="获取会话附件列表")
def list_attachments(
    conversation_id: int = Query(..., description="会话 ID"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = conversation_service.get_owned(db, user, conversation_id)
    rows = attachment_service.list_for_conversation(db, conv.id)
    return {
        "conversation_id": conv.id,
        "total": len(rows),
        "items": [attachment_service.item(a) for a in rows],
    }
