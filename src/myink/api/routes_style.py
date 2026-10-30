"""建书时选文风：把选择器的值解析成落库用的档案。

文风在建书那一刻定死——`project_settings.style_profile` 是当时那份档案的副本，
没有「书内再改」的入口（见 models/creation.py 的口径）。所以这里只有读取侧：
解析选择器的值，没有写 project_settings 的端点。
样本提取与命名保存都在账号级文风库（routes_style_library.py）里做，书只负责选用；
内置预设也由那个端点一起出（`builtin:<id>` 行），这里不再单列一份清单。
"""

from __future__ import annotations

import uuid
import hashlib

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from myink.models import StyleLibraryItem
from myink.models.writing_resource import PersonalWritingResource, WritingResource
from myink.seed import STYLE_PRESETS

router = APIRouter(prefix="/api/v1", tags=["style"])


def resource_style_choices(db, uid: uuid.UUID) -> list[dict]:
    """Published platform profiles and the caller's private profiles, never drafts."""
    public = db.scalars(select(WritingResource).where(
        WritingResource.kind == "style", WritingResource.status == "published",
        WritingResource.current_version.is_not(None)).order_by(WritingResource.id)).all()
    personal = db.scalars(select(PersonalWritingResource).where(
        PersonalWritingResource.user_id == uid, PersonalWritingResource.kind == "style",
        PersonalWritingResource.status == "published").order_by(PersonalWritingResource.id)).all()
    choices = []
    for origin, rows in (("platform", public), ("personal", personal)):
        for row in rows:
            document = row.publication if origin == "platform" else {"name": row.name, "body": row.body}
            profile = (document.get("body") or {}).get("profile")
            if not isinstance(profile, dict):
                continue
            # IDs must fit existing short_creation_sessions.style_item_id (48 chars),
            # even for administrator resource IDs up to 160 chars.
            digest = hashlib.sha256((origin + "\0" + row.id).encode()).hexdigest()[:40]
            choices.append({"id": "wr:" + digest, "name": str(document["name"])[:64],
                            "profile": dict(profile), "note": "", "sample_chars": 0,
                            "created_at": None, "builtin": origin == "platform", "removable": False,
                            "origin": origin, "resource_id": row.id})
    return choices


def attach_resource_style(db, project_id: uuid.UUID, uid: uuid.UUID, item_id: str) -> None:
    """Freeze the selected current resource alongside the book's default resources."""
    from myink import writing_resources as svc
    choices = [item for item in resource_style_choices(db, uid) if item['id'] == item_id]
    if len(choices) != 1:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    snapshot = svc.ensure_project_resources(db, project_id, uid)
    selectable = [dict(origin=item['origin'], resource_id=item['resource_id'],
                       personal_override=item.get('personal_override', False),
                       body=item['body'] if item.get('personal_override') else None)
                  for item in snapshot['selections'] if item['kind'] in ('writing_rule', 'expression_rule')]
    choice = choices[0]
    selectable.append(dict(origin=choice['origin'], resource_id=choice['resource_id']))
    svc.set_selection(db, project_id, uid, snapshot['revision'], selectable)


def resolve_style_selection(db, uid: uuid.UUID, item_id: str) -> tuple[dict, str | None, str]:
    """选择器的值 → (style_profile, skill_pack, 展示名)。短篇建书与长篇建书共用这一份。

    `builtin:<preset id>` 是内置预设（id 同时当 skill_pack 标记，与题材包导入同口径）；
    其他按文风库 item id 处理，且**只查自己名下的**——查不到给 404，不区分「不存在」与
    「是别人的」，免得拿 404/403 的差别当探测别人库的手段。
    """
    if item_id.startswith("wr:"):
        matches = [item for item in resource_style_choices(db, uid) if item["id"] == item_id]
        if len(matches) != 1:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        item = matches[0]
        return dict(item["profile"]), None, item["name"]
    if item_id.startswith("builtin:"):
        key = item_id[len("builtin:"):]
        preset = next((p for p in STYLE_PRESETS if p["id"] == key), None)
        if preset is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        return dict(preset["style_profile"]), key, str(preset["name"])
    try:
        target = uuid.UUID(item_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="NOT_FOUND") from None
    item = db.scalar(select(StyleLibraryItem).where(
        StyleLibraryItem.id == target, StyleLibraryItem.user_id == uid))
    if item is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return dict(item.profile), None, item.name
