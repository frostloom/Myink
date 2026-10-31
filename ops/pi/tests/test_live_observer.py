"""Frozen live windows publish audit facts, never model authority."""
from datetime import datetime,timezone,timedelta
import importlib
import json
from pathlib import Path
import pytest
from ops.pi.audit import AuditStore
from myink.pi_audit import AuditReader
from ops.pi.tests.test_metrics import PROVENANCE

NOW=datetime(2026,10,28,10,16,tzinfo=timezone.utc)


def api():return importlib.import_module('ops.pi.live_observer')


@pytest.fixture
def configured(tmp_path):
    tmp_path.chmod(0o700)
    for name in ('config','output','audit'):(tmp_path/name).mkdir(mode=0o700)
    path=tmp_path/'config/observer.json'
    value=dict(schema='pi-live-observer-v1',mode='SIMULATED',root=str(tmp_path/'output'),audit_path=str(tmp_path/'audit/events.sqlite'),source=dict(docker='/usr/bin/docker',endpoint='unix:///var/run/docker.sock',daemon_id='synthetic-daemon',container_id='a'*64,image_id='sha256:'+'b'*64,database='myink',database_user='myink',view_sha256='c'*64),identity={},interval_minutes=15,lookback_hours=24,minimum_samples=20)
    path.write_text(json.dumps(value));path.chmod(0o600)
    return path,value


def update(configured,**changes):
    path,value=configured;value.update(changes);path.write_text(json.dumps(value));return path


class Rows:
    def __init__(self,count=0,mixed=False,missing=False):self.calls=[];self.count=count;self.mixed=mixed;self.missing=missing
    def __call__(self,request):
        self.calls.append(request);at=NOW-timedelta(hours=1);rows=[]
        for i in range(self.count):
            if request['source']=='tasks':rows.append(dict(id='task-'+str(i),batch_task_id=None,chapter_seq=None,status='done',task_type='other' if self.mixed and i==0 else 'chapter_generate',created_at=at,updated_at=at+timedelta(minutes=5)))
            else:rows.append(dict(id=i,task_id='task-'+str(i),node='write',model_id='synthetic',input_tokens=1,output_tokens=1,cost_est=0,duration_ms=10,created_at=at+timedelta(minutes=1),provenance={} if self.missing else dict(PROVENANCE),measurement={} if self.missing else dict(kind='model',cost=True,latency=True,pricing_id='a'*64)))
        offset=request['params']['offset'];return rows[offset:offset+request['params']['limit']]


def run(configured,rows=None,clock=None):
    return api().observe(configured[0],clock=clock or (lambda:NOW),reader=rows or Rows())


def test_empty_window_is_insufficient_and_main_reads_actual_unknowns(configured):
    path,c=configured;result=run(configured)
    assert result['status']=='insufficient_evidence' and result['mode']=='SIMULATED' and result['evidence_domain']=='synthetic'
    assert result['observed_samples']==0 and result['automatic_execution'] is False
    snapshot=json.loads((Path(c['root'])/result['run_id']/'metrics.json').read_text())
    assert snapshot['identity']['generation'] is None and snapshot['identity']['deployment_id'] is None
    r=AuditReader(Path(c['audit_path']).parent/'export')
    assert r.events(result['run_id'],kind='observation')['items'][-1]['status']=='insufficient_evidence'
    assert all(e['mode']=='SIMULATED' and e['evidence_domain']!='online_business' for e in r.events(result['run_id'])['items'])
    assert r.daily('2026-10-28')['release_state']=='unknown'  # simulated no_release is not an actual release fact


def test_replayed_window_uses_frozen_facts_without_requery_or_duplicate(configured):
    rows=Rows();first=run(configured,rows)
    before=AuditStore(configured[1]['audit_path']).events();count=len(rows.calls)
    second=run(configured,rows,lambda:NOW+timedelta(minutes=2))
    assert second==first and len(rows.calls)==count
    assert AuditStore(configured[1]['audit_path']).events()==before


def test_known_same_type_cohort_and_unknown_history_remain_distinct(configured):
    result=run(configured,Rows(20));assert result['status']=='passed'
    assert result['observed_samples']==20
    result2=run(configured,Rows(20,missing=True),lambda:NOW+timedelta(minutes=15))
    assert result2['status']=='insufficient_evidence'
    result3=run(configured,Rows(20,mixed=True),lambda:NOW+timedelta(minutes=30))
    assert result3['status']=='insufficient_evidence' and 'mixed_task_types' in result3['confounders']


def test_zero_cost_and_missing_measurement_are_not_conflated(configured):
    first=run(configured,Rows(1));second=run(configured,Rows(1,missing=True),lambda:NOW+timedelta(minutes=15))
    root=Path(configured[1]['root'])
    a=json.loads((root/first['run_id']/'metrics.json').read_text());b=json.loads((root/second['run_id']/'metrics.json').read_text())
    assert a['measurements']['cost']['value']==0 and b['measurements']['cost']['value'] is None


def test_truncated_window_cannot_claim_complete_measurement(configured):
    result=run(configured,Rows(1000))
    assert result['status']=='insufficient_evidence' and result['availability']=='unknown'
    assert 'query_truncated' in result['confounders']


def test_failed_source_is_recorded_without_secret_exception_text(configured):
    def broken(request):raise RuntimeError('token=private-error-value raw body')
    result=run(configured,broken)
    assert result['status']=='blocked' and result['evidence_domain']=='unknown'
    events=AuditStore(configured[1]['audit_path']).events()
    assert events[-1]['status']=='blocked'
    assert 'private-error-value' not in json.dumps(events)
    assert not (Path(configured[1]['root'])/result['run_id']/'metrics.json').exists()


