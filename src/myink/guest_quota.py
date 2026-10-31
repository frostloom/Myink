"""Lifetime guest writing admission. PostgreSQL is the authority, Redis is not.

Receipts have no content FK and commit before publication. Fixed lexical bucket
lock order makes original/current-IP admission atomic without deadlocks.
"""
from __future__ import annotations

import uuid
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from myink.api.ratelimit import ApiError
from myink.db import new_session
from myink.guests import ip_key
from myink.models import GuestIdentity, User
from myink.models.guest import GuestQuotaBucket, GuestQuotaOperation

LIMITS = {'short': 2, 'long': 10}


class GuestQuotaError(ApiError):
    def __init__(self, code='GUEST_QUOTA_EXHAUSTED', status_code=429):
        super().__init__(status_code, code)


def request_ip(request):
    # Deliberately do not fall back when an edge-supplied header is malformed.
    return request.headers.get('x-myink-client-ip',
                               request.client.host if request.client else 'unknown')


def _keys(db, user_id, client_ip):
    user = db.get(User, uuid.UUID(str(user_id)))
    if user is None or not getattr(user, 'is_guest', False):
        return None
    identity = db.get(GuestIdentity, user.id)
    if identity is None:
        raise GuestQuotaError('GUEST_QUOTA_UNAVAILABLE', 503)
    try:
        current = ip_key(client_ip or '')
    except ValueError as exc:
        raise GuestQuotaError('GUEST_IP_UNAVAILABLE', 503) from exc
    return sorted({identity.original_ip_key, current})


def quota_view(user_id, client_ip) -> dict:
    try:
        with new_session() as db:
            keys = _keys(db, user_id, client_ip)
            if keys is None:
                raise GuestQuotaError('GUEST_REQUIRED', 403)
            rows = list(db.scalars(select(GuestQuotaBucket).where(GuestQuotaBucket.ip_key.in_(keys))))
            return {name: {'limit': limit,
                           'used': max((getattr(row, name + '_used') for row in rows), default=0),
                           'remaining': limit - max((getattr(row, name + '_used') for row in rows), default=0)}
                    for name, limit in LIMITS.items()}
    except SQLAlchemyError as exc:
        raise GuestQuotaError('GUEST_QUOTA_UNAVAILABLE', 503) from exc


def reserve_in_session(db, *, user_id, client_ip, dimension, amount, operation_id, task_id):
    keys = _keys(db, user_id, client_ip)
    if keys is None:
        return None
    return _reserve_keys(db, user_id=user_id, keys=keys, dimension=dimension,
                         amount=amount, operation_id=operation_id, task_id=task_id)


def _reserve_keys(db, *, user_id, keys, dimension, amount, operation_id, task_id):
    """Internal only: keys originate in admission's trusted request context."""
    if dimension not in LIMITS or type(amount) is not int or amount < 1:
        raise ValueError('Invalid guest quota amount/dimension')
    oid, uid, tid = (uuid.UUID(str(value)) for value in (operation_id, user_id, task_id))
    values = dict(id=oid, user_id=uid, task_id=tid, dimension=dimension, amount=amount, buckets=keys, active=False)
    db.execute(insert(GuestQuotaOperation).values(**values).on_conflict_do_nothing())
    receipt = db.get(GuestQuotaOperation, oid, with_for_update=True)
    if any(getattr(receipt, key) != values[key] for key in ('user_id','task_id','dimension','amount','buckets')):
        raise GuestQuotaError('GUEST_OPERATION_CONFLICT', 409)
    if receipt.active:
        return str(oid)
    rows = []
    for key in keys:
        db.execute(insert(GuestQuotaBucket).values(ip_key=key, short_used=0, long_used=0).on_conflict_do_nothing())
        rows.append(db.get(GuestQuotaBucket, key, with_for_update=True))
    column = dimension + '_used'
    if any(getattr(row, column) + amount > LIMITS[dimension] for row in rows):
        raise GuestQuotaError()
    for row in rows:
        setattr(row, column, getattr(row, column) + amount)
    receipt.active = True
    db.flush()
    return str(oid)


def reserve(**kwargs):
    try:
        with new_session() as db:
            receipt = reserve_in_session(db, **kwargs)
            db.commit()
            return receipt
    except SQLAlchemyError as exc:
        raise GuestQuotaError('GUEST_QUOTA_UNAVAILABLE', 503) from exc


