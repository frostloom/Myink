"""任务进度 SSE：把 worker 写进 `queue:sse:{task_id}` 的帧转发给浏览器。

原先这条路由由 Go 网关独占（Go 只服务 SSE + /healthz）。边缘换成 Caddy 之后，
一个只为一条路由存在的进程要单独构建、单独部署、单独维护，代价高过收益；
Python 侧的鉴权与归属判定本来就已经是权威，于是整条链路收回本文件。
迁回时逐条对齐了网关时代的可观察契约，一条都没省：

- 鉴权：Bearer JWT 自验（签名/issuer/必需 claim/ver 版本），不看 `X-Myink-User`。
- 归属：复用 `routes_tasks.assert_task_access`，含「已入队未落库」窗口。
- 心跳：15s 一条 `: keepalive` 注释帧，同时用它做**会话复检**——token 被吊销
  （改密码 → auth_version 自增）或过期时主动收流，浏览器下次重连即 401。
- 重放：`Last-Event-ID` 走 XRANGE `(` 严格大于起点，断线不重复也不丢帧。
- 收流上限：30 分钟，且不超过 token 自身到期时间。
- 流已过期（终态后 TTL 1h 被回收）→ 410 `sse_stream_expired`，前端回退 GET 快照。

**预检必须在写响应头之前**：响应头一旦提交就是 200，此后的 410 只能落进 body，
浏览器会读成 eof 并无限重连。所以先 `EXISTS` 再决定返回 410 还是开流。

生成器是同步的：redis-py 是同步客户端，且 `XREAD BLOCK` 必须阻塞等待。FastAPI 会把
同步生成器丢进 anyio 线程池，**一条活跃连接占一个线程直到收流**——所以 main.py 把线程
池上限抬高了，见那里的注释。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials

from myink.api.auth import _bearer, _decode_token, _invalid_credentials, _load_identity
from myink.api.routes_tasks import assert_task_access
from myink.worker.redis_client import get_redis, sse_key

router = APIRouter(prefix="/api/v1", tags=["tasks"])

# Redis 流 ID 是 `[0-9]+-[0-9]+`。用 ASCII 数字而非 str.isdigit()——后者对 `²`
# 也返回 True，而后 int() 会抛错，非法值漏进 XRANGE 就成了坏帧。允许正负号是对齐 Go 的
# strconv.ParseInt 口径。
_STREAM_ID_PART = re.compile(r"[+-]?[0-9]+")

# 硬超时兜底：终态帧丢失时不让连接挂死（与网关时代同值）。
_MAX_DURATION = timedelta(minutes=30)
_HEARTBEAT_SECONDS = 15.0
# XREAD 单次阻塞上限；同时用它作为「距收流还有多久」的切片，避免超时后多等一整轮。
_BLOCK_SECONDS = 5.0

# worker 侧 XADD 的扁平字段（processor.py / observer.py / enqueue.py 三处生产点）。
_STR_FIELDS = ("task_id", "node", "status", "message", "stage", "artifact_id", "content", "artifact")
_INT_FIELDS = ("chapter_seq", "attempt", "offset")
# 终态：worker 写成 event=status + 下面之一。收到即收流，前端据此停掉订阅。
_TERMINAL = frozenset({"done", "failed", "awaiting_plan", "awaiting_review", "cancelled"})


@dataclass(frozen=True)
class _Subscriber:
    """订阅者身份：原样保留 token，供 15s 复检重新走一遍自验。"""

    token: str
    user_id: str
    expires_at: datetime


def _subscriber(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> _Subscriber:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _invalid_credentials()
    claims = _decode_token(credentials.credentials)
    if _load_identity(claims) is None:
        raise _invalid_credentials()
    return _Subscriber(
        token=credentials.credentials,
        user_id=str(claims.user_id),
        expires_at=claims.expires_at,
    )


def _still_valid(subscriber: _Subscriber) -> bool:
    """心跳期间的会话复检：签名/版本/账号三者任一失效即收流。"""
    try:
        claims = _decode_token(subscriber.token)
    except HTTPException:
        return False
    return _load_identity(claims) is not None


def _parse_last_event_id(raw: str | None) -> str:
    """解析 `Last-Event-ID`（Redis 流 ID 形如 `1700000000000-0`）。

    畸形一律从 `0-0` 重头重放；非法值绝不能漏进 XRANGE——那会抛错，而此刻响应头
    已经提交，错误只能落进 SSE body，浏览器读到的是坏帧。**唯一例外是序号畸形**：
    起点仍取 head、序号按 0 算，与网关 `ParseLastEventID` 同口径。
    """
    if not raw or "-" not in raw:
        return "0-0"
    head, _, tail = raw.partition("-")
    if not _STREAM_ID_PART.fullmatch(head):
        return "0-0"
    seq = int(tail) if _STREAM_ID_PART.fullmatch(tail) else 0
    # `int(head)` 顺带吃掉 `+` 号：Go 会把 `+17` 原样拼进 XRANGE 而报错。
    return f"{int(head)}-{max(seq, 0)}"


def _decode(fields: dict[str, Any]) -> dict[str, Any] | None:
    """Redis Stream 消息 → 转发用的扁平 dict；无 `event` 字段的帧丢弃（同网关）。"""
    event_type = fields.get("event")
    if not isinstance(event_type, str) or not event_type:
        return None
    decoded: dict[str, Any] = {"type": event_type}
    for name in _STR_FIELDS:
        value = fields.get(name)
        decoded[name] = value if isinstance(value, str) else ""
    for name in _INT_FIELDS:
        try:
            decoded[name] = int(fields.get(name) or 0)
        except (TypeError, ValueError):
            decoded[name] = 0
    return decoded


def _frame(stream_id: str, event: dict[str, Any]) -> str:
    """Event → SSE 帧。data 用紧凑分隔符与键排序，与网关的 json.Marshal 逐字节同形。"""
    body = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    lines = "" if event["type"] == "message" else f"event: {event['type']}\n"
    return f"{lines}id: {stream_id}\ndata: {body}\n\n"


def _is_terminal(event: dict[str, Any]) -> bool:
    return event["status"] in _TERMINAL


def _replay(r, key: str, after: str) -> tuple[list[tuple[str, dict[str, Any]]], str]:
    """追平已有帧，返回 (待发帧, 最后读到的流 ID)。"""
    # XRANGE 起点默认包含自身，用 `(` 做严格大于，重连时不重复上一帧。
    entries = r.xrange(key, f"({after}", "+")
    decoded = [(sid, ev) for sid, fields in entries if (ev := _decode(fields)) is not None]
    last = decoded[-1][0] if decoded else after
    frames = []
    for i, (sid, ev) in enumerate(decoded):
        # 同一 task_id 会跨 awaiting_plan / awaiting_review 多次续跑；历史终态之后还有新
        # 事件时必须跳过那个终态，否则浏览器在此提前关流，看不到后续正文。
        if _is_terminal(ev) and i < len(decoded) - 1:
            continue
        frames.append((sid, ev))
        if _is_terminal(ev):
            break
    return frames, last


def _stream(key: str, after: str, subscriber: _Subscriber, deadline: datetime) -> Iterator[str]:
    r = get_redis()
    try:
        frames, last = _replay(r, key, after)
    except Exception:  # noqa: BLE001 —— 追平失败不谎报「流已过期」，直接收流让前端重连
        return
    for sid, event in frames:
        yield _frame(sid, event)
        if _is_terminal(event):
            return

    beat_at = time.monotonic()
    while True:
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return
        try:
            result = r.xread({key: last}, count=100, block=int(min(_BLOCK_SECONDS, remaining) * 1000))
        except Exception:  # noqa: BLE001 —— Redis 抖动：收流，浏览器重连时会重新预检
            return
        for _stream_name, messages in result or ():
            for sid, fields in messages:
                event = _decode(fields)
                if event is None:
                    continue
                last = sid
                yield _frame(sid, event)
                if _is_terminal(event):
                    return

        now = time.monotonic()
        if now - beat_at >= _HEARTBEAT_SECONDS:
            beat_at = now
            if not _still_valid(subscriber):
                return
            yield ": keepalive\n\n"


@router.get(
    "/tasks/{task_id}/events",
    response_model=None,
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "SSE 帧流（注释帧为心跳）"},
        410: {"description": "流已过期：`sse_stream_expired`，客户端应回退 GET /tasks/{task_id} 快照"},
    },
)
def task_events(
    request: Request,
    task_id: str,
    last_event_id: str | None = Query(default=None),
    subscriber: _Subscriber = Depends(_subscriber),
) -> StreamingResponse | JSONResponse:
    """GET /api/v1/tasks/{task_id}/events —— 任务进度流（SSE）。"""
    try:
        uuid.UUID(task_id)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail=f"任务 id 非法: {task_id}")
    assert_task_access(task_id, subscriber.user_id)

    after = _parse_last_event_id(last_event_id or request.headers.get("Last-Event-ID"))
    key = sse_key(task_id)
    try:
        exists = bool(get_redis().exists(key))
    except Exception:  # noqa: BLE001 —— 预检出错不阻断，交给订阅去暴露真实故障
        exists = True
    if not exists:
        return JSONResponse(
            status_code=410,
            content={"error": "sse_stream_expired", "hint": "fallback_get_snapshot"},
        )

    deadline = min(datetime.now(timezone.utc) + _MAX_DURATION, subscriber.expires_at)
    return StreamingResponse(
        _stream(key, after, subscriber, deadline),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
