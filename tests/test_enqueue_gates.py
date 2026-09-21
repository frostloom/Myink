"""三层闸门 + 入队（Python 接管网关原先独占的那条路径）。

闸门脚本是 `src/myink/worker/gates.lua` / `compensate.lua`，所以这里测的是**调用形状与
失败语义**：5 KEYS / 8 ARGV、五种拒绝码的 `{"error"}` 信封、
发布"确定失败"才补偿而"结果不明"不补偿。

真跑 Redis（测试栈自带）而不是 stub ——KEYS 顺序或 ARGV 个数写错，只有真 Lua 抓得住。
这组性质原先由网关的 `enqueue_test.go` / `handlers_test.go` 保护，Go 退场前在此重建。
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from types import SimpleNamespace

import pika
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import identity_headers
from myink.api.main import app
from myink.config import settings
from myink.db import new_session
from myink.models import Project, User
from myink.worker import amqp, processor
from myink.worker import enqueue as enq
from myink.worker.redis_client import (
    book_cnt_key,
    book_quota_key,
    cost_key,
    get_redis,
    inflight_key,
    quota_key,
    sse_key,
)

client = TestClient(app)

# gates.lua 的检查顺序（配额 → 每书配额 → 书数 → 并发 → 日成本）；播种时必须只顶起
# 目标那一个，否则会被前面那条先拦下，测的就不是本意了。
GATE_CODES = [
    "QUOTA_EXCEEDED",
    "BOOK_QUOTA_EXCEEDED",
    "BOOK_CNT_EXCEEDED",
    "CONCURRENCY_LIMIT",
    "DAILY_BUDGET_EXCEEDED",
]

_MESSAGE_KEYS = {"task_id", "task_type", "project_id", "user_id", "payload",
                 "trace_id", "request_id", "retry_count", "created_at"}


@pytest.fixture
def book(temp_project):
    """可写的书 + 车主 + 身份头；用完清掉本用例碰过的 Redis 键。

    `temp_project` 建的书 creation_status 取列默认值 legacy_ready，所以写闸门放行。
    """
    pid = temp_project
    with new_session() as db:
        owner = db.scalar(select(Project.user_id).where(Project.id == uuid.UUID(pid)))
        user = db.get(User, owner)
    uid = str(user.id)
    today = date.today().isoformat()
    fixed = [quota_key(uid, today), inflight_key(uid, pid), cost_key(today),
             book_quota_key(uid, pid, today), book_cnt_key(uid, today)]
    r = get_redis()
    before = set(r.scan_iter("queue:task-owner:*")) | set(r.scan_iter("queue:sse:*"))
    tier_before = user.tier
    try:
        yield SimpleNamespace(pid=pid, uid=uid, user=user, today=today,
                              fixed=fixed, r=r, headers=identity_headers(user))
    finally:
        r.delete(*fixed)
        stale = (set(r.scan_iter("queue:task-owner:*")) | set(r.scan_iter("queue:sse:*"))) - before
        if stale:
            r.delete(*stale)
        # 车主是共享的 demo 用户：改了 tier 必须改回去，否则污染同一进程里后面所有用例
        with new_session() as db:
            db.get(User, uuid.UUID(uid)).tier = tier_before
            db.commit()


def _seed_gate(ctx, code: str) -> None:
    """只把目标闸门顶到阈值上（先清干净其余计数）。"""
    r, uid, pid, today = ctx.r, ctx.uid, ctx.pid, ctx.today
    r.delete(*ctx.fixed)
    if code == "QUOTA_EXCEEDED":
        r.set(quota_key(uid, today), settings.quota_daily)
    elif code == "BOOK_QUOTA_EXCEEDED":
        r.set(book_quota_key(uid, pid, today), settings.book_quota_daily)
    elif code == "BOOK_CNT_EXCEEDED":
        r.sadd(book_cnt_key(uid, today),
               *[str(uuid.uuid4()) for _ in range(settings.books_per_day_max)])
    elif code == "CONCURRENCY_LIMIT":
        r.sadd(inflight_key(uid, pid), str(uuid.uuid4()))
    elif code == "DAILY_BUDGET_EXCEEDED":
        r.set(cost_key(today), settings.daily_budget)


def _generate(ctx, **body):
    return client.post(f"/api/v1/projects/{ctx.pid}/chapters/{uuid.uuid4()}/generate",
                       json={"seq": 1, **body}, headers=ctx.headers)


def _capture_publish(monkeypatch, sink: dict) -> None:
    def _publish(body, key, **kwargs):
        sink.update(json.loads(body), key=key, **kwargs)
    monkeypatch.setattr(enq.amqp, "publish", _publish)


@pytest.mark.parametrize("code", GATE_CODES)
def test_gate_rejections_use_the_error_envelope(book, code):
    """五种拒绝码都要走 `{"error": CODE}` 429 —— 前端 GATE_CODES 认这个键。

    这条是真端到端：真身份 → 真路由 → 真 gates.lua → 真 Redis 计数 → 真信封。
    """
    _seed_gate(book, code)
    response = _generate(book)
    assert response.status_code == 429, response.text
    assert response.json() == {"error": code}
    # 闸门拒绝不得留下副作用：并发占位不该多出本任务的 id
    assert book.r.scard(inflight_key(book.uid, book.pid)) == (1 if code == "CONCURRENCY_LIMIT" else 0)


def test_draft_book_cannot_be_enqueued(book):
    """草稿状态的书进不了生成队列（409），且闸门一分钱都没扣。"""
    with new_session() as db:
        db.get(Project, uuid.UUID(book.pid)).creation_status = "draft"
        db.commit()
    response = _generate(book)
    assert response.status_code == 409
    assert response.json()["detail"] == "PROJECT_NOT_READY"
    assert book.r.scard(inflight_key(book.uid, book.pid)) == 0
    assert book.r.get(quota_key(book.uid, book.today)) is None


def test_invalid_writing_mode_is_rejected_before_the_gate(book, monkeypatch):
    published: dict = {}
    _capture_publish(monkeypatch, published)
    response = _generate(book, mode="turbo")
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_writing_mode"
    assert published == {}
    assert book.r.scard(inflight_key(book.uid, book.pid)) == 0


def test_success_returns_202_with_a_dispatchable_message(book, monkeypatch):
    """202 + 消息体形状：9 个键、三个 id 相同、task_type 落在 worker 的派发分支上。"""
    published: dict = {}
    _capture_publish(monkeypatch, published)
    response = _generate(book, user_instruction="慢一点", mode="manual")
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert set(accepted) == {"task_id", "trace_id", "status"}
    assert accepted["status"] == "queued"

    assert set(published) == _MESSAGE_KEYS | {"key", "priority"}
    assert published["key"] == amqp.KEY_TASKS
    assert published["priority"] == settings.priority_normal
    assert published["task_id"] == accepted["task_id"] == accepted["trace_id"]
    assert published["request_id"] == published["task_id"]
    assert published["project_id"] == book.pid
    assert published["user_id"] == book.uid
    assert published["retry_count"] == 0
    assert isinstance(published["created_at"], int)
    assert published["payload"]["mode"] == "manual"
    assert published["payload"]["user_instruction"] == "慢一点"


def test_vip_tier_gets_the_priority_boost(book, monkeypatch):
    """JWT tier=vip → 消息优先级 9（主队列 x-max-priority=10）。

    tier 取的是 DB 里的**新鲜值**，不是令牌里的 claim（`current_identity` 的语义），
    所以这里改的是用户行。
    """
    published: dict = {}
    _capture_publish(monkeypatch, published)
    with new_session() as db:
        db.get(User, uuid.UUID(book.uid)).tier = "vip"
        db.commit()
    vip = client.post(f"/api/v1/projects/{book.pid}/chapters/{uuid.uuid4()}/generate",
                      json={"seq": 1}, headers=book.headers)
    assert vip.status_code == 202, vip.text
    assert published["priority"] == settings.priority_vip


def test_owner_record_and_sse_seed_exist_before_the_202(book, monkeypatch):
    """归属记录先于发布：SSE 可能在 worker 物化 Task 行之前就连上来。

    `GET /tasks/{id}/access` 的形状契约就是这里写的这两个键，所以顺带把它钉住。
    """
    monkeypatch.setattr(enq.amqp, "publish", lambda *a, **kw: None)
    task_id = _generate(book).json()["task_id"]

    owner_key = f"queue:task-owner:{task_id}"
    assert json.loads(book.r.get(owner_key)) == {"user_id": book.uid, "project_id": book.pid}
    assert 86_000 < book.r.ttl(owner_key) <= 86_400

    frames = book.r.xrange(sse_key(task_id))
    assert len(frames) == 1
    assert frames[0][1] == {"event": "status", "task_id": task_id, "status": "queued"}
    assert 0 < book.r.ttl(sse_key(task_id)) <= 3600


def test_definite_publish_failure_rolls_the_gates_back(book, monkeypatch):
    """broker 明确拒收 → 消息一定不在队列里 → 回滚配额、每书配额与并发占位。"""
    def _nack(*_args, **_kwargs):
        raise pika.exceptions.NackError([])

    monkeypatch.setattr(enq.amqp, "publish", _nack)
    response = _generate(book)
    assert response.status_code == 503
    assert response.json() == {"error": "enqueue_failed"}
    assert int(book.r.get(quota_key(book.uid, book.today)) or 0) == 0
    assert int(book.r.get(book_quota_key(book.uid, book.pid, book.today)) or 0) == 0
    assert book.r.scard(inflight_key(book.uid, book.pid)) == 0
    # bookcnt 故意不反悔：撤销配额与并发即够，罕见多计一天书数次日自然清零
    assert book.r.sismember(book_cnt_key(book.uid, book.today), book.pid)


def test_ambiguous_publish_failure_leaves_the_gates_deducted(book, monkeypatch):
    """结果不明（confirm 超时）→ **不补偿**：消息可能已入队，退了闸门等于重复扣费。

    搞反的后果就是这条测试的另一半：给已入队的消息补偿，worker 照跑但配额已退。
    """
    def _boom(*_args, **_kwargs):
        raise RuntimeError("confirm timeout")

    monkeypatch.setattr(enq.amqp, "publish", _boom)
    response = _generate(book)
    assert response.status_code == 503
    assert response.json() == {"error": "enqueue_failed"}
    assert int(book.r.get(quota_key(book.uid, book.today)) or 0) == 1
    assert int(book.r.get(book_quota_key(book.uid, book.pid, book.today)) or 0) == 1
    assert book.r.scard(inflight_key(book.uid, book.pid)) == 1


def test_batch_size_is_clamped_and_start_defaults_to_one(book, monkeypatch):
    """size 是钳制不是拒绝（§6.11）；start<1 归一到 1（Go 零值 0 会让批次从第 0 章写起）。"""
    published: dict = {}
    _capture_publish(monkeypatch, published)
    response = client.post(f"/api/v1/projects/{book.pid}/batches/generate",
                           json={"size": 9999, "start": 0}, headers=book.headers)
    assert response.status_code == 202, response.text
    assert published["payload"] == {"size": settings.batch_max_hard, "start": 1}
    assert published["task_type"] == "batch_generate"
    # 扣的是钳制后的 size（闸门扣章数，不是请求里的 9999）
    assert int(book.r.get(quota_key(book.uid, book.today))) == settings.batch_max_hard


@pytest.mark.parametrize("task_type,payload,expected", [
    ("chapter_generate", {"seq": 1}, "chapter"),
    ("batch_generate", {"start": 1, "size": 3}, "batch"),
])
def test_produced_menus_reach_the_right_dispatch_branch(book, monkeypatch, task_type,
                                                        payload, expected):
    """产出的 task_type 必须落在 worker 的派发分支上。

    不跑图：把两个分支目标换成记录器，验消息被送到正确的那个（改写 task_type 名而
    忘了同步 worker 的话，这里立刻红）。
    """
    seen: list[str] = []
    monkeypatch.setattr(processor, "generate_chapter",
                        lambda **kwargs: seen.append("chapter") or "done")
    monkeypatch.setattr(processor, "generate_batch",
                        lambda **kwargs: seen.append("batch") or "done")

    message = {"task_id": str(uuid.uuid4()), "task_type": task_type,
               "project_id": book.pid, "user_id": book.uid, "payload": payload}
    assert processor._dispatch(message) == "done"
    assert seen == [expected]


def test_the_lua_scripts_ship_next_to_the_module():
    """脚本必须躺在模块旁边：`package-data` 漏了的话进不了 wheel / 镜像。

    真跑一遍生产同款的加载路径（`__file__` 同级），而不是断言仓库里那个相对路径。
    这段原先是 `test_gates_parity.py` 的一半——另一半（与网关那份逐字节相同）随 Go 退场作废。
    """
    from pathlib import Path

    from myink.worker import enqueue

    here = Path(enqueue.__file__).parent
    for name in ("gates.lua", "compensate.lua"):
        script = here / name
        assert script.is_file(), f"{here} 里没有 {name}（package-data 漏了？）"
        assert script.read_text(encoding="utf-8").strip(), f"{name} 是空的"
    assert enqueue._GATES_LUA == (here / "gates.lua").read_text(encoding="utf-8")
