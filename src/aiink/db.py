"""数据库访问层。

多租户隔离核心（plan.md §14.1）：
- RLS 主强制：所有业务表 FORCE ROW LEVEL SECURITY，策略读 `current_setting('app.tenant_id')`；
- 连接级上下文：`SET LOCAL app.tenant_id = :id` 只在当前事务生效，事务结束自动恢复，
  连接池复用时不泄漏上一位用户的租户（坑 1：连接池污染）；
- fail closed：未设置租户则 RLS 策略返回空集，任何查询空结果，不返回他人数据。
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from aiink.config import settings

# 生产用连接池配置（plan.md §5.2 真实边界：连接池）。
# pool_size * 并发 worker < PG max_connections(默认 100)。
_engine: Engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=5,
    pool_pre_ping=True,  # 回收失效连接
)

# 超级用户 DDL 连接（仅 init/迁移/RLS，业务不碰；超级用户永远绕过 RLS，不能用于业务）
_admin_engine: Engine = create_engine(settings.admin_database_url, pool_pre_ping=True)

_SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)


def get_engine() -> Engine:
    return _engine


def get_admin_engine() -> Engine:
    return _admin_engine


def session_factory() -> sessionmaker[Session]:
    return _SessionLocal


def new_session() -> Session:
    return _SessionLocal()


@contextmanager
def tenant_session(tenant_id: str | uuid.UUID) -> Iterator[Session]:
    """带租户上下文的会话：事务级 SET LOCAL，RLS 策略据此过滤。

    用法：`with tenant_session(project_id) as db: ...` —— 会话内所有查询自动按租户隔离
    （RLS USING(project_id = current_setting('app.tenant_id'))，§14.1）。
    """
    session = _SessionLocal()
    try:
        # set_config(..., is_local=true) 等价 SET LOCAL：事务级，事务结束自动恢复（§14.1 防连接池污染）
        session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---- RLS 主强制（§14.1：默认拒绝 + 强制集中，非每处自觉带 where）----

def enable_row_level_security() -> None:
    """为所有带 project_id 的业务表启用 FORCE RLS + 租户策略。

    未设置 app.tenant_id 时策略返回空集 → 查询空结果（fail closed）。
    users / projects 是租户根表，不走此策略（应用层归属校验，§14.1）。

    注意：必须用超级用户（owner）连接执行——ALTER TABLE FORCE 只允许 owner/超级；
    且应用连接角色必须 NOBYPASSRLS（超级用户永远绕过 RLS，§14.1 坑 3）。
    """
    from sqlalchemy import inspect

    with _admin_engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        inspector = inspect(conn)
        # 观测/队列表不参与 RLS（§14 隔离清单：agent_runs/tasks 无租户语义，运营查询用普通连接）
        _NO_RLS_TABLES = {"agent_runs", "tasks"}
        tables = [t for t in inspector.get_table_names()
                  if t not in ("users", "projects", "alembic_version", *_NO_RLS_TABLES)]
        # 撤销观测表已存在的 RLS（幂等）
        for no_rls in _NO_RLS_TABLES:
            if no_rls in inspector.get_table_names():
                conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {no_rls}"))
                conn.execute(text(f"ALTER TABLE {no_rls} DISABLE ROW LEVEL SECURITY"))
        for t in tables:
            cols = {c["name"] for c in inspector.get_columns(t)}
            if "project_id" not in cols:
                continue
            conn.execute(text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
            conn.execute(text(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY"))
            conn.execute(text(
                f"DROP POLICY IF EXISTS tenant_isolation ON {t}"
            ))
            conn.execute(text(
                f"CREATE POLICY tenant_isolation ON {t} "
                "USING (current_setting('app.tenant_id', true) IS NOT NULL "
                "AND project_id = current_setting('app.tenant_id', true)::uuid)"
            ))
