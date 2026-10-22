"""Read-only host diagnostics; a receipt never authorizes paid execution.

The trusted caller selects the canonical path and pins reviewed identities.
A logical snapshot hash is neither a signature nor a lock on later writers.
SQLite may maintain WAL shared-memory read marks; no logical writes occur.
"""
import argparse
from dataclasses import asdict
from decimal import ROUND_CEILING
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .analysis_budget import _scope_identity
from .control import live_ready
from .ledger import Ledger, LedgerBlocked, OperationConflict, _json, validate_connection
from .policy import load_policy, rate


_REQUIRED = [
    'current_price_evidence_review',
    'input_bound_evidence_review',
    'frozen_source_config_and_container_provenance',
    'explicit_run_cap_and_absolute_deadline',
    'canonical_ledger_recheck_inside_reservation',
    'trusted_container_paid_launcher_integration',
]


def _sha(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _money(value):
    if type(value) is not int or value < 0:
        raise LedgerBlocked('invalid accounting')
    return value


def _accounting(db):
    known_count = unknown_count = pending_count = known_cost = unknown_reserve = 0
    for row in db.execute("SELECT * FROM operations WHERE kind='model-attempt'"):
        payload = Ledger._decode(row['payload'])
        if payload['scope_id'] != 'local-trial-1':
            raise LedgerBlocked('unexpected accounting scope')
        reserved = _money(payload['reserved_microyuan'])
        if row['status'] == 'pending':
            pending_count += 1
            unknown_count += 1
            unknown_reserve += reserved
            continue
        evidence = Ledger._decode(row['evidence'])
        if type(evidence['usage_known']) is not bool:
            raise LedgerBlocked('invalid accounting')
        charged = _money(evidence['charged_microyuan'])
        if evidence['usage_known']:
            if row['status'] != 'done' or charged > reserved:
                raise LedgerBlocked('invalid known accounting')
            known_count += 1
            known_cost += charged
        else:
            if row['status'] != 'uncertain' or charged != reserved:
                raise LedgerBlocked('unknown accounting must retain reservation')
            unknown_count += 1
            unknown_reserve += reserved
    used = known_cost + unknown_reserve
    return dict(attempts=known_count + unknown_count, known_attempts=known_count,
                unknown_attempts=unknown_count, pending_attempts=pending_count,
                known_charged_microyuan=known_cost, unknown_reserved_microyuan=unknown_reserve,
                conservative_used_microyuan=used, budget_microyuan=20000000,
                conservative_remaining_microyuan=max(0, 20000000 - used))


def audit(ledger_path, policy_path, *, expected_scope_sha256, expected_policy_sha256):
    """Observe one consistent snapshot, without bootstrap, reservation or repair.

    Pins come from the trusted host, never from model input. Policy digest is
    canonical JSON(asdict(load_policy(...))), not the raw file byte digest.
    Historical source strings/flags are declarations, not verified evidence.
    """
    db = None
    try:
        for pin in (expected_scope_sha256, expected_policy_sha256):
            if not isinstance(pin, str) or not re.fullmatch('[0-9a-f]{64}', pin):
                raise LedgerBlocked('invalid identity pin')
        policy = load_policy(Path(policy_path))
        policy_sha = _sha(asdict(policy))
        if (policy_sha != expected_policy_sha256 or policy.schema_version != 2
                or policy.max_attempts is not None or policy.budget_microyuan != 20000000
                or policy.server_daily_enabled):
            raise LedgerBlocked('policy identity mismatch')
        path = Path(ledger_path).resolve(strict=True)
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, isolation_level=None, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        validate_connection(db)
        scope_sha = _scope_identity(db)
        if scope_sha != expected_scope_sha256:
            raise LedgerBlocked('scope identity mismatch')
        accounting = _accounting(db)
        snapshot = dict(
            user_version=db.execute('PRAGMA user_version').fetchone()[0],
            schema=[list(row) for row in db.execute(
                'SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')],
            operations=[dict(row) for row in db.execute('SELECT * FROM operations ORDER BY operation_id')],
            events=[dict(row) for row in db.execute('SELECT * FROM events ORDER BY id')],
            sequences=[list(row) for row in db.execute('SELECT name,seq FROM sqlite_sequence ORDER BY name')])
        reserve = None
        if all(v is not None for v in policy.prices.values()):
            input_rate = max(rate(v) for k, v in policy.prices.items() if k != 'output')
            reserve = int((input_rate * policy.input_token_bound + rate(policy.prices['output'])
                           * policy.max_tokens).to_integral_value(rounding=ROUND_CEILING))
        return dict(audit_valid=True, paid_admission=False,
            ledger=dict(sha256=_sha(snapshot), scope_sha256=scope_sha,
                        operations=len(snapshot['operations']), events=len(snapshot['events'])),
            accounting=accounting,
            policy=dict(sha256=policy_sha, declared_live_ready=live_ready(policy),
                        declared_input_bound_calibrated=policy.input_bound_calibrated,
                        input_token_bound=policy.input_token_bound,
                        max_tokens=policy.max_tokens, max_request_reserved_microyuan=reserve),
            required_before_paid=list(_REQUIRED))
    except (OSError, sqlite3.DatabaseError, ValueError, TypeError, KeyError, ArithmeticError,
            LedgerBlocked, OperationConflict):
        # Neither private rows/paths nor malformed policy text reach CLI errors.
        raise LedgerBlocked('analysis preflight blocked') from None
    finally:
        if db is not None:
            db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--policy', required=True)
    parser.add_argument('--scope-sha256', required=True)
    parser.add_argument('--policy-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(args.ledger, args.policy, expected_scope_sha256=args.scope_sha256,
                       expected_policy_sha256=args.policy_sha256)
    except LedgerBlocked:
        print(json.dumps(dict(audit_valid=False, paid_admission=False, error='analysis preflight blocked')))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
