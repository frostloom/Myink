"""章节编辑 / 记忆校正 / 级联删除（阶段 3 切片：正文轻编辑 + 增量记忆校正）。

- PUT content：只更新正文（版本 +1），不触发任何 LLM / 记忆动作——纯风格编辑默认零动作；
- POST correct-memory：显式校正——对编辑后正文重新 extract → 与该章已落库记忆 diff →
  变更集（新增/删除）进待确认池，人工 confirm/reject 后生效；
- DELETE：级联删除该章及其后全部章节（正文 + 记忆 + 待确认池候选），进度回退到保留最大章。

数据流边界 §6.2：校正的重抽取走编排层（复用节点级 extract 路径），记忆写库仅经确认池
confirm 落库，Agent 不直写。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, func

from aiink.db import tenant_session
from aiink.memory import correction
from aiink.memory.invalidation import invalidate_chapter_memory
from aiink.models import Chapter, MemoryCandidate, Project
from aiink.workflow import nodes

router = APIRouter(prefix="/internal/v1", tags=["chapters"])


class ContentUpdate(BaseModel):
    content: str


def _project_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"项目 id 非法: {raw}") from exc


def _chapter_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"章节 id 非法: {raw}") from exc


@router.put("/projects/{project_id}/chapters/{chapter_id}/content")
def update_chapter_content(project_id: str, chapter_id: str, body: ContentUpdate) -> dict:
    """编辑正文（轻编辑：只写回正文 + 版本递增，不动记忆不耗 LLM）。

    用户改语言风格 / 句子长短 / 标点后直接保存；记忆校正走显式 correct-memory 端点。
    """
    with tenant_session(project_id) as db:
        ch = db.get(Chapter, _chapter_id(chapter_id))
        if ch is None:
            raise HTTPException(status_code=404, detail="章节不存在")
        ch.content = body.content
        ch.version = (ch.version or 1) + 1
    return {"chapter_id": chapter_id, "chapter_seq": ch.chapter_seq,
            "status": ch.status, "version": ch.version}


@router.post("/projects/{project_id}/chapters/{chapter_id}/correct-memory")
def correct_chapter_memory(project_id: str, chapter_id: str) -> dict:
    """显式校正记忆：编辑后正文重新抽取 → 与该章已落库记忆 diff → 变更集进待确认池。

    一次 extract LLM 调用；纯风格编辑 → no_op=True、池零新增。返回变更报告供前端展示，
    变更集的人工确认复用现有 candidates confirm/reject 端点。
    """
    with tenant_session(project_id) as db:
        ch = db.get(Chapter, _chapter_id(chapter_id))
        if ch is None:
            raise HTTPException(status_code=404, detail="章节不存在")
        if not ch.content:
            raise HTTPException(status_code=400, detail="该章无正文，无法校正")
        candidates, err = nodes.extract_candidates_from_draft(
            db, project_id=project_id, chapter_seq=ch.chapter_seq, draft=ch.content,
            task_id=None)
        if err:
            raise HTTPException(status_code=502, detail=f"记忆抽取失败: {err}")
        report = correction.correct_chapter_memory(
            db, project_id=_project_id(project_id), chapter_seq=ch.chapter_seq,
            new_candidates=candidates)
    return report


@router.delete("/projects/{project_id}/chapters/{chapter_id}")
def delete_chapter(project_id: str, chapter_id: str) -> dict:
    """级联删除章节：删除该章及其后全部章节（正文 + 记忆 + 待确认池候选）。

    语义（阶段 3 决策）：中间章删掉后后续章剧情引用已删事件会断层，级联删除让作者
    从被删章重新生成。进度回退到保留的最大章序；无保留章则回 0。
    边界：删除前应确保该范围无进行中的生成/续跑任务（任务 checkpoint 引用章节）。
    """
    with tenant_session(project_id) as db:
        ch = db.get(Chapter, _chapter_id(chapter_id))
        if ch is None:
            raise HTTPException(status_code=404, detail="章节不存在")
        seq = ch.chapter_seq
        rows = (db.query(Chapter).filter(Chapter.chapter_seq >= seq)
                .order_by(Chapter.chapter_seq).all())
        deleted: list[dict] = []
        for c in rows:
            invalidation = invalidate_chapter_memory(db, project_id=uuid.UUID(project_id),
                                                     chapter_seq=c.chapter_seq)
            db.execute(sa_delete(MemoryCandidate).where(
                MemoryCandidate.source_chapter == c.chapter_seq))
            deleted.append({"chapter_seq": c.chapter_seq, "title": c.title,
                            "invalidation": invalidation})
            db.delete(c)
        db.flush()  # autoflush=False：先落删除，max 才反映真实保留集
        proj = db.get(Project, uuid.UUID(project_id))
        remaining = db.query(func.max(Chapter.chapter_seq)).scalar() or 0
        if proj is not None:
            proj.current_chapter = remaining
    return {"deleted": deleted, "current_chapter": remaining}
