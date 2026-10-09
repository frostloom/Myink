"""Ownership and durable extension idempotency at the HTTP boundary."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from conftest import identity_headers
from myink.api.main import app
from myink.db import tenant_session
from myink.models import Task
from myink.models.task_budget import TaskBudget
from myink.task_budget import ensure_task_budget, budget_view
from test_task_budget import budget_task  # noqa:F401

client = TestClient(app)


@pytest.fixture
def paused_budget(budget_task):
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests":1})
    with tenant_session(pid) as db:
        db.get(Task, uuid.UUID(tid)).status = "paused"
        row = db.get(TaskBudget, uuid.UUID(tid))
        row.requests_used = 1
        row.pause_reason = "request_limit"
        row.stage = "audit"
    return tid, pid, uid


def _body(op=None, **kwargs):
    return {"operation_id":op or str(uuid.uuid4()), "add_requests":2, **kwargs}


def test_budget_is_visible_and_empty_resume_rejects_exhaustion(paused_budget, monkeypatch):
    tid, pid, uid = paused_budget
    sent = []
    monkeypatch.setattr("myink.worker.amqp.publish_once", lambda *a, **kw:sent.append(a))
    headers = identity_headers(uid)
    response = client.get(f"/api/v1/tasks/{tid}", headers=headers)
    assert response.status_code == 200
    assert response.json()["budget"]["requests_used"] == 1
    response = client.post(f"/api/v1/tasks/{tid}/resume", headers=headers)
    assert response.status_code == 409
    assert not sent
    with tenant_session(pid) as db:
        assert db.get(Task,uuid.UUID(tid)).status == "paused"


def test_extension_requires_id_and_preserves_used_values(paused_budget, monkeypatch):
    tid, pid, uid = paused_budget
    sent = []
    monkeypatch.setattr("myink.worker.amqp.publish_once", lambda *a, **kw:sent.append(a))
    headers = identity_headers(uid)
    response = client.post(f"/api/v1/tasks/{tid}/resume", json={"add_requests":2}, headers=headers)
    assert response.status_code == 422
    response = client.post(f"/api/v1/tasks/{tid}/resume", json=_body(), headers=headers)
    assert response.status_code == 200, response.text
    budget = budget_view(tid)
    assert budget["limits"]["max_requests"] == 3
    assert budget["requests_used"] == 1
    assert len(sent) == 1


def test_same_operation_replay_and_conflicting_parameters(paused_budget, monkeypatch):
    tid, pid, uid = paused_budget
    sent = []
    monkeypatch.setattr("myink.worker.amqp.publish_once", lambda *a, **kw:sent.append(a))
    headers = identity_headers(uid)
    body = _body()
    for _ in range(2):
        response = client.post(f"/api/v1/tasks/{tid}/resume", json=body, headers=headers)
        assert response.status_code == 200, response.text
    changed = client.post(f"/api/v1/tasks/{tid}/resume", json={**body,"add_requests":3}, headers=headers)
    assert changed.status_code == 409
    assert len(sent) == 1
    assert budget_view(tid)["limits"]["max_requests"] == 3


@pytest.mark.parametrize("status", ["done","cancelled"])
def test_completed_tasks_cannot_extend(paused_budget, status, monkeypatch):
    tid, pid, uid = paused_budget
    sent = []
    monkeypatch.setattr("myink.worker.amqp.publish_once", lambda *a, **kw:sent.append(a))
    with tenant_session(pid) as db:
        db.get(Task,uuid.UUID(tid)).status = status
    response = client.post(f"/api/v1/tasks/{tid}/resume", json=_body(), headers=identity_headers(uid))
    assert response.status_code == 409
    assert budget_view(tid)["limits"]["max_requests"] == 1
    assert not sent


def test_foreign_account_cannot_extend(paused_budget,temp_user,monkeypatch):
    tid, pid, uid = paused_budget
    sent = []
    monkeypatch.setattr("myink.worker.amqp.publish_once", lambda *a, **kw:sent.append(a))
    response = client.post(f"/api/v1/tasks/{tid}/resume", json=_body(),headers=identity_headers(temp_user))
    assert response.status_code in (403,404)
    assert not sent
    assert budget_view(tid)["limits"]["max_requests"] == 1


def test_nack_retry_does_not_append_twice(paused_budget,monkeypatch):
    import pika
    tid, pid, uid = paused_budget
    calls = []
    def publish(*args,**kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise pika.exceptions.NackError([])
    monkeypatch.setattr("myink.worker.amqp.publish_once",publish)
    body = _body()
    headers = identity_headers(uid)
    first = client.post(f"/api/v1/tasks/{tid}/resume",json=body,headers=headers)
    assert first.status_code == 503
    with tenant_session(pid) as db:
        assert db.get(Task,uuid.UUID(tid)).status == "paused"
    retry = client.post(f"/api/v1/tasks/{tid}/resume",json=body,headers=headers)
    assert retry.status_code == 200,retry.text
    assert len(calls) == 2
    assert budget_view(tid)["limits"]["max_requests"] == 3


def test_uncertain_confirm_never_refunds_or_republishes_same_operation(paused_budget,monkeypatch):
    tid, pid, uid = paused_budget
    calls = []
    def publish(*args,**kwargs):
        calls.append(args)
        raise TimeoutError("lost confirm")
    monkeypatch.setattr("myink.worker.amqp.publish_once",publish)
    body = _body()
    headers = identity_headers(uid)
    first = client.post(f"/api/v1/tasks/{tid}/resume",json=body,headers=headers)
    assert first.status_code == 503
    assert "UNCERTAIN" in first.text
    assert budget_view(tid)["resume_publication"] == "uncertain"
    with tenant_session(pid) as db:
        assert db.get(Task,uuid.UUID(tid)).status == "queued"
    replay = client.post(f"/api/v1/tasks/{tid}/resume",json=body,headers=headers)
    assert replay.status_code == 200
    assert len(calls) == 1
    assert budget_view(tid)["limits"]["max_requests"] == 3


@pytest.mark.parametrize("same", [False, True])
def test_concurrent_operations_only_one_queues_and_adds(paused_budget,monkeypatch,same):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    tid, pid, uid = paused_budget
    entered, release = Event(), Event()
    calls = []
    def publish(*args,**kwargs):
        calls.append(args)
        entered.set()
        assert release.wait(10)
    monkeypatch.setattr("myink.worker.amqp.publish_once",publish)
    headers = identity_headers(uid)
    body = _body()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post,f"/api/v1/tasks/{tid}/resume",json=body,headers=headers)
        try:
            assert entered.wait(10)
            second = client.post(f"/api/v1/tasks/{tid}/resume",json=body if same else _body(),headers=headers)
            assert second.status_code == (200 if same else 409)
        finally:
            release.set()
        assert first.result().status_code == 200
    assert len(calls) == 1
    assert budget_view(tid)["limits"]["max_requests"] == 3


def test_default_change_does_not_change_paused_snapshot(paused_budget,monkeypatch):
    from myink.environment import save_raw, load_raw
    tid, pid, uid = paused_budget
    previous = load_raw(uid)
    try:
        save_raw(uid,{**previous,"task_budget":{"max_requests":500,"max_cost_yuan":20,"max_runtime_seconds":6000}})
        monkeypatch.setattr("myink.worker.amqp.publish_once",lambda *a,**kw:None)
        response = client.post(f"/api/v1/tasks/{tid}/resume",json=_body(),headers=identity_headers(uid))
        assert response.status_code == 200
        assert budget_view(tid)["limits"] == {"max_requests":3,"max_cost_yuan":5,"max_runtime_seconds":1800}
    finally:
        save_raw(uid,previous)


def test_old_delivery_cannot_advance_a_new_resume(paused_budget,monkeypatch):
    from myink.worker import processor
    tid, pid, uid = paused_budget
    monkeypatch.setattr("myink.worker.amqp.publish_once",lambda *a,**kw:None)
    response = client.post(f"/api/v1/tasks/{tid}/resume",json=_body(),headers=identity_headers(uid))
    assert response.status_code == 200
    advanced = []
    monkeypatch.setattr(processor,"_dispatch",lambda body:advanced.append(body) or {})
    old = {"task_id":tid,"project_id":pid,"user_id":uid,"task_type":"chapter_generate","payload":{"seq":1},"task_budget":{"max_requests":999}}
    assert processor.process(old) == "waiting"
    assert not advanced
    assert budget_view(tid)["limits"]["max_requests"] == 3


def test_resume_publish_lost_confirm_does_not_retry(monkeypatch):
    from unittest.mock import Mock
    from myink.worker import amqp
    connection = Mock()
    channel = connection.channel.return_value
    channel.basic_publish.side_effect = TimeoutError("lost confirm")
    factory = Mock(return_value=connection)
    monkeypatch.setattr(amqp.pika, "BlockingConnection", factory)
    monkeypatch.setattr(amqp, "declare_topology", lambda ch: None)
    with pytest.raises(TimeoutError):
        amqp.publish_once("{}", amqp.KEY_TASKS)
    assert factory.call_count == 1
    assert channel.basic_publish.call_count == 1
    assert channel.basic_publish.call_args.kwargs["mandatory"] is True
    assert factory.call_args.args[0].connection_attempts == 1
    connection.close.assert_called_once()


def test_resume_clears_active_pause_reason(paused_budget,monkeypatch):
    tid,pid,uid=paused_budget
    monkeypatch.setattr("myink.worker.amqp.publish_once",lambda *a,**kw:None)
    response=client.post(f"/api/v1/tasks/{tid}/resume",json=_body(),headers=identity_headers(uid))
    assert response.status_code == 200
    assert budget_view(tid)["pause_reason"] is None
