"""账号级文风库：导入文章 → 提取文风 → 命名保存 → 建书时选一次。

与项目上的 `/projects/{pid}/style-samples` 的分工：那条是「给这本书导一份参考文风」，
这条是「把文风留成我自己的资产」，后者不依赖任何作品，所以走 make_user_chain 记账。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from myink.api.auth import require_user
from myink.api.schemas import (OkOut, StyleDraftOut, StyleLibraryItemOut, StyleLibraryOut,
                               StyleLibraryPatchBody, StyleLibrarySaveBody, StyleSampleBody)
from myink.db import new_session
from myink.models import StyleLibraryItem
from myink.seed import STYLE_PRESETS
from myink.style_extract import (analyze_sample_stats, clean_samples, extract_style_profile,
                                 merge_style_draft, validate_profile)

router = APIRouter(prefix="/api/v1/style-library", tags=["style-library"])


def _builtin_out(preset: dict) -> dict:
    """内置预设 → 与用户项同形的只读行。id 带 `builtin:` 前缀，建书时原样回传即可。"""
    return {"id": f"builtin:{preset['id']}", "name": preset["name"],
            "profile": preset["style_profile"], "note": "", "sample_chars": 0,
            "created_at": None, "builtin": True, "removable": False}


def _item_out(item: StyleLibraryItem) -> dict:
    return {"id": str(item.id), "name": item.name, "profile": item.profile,
            "note": item.note or "", "sample_chars": item.sample_chars,
            "created_at": item.created_at, "builtin": False, "removable": True}


@router.get("", response_model=StyleLibraryOut)
def list_items(user_id: str = Depends(require_user)) -> dict:
    """内置 4 个在前、用户项在后：一次请求喂满选择器，前端不再自备一份内置清单。"""
    with new_session() as db:
        mine = db.scalars(select(StyleLibraryItem)
                          .where(StyleLibraryItem.user_id == uuid.UUID(user_id))
                          .order_by(StyleLibraryItem.created_at.desc(), StyleLibraryItem.id)).all()
        return {"items": [_builtin_out(p) for p in STYLE_PRESETS] + [_item_out(i) for i in mine]}


@router.post("/samples", response_model=StyleDraftOut)
def extract_samples(body: StyleSampleBody, user_id: str = Depends(require_user)) -> dict:
    """导入的文章 → 一份可编辑的文风草稿（不落库，用户看过、改了名再保存）。"""
    try:
        samples = clean_samples(body.samples)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    uid = uuid.UUID(user_id)
    stats = analyze_sample_stats(samples)
    db = new_session()
    try:
        profile, extract_error = extract_style_profile(samples, stats, user_id=uid, db=db)
        db.commit()
    finally:
        db.close()
    return {"draft": merge_style_draft(stats, profile, extract_error=extract_error)}


@router.post("", response_model=StyleLibraryItemOut)
def save_item(body: StyleLibrarySaveBody, user_id: str = Depends(require_user)) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="文风名不能为空")
    try:
        profile = validate_profile(body.profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    uid = uuid.UUID(user_id)
    with new_session() as db:
        # 表上有 (user_id, name) 唯一约束：不显式挡，重名就是一个 500。
        taken = db.scalar(select(StyleLibraryItem.id).where(
            StyleLibraryItem.user_id == uid, StyleLibraryItem.name == name))
        if taken is not None:
            raise HTTPException(status_code=409, detail="NAME_TAKEN")
        item = StyleLibraryItem(user_id=uid, name=name, profile=profile,
                                note=body.note.strip(), sample_chars=body.sample_chars)
        db.add(item)
        db.commit()
        return _item_out(item)


@router.patch("/{item_id}", response_model=StyleLibraryItemOut)
def patch_item(item_id: str, body: StyleLibraryPatchBody,
               user_id: str = Depends(require_user)) -> dict:
    """改名 / 改备注：只动传了的字段，档案与样本统计不重算。"""
    uid = uuid.UUID(user_id)
    try:
        target = uuid.UUID(item_id)
    except (ValueError, TypeError):
        # "builtin:xxx" 也走这条 —— 内置预设改不得，给 404 而不是 500。
        raise HTTPException(status_code=404, detail="NOT_FOUND") from None
    name = body.name.strip() if body.name is not None else None
    if name is not None and not name:
        raise HTTPException(status_code=400, detail="文风名不能为空")
    with new_session() as db:
        item = db.scalar(select(StyleLibraryItem).where(
            StyleLibraryItem.id == target, StyleLibraryItem.user_id == uid))
        if item is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        if name is not None and name != item.name:
            taken = db.scalar(select(StyleLibraryItem.id).where(
                StyleLibraryItem.user_id == uid, StyleLibraryItem.name == name,
                StyleLibraryItem.id != target))
            if taken is not None:
                raise HTTPException(status_code=409, detail="NAME_TAKEN")
            item.name = name
        if body.note is not None:
            item.note = body.note.strip()
        db.commit()
        return _item_out(item)


@router.delete("/{item_id}", response_model=OkOut)
def delete_item(item_id: str, user_id: str = Depends(require_user)) -> dict:
    uid = uuid.UUID(user_id)
    try:
        target = uuid.UUID(item_id)
    except (ValueError, TypeError):
        # "builtin:xxx" 也走这条 —— 内置预设删不得，给 404 而不是 500。
        raise HTTPException(status_code=404, detail="NOT_FOUND") from None
    with new_session() as db:
        item = db.scalar(select(StyleLibraryItem).where(
            StyleLibraryItem.id == target, StyleLibraryItem.user_id == uid))
        if item is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        db.delete(item)
        db.commit()
    return {"ok": True}
