"""在只回滚的临时 schema 里跑一次旧库升级：不动真实数据，只验升级函数本身。

老库那条 `uq_short_creation_sessions_user_id` 是「一账号一条会话」时代的遗留。模型侧
`user_id` 已经不 unique 了，而 create_all 只建新表、不 ALTER 已存在的表——不显式 DROP，
用户想聊第二个短篇就会撞唯一键。这条闸只有在这里能验。
"""
import uuid

import pytest
from sqlalchemy import text

import myink.db as db_module

# 旧形状：user_id 带唯一约束、没有 title 列。INDEX/`updated_at` 照旧有，升级要往上面加复合索引。
_LEGACY_TABLE = """
    CREATE TABLE short_creation_sessions (
        id UUID PRIMARY KEY,
        user_id UUID NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'active',
        card JSON NOT NULL DEFAULT '{}',
        book_id UUID,
        style_item_id VARCHAR(48),
        style_name VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_short_creation_sessions_user_id UNIQUE (user_id)
    )
"""


@pytest.fixture
def legacy_sessions():
    with db_module.get_admin_engine().connect() as conn:
        transaction = conn.begin()
        schema = "creation_upgrade_" + uuid.uuid4().hex
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        conn.execute(text(_LEGACY_TABLE))
        try:
            yield conn
        finally:
            transaction.rollback()


def _constraint_count(conn, name: str) -> int:
    return conn.scalar(text("""SELECT count(*) FROM pg_constraint
        WHERE conrelid = 'short_creation_sessions'::regclass
        AND conname = :name AND contype = 'u'"""), {"name": name})


def test_upgrade_lets_one_account_keep_several_sessions(legacy_sessions):
    """升级的全部意义：去掉那条唯一约束，并且能反复跑不报错。"""
    conn = legacy_sessions
    uid = uuid.UUID(int=1)
    conn.execute(text("INSERT INTO short_creation_sessions (id, user_id, card) "
                      "VALUES (:id, :uid, '{}')"), {"id": uuid.UUID(int=2), "uid": uid})
    # 先确认这条路真的是被堵住的——不然下面那条 INSERT 通了也证明不了什么。
    # 走 savepoint：这条注定要失败的 INSERT 会把事务打成 aborted，不回滚到存档点，
    # 后面每一条 SQL 都会以 InFailedSqlTransaction 收场。
    with pytest.raises(Exception), conn.begin_nested():
        conn.execute(text("INSERT INTO short_creation_sessions (id, user_id, card) "
                          "VALUES (:id, :uid, '{}')"), {"id": uuid.UUID(int=3), "uid": uid})
    assert conn.scalar(text("SELECT count(*) FROM short_creation_sessions")) == 1

    db_module._upgrade_short_creation_sessions(conn)
    db_module._upgrade_short_creation_sessions(conn)          # 幂等：第二遍不能炸
    conn.execute(text("INSERT INTO short_creation_sessions (id, user_id, card) "
                      "VALUES (:id, :uid, '{}')"), {"id": uuid.UUID(int=3), "uid": uid})
    assert conn.scalar(text("SELECT count(*) FROM short_creation_sessions")) == 2
    assert _constraint_count(conn, "uq_short_creation_sessions_user_id") == 0


def test_upgrade_backfills_titles_from_the_card_and_leaves_the_rest_empty(legacy_sessions):
    """存量会话的列表名：卡上有暂定名就用它，没有的留空（读取时再回落第一条用户消息）。

    两条存量会话得挂在**不同**账号下——旧表唯一约束还在，同账号两条根本插不进去。
    """
    conn = legacy_sessions
    conn.execute(text("INSERT INTO short_creation_sessions (id, user_id, card) VALUES "
                      "(:a, :u1, '{\"working_title\":\"最后一班渡船\"}'), (:b, :u2, '{}')"),
                 {"a": uuid.UUID(int=1), "b": uuid.UUID(int=2),
                  "u1": uuid.UUID(int=8), "u2": uuid.UUID(int=9)})
    db_module._upgrade_short_creation_sessions(conn)
    rows = conn.execute(text("SELECT title FROM short_creation_sessions ORDER BY id")).scalars().all()
    assert rows == ["最后一班渡船", ""]
    # 用户自己后改的名字不能被下一遍升级冲掉。
    conn.execute(text("UPDATE short_creation_sessions SET title = '改过的名字' WHERE title = ''"))
    db_module._upgrade_short_creation_sessions(conn)
    rows = conn.execute(text("SELECT title FROM short_creation_sessions ORDER BY id")).scalars().all()
    assert rows == ["最后一班渡船", "改过的名字"]


def test_upgrade_clips_a_long_legacy_title_and_adds_the_list_index(legacy_sessions):
    """title 列是 64 位；回填要跟着截断，否则存量数据一升级就溢出报错。

    索引 (user_id, updated_at) 同时顶住「按账号取会话」与「按最近更新倒序」两个条件。
    """
    conn = legacy_sessions
    conn.execute(text("INSERT INTO short_creation_sessions (id, user_id, card) "
                      "VALUES (:id, :uid, :card)"),
                 {"id": uuid.UUID(int=1), "uid": uuid.UUID(int=9),
                  "card": '{"working_title": "' + "长" * 100 + '"}'})
    db_module._upgrade_short_creation_sessions(conn)
    title = conn.scalar(text("SELECT title FROM short_creation_sessions"))
    assert len(title) == 64
    assert conn.scalar(text("""SELECT count(*) FROM pg_indexes
        WHERE schemaname = current_schema()
        AND indexname = 'ix_short_creation_sessions_user'""")) == 1
