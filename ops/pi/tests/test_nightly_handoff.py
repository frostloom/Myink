"""Human main updates end old observation without inventing a comparison result."""
from datetime import timedelta
from copy import deepcopy
import json,uuid
import pytest
from ops.pi.audit import digest,strict_json
from ops.pi.development_inputs import ledger_snapshot
from ops.pi.tests.test_nightly_gate import case,ready,permit,deployment


def deployed(case):
    g,cycle=ready(case);(p,pin),_=permit(case,cycle,case[2]);g.approve(cycle,p,pin)
    d,dp=deployment(case,cycle,case[2],pin);g.deployed(cycle,d,dp)
    return g,cycle,dp


def permission(case,cycle,dp,**changes):
    v=dict(schema='pi-nightly-manual-handoff-v1',mode='SIMULATED',issuer='human_operator',action='interrupt_for_manual_main_release',operation_id=str(uuid.uuid4()),cycle_id=cycle,package_sha256=digest(case[2]),deployment_sha256=dp,new_identity=dict(deployment_id='new-main',generation=2,owner='human',image_ids={'python':'sha256:'+'7'*64},commit_sha='8'*40,schema_id='schema',config_hash='9'*64),new_package_sha256='a'*64,driver_sha256='b'*64,profile_sha256='c'*64,issued_at=case[1][0].isoformat(),expires_at=(case[1][0]+timedelta(hours=1)).isoformat())
    v.update(changes);p,pin=case[3](v,'handoff');return p,pin,v


def test_exact_human_interruption_preserves_old_observation_and_original_accounting(case):
    g,cycle,dp=deployed(case);p,pin,v=permission(case,cycle,dp)
    before=ledger_snapshot(g.state),ledger_snapshot(g.billing)
    with g._connection() as c:old=dict(g._row(c,cycle))
    assert hasattr(g,'interrupt_observation'),'missing explicit human observation interruption'
    g.interrupt_observation(cycle,p,pin,'d'*64)
    assert g.status()['phase']=='idle'
    with g._connection() as c:
        row=dict(g._row(c,cycle));events=list(c.execute('SELECT kind,payload FROM approval_events WHERE cycle_id=?',(cycle,)))
    assert all(row[k]==old[k] for k in old if k not in ('phase','result_sha256'))
    assert row['phase']=='completed' and row['result_sha256']=='d'*64
    assert 'comparison_complete' not in [r[0] for r in events]
    event=strict_json([r[1] for r in events if r[0]=='observation_interrupted'][0])
    assert event['decision']=='insufficient_evidence' and event['permission_sha256']==pin and event['new_driver_sha256']==v['driver_sha256']
    assert (ledger_snapshot(g.state),ledger_snapshot(g.billing))==before
    g.interrupt_observation(cycle,p,pin,'d'*64)
    with pytest.raises(ValueError):g.interrupt_observation(cycle,p,pin,'e'*64)


@pytest.mark.parametrize('fault',['package_sha256','deployment_sha256','expiry','issuer','mode','action','extra'])
def test_wrong_or_expired_permission_cannot_end_observation(case,fault):
    g,cycle,dp=deployed(case);changes={fault:'f'*64}
    if fault=='expiry':changes={'expires_at':case[1][0].isoformat()}
    p,pin,_=permission(case,cycle,dp,**changes)
    assert hasattr(g,'interrupt_observation'),'missing explicit human observation interruption'
    with pytest.raises(ValueError):g.interrupt_observation(cycle,p,pin,'d'*64)
    assert g.status()['phase']=='observing'


def test_unpublished_candidate_cannot_be_discarded_by_observation_permission(case):
    g,cycle=ready(case);p,pin,_=permission(case,cycle,'d'*64)
    assert hasattr(g,'interrupt_observation'),'missing explicit human observation interruption'
    with pytest.raises(ValueError):g.interrupt_observation(cycle,p,pin,'d'*64)
    assert g.status()['phase']=='awaiting_approval'


