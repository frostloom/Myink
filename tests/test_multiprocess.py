"""多进程并行自动化回归（§13 BYOK，2026-08-09）。

真正起 2 个 worker 进程消费同一 Redis 消费组，验证多书并行核心语义：
- 异书并行：两个不同 project 的任务同时投递 → 两个 worker 并发执行（overlap>0），都 done；
- 同书串行：同一 project 的两个任务同时投递 → 书锁保证一个执行、另一个 defer 退避重投，
  永不并发（overlap==0），最终都 done。

配套 tests/_mp_worker.py（子进程入口：注入假 provider + 并发检测）。测试数据全用临时
project（复制 demo 的 Project+ProjectSettings），demo 零污染；清理 = 删临时 project
（FK 级联子表）+ agent_runs（无 FK 手动）+ Redis 残留。需活 Redis（aiink-redis :6380）
+ 活 PG（aiink init 建过 demo 项目）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import pytest
from sqlalchemy import delete as sa_delete, select as sa_select

from aiink.db import new_session
from aiink.models import AgentRun, Project, ProjectSettings, Task
from aiink.worker.redis_client import (
    book_key,
    delay_key,
    ensure_group,
    get_redis,
    lock_key,
    sse_key,
    stream_name,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MP_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_mp_worker.py")


# ── worker 子进程管理 ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def two_workers():
    """起 2 个真实 worker 进程（消费同一 Redis 消费组），等心跳就绪后 yield。"""
    ensure_group()
    r = get_redis()
    # 清历史心跳，避免误判就绪（E2E/上次运行残留的 key 已过期或待清理）
    stale_hb = r.keys("queue:heartbeat:*")
    if stale_hb:
        r.delete(*stale_hb)
    procs, logs = [], []
    for i in range(2):
        log_path = os.path.join(tempfile.gettempdir(), f"mp_worker_{i}.log")
        logf = open(log_path, "w", encoding="utf-8")
        p = subprocess.Popen(
            [sys.executable, _MP_WORKER],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=logf,
            env={**os.environ, "PYTHONPATH": ROOT},
        )
        procs.append(p)
        logs.append(logf)
    deadline = time.time() + 40
    while time.time() < deadline:
        if len(r.keys("queue:heartbeat:*")) >= 2:
            break
        time.sleep(0.5)
    else:
        for p in procs:
            p.kill()
        for lf in logs:
            lf.close()
        pytest.fail("2 个 worker 未在 40s 内就绪，详见 tmp mp_worker_*.log")
    # 快照测试开始前的 SSE 键：拆卸时只清「测试期间新建」的键（worker 子进程读消息即写
    # queued 事件，可能在 _cleanup 之后补写 → 残留），绝不碰测试前就存在的真实通道。
    sse_before = set(r.keys("queue:sse:*"))
    yield procs
    for p in procs:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    for lf in logs:
        lf.close()
    for k in set(r.keys("queue:sse:*")) - sse_before:
        r.delete(k)


class _DispatcherSim:
    """主进程模拟网关 dispatcher：把到期的 queue:delay 移回主队列（测试无 Go 网关）。"""

    def __enter__(self):
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(timeout=5)

    def _loop(self):
        r = get_redis()
        while not self._stop.is_set():
            try:
                now = int(time.time() * 1000)
                for member in r.zrangebyscore(delay_key(), "-inf", now):
                    r.xadd(stream_name(), {"body": member})
                    r.zrem(delay_key(), member)
            except Exception:
                pass
            self._stop.wait(1.0)


# ── 数据 helper ───────────────────────────────────────────────────────────────


def _demo_project_id() -> str:
    from sqlalchemy import text

    with new_session() as db:
        row = db.execute(text("SELECT id FROM projects WHERE title='九州问天'")).first()
        assert row is not None, "请先运行 aiink init 建立 demo 项目"
        return str(row.id)


def _make_test_project(demo_id: str, tag: str) -> str:
    """复制 demo 的 Project + ProjectSettings 成独立临时书（demo 零污染，删书即清）。"""
    with new_session() as db:
        demo = db.get(Project, uuid.UUID(demo_id))
        b = Project(user_id=demo.user_id, title=f"MP回归书-{tag}", genre=demo.genre,
                    target_words=demo.target_words)
        db.add(b)
        db.flush()
        ds = db.execute(sa_select(ProjectSettings).where(
            ProjectSettings.project_id == demo.id)).scalar_one_or_none()
        if ds is not None:
            db.add(ProjectSettings(
                project_id=b.id, world_rules=ds.world_rules, style_profile=ds.style_profile,
                skill_pack=ds.skill_pack, model_routes=ds.model_routes,
                hard_constraints=ds.hard_constraints, version=1))
        db.commit()
        return str(b.id)


def _enqueue(r, project_id: str, seq: int, tag: str) -> tuple[str, str]:
    """直接 XADD 到 queue:tasks（网关未起，模拟入队结果），返回 (task_id, msg_id)。"""
    task_id = str(uuid.uuid4())
    body = {
        "task_id": task_id, "task_type": "chapter_generate",
        "project_id": project_id, "user_id": f"mp-{tag}",
        "payload": {"seq": seq}, "trace_id": task_id, "request_id": task_id,
        "retry_count": 0,
    }
    msg_id = r.xadd(stream_name(), {"body": json.dumps(body)})
    return task_id, msg_id


def _wait_status(task_id: str, timeout: int = 90) -> str:
    """轮询 tasks 表直到终态（worker 物化后落库）。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        with new_session() as db:
            row = db.get(Task, uuid.UUID(task_id))
            last = row.status if row is not None else None
            if row is not None and row.status in ("done", "failed", "cancelled"):
                return row.status
        time.sleep(0.5)
    raise AssertionError(f"task {task_id[:8]} 未在 {timeout}s 内终态，末态 {last}")


