"""Audit data is append-only, bounded and never fee/execution authority."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
import importlib
import json
import sqlite3
import pytest
from ops.pi.ledger import Ledger,LedgerBlocked

NOW=datetime(2026,10,28,16,1,tzinfo=timezone.utc)


def api():return importlib.import_module('ops.pi.audit')


@pytest.fixture
def record():
    return dict(kind='analysis',status='passed',run_id='run-1',occurred_at=None,
        summary='Fixed bounded analysis',details=dict(observed_samples=0,known_cost_microyuan=None),
        version=dict(source_commit='a'*40),changes=[],evidence=[],followups=[],
        mode='ACTUAL',evidence_domain='real_provider_fixed_input')


def store(tmp_path,clock=None):
    tmp_path.chmod(0o700)
    return api().AuditStore(tmp_path/'audit.sqlite',clock=clock or (lambda:NOW))


def test_append_reopen_and_hashed_chain(tmp_path,record):
    s=store(tmp_path);a=s.append('source:one',record)
    b=s.append('source:two',dict(record,kind='tool',details=dict(tool_name='candidate_status')))
    rows=api().AuditStore(s.path,clock=lambda:NOW).events()
    assert rows==[a,b] and [x['sequence'] for x in rows]==[1,2]
    assert a['previous_sha256'] is None and b['previous_sha256']==a['event_sha256']
    assert a['authority']=='audit_only' and a['schema_version']==1
    assert a['day']=='2026-10-29' and a['time_basis']=='recorded_at'
    assert a['occurred_at'] is None and a['details']['observed_samples']==0
    assert a['details']['known_cost_microyuan'] is None
    assert a['version']['candidate_sha256'] is None
    assert s.path.stat().st_mode&0o777==0o600


def test_identical_key_is_idempotent_and_conflict_retains_original(tmp_path,record):
    clock=[NOW];s=store(tmp_path,lambda:clock[0]);first=s.append('source:one',record)
    clock[0]+=timedelta(days=1)
    assert s.append('source:one',dict(record))==first
    with pytest.raises(ValueError,match='conflict'):s.append('source:one',dict(record,summary='changed'))
    assert s.events()==[first]


@pytest.mark.parametrize('statement',[
    "UPDATE pi_audit_events SET payload='{}'",
    "DELETE FROM pi_audit_events",
])
def test_database_rejects_historical_mutation(tmp_path,record,statement):
    s=store(tmp_path);s.append('source:one',record)
    c=sqlite3.connect(s.path)
    try:
        with pytest.raises(sqlite3.DatabaseError):c.execute(statement)
    finally:c.close()
    assert len(s.events())==1


def test_audit_schema_can_never_be_used_as_fee_ledger(tmp_path,record):
    s=store(tmp_path);s.append('source:one',record)
    with pytest.raises(LedgerBlocked):Ledger(s.path,existing=True)
    assert len(s.events())==1


def test_parallel_append_serializes_sequence_and_chain(tmp_path,record):
    s=store(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n:s.append('source:'+str(n),record),range(8)))
    rows=s.events()
    assert [x['sequence'] for x in rows]==list(range(1,9))
    assert all(rows[i]['previous_sha256']==rows[i-1]['event_sha256'] for i in range(1,len(rows)))


def test_known_secret_patterns_are_redacted_without_loss_of_provenance(tmp_path,record):
    raw='Bearer abcd1234topsecret PLATFORM_MODEL_API_KEY=sk-real-secretvalue password=p455word https://alice:privatepass@example.com/path'
    s=store(tmp_path);e=s.append('source:one',dict(record,summary=raw,details=dict(reason=raw)))
    encoded=json.dumps(e)
    for secret in ('abcd1234topsecret','sk-real-secretvalue','p455word','privatepass'):
        assert secret not in encoded
    assert e['redacted'] is True and e['record_key']=='source:one'


def test_summary_truncation_is_explicit(tmp_path,record):
    e=store(tmp_path).append('source:one',dict(record,summary='x'*4000))
    assert len(e['summary'])<=2000 and e['truncated'] is True


@pytest.mark.parametrize('change',[
    dict(unexpected='not allowed'),
    dict(details=dict(password='never export')),
    dict(details=dict(model_requests=True)),
    dict(details=dict(duration_ms=float('nan'))),
    dict(version=dict(source_commit='not-a-commit')),
    dict(changes=[dict(path='../credentials/key',category='production',added=1,deleted=0)]),
    dict(evidence=[dict(kind='session',sha256='a'*64,verified=True,evidence_domain='online_business',path='/private/key')]),
    dict(followups=[dict(test_id='next-1',scheduled_for='2026-10-29T02:00:00+00:00',target_run_id='run-1',target_version_sha256=None,criterion='Observe20samples',kind='metrics',status='passed')]),
    dict(occurred_at='2026-10-28T12:00:00'),
    dict(mode='SIMULATED',evidence_domain='online_business'),
])
def test_invalid_or_authority_looking_records_refused_without_append(tmp_path,record,change):
    s=store(tmp_path)
    with pytest.raises(ValueError):s.append('source:one',dict(record,**change))
    assert s.events()==[]


def test_explicit_historical_time_is_not_replaced_by_collector_day(tmp_path,record):
    e=store(tmp_path).append('source:one',dict(record,occurred_at='2026-10-28T15:59:00+00:00'))
    assert e['day']=='2026-10-28' and e['time_basis']=='occurred_at'
    assert e['recorded_at']!=e['occurred_at']


def test_symbolic_or_hardlinked_store_refused(tmp_path,record):
    s=store(tmp_path);s.append('source:one',record)
    link=tmp_path/'alias.sqlite';link.symlink_to(s.path)
    with pytest.raises(ValueError):api().AuditStore(link)
    link.unlink();link.hardlink_to(s.path)
    with pytest.raises(ValueError):api().AuditStore(link)


def test_existing_fee_database_is_not_repurposed_for_audit(tmp_path):
    from ops.pi.development_inputs import ledger_snapshot
    tmp_path.chmod(0o700);fee=Ledger(tmp_path/'fee.sqlite');fee.path.chmod(0o600)
    fee.intent('unchanged','synthetic',dict(value=1));before=ledger_snapshot(fee.path)
    with pytest.raises(ValueError):api().AuditStore(fee.path)
    assert ledger_snapshot(fee.path)==before


def test_same_redacted_display_does_not_hide_source_key_conflict(tmp_path,record):
    s=store(tmp_path)
    first=s.append('source:one',dict(record,summary='password=one-secret'))
    with pytest.raises(ValueError,match='conflict'):
        s.append('source:one',dict(record,summary='password=different-secret'))
    assert s.events()==[first]


def test_hash_valid_but_malformed_payload_is_not_exportable_audit(tmp_path,record):
    s=store(tmp_path);first=s.append('source:one',record)
    bad=dict(first,sequence=2,record_key='forged',previous_sha256=first['event_sha256'],
             details=dict(password='not-exportable'))
    bad['event_sha256']=api().digest({k:v for k,v in bad.items() if k!='event_sha256'})
    c=sqlite3.connect(s.path)
    try:
        with c:c.execute('INSERT INTO pi_audit_events VALUES (?,?,?,?,?,?)',
            (2,'forged','a'*64,bad['event_sha256'],bad['previous_sha256'],api().encoded(bad).decode()))
    finally:c.close()
    with pytest.raises(ValueError):s.events()


@pytest.mark.parametrize('field',['kind','status','mode','evidence_domain'])
def test_unhashable_enum_value_is_rejected_as_invalid_data(tmp_path,record,field):
    with pytest.raises(ValueError):store(tmp_path).append('source:one',dict(record,**{field:[]}))
