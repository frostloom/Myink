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
