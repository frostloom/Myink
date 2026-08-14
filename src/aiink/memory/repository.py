"""记忆读写辅助（阶段 1 最小集）。

数据流边界（§6.2）：Agent 不直接写库——写经 extract 出候选，persist（编排层）
确认或自动放行后落库。本模块只被确定性节点（recall / persist / load_state）使用。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiink.models import (
    Chapter,
    ChapterOutline,
    ChapterVersion,
    Character,
    CharacterState,
    Event,
    Fact,
    Foreshadow,
    PlotThread,
    Project,
    ProjectSettings,
    Relation,
    VolumeOutline,
    WritingLesson,
)


# ---- 读 ----

def get_project(session: Session, project_id: uuid.UUID) -> Project | None:
    return session.get(Project, project_id)


def get_settings(session: Session, project_id: uuid.UUID) -> ProjectSettings | None:
    return session.execute(
        select(ProjectSettings).where(ProjectSettings.project_id == project_id)
    ).scalar_one_or_none()


def get_character(session: Session, project_id: uuid.UUID, name: str) -> Character | None:
    return session.execute(
        select(Character).where(Character.project_id == project_id, Character.name == name)
    ).scalar_one_or_none()


def get_all_characters(session: Session, project_id: uuid.UUID) -> list[Character]:
    return list(session.execute(
        select(Character).where(Character.project_id == project_id).order_by(Character.name)
    ).scalars())


def get_hard_facts(session: Session, project_id: uuid.UUID, chapter_seq: int | None = None) -> list[Fact]:
    """硬约束恒在 Top-K（§7.2）+ 当前有效普通事实。"""
    q = select(Fact).where(Fact.project_id == project_id, Fact.confirm_status == "confirmed")
    if chapter_seq is not None:
        q = q.where(
            (Fact.is_hard.is_(True)) | (Fact.valid_from <= chapter_seq) & (Fact.valid_to.is_(None))
        )
    else:
        q = q.where((Fact.is_hard.is_(True)) | (Fact.valid_to.is_(None)))
    return list(session.execute(q.order_by(Fact.is_hard.desc(), Fact.created_at.desc()).limit(100)).scalars())


def get_recent_events(session: Session, project_id: uuid.UUID, limit: int = 20) -> list[Event]:
    return list(session.execute(
        select(Event).where(Event.project_id == project_id)
        .order_by(Event.source_chapter.desc()).limit(limit)
    ).scalars())


def get_character_state(session: Session, project_id: uuid.UUID, character_id: uuid.UUID,
                        chapter_seq: int) -> dict[str, str]:
    """人物状态台账当前值：按 chapter_seq 最近一条有效记录物化（§7.7）。

    valid_to IS NULL 过滤已失效状态（§7.3 章节重写后旧状态 valid_to 关闭，不再计入）；
    valid_from <= chapter_seq 与 get_hard_facts 时间窗口径对齐（§7.7 时序快照语义）。
    """
    rows = session.execute(
        select(CharacterState).where(
            CharacterState.project_id == project_id,
            CharacterState.character_id == character_id,
            CharacterState.chapter_seq <= chapter_seq,
            CharacterState.valid_from <= chapter_seq,
            CharacterState.valid_to.is_(None),
        ).order_by(CharacterState.chapter_seq.desc())
    ).scalars().all()
    state: dict[str, str] = {}
    for r in rows:  # 同一 field 只取最近一条
        if r.field not in state:
            state[r.field] = r.new_value or ""
    return state


def get_relations(session: Session, project_id: uuid.UUID, entity_ids: list[uuid.UUID] | None = None) -> list[Relation]:
    q = select(Relation).where(Relation.project_id == project_id, Relation.valid_to.is_(None))
    if entity_ids:
        q = q.where(Relation.source_id.in_(entity_ids) | Relation.target_id.in_(entity_ids))
    return list(session.execute(q).scalars())


def get_relation_current_type(session: Session, project_id: uuid.UUID,
                              source_id: uuid.UUID, target_id: uuid.UUID) -> str | None:
    """有序对当前关系类型（§7.8 当前关系 = 最新 valid_to IS NULL）。

    L2 正文-台账语义比对（§8.6）的台账侧取值：0 或 >1 条活跃行（无记录 /
    存量重复/矛盾）→ None，歧义交 L1 relation_ledger_check 兜底，不在此吞掉。
    """
    rows = session.execute(
        select(Relation).where(
            Relation.project_id == project_id,
            Relation.source_id == source_id,
            Relation.target_id == target_id,
            Relation.valid_to.is_(None),
        )
    ).scalars().all()
    if len(rows) != 1:
        return None
    return rows[0].relation_type


def get_open_foreshadows(session: Session, project_id: uuid.UUID) -> list[Foreshadow]:
    return list(session.execute(
        select(Foreshadow).where(Foreshadow.project_id == project_id, Foreshadow.status.in_(["planted", "developing"]))
    ).scalars())


def get_plot_threads(session: Session, project_id: uuid.UUID) -> list[PlotThread]:
    return list(session.execute(
        select(PlotThread).where(PlotThread.project_id == project_id, PlotThread.status == "active")
    ).scalars())


def get_active_lessons(session: Session, project_id: uuid.UUID) -> list[WritingLesson]:
    """在效写作经验（reflexion 注入用，§8.9）：复发数降序、最近优先，cap 在 recall 层。"""
    return list(session.execute(
        select(WritingLesson)
        .where(WritingLesson.project_id == project_id, WritingLesson.status == "active")
        .order_by(WritingLesson.recurrence_count.desc(), WritingLesson.created_at.desc())
    ).scalars())


def get_chapter(session: Session, project_id: uuid.UUID, chapter_seq: int) -> Chapter | None:
    return session.execute(
        select(Chapter).where(Chapter.project_id == project_id, Chapter.chapter_seq == chapter_seq)
    ).scalar_one_or_none()


def get_latest_chapter(session: Session, project_id: uuid.UUID) -> Chapter | None:
    return session.execute(
        select(Chapter).where(Chapter.project_id == project_id)
        .order_by(Chapter.chapter_seq.desc()).limit(1)
    ).scalar_one_or_none()


def get_chapter_outline(session: Session, project_id: uuid.UUID, chapter_seq: int) -> ChapterOutline | None:
    return session.execute(
        select(ChapterOutline).where(ChapterOutline.project_id == project_id, ChapterOutline.chapter_seq == chapter_seq)
    ).scalar_one_or_none()


def get_volume_outline(session: Session, project_id: uuid.UUID, volume_seq: int) -> VolumeOutline | None:
    return session.execute(
        select(VolumeOutline).where(VolumeOutline.project_id == project_id, VolumeOutline.volume_seq == volume_seq)
    ).scalar_one_or_none()


# ---- 写（仅 persist / 编排层调用，§6.2 数据流边界）----

def snapshot_chapter(session: Session, chapter: Chapter, reason: str = "edit") -> None:
    """覆盖写前快照：把 chapter 当前状态写入 chapter_versions（阶段 4 版本表）。

    版本表语义：chapters 是「当前版本」，每次写前把旧状态留痕成历史行（含当时版本号），
    回退/审计据此恢复。仅对已存在章节（有 id）调用——新建章无旧状态可快照。
    """
    if chapter is None or chapter.id is None:
        return
    session.add(ChapterVersion(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        version=chapter.version or 1,
        title=chapter.title,
        content=chapter.content,
        summary=chapter.summary,
        reason=reason,
    ))


def save_chapter(session: Session, *, project_id: uuid.UUID, chapter_seq: int, content: str,
                 summary: str | None = None, title: str | None = None,
                 generation_source: str = "manual") -> Chapter:
    chapter = get_chapter(session, project_id, chapter_seq)
    if chapter is None:
        chapter = Chapter(project_id=project_id, chapter_seq=chapter_seq, status="confirmed", version=1)
        session.add(chapter)
    else:
        snapshot_chapter(session, chapter, reason=generation_source or "edit")  # 版本表快照旧状态
        chapter.version = (chapter.version or 0) + 1
    chapter.content = content
    chapter.summary = summary
    chapter.title = title
    chapter.status = "confirmed"
    chapter.generation_source = generation_source
    return chapter
