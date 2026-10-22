"""Read-only host diagnostics on real SQLite; no credentials or network."""
from dataclasses import asdict, replace
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from ops.pi.analysis_budget import _scope_identity
from ops.pi.budget import reserve, settle
from ops.pi.ledger import Ledger, LedgerBlocked, _json
from ops.pi.tests.test_budget import ledger, policy, request
from ops.pi.tests.test_fee_only_budget import seeded, upgrade, fee_policy


def api():
    return importlib.import_module('ops.pi.analysis_preflight')


@pytest.fixture
def setup(ledger, policy, tmp_path):
    seeded(ledger); upgrade(ledger)
    p = replace(fee_policy(policy), live_enabled=True, input_bound_calibrated=True,
                prices=dict(input='2', output='8', cache_read='0.2', cache_write='2'))
    path = tmp_path / 'trusted-policy.json'
    path.write_text(json.dumps(asdict(p)))
    with ledger.transaction() as db:
        scope = _scope_identity(db)
    pins = dict(expected_scope_sha256=scope,
                expected_policy_sha256=hashlib.sha256(_json(asdict(p)).encode()).hexdigest())
    return ledger, p, path, pins


def audit(setup):
    ledger, _, path, pins = setup
    return api().audit(ledger.path, path, **pins)


def test_known_unknown_and_pending_are_conservative_and_body_free(setup):
    ledger, p, _, _ = setup
    known = reserve(ledger, 'local-trial-1', request(), p)
    settle(ledger, known, dict(input_tokens=10, output_tokens=5,
        cache_read_input_tokens=0, cache_creation_input_tokens=0,
        provider_request_id='PRIVATE-REQUEST-ID'))
    settle(ledger, reserve(ledger, 'local-trial-1', request(), p), None)
    reserve(ledger, 'local-trial-1', request(), p)
    ledger.append_event('private', dict(body='SECRET-BODY'))
    result = audit(setup)
    assert result['audit_valid'] is True and result['paid_admission'] is False
    assert result['accounting'] == dict(attempts=3, known_attempts=1, unknown_attempts=2,
        pending_attempts=1, known_charged_microyuan=60, unknown_reserved_microyuan=20000,
        conservative_used_microyuan=20060, budget_microyuan=20000000,
        conservative_remaining_microyuan=19979940)
    assert result['policy']['declared_live_ready'] is True
    assert result['policy']['max_request_reserved_microyuan'] == 10000
    assert result['required_before_paid']
    encoded = json.dumps(result)
    for private in ('SECRET-BODY', 'PRIVATE-REQUEST-ID', str(ledger.path), 'human-message:', 'provider.example'):
        assert private not in encoded


def test_no_ledger_constructor_or_write_pragmas_and_repeat_is_identical(setup, monkeypatch):
    ledger, _, _, _ = setup
    before = ledger.path.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('Ledger constructor would mutate journal/schema')
    monkeypatch.setattr(Ledger, '__init__', forbidden)
    statements = []
    original = sqlite3.connect
    def connection(*args, **kwargs):
        assert kwargs['uri'] is True and args[0].endswith('?mode=ro')
        db = original(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db
    monkeypatch.setattr(sqlite3, 'connect', connection)
    first = audit(setup)
    assert audit(setup) == first
    assert ledger.path.read_bytes() == before
    assert not any(s.upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'BEGIN IMMEDIATE'))
                   or 'JOURNAL_MODE=' in s.upper() for s in statements)


def test_read_connection_cannot_write(setup, monkeypatch):
    original = api()._scope_identity
    def check(db):
        with pytest.raises(sqlite3.OperationalError):
            db.execute("INSERT INTO events(kind,payload,schema_version) VALUES ('x','{}',1)")
        return original(db)
    monkeypatch.setattr(api(), '_scope_identity', check)
    assert audit(setup)['audit_valid'] is True


def test_wal_visible_and_concurrent_writer_not_mixed_into_snapshot(setup, monkeypatch):
    ledger, p, _, _ = setup
    keeper = sqlite3.connect(ledger.path)
    try:
        keeper.execute('PRAGMA wal_autocheckpoint=0')
        keeper.execute('SELECT count(*) FROM events').fetchone()
        settle(ledger, reserve(ledger, 'local-trial-1', request(), p), None)
        assert Path(str(ledger.path) + '-wal').stat().st_size > 0
        before = audit(setup)
        original = api()._scope_identity
        def concurrent(db):
            identity = original(db)
            ledger.append_event('concurrent', {})
            return identity
        monkeypatch.setattr(api(), '_scope_identity', concurrent)
        during = audit(setup)
        assert during == before
        monkeypatch.setattr(api(), '_scope_identity', original)
        after = audit(setup)
        assert after['ledger']['events'] == before['ledger']['events'] + 1
        assert after['ledger']['sha256'] != before['ledger']['sha256']
        assert during['accounting']['attempts'] == 1
    finally:
        keeper.close()


