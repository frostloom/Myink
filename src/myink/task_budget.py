"""Task limits, PostgreSQL accounting, and execution ownership.

Ledger transactions are independent from chapter transactions: a failed chapter
cannot refund requests that already reached the model provider.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from functools import wraps
import hashlib
import json
import threading
from decimal import ROUND_CEILING

from decimal import Decimal
import time
import uuid

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_serializer, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from myink.db import new_session, tenant_session
from myink.models import Project, Task
from myink.models.task_budget import TaskBudget, TaskBudgetAttempt, TaskBudgetCall

LEASE_SECONDS = 60


class TaskBudgetLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_requests: StrictInt = Field(default=100, ge=0)
    max_cost_yuan: Decimal = Field(default=Decimal("5"), ge=0, le=Decimal("9000000000000"), decimal_places=6, allow_inf_nan=False)
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

# Request-bound accounting uses a task-local scope, not module-global counters.

_SCOPE = ContextVar("task_budget_scope", default=None)
_OPERATION = ContextVar("task_budget_operation", default=None)
_PRICES = ContextVar("task_budget_prices", default=None)


@dataclass(frozen=True)
class BudgetScope:
    task_id: str
    owner_token: str


@dataclass(frozen=True)
class AttemptPermit:
    task_id: str
    attempt_id: str
    owner_token: str
    deadline: float | None
    prices: dict | None

    def remaining_seconds(self) -> float:
        if self.deadline is None:
            return 120.0
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TaskBudgetPaused("time_limit", _OPERATION.get())
        return remaining


@contextmanager
def bind_task_budget(task_id, owner_token):
    managed = claim_budget(task_id, owner_token)
    token = _SCOPE.set(BudgetScope(str(task_id), owner_token) if managed else None)
    stopped = threading.Event()

    def heartbeat():
        while not stopped.wait(LEASE_SECONDS / 3):
            try:
                renew_budget(task_id, owner_token)
            except Exception:
                return

    thread = threading.Thread(target=heartbeat, daemon=True, name="task-budget-lease")
    if managed:
        thread.start()
    try:
        yield
    finally:
        stopped.set()
        if thread.is_alive():
            thread.join(timeout=1)
        _SCOPE.reset(token)
        if managed:
            release_budget(task_id, owner_token)


@contextmanager
def bind_budget_operation(operation_key: str):
    if len(operation_key) > 255:
        operation_key = hashlib.sha256(operation_key.encode()).hexdigest()
    token = _OPERATION.set(operation_key)
    try:
        yield
    finally:
        _OPERATION.reset(token)


def _micros(value) -> int:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise TaskBudgetUnavailable("invalid budget amount")
    integer = int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
    if integer > 9_000_000_000_000_000_000:
        raise TaskBudgetUnavailable("budget amount exceeds ledger capacity")
    return integer


def _reservation_cost(model_id, messages, max_tokens, prices, tools=None):
    from myink.config import settings
    from myink.providers.prices import lookup_prices
    table = prices if prices is not None else lookup_prices(model_id)
    if table is None:
        return _micros(settings.account_model_unknown_cost), None
    numbers = {k: Decimal(str(table[k])) for k in ("input", "input_cache_hit", "output")}
    if any(not v.is_finite() or v < 0 for v in numbers.values()):
        raise TaskBudgetUnavailable("invalid model prices")
    input_bound = len(json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False).encode()) + 1024
    cost = (input_bound * max(numbers["input"], numbers["input_cache_hit"])
            + max_tokens * numbers["output"]) / 1_000_000
    return _micros(cost), {k: float(v) for k, v in numbers.items()}


def reserve_attempt(model_id, messages, max_tokens, prices=None, *, tools=None) -> AttemptPermit | None:
    scope = _SCOPE.get()
    if scope is None:
        return None
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
        raise TaskBudgetUnavailable("request requires a positive output bound")
    reserve, table = _reservation_cost(model_id, messages, max_tokens,
                                        prices if prices is not None else _PRICES.get(), tools)
    try:
        with _ledger(scope.task_id) as db:
            row = _locked(db, scope.task_id)
            now = time.time()
            if row is None or row.owner_token != scope.owner_token or (row.lease_until or 0) <= now:
                raise TaskBudgetUnavailable("task execution lease lost")
            task = db.get(Task, row.task_id)
            if task.status == "cancelled":
                raise TaskBudgetPaused("cancelled", _OPERATION.get())
            if task.status == "paused":
                raise TaskBudgetPaused(row.pause_reason or "manual_pause", _OPERATION.get())
            _accrue(row, now)
            limits = TaskBudgetLimits.model_validate(row.limits)
            reason = None
            if limits.max_runtime_seconds and row.runtime_used_ms >= limits.max_runtime_seconds * 1000:
                reason = "time_limit"
            elif limits.max_requests and row.requests_used >= limits.max_requests:
                reason = "request_limit"
            elif limits.max_cost_yuan and (
                row.cost_used_micros + row.cost_reserved_micros + reserve > _micros(limits.max_cost_yuan)
            ):
                reason = "cost_limit"
            row.stage = _OPERATION.get()
            if reason:
                row.pause_reason = reason
                db.commit()
                raise TaskBudgetPaused(reason, row.stage)
            aid = uuid.uuid4()
            row.requests_used += 1
            row.cost_reserved_micros += reserve
            row.pause_reason = None
            row.version += 1
            db.add(TaskBudgetAttempt(id=aid, task_id=row.task_id, project_id=row.project_id,
                                     owner_token=scope.owner_token, model_id=model_id,
                                     reserved_micros=reserve, status="reserved"))
            deadline = (time.monotonic() + limits.max_runtime_seconds - row.runtime_used_ms / 1000
                        if limits.max_runtime_seconds else None)
            return AttemptPermit(scope.task_id, str(aid), scope.owner_token, deadline, table)
    except (TaskBudgetPaused, TaskBudgetUnavailable):
        raise
    except Exception as exc:
        raise TaskBudgetUnavailable("request accounting unavailable") from exc


def finish_attempt(permit, response=None) -> None:
    if permit is None:
        return
    try:
        with _ledger(permit.task_id) as db:
            row = _locked(db, permit.task_id)
            attempt = db.get(TaskBudgetAttempt, uuid.UUID(permit.attempt_id))
            if row is None or attempt is None or attempt.owner_token != permit.owner_token:
                raise TaskBudgetUnavailable("request receipt missing")
            if attempt.status != "reserved":
                return
            if response is None or permit.prices is None or response.input_tokens <= 0:
                attempt.status = "unknown"
                return  # Keep the conservative reservation exactly once.
            table = permit.prices
            charge = _micros((Decimal(response.input_tokens) * Decimal(str(
                table["input_cache_hit"] if response.cache_hit else table["input"]))
                + Decimal(response.output_tokens) * Decimal(str(table["output"]))) / 1_000_000)
            row.cost_reserved_micros -= attempt.reserved_micros
            row.cost_used_micros += charge
            attempt.charged_micros = charge
            attempt.status = "settled"
            row.version += 1
    except TaskBudgetUnavailable:
        raise
    except Exception as exc:
        raise TaskBudgetUnavailable("request settlement unavailable") from exc


def load_call(operation_key, input_hash):
    scope = _SCOPE.get()
    if scope is None or not operation_key:
        return None
    from myink.providers.base import ModelResponse
    with _ledger(scope.task_id) as db:
        row = _locked(db, scope.task_id)
        if row is None or row.owner_token != scope.owner_token or (row.lease_until or 0) <= time.time():
            raise TaskBudgetUnavailable("execution lease lost before loading result")
        call = db.scalar(select(TaskBudgetCall).where(
            TaskBudgetCall.task_id == uuid.UUID(scope.task_id),
            TaskBudgetCall.operation_key == operation_key,
            TaskBudgetCall.input_hash == input_hash))
        if call is None:
            return None
        response = ModelResponse(**call.response)
        return replace(response, input_tokens=0, output_tokens=0, duration_ms=0,
                       retry_count=0, budget_replayed=True)


def save_call(operation_key, input_hash, response):
    scope = _SCOPE.get()
    if scope is None or not operation_key or response.error:
        return
    with _ledger(scope.task_id) as db:
        row = _locked(db, scope.task_id)
        if row is None or row.owner_token != scope.owner_token or (row.lease_until or 0) <= time.time():
            raise TaskBudgetUnavailable("execution lease lost before saving result")
        db.execute(insert(TaskBudgetCall).values(
            task_id=row.task_id, project_id=row.project_id,
            operation_key=operation_key, input_hash=input_hash, response=asdict(response),
        ).on_conflict_do_nothing(constraint="uq_task_budget_call"))


def budgeted_call(function):
    """Wrap a logical fallback-chain call; providers meter each HTTP attempt."""
    @wraps(function)
    def wrapped(chain, messages, **kwargs):
        scope = _SCOPE.get()
        if scope is None:
            return function(chain, messages, **kwargs)
        operation = _OPERATION.get()
        options = {k: v for k, v in kwargs.items() if k not in {"on_delta", "on_reset"}}
        identity = {"messages": messages, "options": options, "models": chain.chain,
                    "prices": chain.prices, "stream": function.__name__ == "generate_stream",
                    "providers": [p.name() for p in chain.providers],
                    "endpoints": [str(getattr(p, "_url", getattr(getattr(p, "_client", None),
                                                                             "base_url", "")))
                                  for p in chain.providers],
                    "thinking_enabled": chain.thinking_enabled}
        digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        try:
            cached = load_call(operation, digest)
        except TaskBudgetUnavailable:
            raise
        except Exception as exc:
            raise TaskBudgetUnavailable("saved result storage unavailable") from exc
        if cached is not None:
            return cached
        token = _PRICES.set(chain.prices)
        try:
            response = function(chain, messages, **kwargs)
            save_call(operation, digest, response)
            return response
        finally:
            _PRICES.reset(token)
    return wrapped



def budget_sleep(permit, delay):
    if permit is None:
        time.sleep(delay)
        return
    time.sleep(min(delay, permit.remaining_seconds()))
    permit.remaining_seconds()
