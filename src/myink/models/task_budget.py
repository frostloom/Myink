"""Persistent task budget accounting and recoverable model results."""
from __future__ import annotations

import uuid
from sqlalchemy import BigInteger, Float, ForeignKey, Integer, JSON, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from myink.models.base import Base, TimestampMixin, UUIDPkMixin, TenantMixin


class TaskBudget(Base, TimestampMixin, TenantMixin):
    __tablename__ = "task_budgets"
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    limits: Mapped[dict] = mapped_column(JSON, nullable=False)
    requests_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_used_micros: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cost_reserved_micros: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    runtime_used_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    owner_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[float | None] = mapped_column(Float)
    active_since: Mapped[float | None] = mapped_column(Float)
    pause_reason: Mapped[str | None] = mapped_column(String(32))
    stage: Mapped[str | None] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class TaskBudgetAttempt(Base, UUIDPkMixin, TimestampMixin, TenantMixin):
    __tablename__ = "task_budget_attempts"
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("task_budgets.task_id", ondelete="CASCADE"), nullable=False, index=True)
    owner_token: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    reserved_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    charged_micros: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="reserved", nullable=False)


class TaskBudgetCall(Base, UUIDPkMixin, TimestampMixin, TenantMixin):
    __tablename__ = "task_budget_calls"
    __table_args__ = (UniqueConstraint("task_id", "operation_key", "input_hash", name="uq_task_budget_call"),)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("task_budgets.task_id", ondelete="CASCADE"), nullable=False, index=True)
    operation_key: Mapped[str] = mapped_column(String(255), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSON, nullable=False)

