"""整本书删除（阶段 6 硬删）：409 守卫 + FK 级联清全部业务表/向量 + checkpoint/Redis 残留。

- 级联全清：章/事件+向量/池候选/势力/任务/agent_runs 一并删除，Redis 残留键（book 锁、
  sse/lock）清空，Project 行不存在；
- 守卫 409：DB 非终态任务（running/paused）拒绝；Redis inflight 键存在（已入队未物化
  窗口）拒绝——网关入队先 SADD inflight + XADD，worker 消费才物化 DB 行，单查 DB 会漏窗口；
- 404/403 矩阵（仿 test_auth.py 归属断言口径）；
- delete_threads：真实 PostgresSaver.put/put_writes 落 checkpoint 行 + 直接插 blob 行 +
  `:ch%` 批次前缀行 → 三表全清（batch run id 形如 {batch_id}:ch{seq}）。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection

from aiink.api.main import app
from aiink.api.routes_book import delete_project
from aiink.config import settings
from aiink.db import new_session, tenant_session
from aiink.memory.vector_store import PgvectorStore
from aiink.models import (AgentRun, Chapter, EmbeddingRow, Event, Faction,
                          MemoryCandidate, Project, Task, User)
from aiink.worker.redis_client import (book_key, get_redis, inflight_key,
                                       lock_key, sse_key)
from aiink.workflow.checkpointer import build_checkpointer, delete_threads

client = TestClient(app)

ZERO_VEC = [0.0] * 1024


def _demo_user_id() -> uuid.UUID:
    with new_session() as db:
        u = db.query(User).filter(User.username == "demo").first()
        assert u is not None, "请先运行 `aiink init`（demo 用户未建）"
        return u.id


def _h(uid) -> dict:
    return {"X-AiInk-User": str(uid)} if uid is not None else {}


def _seed_chapter(pid: str, seq: int) -> None:
    with tenant_session(pid) as db:
        db.add(Chapter(project_id=uuid.UUID(pid), chapter_seq=seq, title=f"第{seq}章",
                       content=f"第{seq}章正文", status="confirmed", generation_source="auto"))
        db.commit()


def _seed_event_with_vec(pid: str, seq: int) -> None:
    with tenant_session(pid) as db:
        ev = Event(project_id=uuid.UUID(pid), summary=f"事件{seq}", source_chapter=seq, confidence=0.9)
        db.add(ev)
        db.flush()
        PgvectorStore().upsert(db, project_id=uuid.UUID(pid), level="event", source_id=ev.id,
                               source_chapter=seq, model_version="bge-m3", embedding=ZERO_VEC)
        db.commit()


def _seed_pool_candidate(pid: str, seq: int) -> None:
    with tenant_session(pid) as db:
        db.add(MemoryCandidate(project_id=uuid.UUID(pid), kind="event", source_chapter=seq,
                               payload={"summary": f"候选{seq}", "participants": []}, confidence=0.8))
        db.commit()


def _seed_faction(pid: str) -> None:
    with tenant_session(pid) as db:
        db.add(Faction(project_id=uuid.UUID(pid), name="测试势力", stance="中立"))
        db.commit()


def _seed_task(pid: str, *, status: str = "done") -> str:
    """插一条任务（观测表无 RLS，new_session 直写），返回 task_id。"""
    with new_session() as db:
        t = Task(project_id=uuid.UUID(pid), task_type="chapter_generate", status=status,
                 payload={}, chapter_seq=1)
        db.add(t)
        db.commit()
        return str(t.id)


def _seed_agent_run(pid: str, task_id: str) -> None:
    with new_session() as db:
        db.add(AgentRun(project_id=uuid.UUID(pid), task_id=task_id, node="write", cost_est=0.01))
        db.commit()


def _counts(pid: str) -> tuple[int, ...]:
    """各业务表残留计数（都应为 0 才叫级联全清）。"""
    with new_session() as db:
        t = db.query(Task).filter(Task.project_id == uuid.UUID(pid)).count()
        a = db.query(AgentRun).filter(AgentRun.project_id == uuid.UUID(pid)).count()
        proj = db.get(Project, uuid.UUID(pid))
    with tenant_session(pid) as db:
        ch = db.query(Chapter).count()
        ev = db.query(Event).count()
        emb = db.query(EmbeddingRow).count()
        cand = db.query(MemoryCandidate).count()
        fac = db.query(Faction).count()
    return (proj is not None, ch, ev, emb, cand, fac, t, a)


# ---- 级联全清 ----


def test_delete_project_cascades_everything(temp_project):
    """终态任务下整书删除：章/事件+向量/池候选/势力/任务/agent_runs 全清 + Redis 残留键清空。"""
    pid = temp_project
    tid = _seed_task(pid, status="done")
    _seed_chapter(pid, 1)
    _seed_event_with_vec(pid, 1)
    _seed_pool_candidate(pid, 1)
    _seed_faction(pid)
    _seed_agent_run(pid, tid)
    uid = str(_demo_user_id())
    # Redis 残留：book 锁 / sse / lock 键（done 任务已终态，无 inflight——inflight 存在即 409）
    r = get_redis()
    r.set(book_key(pid), "1")
    r.set(sse_key(tid), "x")
    r.set(lock_key(tid), "x")
    try:
        result = delete_project(pid)
        assert result == {"project_id": pid, "deleted": True}
        assert _counts(pid) == (False, 0, 0, 0, 0, 0, 0, 0)
        assert r.exists(book_key(pid)) == 0
        assert r.exists(sse_key(tid)) == 0
        assert r.exists(lock_key(tid)) == 0
        assert r.exists(inflight_key(uid, pid)) == 0, "inflight 键应被清理（无任务时本就不存在）"
    finally:
        # 直接函数调用不经过 require_owner，Redis 键自清；防断言失败残留
        r.delete(book_key(pid), sse_key(tid), lock_key(tid), inflight_key(uid, pid))


# ---- 409 守卫（双腿互补：DB 非终态任务 ∪ Redis inflight 键）----


@pytest.mark.parametrize("status", ["running", "paused", "awaiting_review"])
def test_delete_project_refuses_active_db_task(temp_project, status):
    """DB 非终态任务（queued/running/paused/awaiting_review）→ 409，不删。"""
    _seed_task(temp_project, status=status)
    with pytest.raises(HTTPException) as ei:
        delete_project(temp_project)
    assert ei.value.status_code == 409
    with new_session() as db:
        assert db.get(Project, uuid.UUID(temp_project)) is not None, "409 守卫下不得删除"


def test_delete_project_refuses_queued_task(temp_project):
    _seed_task(temp_project, status="queued")
    with pytest.raises(HTTPException) as ei:
        delete_project(temp_project)
    assert ei.value.status_code == 409


def test_delete_project_refuses_stale_inflight_key(temp_project):
    """Redis inflight 键存在（入队未物化窗口）→ 409，即使 DB 无任务行。"""
    uid = str(_demo_user_id())
    key = inflight_key(uid, temp_project)
    r = get_redis()
    r.set(key, "1")
    try:
        with pytest.raises(HTTPException) as ei:
            delete_project(temp_project)
        assert ei.value.status_code == 409
        with new_session() as db:
            assert db.get(Project, uuid.UUID(temp_project)) is not None
    finally:
        r.delete(key)


# ---- 404 / 403 矩阵（require_owner 挂依赖，走 TestClient HTTP 层）----


def test_delete_project_missing_404():
    resp = client.delete(f"/internal/v1/projects/{uuid.uuid4()}", headers=_h(_demo_user_id()))
    assert resp.status_code == 404


def test_delete_project_rejects_foreign_user(temp_project):
    resp = client.delete(f"/internal/v1/projects/{temp_project}", headers=_h(uuid.uuid4()))
    assert resp.status_code == 403


def test_delete_project_fail_closed_without_identity(temp_project):
    resp = client.delete(f"/internal/v1/projects/{temp_project}")
    assert resp.status_code == 403


def test_delete_project_rejects_invalid_identity(temp_project):
    resp = client.delete(f"/internal/v1/projects/{temp_project}", headers=_h("not-a-uuid"))
    assert resp.status_code == 403


# ---- delete_threads：清 checkpoint 三表（含 batch `:ch%` 前缀）----

_CONN_STR = settings.database_url.replace("postgresql+psycopg://", "postgresql://")


def _pg() -> Connection:
    return Connection.connect(_CONN_STR, autocommit=True)


def test_delete_threads_clears_checkpoint_tables():
    """真实 PostgresSaver.put/put_writes 落 checkpoints/writes 行；直接插 blob 行 + `:ch%`
    批次前缀行 → delete_threads 后三表全空（checkpoint 表无 FK，必须显式按 thread_id 清）。"""
    tid = f"del-cp-{uuid.uuid4().hex[:8]}"
    cid = f"1x{uuid.uuid4().hex}x3"
    config = {"configurable": {"thread_id": tid, "checkpoint_ns": "", "checkpoint_id": cid}}
    ckpt = Checkpoint(v=1, id=cid, ts="2026-08-17T00:00:00+00:00", channel_values={},
                      channel_versions={}, versions_seen={}, updated_channels=[])
    meta = CheckpointMetadata(source="input", step=1, writes=None, score=None)
    saver = build_checkpointer()  # 复用生产连接（put/put_writes 即真实运行写入路径）
    saver.put(config, ckpt, meta, {})
    saver.put_writes(config, [("channel", "value")], "task-1")
    # inline 存储模式不产 blob 行；直接插一行模拟 blob 存储模式，验证 SQL 三表全覆盖
    with _pg() as conn:
        conn.execute(
            "INSERT INTO checkpoint_blobs (thread_id, checkpoint_ns, channel, version, type, blob) "
            "VALUES (%s, '', 'channel', 1, 'json', %s)",
            (tid, b"{\"v\":1}"))
        # 批次每章 run id = {batch_id}:ch{seq} → LIKE {tid}:ch% 覆盖
        conn.execute(
            "INSERT INTO checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob) "
            "VALUES (%s, '', '1xccccccccccccccccccccccccccccx3', 'batch-child', 0, 'c', 'json', %s)",
            (f"{tid}:ch1", b"{}"))
    try:
        delete_threads([tid])
        with _pg() as conn:
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                cur = conn.execute(
                    f"SELECT count(*) FROM {table} WHERE thread_id = %s OR thread_id LIKE %s",
                    (tid, f"{tid}:ch%"))
                assert cur.fetchone()[0] == 0, f"{table} 应按 thread_id 清空（含 :ch% 前缀）"
    finally:
        delete_threads([tid])  # 幂等再清，防断言失败残留
