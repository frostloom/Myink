"""Issue and atomically redeem invitation credentials."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from myink.config import settings
from myink.models.invitation import Invitation

# 自定义码面的长度边界：太长没法口头/纸面分发，太短则熵不足
MIN_CODE_LENGTH = 4
MAX_CODE_LENGTH = 64


class InvitationRejected(ValueError):
    """A stable API error code for a non-redeemable invitation."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def hash_invitation_token(token: str) -> str:
    """Return the storage representation without retaining the plaintext token.

    键控 HMAC 而非裸 SHA-256：管理员可以自定义短码面，若只做无盐摘要，任何拿到库读
    权限的人都能对短码做离线爆破。用 JWT_SECRET 当键后，摘要离开密钥就不可反推，同时
    保留等值索引查找（不像 scrypt 那样要全表扫）。代价：轮换 JWT_SECRET 会让未使用的
    邀请码失效。
    """
    key = settings.jwt_secret.encode("utf-8")
    return hmac.new(key, token.strip().encode("utf-8"), hashlib.sha256).hexdigest()


def create_invitation(
    db: Session,
    *,
    expires_at: datetime,
    max_redemptions: int = 1,
    token: str | None = None,
    label: str | None = None,
    created_by: uuid.UUID | None = None,
) -> tuple[Invitation, str]:
    """Add a new invitation and return its one-time plaintext for explicit display.

    `token` 由调用方给定即为「自定义码面」（管理面板用），否则生成 256 位随机码。
    """
    if expires_at.tzinfo is None:
        raise ValueError("expires_at must be timezone-aware")
    if expires_at <= datetime.now(timezone.utc):
        raise ValueError("expires_at must be in the future")
    if max_redemptions < 1:
        raise ValueError("max_redemptions must be positive")
    if token is None:
        token = secrets.token_urlsafe(32)
    else:
        token = token.strip()
        if not MIN_CODE_LENGTH <= len(token) <= MAX_CODE_LENGTH:
            raise ValueError(
                f"code length must be {MIN_CODE_LENGTH}–{MAX_CODE_LENGTH}"
            )
    invitation = Invitation(
        token_digest=hash_invitation_token(token),
        expires_at=expires_at,
        max_redemptions=max_redemptions,
        redemption_count=0,
        label=(label or "").strip()[:64] or None,
        created_by=created_by,
    )
    db.add(invitation)
    db.flush()
    return invitation, token


def _load_redeemable(
    db: Session,
    token: str | None,
    *,
    now: datetime,
    lock: bool,
) -> Invitation:
    normalized = token.strip() if token else ""
    if not normalized:
        raise InvitationRejected("INVITATION_REQUIRED")
    statement = select(Invitation).where(
        Invitation.token_digest == hash_invitation_token(normalized)
    )
    if lock:
        statement = statement.with_for_update()
    invitation = db.execute(statement).scalar_one_or_none()
    if invitation is None:
        raise InvitationRejected("INVITATION_INVALID")
    if invitation.revoked_at is not None:
        raise InvitationRejected("INVITATION_REVOKED")
    if invitation.expires_at <= now:
        raise InvitationRejected("INVITATION_EXPIRED")
    if invitation.redemption_count >= invitation.max_redemptions:
        raise InvitationRejected("INVITATION_USED")
    return invitation


def validate_invitation(db: Session, token: str | None, *, now: datetime | None = None) -> None:
    """Cheap preflight validation before performing an expensive password hash."""
    _load_redeemable(db, token, now=now or datetime.now(timezone.utc), lock=False)


def consume_invitation(
    db: Session,
    token: str | None,
    *,
    now: datetime | None = None,
) -> Invitation:
    """Lock and consume one redemption inside the caller's account transaction."""
    invitation = _load_redeemable(
        db,
        token,
        now=now or datetime.now(timezone.utc),
        lock=True,
    )
    invitation.redemption_count += 1
    return invitation


def revoke_invitation(
    db: Session,
    invitation_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> bool:
    invitation = db.get(Invitation, invitation_id, with_for_update=True)
    if invitation is None:
        return False
    if invitation.revoked_at is None:
        invitation.revoked_at = now or datetime.now(timezone.utc)
    return True


def ensure_invitation_schema() -> None:
    """Add the standalone invitation table to an existing installation."""
    from sqlalchemy import text

    from myink.db import get_admin_engine

    engine = get_admin_engine()
    Invitation.__table__.create(engine, checkfirst=True)
    # create_all/checkfirst 对已存在的表不补列——活库需显式 ADD COLUMN IF NOT EXISTS（幂等）。
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE invitations ADD COLUMN IF NOT EXISTS label VARCHAR(64)"))
        conn.execute(text("ALTER TABLE invitations ADD COLUMN IF NOT EXISTS created_by UUID"))
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'fk_invitations_created_by_users'
                      AND conrelid = 'invitations'::regclass
                ) THEN
                    ALTER TABLE invitations ADD CONSTRAINT fk_invitations_created_by_users
                    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
                END IF;
            END $$;
        """))
