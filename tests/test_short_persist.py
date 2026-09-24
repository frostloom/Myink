"""短篇落库（SHORT-FORM-PLAN Phase 5）。

复用 `repo.save_chapter`，所以落库形状就是仓库既有的那套版本语义：**`chapters` 行是当前
版本**（`version` 实时计数），`chapter_versions` 每行是历史快照（每次覆盖写前把旧状态留痕）。
于是：

- 首稿落库 = 5 行 v1——**此刻版本表是空的**，当前版本不在历史里；
- 改稿落库 = 同一批行整批升到 v2，版本表拿到 5 行 v1。

「短篇的版本语义是整篇版本」由此成立：整篇 v2 = 逐章读 `chapters`，整篇 v1 = 逐章读版本表。
不需要新表，也不与长篇的章节历史语义打架——`routes_chapters` 的版本列表与回退端点都建立在
「当前版在 chapters、历史在版本表」之上。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from myink.db import tenant_session
from myink.models import (Chapter, ChapterVersion, MemoryCandidate, Message,
                          Project)
from myink.workflow.short_runner import persist_short_story

CHAPTERS = 5


def _result(tag: str = "", chapter_count: int = CHAPTERS, skip: tuple[int, ...] = (),
            error: str | None = None) -> dict:
    """`run_short_story` 的返回值形状（契约由 tests/test_short_runner.py 钉住）。

    error 非空 = 整篇没成，此时 chapters 为空（成稿就没回来，没有可分块的东西）。
    """
    body = [] if error else [
        {"chapter_seq": i, "title": f"渡口之夜 {i}", "body": f"第 {i} 章正文{tag}。"}
        for i in range(1, chapter_count + 1) if i not in skip]
    return {
        "chapters": body,
        "empty_chapters": list(skip), "length_findings": [],
        "review": {"verdict": "pass", "issues": [], "suggestions": []},
        "warning": None, "error": error,
    }


@pytest.fixture
def short_book(temp_project):
    with tenant_session(temp_project) as db:
        db.get(Project, uuid.UUID(temp_project)).form = "short"
        db.commit()
    return temp_project


def _persist(project_id: str, result: dict) -> int:
    return persist_short_story(project_id=project_id, result=result)


def _chapters(project_id: str) -> list[Chapter]:
    with tenant_session(project_id) as db:
        return list(db.scalars(select(Chapter)
                               .where(Chapter.project_id == uuid.UUID(project_id))
                               .order_by(Chapter.chapter_seq)))


def _versions(project_id: str) -> list[ChapterVersion]:
    """历史版本按章序排列——版本表只有 chapter_id，章序要回 `chapters` 取。"""
    pid = uuid.UUID(project_id)
    with tenant_session(project_id) as db:
        seqs = {c.id: c.chapter_seq for c in db.scalars(
            select(Chapter).where(Chapter.project_id == pid))}
        versions = list(db.scalars(
            select(ChapterVersion).where(ChapterVersion.project_id == pid)))
    return sorted(versions, key=lambda v: (seqs.get(v.chapter_id, 0), v.version))


def _progress(project_id: str) -> int:
    with tenant_session(project_id) as db:
        return db.get(Project, uuid.UUID(project_id)).current_chapter


# ---------- 首稿 ----------


def test_a_five_chapter_draft_lands_as_five_confirmed_rows(short_book):
    """成稿按块拆章落库：章表 5 行，逐章 status=confirmed、带标题、进度推到 N。"""
    written = _persist(short_book, _result())

    assert written == CHAPTERS
    rows = _chapters(short_book)
    assert [c.chapter_seq for c in rows] == [1, 2, 3, 4, 5]
    assert [c.title for c in rows] == [f"渡口之夜 {i}" for i in range(1, 6)]
    assert all(c.status == "confirmed" for c in rows)
    assert all(c.version == 1 for c in rows)
    assert all(c.generation_source == "auto" for c in rows), "机器写的，与长篇正文同档"
    assert rows[2].content == "第 3 章正文。"
    assert _progress(short_book) == CHAPTERS, "展示口径是「已写至第 N 章」"


def test_the_current_versions_are_not_history_rows(short_book):
    """首稿落库后版本表是空的：`chapters` 装当前版，版本表只装被覆盖掉的旧版。

    计划的「版本表 5 行」是它自己的一句算术（把 v1 也当历史行），与它同时点名的
    「复用 repo.save_chapter」冲突——仓库语义是当前版不进历史。见 ledger 的 Ruling。
    """
    _persist(short_book, _result())

    assert _versions(short_book) == []
    assert all(c.content for c in _chapters(short_book)), "首稿本身仍可逐章读回"


def test_the_short_form_writes_no_summary_and_no_confirmation_pool(short_book):
    """短篇没有摘要、没有对话表、没有待确认池（决策文档 §三 的分界）。"""
    _persist(short_book, _result())

    assert all(c.summary is None for c in _chapters(short_book))
    with tenant_session(short_book) as db:
        assert db.query(MemoryCandidate).filter_by(project_id=uuid.UUID(short_book)).count() == 0
        assert db.query(Message).filter_by(project_id=uuid.UUID(short_book)).count() == 0


# ---------- 改稿 ----------


def test_the_rewrite_lands_as_a_second_whole_work_version(short_book):
    """再写一次 → 整批 v2：章表是改稿，版本表拿到 5 行 v1（首稿）。

    「整篇 v2 = 逐章取 v2、整篇 v1 = 逐章取版本表」——回退端点据此可用。
    """
    _persist(short_book, _result(tag="-初稿"))
    _persist(short_book, _result(tag="-改稿"))

    rows = _chapters(short_book)
    assert len(rows) == CHAPTERS
    assert all(c.version == 2 for c in rows)
    assert [c.content for c in rows] == [f"第 {i} 章正文-改稿。" for i in range(1, 6)]

    history = _versions(short_book)
    assert len(history) == CHAPTERS
    assert all(v.version == 1 for v in history)
    assert [v.content for v in history] == [f"第 {i} 章正文-初稿。" for i in range(1, 6)], \
        "版本表逐章存着首稿，整篇 v1 拼得回来"
    assert {v.reason for v in history} == {"auto"}
    assert _progress(short_book) == CHAPTERS


# ---------- 边界 ----------


def test_only_the_chapters_that_have_a_body_land(short_book):
    """空章不落库：不写「标题有了、正文是空」的 confirmed 行。

    空章的正文**哪都没有**（模型没写、补写也没成），落一行空的只会在章节列表里显示成一个
    坏掉的白章；用户在界面上能做的唯一事情是重写那一章，而入口是重跑，不是编辑一个空框。
    进度跟着最后落库的那一章走——与删章端点同口径（`current_chapter = 保留的最大章序`）。
    """
    written = _persist(short_book, _result(skip=(5,)))

    assert written == 4
    assert [c.chapter_seq for c in _chapters(short_book)] == [1, 2, 3, 4]
    assert _progress(short_book) == 4


def test_a_failed_run_persists_nothing(short_book):
    """成稿就没回来（error）→ 一行都不写，进度不动。"""
    written = _persist(short_book, _result(error="provider down"))

    assert written == 0
    assert _chapters(short_book) == []
    assert _progress(short_book) == 0