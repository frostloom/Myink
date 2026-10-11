"""Trusted host maintenance entry; the Pi/model HTTP boundary has no control API."""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import uuid
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from .contracts import Identity, Receipt
from .ledger import Ledger
from .schedule import window_at


def enter_maintenance(ledger: Ledger, expected: Identity, now: datetime) -> Receipt:
    from myink.db import get_admin_engine
    from myink.models.maintenance import MaintenanceControl
    window = window_at(now)
    identity = asdict(expected)
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    operation = "maintenance:" + window["day"] + ":admission:" + fingerprint
    epoch = hashlib.sha256(operation.encode()).hexdigest()
    ledger.intent(operation, "maintenance_admission", {"identity":identity, "maintenance_epoch":epoch,
                  "deadline":window["deadline"]})
    existing = ledger.get(operation)
    if existing["status"] not in ("pending", "done", "uncertain"):
        return Receipt(operation, existing["status"], existing["evidence"])
    evidence = {"maintenance_epoch":epoch, "deployment_generation":expected.generation,
                "identity":identity, "deadline":window["deadline"], "verified":False}
    revalidating = existing["status"] in ("done", "uncertain")
    reconciling = existing["status"] == "uncertain"
    if reconciling:
        evidence["reconciliation_id"] = str(uuid.uuid4())
    status = "uncertain"
    try:
        with Session(get_admin_engine()) as db:
            # Only a trusted migration/control connection can assume this role.
            db.execute(text("SET LOCAL ROLE myink_maintenance_control"))
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '10s'"))
            query = select(MaintenanceControl).where(MaintenanceControl.id == 1)
            if revalidating:
                db.execute(text("SET LOCAL transaction_read_only = on"))
            else:
                query = query.with_for_update()
            control = db.scalar(query)
            if (not window["active"] or control is None
                    or control.deployment_id != expected.deployment_id or control.generation != expected.generation
                    or control.owner != expected.owner or control.image_ids != expected.image_ids
                    or (control.admission_closed and control.epoch != epoch)
                    or (revalidating and (control.epoch != epoch or not control.admission_closed or not control.consumer_blocked
                        or control.deadline != datetime.fromisoformat(window["deadline"])))):
                status = "blocked"
                evidence["reason"] = "identity_or_window_mismatch"
            else:
                if not revalidating:
                    control.epoch = epoch
                    control.deadline = datetime.fromisoformat(window["deadline"])
                    control.admission_closed = True
                    control.consumer_blocked = True
                    db.commit()
                status = "done"
                evidence["verified"] = True
    except Exception as exc:
        # A DB/ledger interruption is reconciled against this exact epoch. Never
        # claim a transaction spanning SQLite, PG, Redis, or RabbitMQ.
        evidence["reason"] = "database_outcome_unconfirmed"
        evidence["error_class"] = type(exc).__name__
    receipt = Receipt(operation, status, evidence)
    try:
        if revalidating:
            # The old terminal receipt stays immutable; current authority is a
            # separately recorded read-only identity check, never a cached grant.
            event = {"operation_id":operation, "status":status, "evidence":evidence}
            if reconciling:
                event.update(reconciliation_id=evidence["reconciliation_id"], source_status=existing["status"])
            ledger.append_event("maintenance_reconciliation" if reconciling else "maintenance_revalidation", event)
        else:
            ledger.finish(receipt)
    except Exception:
        return Receipt(operation, "uncertain", {**evidence, "verified":False, "reason":"ledger_outcome_unconfirmed"})
    return receipt


def reconcile_queue(ledger: Ledger, expected: Identity, epoch: str) -> Receipt:
    """Trusted adapter emits aggregate evidence without private rebuild payload."""
    from myink.db import get_admin_engine
    from myink.worker.handoff import reconcile_queue as business_reconcile
    from myink.maintenance import maintenance_view
    operation="queue-reconciliation:"+str(uuid.uuid4())
    with Session(get_admin_engine()) as db:
        control=maintenance_view(db)
        if (control["deployment_id"]!=expected.deployment_id or control["generation"]!=expected.generation
                or control["owner"]!=expected.owner or control["image_ids"]!=expected.image_ids):
            result={"verified":False,"unknown":1,"reason":"identity_mismatch"}
        else:result=business_reconcile(db,epoch)
    evidence={key:result[key] for key in ("verified","unknown","planned","queue_messages","handoffs","epoch") if key in result}
    receipt=Receipt(operation,"done" if result["verified"] else "blocked",evidence)
    ledger.append_event("queue_reconciliation",{"operation_id":operation,"status":receipt.status,**evidence})
    return receipt


def resume_queue(ledger: Ledger,expected: Identity,epoch: str) -> Receipt:
    """Trusted same-deployment adapter; commit durable bridge before any Rabbit effect."""
    from myink.db import get_engine
    from myink.maintenance import lock_maintenance
    from myink.worker.handoff import resume_maintenance_handoffs,publish_handoff
    from myink.models import Project
    operation='queue-resume:'+str(uuid.uuid4())
    try:
        with Session(get_engine()) as db:
            control=lock_maintenance(db)
            if (control['deployment_id']!=expected.deployment_id or control['generation']!=expected.generation
                    or control['owner']!=expected.owner or control['image_ids']!=expected.image_ids):raise ValueError('resume identity mismatch')
            rows=[]
            for project_id in db.scalars(select(Project.id)):
                db.execute(text("SELECT set_config('app.tenant_id',:project,true)"),{'project':str(project_id)})
                rows.extend(resume_maintenance_handoffs(db,epoch,expected.generation))
            db.commit()
        publications=[publish_handoff(row['operation_id']) for row in rows]
        evidence={'verified':all(p['state']=='published' for p in publications),'resumed':len(rows),'epoch':epoch}
        receipt=Receipt(operation,'done' if evidence['verified'] else 'uncertain',evidence)
    except Exception as exc:
        receipt=Receipt(operation,'blocked',{'verified':False,'reason':'resume_unconfirmed','error_class':type(exc).__name__})
    ledger.append_event('queue_resume',{'operation_id':operation,'status':receipt.status,**receipt.evidence})
    return receipt
