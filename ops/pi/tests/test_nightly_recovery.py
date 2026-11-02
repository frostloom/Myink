from pathlib import Path
import uuid,json,pytest
from ops.pi.audit import digest
from ops.pi.development_inputs import file_hash,ledger_snapshot
from ops.pi.tests.test_preexec_reconciliation import old_claim,case


@pytest.fixture
def blocked_night(old_claim):
    from ops.pi.preexec_reconciliation import reconcile
    g,claim,put=old_claim;reconcile(claim,g.state,g.billing,mode='SIMULATED')
    cycle=str(uuid.uuid4());g.begin(cycle,'2026-10-31');root=claim.parent.parent/'nightly';root.mkdir(mode=0o700);root=root/cycle;root.mkdir(mode=0o700)
    put(root/'start.json',dict(config_sha256='a'*64));put(root/'admission-intent.json',dict(config_sha256='a'*64))
    put(root/'admission.json',dict(schema='pi-autonomy-coordinator-tick-v1',mode='SIMULATED',status='uncertain',model_requests=0))
    put(root/'failure.json',dict(status='blocked',failure_class='ValueError',model_replay=False))
    metrics=dict(schema='pi-live-observer-result-v1',mode='SIMULATED',status='insufficient_evidence',observed_samples=0,planned_tasks=0)
    put(root/'source-metrics.json',metrics);observer=root/'observer.json';put(observer,{})
    profile=root/'profile.json';put(profile,dict(observer=dict(observer_config_path=str(observer),observer_config_sha256=file_hash(observer))))
    put(root/'source-stage.json',dict(schema='pi-nightly-source-stage-v1',cycle_id=cycle,metrics_sha256=digest(metrics),fee_sha256=ledger_snapshot(g.billing)['sha256'],profile=dict(path=str(profile),sha256=file_hash(profile))))
    g.block(cycle,'nightly_preparation_ValueError')
    return g,cycle,root,claim,put


def test_recover_only_verified_unadmitted_zero_data_without_changing_history(blocked_night):
    from ops.pi.nightly_recovery import recover
    g,cycle,root,claim,put=blocked_night;before=ledger_snapshot(g.state),ledger_snapshot(g.billing)
    old=file_hash(root/'failure.json'),file_hash(claim/'receipt.json')
    with pytest.raises(ValueError):g.no_release(cycle,'no_evidence','a'*64)
    r=recover(g,cycle,root,claim);assert r['status']=='no_release' and g.status()['phase']=='idle'
    assert (file_hash(root/'failure.json'),file_hash(claim/'receipt.json'))==old
    assert (ledger_snapshot(g.state),ledger_snapshot(g.billing))==before
    with g._connection() as db:kinds=[r[0] for r in db.execute('SELECT kind FROM approval_events WHERE cycle_id=?',(cycle,))]
    assert 'blocked' in kinds and 'no_release' in kinds and 'comparison_complete' not in kinds
    assert recover(g,cycle,root,claim)==r


@pytest.mark.parametrize('fault',['selected','manager_intent','samples','unknown_count','admission_models','profile_pin','no_certificate'])
def test_recovery_refuses_any_unproven_or_possibly_executed_work(blocked_night,fault):
    from ops.pi.nightly_recovery import recover
    g,cycle,root,claim,put=blocked_night
    if fault=='selected':put(root/'selected.json',dict(task_id='foreign'))
    if fault=='manager_intent':put(root/'manager-intent.json',{})
    if fault in ('samples','unknown_count'):
        p=root/'source-metrics.json';v=json.loads(p.read_text());v['planned_tasks']=1 if fault=='samples' else None;put(p,v)
        q=root/'source-stage.json';v=json.loads(q.read_text());v['metrics_sha256']=file_hash(p);put(q,v)
    if fault=='admission_models':
        p=root/'admission.json';v=json.loads(p.read_text());v['model_requests']=1;put(p,v)
    if fault=='profile_pin':(root/'profile.json').write_text('{}')
    if fault=='no_certificate':(claim/'preexec-reconciliation.json').unlink()
    with pytest.raises(ValueError):recover(g,cycle,root,claim)
    assert g.status()['phase']=='blocked' and not (root/'recovery/verified.json').exists()
