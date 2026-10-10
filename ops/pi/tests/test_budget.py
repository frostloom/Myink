import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from ops.pi.ledger import Ledger
from ops.pi.policy import load_policy
from ops.pi.budget import BudgetDenied, reserve, settle, totals


@pytest.fixture
def policy(tmp_path):
    data = dict(schema_version=1, live_enabled=False, server_daily_enabled=False,
                model='deepseek-v4.1-flash', protocol='anthropic', base_url='https://provider.example',
                max_attempts=100, budget_microyuan=10000000, timeout_seconds=120,
                max_body_bytes=65536, input_token_bound=1000, input_bound_source='offline fixture',
                input_bound_calibrated=False, max_tokens=1000, price_source='offline fixture',
                prices=dict(input='2', output='8', cache_read='0.2', cache_write=None))
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(data))
    return load_policy(path)


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / 'ledger.sqlite')


def request():
    return dict(model='deepseek-v4.1-flash', max_tokens=1000,
                messages=[dict(role='user', content='hello')])


def test_unknown_usage_retains_reservation(ledger, policy):
    permit = reserve(ledger, 'local-trial-1', request(), policy)
    settle(ledger, permit, None)
    assert totals(ledger, 'local-trial-1') == (1, 10000)


def test_reservation_race_never_exceeds_ten_yuan(ledger, policy):
    expensive = replace(policy, input_token_bound=1000000)
    def attempt(_):
        try:
            return reserve(ledger, 'local-trial-1', request(), expensive)
        except BudgetDenied:
            return None
    with ThreadPoolExecutor(max_workers=12) as pool:
        permits = list(pool.map(attempt, range(20)))
    assert sum(p is not None for p in permits) == 4
    assert totals(ledger, 'local-trial-1') == (4, 8032000)


def test_midnight_does_not_reset_local_trial(ledger, policy):
    permit = reserve(ledger, 'local-trial-1', request(), policy)
    assert permit.scope_id == 'local-trial-1'
    assert totals(Ledger(ledger.path), 'local-trial-1') == (1, 10000)


@pytest.mark.parametrize('price', [True, '-1', 'NaN', 'Infinity', 2])
def test_boolean_negative_nan_price_rejected(tmp_path, policy, price):
    from dataclasses import asdict
    data = asdict(policy)
    data['prices']['input'] = price
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_policy(path)


def test_complete_usage_refunds_only_unused_reservation(ledger, policy):
    permit = reserve(ledger, 'local-trial-1', request(), policy)
    settle(ledger, permit, dict(input_tokens=100, output_tokens=100,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0))
    assert totals(ledger, 'local-trial-1') == (1, 1000)
    settle(ledger, permit, None)
    assert totals(ledger, 'local-trial-1') == (1, 1000)


def test_cache_usage_incomplete_is_unknown(ledger, policy):
    permit = reserve(ledger, 'local-trial-1', request(), policy)
    settle(ledger, permit, dict(input_tokens=1, output_tokens=1))
    assert totals(ledger, 'local-trial-1') == (1, 10000)

@pytest.mark.parametrize('usage', [dict(input_tokens=True, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0),
                                   dict(input_tokens=1001, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0),
                                   dict(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=1),
                                   dict(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0, server_tool_use={'web_search_requests':1})])
def test_unpriced_or_invalid_usage_retains_full_reservation(ledger, policy, usage):
    permit = reserve(ledger, 'local-trial-1', request(), policy)
    settle(ledger, permit, usage)
    assert totals(ledger, 'local-trial-1') == (1, 10000)


def test_reconfiguration_cannot_raise_original_trial_ceiling(ledger, policy):
    p = replace(policy, max_attempts=1)
    reserve(ledger, 'local-trial-1', request(), p)
    with pytest.raises(BudgetDenied):
        reserve(ledger, 'local-trial-1', request(), policy)


def test_future_daily_scope_remains_disabled(ledger, policy):
    with pytest.raises(BudgetDenied):
        reserve(ledger, 'server-daily:2026-10-11', request(), replace(policy, server_daily_enabled=True))
    assert totals(ledger, 'local-trial-1') == (0, 0)


def test_cache_read_uses_confirmed_decimal_rate(ledger, policy):
    permit = reserve(ledger, 'local-trial-1', request(), policy)
    settle(ledger, permit, dict(input_tokens=100, output_tokens=100,
                              cache_read_input_tokens=100, cache_creation_input_tokens=0))
    assert totals(ledger, 'local-trial-1') == (1, 1020)
