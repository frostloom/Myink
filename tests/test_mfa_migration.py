"""在只回滚的临时 schema 里跑一次第二因子列的补齐（§2.8）：不动真实数据，只验升级本身。

`create_all` 只建新表、不 ALTER 已存在的表。少了这条显式升级，线上老库跑完 `myink init`
也不会有这两列，而登录路径要读它们（`_load_identity` 每次请求都取）——每个请求都会炸在
UnknownColumn 上。这条闸只有在这里能验。
"""

import uuid

import pytest
from sqlalchemy import text

import myink.db as db_module

# 老形状：账号表有认证字段，但没有第二因子的两列。
_LEGACY_USERS = """
    CREATE TABLE users (
        id UUID PRIMARY KEY,
        username VARCHAR(64) NOT NULL,
        password_hash TEXT,
        tier VARCHAR(16) NOT NULL DEFAULT 'normal',
        role VARCHAR(16) NOT NULL DEFAULT 'user',
        auth_version INTEGER NOT NULL DEFAULT 1,
        environment JSON NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
"""


@pytest.fixture
def legacy_users():
    """临时 schema + 只回滚的事务：升级函数原样跑，真库一行都不动。"""
    with db_module.get_admin_engine().connect() as conn:
        transaction = conn.begin()
        schema = "mfa_upgrade_" + uuid.uuid4().hex
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        conn.execute(text(_LEGACY_USERS))
        try:
            yield conn
        finally:
            transaction.rollback()


def _columns(conn) -> dict[str, str]:
    rows = conn.execute(text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'users'"
    )).all()
    return dict(rows)


def test_upgrade_adds_both_second_factor_columns_and_stays_idempotent(legacy_users):
    conn = legacy_users
    assert "totp_secret" not in _columns(conn)

    db_module._upgrade_user_mfa_schema(conn)
    # 幂等：老库会被 init / auth-upgrade 反复跑，第二次必须一字不报。
    db_module._upgrade_user_mfa_schema(conn)

    columns = _columns(conn)
    assert columns["totp_secret"] == "text"
    assert columns["totp_confirmed_at"] == "timestamp with time zone"


def test_upgrade_leaves_existing_accounts_unenrolled(legacy_users):
    """升级只加列：老账号两列都是 NULL = 没开第二因子，登录行为一个字不变。"""
    conn = legacy_users
    conn.execute(
        text("INSERT INTO users (id, username) VALUES (:id, 'demo')"),
        {"id": uuid.UUID(int=1)},
    )

    db_module._upgrade_user_mfa_schema(conn)

    row = conn.execute(text("SELECT totp_secret, totp_confirmed_at FROM users")).one()
    assert tuple(row) == (None, None)