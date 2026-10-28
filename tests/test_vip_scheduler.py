"""Continuous premium traffic cannot starve normal dispatch or monopolize a batch."""
from types import SimpleNamespace
import json
from unittest.mock import Mock
from typing import TypedDict

import pytest
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from myink.worker import amqp, consumer, processor


def test_weighted_dispatch_is_bounded_with_both_queues_busy():
    from myink.worker.scheduling import FairScheduler
    scheduler = FairScheduler()
    class Channel:
        def basic_get(self, queue, auto_ack):
            assert auto_ack is False
            return SimpleNamespace(delivery_tag=queue), None, queue
    actual = [scheduler.take(Channel(), {'vip': 3, 'normal': 1})[2] for _ in range(12)]
    assert actual == [amqp.vip_queue(), amqp.vip_queue(), amqp.vip_queue(), amqp.main_queue()] * 3


def test_empty_queue_lends_all_slots_without_consuming_messages_early():
    from myink.worker.scheduling import FairScheduler
    scheduler = FairScheduler()
    class Channel:
        def basic_get(self, queue, auto_ack):
            return (None, None, None) if queue == amqp.vip_queue() else (SimpleNamespace(delivery_tag=1), None, b'normal')
    assert [scheduler.take(Channel(), {'vip': 3, 'normal': 1})[2] for _ in range(8)] == [b'normal'] * 8


def test_real_broker_keeps_retry_in_original_tier():
    with amqp.connect() as conn:
        ch = conn.channel()
        amqp.declare_topology(ch)
        for queue in [amqp.main_queue(), amqp.vip_queue(), amqp.vip_delay_queue()]:
            ch.queue_purge(queue)
        amqp.publish_once('normal', amqp.KEY_TASKS, priority=0)
        amqp.publish_once('vip', amqp.KEY_TASKS, priority=9)
        assert ch.basic_get(amqp.main_queue(), auto_ack=True)[2] == b'normal'
        assert ch.basic_get(amqp.vip_queue(), auto_ack=True)[2] == b'vip'
        amqp.publish('retry', amqp.KEY_DELAY, priority=9, expiration_ms=1)
        import time
        deadline = time.monotonic() + 5
        body = None
        while time.monotonic() < deadline:
            _, _, body = ch.basic_get(amqp.vip_queue(), auto_ack=True)
            if body: break
            conn.sleep(.05)
        assert body == b'retry'
        assert ch.basic_get(amqp.main_queue(), auto_ack=True)[0] is None


@pytest.mark.parametrize('fails', [False, True])
def test_batch_yield_confirm_precedes_ack_without_retry_charge(monkeypatch, fails):
    events = []
    monkeypatch.setattr(consumer, 'valid_task_owner', lambda body: True)
    monkeypatch.setattr(consumer, 'process', lambda *a, **k: 'yield')
    monkeypatch.setattr(consumer, 'observe', lambda *a: None)
    ch = Mock()
    ch.basic_ack.side_effect = lambda *a: events.append('ack')
    ch.basic_nack.side_effect = lambda *a, **k: events.append('nack')
    def publish(body, key, **kwargs):
        events.append('publish')
        assert json.loads(body)['retry_count'] == 0
        assert key == amqp.KEY_TASKS and kwargs['priority'] == 9
        if fails: raise ConnectionError('confirm lost')
    monkeypatch.setattr(amqp, 'publish', publish)
    consumer._on_message(ch, SimpleNamespace(delivery_tag=1), SimpleNamespace(priority=9),
                         json.dumps({'task_id': 'batch', 'retry_count': 0}), Mock(), 'worker')
    assert events == ['publish', 'nack' if fails else 'ack']


def test_yield_retains_inflight_and_does_not_accumulate_cost(monkeypatch):
    monkeypatch.setattr(processor, '_release_inflight', lambda body: pytest.fail('must retain inflight'))
    monkeypatch.setattr(processor, '_accumulate_cost', lambda body: pytest.fail('not yet terminal'))
    processor._finish({'task_id': 'batch', 'retry_count': 0}, 'yield')


def test_batch_slice_resumes_checkpoint_without_repeating_finished_chapter():
    from myink.worker.scheduling import invoke_batch_slice
    class State(TypedDict):
        position: int
    visited = []
    graph = StateGraph(State)
    graph.add_node('chapter', lambda s: visited.append(s['position']) or {})
    graph.add_node('bridge', lambda s: {'position': s['position'] + 1})
    graph.add_edge(START, 'chapter')
    graph.add_conditional_edges('chapter', lambda s: 'bridge' if s['position'] < 2 else END)
    graph.add_edge('bridge', 'chapter')
    compiled = graph.compile(checkpointer=InMemorySaver())
    config = {'configurable': {'thread_id': 'batch'}, 'recursion_limit': 64}
    assert invoke_batch_slice(compiled, {'position': 0}, config)['scheduler_yield']
    assert visited == [0]
    assert invoke_batch_slice(compiled, None, config)['scheduler_yield']
    assert visited == [0, 1]
    assert not invoke_batch_slice(compiled, None, config).get('scheduler_yield')
    assert visited == [0, 1, 2]


@pytest.mark.parametrize('status,decision', [('running', 'yield'), ('paused', 'terminal'), ('cancelled', 'terminal')])
def test_pause_racing_with_chapter_yield_is_preserved(temp_project, monkeypatch, status, decision):
    import uuid
    from myink.db import new_session
    from myink.models import Task
    tid = uuid.uuid4()
    with new_session() as db:
        db.add(Task(id=tid, project_id=uuid.UUID(temp_project), task_type='batch_generate', status=status, payload={}))
        db.commit()
    monkeypatch.setattr(processor, '_dispatch', lambda body: {'scheduler_yield': True})
    monkeypatch.setattr(processor, '_pub_status', lambda *a, **k: None)
    try:
        assert processor._run_bound({}, str(tid), 'batch_generate', temp_project) == decision
        with new_session() as db:
            assert db.get(Task, tid).status == ('queued' if status == 'running' else status)
    finally:
        with new_session() as db:
            db.query(Task).filter_by(id=tid).delete()
            db.commit()


@pytest.mark.parametrize('status,expected', [('paused', 'skip'), ('queued', 'waiting')])
def test_resumed_batch_continuation_honors_a_later_pause(temp_project, monkeypatch, status, expected):
    import uuid
    from myink.db import new_session
    from myink.models import Task
    from myink.workflow.runner import new_task
    from test_worker import _body
    tid = new_task(project_id=temp_project, task_type='batch_generate', payload={'start': 1, 'size': 3})
    with new_session() as db:
        db.get(Task, uuid.UUID(tid)).status = status
        db.commit()
    monkeypatch.setattr(processor, '_run', lambda *args: 'waiting')
    # A previous manual resume makes subsequent automatic chapter messages
    # batch_resume too; their type cannot override a newer user pause.
    assert processor.process(_body(tid, temp_project, task_type='batch_resume')) == expected
    with new_session() as db:
        assert db.get(Task, uuid.UUID(tid)).status == ('paused' if status == 'paused' else 'running')
