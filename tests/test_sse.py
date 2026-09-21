"""SSE 进度流（`GET /api/v1/tasks/{task_id}/events`）。

这条路由原先由 Go 网关独占，边缘换 Caddy 后收回 Python。本文件把网关时代的可观察契约
钉住——帧格式、重放语义、410 信封、心跳与心跳上的会话复检。**不需要模型、不需要 worker**：
直接往 Redis Stream 里塞帧，端点只负责转发。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update

from conftest import identity_headers
from myink.api import routes_sse
from myink.api.main import app
from myink.db import new_session
from myink.models import Project, User
from myink.worker.redis_client import get_redis, sse_key

client = TestClient(app)

TERMINAL_STATUSES = ("done", "failed", "awaiting_plan", "awaiting_review", "cancelled")


def _account() -> tuple[str, str, dict[str, str]]:
    """建一个干净的 user + 他的书，返回 (user_id, project_id, 认证头)。

    归属判定要真的落在 `projects.user_id` 上，所以两行都得落库。
    """
    with new_session() as db:
        user = User(username=f"sse-{uuid.uuid4().hex[:10]}")
        db.add(user)
        db.flush()
        project = Project(user_id=user.id, title=f"sse-book-{uuid.uuid4().hex[:6]}")
        db.add(project)
        db.flush()
        uid, pid = str(user.id), str(project.id)
        db.commit()
    return uid, pid, identity_headers(uuid.UUID(uid))


def _purge(uid: str) -> None:
    with new_session() as db:
        db.execute(sa_delete(Project).where(Project.user_id == uuid.UUID(uid)))
        db.execute(sa_delete(User).where(User.id == uuid.UUID(uid)))
        db.commit()


def _seed(task_id: str, frames: list[dict]) -> str:
    """写 queue:sse:{tid}，返回 key。"""
    key = sse_key(task_id)
    r = get_redis()
    r.delete(key)
    for frame in frames:
        r.xadd(key, frame, maxlen=1000)
    r.expire(key, 3600)
    return key


def _lease(task_id: str, uid: str, pid: str) -> None:
    """归属租约：入队后、tasks 行落库前，归属只存在于这里。"""
    get_redis().set(
        f"queue:task-owner:{task_id}", json.dumps({"user_id": uid, "project_id": pid}), ex=600
    )


def _drain(key: str) -> None:
    r = get_redis()
    r.delete(key)
    r.delete(key.replace("queue:sse:", "queue:task-owner:"))


def _frames(body: str) -> list[dict]:
    """SSE 文本 → [{id, event, data}]；注释帧（心跳）丢弃。"""
    out = []
    for block in body.split("\n\n"):
        fields = {}
        for line in block.split("\n"):
            if line.startswith(("event: ", "id: ", "data: ")):
                name, _, value = line.partition(": ")
                fields[name] = value
        if "data" in fields:
            out.append(
                {"id": fields.get("id"), "event": fields.get("event"), "data": json.loads(fields["data"])}
            )
    return out


# ---- 纯函数：Last-Event-ID 解析（与网关 ParseLastEventID 逐例同值） ----

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "0-0"), ("", "0-0"), ("5", "0-0"), ("5-", "5-0"), ("-3", "0-0"),
        ("abc-1", "0-0"), ("1_x-2", "0-0"), ("١٢-٣", "0-0"), ("--", "0-0"),
        ("17-2", "17-2"), ("17-9", "17-9"),
        # 序号畸形仍保留起点，只有整个头畸形才回 0-0（网关同口径）
        ("17-abc", "17-0"),
    ],
)
def test_parse_last_event_id_matches_gateway(raw, expected):
    assert routes_sse._parse_last_event_id(raw) == expected


def test_parse_last_event_id_normalizes_leading_plus():
    """网关会把 `+17` 原样拼进 XRANGE 而报错；这里归一成 `17-2`。"""
    assert routes_sse._parse_last_event_id("+17-2") == "17-2"


def test_decode_drops_frames_without_event_field():
    assert routes_sse._decode({"status": "running"}) is None
    assert routes_sse._decode({"event": ""}) is None


def test_decode_int_fields_tolerate_garbage():
    ev = routes_sse._decode({"event": "status", "chapter_seq": "abc", "attempt": None, "offset": "12"})
    assert (ev["chapter_seq"], ev["attempt"], ev["offset"]) == (0, 0, 12)


# ---- 鉴权与归属 ----

def test_events_without_identity_is_401():
    assert client.get(f"/api/v1/tasks/{uuid.uuid4()}/events").status_code == 401


def test_events_with_invalid_task_id_is_400():
    uid, _, headers = _account()
    try:
        assert client.get("/api/v1/tasks/not-a-uuid/events", headers=headers).status_code == 400
    finally:
        _purge(uid)


def test_events_unknown_task_is_404():
    uid, _, headers = _account()
    try:
        assert client.get(f"/api/v1/tasks/{uuid.uuid4()}/events", headers=headers).status_code == 404
    finally:
        _purge(uid)


def test_events_foreign_task_is_403():
    """租约指向别人 → 403（不能因为「有租约」就放行）。"""
    uid, pid, headers = _account()
    task_id = str(uuid.uuid4())
    _lease(task_id, str(uuid.uuid4()), pid)
    try:
        assert client.get(f"/api/v1/tasks/{task_id}/events", headers=headers).status_code == 403
    finally:
        _drain(sse_key(task_id))
        _purge(uid)


# ---- 流不存在 → 410（前端据此回退 GET 快照） ----

def test_events_missing_stream_returns_410_envelope():
    uid, pid, headers = _account()
    task_id = str(uuid.uuid4())
    _lease(task_id, uid, pid)
    try:
        resp = client.get(f"/api/v1/tasks/{task_id}/events", headers=headers)
        assert resp.status_code == 410
        assert resp.json() == {"error": "sse_stream_expired", "hint": "fallback_get_snapshot"}
        assert "text/event-stream" not in resp.headers.get("content-type", "")
    finally:
        _drain(sse_key(task_id))
        _purge(uid)


# ---- 正常转发：帧格式 + 终态收流 ----

def test_events_forwards_frames_and_stops_at_terminal():
    uid, pid, headers = _account()
    task_id = str(uuid.uuid4())
    key = _seed(task_id, [
        {"event": "status", "task_id": task_id, "status": "queued"},
        {"event": "node", "task_id": task_id, "status": "running", "node": "writer",
         "chapter_seq": "1", "offset": "12", "content": "===\n夜色沉沉\n"},
        {"event": "status", "task_id": task_id, "status": "done"},
    ])
    _lease(task_id, uid, pid)
    try:
        resp = client.get(f"/api/v1/tasks/{task_id}/events", headers=headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["cache-control"] == "no-store"
        body = resp.text

        # 帧是 `event:` + `id:` + `data:` + 空行；每一行都是合法 SSE 行。
        assert body.endswith("\n\n")
        assert not [l for l in body.split("\n") if l and not l.startswith(("event: ", "id: ", "data: ", ":"))]

        parsed = _frames(body)
        assert [f["event"] for f in parsed] == ["status", "node", "status"]
        assert [f["data"]["status"] for f in parsed] == ["queued", "running", "done"]
        # id 必须是 Redis 流 ID（断线重连靠它）
        assert all(f["id"] and "-" in f["id"] for f in parsed)

        # data 载荷恒有 12 个键（与 sse.ts 的 SSEEvent 一一对应）
        assert set(parsed[1]["data"]) == {
            "type", "task_id", "node", "status", "message", "stage",
            "chapter_seq", "attempt", "offset", "artifact_id", "content", "artifact",
        }
        assert parsed[1]["data"]["content"] == "===\n夜色沉沉\n"
        assert parsed[1]["data"]["chapter_seq"] == 1
        assert parsed[1]["data"]["offset"] == 12
        # 终态帧就是最后一帧（前端读到它才 stop）
        assert parsed[-1]["data"]["status"] == "done"
    finally:
        _drain(key)
        _purge(uid)


def test_events_skips_historical_terminal_frame():
    """同一 task 跨 awaiting_review 续跑：历史终态必须跳过，否则前端在此提前关流。

    只在「终态之后还有新事件」时跳过；终态是最后一帧时照发（前端靠它收尾）。
    """
    uid, pid, headers = _account()
    task_id = str(uuid.uuid4())
    key = _seed(task_id, [
        {"event": "status", "task_id": task_id, "status": "queued"},
        {"event": "status", "task_id": task_id, "status": "awaiting_review"},
        {"event": "status", "task_id": task_id, "status": "running"},
        {"event": "node", "task_id": task_id, "status": "running", "content": "续跑正文"},
        {"event": "status", "task_id": task_id, "status": "done"},
    ])
    _lease(task_id, uid, pid)
    try:
        parsed = _frames(client.get(f"/api/v1/tasks/{task_id}/events", headers=headers).text)
        statuses = [f["data"]["status"] for f in parsed]
        assert "awaiting_review" not in statuses, "历史终态没被跳过 → 浏览器会提前关流"
        assert statuses == ["queued", "running", "running", "done"]
        assert "续跑正文" in [f["data"]["content"] for f in parsed]
    finally:
        _drain(key)
        _purge(uid)


def test_events_lone_terminal_frame_is_delivered():
    """库里只有一条终态（任务已结束）——必须发出去，前端要靠它把 phase 置为 terminal。"""
    uid, pid, headers = _account()
    task_id = str(uuid.uuid4())
    key = _seed(task_id, [{"event": "status", "task_id": task_id, "status": "done"}])
    _lease(task_id, uid, pid)
    try:
        parsed = _frames(client.get(f"/api/v1/tasks/{task_id}/events", headers=headers).text)
        assert [f["data"]["status"] for f in parsed] == ["done"]
    finally:
        _drain(key)
        _purge(uid)


# ---- 断线重连 ----

def test_replay_from_last_event_id_is_exclusive_and_lossless():
    """`(` 严格大于起点：不重复上一帧，也不丢后续帧。查询串与请求头两种都认。"""
    uid, pid, headers = _account()
    task_id = str(uuid.uuid4())
    key = _seed(task_id, [
        {"event": "status", "task_id": task_id, "status": "queued"},
        {"event": "status", "task_id": task_id, "status": "running"},
        {"event": "status", "task_id": task_id, "status": "done"},
    ])
    _lease(task_id, uid, pid)
    url = f"/api/v1/tasks/{task_id}/events"
    try:
        ids = [f["id"] for f in _frames(client.get(url, headers=headers).text)]
        assert len(ids) == 3

        via_query = _frames(client.get(url, headers=headers, params={"last_event_id": ids[0]}).text)
        assert [f["id"] for f in via_query] == ids[1:], "查询串重放应严格大于起点"
        via_header = _frames(client.get(url, headers={**headers, "Last-Event-ID": ids[1]}).text)
        assert [f["id"] for f in via_header] == ids[2:], "请求头重放应严格大于起点"
        from_zero = _frames(client.get(url, headers=headers, params={"last_event_id": "0-0"}).text)
        assert [f["id"] for f in from_zero] == ids, "0-0 从头重放"
        bad = _frames(client.get(url, headers=headers, params={"last_event_id": "not-an-id"}).text)
        assert [f["id"] for f in bad] == ids, "畸形 ID 退化为从头重放，不得抛错"
    finally:
        _drain(key)
        _purge(uid)


# ---- 心跳 + 心跳上的会话复检（网关时代由 ticker goroutine 承担） ----

def test_keepalive_is_sent_while_idle(monkeypatch):
    """空闲流靠注释帧保活（中间代理会掐掉长时间无字节的连接）。

    把硬超时压到 0.6s，让流自己收尾——读到 EOF 而不是中途 break：同步生成器阻塞在
    `xread` 里，客户端单方面挂断会让 ASGI 任务卡在无人读取的 send 上。
    """
    monkeypatch.setattr(routes_sse, "_HEARTBEAT_SECONDS", 0.03)
    monkeypatch.setattr(routes_sse, "_BLOCK_SECONDS", 0.02)
    monkeypatch.setattr(routes_sse, "_MAX_DURATION", timedelta(seconds=0.6))
    uid, pid, headers = _account()
    task_id = str(uuid.uuid4())
    key = _seed(task_id, [{"event": "status", "task_id": task_id, "status": "running"}])
    _lease(task_id, uid, pid)
    try:
        with client.stream("GET", f"/api/v1/tasks/{task_id}/events", headers=headers) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())
        assert ": keepalive" in body, "空闲时必须发注释帧保活"
        assert '"status":"running"' in body, "已有帧照常发出"
        assert body.count(": keepalive") >= 2, "0.6s / 30ms 心跳应有多条"
    finally:
        _drain(key)
        _purge(uid)


def test_stream_closes_when_session_is_revoked(monkeypatch):
    """改密码/登出会让 auth_version 自增 → 下一次心跳复检必须主动收流。

    这是「SSE 连接不会被吊销后的旧令牌一直吊着」的唯一保障：不靠终态帧，不靠 30min 超时。
    """
    monkeypatch.setattr(routes_sse, "_HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(routes_sse, "_BLOCK_SECONDS", 0.02)
    uid, pid, headers = _account()
    task_id = str(uuid.uuid4())
    key = _seed(task_id, [{"event": "status", "task_id": task_id, "status": "running"}])
    _lease(task_id, uid, pid)

    def revoke() -> None:
        time.sleep(0.25)
        with new_session() as db:
            db.execute(sa_update(User).where(User.id == uuid.UUID(uid)).values(auth_version=User.auth_version + 1))
            db.commit()

    threading.Thread(target=revoke, daemon=True).start()
    try:
        start = time.monotonic()
        with client.stream("GET", f"/api/v1/tasks/{task_id}/events", headers=headers) as resp:
            body = "".join(resp.iter_text())
        assert time.monotonic() - start < 10, "被吊销后必须很快收流，而不是等 30min 硬超时"
        assert '"status":"done"' not in body, "流里没有终态帧：收流只能来自会话复检"
    finally:
        _drain(key)
        _purge(uid)


def test_stream_is_capped_by_token_expiry(monkeypatch):
    """流的最长存活时间还要受令牌自身到期约束（网关的 auth_expires）。

    这里断言的是**「到期约束生效，而不是撞上 30 分钟硬超时」**，所以门槛按硬超时来定而不能
    贴着 1s 写：整个测试进程共用同一个 Redis，一次卡住的往返就能把 wall-clock 推高十几秒
    （实测跑全量时出现过 11s，单跑 2s）。真正要排除的是 1800s 那条路径。
    """
    monkeypatch.setattr(routes_sse, "_BLOCK_SECONDS", 0.02)
    uid, pid, _ = _account()
    task_id = str(uuid.uuid4())
    key = _seed(task_id, [{"event": "status", "task_id": task_id, "status": "running"}])
    _lease(task_id, uid, pid)
    try:
        now = datetime.now(timezone.utc)
        subscriber = routes_sse._Subscriber(token="irrelevant", user_id=uid, expires_at=now + timedelta(seconds=1))
        start = time.monotonic()
        frames = list(routes_sse._stream(key, "0-0", subscriber, now + timedelta(seconds=1)))
        elapsed = time.monotonic() - start
        ceiling = routes_sse._MAX_DURATION.total_seconds()
        assert elapsed < ceiling / 10, (
            f"应按令牌到期（1s）收流，而不是撞 30min 硬超时；实际 {elapsed:.1f}s"
        )
        assert len(frames) == 1, "已有帧照发，然后停在到期点"
    finally:
        _drain(key)
        _purge(uid)


@pytest.mark.parametrize("status", TERMINAL_STATUSES)
def test_every_terminal_status_closes_the_stream(status):
    """五个终态都要收流（前端 isTerminalStatus 认这五个）。"""
    uid, pid, headers = _account()
    task_id = str(uuid.uuid4())
    key = _seed(task_id, [{"event": "status", "task_id": task_id, "status": status}])
    _lease(task_id, uid, pid)
    try:
        parsed = _frames(client.get(f"/api/v1/tasks/{task_id}/events", headers=headers).text)
        assert [f["data"]["status"] for f in parsed] == [status]
    finally:
        _drain(key)
        _purge(uid)