def _cleanup(project_ids: list[str], task_ids: list[str], msg_ids: list[str]) -> None:
    """删临时 project（级联子表）+ agent_runs（无 FK 手动）+ Redis 残留。"""
    with new_session() as db:
        for pid in project_ids:
            db.execute(sa_delete(AgentRun).where(AgentRun.project_id == uuid.UUID(pid)))
            db.execute(sa_delete(Project).where(Project.id == uuid.UUID(pid)))
        db.commit()
    r = get_redis()
    for tid in task_ids:
        r.delete(sse_key(tid), lock_key(tid))
    for pid in project_ids:
        r.delete(book_key(pid))
    if msg_ids:
        r.xdel(stream_name(), *msg_ids)
    # defer 重投消息：dispatcher 从 delay 移回主队列会生成新 msg_id（原 msg_id 已 xack），
    # 只删 msg_ids 会漏——按 task_id 匹配把该任务在主队列的所有消息都删掉。
    for mid, fields in r.xrange(stream_name()):
        try:
            b = json.loads(fields.get("body", ""))
        except Exception:
            continue
        if b.get("task_id") in task_ids:
            r.xdel(stream_name(), mid)
    # delay 退避 ZSET：未到期的同任务 body 一并清（测试收尾无 dispatcher 在移）。
    for member in r.zrange(delay_key(), 0, -1):
        try:
            if json.loads(member).get("task_id") in task_ids:
                r.zrem(delay_key(), member)
        except Exception:
            continue


# ── 测试 ──────────────────────────────────────────────────────────────────────


def test_hetero_book_parallel(two_workers):
    """异书并行：两本不同书的任务同时投递 → 两个 worker 并发执行（书锁互不阻塞）。"""
    r = get_redis()
    r.delete("mp:overlap", "mp:active")
    demo_id = _demo_project_id()
    book_a = _make_test_project(demo_id, "A")
    book_b = _make_test_project(demo_id, "B")
    ta, ma = _enqueue(r, book_a, 1, "a")
    tb, mb = _enqueue(r, book_b, 1, "b")
    try:
        with _DispatcherSim():
            assert _wait_status(ta) == "done"
            assert _wait_status(tb) == "done"
        overlap = int(r.get("mp:overlap") or 0)
        assert overlap > 0, "异书任务应由两个 worker 并发执行（书锁互不阻塞），overlap 应 >0"
    finally:
        _cleanup([book_a, book_b], [ta, tb], [ma, mb])


def test_same_book_serial(two_workers):
    """同书串行：同一本书两个任务同时投递 → 书锁保证 defer→接棒，永不并发，最终都 done。"""
    r = get_redis()
    r.delete("mp:overlap", "mp:active")
    demo_id = _demo_project_id()
    book = _make_test_project(demo_id, "S")
    t1, m1 = _enqueue(r, book, 1, "s1")
    t2, m2 = _enqueue(r, book, 2, "s2")
    try:
        with _DispatcherSim():
            assert _wait_status(t1) == "done"
            assert _wait_status(t2) == "done"
        overlap = int(r.get("mp:overlap") or 0)
        assert overlap == 0, "同书任务应串行（书锁保证 defer→接棒），overlap 应 ==0"
    finally:
        _cleanup([book], [t1, t2], [m1, m2])
