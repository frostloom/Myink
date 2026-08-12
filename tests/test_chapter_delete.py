"""级联删除章节（阶段 3：删该章及其后全部正文 + 记忆 + 池候选，进度回退）。

决策（阶段 3 对齐）：中间章删掉后后续章剧情引用已删事件会断层 → 级联删除让作者
从被删章重新生成；Project.current_chapter 回退到保留的最大章序。复用失效原语
invalidate_chapter_memory（facts/states/relations 关窗、events/foreshadows/embeddings 删）。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from aiink.api.routes_chapters import delete_chapter
from aiink.db import tenant_session
from aiink.memory.vector_store import PgvectorStore
from aiink.models import Chapter, EmbeddingRow, Event, MemoryCandidate, Project

ZERO_VEC = [0.0] * 1024


def _seed_chapter(pid: str, seq: int) -> str:
    with tenant_session(pid) as db:
        ch = Chapter(project_id=uuid.UUID(pid), chapter_seq=seq, title=f"第{seq}章",
                     content=f"第{seq}章正文", status="confirmed", generation_source="auto")
        db.add(ch)
        db.commit()
        return str(ch.id)


def _seed_event_with_vec(pid: str, seq: int) -> None:
    with tenant_session(pid) as db:
        ev = Event(project_id=uuid.UUID(pid), summary=f"事件{seq}", source_chapter=seq, confidence=0.9)
        db.add(ev)
        db.flush()
        PgvectorStore().upsert(db, project_id=uuid.UUID(pid), level="event", source_id=ev.id,
                               source_chapter=seq, model_version="bge-m3", embedding=ZERO_VEC)
        db.commit()


def _seed_pool_candidate(pid: str, seq: int) -> None:
    with tenant_session(pid) as db:
        db.add(MemoryCandidate(project_id=uuid.UUID(pid), kind="event", source_chapter=seq,
                               payload={"summary": f"候选{seq}", "participants": []}, confidence=0.8))
        db.commit()


def _set_current_chapter(pid: str, seq: int) -> None:
    with tenant_session(pid) as db:
        proj = db.query(Project).filter(Project.id == uuid.UUID(pid)).first()
        proj.current_chapter = seq
        db.commit()


def test_delete_chapter_cascades_tail_and_memories(temp_project):
    """删 ch4 → ch4/5/6 正文、事件+向量、池候选全删；ch2/3 保留；进度回退到 3。"""
    ids = {seq: _seed_chapter(temp_project, seq) for seq in (2, 3, 4, 5, 6)}
    for seq in (4, 5, 6):
        _seed_event_with_vec(temp_project, seq)
        _seed_pool_candidate(temp_project, seq)
    _set_current_chapter(temp_project, 6)

    result = delete_chapter(temp_project, ids[4])
    assert [d["chapter_seq"] for d in result["deleted"]] == [4, 5, 6]
    assert result["current_chapter"] == 3

    with tenant_session(temp_project) as db:
        remain = [c.chapter_seq for c in db.query(Chapter).order_by(Chapter.chapter_seq).all()]
        assert remain == [2, 3]
        assert db.query(Event).filter(Event.source_chapter.in_([4, 5, 6])).count() == 0
        assert db.query(EmbeddingRow).filter(EmbeddingRow.source_chapter.in_([4, 5, 6])).count() == 0
        assert db.query(MemoryCandidate).filter(MemoryCandidate.source_chapter.in_([4, 5, 6])).count() == 0
        assert db.query(Project).filter(Project.id == uuid.UUID(temp_project)).first().current_chapter == 3


def test_delete_tail_rolls_back_current_chapter(temp_project):
    """删尾部章（无后续）→ 进度回退到保留最大章。"""
    _seed_chapter(temp_project, 2)
    id6 = _seed_chapter(temp_project, 6)
    _seed_chapter(temp_project, 7)
    _set_current_chapter(temp_project, 7)

    result = delete_chapter(temp_project, id6)
    assert [d["chapter_seq"] for d in result["deleted"]] == [6, 7]
    assert result["current_chapter"] == 2


def test_delete_all_chapters_resets_progress(temp_project):
    """删光全部章 → 进度回 0。"""
    id1 = _seed_chapter(temp_project, 1)
    _set_current_chapter(temp_project, 1)
    result = delete_chapter(temp_project, id1)
    assert result["current_chapter"] == 0
    with tenant_session(temp_project) as db:
        assert db.query(Chapter).count() == 0


def test_delete_chapter_missing_404(temp_project):
    try:
        delete_chapter(temp_project, str(uuid.uuid4()))
        raise AssertionError("应 404")
    except HTTPException as exc:
        assert exc.status_code == 404


def test_delete_keeps_earlier_chapter_memories(temp_project):
    """级联只清 [seq, tail]，被删章之前的记忆不受影响（0 误伤）。"""
    _seed_chapter(temp_project, 2)
    _seed_event_with_vec(temp_project, 2)
    id3 = _seed_chapter(temp_project, 3)
    _seed_event_with_vec(temp_project, 3)

    delete_chapter(temp_project, id3)
    with tenant_session(temp_project) as db:
        assert db.query(Event).filter(Event.source_chapter == 2).count() == 1
        assert db.query(EmbeddingRow).filter(EmbeddingRow.source_chapter == 2).count() == 1