def release_in_session(db, operation_id):
    if not operation_id:
        return
    row = db.get(GuestQuotaOperation, uuid.UUID(str(operation_id)), with_for_update=True)
    if row is None or not row.active:
        return
    for key in sorted(row.buckets):
        bucket = db.get(GuestQuotaBucket, key, with_for_update=True)
        column = row.dimension + '_used'
        setattr(bucket, column, getattr(bucket, column) - row.amount)
    row.active = False
    db.flush()


def release(operation_id):
    if not operation_id:
        return
    try:
        with new_session() as db:
            release_in_session(db, operation_id)
            db.commit()
    except SQLAlchemyError as exc:
        raise GuestQuotaError('GUEST_QUOTA_UNAVAILABLE', 503) from exc


BODY_NODES = {'write', 'revise', 'patch', 'short_write', 'short_continue', 'short_revise'}


def record_body_attempt(task_id, stage):
    """Called only after cache lookup, immediately before real body generation.

    A receipt survives provider errors or a worker crash. Cached recovery can
    defer manual replay admission until this exact cache miss; its guard is
    consumed transactionally once, so automatic retries never reserve again.
    """
    from myink.models import Task, Project
    from myink.models.guest import GuestBodyAttempt
    if not stage or not any(node in stage.split(':') for node in BODY_NODES):
        return
    with new_session() as db:
        task = db.get(Task, uuid.UUID(str(task_id)), with_for_update=True)
        if task is None:
            return
        project = db.get(Project, task.project_id)
        user = db.get(User, project.user_id)
        if not user.is_guest:
            return
        guard = (task.payload or {}).get('_guest_replay_guard')
        if guard and stage in guard['stages']:
            # Exact cache lookup already missed. This is now real replay I/O,
            # so atomically charge before the provider can see the request.
            receipt = _reserve_keys(db, user_id=str(user.id), keys=guard['keys'],
                dimension='short' if task.task_type == 'short_generate' else 'long',
                amount=1, operation_id=guard['operation_id'], task_id=str(task.id))
            payload = dict(task.payload)
            payload.pop('_guest_replay_guard', None)
            task.payload = {**payload, '_guest_operation': receipt}
        db.execute(insert(GuestBodyAttempt).values(task_id=task.id, stage=stage).on_conflict_do_nothing())
        db.commit()


def valid_message(body):
    """Fail closed before worker materialization, including direct/forged tasks."""
    with new_session() as db:
        user = db.get(User, uuid.UUID(body['user_id']))
        if user is None:
            return False
        if not user.is_guest:
            return True
        oid = (body.get('payload') or {}).get('_guest_operation')
        if not oid:
            return False
        row = db.get(GuestQuotaOperation, uuid.UUID(oid))
        return bool(row and row.active and row.user_id == user.id and str(row.task_id) == body['task_id'])


def _replay_charge(task, stages):
    """Cached stages are recoverable; only an exact cache miss may charge them.

    One stage can issue multiple different calls (tools, parsing retries). A
    successful call for the stage is therefore never proof every next input is
    cached. The persisted guard makes that decision after exact hash lookup.
    """
    from myink.db import tenant_session
    from myink.models.task_budget import TaskBudgetCall
    stages = sorted(stages)
    if not stages:
        return 0
    with tenant_session(task.project_id) as db:
        cached = db.scalar(select(TaskBudgetCall.id).where(
            TaskBudgetCall.task_id == task.id, TaskBudgetCall.operation_key.in_(stages)).limit(1))
    if cached is not None:
        task.payload = {**(task.payload or {}), '_guest_replay_guard': {'stages': stages}}
        return 0
    return 1


