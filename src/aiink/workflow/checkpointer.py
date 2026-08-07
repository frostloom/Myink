"""PG Checkpointer（§6.7：开发与生产统一 PostgreSQL，不用 SQLite/Redis）。

- 持久化分级（生产标准，plan §6.7/§5.3）：checkpoint 是任务现场，丢了用户从头重跑，
  必须落有备份/PITR 的 PG；Redis 只管可重建数据；
- checkpointer 表（checkpoints/checkpoint_blobs/checkpoint_writes）是 LangGraph 内部表，
  不带 project_id/RLS——靠 task_id（thread_id）归属校验，不属于业务租户表（§14 隔离清单）。
"""

from __future__ import annotations

import logging

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row

from aiink.config import settings

logger = logging.getLogger(__name__)

_build: dict[str, PostgresSaver] = {}

# 复用 psycopg3 连接串（去掉 SQLAlchemy 方言前缀）
_CONN_STR = settings.database_url.replace("postgresql+psycopg://", "postgresql://")


def build_checkpointer() -> PostgresSaver:
    """构建并初始化 PG Checkpointer（幂等：setup() 建内部表）。

    langgraph-checkpoint-postgres 新版的 `from_conn_string` 是上下文管理器
    （进入即占连接、退出即关闭），不适合进程级缓存的长期 saver。这里复刻其
    内部行为：autocommit + prepare_threshold=0 + dict_row，连接随进程存活。
    checkpointer 连接是 psycopg 直连，与 SQLAlchemy 双引擎完全分离（§6.7）。
    """
    if "saver" in _build:
        return _build["saver"]
    conn: Connection = Connection.connect(
        _CONN_STR, autocommit=True, prepare_threshold=0, row_factory=dict_row
    )
    saver = PostgresSaver(conn)
    saver.setup()  # 建 checkpoints / checkpoint_blobs / checkpoint_writes
    _build["saver"] = saver
    return saver
