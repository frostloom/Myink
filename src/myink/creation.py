"""Explicit, recoverable book creation lifecycle; proposals are never canon."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from myink.db import new_session
from myink.models import Project
from myink.short.form import SHORT_CHAPTER_MAX, SHORT_CHAPTER_MIN

DRAFT_STATES = {"draft", "setup_confirmed"}


def project_payload(project: Project) -> dict:
    return {"id": str(project.id), "title": project.title, "genre": project.genre,
            "current_chapter": project.current_chapter, "target_words": project.target_words,
            "creation_status": project.creation_status, "form": project.form or "long"}


def save_proposal(project_id: str, patch: dict) -> None:
    # Serialize concurrent setup/outline responses so neither overwrites the other.
    with new_session() as db:
        project = db.scalar(select(Project).where(Project.id == uuid.UUID(project_id)).with_for_update())
        if project is None or project.creation_status not in DRAFT_STATES:
            return
        if project.creation_status == "setup_confirmed":
            patch = {key: value for key, value in patch.items() if key != "setup_draft"}
        project.creation_context = {**(project.creation_context or {}), **patch}
        db.commit()


def validate_creation_outline(payload: dict) -> None:
    """Require meaningful goals and contiguous volume coverage before first write."""
    count = payload.get("chapter_count", 0)
    volumes = payload.get("volumes", [])
    if not str(payload.get("objective", "")).strip() or not volumes or not 50 <= count <= 1000:
        raise HTTPException(status_code=400, detail="OUTLINE_INCOMPLETE")
    next_chapter = 1
    for volume in volumes:
        start, end = volume.get("chapter_start", 0), volume.get("chapter_end", 0)
        if not volume.get("goal", "").strip() or start != next_chapter or end < start or end > count:
            raise HTTPException(status_code=400, detail="OUTLINE_INCOMPLETE")
        next_chapter = end + 1
    if next_chapter != count + 1:
        raise HTTPException(status_code=400, detail="OUTLINE_INCOMPLETE")


def validate_short_outline(payload: dict) -> None:
    """短篇大纲校验：恰好一卷 + 逐章细纲必须齐（SHORT-FORM §5）。

    整体比长篇松得多，但有一条更严：长篇明令「禁止输出逐章 chapters」，短篇则**必须**
    逐章——总共不到 10 章，没有 JSON 爆炸风险，而写手要靠这份逐章方案一次成稿。
    所以缺章、序号不连续、章 goal 为空，都算大纲不完整。
    """
    count = payload.get("chapter_count", 0)
    volumes = payload.get("volumes", [])
    if (not str(payload.get("objective", "")).strip() or not volumes
            or not SHORT_CHAPTER_MIN <= count <= SHORT_CHAPTER_MAX
            or len(volumes) != 1):
        raise HTTPException(status_code=400, detail="OUTLINE_INCOMPLETE")
    volume = volumes[0]
    if (not volume.get("goal", "").strip()
            or volume.get("chapter_start", 0) != 1
            or volume.get("chapter_end", 0) != count):
        raise HTTPException(status_code=400, detail="OUTLINE_INCOMPLETE")
    chapters = volume.get("chapters")
    if not isinstance(chapters, list) or len(chapters) != count:
        raise HTTPException(status_code=400, detail="OUTLINE_INCOMPLETE")
    for seq, chapter in enumerate(chapters, start=1):
        if (not isinstance(chapter, dict) or chapter.get("chapter_seq") != seq
                or not str(chapter.get("goal", "")).strip()):
            raise HTTPException(status_code=400, detail="OUTLINE_INCOMPLETE")
