"""消费循环：普通/VIP 队列加权拉取 → process → 确认重投后 ack → TTL+DLX 延迟重试。

优雅停机（§17.2）：收 SIGTERM → 置 shutdown flag → 跑完当前任务（含 checkpoint）再退出；
未 ack 消息在连接断开时自动 requeue，重启后重新消费（RabbitMQ 崩溃认领，替换网关 dispatcher）。

重试（retry）：body.retry_count+1，`>= worker_max_retries` → basic_nack(requeue=false)
（主队列 DLX → queue:dlq）；否则发布到 queue:delay（expiration=退避毫秒，priority 随属性传递）。
书忙（defer）：发布到 queue:delay（expiration=固定 5s，不 bump retry_count）。
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pika

from myink.config import settings
from myink.maintenance import may_consume, MaintenanceUnavailable
from myink.worker import amqp
from myink.db import tenant_session
from myink.worker.handoff import record_handoff, publish_handoff, delivery_predecessor, replay_handoffs, body_hash, QueueAuthorityUnknown
from myink.worker.observer import observe
from myink.worker.processor import _is_retryable, process, valid_task_owner
from myink.worker.redis_client import get_redis, sse_key

logger = logging.getLogger(__name__)

_shutdown = threading.Event()


def _handle_sigterm(signum, frame):  # noqa: ARG001
    logger.info("收到 SIGTERM，跑完当前任务后退出")
    _shutdown.set()


def _heartbeat(r, worker_id: str) -> None:
    """worker 存活心跳（网关 /readyz 探活 + 运营判断崩溃）。"""
    while not _shutdown.is_set():
        try:
            r.set(f"queue:heartbeat:{worker_id}", "1", ex=settings.worker_heartbeat_interval * 3)
        except Exception:
            pass
        _shutdown.wait(settings.worker_heartbeat_interval)


def _process_with_events(body, worker_id, connection=None):
    """Keep Pika I/O and acknowledgements on the connection's own thread.

    Shutdown waits for this single task, including its checkpoint. A lost
    connection also waits for processing to finish before reconnecting: it
    must not start another task while the old thread still holds its locks.
    """
    if connection is None:
        return process(body, worker_id=worker_id)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='myink-task') as executor:
        future = executor.submit(copy_context().run, process, body, worker_id=worker_id)
        while not future.done():
            connection.process_data_events(time_limit=0.25)
        return future.result()


def _on_message(ch, method, properties, body_raw, r, worker_id: str, *, connection=None) -> None:
    """单条任务：SSE + observer + process + retry/defer/yield/terminal/skip 决策。"""
    if not may_consume():
        ch.stop_consuming()
        return
    try:
        body = json.loads(body_raw)
    except json.JSONDecodeError:
        logger.warning("坏消息丢弃: %s %r", method.delivery_tag, body_raw[:200])
        ch.basic_ack(method.delivery_tag)
        return

    try:
        owner_valid = isinstance(body, dict) and valid_task_owner(body)
        predecessor=None
        if owner_valid:
            with tenant_session(body["project_id"]) as db:
                predecessor=delivery_predecessor(db,body,properties)
    except QueueAuthorityUnknown:
        ch.basic_nack(method.delivery_tag, requeue=False)
        return
    except Exception as exc:
        if _is_retryable(exc):
            logger.warning("任务归属暂时无法验证，保留消息: delivery=%s", method.delivery_tag)
            ch.basic_nack(method.delivery_tag, requeue=True)
            return
        raise
    if not owner_valid:
        logger.warning("拒绝非法任务消息或归属不匹配: delivery=%s", method.delivery_tag)
        ch.basic_ack(method.delivery_tag)
        return
    task_id = body.get("task_id")
    logger.info("取到任务 %s (%s), delivery=%s", task_id, body.get("task_type"), method.delivery_tag)
    # 确保 SSE stream 存在（observer 只追加，首条 status 由 process 写）
    r.xadd(sse_key(task_id), {"event": "status", "task_id": task_id, "status": "queued"}, maxlen=1000)
    r.expire(sse_key(task_id), 3600)
    obs_stop = threading.Event()
    obs_thread = threading.Thread(target=observe, args=(task_id, obs_stop), daemon=True)
    obs_thread.start()
    try:
        decision = _process_with_events(body, worker_id, connection)
    except MaintenanceUnavailable:
        ch.stop_consuming()
        return
    except pika.exceptions.AMQPError:
        # Transport loss is not a bad task: closing the connection requeues
        # the unacked delivery. Never ACK it through the business-error branch.
        raise
    except Exception as exc:
        if _is_retryable(exc):
            logger.warning("任务前置检查暂时失败，保留消息: task=%s", task_id)
            ch.basic_nack(method.delivery_tag, requeue=True)
            return
        # 非预期异常（坏任务/校验失败）：丢弃不重试，worker 保持存活。
        # 可重试失败在 process 内部已分类返回 "retry"，到不了这里。
        logger.error("任务处理异常丢弃: %s task=%s err=%s", method.delivery_tag, task_id, exc)
        ch.basic_ack(method.delivery_tag)
        return
    finally:
        obs_stop.set()
        obs_thread.join(timeout=5)

    # 优先级随消息属性传递：延迟重投/书忙重投保留原优先级（VIP 优先贯穿退避循环）
    priority = int(properties.priority) if properties and properties.priority is not None else 0

    if decision == "retry" and int(body.get("retry_count", 0)) >= settings.worker_max_retries:
        # 重试超限 → 不 requeue → 主队列 DLX → queue:dlq（死信由 RabbitMQ 侧完成）
        ch.basic_nack(method.delivery_tag, requeue=False)
        logger.warning("重试超限进 DLQ: task=%s retry=%s", task_id, body.get("retry_count"))
        return

    if decision == 'yield':
        try:
            amqp.publish(json.dumps(body, ensure_ascii=False), amqp.KEY_TASKS, priority=priority)
        except Exception:
            logger.warning('批次续跑未确认，保留原消息: task=%s', task_id, exc_info=True)
            ch.basic_nack(method.delivery_tag, requeue=True)
            return
        ch.basic_ack(method.delivery_tag)
        return

    if decision in ("retry", "defer"):
        retry_count = int(body.get("retry_count", 0))
        outgoing = dict(body)
        if decision == "retry":
            outgoing["retry_count"] = retry_count + 1
            expiration = settings.worker_backoff_base * (2 ** retry_count) * 1000
        else:
            expiration = settings.worker_defer_backoff_s * 1000
        operation = "handoff:" + body["project_id"] + ":" + decision + ":" + body_hash({"body":outgoing,"predecessor":predecessor})
        with tenant_session(body["project_id"]) as db:
            record_handoff(db,outgoing,"delay",operation,priority=priority,expiration_ms=expiration,predecessor_id=predecessor)
        # The transaction context above has committed BEFORE acknowledging.
        ch.basic_ack(method.delivery_tag)
        publish_handoff(operation)
    elif decision == "terminal":
        ch.basic_ack(method.delivery_tag)
        logger.info("任务完成: %s", task_id)
    else:
        ch.basic_ack(method.delivery_tag)
    # skip: 无事可做


def run() -> None:
    """worker 主循环（阻塞，Ctrl+C / SIGTERM 退出；连接断开自动重连）。"""
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    r = get_redis()
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    logger.info("worker 启动: %s", worker_id)

    signal.signal(signal.SIGTERM, _handle_sigterm)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, _handle_sigterm)

    hb = threading.Thread(target=_heartbeat, args=(r, worker_id), daemon=True)
    hb.start()

    while not _shutdown.is_set():
        conn = None
        try:
            if not may_consume():
                _shutdown.wait(settings.worker_heartbeat_interval)
                continue
            replay_handoffs()
            conn = amqp.connect()
            ch = conn.channel()
            amqp.declare_topology(ch)
            from myink.worker.scheduling import FairScheduler
            from myink.platform_configuration import load_configuration, QueueWeights
            scheduler = FairScheduler()
            logger.info('开始公平调度 %s / %s', amqp.vip_queue(), amqp.main_queue())
            next_replay=time.monotonic()+5
            while not _shutdown.is_set() and may_consume():
                conn.process_data_events(time_limit=0)
                weights = load_configuration().get('queue_weights', QueueWeights().model_dump())
                if _shutdown.is_set() or not may_consume():
                    break
                delivery = scheduler.take(ch, weights)
                if delivery is None:
                    conn.sleep(0.5)
                else:
                    _on_message(ch, *delivery, r=r, worker_id=worker_id, connection=conn)
                if not _shutdown.is_set() and time.monotonic()>=next_replay:
                    replay_handoffs(max_operations=1)
                    next_replay=time.monotonic()+5
        except (pika.exceptions.AMQPConnectionError, pika.exceptions.ChannelWrongStateError) as exc:
            logger.warning("RabbitMQ 连接/通道异常，5s 后重连: %s", exc)
        except Exception as exc:
            logger.error("消费循环异常退出（待重连）: %s", exc)
        finally:
            if conn is not None and not conn.is_closed:
                try:
                    conn.close()
                except Exception:
                    pass
            _shutdown.wait(5)

    logger.info("worker 退出")
    hb.join(timeout=5)


if __name__ == "__main__":
    run()
