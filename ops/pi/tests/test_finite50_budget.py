"""Explicit user finite ceiling after unlimited authority; no paid transports."""
from dataclasses import asdict,replace
from concurrent.futures import ThreadPoolExecutor
import json,time
import pytest
from ops.pi import budget
from ops.pi.policy import load_policy
from ops.pi.ledger import Ledger,OperationConflict,_json
from ops.pi.contracts import Receipt
from ops.pi.tests.test_budget import ledger,policy,request
from ops.pi.tests.test_budget_amendment import snapshot
from ops.pi.tests.test_fee_only_budget import seeded,upgrade,fee_policy
from ops.pi.tests.test_uncapped_trial_budget import approve as unlimited,uncapped
from ops.pi.tests.test_analysis_execution import prepared
from ops.pi.tests.test_analysis_run import BINDING


def finite(policy):return replace(uncapped(policy),schema_version=4,budget_microyuan=50000000)


def seed(ledger):seeded(ledger);upgrade(ledger);unlimited(ledger)


def approve(ledger,**changes):
    api=getattr(budget,'amend_local_trial_budget_v4',None)
    assert callable(api),'finite50 approval missing'
    return api(ledger,'local-trial-1',**(dict(operation_id='finite50',authorization_reference='human:2026-10-27-budget50',approved=True)|changes))


def test_load_finite50_policy(tmp_path,policy):
    p=tmp_path/'policy.json';p.write_text(json.dumps(asdict(finite(policy))))
    assert load_policy(p).budget_microyuan==50000000


@pytest.mark.parametrize('change',[dict(budget_microyuan=None),dict(budget_microyuan=True),dict(budget_microyuan=50000001),dict(budget_microyuan=50000000.0),dict(max_attempts=100),dict(server_daily_enabled=True)])
def test_invalid_finite50_policy_rejected(tmp_path,policy,change):
    p=tmp_path/'policy.json';p.write_text(json.dumps(asdict(finite(policy))|change))
    with pytest.raises(ValueError):load_policy(p)


def test_append_and_reopen_preserve_all_history_and_unknown(ledger,policy):
    seed(ledger);budget.settle(ledger,budget.reserve(ledger,'local-trial-1',request(),uncapped(policy)),None)
    before=snapshot(ledger);used=budget.totals(ledger,'local-trial-1');r=approve(ledger);after=snapshot(ledger)
    assert r['kind']=='model-budget-amendment-v4' and r['status']=='done'
    assert all(x in after[0] for x in before[0]) and after[1][:-2]==before[1]
    assert budget.effective_trial_limits(ledger)==dict(max_attempts=None,budget_microyuan=50000000,phase_allocations=None)
    assert budget.totals(ledger,'local-trial-1')==used
    assert approve(Ledger(ledger.path))==r and snapshot(ledger)==after
    with pytest.raises(OperationConflict):approve(ledger,operation_id='another')


@pytest.mark.parametrize('version',[3,4])
def test_atomic_race_holds_unknowns_and_old_policy_cannot_bypass(ledger,policy,version):
    seed(ledger);approve(ledger)
    p=replace(finite(policy) if version==4 else uncapped(policy),input_token_bound=1000000,prices=dict(input='25',output='0',cache_read='25',cache_write='25'))
    def reserve(_):
        try:return budget.reserve(Ledger(ledger.path),'local-trial-1',request(),p)
        except budget.BudgetDenied:return None
    with ThreadPoolExecutor(max_workers=6) as pool:permits=list(pool.map(reserve,range(8)))
    assert sum(x is not None for x in permits)==2
    for permit in permits:
        if permit:budget.settle(ledger,permit,None)
    assert budget.totals(ledger,'local-trial-1')==(2,50000000)
    before=snapshot(ledger)
    with pytest.raises(budget.BudgetDenied):budget.reserve(ledger,'local-trial-1',request(),p)
    assert snapshot(ledger)==before


@pytest.mark.parametrize('bad',['missing_v3','pending','phase_admission','overspent'])
def test_bad_original_state_does_not_write(ledger,policy,bad):
    if bad=='missing_v3':seeded(ledger);upgrade(ledger)
    else:seed(ledger)
    if bad=='phase_admission':ledger.intent('active-phase','phase-admission',{})
    if bad=='pending':budget.reserve(ledger,'local-trial-1',request(),uncapped(policy))
    if bad=='overspent':
        p=replace(uncapped(policy),input_token_bound=1000000,prices=dict(input='51',output='0',cache_read='51',cache_write='51'))
        budget.settle(ledger,budget.reserve(ledger,'local-trial-1',request(),p),None)
    before=snapshot(ledger)
    with pytest.raises(budget.BudgetDenied):approve(ledger)
    assert snapshot(ledger)==before


