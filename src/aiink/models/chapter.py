"""章节与大纲模型（§11.1）。"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aiink.models.base import Base, TimestampMixin, UUIDPkMixin

CHAPTER_STATUSES = ("planning", "writing", "awaiting_review", "confirmed", "failed", "cancelled")


class Chapter(Base, UUIDPkMixin, TimestampMixin):
    """章节正文与状态。"""

    __tablename__ = "chapters"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chapter_seq: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, comment="章节摘要")
    status: Mapped[str] = mapped_column(String(16), default="planning", nullable=False)
    generation_source: Mapped[str | None] = mapped_column(String(32), comment="manual/batch/revise")
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class VolumeOutline(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "volume_outlines"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    volume_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    outline: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False, comment="卷纲内容")


class ChapterOutline(Base, UUIDPkMixin, TimestampMixin):
    """章节计划（§6.4 ChapterPlan 结构化对象，含预期事件 → 大纲偏差比对输入）。"""

    __tablename__ = "chapter_outlines"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chapter_seq: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    plan: Mapped[dict] = mapped_column(JSON, nullable=False, comment="ChapterPlan 对象体")
