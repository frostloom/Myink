"""Human-gated cycle state survives dates/processes without touching original ledgers."""
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import importlib.util,json,sqlite3,uuid
import pytest
from ops.pi.audit import digest
from ops.pi.ledger import Ledger,LedgerBlocked
from ops.pi import manager

NOW=datetime(2026,10,30,18,tzinfo=timezone.utc)


def api():
    assert importlib.util.find_spec('ops.pi.nightly_gate'),'missing persistent nightly human gate'
    from ops.pi.nightly_gate import ApprovalGate
    return ApprovalGate


@pytest.fixture
def case(tmp_path):
    billing=tmp_path/'original-fee.sqlite';Ledger(billing);billing.chmod(0o600)
    for i in range(9):Ledger(billing).intent('historical-'+str(i),'model_attempt',dict(held_microyuan=2000000))
    state=tmp_path/'original-manager.sqlite';manager.init(state,billing,mode='SIMULATED')
    now=[NOW];path=tmp_path/'approval.sqlite'
    package=dict(schema='pi-nightly-artifact-v1',baseline_sha256='a'*64,source_sha256='b'*64,patch_sha256='c'*64,evaluation_sha256='d'*64,image_id='sha256:'+'e'*64,image_artifact_sha256='f'*64,comparison_sha256='1'*64,changes_sha256='2'*64)
    def open_gate(initialize=False):
        if initialize:api().initialize(path,state,billing,mode='SIMULATED')
        return api()(path,state,billing,mode='SIMULATED',clock=lambda:now[0])
    def packet(value,name='approval'):
        p=tmp_path/(name+'-'+str(uuid.uuid4())+'.json');p.write_text(json.dumps(value));p.chmod(0o600)
        from hashlib import sha256
        return p,sha256(p.read_bytes()).hexdigest()
    return open_gate,now,package,packet,state,billing,path


def ready(case):
    open_gate,now,pkg,packet,*_=case;g=open_gate(True);cycle=str(uuid.uuid4());assert g.begin(cycle,'2026-10-31')['claimed']
    assert g.ready(cycle,pkg)['phase']=='awaiting_approval';return g,cycle


def permit(case,cycle,pkg,actions=None):
    _,now,_,packet,*_=case
    value=dict(schema='pi-nightly-human-approval-v1',mode='SIMULATED',issuer='human_operator',cycle_id=cycle,package_sha256=digest(pkg),approved_actions=actions or ['github_push','registry_push','deploy'],issued_at=now[0].isoformat(),expires_at=(now[0]+timedelta(hours=1)).isoformat())
    return packet(value),value


def deployment(case,cycle,pkg,approval_pin):
    _,now,_,packet,*_=case
    return packet(dict(schema='pi-nightly-deployment-receipt-v1',mode='SIMULATED',issuer='trusted_deployment_verifier',cycle_id=cycle,package_sha256=digest(pkg),approval_sha256=approval_pin,image_id=pkg['image_id'],source_sha256=pkg['source_sha256'],comparison_sha256=pkg['comparison_sha256'],deployment_id='manual-release-one',deployed_at=now[0].isoformat()),'deployment')


def test_unconfirmed_package_blocks_across_days_restart_and_original_ledger_stays_valid(case):
    g,cycle=ready(case);open_gate,now,_,_,state,billing,_=case
    before=manager.status(state,billing,mode='SIMULATED')
    for day in (1,3,14):
        now[0]=NOW+timedelta(days=day);g=open_gate()
        result=g.begin(str(uuid.uuid4()),now[0].date().isoformat());assert not result['claimed'] and result['phase']=='awaiting_approval' and result['cycle_id']==cycle
        for action in ('github_push','registry_push','deploy','observe_metrics'):
            with pytest.raises(ValueError):g.require_action(cycle,action)
    assert manager.status(state,billing,mode='SIMULATED')==before
    assert all(Ledger(billing,existing=True).get('historical-'+str(i))['status']=='pending' for i in range(9))


def test_approval_is_not_deployment_and_expiry_does_not_start_new_cycle(case):
    g,cycle=ready(case);pkg=case[2];(p,pin),_=permit(case,cycle,pkg)
    assert g.approve(cycle,p,pin)['phase']=='awaiting_deployment'
    g.require_action(cycle,'deploy')
    with pytest.raises(ValueError):g.require_action(cycle,'observe_metrics')
    case[1][0]+=timedelta(days=3);g=case[0]()
    assert not g.begin(str(uuid.uuid4()),'2026-11-03')['claimed']
    with pytest.raises(ValueError):g.require_action(cycle,'deploy')
    assert g.status()['phase']=='awaiting_approval'


