"""任务入队：三层闸门（gates.lua）→ 归属登记 → RabbitMQ 发布（publisher confirm + 失败补偿）。

移植自网关 `gateway/internal/queue/enqueue.go`。闸门脚本不重写：`gates.lua` /
`compensate.lua` 是网关那份的**逐字节副本**（`tests/test_gates_parity.py` 钉住），
语义真源留在 Go 的 `internal/queue/`（连带它那 8 个行为测试）。

调用形状与 `enqueue.go:71-76` 对齐：5 KEYS / 8 ARGV，ARGV 全传字符串（脚本内部
`tonumber`）。**不要**去"修" gates.lua 里那句硬编码的 `if inflight > 0`——
`CONCURRENCY_LIMIT` 从来没人传过，Go 也一样，parity 测试就是防这个的。

失败语义（与 Go 逐条对齐，搞反的后果是要么配额泄漏、要么重复扣费）：
- `GateError`：闸门拒绝，无副作用 → 429 `{"error": <CODE>}`
- 发布**确定失败**（broker nack / unroutable）：跑 compensate.lua 回滚闸门副作用
- 发布**结果不明**（confirm 超时/连接中断）：**不补偿**——消息可能已入队，
  worker 按 task_id 幂等兜底
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import date
from pathlib import Path

import pika

from myink.config import settings
from myink.worker import amqp
from myink.worker.redis_client import (
    book_cnt_key,
    book_quota_key,
    cost_key,
    get_redis,
    inflight_key,
    quota_key,
    sse_key,
)

logger = logging.getLogger(__name__)

# 模块级读入：`package-data` 没配好的话，导入即炸（比首次入队才炸更早暴露）。
_GATES_LUA = Path(__file__).with_name("gates.lua").read_text(encoding="utf-8")
_COMPENSATE_LUA = Path(__file__).with_name("compensate.lua").read_text(encoding="utf-8")

_OWNER_TTL_S = 24 * 3600
_SSE_TTL_S = 3600
_SSE_MAXLEN = 1000


class GateError(Exception):
    """闸门拒绝（配额/并发/成本/书数超限）。code 即前端 GATE_CODES 认的键。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class EnqueueUnavailable(Exception):
    """入队基础设施失败（Redis / 发布）。reason 只进日志，响应统一 503 enqueue_failed。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def enqueue(*, user_id: str, project_id: str, task_type: str, payload: dict,
            quota_n: int, cost_est: float, priority: int) -> dict:
    """闸门 + 入队。返回 `{"task_id", "trace_id", "status"}`（路由侧回 202）。

    顺序不可换：闸门 → 归属登记 → 发布 → SSE 种子帧。

    归属登记必须先于发布：SSE 可能在 worker 物化 Task 行之前就连上来，
    那时 `GET /tasks/{id}/access` 只能靠 `queue:task-owner:{id}` 判归属。

    日期桶用**本地**日期（同 worker 的 `date.today()` 与 Go 的 `time.Now()`）——
    换成 UTC 会让跨零点那一小段落到不同的 key 上，配额被静默放宽一倍。
    """
    today = date.today().isoformat()
    task_id = str(uuid.uuid4())
    keys = [
        quota_key(user_id, today),
        inflight_key(user_id, project_id),
        cost_key(today),
        book_quota_key(user_id, project_id, today),
        book_cnt_key(user_id, today),
    ]
    body = {
        "task_id": task_id,
        "task_type": task_type,
        "project_id": project_id,
        "user_id": user_id,
        "payload": payload,
        "trace_id": task_id,
        "request_id": task_id,
        "retry_count": 0,
        "created_at": int(time.time() * 1000),
    }

    r = get_redis()
    try:
        code, reason = _run_gates(r, keys, task_id=task_id, quota_n=quota_n,
                                  cost_est=cost_est, project_id=project_id)
    except Exception as exc:
        raise EnqueueUnavailable("gates") from exc
    if code != 1:
        raise GateError(reason)

    owner = json.dumps({"user_id": user_id, "project_id": project_id})
    try:
        r.set(f"queue:task-owner:{task_id}", owner, ex=_OWNER_TTL_S)
    except Exception as exc:
        _compensate(r, keys, task_id=task_id, quota_n=quota_n)
        raise EnqueueUnavailable("owner") from exc

    try:
        amqp.publish(json.dumps(body, ensure_ascii=False), amqp.KEY_TASKS, priority=priority)
    except (pika.exceptions.NackError, pika.exceptions.UnroutableError) as exc:
        # 确定失败：broker 明确拒收，消息一定不在队列里 → 回滚闸门
        _compensate(r, keys, task_id=task_id, quota_n=quota_n)
        raise EnqueueUnavailable("publish_rejected") from exc
    except Exception as exc:
        # 结果不明（confirm 超时/连接中断）：消息可能已入队。补偿会造成
        # "闸门已退而任务照跑"的重复扣费，所以这里刻意什么都不做。
        raise EnqueueUnavailable("publish_ambiguous") from exc

    _seed_sse(r, task_id)
    return {"task_id": task_id, "trace_id": task_id, "status": "queued"}


def _run_gates(r, keys: list[str], *, task_id: str, quota_n: int, cost_est: float,
               project_id: str) -> tuple[int, str]:
    """原子跑 gates.lua。通过 → (1, task_id)；拒绝 → (-N, 原因码)。"""
    res = r.eval(
        _GATES_LUA, len(keys), *keys,
        task_id, str(quota_n), str(cost_est),
        str(settings.quota_daily), str(settings.daily_budget),
        str(settings.book_quota_daily), str(settings.books_per_day_max),
        project_id,
    )
    if not isinstance(res, (list, tuple)) or not res:
        raise RuntimeError(f"gates.lua 异常返回: {res!r}")
    return int(res[0]), (str(res[1]) if len(res) > 1 else "")


def _compensate(r, keys: list[str], *, task_id: str, quota_n: int) -> None:
    """回滚闸门副作用（用户配额 KEYS[1] + 每书配额 KEYS[4] + 并发占位 KEYS[2]）。

    最佳努力：补偿失败只记日志，不掩盖原始错误。`compensate.lua` 故意不回滚
    `bookcnt`——撤销配额与并发即够，罕见多计一天书数次日自然清零（安全方向）。
    """
    try:
        r.eval(_COMPENSATE_LUA, 3, keys[0], keys[3], keys[1], str(quota_n), task_id)
    except Exception as exc:  # noqa: BLE001 —— 补偿是尽力而为，主错误更重要
        logger.warning("闸门补偿失败 task=%s: %s", task_id, exc)


def _seed_sse(r, task_id: str) -> None:
    """种子帧：让浏览器在 202 之后立刻能订阅（否则可能撞上"流已过期"）。

    consumer 取到消息时会写同形状的帧，所以这里失败不致命——只记日志。
    """
    try:
        r.xadd(sse_key(task_id),
               {"event": "status", "task_id": task_id, "status": "queued"},
               maxlen=_SSE_MAXLEN)
        r.expire(sse_key(task_id), _SSE_TTL_S)
    except Exception as exc:  # noqa: BLE001 —— 同上
        logger.warning("SSE 种子帧写入失败 task=%s: %s", task_id, exc)
