"""Offline admission selection using the real mapped tables and SQLite queries.

These tests do not exercise PostgreSQL RLS, Redis gates, or broker publication.
"""
import hashlib
import json
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


BODY = dict(task_id='00000000-0000-0000-0000-000000000010',
            project_id='00000000-0000-0000-0000-000000000020',
            user_id='00000000-0000-0000-0000-000000000030',
            task_type='chapter_resume', request_id='same-budget-operation',
            budget_operation_id='same-budget-operation', retry_count=0, payload={})


def digest(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@pytest.fixture
def admission_db(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'src'))
    from myink.models.maintenance import AdmissionIntent, QueueHandoff
    engine = create_engine('sqlite:///:memory:')
    AdmissionIntent.__table__.create(engine)
    QueueHandoff.__table__.create(engine)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def intent(db, number, *, gate='not_required', publication='published', body=BODY):
    from myink.models.maintenance import AdmissionIntent
    row = AdmissionIntent(id=uuid.UUID(int=number), task_id=uuid.UUID(body['task_id']),
                          project_id=uuid.UUID(body['project_id']), user_id=uuid.UUID(body['user_id']),
                          message_id=body['request_id'], epoch='epoch', deployment_generation=1,
                          deployment_id='deployment', owner='human', payload_hash=digest(body),
                          rebuild_payload=dict(body), priority=0, gate_state=gate,
                          publication_state=publication)
    db.add(row)
    db.flush()
    return row


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('gate', ['accepted', 'not_required'])
def test_rejected_same_operation_attempt_cannot_shadow_published_retry(admission_db, reverse, gate):
    from myink.worker.handoff import admission_for
    db = admission_db
    rejected = intent(db, 1, gate=gate, publication='rejected')
    published = intent(db, 2, gate=gate)
    db.execute(text('PRAGMA reverse_unordered_selects=' + ('ON' if reverse else 'OFF')))
    assert rejected.payload_hash == published.payload_hash
    selected = admission_for(db, dict(BODY))
    assert selected is not None
    assert selected.id == published.id


@pytest.mark.parametrize('gate,publication', [
    ('pending', 'published'), ('unknown', 'published'), ('rejected', 'published'),
    ('compensated', 'published'), ('not_required', 'rejected'),
    ('accepted', 'not_attempted'),
])
def test_unconfirmed_or_rejected_intake_cannot_authorize(admission_db, gate, publication):
    from myink.worker.handoff import admission_for
    intent(admission_db, 1, gate=gate, publication=publication)
    assert admission_for(admission_db, dict(BODY)) is None


@pytest.mark.parametrize('changes', [
    {'project_id': '00000000-0000-0000-0000-000000000021'},
    {'task_id': '00000000-0000-0000-0000-000000000011'},
    {'payload': {'changed': True}},
])
def test_changed_identity_or_payload_cannot_borrow_published_intake(admission_db, changes):
    from myink.worker.handoff import admission_for
    intent(admission_db, 1)
    assert admission_for(admission_db, {**BODY, **changes}) is None


def test_unknown_task_without_intake_cannot_authorize(admission_db):
    from myink.worker.handoff import admission_for
    assert admission_for(admission_db, dict(BODY)) is None


@pytest.mark.parametrize('publication,allowed', [('published', True), ('unknown', True), ('rejected', False)])
def test_handoff_keeps_bound_original_admission_authority(admission_db, publication, allowed):
    from myink.models.maintenance import QueueHandoff
    from myink.worker.handoff import admission_for
    db = admission_db
    original = intent(db, 1, publication=publication)
    retry = {**BODY, 'retry_count': 1}
    db.add(QueueHandoff(operation_id='delivery-1', message_id=BODY['request_id'],
                       task_id=original.task_id, project_id=original.project_id,
                       admission_id=original.id, body_hash=digest(retry), destination='tasks',
                       state='published', rebuild_payload=retry, priority=0))
    db.flush()
    selected = admission_for(db, retry)
    assert (selected.id if selected is not None else None) == (original.id if allowed else None)
