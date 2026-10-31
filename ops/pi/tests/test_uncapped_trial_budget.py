"""Explicit human no-fee-cap authority; synthetic ledger/transport only."""
from dataclasses import asdict, replace
import json
import time

import pytest

from ops.pi import budget
from ops.pi.analysis_execution import _hash
from ops.pi.analysis_budget import AnalysisBudgetSlot, _scope_identity
from ops.pi.analysis_run import AnalysisRun
from ops.pi.analysis_preflight import audit
from ops.pi.ledger import LedgerBlocked, OperationConflict
from ops.pi.policy import load_policy
from ops.pi.tests.test_budget import ledger, policy, request
from ops.pi.tests.test_budget_amendment import snapshot
from ops.pi.tests.test_fee_only_budget import seeded, upgrade, fee_policy
from ops.pi.tests.test_analysis_execution import prepared
from ops.pi.tests.test_analysis_run import BINDING
from ops.pi.tests.test_analysis_launcher import setup
from ops.pi.tests.test_analysis_trial_lifecycle import config_v2
from ops.pi.tests.test_analysis_full_trial import install
from ops.pi import analysis_launcher


def uncapped(policy):
    return replace(fee_policy(policy), schema_version=3, budget_microyuan=None)


def approve(ledger, **changes):
    fn = getattr(budget, 'amend_local_trial_budget_v3', None)
    assert callable(fn), 'explicit no-fee-cap approval API missing'
    args = dict(operation_id='uncapped-approval', authorization_reference='human:next-step-no-fee-cap', approved=True)
    return fn(ledger, 'local-trial-1', **(args | changes))


def test_new_policy_requires_explicit_null(tmp_path, policy):
    p=tmp_path/'policy.json';p.write_text(json.dumps(asdict(uncapped(policy))))
    assert load_policy(p).budget_microyuan is None
    for changes in [dict(schema_version=2),dict(budget_microyuan=0),dict(budget_microyuan=20000000),dict(max_attempts=100),dict(server_daily_enabled=True)]:
        p.write_text(json.dumps(asdict(uncapped(policy))|changes))
        with pytest.raises(ValueError):load_policy(p)


def test_approval_preserves_history_replays_and_does_not_release_unknown(ledger, policy):
    seeded(ledger);upgrade(ledger)
    budget.settle(ledger,budget.reserve(ledger,'local-trial-1',request(),fee_policy(policy)),None)
    before=snapshot(ledger);cost=budget.totals(ledger,'local-trial-1')
    row=approve(ledger);after=snapshot(ledger)
    assert row['kind']=='model-budget-amendment-v3' and row['status']=='done'
    assert all(r in after[0] for r in before[0]) and after[1][:-2]==before[1]
    assert approve(ledger)==row and snapshot(ledger)==after
    assert budget.totals(ledger,'local-trial-1')==cost
    assert budget.effective_trial_limits(ledger)==dict(max_attempts=None,budget_microyuan=None,phase_allocations=None)
    with pytest.raises(OperationConflict):approve(ledger,operation_id='second-approval')


def test_policy_alone_does_not_remove_twenty_yuan_scope(ledger, policy):
    seeded(ledger);upgrade(ledger)
    p=replace(uncapped(policy),input_token_bound=1000000,prices=dict(input='20',output='0',cache_read='20',cache_write='20'))
    budget.settle(ledger,budget.reserve(ledger,'local-trial-1',request(),p),None)
    with pytest.raises(budget.BudgetDenied):budget.reserve(ledger,'local-trial-1',request(),p)
    approve(ledger)
    assert budget.reserve(ledger,'local-trial-1',request(),p).reserved_microyuan==20000000


@pytest.mark.parametrize('seed', [False, True])
def test_requires_fee_only_history(ledger,seed):
    if seed:seeded(ledger)
    before=snapshot(ledger)
    with pytest.raises(budget.BudgetDenied):approve(ledger)
    assert snapshot(ledger)==before


@pytest.mark.parametrize('changes',[dict(approved=False),dict(approved=1),dict(authorization_reference=''),dict(authorization_reference='bad\nref')])
def test_invalid_authority_cannot_write(ledger,changes):
    seeded(ledger);upgrade(ledger);before=snapshot(ledger)
    with pytest.raises((budget.BudgetDenied,ValueError)):approve(ledger,**changes)
    assert snapshot(ledger)==before


