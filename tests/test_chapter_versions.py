"""章节历史版本（阶段 4 版本表：覆盖写前快照 → 列表 → 回退）。

语义（models/chapter.py ChapterVersion）：chapters 是「当前版本」，每次覆盖写前把旧状态
快照成历史行；回退 = 快照当前（revert 留痕）→ 覆盖回目标版本 → 版本 +1。
覆盖两条写路径：persist 的 save_chapter（批次/单章生成）与 PUT content 编辑端点。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from aiink.api.routes_chapters import (ContentUpdate, list_chapter_versions,
                                       restore_chapter_version,
                                       update_chapter_content)
from aiink.db import tenant_session
from aiink.memory.repository import save_chapter
from aiink.models import Chapter, ChapterVersion


def _seed(pid: str, seq: int = 1) -> str:
    with tenant_session(pid) as db:
        ch = save_chapter(db, project_id=uuid.UUID(pid), chapter_seq=seq,
                          content="v1 正文", title="第一章")
        db.commit()
        return str(ch.id)


def test_save_chapter_snapshots_previous_versions(temp_project):
    """save_chapter 覆盖写（批次/生成落库）→ 旧版本进版本表，version 单调递增。"""
    cid = _seed(temp_project)
    with tenant_session(temp_project) as db:
        save_chapter(db, project_id=uuid.UUID(temp_project), chapter_seq=1,
                     content="v2 正文", title="第一章", generation_source="batch")
        db.commit()
    with tenant_session(temp_project) as db:
        ch = db.get(Chapter, uuid.UUID(cid))
        assert ch.version == 2 and ch.content == "v2 正文"
        hist = db.query(ChapterVersion).filter(ChapterVersion.chapter_id == ch.id).all()
        assert len(hist) == 1
        assert hist[0].version == 1 and hist[0].content == "v1 正文"
        assert hist[0].reason == "batch"


def test_put_content_snapshots_and_increments(temp_project):
    """PUT content（编辑保存）→ 快照旧正文 + 版本 +1，列表按版本降序返回。"""
    cid = _seed(temp_project)
    for i, body in enumerate(("改标点后正文", "再改一次正文"), start=2):
        resp = update_chapter_content(temp_project, cid, ContentUpdate(content=body))
        assert resp["version"] == i
    result = list_chapter_versions(temp_project, cid)
    assert result["current_version"] == 3
    versions = result["versions"]
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["content"] == "改标点后正文"
    assert versions[1]["content"] == "v1 正文"


def test_restore_rolls_back_content_and_leaves_revert_trace(temp_project):
    """回退到历史版本 → 正文/标题覆盖回目标版，当前再快照（reason=revert），版本 +1。"""
    cid = _seed(temp_project)
    update_chapter_content(temp_project, cid, ContentUpdate(content="v2 正文"))
    update_chapter_content(temp_project, cid, ContentUpdate(content="v3 正文"))

    resp = restore_chapter_version(temp_project, cid, 2)
    assert resp["version"] == 4
    with tenant_session(temp_project) as db:
        ch = db.get(Chapter, uuid.UUID(cid))
        assert ch.content == "v2 正文" and ch.version == 4
        top = (db.query(ChapterVersion).filter(ChapterVersion.chapter_id == ch.id)
               .order_by(ChapterVersion.version.desc()).first())
        assert top.version == 3 and top.content == "v3 正文" and top.reason == "revert"


def test_versions_missing_chapter_or_version_404(temp_project):
    with pytest.raises(HTTPException) as e1:
        list_chapter_versions(temp_project, str(uuid.uuid4()))
    assert e1.value.status_code == 404

    cid = _seed(temp_project)
    with pytest.raises(HTTPException) as e2:
        restore_chapter_version(temp_project, cid, 99)
    assert e2.value.status_code == 404


def test_delete_chapter_cascades_versions(temp_project):
    """级联删章 → 版本历史随章节 FK 级联清除（不回留下孤儿历史）。"""
    cid = _seed(temp_project)
    update_chapter_content(temp_project, cid, ContentUpdate(content="v2"))
    from aiink.api.routes_chapters import delete_chapter
    delete_chapter(temp_project, cid)
    with tenant_session(temp_project) as db:
        assert db.query(ChapterVersion).filter(
            ChapterVersion.chapter_id == uuid.UUID(cid)).count() == 0
