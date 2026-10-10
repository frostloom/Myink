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

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_serializer, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from myink.db import new_session, tenant_session
from myink.maintenance import lock_maintenance, require_admission_open, register_admission, intent_outcome
from myink.models import Project, Task
from myink.maintenance_pause import (bind_execution, authorized_node, guard_maintenance, fence_effect, MaintenancePaused, READ_ONLY_TOOLS)
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
    if _SCOPE.get() is None:
        lock_maintenance(db)
        db.scalar(select(Task).where(Task.id == uuid.UUID(str(task_id))).with_for_update())
    fence_effect(db)
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
        lock_maintenance(db)
        db.scalar(select(Task).where(Task.id==uuid.UUID(str(task_id))).with_for_update())
        from myink.maintenance_pause import _SCOPE as execution_scope
        from myink.models.maintenance import MaintenanceExecution
        execution=execution_scope.get()
        current=db.get(MaintenanceExecution,uuid.UUID(str(task_id)))
        if execution and (current.owner_token!=execution.owner or current.execution_generation!=execution.generation):
            return
        row = db.scalar(select(TaskBudget).where(TaskBudget.task_id==uuid.UUID(str(task_id))).with_for_update())
        if row is None or row.owner_token != owner_token:
            return
        _accrue(row, time.time())
        # Retain the last generation as a status-report fencing token.
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
        task = db.get(Task, row.task_id)
        operation = (task.payload or {}).get("_budget_resume_operation")
        receipt = _extension(db, task_id, "extension:" + operation) if operation else None
        return {
            "resume_publication": receipt.response.get("publication") if receipt else None,
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
def _bind_task_budget(task_id, owner_token):
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
def bind_task_budget(task_id, owner_token):
    with bind_execution(task_id, owner_token):
        with _bind_task_budget(task_id, owner_token):
            yield


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
            if response is None or permit.prices is None or response.input_tokens <= 0 or response.output_tokens < 0 or not response.usage_complete:
                attempt.status = "unknown"
                return  # Keep the conservative reservation exactly once.
            table = permit.prices
            charge = _micros((Decimal(response.input_tokens) * Decimal(str(
                max(table["input"], table["input_cache_hit"])))
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



def budget_io(permit, operation):
    """Bound total network consumption, including trickled incomplete chunks.

    A supplier request already sent cannot be revoked. Its reservation remains
    unknown on timeout; the daemon closes any late response and cannot settle it
    or publish a result. No subsequent Agent node waits for this operation.
    """
    if permit is None or permit.deadline is None:
        return operation()
    completed = threading.Event()
    abandoned = threading.Event()
    result = []
    def run():
        try:
            value = operation()
            result.append((True, value))
        except BaseException as exc:
            result.append((False, exc))
        finally:
            completed.set()
            if abandoned.is_set() and result and result[0][0]:
                close = getattr(result[0][1], "close", None)
                if close:
                    try: close()
                    except Exception: pass
    threading.Thread(target=run, daemon=True, name="task-budget-network").start()
    try:
        if not completed.wait(permit.remaining_seconds()):
            raise TaskBudgetPaused("time_limit", _OPERATION.get())
        permit.remaining_seconds()
    except TaskBudgetPaused:
        abandoned.set()
        raise
    ok, value = result[0]
    if not ok:
        raise value
    return value


def budget_iter(permit, iterable):
    iterator = iter(iterable)
    sentinel = object()
    while True:
        value = budget_io(permit, lambda: next(iterator, sentinel))
        if value is sentinel:
            break
        yield value


@contextmanager
def budget_stream(permit, manager):
    response = budget_io(permit, manager.__enter__)
    try:
        yield response
    finally:
        manager.__exit__(None, None, None)


def budget_sleep(permit, delay):
    if permit is None:
        time.sleep(delay)
        return
    time.sleep(min(delay, permit.remaining_seconds()))
    permit.remaining_seconds()


def budget_managed() -> bool:
    return _SCOPE.get() is not None


def _require_owner(row, scope):
    if row is None or row.owner_token != scope.owner_token or (row.lease_until or 0) <= time.time():
        raise TaskBudgetUnavailable("task execution lease lost")


def guard_budget(stage=None):
    """Node boundaries also stop local work after cancellation or elapsed time."""
    scope = _SCOPE.get()
    if scope is None:
        return
    with _ledger(scope.task_id) as db:
        row = _locked(db, scope.task_id)
        _require_owner(row, scope)
        task = db.get(Task, row.task_id)
        if task.status in {"paused", "cancelled"}:
            raise TaskBudgetPaused("cancelled" if task.status == "cancelled" else
                                   row.pause_reason or "manual_pause", stage)
        _accrue(row, time.time())
        limit = TaskBudgetLimits.model_validate(row.limits).max_runtime_seconds
        row.stage = stage or _OPERATION.get() or row.stage
        if limit and row.runtime_used_ms >= limit * 1000:
            row.pause_reason = "time_limit"
            db.commit()
            raise TaskBudgetPaused("time_limit", row.stage)


def operation_for(state, node):
    return (f"{state.get('task_id') or state.get('batch_task_id')}:{node}:"
            f"ch{state.get('chapter_seq', state.get('position', 0))}:"
            f"r{state.get('revision_count', 0)}:p{state.get('patch_count', 0)}:"
            f"re{state.get('replan_count', state.get('batch_replan_count', 0))}:bg{state.get('batch_generation', 0)}")


def budget_node(function, name=None):
    @wraps(function)
    def wrapped(state, *args, **kwargs):
        operation = operation_for(state, name or function.__name__)
        with bind_budget_operation(operation):
            with authorized_node(operation):
                guard_budget(operation)
                return function(state, *args, **kwargs)
    return wrapped


def budget_llm(function):
    @wraps(function)
    def wrapped(db, state, node, *args, **kwargs):
        with bind_budget_operation(operation_for(state, node)):
            guard_maintenance(operation_for(state, node))
            guard_budget()
            return function(db, state, node, *args, **kwargs)
    return wrapped


def _load_progress(task_id, key):
    scope = _SCOPE.get()
    if scope is None:
        return None
    if str(task_id) != scope.task_id:
        raise TaskBudgetUnavailable("progress task owner mismatch")
    with _ledger(task_id) as db:
        row = _locked(db, task_id)
        _require_owner(row, scope)
        call = db.scalar(select(TaskBudgetCall).where(TaskBudgetCall.task_id == row.task_id,
                         TaskBudgetCall.operation_key == key, TaskBudgetCall.input_hash == "progress"))
        return dict(call.response) if call else None


def _save_progress(task_id, key, payload):
    scope = _SCOPE.get()
    if scope is None:
        return
    if str(task_id) != scope.task_id:
        raise TaskBudgetUnavailable("progress task owner mismatch")
    with _ledger(task_id) as db:
        row = _locked(db, task_id)
        _require_owner(row, scope)
        db.execute(insert(TaskBudgetCall).values(task_id=row.task_id, project_id=row.project_id,
                    operation_key=key, input_hash="progress", response=payload)
                   .on_conflict_do_update(constraint="uq_task_budget_call", set_={"response": payload}))


def save_short_progress(task_id, stage, payload):
    _save_progress(task_id, "short:progress", {"stage": stage, **payload})


def load_short_progress(task_id):
    return _load_progress(task_id, "short:progress")


def budget_tool_call(identity, execute):
    scope = _SCOPE.get()
    if scope is None:
        return execute()
    from myink.workflow.tools import _EXECUTORS
    if identity.get("name") not in READ_ONLY_TOOLS or identity.get("name") not in _EXECUTORS:
        raise TaskBudgetUnavailable("tool lacks a verified effect contract")
    key = "tool:" + hashlib.sha256(json.dumps([_OPERATION.get(), identity],
                                             sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    saved = _load_progress(scope.task_id, key)
    if saved is not None:
        return saved["result"]
    guard_maintenance("tool:" + identity["name"])
    guard_budget()
    result = execute()
    _save_progress(scope.task_id, key, {"result": result})
    return result


def record_budget_pause(task_id, exc, *, expected_owner=None):
    with _ledger(task_id) as db:
        lock_maintenance(db)
        task = db.scalar(select(Task).where(Task.id == uuid.UUID(str(task_id))).with_for_update())
        row = _locked(db, task_id)
        if task.status == "cancelled":
            return "cancelled"
        if row is not None and row.owner_token and expected_owner and row.owner_token != expected_owner:
            return "superseded"
        task.status = "paused"
        task.error = str(exc)
        if row is not None:
            row.pause_reason = getattr(exc, "reason", "accounting_unavailable")
            row.stage = getattr(exc, "stage", None) or row.stage
        return "paused"


def budget_execution(function):
    """CLI entry points share the same scope as Worker entry points."""
    import inspect
    signature = inspect.signature(function)
    @wraps(function)
    def wrapped(*args, **kwargs):
        if budget_managed():
            return function(*args, **kwargs)
        params = signature.bind(*args, **kwargs).arguments
        task_id = params.get("task_id") or params.get("batch_task_id") or params.get("thread_id")
        if not task_id:
            return function(*args, **kwargs)
        try:
            tid = uuid.UUID(str(task_id))
        except ValueError:
            return function(*args, **kwargs)  # legacy CLI/test labels have no task ledger
        with new_session() as db:
            if db.get(Task, tid) is None:
                return function(*args, **kwargs)
        owner = uuid.uuid4().hex
        try:
            with bind_task_budget(task_id, owner):
                return function(*args, **kwargs)
        except MaintenancePaused:
            raise
        except (TaskBudgetPaused, TaskBudgetUnavailable) as exc:
            record_budget_pause(task_id, exc, expected_owner=owner)
            raise
    return wrapped


def effect_identity(state, node):
    digest = hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False,
                                       default=str).encode()).hexdigest()
    key = "effect:" + operation_for(state, node)
    if len(key) > 255:
        key = hashlib.sha256(key.encode()).hexdigest()
    return key, digest


def load_effect(db, identity):
    """Lock the lease and receipt in the business transaction itself."""
    fence_effect(db)
    scope = _SCOPE.get()
    if scope is None:
        return None
    row = _locked(db, scope.task_id)
    _require_owner(row, scope)
    call = db.scalar(select(TaskBudgetCall).where(TaskBudgetCall.task_id == row.task_id,
                     TaskBudgetCall.operation_key == identity[0], TaskBudgetCall.input_hash == identity[1]))
    return dict(call.response) if call else None


def save_effect(db, identity, result):
    fence_effect(db)
    scope = _SCOPE.get()
    if scope is None:
        return
    row = _locked(db, scope.task_id)
    _require_owner(row, scope)
    db.execute(insert(TaskBudgetCall).values(task_id=row.task_id, project_id=row.project_id,
                operation_key=identity[0], input_hash=identity[1], response=result)
               .on_conflict_do_nothing(constraint="uq_task_budget_call"))


class ResumeBudgetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: uuid.UUID | None = None
    add_requests: StrictInt = Field(default=0, ge=0, le=2_000_000_000)
    add_cost_yuan: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("9000000000000"),
                                   decimal_places=6, allow_inf_nan=False)
    add_runtime_seconds: StrictInt = Field(default=0, ge=0, le=9_000_000_000_000)

    @field_validator("add_cost_yuan", mode="before")
    @classmethod
    def reject_bool_cost(cls, value):
        if isinstance(value, bool):
            raise ValueError("cost must be a number, not a boolean")
        return value

    @field_serializer("add_cost_yuan")
    def serialize_cost(self, value):
        return float(value)

    @model_validator(mode="after")
    def require_operation_id(self):
        if (self.add_requests or self.add_cost_yuan or self.add_runtime_seconds) and not self.operation_id:
            raise ValueError("追加预算必须提供 operation_id")
        return self


class BudgetResumeError(Exception):
    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


def _extension(db, task_id, key):
    return db.scalar(select(TaskBudgetCall).where(TaskBudgetCall.task_id == uuid.UUID(str(task_id)),
                     TaskBudgetCall.operation_key == key, TaskBudgetCall.input_hash == "extension"))


def _require_resume_room(row, limits, body):
    if limits.max_requests and row.requests_used >= limits.max_requests:
        raise BudgetResumeError("TASK_BUDGET_EXHAUSTED: 请追加请求次数后继续")
    if limits.max_runtime_seconds and row.runtime_used_ms >= limits.max_runtime_seconds * 1000:
        raise BudgetResumeError("TASK_BUDGET_EXHAUSTED: 请追加运行时间后继续")
    if limits.max_cost_yuan and (row.cost_used_micros + row.cost_reserved_micros >= _micros(limits.max_cost_yuan)
                                or (row.pause_reason == "cost_limit" and not body.add_cost_yuan)):
        raise BudgetResumeError("TASK_BUDGET_EXHAUSTED: 剩余费用不足，请追加费用后继续")


def extend_and_resume_budget(task_id, user_id, body: ResumeBudgetBody) -> dict:
    """Append limits once, then publish once; unknown delivery never refunds limits."""
    from myink.worker import amqp
    import pika
    body = ResumeBudgetBody.model_validate(body)
    operation_id = str(body.operation_id or uuid.uuid4())
    key = "extension:" + operation_id
    params = body.model_dump(mode="json", exclude={"operation_id"})
    with _ledger(task_id) as db:
        require_admission_open(db)
        task = db.scalar(select(Task).where(Task.id == uuid.UUID(str(task_id))).with_for_update())
        row = _locked(db, task_id)
        if row is None:
            raise BudgetResumeError("TASK_BUDGET_NOT_ENABLED")
        if str(row.user_id) != str(user_id):
            raise BudgetResumeError("任务不属于此账号", 403)
        receipt = _extension(db, task_id, key)
        if receipt is not None:
            stored = dict(receipt.response)
            if stored["params"] != params:
                raise BudgetResumeError("BUDGET_OPERATION_CONFLICT: 同一操作标识的参数不能改变")
            if stored["publication"] in {"published", "sending", "uncertain"}:
                return {"task_id":str(task_id), "status":task.status,
                        "message": "预算操作已受理；请刷新任务状态，未重复追加或发布"}
            if task.status not in {"paused", "failed", "awaiting_review"}:
                raise BudgetResumeError("当前任务状态不可重新投递")
        else:
            adding = bool(body.add_requests or body.add_cost_yuan or body.add_runtime_seconds)
            if task.status not in {"paused", "failed", "awaiting_review"} and not (
                task.status == "queued" and not adding):
                raise BudgetResumeError(f"当前状态不可追加或续跑: {task.status}")
            if row.owner_token and (row.lease_until or 0) > time.time():
                raise BudgetResumeError("TASK_STILL_RUNNING: 正在保存进度，请稍后继续")
            old = TaskBudgetLimits.model_validate(row.limits)
            try:
                limits = TaskBudgetLimits(
                    max_requests=old.max_requests + body.add_requests if old.max_requests else 0,
                    max_cost_yuan=old.max_cost_yuan + body.add_cost_yuan if old.max_cost_yuan else 0,
                    max_runtime_seconds=old.max_runtime_seconds + body.add_runtime_seconds if old.max_runtime_seconds else 0)
            except ValueError as exc:
                raise BudgetResumeError("追加后预算超出可保存范围", 422) from exc
            _accrue(row, time.time())
            _require_resume_room(row, limits, body)
            row.limits = public_limits(limits)
            row.version += 1
            receipt = TaskBudgetCall(task_id=row.task_id, project_id=row.project_id,
                         operation_key=key, input_hash="extension", response={})
            db.add(receipt)
        if row.owner_token and (row.lease_until or 0) > time.time():
            raise BudgetResumeError("TASK_STILL_RUNNING: 正在保存进度，请稍后继续")
        row.pause_reason = None
        task.status = "queued"
        task.error = None
        task.payload = {**(task.payload or {}), "_budget_resume_operation":operation_id}
        resume_type = {"batch_generate":"batch_resume", "short_generate":"short_resume"}.get(
            task.task_type, "chapter_resume")
        message = {"task_id":str(task_id), "task_type":resume_type, "project_id":str(task.project_id),
                   "user_id":str(row.user_id), "payload":dict(task.payload),
                   "trace_id":task.trace_id or str(task_id), "request_id":operation_id,
                   "budget_operation_id":operation_id, "retry_count":0, "created_at":""}
        intent_id = register_admission(db, message, priority=0)
        receipt.response = {"params":params, "publication":"sending", "message":message}

    intent_outcome(intent_id, message["project_id"], publication_state="unknown")
    try:
        amqp.publish_once(json.dumps(message, ensure_ascii=False), amqp.KEY_TASKS)
    except Exception as exc:
        definite = isinstance(exc, (amqp.PublishNotSent, pika.exceptions.NackError,
                                    pika.exceptions.UnroutableError))
        intent_outcome(intent_id, message["project_id"], publication_state="rejected" if definite else "unknown")
        with _ledger(task_id) as db:
            task = db.scalar(select(Task).where(Task.id == uuid.UUID(str(task_id))).with_for_update())
            _locked(db, task_id)
            receipt = _extension(db, task_id, key)
            receipt.response = {**receipt.response, "publication":"nack" if definite else "uncertain"}
            if definite and task.status == "queued" and (task.payload or {}).get("_budget_resume_operation") == operation_id:
                task.status = "paused"
                task.error = "续跑投递被明确拒绝；额度已保留，可使用同一操作重试"
        raise BudgetResumeError("BUDGET_PUBLISH_REJECTED: 使用同一操作重试" if definite else
                               "BUDGET_PUBLISH_UNCERTAIN: 预算已保留，请刷新任务状态", 503) from exc
    intent_outcome(intent_id, message["project_id"], publication_state="published")
    with _ledger(task_id) as db:
        receipt = _extension(db, task_id, key)
        receipt.response = {**receipt.response, "publication":"published"}
        task = db.get(Task, uuid.UUID(str(task_id)))
        return {"task_id":str(task_id), "status":task.status, "message":"已追加预算并投递续跑消息"}