def test_no_release_cannot_discard_an_unconfirmed_artifact(case):
    g,cycle=ready(case)
    with pytest.raises(ValueError):g.no_release(cycle,'no_task','a'*64)
    assert g.status()['phase']=='awaiting_approval'


def test_verified_deployment_unlocks_observation_and_only_completion_allows_next_night(case):
    g,cycle=ready(case);pkg=case[2];(p,pin),_=permit(case,cycle,pkg);g.approve(cycle,p,pin)
    d,dpin=deployment(case,cycle,pkg,pin);assert g.deployed(cycle,d,dpin)['phase']=='observing'
    g.require_action(cycle,'observe_metrics');assert not g.begin(str(uuid.uuid4()),'2026-11-01')['claimed']
    case[1][0]+=timedelta(days=2);g=case[0]();g.require_action(cycle,'observe_metrics')
    assert g.complete(cycle,'3'*64)['phase']=='idle'
    assert not g.begin(str(uuid.uuid4()),'2026-10-31')['claimed']
    assert g.begin(str(uuid.uuid4()),'2026-11-02')['claimed']


@pytest.mark.parametrize('field,value',[('issuer','model'),('package_sha256','0'*64),('cycle_id',str(uuid.uuid4())),('mode','ACTUAL'),('approved_actions',['shell']),('expires_at','2020-01-01T00:00:00+00:00')])
def test_spoofed_or_wrong_approval_is_rejected(case,field,value):
    g,cycle=ready(case);(_,pin),v=permit(case,cycle,case[2]);v[field]=value;p,pin=case[3](v)
    with pytest.raises(ValueError):g.approve(cycle,p,pin)
    assert g.status()['phase']=='awaiting_approval'


@pytest.mark.parametrize('field,value',[('image_id','sha256:'+'0'*64),('source_sha256','0'*64),('comparison_sha256','0'*64),('approval_sha256','0'*64),('issuer','model')])
def test_unmatched_deployment_cannot_read_metrics(case,field,value):
    g,cycle=ready(case);pkg=case[2];(p,pin),_=permit(case,cycle,pkg);g.approve(cycle,p,pin)
    d,_=deployment(case,cycle,pkg,pin);v=json.loads(d.read_bytes());v[field]=value;d,dpin=case[3](v,'deployment')
    with pytest.raises(ValueError):g.deployed(cycle,d,dpin)
    with pytest.raises(ValueError):g.require_action(cycle,'observe_metrics')


def test_parallel_triggers_claim_only_one_cycle(case):
    g=case[0](True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(lambda _:case[0]().begin(str(uuid.uuid4()),'2026-10-31'),range(2)))
    assert sum(v['claimed'] for v in outcomes)==1


def test_preparation_crash_and_failed_round_never_reset_on_next_day(case):
    g=case[0](True);cycle=str(uuid.uuid4());g.begin(cycle,'2026-10-31')
    assert case[0]().status()['phase']=='preparing'
    assert not case[0]().begin(str(uuid.uuid4()),'2026-11-03')['claimed']
    g.block(cycle,'preparation_unconfirmed');assert case[0]().status()['phase']=='blocked'
    assert not g.begin(str(uuid.uuid4()),'2026-11-04')['claimed']


def test_sealed_package_cannot_change_and_approval_file_replacement_revokes_action(case):
    g,cycle=ready(case);other=deepcopy(case[2]);other['image_id']='sha256:'+'4'*64
    with pytest.raises(ValueError):g.ready(cycle,other)
    (p,pin),_=permit(case,cycle,case[2]);g.approve(cycle,p,pin);p.write_text('{}')
    with pytest.raises(ValueError):g.require_action(cycle,'deploy')


def test_gate_format_cannot_be_fee_or_manager_ledger_and_history_is_append_only(case):
    g=case[0](True);path=case[-1]
    with pytest.raises(LedgerBlocked):Ledger(path,existing=True)
    with sqlite3.connect(path) as c:
        with pytest.raises(sqlite3.DatabaseError):c.execute('DELETE FROM approval_events')
    for target in (case[-2],case[-3]):
        with pytest.raises(ValueError):api().initialize(target,case[-3],case[-2],mode='SIMULATED')
