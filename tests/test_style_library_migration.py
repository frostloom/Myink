"""Run the legacy upgrade in a rollback-only schema; never alter the real library."""
import uuid

import pytest
from sqlalchemy import text

import myink.db as db_module


@pytest.fixture
def legacy_library():
    with db_module.get_admin_engine().connect() as conn:
        transaction = conn.begin()
        schema = "style_upgrade_" + uuid.uuid4().hex
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        conn.execute(text("""
            CREATE TABLE style_library_items (
                id UUID PRIMARY KEY, user_id UUID NOT NULL,
                name VARCHAR(64) NOT NULL, profile JSON NOT NULL
            )
        """))
        try:
            yield conn
        finally:
            transaction.rollback()


def test_upgrade_preserves_ids_and_profiles_and_is_idempotent(legacy_library):
    conn = legacy_library
    conn.execute(text("""INSERT INTO style_library_items VALUES
        ('00000000-0000-0000-0000-000000000001',
         '00000000-0000-0000-0000-000000000002', '原有文风', '{"pov":"限知"}')"""))
    db_module._upgrade_style_library_schema(conn)
    db_module._upgrade_style_library_schema(conn)
    row = conn.execute(text("SELECT id, name, profile, note FROM style_library_items")).one()
    assert str(row.id) == "00000000-0000-0000-0000-000000000001"
    assert row.name == "原有文风"
    assert row.profile == {"pov": "限知"}
    assert row.note == ""
    assert conn.scalar(text("""SELECT count(*) FROM pg_constraint
        WHERE conrelid = 'style_library_items'::regclass
        AND conname = 'uq_style_library_user_name' AND contype = 'u'""")) == 1


def test_duplicate_legacy_names_stop_upgrade_without_deleting_or_renaming(legacy_library):
    conn = legacy_library
    for n in (1, 2):
        conn.execute(text("INSERT INTO style_library_items VALUES (:id,:uid,'同名','{}')"),
                     {"id": uuid.UUID(int=n), "uid": uuid.UUID(int=3)})
    with pytest.raises(RuntimeError, match="duplicate"):
        db_module._upgrade_style_library_schema(conn)
    rows = conn.execute(text("SELECT name FROM style_library_items ORDER BY id")).scalars().all()
    assert rows == ["同名", "同名"]


def test_different_users_can_keep_the_same_style_name(legacy_library):
    conn = legacy_library
    for n in (1, 2):
        conn.execute(text("INSERT INTO style_library_items VALUES (:id,:uid,'同名','{}')"),
                     {"id": uuid.UUID(int=n), "uid": uuid.UUID(int=n + 2)})
    db_module._upgrade_style_library_schema(conn)
    assert conn.scalar(text("SELECT count(*) FROM style_library_items")) == 2