@pytest.fixture
def handoff_case(case):
    from pathlib import Path
    from ops.pi.development_inputs import file_hash
    g,cycle,dp=deployed(case);parent=g.path.parent
    root=parent/'nightly';root.mkdir(mode=0o700);(root/cycle).mkdir(mode=0o700)
    lock=parent/'nightly.lock';lock.touch(mode=0o600)
    (parent/'maintenance.lock').touch(mode=0o600)
    profile=parent/'profile.json';profile.write_text('{}');profile.chmod(0o600)
    template=parent/'source-template.json';template.write_text('{}');template.chmod(0o600)
    cfg=dict(schema='pi-nightly-driver-v1',mode='SIMULATED',state_path=str(g.state),billing_path=str(g.billing),gate_path=str(g.path),root=str(root),lock_path=str(lock),inherit_task_id=None,base_image_id='sha256:'+'7'*64,docker='/bin/echo',endpoint='unix:///test.sock',daemon_id='test-daemon',autonomy_profile=dict(path=str(profile),sha256=file_hash(profile)),source_template=dict(path=str(template),sha256=file_hash(template)))
    driver=parent/'new-driver.json';driver.write_text(json.dumps(cfg));driver.chmod(0o600)
    p,pin,v=permission(case,cycle,dp,driver_sha256=file_hash(driver),profile_sha256=file_hash(profile))
    audit_dir=parent/'audit';audit_dir.mkdir(mode=0o700)
    proof=dict(identity=v['new_identity'],package_sha256=v['new_package_sha256'],source_sha256='e'*64,profile_sha256=v['profile_sha256'],cohort_sha256='f'*64,audit_path=str(audit_dir/'events.sqlite'),export_root=str(parent/'export'),observer=dict(path=str(profile),sha256=file_hash(profile)),deployed_at=g.clock().isoformat(),metrics_source_sha256='d'*64)
    output=root/cycle/('manual-handoff-'+v['operation_id'])
    def execute(verify=None):
        from ops.pi.nightly_handoff import handoff
        return handoff(g,p,pin,driver,file_hash(driver),output,verify=verify or (lambda *args:deepcopy(proof)))
    return g,cycle,p,pin,v,driver,cfg,proof,output,execute


def test_handoff_exports_insufficient_evidence_before_unblocking_original_manager(handoff_case):
    g,cycle,p,pin,v,driver,cfg,proof,out,execute=handoff_case
    before=ledger_snapshot(g.state),ledger_snapshot(g.billing)
    result=execute()
    assert result['status']=='handed_off' and result['comparison_status']=='interrupted' and result['online_improvement_proven'] is False
    assert g.status()['phase']=='idle' and (ledger_snapshot(g.state),ledger_snapshot(g.billing))==before
    from ops.pi.audit import AuditStore
    import sqlite3
    with sqlite3.connect(proof['audit_path']) as db:
        rows=db.execute('SELECT payload FROM pi_audit_events').fetchall()
    events=[strict_json(row[0]) for row in rows]
    assert events and all(e['status']=='insufficient_evidence' for e in events)
    assert all(e['details']['reference']=='nightly.manual_handoff.v1' for e in events)
    assert (out/'verified.json').exists() and not result['model_requests']
    assert execute(lambda *args:pytest.fail('cached handoff must not inspect or execute again'))==result


@pytest.mark.parametrize('fault',['identity','package_sha256','profile_sha256','source_sha256','cohort_sha256'])
def test_bad_new_version_proof_keeps_original_observation(handoff_case,fault):
    g,*rest=handoff_case;proof=handoff_case[7];execute=handoff_case[-1]
    def verify(*args):
        result=deepcopy(proof);result[fault]='invalid';return result
    with pytest.raises(ValueError):execute(verify)
    assert g.status()['phase']=='observing'


def test_handoff_never_replays_an_unfinished_intent(handoff_case):
    g,*_=handoff_case;out=handoff_case[-2];out.mkdir(mode=0o700);(out/'intent.json').write_text('{}')
    with pytest.raises(ValueError,match='unfinished'):handoff_case[-1](lambda *args:pytest.fail('do not repeat verifier'))
    assert g.status()['phase']=='observing'


def test_audit_failure_cannot_release_gate(handoff_case,monkeypatch):
    from ops.pi.audit import AuditStore
    def fail(*args):raise OSError('export unavailable')
    monkeypatch.setattr(AuditStore,'export',fail)
    with pytest.raises(OSError):handoff_case[-1]()
    assert handoff_case[0].status()['phase']=='observing'


def test_concurrent_nightly_lock_prevents_handoff(handoff_case):
    import fcntl
    with open(handoff_case[6]['lock_path'],'rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):handoff_case[-1](lambda *args:pytest.fail('locked verifier'))
    assert not handoff_case[-2].exists()


def test_changed_accounting_is_not_authorized_by_manual_release(handoff_case):
    g=handoff_case[0]
    def changed(*args):
        from ops.pi.ledger import Ledger
        Ledger(g.billing,existing=True).intent('unexpected-model','model_attempt',{'held_microyuan':1})
        return deepcopy(handoff_case[7])
    with pytest.raises(ValueError,match='accounting'):handoff_case[-1](changed)
    assert g.status()['phase']=='observing'


def test_version_drift_while_audit_is_exported_cannot_end_observation(handoff_case):
    calls=[]
    def changing(*args):
        result=deepcopy(handoff_case[7]);calls.append(None)
        if len(calls)>1:result['cohort_sha256']='0'*64
        return result
    with pytest.raises(ValueError,match='changed'):handoff_case[-1](changing)
    assert handoff_case[0].status()['phase']=='observing'


def test_actual_handoff_rejects_injected_verifier_before_any_effect(handoff_case):
    g=handoff_case[0];g.mode='ACTUAL'
    with pytest.raises(ValueError,match='root native'):handoff_case[-1](lambda *args:pytest.fail('actual callback'))
    assert not handoff_case[-2].exists()


def test_original_product_maintenance_lock_serializes_manual_handoff(handoff_case):
    from pathlib import Path
    import fcntl
    path=Path(handoff_case[6]['lock_path']).with_name('maintenance.lock')
    with path.open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):handoff_case[-1](lambda *args:pytest.fail('maintenance lock busy'))
    assert not handoff_case[-2].exists()