def test_pending_transport_blocks_approval(ledger,policy):
    seeded(ledger);upgrade(ledger)
    budget.reserve(ledger,'local-trial-1',request(),fee_policy(policy));before=snapshot(ledger)
    with pytest.raises(budget.BudgetDenied):approve(ledger)
    assert snapshot(ledger)==before


def test_uncapped_run_keeps_binding_identity_and_no_retry(tmp_path,ledger,policy):
    seeded(ledger);upgrade(ledger);approve(ledger)
    slots,*_=prepared(tmp_path);run=AnalysisRun.create(ledger,'uncapped-run',slots,**BINDING);p=replace(uncapped(policy),max_tokens=2048)
    deadline=time.time()+60;run.bind_budget(p,cap_microyuan=None,deadline=deadline)
    run.guard(0)(slots[0]['request'])
    permit=budget.reserve(ledger,'local-trial-1',slots[0]['request'],p,analysis_slot=AnalysisBudgetSlot(run,0))
    budget.settle(ledger,permit,None)
    with pytest.raises(budget.BudgetDenied):budget.reserve(ledger,'local-trial-1',slots[0]['request'],p,analysis_slot=AnalysisBudgetSlot(run,0))
    with pytest.raises(OperationConflict):run.bind_budget(p,cap_microyuan=None,deadline=deadline+1)


def test_full_thirty_without_fee_cap_still_checks_all_contracts(setup,monkeypatch):
    c,ledger,p,*_=setup;approve(ledger);p=uncapped(p)
    from pathlib import Path
    Path(c['policy_path']).write_text(json.dumps(asdict(p)));c['expected_policy_sha256']=_hash(asdict(p))
    e=json.loads(Path(c['evidence_path']).read_text());e['policy_sha256']=c['expected_policy_sha256']
    Path(c['evidence_path']).write_text(json.dumps(e));c['expected_evidence_sha256']=_hash(e)
    with ledger.transaction() as db:c['expected_scope_sha256']=_scope_identity(db)
    c=config_v2(c)|dict(cap_microyuan=None)
    processes,calls,daemon=install(monkeypatch,{'0':'json'})
    result=analysis_launcher.launch(c,execute=True)
    assert result['status']=='completed' and result['summary']['done']==29 and result['summary']['failed']==1
    assert len(calls)==30 and not daemon.objects and result['cleanup_complete']
    d=audit(Path(c['ledger_path']),Path(c['policy_path']),expected_scope_sha256=c['expected_scope_sha256'],expected_policy_sha256=c['expected_policy_sha256'])
    assert d['accounting']['budget_microyuan'] is None and d['accounting']['conservative_remaining_microyuan'] is None


def test_concurrent_approval_is_one_pair(ledger):
    from concurrent.futures import ThreadPoolExecutor
    seeded(ledger);upgrade(ledger);before=snapshot(ledger)
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(lambda _:approve(ledger),range(8)))
    assert all(row==rows[0] for row in rows)
    after=snapshot(ledger)
    assert len(after[0])==len(before[0])+1 and len(after[1])==len(before[1])+2


@pytest.mark.parametrize('tamper',['missing-intent','duplicate-receipt','receipt','pending','payload'])
def test_approval_tampering_denies_without_reserving(tmp_path,ledger,policy,tamper):
    from ops.pi.ledger import Ledger, _json
    from ops.pi.contracts import Receipt
    seeded(ledger);upgrade(ledger);row=approve(ledger)
    other=Ledger(tmp_path/'forged.sqlite');seeded(other);upgrade(other)
    payload=dict(row['payload']);evidence=dict(row['evidence'])
    if tamper=='payload':payload['expected_effective_microyuan']=True
    if tamper=='receipt':evidence['approved']=False
    if tamper=='missing-intent':
        with other.transaction() as db:
            db.execute("INSERT INTO operations VALUES (?,'model-budget-amendment-v3',?,'done',?,1)",
                (row['operation_id'],_json(payload),_json(evidence)))
    else:
        other.intent(row['operation_id'],'model-budget-amendment-v3',payload)
        if tamper!='pending':other.finish(Receipt(row['operation_id'],'done',evidence))
        if tamper=='duplicate-receipt':
            with other.transaction() as db:
                db.execute("INSERT INTO events(kind,payload,schema_version) SELECT kind,payload,schema_version FROM events WHERE kind='receipt' AND json_extract(payload,'$.operation_id')=?",(row['operation_id'],))
    before=snapshot(other)
    with pytest.raises(budget.BudgetDenied):budget.reserve(other,'local-trial-1',request(),uncapped(policy))
    assert snapshot(other)==before