def test_actual_mode_never_accepts_injected_source(configured):
    update(configured,mode='ACTUAL');rows=Rows()
    with pytest.raises(ValueError,match='ACTUAL'):run(configured,rows)
    assert rows.calls==[] and not Path(configured[1]['audit_path']).exists()


@pytest.mark.parametrize('change',[dict(minimum_samples=5),dict(minimum_samples=True),dict(provider_key='never-allowed'),dict(interval_minutes=0),dict(lookback_hours=1000)])
def test_untrusted_config_never_enters_collection(configured,change):
    update(configured,**change);rows=Rows()
    with pytest.raises(ValueError):run(configured,rows)
    assert rows.calls==[]


def test_window_artifact_tampering_is_not_treated_as_cached_success(configured):
    result=run(configured);p=Path(configured[1]['root'])/result['run_id']/'metrics.json';p.write_text('{}')
    with pytest.raises(ValueError):run(configured)


def test_reconfigured_source_during_read_does_not_publish_metrics(configured):
    rows=Rows()
    def changed(request):
        result=rows(request);update(configured,minimum_samples=30);return result
    result=run(configured,changed)
    assert result['status']=='blocked' and result['evidence_domain']=='unknown'


def test_fee_schema_is_never_opened_as_mutable_audit_target(configured):
    from ops.pi.ledger import Ledger
    p=Path(configured[1]['audit_path']);Ledger(p);p.chmod(0o600)
    before=p.read_bytes();rows=Rows()
    with pytest.raises(ValueError):run(configured,rows)
    assert p.read_bytes()==before and rows.calls==[]


def test_corrupt_cached_receipt_cannot_forge_a_success(configured):
    result=run(configured);p=Path(configured[1]['root'])/result['run_id']/'receipt.json'
    changed=json.loads(p.read_text());changed['status']='passed';changed['observed_samples']=999;p.write_text(json.dumps(changed))
    with pytest.raises(ValueError):run(configured)


def test_explicit_export_directory_preserves_private_database_separation(configured):
    target=Path(configured[1]['root']).parent/'public-audit'
    update(configured,export_root=str(target))
    result=run(configured)
    assert AuditReader(target).events(result['run_id'])['total']>=2


@pytest.mark.parametrize('identity',[dict(image_ids={'x'*81:'sha256:'+'a'*64}),dict(owner='sk-private-key-value-123456')])
def test_invalid_audit_identity_is_rejected_before_creating_outputs(configured,identity):
    update(configured,identity=identity)
    with pytest.raises(ValueError):run(configured)
    assert not Path(configured[1]['audit_path']).exists()
    assert not list(Path(configured[1]['root']).iterdir())


def test_export_failure_retains_previous_good_manifest(configured,monkeypatch):
    import os
    first=run(configured);root=Path(configured[1]['audit_path']).parent/'export';before=(root/'manifest.json').read_bytes();replace=os.replace
    def fail(source,target):
        if Path(target).name=='manifest.json':raise OSError('synthetic manifest publication failure')
        return replace(source,target)
    with monkeypatch.context() as patch:
        patch.setattr(os,'replace',fail)
        result=run(configured,clock=lambda:NOW+timedelta(minutes=15))
    assert result['status']=='blocked' and result['export_published'] is False
    assert (root/'manifest.json').read_bytes()==before
    assert AuditReader(root).events(first['run_id'])['total']>=2


def test_unfinished_window_is_retained_without_automatic_requery(configured):
    rows=Rows();result=run(configured,rows);count=len(rows.calls)
    (Path(configured[1]['root'])/result['run_id']/'receipt.json').unlink()
    with pytest.raises(ValueError,match='unfinished'):run(configured,rows)
    assert len(rows.calls)==count


def test_oversized_snapshot_is_blocked_before_copying_to_report(configured,monkeypatch):
    module=api()
    monkeypatch.setattr(module,'collect_snapshot',lambda *a,**k:dict(confounders=[],availability='unknown',oversized='private-body-'*100000))
    result=run(configured)
    assert result['status']=='blocked'
    assert not (Path(configured[1]['root'])/result['run_id']/'metrics.json').exists()
    assert 'private-body-' not in json.dumps(AuditStore(configured[1]['audit_path']).events())


def test_unrecognized_or_unfinished_tasks_do_not_certify_complete_window(configured):
    rows=Rows(21)
    def unknown(request):
        batch=rows(request)
        if request['source']=='tasks':batch[-1]['status']='unknown-status'
        return batch
    result=run(configured,unknown)
    assert result['status']=='insufficient_evidence'
    assert 'unknown_task_status' in result['confounders']


def test_real_cohort_fingerprint_is_stable_across_windows_and_changes_with_task_ids(configured):
    from ops.pi.audit import AuditStore
    from hashlib import sha256
    first=run(configured,Rows(2));second=run(configured,Rows(2),lambda:NOW+timedelta(minutes=15))
    def read(result):return json.loads((Path(configured[1]['root'])/result['run_id']/'metrics.json').read_bytes())
    a,b=read(first),read(second)
    assert len(a['cohort_sha256'])==64 and a['cohort_sha256']==b['cohort_sha256']
    original=Rows(2)
    def changed(request):
        rows=original(request)
        for row in rows:
            if request['source']=='tasks':row['id']='changed-'+row['id']
            else:row['task_id']='changed-'+row['task_id']
        return rows
    third=run(configured,changed,lambda:NOW+timedelta(minutes=30));assert read(third)['cohort_sha256']!=a['cohort_sha256']
    events=AuditStore(configured[1]['audit_path']).events(run_id=first['run_id'])
    terminal=next(e for e in events if e['kind']=='observation' and e['status']!='running')
    assert any(p['kind']=='observation_cohort' and p['sha256']==a['cohort_sha256'] and p['verified'] for p in terminal['evidence'])
