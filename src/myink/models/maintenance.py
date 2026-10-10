"""Durable maintenance authority and private, unmaterialized intake identities."""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Integer, JSON, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from myink.models.base import Base


class MaintenanceControl(Base):
    __tablename__ = "maintenance_control"
    __table_args__ = (CheckConstraint("id = 1", name="ck_maintenance_singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    epoch: Mapped[str] = mapped_column(String(64), nullable=False)
    deployment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    image_ids: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admission_closed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    consumer_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False)


class AdmissionIntent(Base):
    __tablename__ = "admission_intents"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    epoch: Mapped[str] = mapped_column(String(64), nullable=False)
    deployment_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deployment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rebuild_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    gate_state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    publication_state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
