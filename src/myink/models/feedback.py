"""用户问题反馈：问题描述 + 图片/视频佐证，管理端可查看并标记已解决。

与 ``creation.py`` 同属账号级表：**不带 `project_id` 列**。`db.enable_row_level_security()`
只给带该列的表加 FORCE RLS + tenant_isolation 策略，而反馈发生在任何作品之外，查询也不设
`app.tenant_id`——一旦带上列，读出来会被策略静默清空。归属一律用 `user_id` 在查询条件里把住。

附件**字节不落这张表**：文件写在 ``settings.feedback_dir`` 下，这里只留元数据
（原名 / mime / 字节数 / 服务端生成的相对路径），便于列表页免读盘展示。
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from myink.models.base import Base, TimestampMixin, UUIDPkMixin

CATEGORY_IDS = ("bug", "suggestion", "other")
STATUSES = ("open", "resolved")


class Feedback(Base, UUIDPkMixin, TimestampMixin):
    """一条用户反馈。``status`` 只有 open/resolved 两态，够用且不引入工作流。"""

    __tablename__ = "feedback"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="bug")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contact: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # 提交时所在页面与 UA：用户在描述里常常说不清「哪个页面」，这两列替他说。
    page_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    attachments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