def test_legacy_policy_keeps_fee_cap_after_approval(ledger,policy):
    seeded(ledger);upgrade(ledger);approve(ledger)
    p=replace(fee_policy(policy),input_token_bound=1000000,prices=dict(input='20',output='0',cache_read='20',cache_write='20'))
    budget.settle(ledger,budget.reserve(ledger,'local-trial-1',request(),p),None)
    with pytest.raises(budget.BudgetDenied):budget.reserve(ledger,'local-trial-1',request(),p)


def test_null_run_needs_both_policy_and_approval(tmp_path,ledger,policy):
    seeded(ledger);upgrade(ledger)
    slots,*_=prepared(tmp_path);run=AnalysisRun.create(ledger,'unapproved-run',slots,**BINDING)
    before=snapshot(ledger)
    for p in [fee_policy(policy),uncapped(policy)]:
        with pytest.raises(budget.BudgetDenied):run.bind_budget(p,cap_microyuan=None,deadline=time.time()+60)
    assert snapshot(ledger)==before


def uncapped_config(setup):
    from pathlib import Path
    c,ledger,p,*_=setup;approve(ledger);p=uncapped(p)
    Path(c['policy_path']).write_text(json.dumps(asdict(p)));c['expected_policy_sha256']=_hash(asdict(p))
    e=json.loads(Path(c['evidence_path']).read_text());e['policy_sha256']=c['expected_policy_sha256']
    Path(c['evidence_path']).write_text(json.dumps(e));c['expected_evidence_sha256']=_hash(e)
    with ledger.transaction() as db:c['expected_scope_sha256']=_scope_identity(db)
    return config_v2(c)|dict(cap_microyuan=None)


@pytest.mark.parametrize('mode',['unknown','cleanup-failure','duplicate-session'])
def test_uncapped_trial_stops_on_billing_cleanup_and_identity(setup,monkeypatch,mode):
    c=uncapped_config(setup);processes,calls,daemon=install(monkeypatch,mode=mode)
    r=analysis_launcher.launch(c,execute=True)
    assert r['status']=='blocked' and len(calls)==(2 if mode=='duplicate-session' else 1)
    assert r['summary']['uncertain']==1
    assert all(p.poll() is not None for p in processes)
    if mode!='cleanup-failure':assert not daemon.objects


def test_null_cap_does_not_enable_legacy_launcher(setup):
    c=uncapped_config(setup);c['schema']='pi-analysis-launch-v1';del c['time_policy'];del c['failure_policy']
    with pytest.raises(LedgerBlocked):analysis_launcher.launch(c)


def test_uncapped_trial_keeps_deadline_admission(setup,monkeypatch):
    c=uncapped_config(setup)|dict(deadline=time.time()+119)
    processes,calls,daemon=install(monkeypatch)
    r=analysis_launcher.launch(c,execute=True)
    assert r['stop_reason']=='insufficient_slot_window' and len(calls)==0
    assert r['cleanup_complete'] and not processes and not daemon.objects


@pytest.mark.parametrize('version',[2,3])
def test_schedule_keeps_legacy_limit_and_handles_uncapped_scope(ledger,policy,version):
    from ops.pi import schedule
    from ops.pi.tests.test_schedule import now, receipt
    seeded(ledger);upgrade(ledger);approve(ledger)
    receipt(ledger,'2026-10-11','pre_backup')
    p=fee_policy(policy) if version==2 else uncapped(policy)
    assert schedule.next_action(ledger,now(),{},p)['kind']=='analyze'
    expensive=replace(uncapped(policy),input_token_bound=1000000,prices=dict(input='20',output='0',cache_read='20',cache_write='20'))
    budget.settle(ledger,budget.reserve(ledger,'local-trial-1',request(),expensive),None)
    assert schedule.next_action(ledger,now(),{},p)['kind']==('report' if version==2 else 'analyze')
    assert schedule.next_action(ledger,now('05:30'),{},p)['kind']=='close'
