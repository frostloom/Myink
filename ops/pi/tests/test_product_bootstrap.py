"""First product bootstrap: real control ledger, fixed trusted host boundary."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import importlib.util
import uuid

import pytest

from ops.pi.audit import digest
from ops.pi.contracts import Identity
from ops.pi.ledger import Ledger, OperationConflict

NOW = datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc)
STEPS = ('close_ingress', 'drain_legacy', 'backup_pre', 'install_schema', 'bind_identity')
COUNTS = ('active_tasks', 'ready_messages', 'unacked_messages', 'consumers', 'task_locks', 'book_locks', 'unknown')


def api():
    assert importlib.util.find_spec('ops.pi.product_bootstrap'), 'missing durable product bootstrap protocol'
    from ops.pi.product_bootstrap import prepare_bootstrap
    return prepare_bootstrap


@pytest.fixture
def case(tmp_path):
    images={k:'sha256:'+str(i)*64 for i,k in enumerate(('python','frontend','postgres','redis','rabbitmq'),1)}
    roles=('api','worker','worker','frontend','postgres','redis','rabbitmq')
    legacy=dict(source_commit='a'*40, source_sha256='b'*64,
                containers=[dict(id=format(i,'x')*64, service=role, image_id=images['python' if role in ('api','worker') else role]) for i,role in enumerate(roles,1)])
    candidate=asdict(Identity('next-deployment',1,'pi',images,commit_sha='c'*40,schema_id='maintenance-v1',config_hash='d'*64))
    plan=dict(schema='pi-product-bootstrap-v1',mode='SIMULATED',operation_id=str(uuid.uuid4()),legacy=legacy,candidate=candidate,expires_at=(NOW+timedelta(minutes=10)).isoformat())
    ledger=Ledger(tmp_path/'control.sqlite')
    class Host:
        def __init__(self):
            self.calls=[];self.identity=deepcopy(legacy);self.denied=False;self.drift_after=None;self.fail=None;self.tamper=None
        @contextmanager
        def lock(self, value):
            self.calls.append('lock')
            yield
        def authorize(self, value):
            self.calls.append('authorize')
            if self.denied:raise PermissionError('external approval unavailable')
        def inspect(self, value):
            self.calls.append('inspect')
            return deepcopy(self.identity)
        def perform(self, action, value, context):
            assert ledger.get(value['operation_id'])['status']=='pending'
            intent=ledger.get(value['operation_id']+':'+action)
            assert intent and intent['status']=='pending', 'effect must follow durable intent'
            self.calls.append(action)
            if self.fail==action:raise ConnectionError('effect outcome lost')
            facts=dict(verified=True,plan_sha256=digest(value))
            if action=='close_ingress':facts['fence_sha256']='f'*64
            elif action=='drain_legacy':facts.update(fence_sha256='f'*64,worker_exit_codes=[0,0],**dict.fromkeys(COUNTS,0))
            elif action=='backup_pre':facts.update(release_pair_id=value['operation_id'],manifest_sha256='e'*64,restore_operation_id='restore:'+value['operation_id'],source_sha256=value['legacy']['source_sha256'])
            elif action=='install_schema':facts.update(source_commit=value['candidate']['commit_sha'],historical_provenance_updated=False,protocol=dict(protocol=1,schema=1,state=1,effect_keys=1,serialization='jsonplus'))
            elif action=='bind_identity':facts['identity']=deepcopy(value['candidate'])
            if self.tamper:self.tamper(action,facts)
            if self.drift_after==action:self.identity['containers'][0]['image_id']='sha256:'+'9'*64
            return facts
    return ledger,plan,Host()


def test_bootstrap_prepares_closed_protocol_without_activating_or_reopening(case):
    ledger,plan,host=case
    receipt=api()(ledger,plan,host,now=lambda:NOW)
    assert receipt.status=='done'
    assert [v for v in host.calls if v in STEPS]==list(STEPS)
    assert receipt.evidence['phase']=='protocol_prepared'
    assert receipt.evidence['release_allowed'] is False and receipt.evidence['admission_closed'] is True
    assert 'activate' not in host.calls and 'reopen' not in host.calls
    assert ledger.get(plan['operation_id'])['evidence']==receipt.evidence


@pytest.mark.parametrize('field',COUNTS)
def test_unsettled_drain_prevents_backup_and_schema(case,field):
    ledger,plan,host=case
    host.tamper=lambda action,facts: facts.update({field:1}) if action=='drain_legacy' else None
    result=api()(ledger,plan,host,now=lambda:NOW)
    assert result.status=='blocked'
    assert 'backup_pre' not in host.calls and 'install_schema' not in host.calls
    assert ledger.get(plan['operation_id']+':close_ingress')['status']=='done'


@pytest.mark.parametrize('codes',[[0,137],[0],[0,True]])
def test_only_complete_natural_worker_exit_permits_bootstrap(case,codes):
    ledger,plan,host=case
    host.tamper=lambda action,facts: facts.update(worker_exit_codes=codes) if action=='drain_legacy' else None
    assert api()(ledger,plan,host,now=lambda:NOW).status=='blocked'
    assert 'install_schema' not in host.calls


def test_gate_cannot_use_a_different_ingress_fence(case):
    ledger,plan,host=case
    host.tamper=lambda action,facts: facts.update(fence_sha256='0'*64) if action=='drain_legacy' else None
    assert api()(ledger,plan,host,now=lambda:NOW).status=='blocked'
    assert 'backup_pre' not in host.calls


@pytest.mark.parametrize('when',[None,'close_ingress','drain_legacy','backup_pre'])
def test_identity_drift_stops_next_mutation(case,when):
    ledger,plan,host=case
    if when is None:host.identity['source_commit']='9'*40
    else:host.drift_after=when
    result=api()(ledger,plan,host,now=lambda:NOW)
    assert result.status=='blocked'
    assert 'install_schema' not in host.calls
    if when is None:assert 'close_ingress' not in host.calls


@pytest.mark.parametrize('action',STEPS)
def test_unknown_effect_is_immutable_and_never_replayed(case,action):
    ledger,plan,host=case;host.fail=action
    result=api()(ledger,plan,host,now=lambda:NOW)
    assert result.status=='uncertain'
    assert ledger.get(plan['operation_id']+':'+action)['status']=='uncertain'
    calls=list(host.calls);host.fail=None
    again=api()(ledger,plan,host,now=lambda:NOW)
    assert again.status=='uncertain' and host.calls==calls


def test_crash_after_parent_intent_never_dispatches_on_reentry(case):
    ledger,plan,host=case
    ledger.intent(plan['operation_id'],'product_bootstrap',dict(plan_sha256=digest(plan)))
    assert api()(ledger,plan,host,now=lambda:NOW).status=='uncertain'
    assert host.calls==[] and ledger.get(plan['operation_id'])['status']=='pending'


def test_reentry_of_completed_preparation_is_not_new_authority(case):
    ledger,plan,host=case
    first=api()(ledger,plan,host,now=lambda:NOW);calls=list(host.calls)
    assert api()(ledger,plan,host,now=lambda:NOW)==first
    assert host.calls==calls
    changed=deepcopy(plan);changed['candidate']['generation']=2
    with pytest.raises(OperationConflict):api()(ledger,changed,host,now=lambda:NOW)


@pytest.mark.parametrize('reason',['denied','expired'])
def test_missing_current_authority_has_no_product_effect(case,reason):
    ledger,plan,host=case
    if reason=='denied':host.denied=True
    else:plan['expires_at']=(NOW-timedelta(seconds=1)).isoformat()
    assert api()(ledger,plan,host,now=lambda:NOW).status=='blocked'
    assert not any(v in STEPS for v in host.calls)


@pytest.mark.parametrize('action,field,value',[
    ('backup_pre','source_sha256','0'*64),
    ('backup_pre','release_pair_id','unrelated'),
    ('backup_pre','restore_operation_id',None),
    ('install_schema','historical_provenance_updated',True),
    ('install_schema','source_commit','0'*40),
    ('bind_identity','identity',{}),
    ('drain_legacy','active_tasks',False),
])
def test_incomplete_or_conflicting_proofs_cannot_prepare(case,action,field,value):
    ledger,plan,host=case
    host.tamper=lambda current,facts:facts.update({field:value}) if current==action else None
    assert api()(ledger,plan,host,now=lambda:NOW).status in ('blocked','uncertain')
    assert 'reopen' not in host.calls


def test_actual_cannot_be_claimed_by_injected_adapter_or_clock(case):
    ledger,plan,host=case;plan['mode']='ACTUAL'
    assert api()(ledger,plan,host,now=lambda:NOW).status=='blocked'
    assert host.calls==[]


def test_crash_after_step_intent_stays_pending_and_cannot_replay(case):
    ledger,plan,host=case
    class PowerLoss(BaseException):pass
    def crash(action,value,context):raise PowerLoss()
    host.perform=crash
    with pytest.raises(PowerLoss):api()(ledger,plan,host,now=lambda:NOW)
    assert ledger.get(plan['operation_id']+':close_ingress')['status']=='pending'
    calls=list(host.calls)
    assert api()(ledger,plan,host,now=lambda:NOW).status=='uncertain'
    assert host.calls==calls


def test_revocation_between_steps_leaves_fence_closed(case):
    ledger,plan,host=case
    perform=host.perform
    def revoke(action,value,context):
        result=perform(action,value,context)
        if action=='close_ingress':host.denied=True
        return result
    host.perform=revoke
    assert api()(ledger,plan,host,now=lambda:NOW).status=='blocked'
    assert [v for v in host.calls if v in STEPS]==['close_ingress']
    assert ledger.get(plan['operation_id']+':close_ingress')['status']=='done'


def test_contending_same_operation_cannot_finish_another_owner(case,tmp_path):
    fcntl=pytest.importorskip('fcntl')
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event, Lock, local, get_ident
    ledger,plan,host=case
    gate=Barrier(2);running=Event();release=Event();local_state=local();seen=set();seen_lock=Lock()
    original_get=ledger.get
    def raced_get(identity):
        value=original_get(identity)
        if identity==plan['operation_id'] and not getattr(local_state,'locked',False):
            with seen_lock:
                first=get_ident() not in seen;seen.add(get_ident())
            if first:gate.wait(timeout=5)  # Both initial reads precede the winning claim.
        return value
    ledger.get=raced_get
    @contextmanager
    def shared_lock(value):
        with (tmp_path/'maintenance.lock').open('a+b') as locked:
            fcntl.flock(locked,fcntl.LOCK_EX|fcntl.LOCK_NB)
            local_state.locked=True
            try:yield
            finally:local_state.locked=False;fcntl.flock(locked,fcntl.LOCK_UN)
    host.lock=shared_lock;perform=host.perform
    def hold(action,value,context):
        if action=='close_ingress':
            running.set();assert release.wait(timeout=5)
        return perform(action,value,context)
    host.perform=hold
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(api(),ledger,deepcopy(plan),host,now=lambda:NOW) for _ in range(2)]
        try:
            assert running.wait(timeout=5)
            from concurrent.futures import wait,FIRST_COMPLETED
            done,_=wait(futures,timeout=5,return_when=FIRST_COMPLETED)
            assert len(done)==1 and next(iter(done)).result().status in ('blocked','uncertain')
            assert original_get(plan['operation_id'])['status']=='pending', 'contender overwrote the active owner'
        finally:release.set()
        results=[f.result() for f in futures]
    assert sum(v.status=='done' for v in results)==1
    assert [v for v in host.calls if v in STEPS]==list(STEPS)


@pytest.mark.parametrize('field,value',[('schema',2),('state',True),('serialization','pickle')])
def test_incompatible_migrated_protocol_never_binds_identity(case,field,value):
    ledger,plan,host=case
    def change(action,facts):
        if action=='install_schema':facts['protocol'][field]=value
    host.tamper=change
    assert api()(ledger,plan,host,now=lambda:NOW).status=='uncertain'
    assert 'bind_identity' not in host.calls
