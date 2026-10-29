"""A committed outbox retains delayed work before the delivery is acknowledged."""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import pika
from sqlalchemy import select

from myink.db import new_session, tenant_session
from myink.models import Project
from myink.models.maintenance import QueueHandoff
from myink.maintenance import register_admission
from myink.worker import consumer


@pytest.mark.parametrize("decision", ["retry", "defer"])
@pytest.mark.parametrize("publish_fails", [False, True])
def test_delay_handoff_is_durable_before_delivery_ack(temp_project, monkeypatch, decision, publish_fails):
    with new_session() as db:
        owner = str(db.get(Project, uuid.UUID(temp_project)).user_id)
    tid = str(uuid.uuid4())
    original = dict(task_id=tid, request_id=tid, project_id=temp_project,
                    user_id=owner, task_type="chapter_generate", payload={"seq": 1}, retry_count=0)
    with tenant_session(temp_project) as db:
        register_admission(db, original, priority=5)
    actions = []
    channel = Mock()
    def acknowledge(tag):
        with tenant_session(temp_project) as db:
            row = db.scalar(select(QueueHandoff).where(QueueHandoff.task_id == uuid.UUID(tid)))
            assert row.state == "pending" and row.destination == "delay"
            assert row.priority == 5
            assert row.rebuild_payload["retry_count"] == (1 if decision == "retry" else 0)
        actions.append(("ack", tag))
    channel.basic_ack.side_effect = acknowledge
    channel.basic_nack.side_effect = lambda tag, **kw: actions.append(("nack", kw["requeue"]))
    monkeypatch.setattr(consumer, "process", lambda body, **kw: decision)
    monkeypatch.setattr(consumer, "observe", lambda *args: None)
    def publish(body, key, *, priority, expiration_ms, operation_id):
        payload = json.loads(body)
        assert payload["retry_count"] == (1 if decision == "retry" else 0)
        assert key == consumer.amqp.KEY_DELAY and priority == 5 and expiration_ms > 0
        with tenant_session(temp_project) as db:
            row = db.get(QueueHandoff, operation_id)
            assert row.state == "unknown" and row.rebuild_payload == payload
        actions.append(("publish", payload["task_id"]))
        if publish_fails:
            raise pika.exceptions.AMQPConnectionError("connection lost before confirmation")
    monkeypatch.setattr(consumer.amqp, "publish_once", publish)
    consumer._on_message(channel, SimpleNamespace(delivery_tag=42), SimpleNamespace(priority=5),
                         json.dumps(original), Mock(), "worker-1")
    assert actions == [("ack", 42), ("publish", tid)]
    with tenant_session(temp_project) as db:
        row = db.scalar(select(QueueHandoff).where(QueueHandoff.task_id == uuid.UUID(tid)))
        assert row.state == ("unknown" if publish_fails else "published")
        assert row.rebuild_payload["task_id"] == tid
