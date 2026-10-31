"""Next-day collection is deployment-anchored and never fabricates improvement."""
from datetime import timedelta
from pathlib import Path
import json
import pytest
from ops.pi.tests.test_nightly_deployment import deployed_case,bundle_case,finished,stopped,completed,config_file,Image,confirm
from ops.pi.development_inputs import file_hash,ledger_snapshot
from ops.pi.audit import digest


@pytest.fixture
def observation_case(deployed_case):
    confirm(deployed_case);case,calls=deployed_case;g,cycle,root,task,finished,now=case
    with g._connection() as c:packet=json.loads(g._row(c,cycle)['deployment'])['packet']
    cp=root/'observer.json';value=dict(schema='pi-live-observer-v1',mode='SIMULATED',lookback_hours=1,identity=dict(deployment_id=packet['deployment_id'],image_ids=dict(python='sha256:'+'7'*64)),minimum_samples=20)
    state=root/'native-audit-state';state.mkdir(mode=0o700);value.update(audit_path=str(state/'events.sqlite'),export_root=str(root/'native-audit-export'))
    cp.write_text(json.dumps(value));cp.chmod(0o600);callbacks=[]
    def observe(path,pin):
        callbacks.append('metrics');return dict(schema='pi-live-observer-result-v1',mode='SIMULATED',status='passed',config_sha256=digest(json.loads(Path(path).read_bytes())),observed_samples=20,minimum_samples=20,confounders=[],window=dict(start=(now[0]-timedelta(hours=1)).isoformat(),end=now[0].isoformat()),snapshot_sha256='4'*64)
    def check(e,path,write):callbacks.append('checker');return dict(passed=True,tests=len(e['test_cases']),failures=0,errors=0,skipped=0,cleanup=[dict(removed=True)])
    return case,cp,callbacks,observe,check


def assess(case,**kwargs):
    from ops.pi.nightly_observation import assess
    data,cp,calls,observe,check=case;g,cycle,root,*_=data
    return assess(g,cycle,root/'bundle',cp,file_hash(cp),observe=kwargs.get('observe',observe),check=kwargs.get('check',check))


def test_same_day_is_reserved_without_metrics_or_regression(observation_case):
    result=assess(observation_case)
    assert result['status']=='waiting_due' and observation_case[2]==[]
    assert observation_case[0][0].status()['phase']=='observing'


def test_due_assessment_is_once_and_records_no_online_improvement_claim(observation_case):
    data,cp,calls,observe,check=observation_case;g,cycle,root,task,finished,now=data;now[0]+=timedelta(hours=26);before=ledger_snapshot(finished[0]),ledger_snapshot(finished[1])
    result=assess(observation_case)
    assert result['status']=='completed' and result['online_improvement_proven'] is False and calls==['checker','metrics']
    assert g.status()['phase']=='idle' and (ledger_snapshot(finished[0]),ledger_snapshot(finished[1]))==before


def test_insufficient_samples_keep_observing_and_do_not_repeat_frozen_check(observation_case):
    data,cp,calls,observe,check=observation_case;data[5][0]+=timedelta(hours=26)
    def low(path,pin):r=observe(path,pin);r.update(status='insufficient_evidence',observed_samples=2);return r
    assert assess(observation_case,observe=low)['status']=='insufficient_evidence'
    data[5][0]+=timedelta(minutes=15)
    assert assess(observation_case,observe=low)['status']=='insufficient_evidence'
    assert calls==['checker','metrics','metrics'] and data[0].status()['phase']=='observing'


def test_failed_regression_reserves_manual_rollback_review_without_deploy(observation_case):
    data,cp,calls,observe,check=observation_case;data[5][0]+=timedelta(hours=26)
    def failed(*a):calls.append('checker');return dict(passed=False,tests=18,failures=1,errors=0,skipped=0,cleanup=[dict(removed=True)])
    r=assess(observation_case,check=failed)
    assert r['status']=='blocked' and r['next_action']=='manual_rollback_review' and calls==['checker'] and data[0].status()['phase']=='blocked'


@pytest.mark.parametrize('fault',['identity','predeployment_window'])
def test_wrong_version_or_old_window_cannot_close_comparison(observation_case,fault):
    data,cp,calls,observe,check=observation_case;data[5][0]+=timedelta(hours=26)
    if fault=='identity':
        c=json.loads(cp.read_bytes());c['identity']['image_ids']['python']='sha256:'+'5'*64;cp.write_text(json.dumps(c))
    def old(path,pin):r=observe(path,pin);r['window']['start']=(data[5][0]-timedelta(hours=30)).isoformat();return r
    with pytest.raises(ValueError):assess(observation_case,observe=old if fault=='predeployment_window' else observe)
    assert data[0].status()['phase']=='observing'


