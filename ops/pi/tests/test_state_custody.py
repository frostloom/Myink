"""Synthetic canonical custody: no paid transport or candidate execution."""
import importlib
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from ops.pi import budget
from ops.pi.backup import snapshot_ledger
from ops.pi.ledger import Ledger
from ops.pi.tests.test_budget import ledger, policy, request
from ops.pi.tests.test_finite50_budget import seed, approve, finite
from ops.pi.tests.test_budget_amendment import snapshot


@pytest.fixture
def api(monkeypatch):
    try: module=importlib.import_module('ops.pi.state_custody')
    except ModuleNotFoundError:pytest.fail('state custody API missing')
    monkeypatch.setattr(module,'native_host_sha256',lambda:'a'*64)
    return module


@pytest.fixture
def ready(ledger,policy):
    seed(ledger);approve(ledger)
    return ledger,finite(policy)


def destination(path,host='a'):
    return dict(host_sha256=host*64,ledger_path=str(path.resolve()))


def freeze(api,ledger,target,transfer='transfer-001'):
    return api.freeze(ledger,transfer_id=transfer,destination=destination(target),authorization_reference='human:go-live')


def activate(api,ledger,status,transfer='transfer-001'):
    return api.activate(ledger,transfer_id=transfer,snapshot_sha256=status['snapshot_sha256'],authorization_reference='operator:handoff')


def clone(ledger,path):
    snapshot_ledger(ledger,path)
    return Ledger(path,existing=True)


def assert_denied(ledger,p):
    before=snapshot(ledger)
    with pytest.raises(budget.BudgetDenied,match='custody'):
        budget.reserve(ledger,'local-trial-1',request(),p)
    assert snapshot(ledger)==before


def test_legacy_paid_authorization_unchanged(api,ready):
    l,p=ready
    assert api.status(l)['phase']=='legacy'
    budget.settle(l,budget.reserve(l,'local-trial-1',request(),p),None)
    assert budget.totals(l,'local-trial-1')[0]==1


def test_freeze_blocks_source_and_reopened_source_before_analysis_authorize(api,ready,tmp_path):
    l,p=ready;old=snapshot(l)
    result=freeze(api,l,tmp_path/'destination.sqlite')
    assert result['phase']=='frozen'
    now=snapshot(l);assert now[0]==old[0] and now[1][:-1]==old[1]
    assert_denied(Ledger(l.path,existing=True),p)
    class ForbiddenSlot:
        def authorize(self,*args):pytest.fail('frozen reserve reached analysis mutation')
    with pytest.raises(budget.BudgetDenied,match='custody'):
        budget.reserve(l,'local-trial-1',request(),p,analysis_slot=ForbiddenSlot())
    assert snapshot(l)==now


def test_copy_activation_keeps_history_unknown_holds_and_finite_scope(api,ready,tmp_path):
    l,p=ready
    for _ in range(9):budget.settle(l,budget.reserve(l,'local-trial-1',request(),p),None)
    old=snapshot(l);totals=budget.totals(l,'local-trial-1');limits=budget.effective_trial_limits(l)
    target=tmp_path/'destination.sqlite';frozen=freeze(api,l,target);copy=clone(l,target)
    assert_denied(copy,p)
    activated=activate(api,copy,frozen)
    assert activated['phase']=='active' and activated['owner']==destination(target)
    now=snapshot(copy);assert now[0]==old[0] and now[1][:len(old[1])]==old[1]
    assert budget.totals(copy,'local-trial-1')==totals and budget.effective_trial_limits(copy)==limits
    assert_denied(l,p)
    permit=budget.reserve(copy,'local-trial-1',request(),p);budget.settle(copy,permit,None)
    assert budget.totals(copy,'local-trial-1')[0]==10


@pytest.mark.parametrize('expired',[False,True])
def test_pending_permit_blocks_freeze_even_expired(api,ready,tmp_path,expired):
    l,p=ready;budget.reserve(l,'local-trial-1',request(),p)
    # Frozen-clock expiry cannot convert an unsettled in-flight permit into quiescence.
    if expired:
        import unittest.mock
        clock=unittest.mock.patch('time.time',return_value=10**12);clock.start()
    try:
        before=snapshot(l)
        with pytest.raises(api.CustodyDenied,match='pending'):freeze(api,l,tmp_path/'target.sqlite')
        assert snapshot(l)==before
    finally:
        if expired:clock.stop()


@pytest.mark.parametrize('mismatch',['host','path','snapshot','transfer'])
def test_activation_rejects_wrong_binding_without_writes(api,ready,tmp_path,monkeypatch,mismatch):
    l,p=ready;target=tmp_path/'target.sqlite';frozen=freeze(api,l,target)
    copy=clone(l,tmp_path/'other.sqlite' if mismatch=='path' else target);before=snapshot(copy)
    if mismatch=='host':monkeypatch.setattr(api,'native_host_sha256',lambda:'b'*64)
    if mismatch=='snapshot':frozen=dict(frozen,snapshot_sha256='0'*64)
    with pytest.raises(api.CustodyDenied):activate(api,copy,frozen,'different-transfer' if mismatch=='transfer' else 'transfer-001')
    assert snapshot(copy)==before;assert_denied(copy,p)


