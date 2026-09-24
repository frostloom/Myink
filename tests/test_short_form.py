"""短篇形态（SHORT-FORM）单测。

Phase 1：`Project.form` 字段与「章数 × 每章字数」联合约束。
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import text

import myink.db as db_module
from myink.models.project import Project
from myink.short.form import (
    SHORT_CHAPTER_MAX,
    SHORT_CHAPTER_MIN,
    SHORT_CHARS_MAX,
    SHORT_CHARS_MIN,
    SHORT_TOTAL_MAX,
    resolve_short_lengths,
)


class _ExistingConnectionEngine:
    """Expose Engine.begin() without committing the test's outer transaction."""

    def __init__(self, connection):
        self._connection = connection

    @contextmanager
    def begin(self):
        yield self._connection


def test_new_project_declares_long_form_default():
    """不指定形态即长篇：短篇是显式选择，存量调用点不会因为多了一列而改变语义。

    列 default / server_default 都在 INSERT 时才生效（刚构造的实例上还是 None），
    所以这里钉的是声明本身：新行走 default，ALTER 时已存在的行走 server_default。
    """
    col = Project.__table__.c.form
    assert col.default.arg == "long"
    assert col.server_default.arg == "long"
    assert col.nullable is False


def test_ensure_project_form_is_idempotent_and_backfills_legacy_books(monkeypatch):
    """老库的 projects 表没有 form 列，create_all 不会补；补列后存量书必须落为 long。

    存量书全是长篇（短篇功能此前不存在），所以默认值不是「随便挑的宽松值」而是
    正确语义：server_default 让 alter 时已有的行直接变成 long。
    """
    schema = f"short_form_{uuid.uuid4().hex}"
    legacy_id = uuid.uuid4()
    engine = db_module.get_admin_engine()

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(text("""
                CREATE TABLE projects (
                    id UUID PRIMARY KEY,
                    title TEXT NOT NULL
                )
            """))
            connection.execute(
                text("INSERT INTO projects (id, title) VALUES (:id, '遗留长篇')"),
                {"id": legacy_id},
            )

            monkeypatch.setattr(
                db_module, "get_admin_engine", lambda: _ExistingConnectionEngine(connection),
            )

            db_module.ensure_project_form()
            assert connection.execute(text(
                "SELECT form FROM projects WHERE id = :id"
            ), {"id": legacy_id}).scalar_one() == "long"

            db_module.ensure_project_form()
            assert connection.execute(text("SELECT count(*) FROM projects")).scalar_one() == 1
        finally:
            transaction.rollback()


# ---------- Phase 1.2：章数 × 每章字数的联合约束 ----------


def test_short_form_constants_match_the_spec():
    assert (SHORT_CHAPTER_MIN, SHORT_CHAPTER_MAX) == (1, 10)
    assert (SHORT_CHARS_MIN, SHORT_CHARS_MAX) == (1000, 8000)
    assert SHORT_TOTAL_MAX == 20000


@pytest.mark.parametrize("chapters,chars,expected", [
    # 决策文档 §5 的表：章数少则每章长，总量卡在 2 万
    (1, 8000, (1, 8000, False)),
    (2, 8000, (2, 8000, False)),
    (5, 4000, (5, 4000, False)),
    (10, 2000, (10, 2000, False)),
    # 决策文档点名的两个边界：总量超限按比例压；未超限就不动
    (10, 8000, (10, 2000, True)),
    (1, 5000, (1, 5000, False)),
])
def test_resolve_short_lengths_follows_the_parameter_table(chapters, chars, expected):
    """超限是「按比例压每章字数并告知」，不是拒绝——所以第三个返回值是「压过」标记。"""
    assert resolve_short_lengths(chapters, chars) == expected


@pytest.mark.parametrize("chapters,chars,expected", [
    (0, 2000, (1, 2000, False)),      # 章数下限：夹到 1
    (99, 1000, (10, 1000, False)),    # 章数上限：夹到 10
    (5, 200, (5, 1000, False)),       # 每章下限：1000 以下写不出完整场面
    (5, 99999, (5, 4000, True)),      # 每章上限先夹到 8000，再因总量超限压到 4000
])
def test_resolve_short_lengths_clamps_to_the_declared_ranges(chapters, chars, expected):
    assert resolve_short_lengths(chapters, chars) == expected