@pytest.mark.parametrize('which', ['missing', 'empty', 'corrupt', 'no-scope', 'v1-only', 'bad-schema'])
def test_invalid_ledger_is_never_created_or_repaired(setup, tmp_path, which):
    ledger, _, path, pins = setup
    target = tmp_path / 'bad.sqlite'
    if which == 'empty': target.touch()
    elif which == 'corrupt': target.write_bytes(b'not sqlite PRIVATE-ERROR')
    elif which in ('no-scope', 'v1-only', 'bad-schema'):
        other = Ledger(target)
        if which == 'v1-only': seeded(other)
        if which == 'bad-schema':
            with other.transaction() as db: db.execute('DROP TRIGGER events_no_delete')
    before = target.read_bytes() if target.exists() else None
    with pytest.raises(LedgerBlocked, match='analysis preflight blocked'):
        api().audit(target, path, **pins)
    assert (target.read_bytes() if target.exists() else None) == before


@pytest.mark.parametrize('key', ['expected_scope_sha256', 'expected_policy_sha256'])
@pytest.mark.parametrize('value', ['0' * 64, '', True])
def test_identity_pin_required_and_drift_rejected(setup, key, value):
    ledger, _, path, pins = setup
    with pytest.raises(LedgerBlocked, match='analysis preflight blocked'):
        api().audit(ledger.path, path, **(pins | {key:value}))


def test_missing_approval_event_is_rejected(setup):
    ledger, _, _, _ = setup
    with ledger.transaction() as db:
        db.execute('DROP TRIGGER events_no_delete')
        db.execute("DELETE FROM events WHERE id=(SELECT max(id) FROM events)")
        from ops.pi.ledger import _SCHEMA
        db.execute(next(s for s in _SCHEMA if s.startswith('CREATE TRIGGER events_no_delete ')))
    with pytest.raises(LedgerBlocked): audit(setup)


@pytest.mark.parametrize('reserved,evidence,status', [
    (True, None, 'pending'), (-1, None, 'pending'),
    (10, dict(charged_microyuan=-1, usage_known=True), 'done'),
    (10, dict(charged_microyuan=True, usage_known=True), 'done'),
    (10, dict(charged_microyuan=11, usage_known=True), 'done'),
    (10, dict(charged_microyuan=1, usage_known=False), 'uncertain'),
    (10, dict(charged_microyuan=10, usage_known=1), 'done'),
    (10, dict(charged_microyuan=10, usage_known=True), 'uncertain'),
])
def test_ambiguous_or_underreported_money_blocks(setup, reserved, evidence, status):
    ledger, _, _, _ = setup
    ledger.intent('bad-money', 'model-attempt', dict(scope_id='local-trial-1', reserved_microyuan=reserved))
    if evidence is not None:
        from ops.pi.contracts import Receipt
        ledger.finish(Receipt('bad-money', status, evidence))
    with pytest.raises(LedgerBlocked): audit(setup)


def test_disabled_policy_is_diagnostic_only(setup):
    ledger, p, path, pins = setup
    p = replace(p, live_enabled=False, input_bound_calibrated=False)
    path.write_text(json.dumps(asdict(p)))
    pins['expected_policy_sha256'] = hashlib.sha256(_json(asdict(p)).encode()).hexdigest()
    result = api().audit(ledger.path, path, **pins)
    assert result['policy']['declared_live_ready'] is False
    assert result['paid_admission'] is False


def test_cli_has_safe_failure_and_success_json(setup):
    ledger, _, path, pins = setup
    command = [sys.executable, '-m', 'ops.pi.analysis_preflight', '--ledger', str(ledger.path),
               '--policy', str(path), '--scope-sha256', pins['expected_scope_sha256'],
               '--policy-sha256', pins['expected_policy_sha256']]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0 and not result.stderr
    assert json.loads(result.stdout) == audit(setup)
    command[-1] = 'PRIVATE-BAD-PIN'
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 2 and not result.stderr
    assert json.loads(result.stdout) == dict(audit_valid=False, paid_admission=False,
                                            error='analysis preflight blocked')


def test_extreme_price_fails_safely_without_decimal_traceback(setup):
    ledger, p, path, pins = setup
    data = asdict(p)
    data['prices']['input'] = '1E999999999'
    path.write_text(json.dumps(data))
    pins['expected_policy_sha256'] = hashlib.sha256(_json(data).encode()).hexdigest()
    with pytest.raises(LedgerBlocked, match='analysis preflight blocked'):
        api().audit(ledger.path, path, **pins)


def test_unpriced_cache_does_not_fabricate_a_reservation_estimate(setup):
    ledger, p, path, pins = setup
    data = asdict(p);data['prices']['cache_write'] = None
    path.write_text(json.dumps(data))
    pins['expected_policy_sha256'] = hashlib.sha256(_json(data).encode()).hexdigest()
    result = api().audit(ledger.path, path, **pins)
    assert result['policy']['max_request_reserved_microyuan'] is None
    assert result['policy']['declared_live_ready'] is False
    assert result['paid_admission'] is False
