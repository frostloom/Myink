"""Task limits, PostgreSQL accounting, and execution ownership.

Ledger transactions are independent from chapter transactions: a failed chapter
cannot refund requests that already reached the model provider.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
import time
import uuid

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_serializer, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from myink.db import new_session, tenant_session
from myink.models import Project, Task
from myink.models.task_budget import TaskBudget

LEASE_SECONDS = 60


class TaskBudgetLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_requests: StrictInt = Field(default=100, ge=0)
    max_cost_yuan: Decimal = Field(default=Decimal("5"), ge=0, decimal_places=6, allow_inf_nan=False)
    max_runtime_seconds: StrictInt = Field(default=1800, ge=0)

    @field_validator("max_cost_yuan", mode="before")
    @classmethod
    def reject_bool_cost(cls, value):
        if isinstance(value, bool):
            raise ValueError("cost must be a number, not a boolean")
        return value

    @field_serializer("max_cost_yuan")
    def serialize_cost(self, value: Decimal) -> float:
        return float(value)


class TaskBudgetPaused(Exception):
    def __init__(self, reason: str, stage: str | None = None):
        self.reason = reason
        self.stage = stage
        super().__init__(f"Task budget paused: {reason}")


class TaskBudgetUnavailable(Exception):
    """Accounting or execution ownership is unavailable; never send paid I/O."""


def public_limits(limits: TaskBudgetLimits) -> dict:
    return limits.model_dump(mode="json")


def budget_defaults(user_id=None) -> TaskBudgetLimits:
    if user_id is None:
        return TaskBudgetLimits()
    from myink.environment import load_raw
    raw = load_raw(user_id).get("task_budget")
    return TaskBudgetLimits.model_validate(raw if isinstance(raw, dict) else {})


def snapshot_budget(user_id=None) -> dict:
    return public_limits(budget_defaults(user_id))


@contextmanager
def _ledger(task_id: str):
    with new_session() as db:
        task = db.get(Task, uuid.UUID(str(task_id)))
        project_id = str(task.project_id) if task else None
    if project_id is None:
        raise TaskBudgetUnavailable("task does not exist")
    with tenant_session(project_id) as db:
        yield db


def ensure_task_budget(task_id, project_id, user_id, snapshot: dict | None) -> None:
    if snapshot is None:
        return
    limits = public_limits(TaskBudgetLimits.model_validate(snapshot))
    with tenant_session(project_id) as db:
        task = db.get(Task, uuid.UUID(str(task_id)))
        project = db.get(Project, uuid.UUID(str(project_id)))
        if task is None or task.project_id != uuid.UUID(str(project_id)) or (
            project is None or project.user_id != uuid.UUID(str(user_id))
        ):
            raise TaskBudgetUnavailable("budget owner mismatch")
        db.execute(insert(TaskBudget).values(
            task_id=task.id, project_id=task.project_id, user_id=project.user_id, limits=limits,
            requests_used=0, cost_used_micros=0, cost_reserved_micros=0,
            runtime_used_ms=0, version=1,
        ).on_conflict_do_nothing(index_elements=["task_id"]))


def _locked(db, task_id) -> TaskBudget | None:
    return db.scalar(select(TaskBudget).where(
        TaskBudget.task_id == uuid.UUID(str(task_id))).with_for_update())


def _accrue(row: TaskBudget, now: float) -> None:
    if row.active_since is not None:
        end = min(now, row.lease_until if row.lease_until is not None else now)
        row.runtime_used_ms += max(0, int(round((end - row.active_since) * 1000)))
        row.active_since = now


def claim_budget(task_id, owner_token) -> bool:
    with _ledger(task_id) as db:
        row = _locked(db, task_id)
        if row is None:
            return False
        now = time.time()
        if row.owner_token and row.owner_token != owner_token and (row.lease_until or 0) > now:
            raise TaskBudgetUnavailable("task execution already leased")
        _accrue(row, now)
        row.owner_token = owner_token
        row.active_since = now
        row.lease_until = now + LEASE_SECONDS
        row.version += 1
        return True


def renew_budget(task_id, owner_token) -> None:
    with _ledger(task_id) as db:
        row = _locked(db, task_id)
        if row is None:
            return
        now = time.time()
        if row.owner_token != owner_token or (row.lease_until or 0) <= now:
            raise TaskBudgetUnavailable("task execution lease lost")
        _accrue(row, now)
        row.lease_until = now + LEASE_SECONDS


def release_budget(task_id, owner_token) -> None:
    with _ledger(task_id) as db:
        row = _locked(db, task_id)
        if row is None or row.owner_token != owner_token:
            return
        _accrue(row, time.time())
        row.owner_token = None
        row.active_since = None
        row.lease_until = None


def budget_view(task_id) -> dict | None:
    with _ledger(task_id) as db:
        row = db.get(TaskBudget, uuid.UUID(str(task_id)))
        if row is None:
            return None
        elapsed = row.runtime_used_ms
        if row.active_since is not None:
            elapsed += max(0, int(round((min(time.time(), row.lease_until or time.time()) - row.active_since) * 1000)))
        return {
            "limits": dict(row.limits), "requests_used": row.requests_used,
            "cost_used_yuan": row.cost_used_micros / 1_000_000,
            "cost_reserved_yuan": row.cost_reserved_micros / 1_000_000,
            "runtime_used_seconds": elapsed / 1000, "pause_reason": row.pause_reason,
            "stage": row.stage, "version": row.version,
        }