@pytest.mark.parametrize('mismatch',['host','path'])
def test_active_copy_wrong_host_or_path_cannot_reserve(api,ready,tmp_path,monkeypatch,mismatch):
    l,p=ready;target=tmp_path/'target.sqlite';frozen=freeze(api,l,target);copy=clone(l,target);activate(api,copy,frozen)
    if mismatch=='path':copy=clone(copy,tmp_path/'fork.sqlite')
    else:monkeypatch.setattr(api,'native_host_sha256',lambda:'b'*64)
    assert_denied(copy,p)


def test_changed_frozen_snapshot_is_not_activation_authority(api,ready,tmp_path):
    l,p=ready;target=tmp_path/'target.sqlite';frozen=freeze(api,l,target);copy=clone(l,target)
    copy.append_event('diagnostic',dict(observed=True));before=snapshot(copy)
    with pytest.raises(api.CustodyDenied,match='snapshot'):activate(api,copy,frozen)
    assert snapshot(copy)==before;assert_denied(copy,p)


@pytest.mark.parametrize('kind,payload',[
    ('state-custody',{}),('state-custody-unknown',{}),
    ('state-custody',dict(phase='active',schema_version=1)),
    ('state-custody',dict(schema_version=True,phase='frozen'))])
def test_malformed_unknown_or_partial_custody_fails_closed(api,ready,kind,payload):
    l,p=ready;l.append_event(kind,payload);assert_denied(l,p)
    with pytest.raises(api.CustodyDenied):api.status(l)


@pytest.mark.parametrize('bad',[
    dict(host_sha256='bad',ledger_path='/tmp/x'),
    dict(host_sha256='a'*64,ledger_path='relative.sqlite'),
    dict(host_sha256='a'*64,ledger_path='/tmp/../x'),
    dict(host_sha256='a'*64,ledger_path='/tmp/x',extra=True)])
def test_invalid_destination_does_not_freeze(api,ready,bad):
    l,p=ready;before=snapshot(l)
    with pytest.raises(api.CustodyDenied):api.freeze(l,transfer_id='transfer-001',destination=bad,authorization_reference='human:go-live')
    assert snapshot(l)==before


def test_repeated_identity_and_return_transfer_require_new_chain(api,ready,tmp_path):
    l,p=ready;target=tmp_path/'target.sqlite';frozen=freeze(api,l,target);copy=clone(l,target);activate(api,copy,frozen)
    before=snapshot(copy)
    with pytest.raises(api.CustodyDenied):activate(api,copy,frozen)
    with pytest.raises(api.CustodyDenied):freeze(api,copy,tmp_path/'return.sqlite')
    assert snapshot(copy)==before
    returning=tmp_path/'return.sqlite';frozen2=freeze(api,copy,returning,'transfer-002');returned=clone(copy,returning);activate(api,returned,frozen2,'transfer-002')
    assert_denied(copy,p)
    permit=budget.reserve(returned,'local-trial-1',request(),p);budget.settle(returned,permit,None)


def test_freeze_reserve_race_has_only_one_paid_owner(api,ready,tmp_path):
    l,p=ready
    def reserve():
        try:return budget.reserve(Ledger(l.path,existing=True),'local-trial-1',request(),p)
        except budget.BudgetDenied:return None
    def handoff():
        try:return freeze(api,Ledger(l.path,existing=True),tmp_path/'target.sqlite')
        except api.CustodyDenied:return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(reserve);b=pool.submit(handoff);permit=a.result();frozen=b.result()
    assert (permit is None)!=(frozen is None)
    if frozen is not None:assert_denied(l,p)
    else:budget.settle(l,permit,None)


@pytest.mark.parametrize('system,raw',[
    ('Linux','0123456789abcdef0123456789abcdef\n'),
    ('Darwin','    "IOPlatformUUID" = "12345678-1234-5678-ABCD-1234567890AB"')])
def test_native_identity_only_exposes_domain_separated_hash(api,system,raw):
    result=api._native_identity(system,raw)
    assert len(result)==64 and result==api._native_identity(system,raw)
    assert raw.strip() not in result


@pytest.mark.parametrize('system,raw',[
    ('Linux',''),('Linux','0'*32),('Linux','x'*32),('Linux','a'*33),
    ('Darwin','"IOPlatformUUID" = "00000000-0000-0000-0000-000000000000"'),
    ('Darwin','"IOPlatformUUID" = "broken"'),
    ('Darwin','"IOPlatformUUID" = "12345678-1234-5678-abcd-1234567890ab"\n'*2),
    ('Windows','0123456789abcdef0123456789abcdef'),('Linux',None)])