@pytest.mark.parametrize('outcome',['completed','insufficient_evidence','regression_failed'])
def test_nextday_results_and_rollback_advice_reserve_standard_admin_audit(observation_case,outcome):
    from ops.pi.audit import AuditStore
    from myink.pi_audit import AuditReader
    data,cp,calls,observe,check=observation_case;data[5][0]+=timedelta(hours=26)
    def metrics(*args):
        r=observe(*args)
        if outcome=='insufficient_evidence':r.update(status='insufficient_evidence',observed_samples=2)
        return r
    def fixed(*args):
        r=check(*args)
        if outcome=='regression_failed':r.update(passed=False,failures=1)
        return r
    assess(observation_case,observe=metrics,check=fixed);root=data[2]
    reserved=list((root/'observation').glob('assessment-*/audit.json'));assert len(reserved)==1
    packet=json.loads(reserved[0].read_bytes());parent=root/'audit-state';parent.mkdir(mode=0o700);store=AuditStore(parent/'audit.sqlite')
    for item in packet['records']:store.append(item['record_key'],item['event'])
    export=root/'audit-export';store.export(export);reader=AuditReader(export);assert reader.events(data[3])['total']==len(packet['records'])
    events=[r['event'] for r in packet['records']];assert any(r['kind']=='test' for r in events)
    assert all(r['details']['model_requests']==0 and r['details']['known_cost_microyuan']==0 for r in events)
    assert not any(r['kind']=='deployment' for r in events) and str(root) not in json.dumps(packet)
    if outcome=='regression_failed':assert any(r['kind']=='rollback' and r['status']=='blocked' and r['details']['next_action']=='manual_rollback_review' for r in events)


def test_nextday_audit_is_published_with_stable_plan_result_ids(observation_case):
    from ops.pi.audit import AuditStore
    data,cp,calls,observe,check=observation_case;g,cycle,root,*_=data;data[5][0]+=timedelta(hours=26)
    state=root/'publication-state';state.mkdir(mode=0o700);config=json.loads(cp.read_bytes());config.update(audit_path=str(state/'events.sqlite'),export_root=str(root/'published-audit'));cp.write_text(json.dumps(config))
    assess(observation_case)
    store=AuditStore(config['audit_path']);events=store.events();tests={e['details'].get('test_id'):e for e in events if e['kind']=='test'}
    assert set(tests)=={'nightly-regression-'+cycle,'nightly-metrics-'+cycle}
    assert all(e['status']=='passed' for e in tests.values())
    assert any(e['kind']=='observation' for e in events) and all(e['authority']=='audit_only' for e in events)
    from ops.pi.nightly_observation import publish_audit
    slot=next((root/'observation').glob('assessment-*'));before=store.events();publish_audit(g,cycle,slot,config)
    assert store.events()==before and calls==['checker','metrics']


def test_audit_export_failure_does_not_close_or_reexecute_assessment(observation_case,monkeypatch):
    from ops.pi import nightly_observation as module
    data,cp,calls,observe,check=observation_case;g,cycle,root,*_=data;data[5][0]+=timedelta(hours=26)
    def failure(*a):raise ValueError('audit export unavailable')
    monkeypatch.setattr(module,'publish_audit',failure,raising=False)
    with pytest.raises(ValueError):assess(observation_case)
    assert g.status()['phase']=='observing' and calls==['checker','metrics']
    slot=next((root/'observation').glob('assessment-*'));assert (slot/'audit.json').exists() and not (slot/'receipt.json').exists()
    with pytest.raises(ValueError):assess(observation_case)
    assert calls==['checker','metrics']
    data[5][0]+=timedelta(minutes=15)
    with pytest.raises(ValueError,match='unfinished observation claim'):assess(observation_case)
    assert calls==['checker','metrics'] and len(list((root/'observation').glob('assessment-*')))==1


