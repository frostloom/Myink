"""Exercise the real worker loop while isolating only external I/O."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import pika

from myink.worker import amqp, consumer


class LoopChannel:
    def __init__(self):
        self.callback = None
        self.queue = None

    def basic_qos(self, **kwargs):
        pass

    def basic_consume(self, queue, callback):
        self.queue, self.callback = queue, callback

    def basic_get(self, queue, auto_ack):
        return SimpleNamespace(delivery_tag=1), None, queue


class LoopConnection:
    def __init__(self):
        self.ch = LoopChannel()
        self.is_closed = False
        self.ticks = 0

    def channel(self):
        return self.ch

    def process_data_events(self, time_limit):
        self.ticks += 1
        # Reproduce the old push loop as well as the new pull loop.
        if self.ch.callback and time_limit:
            self.ch.callback(self.ch, SimpleNamespace(delivery_tag=1), None, self.ch.queue)

    def sleep(self, seconds):
        self.process_data_events(seconds)

    def close(self):
        self.is_closed = True


def test_real_run_dispatches_weighted_queues_then_closes_on_sigterm(monkeypatch):
    conn = LoopConnection()
    stop = threading.Event()
    monkeypatch.setattr(consumer, '_shutdown', stop)
    monkeypatch.setattr(consumer.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(consumer, 'get_redis', Mock)
    monkeypatch.setattr(amqp, 'connect', lambda: conn)
    monkeypatch.setattr(amqp, 'declare_topology', lambda ch: None)
    monkeypatch.setattr('myink.platform_configuration.load_configuration', lambda: {'queue_weights': {'vip': 3, 'normal': 1}})
    seen = []
    def handle(ch, method, props, body, *args, **kwargs):
        seen.append(body)
        if len(seen) == 4:
            consumer._handle_sigterm(None, None)
    monkeypatch.setattr(consumer, '_on_message', handle)
    consumer.run()
    assert seen == [amqp.vip_queue(), amqp.vip_queue(), amqp.vip_queue(), amqp.main_queue()]
    assert conn.is_closed
    assert conn.ticks >= 4


def test_blocking_task_keeps_connection_events_alive_until_completion(monkeypatch):
    started, release = threading.Event(), threading.Event()
    thread_ids = []
    def process(body, worker_id):
        thread_ids.append(threading.get_ident())
        started.set()
        assert release.wait(2), 'worker I/O thread did not keep pumping events'
        return 'terminal'
    class Connection:
        def process_data_events(self, time_limit):
            assert started.wait(2)
            release.set()
    monkeypatch.setattr(consumer, 'process', process)
    assert consumer._process_with_events({}, 'worker', Connection()) == 'terminal'
    assert thread_ids != [threading.get_ident()]


def test_idle_loop_pumps_events_and_stops_without_fetching_again(monkeypatch):
    conn = LoopConnection()
    stop = threading.Event()
    monkeypatch.setattr(consumer, '_shutdown', stop)
    monkeypatch.setattr(consumer.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(consumer, 'get_redis', Mock)
    monkeypatch.setattr(amqp, 'connect', lambda: conn)
    monkeypatch.setattr(amqp, 'declare_topology', lambda ch: None)
    monkeypatch.setattr('myink.platform_configuration.load_configuration', lambda: {'queue_weights': {'vip': 3, 'normal': 1}})
    fetches = []
    def get(queue, auto_ack):
        fetches.append(queue)
        return None, None, None
    conn.ch.basic_get = get
    def sleep(seconds):
        conn.ticks += 1
        consumer._handle_sigterm(None, None)
    conn.sleep = sleep
    # Old basic_consume never calls sleep; bound that path to avoid hanging.
    old_events = conn.process_data_events
    def events(time_limit):
        old_events(0)
        if time_limit:
            stop.set()
    conn.process_data_events = events
    consumer.run()
    assert fetches == [amqp.vip_queue(), amqp.main_queue()]
    assert conn.is_closed


def test_processor_error_propagates_after_io_pump(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('processor failed')
    monkeypatch.setattr(consumer, 'process', fail)
    with pytest.raises(RuntimeError, match='processor failed'):
        consumer._process_with_events({}, 'worker', Mock())


def test_connection_loss_during_processing_leaves_delivery_unacked(temp_project, monkeypatch):
    import json
    from myink.workflow.runner import new_task
    from test_worker import _body
    tid = new_task(project_id=temp_project, task_type="chapter_generate", payload={"seq": 1})
    body = _body(tid, temp_project, payload={"seq": 1})
    release = threading.Event()
    finished = threading.Event()
    def process(*args, **kwargs):
        assert release.wait(2)
        finished.set()
        return 'terminal'
    class Connection:
        def process_data_events(self, time_limit):
            release.set()
            raise pika.exceptions.AMQPConnectionError('connection lost')
    acknowledgements = []
    ch = Mock()
    ch.basic_ack.side_effect = lambda *a: acknowledgements.append('ack')
    ch.basic_nack.side_effect = lambda *a, **k: acknowledgements.append('nack')
    monkeypatch.setattr(consumer, 'process', process)
    monkeypatch.setattr(consumer, 'observe', lambda *a: None)
    with pytest.raises(pika.exceptions.AMQPConnectionError):
        consumer._on_message(ch, SimpleNamespace(delivery_tag=1), None,
            json.dumps(body), Mock(), 'worker', connection=Connection())
    assert finished.is_set()
    assert acknowledgements == []


def test_sigterm_received_by_event_pump_prevents_next_fetch(monkeypatch):
    conn = LoopConnection()
    stop = threading.Event()
    monkeypatch.setattr(consumer, '_shutdown', stop)
    monkeypatch.setattr(consumer.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(consumer, 'get_redis', Mock)
    monkeypatch.setattr(amqp, 'connect', lambda: conn)
    monkeypatch.setattr(amqp, 'declare_topology', lambda ch: None)
    monkeypatch.setattr('myink.platform_configuration.load_configuration', lambda: {'queue_weights': {'vip': 3, 'normal': 1}})
    fetches = []
    def get(queue, auto_ack):
        fetches.append(queue)
        return None, None, None
    conn.ch.basic_get = get
    conn.process_data_events = lambda time_limit: consumer._handle_sigterm(None, None)
    consumer.run()
    assert fetches == []
    assert conn.is_closed