@pytest.mark.parametrize('change',[dict(approved=False),dict(approved=1),dict(authorization_reference=''),dict(authorization_reference='bad\nref')])
def test_invalid_explicit_authority_is_atomic(ledger,change):
    seed(ledger);before=snapshot(ledger)
    with pytest.raises((ValueError,budget.BudgetDenied)):approve(ledger,**change)
    assert snapshot(ledger)==before


def test_concurrent_same_approval_is_one_pair(ledger):
    seed(ledger);before=snapshot(ledger)
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(lambda _:approve(Ledger(ledger.path)),range(8)))
    assert all(x==rows[0] for x in rows)
    after=snapshot(ledger);assert len(after[0])==len(before[0])+1 and len(after[1])==len(before[1])+2


@pytest.mark.parametrize('tamper',['missing-intent','duplicate-receipt','payload','pending'])
def test_tampered_finite_approval_refuses_new_reservation(tmp_path,ledger,policy,tamper):
    seed(ledger);row=approve(ledger);other=Ledger(tmp_path/'forged.sqlite');seed(other)
    payload=dict(row['payload']);evidence=dict(row['evidence'])
    if tamper=='payload':payload['budget_microyuan']=50000001
    if tamper=='missing-intent':
        with other.transaction() as db:db.execute("INSERT INTO operations VALUES (?,'model-budget-amendment-v4',?,'done',?,1)",(row['operation_id'],_json(payload),_json(evidence)))
    else:
        other.intent(row['operation_id'],'model-budget-amendment-v4',payload)
        if tamper!='pending':other.finish(Receipt(row['operation_id'],'done',evidence))
        if tamper=='duplicate-receipt':
            with other.transaction() as db:db.execute("INSERT INTO events(kind,payload,schema_version) SELECT kind,payload,schema_version FROM events WHERE kind='receipt' AND json_extract(payload,'$.operation_id')=?",(row['operation_id'],))
    before=snapshot(other)
    with pytest.raises(budget.BudgetDenied):budget.reserve(other,'local-trial-1',request(),finite(policy))
    assert snapshot(other)==before


def test_finite_analysis_scope_and_budget_binding(tmp_path,ledger,policy):
    from ops.pi.analysis_run import AnalysisRun
    from ops.pi.analysis_budget import _scope_identity,AnalysisBudgetSlot
    seed(ledger)
    with ledger.transaction() as db:old=_scope_identity(db)
    approve(ledger)
    with ledger.transaction() as db:assert _scope_identity(db)!=old
    slots,*_=prepared(tmp_path);run=AnalysisRun.create(ledger,'finite-run',slots,**BINDING)
    p=replace(finite(policy),max_tokens=2048);run.bind_budget(p,cap_microyuan=1000000,deadline=time.time()+60)
    run.guard(0)(slots[0]['request'])
    permit=budget.reserve(ledger,'local-trial-1',slots[0]['request'],p,analysis_slot=AnalysisBudgetSlot(run,0));assert permit.reserved_microyuan>0


def test_finite_scope_does_not_allow_null_analysis_run_budget(tmp_path,ledger,policy):
    from ops.pi.analysis_run import AnalysisRun
    seed(ledger);approve(ledger);slots,*_=prepared(tmp_path);run=AnalysisRun.create(ledger,'no-null',slots,**BINDING)
    with pytest.raises(budget.BudgetDenied):run.bind_budget(finite(policy),cap_microyuan=None,deadline=time.time()+60)


def test_finite_policy_does_not_elevate_legacy_twenty_yuan_scope(ledger,policy):
    seeded(ledger);upgrade(ledger)
    p=replace(finite(policy),input_token_bound=1000000,prices=dict(input='20',output='0',cache_read='20',cache_write='20'))
    budget.settle(ledger,budget.reserve(ledger,'local-trial-1',request(),p),None)
    with pytest.raises(budget.BudgetDenied):budget.reserve(ledger,'local-trial-1',request(),p)


