"""RabbitMQ 连接与拓扑（worker 消费 + API/worker 发布共用）。

拓扑沿用 Go 网关 `gateway/internal/queue/amqp.go`（已退场）：producer/consumer/API 三端
幂等声明；参数不一致会 PRECONDITION_FAILED。

    myink.tasks (direct)
      ├─ key "tasks" → queue:tasks  (x-max-priority=10, DLX→myink.dlx/dlq)
      └─ key "delay" → queue:delay  (DLX→myink.tasks/tasks；无固定 TTL，逐条 expiration 退避)
      ├─ key "tasks.vip" → queue:tasks:vip  (FIFO, DLX→myink.dlx/dlq)
      └─ key "delay.vip" → queue:delay:vip  (DLX→myink.tasks/tasks.vip)
    myink.dlx (direct) → key "dlq" → queue:dlq

协议不变量（最高风险）：消息体 = 任务 JSON 本身（发出去就是任务字典，worker 单次
json.loads，不再包 {"body":...}）。

QUEUE_PREFIX 只用于测试隔离：对 exchange 与 queue 名统一加前缀（生产空串）。
"""

from __future__ import annotations

import threading

import pika

from myink.config import settings

EXCHANGE_TASKS = "myink.tasks"
EXCHANGE_DLX = "myink.dlx"
KEY_TASKS = "tasks"
KEY_DELAY = "delay"
KEY_DLQ = "dlq"


def _px() -> str:
    return settings.queue_prefix


def exchange() -> str:
    return EXCHANGE_TASKS + _px()


def dlx_exchange() -> str:
    return EXCHANGE_DLX + _px()


def main_queue() -> str:
    return "queue:tasks" + _px()


def vip_queue() -> str:
    return 'queue:tasks:vip' + _px()


def vip_delay_queue() -> str:
    return 'queue:delay:vip' + _px()


def tier_routing_key(routing_key: str, priority: int) -> str:
    if (priority == settings.priority_vip and priority != settings.priority_normal
            and routing_key in {KEY_TASKS, KEY_DELAY}):
        return routing_key + '.vip'
    return routing_key


def priority_for_user(user_id) -> int:
    """Resume messages use current membership, rather than an old token."""
    import uuid
    from myink.db import new_session
    from myink.models import User
    with new_session() as db:
        user = db.get(User, uuid.UUID(str(user_id)))
        return settings.priority_vip if user is not None and user.tier == 'vip' else settings.priority_normal


def delay_queue() -> str:
    return "queue:delay" + _px()


def dlq_queue() -> str:
    return "queue:dlq" + _px()


def connect() -> pika.BlockingConnection:
    """worker 消费连接：heartbeat=1800（批次任务可超 30 分钟默认看门狗，防通道被服务端杀掉）。

    返回 BlockingConnection（worker 单线程消费，非 asyncio 场景专用）。
    heartbeat/blocked_connection_timeout 是连接参数（非 URL 参数），URLParameters 只收 url。
    """
    params = pika.URLParameters(settings.amqp_url)
    params.heartbeat = 1800
    params.blocked_connection_timeout = None
    return pika.BlockingConnection(params)


