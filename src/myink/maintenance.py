"""Short PG admission/claim boundary. Redis and AMQP follow a durable intent."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid
from sqlalchemy import select, text
from myink.models.maintenance import AdmissionIntent, MaintenanceControl

SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


class MaintenanceUnavailable(RuntimeError):
    def __init__(self, reopen_at=None):
        self.reopen_at = reopen_at.astimezone(SHANGHAI).isoformat() if reopen_at else None
        self.retry_after = max(1, int((reopen_at - datetime.now(timezone.utc)).total_seconds())) if reopen_at else 60
        super().__init__("maintenance")


def _valid(row):
    if row is None or row["id"] != 1 or row["generation"] < 0:
        raise MaintenanceUnavailable()
    if not row["owner"] or not row["deployment_id"]:
        raise MaintenanceUnavailable()
    return dict(row)


def maintenance_view(db) -> dict:
    try:
        row = db.execute(select(MaintenanceControl.__table__)).mappings().one_or_none()
        return _valid(row)
    except MaintenanceUnavailable:
        raise
    except Exception as exc:
        raise MaintenanceUnavailable() from exc


def lock_maintenance(db) -> dict:
    # FOR SHARE is executed by the narrowly scoped function owner. Business
    # roles have SELECT + EXECUTE, never UPDATE on the maintenance control row.
    try:
        row = db.execute(text("SELECT * FROM public.myink_lock_maintenance()")).mappings().one_or_none()
        return _valid(row)
    except MaintenanceUnavailable:
        raise
    except Exception as exc:
        raise MaintenanceUnavailable() from exc


def require_admission_open(db) -> None:
    row = lock_maintenance(db)
    if row["admission_closed"]:
        raise MaintenanceUnavailable(row["deadline"])


def require_consumption_open(db) -> None:
    row = lock_maintenance(db)
    if row["consumer_blocked"]:
        raise MaintenanceUnavailable(row["deadline"])


def may_consume(db=None) -> bool:
    try:
        if db is None:
            from myink.db import new_session
            with new_session() as session:
                return may_consume(session)
        return not maintenance_view(db)["consumer_blocked"]
    except MaintenanceUnavailable:
        return False


def register_admission(db, message: dict, *, priority: int, gates=False) -> uuid.UUID:
    row = lock_maintenance(db)
    if row["admission_closed"]:
        raise MaintenanceUnavailable(row["deadline"])
    encoded = json.dumps(message, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    intent = AdmissionIntent(id=uuid.uuid4(), task_id=uuid.UUID(message["task_id"]),
        message_id=str(message["request_id"]), user_id=uuid.UUID(message["user_id"]),
        project_id=uuid.UUID(message["project_id"]), epoch=row["epoch"],
        deployment_generation=row["generation"], deployment_id=row["deployment_id"], owner=row["owner"],
        payload_hash=hashlib.sha256(encoded.encode()).hexdigest(), rebuild_payload=json.loads(encoded),
        priority=priority, gate_state="pending" if gates else "not_required", publication_state="pending")
    db.add(intent)
    db.flush()
    return intent.id


def intent_outcome(intent_id, project_id, *, gate_state=None, publication_state=None):
    from myink.db import tenant_session
    from sqlalchemy import update
    changes = {key:value for key,value in (("gate_state",gate_state),("publication_state",publication_state)) if value is not None}
    with tenant_session(project_id) as db:
        result = db.execute(update(AdmissionIntent).where(AdmissionIntent.id == intent_id).values(**changes))
        if result.rowcount != 1:
            raise MaintenanceUnavailable()
