"""账号级建书产物：用户自命名的文风档案 + 短篇建书会话。

这些表都**不带 `project_id` 列**：`db.enable_row_level_security()` 只给带该列的表加
FORCE RLS + tenant_isolation 策略，而这些数据在建书之前就存在（还没有书），账号级
查询也不设 `app.tenant_id`——一旦带上列，读出来会被策略静默清空。归属一律用 `user_id`
在查询条件里自己把住。
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from myink.models.base import Base, TimestampMixin, UUIDPkMixin


class StyleLibraryItem(Base, UUIDPkMixin, TimestampMixin):
    """用户导入文章提取出来的文风，命名后可复用（长短篇都能在建书时选一次）。

    建书后 `ProjectSettings.style_profile` 是那一刻的副本——改这里不会回头改已建的书，
    这是有意的：文风建书后不可换。
    """

    __tablename__ = "style_library_items"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sample_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