def declare_topology(ch: pika.channel.Channel) -> None:
    """幂等声明拓扑；保留普通队列原参数，新增 VIP 队列无需清理已有消息。"""
    ch.exchange_declare(exchange(), exchange_type="direct", durable=True)
    # 主队列：优先级 + 死信 → myink.dlx/dlq
    ch.queue_declare(
        main_queue(),
        durable=True,
        arguments={
            "x-max-priority": 10,
            "x-dead-letter-exchange": dlx_exchange(),
            "x-dead-letter-routing-key": KEY_DLQ,
        },
    )
    ch.queue_bind(main_queue(), exchange(), KEY_TASKS)
    # 延迟队列：无固定 TTL，消息逐条带 expiration 死信回主队列实现退避（零插件）
    ch.queue_declare(
        delay_queue(),
        durable=True,
        arguments={
            "x-dead-letter-exchange": exchange(),
            "x-dead-letter-routing-key": KEY_TASKS,
        },
    )
    ch.queue_bind(delay_queue(), exchange(), KEY_DELAY)
    # 死信交换机 + 死信队列
    ch.exchange_declare(dlx_exchange(), exchange_type="direct", durable=True)
    ch.queue_declare(dlq_queue(), durable=True)
    ch.queue_bind(dlq_queue(), dlx_exchange(), KEY_DLQ)
    # Keep the existing normal queue and drain pre-upgrade deliveries.
    # New VIP deliveries use a FIFO queue with their own delay return route.
    ch.queue_declare(vip_queue(), durable=True, arguments={
        'x-dead-letter-exchange': dlx_exchange(), 'x-dead-letter-routing-key': KEY_DLQ})
    ch.queue_bind(vip_queue(), exchange(), KEY_TASKS + '.vip')
    ch.queue_declare(vip_delay_queue(), durable=True, arguments={
        'x-dead-letter-exchange': exchange(), 'x-dead-letter-routing-key': KEY_TASKS + '.vip'})
    ch.queue_bind(vip_delay_queue(), exchange(), KEY_DELAY + '.vip')


# 模块级发布连接（publisher confirm）：API 路由线程池 / worker 重投共用，锁串行。
_publish_lock = threading.Lock()
_publish_conn: pika.BlockingConnection | None = None


def publish(body: str, routing_key: str, priority: int = 0, expiration_ms: int | None = None) -> None:
    """发布到 myink.tasks 交换机（持久化 + 优先级 + publisher confirm）。

    routing_key: KEY_TASKS（主队列）/ KEY_DELAY（延迟退避）。expiration_ms 非空时设置
    逐条 TTL（毫秒）——延迟队列 DLX 回主队列实现退避。
    阻塞式 confirm：broker nack / 连接断开抛 pika 异常；连接失效自动重建。
    """
    routing_key = tier_routing_key(routing_key, priority)
    global _publish_conn
    with _publish_lock:
        try:
            if _publish_conn is None or _publish_conn.is_closed:
                _publish_conn = connect()
            ch = _publish_conn.channel()
            declare_topology(ch)
            ch.confirm_delivery()  # 阻塞式 publisher confirm
            properties = pika.BasicProperties(delivery_mode=2, priority=priority)
            if expiration_ms is not None:
                properties.expiration = str(int(expiration_ms))
            ch.basic_publish(exchange=exchange(), routing_key=routing_key, body=body, properties=properties, mandatory=True)
        except pika.exceptions.AMQPError:
            # 连接/通道失效：重建连接重试一次；仍失败抛给调用方（API 侧 503）
            try:
                if _publish_conn is not None and not _publish_conn.is_closed:
                    _publish_conn.close()
            except Exception:
                pass
            _publish_conn = connect()
            ch = _publish_conn.channel()
            declare_topology(ch)
            ch.confirm_delivery()
            properties = pika.BasicProperties(delivery_mode=2, priority=priority)
            if expiration_ms is not None:
                properties.expiration = str(int(expiration_ms))
            ch.basic_publish(exchange=exchange(), routing_key=routing_key, body=body, properties=properties, mandatory=True)


class PublishNotSent(Exception):
    """The resume message definitely did not reach the queue."""


def publish_once(body: str, routing_key: str, priority: int = 0) -> None:
    """No implicit retry after a lost confirm; bounded and mandatory delivery."""
    routing_key = tier_routing_key(routing_key, priority)
    connection = None
    try:
        params = pika.URLParameters(settings.amqp_url)
        params.connection_attempts = 1
        params.socket_timeout = 10
        params.stack_timeout = 15
        params.blocked_connection_timeout = 10
        params.heartbeat = 30
        try:
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            declare_topology(channel)
            channel.confirm_delivery()
        except Exception as exc:
            raise PublishNotSent("续跑队列连接未建立") from exc
        try:
            channel.basic_publish(exchange=exchange(), routing_key=routing_key, body=body,
                                  properties=pika.BasicProperties(delivery_mode=2, priority=priority), mandatory=True)
        except (pika.exceptions.NackError, pika.exceptions.UnroutableError) as exc:
            raise PublishNotSent("续跑投递被拒绝") from exc
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
