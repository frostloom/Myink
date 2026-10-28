"""Guest recovery identity, separate from permanent account credentials."""
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from myink.models.base import Base, TimestampMixin


class GuestIdentity(Base, TimestampMixin):
    __tablename__ = 'guest_identities'

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True,
    )
    original_ip_key: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


# No user/project/task FK: deleting content or upgrading an identity must never
# reset lifetime use, nor erase the admission receipt before worker materializes.
class GuestQuotaBucket(Base, TimestampMixin):
    __tablename__ = 'guest_quota_buckets'
    __table_args__ = (CheckConstraint('short_used BETWEEN 0 AND 2 AND long_used BETWEEN 0 AND 10', name='guest_quota_limits'),)
    ip_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    short_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    long_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class GuestQuotaOperation(Base, TimestampMixin):
    __tablename__ = 'guest_quota_operations'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    dimension: Mapped[str] = mapped_column(String(8), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    buckets: Mapped[list] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class GuestBodyAttempt(Base, TimestampMixin):
    __tablename__ = 'guest_body_attempts'
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    stage: Mapped[str] = mapped_column(String(255), primary_key=True)
