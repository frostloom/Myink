"""Real broker, worker processes and Redis with a unique queue namespace."""
from collections import Counter
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pika
import pytest

from myink.config import settings
from myink.worker import amqp
from myink.worker.redis_client import get_redis, sse_key


def eventually(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.03)
    pytest.fail('worker probe did not reach the expected state')


@pytest.fixture
def probe(temp_project, monkeypatch, tmp_path):
    from myink.db import new_session, tenant_session
    from myink.models import Project
    from myink.maintenance import register_admission, intent_outcome
    with new_session() as db:
        owner = str(db.get(Project, uuid.UUID(temp_project)).user_id)
    probe_id = uuid.uuid4().hex
    queue_prefix = '-vip-' + probe_id
    monkeypatch.setattr(amqp, 'settings', replace(settings, queue_prefix=queue_prefix))
    r = get_redis()
    key = 'test:vip:' + probe_id
    processes, logs, tids = [], [], []
    conn = amqp.connect()
    channel = conn.channel()
    amqp.declare_topology(channel)
    channel.confirm_delivery()

    def start(lose_confirm=False):
        log = (tmp_path / f'worker-{len(processes)}.log').open('w')
        child = subprocess.Popen([sys.executable, str(Path(__file__).with_name('_vip_queue_worker.py'))],
            stdout=log, stderr=log, env={**os.environ, 'QUEUE_PREFIX': queue_prefix,
                'VIP_PROBE_ID': probe_id, 'VIP_LOSE_CONFIRM': '1' if lose_confirm else '0'})
        processes.append(child)
        logs.append(log)
        eventually(lambda: bool(r.keys(f'queue:heartbeat:*-{child.pid}')))
        return child

    def publish(tier, **values):
        tid = str(uuid.uuid4())
        tids.append(tid)
        priority = 9 if tier == 'vip' else 0
        body = {'task_id': tid, 'request_id': tid, 'project_id': temp_project,
                'user_id': owner, 'task_type': 'chapter_generate', 'payload': {},
                'probe': probe_id, 'tier': tier, 'retry_count': 0, **values}
        with tenant_session(temp_project) as db:
            intent_id = register_admission(db, body, priority=priority)
        intent_outcome(intent_id, temp_project, publication_state="unknown")
        channel.basic_publish(exchange=amqp.exchange(),
            routing_key=amqp.tier_routing_key(amqp.KEY_TASKS, priority), body=json.dumps(body),
            properties=pika.BasicProperties(delivery_mode=2, priority=priority), mandatory=True)
        intent_outcome(intent_id, temp_project, publication_state="published")
        return tid

    class Probe:
        def starts(self):
            return [json.loads(item) for item in r.lrange(key + ':starts', 0, -1)]
        def done(self):
            return r.lrange(key + ':done', 0, -1)
    result = Probe()
    result.start, result.publish, result.r, result.key, result.channel = start, publish, r, key, channel
    try:
        yield result
    finally:
        for child in processes:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        for log in logs:
            log.close()
        for queue in (amqp.main_queue(), amqp.delay_queue(), amqp.vip_queue(), amqp.vip_delay_queue(), amqp.dlq_queue()):
            channel.queue_delete(queue)
        channel.exchange_delete(amqp.exchange())
        channel.exchange_delete(amqp.dlx_exchange())
        conn.close()
        keys = list(r.scan_iter(key + ':*')) + [sse_key(tid) for tid in tids]
        for child in processes:
            keys += list(r.scan_iter(f'queue:heartbeat:*-{child.pid}'))
        if keys:
            r.delete(*keys)


def test_worker_consumes_both_tiers_with_bounded_normal_opportunities(probe):
    for _ in range(12):
        probe.publish('vip')
    for _ in range(4):
        probe.publish('normal')
    probe.start()
    eventually(lambda: len(probe.done()) == 16)
    assert [entry['tier'] for entry in probe.starts()] == ['vip', 'vip', 'vip', 'normal'] * 4


def test_two_workers_serve_normals_while_vip_backlog_remains(probe):
    tasks = [probe.publish('vip', delay=.02, hold=True) for _ in range(100)]
    tasks += [probe.publish('normal', delay=.02, hold=True) for _ in range(4)]
    first, second = probe.start(), probe.start()
    eventually(lambda: all(probe.r.exists(probe.key + ':active:' + str(child.pid)) for child in (first, second)))
    probe.r.set(probe.key + ':release', '1')
    eventually(lambda: len(probe.done()) == 104)
    entries = probe.starts()
    normals = [i for i, item in enumerate(entries) if item['tier'] == 'normal']
    assert normals[0] <= 6
    assert normals[-1] < 40
    assert len({item['pid'] for item in entries}) == 2
    assert Counter(probe.done()) == Counter(tasks)


def test_long_task_keeps_heartbeat_and_sigterm_finishes_only_current_delivery(probe):
    running = probe.publish('vip', hold=True)
    queued = probe.publish('normal')
    child = probe.start()
    eventually(lambda: probe.r.get(probe.key + ':active:' + str(child.pid)) == running)
    time.sleep(5)  # More than twice the negotiated 2s AMQP heartbeat timeout.
    assert child.poll() is None
    child.terminate()
    probe.r.set(probe.key + ':release', '1')
    assert child.wait(timeout=10) == 0
    assert probe.done() == [running]
    assert queued not in [item['id'] for item in probe.starts()]
    assert probe.channel.basic_get(amqp.vip_queue(), auto_ack=True)[0] is None
    _, _, body = probe.channel.basic_get(amqp.main_queue(), auto_ack=True)
    assert json.loads(body)['task_id'] == queued


def test_killed_worker_redelivers_unacked_vip_to_replacement(probe):
    tid = probe.publish('vip', hold=True)
    child = probe.start()
    eventually(lambda: probe.r.get(probe.key + ':active:' + str(child.pid)) == tid)
    child.kill()
    child.wait(timeout=5)
    probe.r.set(probe.key + ':release', '1')
    probe.start()
    eventually(lambda: probe.done() == [tid])
    assert [item['id'] for item in probe.starts()] == [tid, tid]


def test_lost_yield_confirmation_does_not_lose_task_or_repeat_terminal_receipt(probe):
    tid = probe.publish('vip', yield_once=True)
    probe.start(lose_confirm=True)
    eventually(lambda: probe.r.exists(probe.key + ':confirm_lost') and len(probe.starts()) >= 3)
    eventually(lambda: probe.done() == [tid])
    assert {item['id'] for item in probe.starts()} == {tid}
    assert Counter(probe.done()) == {tid: 1}
