"""账号级文风库：表形状 + 端点（端点部分在后一个任务补齐）。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete as sa_delete, select

from myink.db import new_session
from myink.models import StyleLibraryItem, User


def test_style_library_item_roundtrip():
    with new_session() as db:
        user = User(username=f"style-{uuid.uuid4().hex[:8]}")
        db.add(user)
        db.commit()
        uid = user.id
    try:
        with new_session() as db:
            item = StyleLibraryItem(user_id=uid, name="渡口冷白描",
                                    profile={"pov": "第三人称限知"}, sample_chars=3200)
            db.add(item)
            db.commit()
            item_id = item.id
        with new_session() as db:
            row = db.scalar(select(StyleLibraryItem).where(StyleLibraryItem.id == item_id))
            assert row is not None
            assert row.name == "渡口冷白描"
            assert row.profile["pov"] == "第三人称限知"
            assert row.sample_chars == 3200
    finally:
        with new_session() as db:
            db.execute(sa_delete(StyleLibraryItem).where(StyleLibraryItem.user_id == uid))
            db.execute(sa_delete(User).where(User.id == uid))
            db.commit()


def test_style_library_has_no_project_id_column():
    """账号级表不能有 project_id 列。

    db.enable_row_level_security() 会给任何带 project_id 的表套 FORCE RLS +
    tenant_isolation 策略；账号级查询没设 app.tenant_id，会被策略静默过滤成空。
    """
    assert "project_id" not in StyleLibraryItem.__table__.columns