def test_v4_readonly_accounting_observes_finite_scope(tmp_path,ledger,policy):
    from ops.pi.analysis_budget import _scope_identity
    from ops.pi.analysis_execution import _hash
    from ops.pi.analysis_preflight import audit
    seed(ledger);approve(ledger);p=finite(policy)
    target=tmp_path/'finite-policy.json';target.write_text(json.dumps(asdict(p)))
    with ledger.transaction() as db:scope=_scope_identity(db)
    before=snapshot(ledger)
    result=audit(ledger.path,target,expected_scope_sha256=scope,expected_policy_sha256=_hash(asdict(p)))
    assert result['accounting']['budget_microyuan']==50000000
    assert result['accounting']['conservative_remaining_microyuan']==50000000
    assert snapshot(ledger)==before


def test_old_unlimited_approval_replay_does_not_remove_finite_ceiling(ledger):
    seed(ledger);approve(ledger);before=snapshot(ledger)
    unlimited(ledger)
    assert budget.effective_trial_limits(ledger)['budget_microyuan']==50000000
    assert snapshot(ledger)==before


def test_orphan_finite_approval_is_not_an_initial_scope(tmp_path,ledger,policy):
    seed(ledger);r=approve(ledger);other=Ledger(tmp_path/'orphan.sqlite')
    other.intent(r['operation_id'],r['kind'],r['payload']);other.finish(Receipt(r['operation_id'],'done',r['evidence']))
    before=snapshot(other)
    with pytest.raises(budget.BudgetDenied):budget.effective_trial_limits(other)
    with pytest.raises(budget.BudgetDenied):budget.reserve(other,'local-trial-1',request(),finite(policy))
    assert snapshot(other)==before


def test_old_uncapped_run_binding_is_not_reinterpreted_after_ceiling(tmp_path,ledger,policy):
    from ops.pi.analysis_run import AnalysisRun
    from ops.pi.analysis_budget import AnalysisBudgetSlot
    seed(ledger);slots,*_=prepared(tmp_path);p=replace(uncapped(policy),max_tokens=2048)
    run=AnalysisRun.create(ledger,'old-bound',slots,**BINDING);run.bind_budget(p,cap_microyuan=None,deadline=time.time()+60)
    guard=AnalysisBudgetSlot(run,0);run.guard(0)(slots[0]['request']);approve(ledger);before=snapshot(ledger)
    with pytest.raises(budget.BudgetDenied):budget.reserve(ledger,'local-trial-1',slots[0]['request'],p,analysis_slot=guard)
    assert snapshot(ledger)==before

@pytest.mark.parametrize('events',['intent','receipt','pair','conflicting_identity'])
def test_orphan_finite_events_never_restore_unlimited_or_append_duplicate_authority(tmp_path,ledger,policy,events):
    seed(ledger);row=approve(ledger);other=Ledger(tmp_path/'event-orphan.sqlite');seed(other)
    identity='model-scope:local-trial-1' if events=='conflicting_identity' else row['operation_id']
    if events!='receipt':other.append_event('intent',dict(operation_id=identity,kind=row['kind'],payload=row['payload'],schema_version=1))
    if events!='intent':other.append_event('receipt',dict(operation_id=identity,status='done',evidence=row['evidence'],schema_version=1))
    other=Ledger(other.path,existing=True);before=snapshot(other)
    with pytest.raises(budget.BudgetDenied):budget.effective_trial_limits(other)
    p=replace(uncapped(policy),input_token_bound=1000000,prices=dict(input='51',output='0',cache_read='51',cache_write='51'))
    with pytest.raises(budget.BudgetDenied):budget.reserve(other,'local-trial-1',request(),p)
    with pytest.raises(budget.BudgetDenied):approve(other)
    assert snapshot(other)==before


def test_valid_finite_row_cannot_hide_a_different_orphan_approval_event(ledger,policy):
    seed(ledger);r=approve(ledger)
    ledger.append_event('intent',dict(operation_id='unmatched-v4',kind=r['kind'],payload=r['payload'],schema_version=1))
    before=snapshot(ledger)
    with pytest.raises(budget.BudgetDenied):budget.effective_trial_limits(ledger)
    with pytest.raises(budget.BudgetDenied):budget.reserve(ledger,'local-trial-1',request(),uncapped(policy))
    assert snapshot(ledger)==before
