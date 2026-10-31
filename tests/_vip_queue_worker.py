"""Synthetic task boundary around the real consumer; no model vendor calls."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import pika
from myink.config import settings
from myink.worker import amqp, consumer
from myink.worker.redis_client import get_redis

r = get_redis()
probe = os.environ['VIP_PROBE_ID']
key = 'test:vip:' + probe


def connect():
    params = pika.URLParameters(settings.amqp_url)
    params.heartbeat = 2
    params.blocked_connection_timeout = 10
    return pika.BlockingConnection(params)


def process(body, worker_id):
    tid = body['task_id']
    r.rpush(key + ':starts', json.dumps({'id': tid, 'tier': body['tier'], 'pid': os.getpid()}))
    r.set(key + ':active:' + str(os.getpid()), tid)
    if body.get('hold'):
        deadline = time.monotonic() + 20
        while not r.get(key + ':release'):
            if time.monotonic() > deadline:
                raise TimeoutError('probe release not received')
            time.sleep(.02)
    time.sleep(body.get('delay', 0))
    if body.get('yield_once') and r.set(key + ':yielded:' + tid, '1', nx=True):
        return 'yield'
    # This models a durable terminal receipt; full graph/idempotency coverage
    # remains in test_multiprocess with the real processor and checkpoint DB.
    if r.set(key + ':committed:' + tid, '1', nx=True):
        r.rpush(key + ':done', tid)
    r.delete(key + ':active:' + str(os.getpid()))
    return 'terminal'


original_publish = amqp.publish_once


def publish_with_lost_confirm(body, routing_key, **kwargs):
    original_publish(body, routing_key, **kwargs)
    if r.set(key + ':confirm_lost', '1', nx=True):
        raise pika.exceptions.AMQPConnectionError('probe: confirmation lost after broker commit')


amqp.connect = connect
consumer.valid_task_owner = lambda body: body.get('probe') == probe
consumer.observe = lambda *args: None
consumer.process = process
if os.getenv('VIP_LOSE_CONFIRM') == '1':
    amqp.publish_once = publish_with_lost_confirm
consumer.run()