def resume_charge(db, task):
    """Count only the active chapter being manually replayed, not a whole batch.

    Pauses and unattempted nodes retain the original operation. A rejected
    candidate requesting body revision is an explicit new operation even from
    awaiting_review. Checkpoint state matches runner's actual restart rules.
    """
    from myink.db import tenant_session
    from myink.models import MemoryCandidate, Chapter
    from myink.models.guest import GuestBodyAttempt
    from myink.models.task_budget import TaskBudgetCall
    from myink.workflow.runner import get_graphs
    from myink.task_budget import operation_for

    tid = str(task.id)
    attempts = set(db.scalars(select(GuestBodyAttempt.stage).where(GuestBodyAttempt.task_id == task.id)))
    if task.task_type == 'short_generate':
        if task.status != 'failed':
            return 0
        with tenant_session(task.project_id) as tenant:
            progress = tenant.scalar(select(TaskBudgetCall).where(
                TaskBudgetCall.task_id == task.id, TaskBudgetCall.operation_key == 'short:progress',
                TaskBudgetCall.input_hash == 'progress'))
            saved = progress.response if progress else {}
            if saved.get('stage') == 'complete':
                return 0
            if saved.get('stage') == 'reviewed':
                return _replay_charge(task, attempts & {f'{tid}:short_revise'}) if saved.get('review', {}).get('verdict') == 'revise' else 0
            if saved.get('stage') == 'written' and any(not text.strip() for text in saved.get('bodies', [])):
                return _replay_charge(task, attempts & {f'{tid}:short_continue'})
            if saved:
                return 0  # review not attempted yet; any resulting revision is internal
            chapters = list(tenant.scalars(select(Chapter).where(Chapter.project_id == task.project_id)))
            expected = int((task.payload or {}).get('chapter_count') or 1)
            if all(any(ch.chapter_seq == seq and ch.content for ch in chapters) for seq in range(1, expected + 1)):
                return _replay_charge(task, attempts & {f'{tid}:short_revise'})
        return _replay_charge(task, attempts & {f'{tid}:short_write'})

    chapter_graph, batch_graph = get_graphs()
    if task.task_type == 'batch_generate':
        batch = batch_graph.get_state({'configurable': {'thread_id': tid}})
        state = batch.values or {}
        # Only the current chapter is replayed; subsequent chapters were already
        # reserved by the original batch admission.
        seq = int(state.get('start_chapter', (task.payload or {}).get('start', 1))) + int(state.get('position', 0))
        tid = f'{tid}:ch{seq}'
    else:
        seq = int((task.payload or {}).get('seq') or task.chapter_seq or 1)
    snap = chapter_graph.get_state({'configurable': {'thread_id': tid}})
    values = snap.values or {}
    if not snap.next and not values.get('review_finalization_pending'):
        with tenant_session(task.project_id) as tenant:
            candidates = tenant.scalars(select(MemoryCandidate).where(
                MemoryCandidate.project_id == task.project_id, MemoryCandidate.source_chapter == seq,
                MemoryCandidate.status == 'rejected'))
            revision_ids = [str(row.id) for row in candidates if (row.review or {}).get('mode') == 'revise'
                            and not (row.review or {}).get('applied')]
            if revision_ids:
                task.payload = {**(task.payload or {}), '_guest_review_candidates': revision_ids}
                # resolve_review enters revise with these counters reset. Only
                # that actual pending stage may be cached recovery; an old write
                # (or another revision coordinate) cannot admit a new revision.
                revision_state = {**values, 'task_id': tid, 'chapter_seq': seq,
                                  'revision_count': 0, 'patch_count': 0, 'replan_count': 0}
                revision_stage = operation_for(revision_state, 'revise')
                if task.status == 'failed' and revision_stage in attempts:
                    return _replay_charge(task, {revision_stage})
                return 1
    if task.status != 'failed':
        return 0
    if snap.next:
        return _replay_charge(task, {operation_for(values, node) for node in snap.next if node in BODY_NODES} & attempts)
    if values.get('error') or not values:
        return _replay_charge(task, {stage for stage in attempts if stage.startswith(tid + ':')})
    return 0


def reserve_resume(db, task, user_id, client_ip, operation_id, retry_charge=None):
    if not getattr(db.get(User, uuid.UUID(str(user_id))), 'is_guest', False):
        return None, 0
    # Invalid current addresses fail closed even for a free continuation.
    keys = _keys(db, user_id, client_ip)
    amount = resume_charge(db, task) if retry_charge is None else retry_charge
    if not amount:
        guard = (task.payload or {}).get('_guest_replay_guard')
        if guard:
            task.payload = {**task.payload, '_guest_replay_guard': {
                'stages': guard['stages'], 'keys': keys, 'operation_id': str(operation_id)}}
        return None, 0
    if (task.payload or {}).get('_guest_replay_guard'):
        payload = dict(task.payload)
        payload.pop('_guest_replay_guard')
        task.payload = payload
    receipt = reserve_in_session(db, user_id=user_id, client_ip=client_ip,
        dimension='short' if task.task_type == 'short_generate' else 'long', amount=amount,
        operation_id=operation_id, task_id=str(task.id))
    return receipt, amount


