"""One original task per night; pending packages stop every expensive callback."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,uuid
import pytest
from ops.pi.tests.test_manager_completion import finished,stopped,completed,config_file
from ops.pi.tests.test_nightly_bundle import Image
from ops.pi.nightly_gate import ApprovalGate
from ops.pi.development_inputs import file_hash,ledger_snapshot

NOW=datetime(2026,10,30,18,tzinfo=timezone.utc)


@pytest.fixture
def driver_case(finished):
    state,fee,task,qp,*_=finished;store=state.parent/'nightly.sqlite';ApprovalGate.initialize(store,state,fee,mode='SIMULATED')
    root=qp.parent/'nightly';root.mkdir(mode=0o700);lock=qp.parent/'nightly.lock';lock.touch(mode=0o600)
    cfg=dict(schema='pi-nightly-driver-v1',mode='SIMULATED',state_path=str(state),billing_path=str(fee),gate_path=str(store),root=str(root),lock_path=str(lock),inherit_task_id=task,base_image_id='sha256:'+'6'*64,docker='/bin/echo',endpoint='unix:///test.sock',daemon_id='test-daemon',autonomy_profile=None)
    cp=qp.parent/'nightly-driver.json';cp.write_text(json.dumps(cfg));cp.chmod(0o600);Image.calls=[]
    now=[NOW]
    def gate():return ApprovalGate(store,state,fee,mode='SIMULATED',clock=lambda:now[0])
    return cp,cfg,finished,now,gate


def tick(case,**kwargs):
    from ops.pi.nightly_driver import run
    return run(case[0],file_hash(case[0]),clock=lambda:case[3][0],image_factory=Image,**kwargs)


def test_finished_candidate_is_inherited_before_intake_then_waits_across_dates(driver_case):
    cp,cfg,finished,now,gate=driver_case;calls=[];before=ledger_snapshot(finished[0]),ledger_snapshot(finished[1])
    def forbidden(*a,**k):pytest.fail('unconfirmed or inherited candidate must not call intake/manager')
    result=tick(driver_case,admit=forbidden,manager_trigger=forbidden)
    assert result['status']=='waiting_human' and result['phase']=='awaiting_approval' and len(Image.calls)==1
    assert gate().status()['task_id']==finished[2]
    for days in (1,4,14):
        now[0]=NOW+timedelta(days=days);r=tick(driver_case,admit=forbidden,manager_trigger=forbidden)
        assert r['phase']=='awaiting_approval' and r['cycle_id']==result['cycle_id']
    assert len(Image.calls)==1 and (ledger_snapshot(finished[0]),ledger_snapshot(finished[1]))==before


def test_unknown_build_blocks_round_without_retry_next_night(driver_case,monkeypatch):
    def fail(*a,**k):raise TimeoutError('owned build not confirmed')
    monkeypatch.setattr(Image,'build',fail)
    assert tick(driver_case)['status']=='blocked';assert driver_case[4]().status()['phase']=='blocked'
    driver_case[3][0]+=timedelta(days=2)
    assert tick(driver_case)['status']=='waiting_human'


def test_original_task_binding_cannot_change_or_be_forged_after_seal(driver_case):
    g=driver_case[4]();cycle=str(uuid.uuid4());g.begin(cycle,'2026-10-31');g.bind_task(cycle,driver_case[2][2]);g.bind_task(cycle,driver_case[2][2])
    with pytest.raises(ValueError):g.bind_task(cycle,'foreign')
    assert g.status()['task_id']==driver_case[2][2]


def test_empty_source_configuration_does_not_create_an_unbounded_new_scope(driver_case):
    cp,cfg,*_=driver_case;cfg['inherit_task_id']=None;cp.write_text(json.dumps(cfg))
    result=tick(driver_case)
    assert result['status']=='source_not_configured' and driver_case[4]().status()['phase']=='idle'
    assert Image.calls==[]


def test_root_profile_admission_and_original_manager_notification_are_single_claims(driver_case):
    cp,cfg,finished,now,gate=driver_case;cfg['inherit_task_id']=None;profile=cp.parent/'profile.json';profile.write_text('{}');profile.chmod(0o600);cfg['autonomy_profile']=dict(path=str(profile),sha256=file_hash(profile));cp.write_text(json.dumps(cfg));calls=[]
    def admit(*args):calls.append('source');return dict(status='admitted',research_fingerprint='a'*64)
    def trigger(task):calls.append(('manager',task));return dict(status='started')
    result=tick(driver_case,admit=admit,manager_trigger=trigger)
    assert result['phase']=='awaiting_approval' and calls==['source',('manager',finished[2])]
    tick(driver_case,admit=admit,manager_trigger=trigger);assert len(calls)==2


def test_interrupted_source_intent_blocks_without_replaying_models(driver_case):
    cp,cfg,finished,now,gate=driver_case;g=gate();cycle=str(uuid.uuid4());g.begin(cycle,'2026-10-31');root=Path(cfg['root'])/cycle;root.mkdir(mode=0o700)
    p=root/'admission-intent.json';p.write_text('{}');p.chmod(0o600)
    result=tick(driver_case,admit=lambda *a:pytest.fail('source replay'))
    assert result['status']=='blocked' and gate().status()['phase']=='blocked'


def test_daytime_idle_does_not_claim_a_new_round(driver_case):
    driver_case[3][0]=NOW+timedelta(hours=8)
    assert tick(driver_case)['status']=='outside_window' and driver_case[4]().status()['phase']=='idle'
    assert Image.calls==[]


def test_prepared_source_does_not_start_manager_outside_admission_window(driver_case):
    cp,cfg,finished,now,gate=driver_case;g=gate();cycle=str(uuid.uuid4());g.begin(cycle,'2026-10-31');g.bind_task(cycle,finished[2]);root=Path(cfg['root'])/cycle;root.mkdir(mode=0o700)
    for name,value in [('start.json',dict(config_sha256=file_hash(cp))),('selected.json',dict(task_id=finished[2],origin='original_source_coordinator'))]:
        p=root/name;p.write_text(json.dumps(value));p.chmod(0o600)
    now[0]+=timedelta(hours=8)
    def forbidden(*a):pytest.fail('outside-window manager notification')
    r=tick(driver_case,manager_trigger=forbidden)
    assert r['status']=='waiting_next_window' and gate().status()['phase']=='preparing' and not (root/'manager-intent.json').exists()


def _human_deploy_permission(case):
    tick(case);cp,cfg,finished,now,gate=case;g=gate();s=g.status();root=Path(cfg['root'])/s['cycle_id'];manifest=json.loads((root/'bundle/manifest.json').read_bytes())
    from ops.pi.audit import digest
    p=root/'operator.json';p.write_text(json.dumps(dict(schema='pi-nightly-human-approval-v1',mode='SIMULATED',issuer='human_operator',cycle_id=s['cycle_id'],package_sha256=digest(manifest),approved_actions=['deploy'],issued_at=now[0].isoformat(),expires_at=(now[0]+timedelta(hours=1)).isoformat())));p.chmod(0o600);pin=file_hash(p);g.approve(s['cycle_id'],p,pin)
    return g,s['cycle_id'],root,manifest,pin


def test_approved_driver_only_verifies_deployment_without_new_intake(driver_case):
    g,cycle,root,manifest,pin=_human_deploy_permission(driver_case);calls=[]
    result=tick(driver_case,deployment_confirm=lambda *a:calls.append('verify') or dict(status='awaiting_deployment'))
    assert result['phase']=='awaiting_deployment' and calls==['verify'] and len(Image.calls)==1


def test_observing_driver_routes_only_confirmed_version_assessment(driver_case):
    from ops.pi.audit import digest
    g,cycle,root,m,approval_pin=_human_deploy_permission(driver_case);cp,cfg,finished,now,gate=driver_case
    p=root/'deployment.json';p.write_text(json.dumps(dict(schema='pi-nightly-deployment-receipt-v1',mode='SIMULATED',issuer='trusted_deployment_verifier',cycle_id=cycle,package_sha256=digest(m),approval_sha256=approval_pin,image_id=m['image_id'],source_sha256=m['source_sha256'],comparison_sha256=m['comparison_sha256'],deployment_id='verified-one',deployed_at=now[0].isoformat())));p.chmod(0o600);g.deployed(cycle,p,file_hash(p))
    observer=root/'observer.json';observer.write_text('{}');observer.chmod(0o600);cfg['observation_config']=dict(path=str(observer),sha256=file_hash(observer));cp.write_text(json.dumps(cfg));calls=[]
    result=tick(driver_case,assessor=lambda *a:calls.append('assessment') or dict(status='insufficient_evidence'))
    assert result['phase']=='observing' and calls==['assessment'] and len(Image.calls)==1
