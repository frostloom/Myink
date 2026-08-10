"""消费循环：XREADGROUP 阻塞读 → process → XACK → 可重试失败进退避 ZSET。

优雅停机（§17.2）：收 SIGTERM → 置 shutdown flag → 跑完当前任务（含 checkpoint）
再退出；未拉取消息留在消费组 PENDING，网关 dispatcher 认领重投 → 断点续跑。
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import threading
import time

from aiink.config import settings
from aiink.worker.observer import observe
from aiink.worker.processor import process
from aiink.worker.redis_client import (
    delay_key,
    ensure_group,
    get_redis,
    sse_key,
    stream_name,
)

logger = logging.getLogger(__name__)

_shutdown = threading.Event()


def _handle_sigterm(signum, frame):  # noqa: ARG001
    logger.info("收到 SIGTERM，跑完当前任务后退出")
    _shutdown.set()


def _heartbeat(r, worker_id: str) -> None:
    """worker 存活心跳（网关 /readyz 探活 + guardian 判断崩溃）。"""
    while not _shutdown.is_set():
        try:
            r.set(f"queue:heartbeat:{worker_id}", "1", ex=settings.worker_heartbeat_interval * 3)
        except Exception:
            pass
        _shutdown.wait(settings.worker_heartbeat_interval)


def run() -> None:
    """worker 主循环（阻塞，Ctrl+C / SIGTERM 退出）。"""
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    r = get_redis()
    ensure_group()
    # 多进程并行（§13）：消费组天然支持多消费者，用 PID 区分进程。
    # 原 threading.get_ident() 在同一台机多个 worker 进程间会撞名 → XREADGROUP 同消费者名
    # 会互相抢 PENDING、重复消费；PID 全局唯一，异书并行靠多 worker 进程实现。
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    logger.info("worker 启动: %s stream=%s group=%s", worker_id, settings.worker_stream, settings.worker_group)

    signal.signal(signal.SIGTERM, _handle_sigterm)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, _handle_sigterm)

    hb = threading.Thread(target=_heartbeat, args=(r, worker_id), daemon=True)
    hb.start()

    stream = stream_name()
    group = settings.worker_group
    consumer = f"worker-{socket.gethostname()}-{os.getpid()}"

    while not _shutdown.is_set():
        try:
            resp = r.xreadgroup(group, consumer, {stream: ">"}, count=1, block=5000)
        except Exception as exc:
            logger.warning("XREADGROUP 异常（可忽略，退避后重试）: %s", exc)
            _shutdown.wait(2)
            continue
        if not resp:
            continue
        for _, entries in resp:
            for entry_id, fields in entries:
                try:
                    body = json.loads(fields["body"])
                except (KeyError, json.JSONDecodeError):
                    logger.warning("坏消息丢弃: %s fields=%s", entry_id, fields)
                    r.xack(stream, group, entry_id)
                    continue

                logger.info("取到任务 %s (%s), entry=%s", body.get("task_id"), body.get("task_type"), entry_id)
                task_id = body.get("task_id")
                # 确保 SSE stream 存在（observer 只追加，首条 status 由 process 写）
                r.xadd(sse_key(task_id), {"event": "status", "task_id": task_id, "status": "queued"}, maxlen=1000)
                r.expire(sse_key(task_id), 3600)
                obs_stop = threading.Event()
                obs_thread = threading.Thread(
                    target=observe, args=(task_id, obs_stop), daemon=True
                )
                obs_thread.start()
                try:
                    decision = process(body, worker_id=worker_id)
                except Exception as exc:
                    # 非预期异常（坏任务/校验失败）：丢弃不重试，worker 保持存活。
                    # 可重试失败在 process 内部已分类返回 "retry"，到不了这里。
                    logger.error("任务处理异常丢弃: %s task=%s err=%s", entry_id, task_id, exc)
                    r.xack(stream, group, entry_id)
                    continue
                finally:
                    obs_stop.set()
                    obs_thread.join(timeout=5)
                # 处理完才 ack（§阶段2：处理后 ack，崩溃留 PENDING 由 guardian 认领）
                r.xack(stream, group, entry_id)
                if decision == "retry":
                    backoff_s = settings.worker_backoff_base * (2 ** int(body.get("retry_count", 0)))
                    run_at = int(time.time() * 1000) + backoff_s * 1000
                    body["retry_count"] = int(body.get("retry_count", 0)) + 1
                    r.zadd(delay_key(), {json.dumps(body): run_at})
                    logger.info("退避重投: %s +%ss (retry=%s)", body.get("task_id"), backoff_s, body.get("retry_count"))
                elif decision == "defer":
                    # 书忙固定退避：不计 retry_count（书忙是瞬态非失败）→ 永远不过 MaxRetries，
                    # 重投不经 DLQ；书锁释放后下次重投即执行。同书任务在多个 worker 间自然串行。
                    run_at = int(time.time() * 1000) + settings.worker_defer_backoff_s * 1000
                    r.zadd(delay_key(), {json.dumps(body): run_at})
                    logger.info("书忙退避重投: %s book=%s +%ss",
                                body.get("task_id"), body.get("project_id"), settings.worker_defer_backoff_s)
                elif decision == "terminal":
                    logger.info("任务完成: %s", body.get("task_id"))
                # skip: 无事可做

    logger.info("worker 退出")
    hb.join(timeout=5)


if __name__ == "__main__":
    run()
