"""Fee-only host authorization against real temporary SQLite, never a provider."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json

import pytest

from ops.pi import budget, plans, prompts, schedule, trial_runtime
from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger, OperationConflict, _json
from ops.pi.policy import load_policy
from ops.pi.tests.test_budget import policy, ledger, request
from ops.pi.tests.test_budget_amendment import amend, snapshot
from ops.pi.tests.test_plans import candidate, baseline
from ops.pi.tests.test_schedule import now, receipt


def fee_policy(policy):
    return replace(policy, schema_version=2, max_attempts=None, budget_microyuan=20000000)


def upgrade(ledger, **changes):
    api = getattr(budget, 'amend_local_trial_budget_v2', None)
    assert callable(api), 'trusted fee-only v2 API missing'
    args = dict(operation_id='fee-only-001', expected_original_microyuan=10000000,
        expected_effective_microyuan=20000000, expected_effective_max_attempts=100,
        budget_microyuan=20000000, max_attempts=None, phase_allocations=None,
        authorization_reference='human-message:fee-only20-no-attempt-cap', approved=True)
    args.update(changes)
    return api(ledger, 'local-trial-1', **args)


def seeded(ledger):
    ledger.intent('model-scope:local-trial-1','model-scope',dict(max_attempts=100,budget_microyuan=10000000))
    trial_runtime.ensure_phase_fence(ledger)
    amend(ledger)
    return ledger


def add_attempts(ledger, policy, count):
    for _ in range(count):
        settle = budget.settle
        settle(ledger, budget.reserve(ledger,'local-trial-1',request(),policy), None)


def test_policy_v2_null_is_explicit_and_loadable(tmp_path,policy):
    path=tmp_path/'fee.json'; path.write_text(json.dumps(asdict(fee_policy(policy))))
    loaded=load_policy(path)
    assert loaded.max_attempts is None and loaded.timeout_seconds==120


@pytest.mark.parametrize('changes',[dict(schema_version=1),dict(max_attempts=100),dict(max_attempts=True),
    dict(max_attempts=100.0),dict(budget_microyuan=20000001),dict(server_daily_enabled=True)])
def test_policy_v2_rejects_ambiguous_or_future_scope(tmp_path,policy,changes):
    path=tmp_path/'bad.json'; path.write_text(json.dumps(asdict(fee_policy(policy))|changes))
    with pytest.raises(ValueError): load_policy(path)


def test_null_policy_alone_keeps_original_scope_and_count_limit(ledger,policy):
    p=fee_policy(policy)
    add_attempts(ledger,p,100)
    assert ledger.get('model-scope:local-trial-1')['payload']==dict(max_attempts=100,budget_microyuan=10000000)
    before=snapshot(ledger)
    with pytest.raises(budget.BudgetDenied): budget.reserve(ledger,'local-trial-1',request(),p)
    assert snapshot(ledger)==before


def test_v2_prefix_preserved_one_event_pair_and_replay(ledger,policy):
    seeded(ledger); add_attempts(ledger,policy,3); before=snapshot(ledger)
    first=upgrade(ledger)
    assert first['kind']=='model-budget-amendment-v2' and first['status']=='done'
    assert first['payload']['amendment_version']==2
    assert first['payload']['max_attempts'] is None and first['payload']['phase_allocations'] is None
    after=snapshot(ledger)
    assert all(row in after[0] for row in before[0]) and after[1][:-2]==before[1]
    assert len(after[0])==len(before[0])+1
    assert upgrade(Ledger(ledger.path))==first and snapshot(ledger)==after
    limits=budget.effective_trial_limits(ledger)
    assert limits==dict(max_attempts=None,budget_microyuan=20000000,phase_allocations=None)


def test_real_count_exceeds100_only_after_v2_and_explicit_policy(ledger,policy):
    seeded(ledger); add_attempts(ledger,replace(policy,budget_microyuan=20000000),100)
    with pytest.raises(budget.BudgetDenied): budget.reserve(ledger,'local-trial-1',request(),fee_policy(policy))
    upgrade(ledger)
    with pytest.raises(budget.BudgetDenied): budget.reserve(ledger,'local-trial-1',request(),policy)
    budget.reserve(Ledger(ledger.path),'local-trial-1',request(),fee_policy(policy))
    assert budget.totals(ledger,'local-trial-1')==(101,1010000)


@pytest.mark.parametrize('changes',[dict(approved=False),dict(approved=1),dict(authorization_reference=''),
    dict(authorization_reference='bad\nsource'),dict(expected_effective_max_attempts=True),
    dict(expected_effective_max_attempts=101),dict(budget_microyuan=20000001),
    dict(budget_microyuan=20000000.0),dict(max_attempts=1000000000),dict(phase_allocations={}),
    dict(expected_effective_microyuan=10000000)])
def test_invalid_v2_is_atomic(ledger,changes):
    seeded(ledger); before=snapshot(ledger)
    with pytest.raises((budget.BudgetDenied,OperationConflict,ValueError)): upgrade(ledger,**changes)
    assert snapshot(ledger)==before


@pytest.mark.parametrize('missing',['v1','fence','pending-model','pending-admission'])
def test_v2_requires_old_authority_and_settled_transport(ledger,policy,missing):
    if missing=='v1':
        ledger.intent('model-scope:local-trial-1','model-scope',dict(max_attempts=100,budget_microyuan=10000000))
        trial_runtime.ensure_phase_fence(ledger)
    elif missing=='fence':
        ledger.intent('model-scope:local-trial-1','model-scope',dict(max_attempts=100,budget_microyuan=10000000)); amend(ledger)
    else:
        seeded(ledger)
        if missing=='pending-model': budget.reserve(ledger,'local-trial-1',request(),policy)
        else: ledger.intent('pending-phase','phase-admission',dict(attempt_id='not-sent',category='develop'))
    before=snapshot(ledger)
    with pytest.raises(budget.BudgetDenied): upgrade(ledger)
    assert snapshot(ledger)==before


def test_duplicate_or_conflicting_v2_denied_without_mutation(ledger):
    seeded(ledger); upgrade(ledger); before=snapshot(ledger)
    for changes in [dict(operation_id='second'),dict(authorization_reference='different-human-message')]:
        with pytest.raises(OperationConflict): upgrade(ledger,**changes)
        assert snapshot(ledger)==before


def test_forged_v2_without_audit_pair_cannot_remove_limits(ledger,policy,tmp_path):
    seeded(ledger); valid=upgrade(ledger)
    other=Ledger(tmp_path/'forged.sqlite'); seeded(other)
    with other.transaction() as db:
        db.execute("INSERT INTO operations VALUES (?,'model-budget-amendment-v2',?,'done',?,1)",
            (valid['operation_id'],_json(valid['payload']),_json(valid['evidence'])))
    before=snapshot(other)
    with pytest.raises(budget.BudgetDenied): budget.reserve(other,'local-trial-1',request(),fee_policy(policy))
    assert snapshot(other)==before


def test_phase_quota_removed_without_rewriting_old_fence(ledger,policy):
    seeded(ledger); original=ledger.get(trial_runtime.FENCE_ID); sent=[]
    send=trial_runtime.phase_transport(ledger,'develop',lambda *_:sent.append(True) or 'response')
    p=replace(policy,budget_microyuan=20000000)
    for _ in range(45):
        permit=budget.reserve(ledger,'local-trial-1',request(),p); send(request(),1); budget.settle(ledger,permit,None)
    permit=budget.reserve(ledger,'local-trial-1',request(),p)
    with pytest.raises(ValueError): send(request(),1)
    budget.settle(ledger,permit,None)
    denied=ledger.get('phase-admission:'+permit.attempt_id)
    upgrade(ledger)
    # Existing host wrapper must observe the current trusted amendment as well.
    permit=budget.reserve(ledger,'local-trial-1',request(),fee_policy(policy)); send(request(),1)
    assert len(sent)==46 and ledger.get(trial_runtime.FENCE_ID)==original
    assert ledger.get(denied['operation_id'])==denied
    with pytest.raises(ValueError): send(request(),1)


def test_fee_only_concurrent_unknown_reserves_keep20_cap(ledger,policy):
    seeded(ledger); upgrade(ledger)
    p=replace(fee_policy(policy),input_token_bound=1000000)
    def attempt(_):
        try: return budget.reserve(ledger,'local-trial-1',request(),p)
        except budget.BudgetDenied: return None
    with ThreadPoolExecutor(max_workers=6) as pool: permits=list(pool.map(attempt,range(12)))
    permits=[v for v in permits if v]
    for permit in permits: budget.settle(ledger,permit,None)
    assert len(permits)==9 and budget.totals(ledger,'local-trial-1')==(9,18072000)
    before=snapshot(ledger)
    for permit in permits: budget.settle(ledger,permit,dict(input_tokens=0,output_tokens=0,cache_read_input_tokens=0,cache_creation_input_tokens=0))
    assert snapshot(ledger)==before


def test_plan_prompt_and_schedule_accept_null_but_stay_bounded(ledger,policy):
    p=fee_policy(policy); plan=candidate(call_estimate=16)
    assert plans.validate_plan(plan,baseline(),p).status=='done'
    for value in [-1,True,1.5,float('inf')]:
        assert plans.validate_plan(candidate(call_estimate=value),baseline(),p).status=='blocked'
    text=prompts.build_phase_prompt('develop',{},dict(max_attempts=None,budget_microyuan=20000000,deadline='fixed'))
    data=json.loads(text.split('CONTROLLED_DATA\n',1)[1]); assert data['limits']['max_attempts'] is None
    assert data['permissions']['tools']==list(trial_runtime.PHASE_TOOLS['develop'])
    seeded(ledger); add_attempts(ledger,policy,100); receipt(ledger,'2026-10-11','pre_backup')
    assert schedule.next_action(ledger,now(),{},p)['kind']=='report'
    upgrade(ledger)
    assert schedule.next_action(ledger,now(),{},p)['kind']=='analyze'
    assert schedule.next_action(ledger,now('05:30'),{},p)['kind']=='close'
