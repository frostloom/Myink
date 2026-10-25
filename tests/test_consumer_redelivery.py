"""A delay publication must be confirmed before the original delivery is removed."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import pika

from myink.worker import consumer


@pytest.mark.parametrize("decision", ["retry", "defer"])
@pytest.mark.parametrize("publish_fails", [False, True])
def test_delay_handoff_keeps_delivery_until_publish_succeeds(monkeypatch, decision, publish_fails):
    actions = []
    channel = Mock()
    channel.basic_ack.side_effect = lambda tag: actions.append(("ack", tag))
    channel.basic_nack.side_effect = lambda tag, **kw: actions.append(("nack", kw["requeue"]))
    monkeypatch.setattr(consumer, "valid_task_owner", lambda body: True)
    monkeypatch.setattr(consumer, "process", lambda body, **kw: decision)
    monkeypatch.setattr(consumer, "observe", lambda *args: None)

    def publish(body, key, *, priority, expiration_ms):
        payload = json.loads(body)
        assert payload["retry_count"] == (1 if decision == "retry" else 0)
        assert key == consumer.amqp.KEY_DELAY and priority == 5 and expiration_ms > 0
        actions.append(("publish", payload["task_id"]))
        if publish_fails:
            raise pika.exceptions.AMQPConnectionError("connection lost before confirmation")

    monkeypatch.setattr(consumer.amqp, "publish", publish)
    try:
        consumer._on_message(channel, SimpleNamespace(delivery_tag=42), SimpleNamespace(priority=5),
                             json.dumps({"task_id": "task-1", "retry_count": 0}), Mock(), "worker-1")
    except pika.exceptions.AMQPConnectionError:
        pass
    assert actions[0] == ("publish", "task-1")
    if publish_fails:
        assert ("ack", 42) not in actions
        assert actions[-1] == ("nack", True)
    else:
        assert actions == [("publish", "task-1"), ("ack", 42)]