@pytest.mark.parametrize('outcome',['completed','insufficient_evidence','regression_failed'])
def test_reserved_plans_link_only_to_actual_typed_cross_day_results(observation_case,outcome):
    from datetime import datetime
    from ops.pi.audit import AuditStore,SHANGHAI
    from myink.pi_audit import AuditReader
    data,cp,calls,observe,check=observation_case;g,cycle,root,task,_,now=data;planned=now[0]
    with g._connection() as db:deployed=datetime.fromisoformat(json.loads(g._row(db,cycle)['deployment'])['packet']['deployed_at'])
    due=(deployed.astimezone(SHANGHAI)+timedelta(days=1)).replace(hour=3,minute=0,second=0,microsecond=0);candidate=json.loads((root/'bundle/manifest.json').read_bytes())['source_sha256'];state=root/'contract-state';state.mkdir(mode=0o700);store=AuditStore(state/'audit.sqlite')
    plans=[dict(test_id='nightly-'+kind+'-'+cycle,scheduled_for=due.isoformat(),target_run_id=task,target_version_sha256=candidate,criterion='Fixture native result contract.',kind='regression' if kind=='regression' else 'metrics',status='planned') for kind in ('regression','metrics')]
    store.append('plan',dict(kind='followup',status='planned',run_id=task,occurred_at=planned.isoformat(),summary='Synthetic contract fixture only.',details={},version={},changes=[],evidence=[],followups=plans,mode='SIMULATED',evidence_domain='synthetic'));now[0]+=timedelta(hours=26)
    def metrics(*args):
        result=observe(*args)
        if outcome=='insufficient_evidence':result.update(status='insufficient_evidence',observed_samples=2)
        return result
    def fixed(*args):
        result=check(*args)
        if outcome=='regression_failed':result.update(passed=False,failures=1)
        return result
    assess(observation_case,observe=metrics,check=fixed);packet=json.loads(next((root/'observation').glob('assessment-*/audit.json')).read_bytes());export=root/'contract-export'
    for item in packet['records']:store.append(item['record_key'],item['event'])
    store.export(export);assert all(p['result'] is None for p in AuditReader(export).daily(planned.astimezone(SHANGHAI).date().isoformat())['next_tests'])
    # ACTUAL-shaped synthetic records exercise the consumer contract only;
    # no actual assessment, injected production clock or production data exists.
    for item in packet['records']:store.append(item['record_key']+':typed-fixture',dict(item['event'],mode='ACTUAL'))
    store.export(export);results={p['kind']:p['result'] for p in AuditReader(export).daily(planned.astimezone(SHANGHAI).date().isoformat())['next_tests']}
    assert results['regression']['status']==('failed' if outcome=='regression_failed' else 'passed')
    assert results['metrics'] is None if outcome=='regression_failed' else results['metrics']['status']==('passed' if outcome=='completed' else 'insufficient_evidence')


def test_audit_only_recovery_keeps_records_and_does_not_acknowledge_or_recheck(observation_case,monkeypatch):
    from ops.pi.audit import AuditStore
    from ops.pi.nightly_observation import publish_audit
    data,cp,calls,observe,check=observation_case;g,cycle,root,*_=data;data[5][0]+=timedelta(hours=26);config=json.loads(cp.read_bytes());original=AuditStore.export
    def unavailable(*a):raise OSError('export unavailable after append')
    monkeypatch.setattr(AuditStore,'export',unavailable)
    with pytest.raises(OSError):assess(observation_case)
    store=AuditStore(config['audit_path']);before=store.events();assert len(before)==4 and g.status()['phase']=='observing'
    monkeypatch.setattr(AuditStore,'export',original);slot=next((root/'observation').glob('assessment-*'));publish_audit(g,cycle,slot,config)
    assert store.events()==before and g.status()['phase']=='observing' and calls==['checker','metrics'] and not (slot/'receipt.json').exists()


def test_actual_publisher_rejects_nonfixed_outputs_before_opening_store(observation_case,monkeypatch):
    from types import SimpleNamespace
    from ops.pi import nightly_observation as module
    data,cp,*_=observation_case;g,cycle,root,*_=data;monkeypatch.setattr(module.os,'geteuid',lambda:0)
    with pytest.raises(ValueError):module.publish_audit(SimpleNamespace(mode='ACTUAL'),cycle,root/'outside-assessment',json.loads(cp.read_bytes()))


def test_optional_export_root_uses_existing_observer_default(observation_case):
    from myink.pi_audit import AuditReader
    data,cp,*_=observation_case;data[5][0]+=timedelta(hours=26);config=json.loads(cp.read_bytes());config.pop('export_root');cp.write_text(json.dumps(config))
    assert assess(observation_case)['status']=='completed'
    assert AuditReader(Path(config['audit_path']).parent/'export').events(data[3])['total']==4
