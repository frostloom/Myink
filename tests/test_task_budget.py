"""Task budget configuration and durable execution leases."""
from decimal import Decimal
import uuid

import pytest
from pydantic import ValidationError

from myink.task_budget import (
    TaskBudgetLimits, budget_defaults, public_limits, snapshot_budget,
    ensure_task_budget, budget_view, claim_budget, renew_budget, release_budget,
    TaskBudgetUnavailable,
)


def test_task_budget_defaults():
    assert public_limits(TaskBudgetLimits()) == {
        "max_requests": 100, "max_cost_yuan": 5.0, "max_runtime_seconds": 1800,
    }


@pytest.mark.parametrize("field,value", [
    ("max_requests", -1), ("max_requests", True), ("max_requests", 1.5),
    ("max_runtime_seconds", -1), ("max_runtime_seconds", False),
    ("max_cost_yuan", True), ("max_cost_yuan", -1),
    ("max_cost_yuan", float("nan")), ("max_cost_yuan", float("inf")),
    ("max_cost_yuan", "0.0000001"),
])
def test_task_budget_rejects_invalid_limits(field, value):
    with pytest.raises(ValidationError):
        TaskBudgetLimits(**{field: value})


def test_task_budget_zero_disables_each_limit():
    assert public_limits(TaskBudgetLimits(max_requests=0, max_cost_yuan=0,
                                         max_runtime_seconds=0)) == {
        "max_requests": 0, "max_cost_yuan": 0.0, "max_runtime_seconds": 0,
    }


def test_snapshot_is_independent_of_later_defaults(monkeypatch):
    import myink.environment as environment
    raw = {"task_budget": {"max_requests": 2, "max_cost_yuan": 1, "max_runtime_seconds": 60}}
    monkeypatch.setattr(environment, "load_raw", lambda user_id: raw)
    snap = snapshot_budget("account")
    raw["task_budget"]["max_requests"] = 9
    assert snap["max_requests"] == 2
    assert budget_defaults("account").max_requests == 9


@pytest.fixture
def budget_task(temp_project):
    from myink.db import tenant_session
    from myink.models import Task, Project
    tid = str(uuid.uuid4())
    with tenant_session(temp_project) as db:
        owner = str(db.get(Project, uuid.UUID(temp_project)).user_id)
        db.add(Task(id=uuid.UUID(tid), project_id=uuid.UUID(temp_project),
                    task_type="chapter_generate", payload={}, status="queued"))
    return tid, temp_project, owner


def test_duplicate_snapshot_keeps_original_limits(budget_task):
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests": 2})
    ensure_task_budget(tid, pid, uid, {"max_requests": 8})
    assert budget_view(tid)["limits"]["max_requests"] == 2


def test_legacy_task_without_snapshot_is_unmanaged(budget_task):
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, None)
    assert budget_view(tid) is None


def test_lease_rejects_stale_owner(budget_task, monkeypatch):
    import myink.task_budget as budget
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {})
    now = [1000.0]
    monkeypatch.setattr(budget.time, "time", lambda: now[0])
    claim_budget(tid, "worker-a")
    with pytest.raises(TaskBudgetUnavailable):
        claim_budget(tid, "worker-b")
    now[0] += 61
    claim_budget(tid, "worker-b")
    with pytest.raises(TaskBudgetUnavailable):
        renew_budget(tid, "worker-a")
    release_budget(tid, "worker-a")
    renew_budget(tid, "worker-b")


def test_runtime_survives_restart_excludes_pause(budget_task, monkeypatch):
    import myink.task_budget as budget
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {})
    now = [1000.0]
    monkeypatch.setattr(budget.time, "time", lambda: now[0])
    claim_budget(tid, "a")
    now[0] += 4
    release_budget(tid, "a")
    now[0] += 100
    claim_budget(tid, "b")
    now[0] += 3
    release_budget(tid, "b")
    assert budget_view(tid)["runtime_used_seconds"] == 7

def test_cost_limit_fits_durable_currency_storage():
    with pytest.raises(ValidationError):
        TaskBudgetLimits(max_cost_yuan="1e1000")

