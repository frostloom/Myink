"""在只回滚的临时 schema 里跑一次老库升级：不动真实数据，只验升级函数本身。

`create_all` 只建新表、不 ALTER 已存在的表，所以线上那 6 个存量账号的 `users` 表不会自己
长出 `platform_short_used` / `platform_long_used`。少了这两列，**每一次**建书或开写短篇都会
在 `with_for_update()` 之后撞 UndefinedColumn 而 500——不是「免费额度不生效」那么轻。
"""

import uuid

import pytest
from sqlalchemy import text

import myink.db as db_module

# 旧形状：只有 id / username，没有任何平台额度列。
_LEGACY_USERS = """
    CREATE TABLE users (
        id UUID PRIMARY KEY,
        username VARCHAR(64) NOT NULL
    )
"""


@pytest.fixture
def legacy_users():
    with db_module.get_admin_engine().connect() as conn:
        transaction = conn.begin()
        schema = "platform_upgrade_" + uuid.uuid4().hex
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        conn.execute(text(_LEGACY_USERS))
        try:
            yield conn
        finally:
            transaction.rollback()


def _columns(conn) -> dict[str, tuple[str, str]]:
    rows = conn.execute(text("""SELECT column_name, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'users'
          AND column_name LIKE 'platform%'""")).all()
    return {name: (nullable, default) for name, nullable, default in rows}


def test_upgrade_adds_both_counters_as_zero_and_is_idempotent(legacy_users):
    """两列都补上、存量账号一律 0、连跑两遍不炸（`IF NOT EXISTS` 的意义）。"""
    conn = legacy_users
    uid = uuid.UUID(int=1)
    conn.execute(text("INSERT INTO users (id, username) VALUES (:id, 'zlx')"), {"id": uid})

    db_module._upgrade_platform_quota(conn)
    db_module._upgrade_platform_quota(conn)          # 幂等：第二遍不能炸

    assert _columns(conn) == {"platform_short_used": ("NO", "0"),
                              "platform_long_used": ("NO", "0")}
    # 存量账号吃到的是默认值 0——不是 NULL，否则「已用 >= 额度」的判据会静默失效。
    assert conn.execute(text("SELECT platform_short_used, platform_long_used FROM users WHERE id = :id"),
                        {"id": uid}).one() == (0, 0)


def test_upgrade_keeps_existing_usage(legacy_users):
    """升级不改动已经用掉的那部分（重跑迁移不该把额度退回给用户）。"""
    conn = legacy_users
    uid = uuid.UUID(int=2)
    conn.execute(text("INSERT INTO users (id, username) VALUES (:id, 'chy')"), {"id": uid})
    db_module._upgrade_platform_quota(conn)
    conn.execute(text("UPDATE users SET platform_long_used = 3 WHERE id = :id"), {"id": uid})
    db_module._upgrade_platform_quota(conn)
    assert conn.scalar(text("SELECT platform_long_used FROM users WHERE id = :id"), {"id": uid}) == 3


def test_the_counters_are_writable_after_the_upgrade(legacy_users):
    """升级完这两列要是可写的（NOT NULL 且没有别的约束挡着扣减）。"""
    conn = legacy_users
    db_module._upgrade_platform_quota(conn)
    conn.execute(text("INSERT INTO users (id, username, platform_short_used) VALUES "
                      "(:id, 'new', 1)"), {"id": uuid.UUID(int=3)})
    assert conn.scalar(text("SELECT platform_short_used FROM users WHERE username = 'new'")) == 1