def test_same_deployment_cannot_be_relabelled_as_new_main(case):
    g,cycle,dp=deployed(case)
    p,pin,v=permission(case,cycle,dp)
    v['new_identity']['deployment_id']='manual-release-one';p.write_text(json.dumps(v))
    from ops.pi.development_inputs import file_hash
    with pytest.raises(ValueError):g.interrupt_observation(cycle,p,file_hash(p),'d'*64)
    assert g.status()['phase']=='observing'


def test_failed_handoff_cannot_be_retried_under_another_operation_uuid(handoff_case,monkeypatch):
    from ops.pi.audit import AuditStore
    from ops.pi.development_inputs import file_hash
    from ops.pi.nightly_handoff import handoff
    g,cycle,_,_,value,driver,_,_,out,execute=handoff_case
    original=AuditStore.export
    monkeypatch.setattr(AuditStore,'export',lambda *args:(_ for _ in ()).throw(OSError('failed export')))
    with pytest.raises(OSError):execute()
    monkeypatch.setattr(AuditStore,'export',original)
    changed=dict(value,operation_id=str(uuid.uuid4()));p=g.path.parent/'new-permission.json';p.write_text(json.dumps(changed));p.chmod(0o600)
    with pytest.raises(ValueError,match='unfinished'):
        handoff(g,p,file_hash(p),driver,file_hash(driver),out.parent/('manual-handoff-'+changed['operation_id']),verify=lambda *args:pytest.fail('new UUID must not repeat effects'))
    assert g.status()['phase']=='observing' and (out/'intent.json').exists()


@pytest.mark.parametrize('installed', ['a'*64,'b'*64,None])
def test_installed_nightly_controller_must_match_executing_verified_release(monkeypatch,installed):
    from ops.pi import nightly_handoff as mod
    monkeypatch.setenv('PI_OBSERVER_RUNTIME_SHA256','a'*64)
    assert hasattr(mod,'_controller_pin'),'missing executing-release binding'
    if installed=='a'*64:mod._controller_pin(installed)
    else:
        with pytest.raises(ValueError):mod._controller_pin(installed)


@pytest.mark.parametrize('fault',[None,'container','image','daemon','endpoint','database','user','unsafe_role'])
def test_native_metric_probe_binds_actual_pg_and_validates_readonly_views(tmp_path,monkeypatch,fault):
    from types import SimpleNamespace
    from ops.pi import nightly_handoff as mod,nightly_deployment,psql_metrics
    from ops.pi.tests.test_psql_metrics import Runner,metadata
    source=dict(docker='/usr/bin/docker',endpoint='unix:///var/run/docker.sock',daemon_id=nightly_deployment.PRODUCTION,container_id='a'*64,image_id='sha256:'+'b'*64,database='myink',database_user='myink',view_sha256='c'*64)
    pg=dict(Id=source['container_id'],Image=source['image_id'],State=dict(Running=True))
    monkeypatch.setattr(nightly_deployment,'_run',lambda *args,**kwargs:json.dumps([pg]).encode())
    changes={'container':('container_id','d'*64),'image':('image_id','sha256:'+'d'*64),'daemon':('daemon_id','different'),'endpoint':('endpoint','unix:///other.sock'),'database':('database','other'),'user':('database_user','other')}
    if fault in changes:source[changes[fault][0]]=changes[fault][1]
    real=psql_metrics.PsqlMetricsReader
    def reader(config):
        meta=metadata(config)
        if fault=='unsafe_role':meta['superuser']=True
        return real(config,run=Runner(config,meta=meta))
    monkeypatch.setattr(psql_metrics,'PsqlMetricsReader',reader)
    assert hasattr(mod,'_metrics_source'),'missing live PG/readonly metadata source verification'
    if fault is None:assert mod._metrics_source(dict(source=source),None,SimpleNamespace(container='a'*64),case_now())==digest(source)
    else:
        with pytest.raises(ValueError):mod._metrics_source(dict(source=source),None,SimpleNamespace(container='a'*64),case_now())


def case_now():
    from datetime import datetime,timezone
    return datetime(2026,10,31,7,tzinfo=timezone.utc)
