"""Post-window rollback has independent finite authority; activation never renews."""
from datetime import timedelta
from copy import deepcopy
from pathlib import Path
import importlib.util
import pytest
from ops.pi.audit import digest
from ops.pi.contracts import Receipt
from test_product_bootstrap import case as bootstrap_case,NOW
from test_product_runtime import runtime_case,write
from test_product_release import release_case,activation_inputs,context


def api():
    assert importlib.util.find_spec('ops.pi.product_rollback_lease'),'missing independently approved post-window rollback'
    from ops.pi import product_rollback_lease
    return product_rollback_lease


def packet(plan,target='rehearsal'):
    return dict(schema='pi-product-rollback-lease-v1',mode=plan['mode'],target=target,authority='owned_rehearsal' if target=='rehearsal' else 'human_product_release',plan_sha256=digest(plan),control_sha256='f'*64,candidate=deepcopy(plan['candidate']),approved_action='rollback',issued_at=NOW.isoformat(),expires_at=(NOW+timedelta(hours=48)).isoformat(),maximum_stopped_seconds=600)


def test_post_window_lease_is_finite_and_does_not_change_original_plan(bootstrap_case):
    _,plan,_=bootstrap_case;before=deepcopy(plan);lease=packet(plan)
    assert api().validate(lease,plan,'rehearsal',NOW+timedelta(hours=8))==lease
    assert plan==before


@pytest.mark.parametrize('fault',['action','plan','candidate','owner','control','mode','target','authority','expired','future','too-long','boolean-budget','unbounded-budget','extra'])
def test_lease_rejects_renewal_or_different_authority(bootstrap_case,fault):
    _,plan,_=bootstrap_case;p=packet(plan);now=NOW+timedelta(hours=8)
    if fault=='action':p['approved_action']='activate'
    elif fault=='plan':p['plan_sha256']='0'*64
    elif fault=='candidate':p['candidate']['generation']+=1
    elif fault=='owner':p['candidate']['owner']='different'
    elif fault=='control':p['control_sha256']='bad'
    elif fault=='mode':p['mode']='ACTUAL'
    elif fault=='target':p['target']='production'
    elif fault=='authority':p['authority']='model'
    elif fault=='expired':p['expires_at']=NOW.isoformat()
    elif fault=='future':p['issued_at']=(now+timedelta(minutes=1)).isoformat()
    elif fault=='too-long':p['expires_at']=(NOW+timedelta(days=10)).isoformat()
    elif fault=='boolean-budget':p['maximum_stopped_seconds']=True
    elif fault=='unbounded-budget':p['maximum_stopped_seconds']=1801
    elif fault=='extra':p['waive_debt']=True
    with pytest.raises(ValueError):api().validate(p,plan,'rehearsal',now)


def test_expired_host_requires_completed_original_adoption_and_cannot_bootstrap(runtime_case,tmp_path):
    from ops.pi.product_runtime import LinuxProductHost
    path,pin,c,plan,*_=runtime_case
    original=LinuxProductHost(path,pin,clock=lambda:NOW);permit=packet(plan);pp=tmp_path/'rollback-lease.json';ppin=write(pp,permit)
    with pytest.raises(ValueError):LinuxProductHost(path,pin,clock=lambda:NOW+timedelta(hours=8),rollback_lease_path=pp,rollback_lease_sha256=ppin)
    op='product-control:'+plan['operation_id']+':activate'
    original.ledger.intent(op,'product_control',dict(plan_sha256=digest(plan),config_sha256=permit['control_sha256'],action='activate'))
    original.ledger.finish(Receipt(op,'done',dict(verified=True,phase='native_candidate_open',identity=plan['candidate'])))
    h=LinuxProductHost(path,pin,clock=lambda:NOW+timedelta(hours=8),rollback_lease_path=pp,rollback_lease_sha256=ppin)
    with h.lock(plan):
        with pytest.raises(ValueError,match='rollback'):h.preflight()
        with pytest.raises(ValueError,match='rollback'):h.perform('close_ingress',plan,{})
        with pytest.raises(ValueError,match='rollback'):h._run(['info'])
    assert h.plan==plan and h.rollback_lease['approved_action']=='rollback'


def test_old_native_only_control_cannot_use_post_window_lease(release_case):
    from ops.pi.product_release import NativeProductRelease
    h,*rest=release_case;h.rollback_lease=packet(h.plan);h.rollback_lease['control_sha256']=release_case[2]
    with pytest.raises(ValueError,match='v2'):NativeProductRelease(*release_case[:5])
    assert not (h.root/'native-control').exists()


@pytest.mark.parametrize('fault',[None,'missing-parent','missing-stage','unknown-stage','wrong-control','activate-action','expired-timer'])
def test_native_return_needs_original_pending_parent_and_timer(bootstrap_case,tmp_path,fault):
    from types import SimpleNamespace
    _,plan,_=bootstrap_case;ledger=bootstrap_case[0];now=NOW+timedelta(hours=8);permit=packet(plan)
    h=SimpleNamespace(plan=plan,root=tmp_path,ledger=ledger,clock=lambda:now,rollback_lease=permit,rollback_lease_pin='b'*64)
    root='product-control:'+plan['operation_id']+':rollback';stage=root+':return'
    folder=tmp_path/'native-control/rollback';folder.mkdir(parents=True)
    value=api().start_packet(h)
    if fault=='expired-timer':value['started_at']=(now-timedelta(seconds=601)).isoformat()
    write(folder/'start.json',value)
    if fault!='missing-parent':ledger.intent(root,'product_control',dict(plan_sha256=digest(plan),config_sha256='0'*64 if fault=='wrong-control' else permit['control_sha256'],action='rollback'))
    if fault!='missing-stage':
        ledger.intent(stage,'product_control_step',dict(plan_sha256=digest(plan),config_sha256=permit['control_sha256'],step='return'))
        if fault=='unknown-stage':ledger.finish(Receipt(stage,'uncertain',dict(verified=False)))
    if fault is None:api().native_action(h,'create_rollback')
    else:
        with pytest.raises(ValueError):api().native_action(h,'create_candidate' if fault=='activate-action' else 'create_rollback')
    assert ledger.get('native:'+plan['operation_id']+':create_rollback') is None


def test_settled_historical_recovery_allows_a_new_pair(tmp_path):
    from test_backup import case,qualified_restore,backup as collect,CONTEXT,NOW as BACKUP_NOW
    from ops.pi import backup
    from ops.pi.product_release import _preflight_recovery
    from ops.pi.ledger import Ledger
    from dataclasses import asdict
    from ops.pi.contracts import Identity
    from test_backup import trusted_references
    ledger=Ledger(tmp_path/'history.sqlite');trusted_references(ledger)
    identity=Identity('old',1,'trusted',{'worker':'sha256:old'},commit_sha='frozen')
    pair={'release_pair_id':'release-1','pre_identity':asdict(identity),'post_identity':asdict(Identity('new',2,'trusted',{'worker':'sha256:new'},commit_sha='candidate')),'plan_hash':'a'*64}
    data=(ledger,identity,pair,tmp_path/'backups')
    qualified_restore(data);backup.mark_released(ledger,'release-1',pair['post_identity'],context=CONTEXT,now=BACKUP_NOW)
    with pytest.raises(ValueError):_preflight_recovery(ledger,'next-release',CONTEXT,BACKUP_NOW)
    qualified_restore(data,phase='POST')
    _preflight_recovery(ledger,'next-release',CONTEXT,BACKUP_NOW)
