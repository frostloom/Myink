"""用户问题反馈：提交（问题描述 + 图片/视频佐证）、查看自己的历史、取回附件。

附件字节落盘在 ``settings.feedback_dir``（容器里是卷挂载点），库表只存元数据。
上传校验的要点是**边读边计数**：`Content-Length` 与 `UploadFile.size` 都是客户端可
声称的数字，超限要能在写完之前中断，并且把已写下的分片删掉，不留垃圾。
"""

from __future__ import annotations

import re
import secrets
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from myink.api.auth import require_user
from myink.api.schemas import FeedbackListOut, FeedbackOut
from myink.config import settings
from myink.db import new_session
from myink.models import Feedback, User
from myink.models.feedback import CATEGORY_IDS

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])

# mime → 落盘扩展名。别的一律拒；客户端文件名只作展示，不进路径。
_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
_VIDEO_TYPES = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}
_ALLOWED_TYPES = {**_IMAGE_TYPES, **_VIDEO_TYPES}
_READ_CHUNK = 1024 * 1024
_DESCRIPTION_MAX = 2000
# 只保留字母数字、下划线、点、连字符与汉字；路径分隔符与控制字符一并抹掉
_NAME_KEEP = re.compile(r"[^\w.\-一-鿿]+")


def _safe_display_name(name: str) -> str:
    cleaned = _NAME_KEEP.sub("_", Path(name or "").name.strip())[:120]
    return cleaned or "附件"


def _max_bytes(mime: str) -> int:
    return settings.feedback_video_max_bytes if mime in _VIDEO_TYPES else settings.feedback_image_max_bytes


def _out(item: Feedback, *, username: str = "") -> dict:
    return {
        "id": str(item.id),
        "username": username,
        "category": item.category,
        "description": item.description,
        "contact": item.contact,
        "page_url": item.page_url,
        "status": item.status,
        "attachments": [
            {"index": i, **record} for i, record in enumerate(item.attachments or [])
        ],
        "created_at": item.created_at,
    }


def _write_attachment(target: Path, upload: UploadFile, limit: int) -> int:
    """流式落盘并返回实际字节数；超过 ``limit`` 抛 400 并删除半截文件。"""
    written = 0
    try:
        with target.open("wb") as sink:
            while chunk := upload.file.read(_READ_CHUNK):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(
                        status_code=400,
                        detail=f"ATTACHMENT_TOO_LARGE: 单个附件不超过 {limit // (1024 * 1024)} MB",
                    )
                sink.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if written == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="ATTACHMENT_EMPTY")
    return written


@router.post("", response_model=FeedbackOut)
def submit(
    request: Request,
    description: str = Form(..., max_length=_DESCRIPTION_MAX),
    category: str = Form("bug"),
    contact: str = Form("", max_length=200),
    page_url: str = Form("", max_length=512),
    files: list[UploadFile] = File(default=[]),
    user_id: str = Depends(require_user),
) -> dict:
    """提交一条反馈。附件按 mime 分类限体积、整体限个数；全部写盘成功才落库。"""
    text = description.strip()
    if not text:
        raise HTTPException(status_code=400, detail="问题描述不能为空")
    if category not in CATEGORY_IDS:
        category = "other"
    uploads = [item for item in files if item.filename]
    if len(uploads) > settings.feedback_max_files:
        raise HTTPException(
            status_code=400, detail=f"TOO_MANY_FILES: 最多 {settings.feedback_max_files} 个附件"
        )

    feedback_id = uuid.uuid4()
    folder = Path(settings.feedback_dir) / str(feedback_id)
    records: list[dict] = []
    try:
        if uploads:
            folder.mkdir(parents=True, exist_ok=True)
        for seq, upload in enumerate(uploads):
            mime = (upload.content_type or "").split(";")[0].strip().lower()
            ext = _ALLOWED_TYPES.get(mime)
            if ext is None:
                raise HTTPException(
                    status_code=400,
                    detail="UNSUPPORTED_MEDIA_TYPE: 只收 jpg/png/webp/gif 与 mp4/webm/mov",
                )
            stored = f"{seq}-{secrets.token_hex(8)}{ext}"
            size = _write_attachment(folder / stored, upload, _max_bytes(mime))
            records.append({
                "name": _safe_display_name(upload.filename or ""),
                "mime": mime,
                "bytes": size,
                "stored": stored,
            })
    except Exception:
        # 半途失败连目录一起清掉：库里没这条反馈，盘上也不该留它的附件
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        for upload in uploads:
            upload.file.close()

    with new_session() as db:
        item = Feedback(
            id=feedback_id,
            user_id=uuid.UUID(user_id),
            category=category,
            description=text,
            contact=contact.strip(),
            page_url=page_url.strip(),
            user_agent=(request.headers.get("user-agent") or "")[:256],
            status="open",
            attachments=records,
        )
        db.add(item)
        db.commit()
        return _out(item)


@router.get("", response_model=FeedbackListOut)
def list_items(user_id: str = Depends(require_user)) -> dict:
    """本人提交历史，新的在前。附件取件地址由前端按 id + index 拼。"""
    with new_session() as db:
        rows = db.scalars(
            select(Feedback)
            .where(Feedback.user_id == uuid.UUID(user_id))
            .order_by(Feedback.created_at.desc(), Feedback.id.desc())
        ).all()
        return {"items": [_out(item) for item in rows]}


@router.get("/{feedback_id}/attachments/{index}")
def read_attachment(feedback_id: str, index: int, user_id: str = Depends(require_user)) -> FileResponse:
    """取回附件。非本人（且非 admin）一律 404——不用 403，免得暴露「这条反馈存在」。"""
    try:
        target = uuid.UUID(feedback_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="NOT_FOUND") from None
    with new_session() as db:
        item = db.get(Feedback, target)
        if item is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        role = db.scalar(select(User.role).where(User.id == uuid.UUID(user_id)))
        if item.user_id != uuid.UUID(user_id) and role != "admin":
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        records = item.attachments or []
        if index < 0 or index >= len(records):
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        record = records[index]

    path = Path(settings.feedback_dir) / str(target) / str(record.get("stored", ""))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return FileResponse(
        path,
        media_type=record.get("mime") or "application/octet-stream",
        filename=record.get("name") or path.name,
        headers={"Cache-Control": "private, no-store"},
    )