def resume_legacy(task_id, user_id, client_ip):
    """Commit the guest receipt and immutable intake under one maintenance fence."""
    import json
    import pika
    from sqlalchemy import text
    from myink.db import tenant_session
    from myink.models import Task, Project
    from myink.models.maintenance import AdmissionIntent, QueueHandoff
    from myink.maintenance import require_admission_open, register_admission, intent_outcome
    from myink.worker import amqp
    from myink.worker.handoff import admission_lane
    from myink.platform_readiness import require_operation_ready
    operation_id = str(uuid.uuid4())
    priority = amqp.priority_for_user(user_id)
    with new_session() as db:
        require_admission_open(db)
        task = db.get(Task, uuid.UUID(task_id), with_for_update=True)
        if task is None:
            raise GuestQuotaError('TASK_NOT_FOUND', 404)
        project = db.get(Project, task.project_id)
        if project is None or str(project.user_id) != str(user_id):
            raise GuestQuotaError('TASK_NOT_OWNED', 403)
        if task.status == 'queued':
            return {'task_id': task_id, 'status': 'queued', 'message': '续跑已受理'}
        if task.status not in {'failed','paused','awaiting_review'}:
            raise GuestQuotaError('TASK_NOT_RESUMABLE', 409)
        require_operation_ready(task.task_type, user_id)
        before = task.status
        receipt, _ = reserve_resume(db, task, user_id, client_ip, operation_id)
        payload = {**(task.payload or {}), '_guest_resume_operation': operation_id}
        if receipt:
            payload['_guest_operation'] = receipt
        task.payload, task.status, task.error = payload, 'queued', None
        project_id = str(task.project_id)
        resume_type = {'batch_generate':'batch_resume','short_generate':'short_resume'}.get(task.task_type,'chapter_resume')
        message = {'task_id':task_id,'project_id':project_id,'user_id':str(user_id),
                   'task_type':resume_type,'payload':payload,'trace_id':task.trace_id or task_id,
                   'request_id':operation_id,'retry_count':0,'created_at':''}
        db.execute(text("SELECT set_config('app.tenant_id', :pid, true)"), {'pid':project_id})
        intent_id = register_admission(db, message, priority=priority)
        db.commit()
    with admission_lane(intent_id, project_id) as lane:
        if lane is None:
            raise GuestQuotaError('GUEST_PUBLISH_UNCERTAIN', 503)
        with tenant_session(project_id) as db:
            intent = db.get(AdmissionIntent, intent_id)
            state = intent.publication_state
            outbox = db.scalar(select(QueueHandoff.operation_id).where(QueueHandoff.admission_id == intent_id))
        if state == 'published':
            return {'task_id':task_id,'status':'queued','message':'已投递续跑消息'}
        if state != 'pending' or outbox is not None:
            raise GuestQuotaError('GUEST_PUBLISH_UNCERTAIN', 503)
        intent_outcome(intent_id, project_id, publication_state='unknown')
        try:
            amqp.publish_once(json.dumps(message,ensure_ascii=False),amqp.KEY_TASKS,priority=priority)
        except Exception as exc:
            definite = isinstance(exc,(amqp.PublishNotSent,pika.exceptions.NackError,pika.exceptions.UnroutableError))
            if definite:
                with tenant_session(project_id) as db:
                    intent = db.get(AdmissionIntent, intent_id, with_for_update=True)
                    possible = intent.publication_state == 'published' or db.scalar(select(QueueHandoff.operation_id).where(QueueHandoff.admission_id == intent_id)) is not None
                    if not possible:
                        task = db.get(Task,uuid.UUID(task_id),with_for_update=True)
                        release_in_session(db,receipt)
                        intent.publication_state = 'not_attempted'
                        if task is not None and task.status == 'queued' and (task.payload or {}).get('_guest_resume_operation') == operation_id:
                            task.status = before
            raise GuestQuotaError('GUEST_PUBLISH_REJECTED' if definite else 'GUEST_PUBLISH_UNCERTAIN',503) from exc
        intent_outcome(intent_id, project_id, publication_state='published')
    return {'task_id':task_id,'status':'queued','message':'已投递续跑消息'}


def require_review_admission(db, task_id, candidate_ids):
    """A candidate rejected after admission cannot silently add paid revision."""
    from myink.models import Task, Project
    task = db.get(Task, uuid.UUID(task_id.split(':')[0]))
    if task is None:
        return
    user = db.get(User, db.get(Project, task.project_id).user_id)
    if not user.is_guest:
        return
    permitted = set((task.payload or {}).get('_guest_review_candidates', []))
    if not {str(cid) for cid in candidate_ids}.issubset(permitted):
        raise GuestQuotaError('GUEST_REVIEW_NOT_ADMITTED', 409)