def test_invalid_native_identity_has_no_fallback(api,system,raw):
    with pytest.raises(api.CustodyDenied):api._native_identity(system,raw)


def test_broken_parent_chain_never_grants_active_authority(api,ready,tmp_path):
    l,p=ready;freeze(api,l,tmp_path/'target.sqlite')
    with l.transaction() as db:
        last=json.loads(db.execute("select payload from events where kind='state-custody' order by id desc limit 1").fetchone()[0])
    l.append_event('state-custody',dict(last,phase='active',parent_sha256='0'*64))
    assert_denied(l,p)


@pytest.mark.parametrize('authorization',[None,'','   ',True,'x'*257])
def test_operator_authorization_reference_required(api,ready,tmp_path,authorization):
    l,p=ready;before=snapshot(l)
    with pytest.raises(api.CustodyDenied):api.freeze(l,transfer_id='transfer-001',destination=destination(tmp_path/'target.sqlite'),authorization_reference=authorization)
    assert snapshot(l)==before


def cli(path,*args):
    import subprocess,sys
    return subprocess.run([sys.executable,'-m','ops.pi.state_custody','--ledger',str(path),*args],capture_output=True,text=True,timeout=15)


def test_cli_status_and_freeze_are_durable_without_model_effects(ready,tmp_path):
    l,p=ready;before=budget.totals(l,'local-trial-1')
    result=cli(l.path,'status');assert result.returncode==0,result.stderr
    first=json.loads(result.stdout);assert first['phase']=='legacy' and len(first['current_binding']['host_sha256'])==64
    target=tmp_path/'target.sqlite';dest=dict(first['current_binding'],ledger_path=str(target.resolve()))
    result=cli(l.path,'freeze','--transfer-id','cli-001','--destination',json.dumps(dest),'--authorization-reference','human:go-live')
    assert result.returncode==0,result.stderr
    frozen=json.loads(result.stdout);assert frozen['phase']=='frozen';assert_denied(l,p)
    copy=clone(l,target)
    result=cli(copy.path,'activate','--transfer-id','cli-001','--snapshot-sha256',frozen['snapshot_sha256'],'--authorization-reference','operator:handoff')
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['phase']=='active' and budget.totals(copy,'local-trial-1')==before
    again=cli(copy.path,'status');assert again.returncode==0 and json.loads(again.stdout)['phase']=='active'


@pytest.mark.parametrize('args',[
    ('freeze','--transfer-id','bad'),
    ('freeze','--transfer-id','bad','--destination','{','--authorization-reference','human'),
    ('activate','--transfer-id','missing','--snapshot-sha256','0'*64,'--authorization-reference','human')])
def test_cli_failure_is_nonzero_and_does_not_mutate(ready,args):
    l,p=ready;before=snapshot(l);result=cli(l.path,*args)
    assert result.returncode!=0 and not result.stdout.strip()
    assert 'Traceback' not in result.stderr and snapshot(l)==before


def historical_activation(api,l,frozen):
    with l.transaction() as db:
        latest=json.loads(db.execute("select payload from events where kind='state-custody' order by id desc limit 1").fetchone()[0])
    return dict(latest,phase='active',parent_sha256=api._hash(latest),input_snapshot_sha256=frozen['snapshot_sha256'])


def test_correct_parent_with_wrong_historical_input_digest_cannot_authorize(api,ready,tmp_path):
    l,p=ready;target=tmp_path/'target.sqlite';frozen=freeze(api,l,target);copy=clone(l,target)
    value=historical_activation(api,copy,frozen);value['input_snapshot_sha256']='0'*64
    copy.append_event('state-custody',value)
    assert_denied(Ledger(copy.path,existing=True),p)


@pytest.mark.parametrize('duplicate',['phase','nested_binding'])
def test_duplicate_historical_json_keys_never_grant_authority(api,ready,tmp_path,duplicate):
    l,p=ready;target=tmp_path/'target.sqlite';frozen=freeze(api,l,target);copy=clone(l,target)
    value=historical_activation(api,copy,frozen);raw=json.dumps(value)
    if duplicate=='phase':raw=raw.replace('"phase": "active"','"phase": "frozen", "phase": "active"')
    else:raw=raw.replace('"host_sha256": "'+'a'*64+'"','"host_sha256": "'+'b'*64+'", "host_sha256": "'+'a'*64+'"')
    with copy.transaction() as db:db.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',('state-custody',raw))
    assert_denied(Ledger(copy.path,existing=True),p)


def test_new_metadata_cannot_refresh_away_frozen_operations_snapshot(api,ready,tmp_path):
    l,p=ready;target=tmp_path/'target.sqlite';freeze(api,l,target);copy=clone(l,target)
    copy.intent('new-diagnostic','diagnostic',dict(observed=True))
    refreshed=api.status(copy);before=snapshot(copy)
    with pytest.raises(api.CustodyDenied,match='snapshot'):activate(api,copy,refreshed)
    assert snapshot(copy)==before
