"""Redis 客户端与队列 key 约定（§阶段2；key 前缀遵守 §14：queue: / lock: / rate:）。

- queue:tasks      —— 主任务 Stream（消费组 workers，网关 XADD / dispatcher 重投）
- queue:delay      —— 退避 ZSET（score=run_at ms，网关 dispatcher 移出重投）
- queue:dlq        —— 重投超限待人工 Stream
- queue:sse:{task} —— SSE 进度 Stream（worker 写，网关只读转发）
- lock:task:{task} —— 跨 worker 防重复执行 SETNX
- lock:book:{pid}  —— 书级租约锁（同书串行、异书并行，§13 BYOK；网关闸门的第一道防线是
                      rate:inflight，resume 直发绕过闸门时书锁为权威）
- rate:inflight:{uid}:{pid} —— 每书并发闸门（异书并行、同书串行；worker 终态 SREM）
- rate:cost:{date} —— 全局日成本累计（worker 终态 INCRBYFLOAT）
"""

from __future__ import annotations

import redis

from aiink.config import settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """进程级 Redis 客户端单例（redis-py 自带连接池）。

    socket_timeout 必须 > consumer 的 XREADGROUP block(5s)：redis-py 8.x 默认
    socket 超时改为 5s，与 5s 阻塞读同值 → 读被误判超时（TimeoutError），worker
    反复掉退避、消费组活跃读者分布失衡（一个 worker 抢走全部消息，多进程并行失效）。
    """
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=10,
            health_check_interval=30,
        )
    return _client


def ensure_group() -> None:
    """幂等创建消费组（worker 启动时调用）。"""
    r = get_redis()
    try:
        r.xgroup_create(settings.worker_stream, settings.worker_group, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):  # 已存在则忽略
            raise


def stream_name() -> str:
    return settings.worker_stream


def delay_key() -> str:
    return "queue:delay"


def dlq_key() -> str:
    return "queue:dlq"


def sse_key(task_id: str) -> str:
    return f"queue:sse:{task_id}"


def lock_key(task_id: str) -> str:
    return f"lock:task:{task_id}"


def book_key(project_id: str) -> str:
    return f"lock:book:{project_id}"


def inflight_key(user_id: str, project_id: str) -> str:
    return f"rate:inflight:{user_id}:{project_id}"


def cost_key(date: str) -> str:
    return f"rate:cost:{date}"
