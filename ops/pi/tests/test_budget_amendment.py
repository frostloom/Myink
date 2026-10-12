"""Trusted host amendments retain the real SQLite cumulative trial history."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json

import pytest

from ops.pi import budget
from ops.pi.budget import BudgetDenied, reserve, settle, totals
from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger, OperationConflict
from ops.pi.policy import load_policy
from ops.pi.tests.test_budget import ledger, policy, request


AUTHORIZATION = 'human-message:c19-local-trial-cumulative-20-cny'


def amend(ledger, **changes):
    host_api = getattr(budget, 'amend_local_trial_budget', None)
    assert callable(host_api), 'trusted host append-only amendment API is missing'
    args = dict(operation_id='c19-budget-amendment-001',
                expected_original_microyuan=10000000, expected_effective_microyuan=10000000,
                budget_microyuan=20000000, authorization_reference=AUTHORIZATION, approved=True)
    scope_id = changes.pop('scope_id', 'local-trial-1')
    args.update(changes)
    return host_api(ledger, scope_id, **args)


def snapshot(ledger):
    with ledger.transaction() as connection:
        return ([tuple(r) for r in connection.execute('SELECT * FROM operations ORDER BY operation_id')],
                [tuple(r) for r in connection.execute('SELECT * FROM events ORDER BY id')])


@pytest.fixture
def historical(ledger, policy):
    # Four literal unknown reserves:4*2012352=8049408. Two known23172 charges.
    unknown_policy = replace(policy, input_token_bound=1000000, max_tokens=1544)
    unknown_request = request() | dict(max_tokens=1544)
    for _ in range(4):
        settle(ledger, reserve(ledger, 'local-trial-1', unknown_request, unknown_policy), None)
    known_policy = replace(policy, input_token_bound=2000, max_tokens=3000)
    for _ in range(2):
        permit = reserve(ledger, 'local-trial-1', request() | dict(max_tokens=3000), known_policy)
        settle(ledger, permit, dict(input_tokens=1002, output_tokens=2646,
                                   cache_read_input_tokens=0, cache_creation_input_tokens=0))
    assert totals(ledger, 'local-trial-1') == (6, 8095752)
    return ledger


def next_policy(policy, **changes):
    return replace(policy, input_token_bound=1000000, max_tokens=2048,
                   budget_microyuan=20000000, **changes)


def next_request():
    return request() | dict(max_tokens=2048)


def test_policy_twenty_is_loadable_but_above_twenty_is_rejected(tmp_path, policy):
    data = asdict(policy)
    data['budget_microyuan'] = 20000000
    path = tmp_path / 'twenty.json'
    path.write_text(json.dumps(data))
    assert load_policy(path).budget_microyuan == 20000000
    data['budget_microyuan'] = 20000001
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_policy(path)


@pytest.mark.parametrize('value', [True, 20000000.0, 0, -1])
def test_policy_budget_types_remain_strict(tmp_path, policy, value):
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps(asdict(policy) | dict(budget_microyuan=value)))
    with pytest.raises(ValueError):
        load_policy(path)


def test_policy_twenty_alone_cannot_bypass_historical_ten(historical, policy):
    before = snapshot(historical)
    with pytest.raises(BudgetDenied):
        reserve(historical, 'local-trial-1', next_request(), next_policy(policy))
    assert snapshot(historical) == before
    assert totals(historical, 'local-trial-1') == (6, 8095752)


def test_fresh_scope_policy_twenty_still_persists_original_ten(ledger, policy):
    reserve(ledger, 'local-trial-1', request(), replace(policy, budget_microyuan=20000000))
    assert ledger.get('model-scope:local-trial-1')['payload'] == dict(max_attempts=100, budget_microyuan=10000000)


def test_host_amendment_retains_history_scope_and_unknown_receipts_on_reopen(historical, policy, monkeypatch):
    before = snapshot(historical)
    record = amend(historical)
    assert record['kind'] == 'model-budget-amendment' and record['status'] == 'done'
    assert record['payload']['authorization_reference'] == AUTHORIZATION
    assert totals(historical, 'local-trial-1') == (6, 8095752)
    reopened = Ledger(historical.path)
    monkeypatch.setattr(budget.time, 'time', lambda: 86400 * 30000)
    permit = reserve(reopened, 'local-trial-1', next_request(), next_policy(policy))
    assert permit.reserved_microyuan == 2016384
    assert totals(reopened, 'local-trial-1') == (7, 10112136)
    after = snapshot(reopened)
    assert all(row in after[0] for row in before[0])
    assert after[1][:len(before[1])] == before[1]
    unknowns = [r for r in after[0] if r[3] == 'uncertain']
    assert len(unknowns) == 4
    for row in unknowns:
        settle(reopened, budget.BudgetPermit(row[0], 'local-trial-1', 2012352,
                                            json.loads(row[2])['deadline']),
               dict(input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0))
    assert totals(reopened, 'local-trial-1') == (7, 10112136)
    assert snapshot(reopened) == after


def test_exact_amendment_replay_is_idempotent_even_after_reservation(historical, policy):
    first = amend(historical)
    reserve(historical, 'local-trial-1', next_request(), next_policy(policy))
    before = snapshot(historical)
    assert amend(Ledger(historical.path)) == first
    assert snapshot(historical) == before


@pytest.mark.parametrize('changes', [
    dict(approved=False), dict(approved=None), dict(approved=1), dict(approved='true'),
    dict(authorization_reference=''), dict(authorization_reference='   '), dict(authorization_reference=None),
    dict(authorization_reference=True), dict(authorization_reference='x\nforged'),
    dict(operation_id=''), dict(operation_id=None), dict(operation_id=True),
    dict(expected_original_microyuan=True), dict(expected_original_microyuan=10000000.0),
    dict(expected_original_microyuan=9000000), dict(expected_effective_microyuan=True),
    dict(expected_effective_microyuan=10000000.0), dict(expected_effective_microyuan=20000000),
    dict(budget_microyuan=True), dict(budget_microyuan=20000000.0), dict(budget_microyuan=9999999),
    dict(budget_microyuan=15000000), dict(budget_microyuan=20000001),
    dict(scope_id='local-trial-2'), dict(scope_id='server-daily:2026-10-12'), dict(scope_id=True),
])
def test_invalid_amendment_is_denied_without_partial_mutation(historical, changes):
    before = snapshot(historical)
    with pytest.raises((BudgetDenied, OperationConflict, ValueError)):
        amend(historical, **changes)
    assert snapshot(historical) == before


def test_unknown_scope_cannot_be_created_by_amendment(ledger):
    before = snapshot(ledger)
    with pytest.raises(BudgetDenied):
        amend(ledger)
    assert snapshot(ledger) == before


def test_missing_approval_does_not_authorize_amendment(historical):
    host_api = getattr(budget, 'amend_local_trial_budget', None)
    assert callable(host_api), 'trusted host append-only amendment API is missing'
    before = snapshot(historical)
    with pytest.raises((TypeError, BudgetDenied)):
        host_api(historical, 'local-trial-1', operation_id='missing-approval',
                 expected_original_microyuan=10000000, expected_effective_microyuan=10000000,
                 budget_microyuan=20000000, authorization_reference=AUTHORIZATION)
    assert snapshot(historical) == before


@pytest.mark.parametrize('changes', [dict(authorization_reference='different-human-message'),
                                     dict(operation_id='c19-budget-amendment-002')])
def test_conflicting_replay_or_second_operation_cannot_amend(historical, changes):
    amend(historical)
    before = snapshot(historical)
    with pytest.raises(OperationConflict):
        amend(historical, **changes)
    assert snapshot(historical) == before


def test_operation_identity_collision_is_atomic(historical):
    historical.intent('c19-budget-amendment-001', 'other-operation', dict(other=True))
    before = snapshot(historical)
    with pytest.raises(OperationConflict):
        amend(historical)
    assert snapshot(historical) == before


@pytest.mark.parametrize('mutation', ['pending', 'false-approval', 'wrong-cap', 'missing-source', 'wrong-scope', 'wrong-evidence', 'extra-field', 'no-events'])
def test_invalid_persisted_amendment_fails_closed(historical, policy, mutation):
    record = amend(historical)
    source = Ledger(historical.path.parent / (mutation + '.sqlite'))
    # Simulate an untrusted approval in a distinct real ledger without altering any immutable original.
    scope = historical.get('model-scope:local-trial-1')
    source.intent('model-scope:local-trial-1', 'model-scope', scope['payload'])
    payload = dict(record['payload'])
    evidence = dict(record['evidence'])
    if mutation == 'false-approval':
        payload['approved'] = False
    elif mutation == 'wrong-cap':
        payload['budget_microyuan'] = 20000001
    elif mutation == 'missing-source':
        payload['authorization_reference'] = ''
    elif mutation == 'wrong-scope':
        payload['scope_id'] = 'server-daily:2026-10-12'
    elif mutation == 'wrong-evidence':
        evidence['approved'] = False
    elif mutation == 'extra-field':
        payload['max_attempts'] = 101
    if mutation == 'no-events':
        with source.transaction() as connection:
            connection.execute("INSERT INTO operations VALUES (?,'model-budget-amendment',?,'done',?,1)",
                               (record['operation_id'], json.dumps(payload), json.dumps(evidence)))
    else:
        source.intent(record['operation_id'], 'model-budget-amendment', payload)
        if mutation != 'pending':
            source.finish(Receipt(record['operation_id'], 'done', evidence))
    before = snapshot(source)
    with pytest.raises((BudgetDenied, OperationConflict)):
        reserve(source, 'local-trial-1', request(), replace(policy, budget_microyuan=20000000))
    assert snapshot(source) == before
    with pytest.raises((BudgetDenied, OperationConflict)):
        amend(source)
    assert snapshot(source) == before


def test_concurrent_amendment_identity_writes_once(historical):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: amend(historical), range(6)))
    assert all(r == results[0] for r in results)
    after = snapshot(historical)
    assert len([r for r in after[0] if r[1] == 'model-budget-amendment']) == 1
    events = [json.loads(r[2]) for r in after[1]]
    assert len([e for e in events if e.get('operation_id') == 'c19-budget-amendment-001']) == 2


def test_reservation_race_after_amendment_never_exceeds_twenty(historical, policy):
    amend(historical)
    def attempt(_):
        try:
            return reserve(historical, 'local-trial-1', next_request(), next_policy(policy))
        except BudgetDenied:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        permits = list(pool.map(attempt, range(12)))
    assert sum(p is not None for p in permits) == 5
    assert totals(historical, 'local-trial-1') == (11, 18177672)


def test_exact_twenty_ceiling_has_no_extra_reservation(ledger, policy):
    ledger.intent('model-scope:local-trial-1', 'model-scope', dict(max_attempts=100, budget_microyuan=10000000))
    amend(ledger)
    expensive = replace(policy, budget_microyuan=20000000, input_token_bound=1000000,
                        prices=dict(input='20', output='0', cache_read='0', cache_write=None))
    reserve(ledger, 'local-trial-1', request(), expensive)
    with pytest.raises(BudgetDenied):
        reserve(ledger, 'local-trial-1', request(), expensive)
    assert totals(ledger, 'local-trial-1') == (1, 20000000)


def test_amendment_never_raises_one_hundred_attempt_limit(ledger, policy):
    reserve(ledger, 'local-trial-1', request(), policy)
    amend(ledger)
    twenty = replace(policy, budget_microyuan=20000000, max_attempts=200)
    for _ in range(99):
        reserve(ledger, 'local-trial-1', request(), twenty)
    before = snapshot(ledger)
    with pytest.raises(BudgetDenied):
        reserve(ledger, 'local-trial-1', request(), twenty)
    assert totals(ledger, 'local-trial-1') == (100, 1000000)
    assert snapshot(ledger) == before


def test_amendment_retains_original_lower_attempt_ceiling(ledger, policy):
    reserve(ledger, 'local-trial-1', request(), replace(policy, max_attempts=1))
    original = ledger.get('model-scope:local-trial-1')
    amend(ledger)
    with pytest.raises(BudgetDenied):
        reserve(ledger, 'local-trial-1', request(), replace(policy, budget_microyuan=20000000))
    assert ledger.get('model-scope:local-trial-1') == original


def test_lower_policy_and_future_server_flag_do_not_bypass_limits(historical, policy):
    amend(historical)
    expensive = replace(policy, input_token_bound=1000000, max_tokens=2048)
    with pytest.raises(BudgetDenied):
        reserve(historical, 'local-trial-1', next_request(), expensive)
    before = snapshot(historical)
    with pytest.raises(BudgetDenied):
        reserve(historical, 'server-daily:2026-10-12', next_request(), next_policy(policy, server_daily_enabled=True))
    assert snapshot(historical) == before


def test_original_scope_below_ten_cannot_be_upgraded(ledger, policy):
    reserve(ledger, 'local-trial-1', request(), replace(policy, budget_microyuan=9000000))
    before = snapshot(ledger)
    with pytest.raises(BudgetDenied):
        amend(ledger)
    assert snapshot(ledger) == before

