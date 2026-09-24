"""账号级建书产物：用户自命名的文风档案 + 短篇建书会话。

这些表都**不带 `project_id` 列**：`db.enable_row_level_security()` 只给带该列的表加
FORCE RLS + tenant_isolation 策略，而这些数据在建书之前就存在（还没有书），账号级
查询也不设 `app.tenant_id`——一旦带上列，读出来会被策略静默清空。归属一律用 `user_id`
在查询条件里自己把住。
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Float, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from myink.models.base import Base, TimestampMixin, UUIDPkMixin


class StyleLibraryItem(Base, UUIDPkMixin, TimestampMixin):
    """用户导入文章提取出来的文风，命名后可复用（长短篇都能在建书时选一次）。

    建书后 `ProjectSettings.style_profile` 是那一刻的副本——改这里不会回头改已建的书，
    这是有意的：文风建书后不可换。
    """

    __tablename__ = "style_library_items"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_style_library_user_name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sample_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str] = mapped_column(String(200), nullable=False, default="")


class ShortCreationSession(Base, UUIDPkMixin, TimestampMixin):
    """每用户一条建书会话（一期不做多会话）。确认开写后 status='committed'。

    `book_id` 记下已建成的书：commit 重试时复用它，不会建出第二本（也没有 request_id 可依，
    这条会话本身就是幂等键）。不建外键——会话要能在书被删掉之后留档。
    """

    __tablename__ = "short_creation_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    card: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    book_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    style_item_id: Mapped[str | None] = mapped_column(
        String(48), comment="builtin:<preset id> 或 style_library_items.id")
    style_name: Mapped[str | None] = mapped_column(String(64))


class ShortCreationMessage(Base, TimestampMixin):
    """会话消息流。自增 id：对话很短，顺序读即可，不需要 UUID。

    token 与花费逐条记下来，是为了让「这次建书花了多少」在会话里就看得见——
    agent_runs 里也有，但那是给管理面板的；这里的数字是给用户看的。
    """

    __tablename__ = "short_creation_messages"
    __table_args__ = (Index("ix_short_creation_messages_session", "session_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    card: Mapped[dict | None] = mapped_column(JSON)
    model_id: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_est: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error: Mapped[str | None] = mapped_column(String(512))
