"""Atomic shared trial reservations, using the ledger's immutable intents/receipts."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
import time
import uuid

from .contracts import Receipt, Record
from .ledger import Ledger, _json, OperationConflict
from .policy import Policy, rate


class BudgetDenied(ValueError):
    pass


@dataclass(frozen=True)
class BudgetPermit:
    attempt_id: str
    scope_id: str
    reserved_microyuan: int
    deadline: float


def _totals(connection, scope_id):
    count = total = 0
    for row in connection.execute("SELECT payload,evidence FROM operations WHERE kind='model-attempt'"):
        payload = Ledger._decode(row['payload'])
        if payload['scope_id'] == scope_id:
            count += 1
            evidence = Ledger._decode(row['evidence']) if row['evidence'] else {}
            total += evidence.get('charged_microyuan', payload['reserved_microyuan'])
    return count, total


def totals(ledger: Ledger, scope_id: str) -> tuple[int, int]:
    with ledger.transaction() as connection:
        return _totals(connection, scope_id)



def _trusted_reference(value, maximum):
    return (isinstance(value, str) and 0 < len(value) <= maximum and value == value.strip()
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def _validate_amendment(payload):
    fields = {'scope_id', 'expected_original_microyuan', 'expected_effective_microyuan',
              'budget_microyuan', 'authorization_reference', 'approved'}
    if (set(payload) != fields or payload['scope_id'] != 'local-trial-1'
            or payload['approved'] is not True
            or not _trusted_reference(payload['authorization_reference'], 512)
            or any(type(payload[k]) is not int for k in
                   ('expected_original_microyuan', 'expected_effective_microyuan', 'budget_microyuan'))
            or (payload['expected_original_microyuan'], payload['expected_effective_microyuan'],
                payload['budget_microyuan']) != (10000000, 10000000, 20000000)):
        raise BudgetDenied('invalid trusted local budget amendment')


def _scope_payload(row):
    if row is None:
        raise BudgetDenied('budget amendment requires the original scope')
    if row['kind'] != 'model-scope':
        raise OperationConflict('scope identity conflict')
    payload = Ledger._decode(row['payload'])
    if (set(payload) != {'max_attempts', 'budget_microyuan'}
            or type(payload['max_attempts']) is not int or not 0 < payload['max_attempts'] <= 100
            or type(payload['budget_microyuan']) is not int or not 0 < payload['budget_microyuan'] <= 10000000
            or row['status'] != 'pending' or row['evidence'] is not None):
        raise BudgetDenied('invalid original model scope')
    return payload


def _amendment_evidence(payload):
    return dict(approved=True, budget_microyuan=payload['budget_microyuan'],
                authorization_reference=payload['authorization_reference'])


def _effective_budget(connection, scope_payload):
    rows = connection.execute("SELECT * FROM operations WHERE kind='model-budget-amendment'").fetchall()
    if not rows:
        return scope_payload['budget_microyuan']
    if len(rows) != 1 or scope_payload['budget_microyuan'] != 10000000:
        raise BudgetDenied('invalid cumulative budget amendment history')
    row = rows[0]
    payload = Ledger._decode(row['payload'])
    _validate_amendment(payload)
    evidence = _amendment_evidence(payload)
    if (not _trusted_reference(row['operation_id'], 128) or row['status'] != 'done'
            or row['evidence'] is None or _json(Ledger._decode(row['evidence'])) != _json(evidence)):
        raise BudgetDenied('budget amendment lacks trusted approval receipt')
    expected = [
        ('intent', dict(operation_id=row['operation_id'], kind='model-budget-amendment',
                        payload=payload, schema_version=1)),
        ('receipt', dict(operation_id=row['operation_id'], status='done', evidence=evidence, schema_version=1)),
    ]
    actual = []
    for event in connection.execute("SELECT kind,payload FROM events WHERE kind IN ('intent','receipt') ORDER BY id"):
        event_payload = Ledger._decode(event['payload'])
        if event_payload.get('operation_id') == row['operation_id']:
            actual.append((event['kind'], event_payload))
    if [(kind, _json(data)) for kind, data in actual] != [(kind, _json(data)) for kind, data in expected]:
        raise BudgetDenied('budget amendment approval audit mismatch')
    return payload['budget_microyuan']


def amend_local_trial_budget(ledger: Ledger, scope_id: str, *, operation_id: str,
                             expected_original_microyuan: int, expected_effective_microyuan: int,
                             budget_microyuan: int, authorization_reference: str, approved: bool) -> Record:
    """Root host only: append one explicitly approved cumulative10->20CNY upgrade.

    The root-only ledger/private-policy mount and model tool allowlist are the
    authorization boundary. This host attestation is never a model tool or API.
    Original scopes, historical attempts and their terminal receipts stay intact.
    """
    payload = dict(scope_id=scope_id, expected_original_microyuan=expected_original_microyuan,
                   expected_effective_microyuan=expected_effective_microyuan,
                   budget_microyuan=budget_microyuan, authorization_reference=authorization_reference,
                   approved=approved)
    _validate_amendment(payload)
    if not _trusted_reference(operation_id, 128):
        raise BudgetDenied('invalid amendment identity')
    encoded = _json(payload)
    evidence = _amendment_evidence(payload)
    with ledger.transaction() as connection:
        scope = connection.execute('SELECT * FROM operations WHERE operation_id=?',
                                   ('model-scope:' + scope_id,)).fetchone()
        original = _scope_payload(scope)
        existing = connection.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
        if existing is not None and (existing['kind'] != 'model-budget-amendment' or existing['payload'] != encoded):
            raise OperationConflict('amendment identity already has a different intent')
        effective = _effective_budget(connection, original)
        if existing is not None:
            return Ledger._record(existing)
        if original['budget_microyuan'] != expected_original_microyuan:
            raise BudgetDenied('original budget does not match authorization')
        if effective != expected_effective_microyuan:
            raise OperationConflict('effective budget does not match authorization')
        connection.execute("INSERT INTO operations VALUES (?,'model-budget-amendment',?,'pending',NULL,1)",
                           (operation_id, encoded))
        connection.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',
                           ('intent', _json(dict(operation_id=operation_id, kind='model-budget-amendment',
                                                 payload=payload, schema_version=1))))
        connection.execute("UPDATE operations SET status='done',evidence=? WHERE operation_id=?",
                           (_json(evidence), operation_id))
        connection.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',
                           ('receipt', _json(dict(operation_id=operation_id, status='done', evidence=evidence, schema_version=1))))
        return Ledger._record(connection.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone())


def reserve(ledger: Ledger, scope_id: str, request: Record, policy: Policy) -> BudgetPermit:
    # No date-derived reset in this trial; future daily scopes remain disabled.
    if scope_id != 'local-trial-1':
        raise BudgetDenied('scope disabled')
    tokens = request.get('max_tokens')
    if type(tokens) is not int or not 0 < tokens <= policy.max_tokens:
        raise ValueError('invalid max_tokens')
    input_rate = max(rate(v) for k, v in policy.prices.items() if k != 'output' and v is not None)
    amount = int((input_rate * policy.input_token_bound + rate(policy.prices['output']) * tokens).to_integral_value(rounding=ROUND_CEILING))
    permit = BudgetPermit(str(uuid.uuid4()), scope_id, amount, time.time() + policy.timeout_seconds)
    payload = dict(scope_id=scope_id, reserved_microyuan=amount, deadline=permit.deadline,
                   prices=dict(policy.prices), input_token_bound=policy.input_token_bound, max_tokens=tokens)
    with ledger.transaction() as connection:
        scope_key = 'model-scope:' + scope_id
        scope = connection.execute('SELECT * FROM operations WHERE operation_id=?', (scope_key,)).fetchone()
        if scope is None:
            scope_payload = dict(max_attempts=min(100, policy.max_attempts), budget_microyuan=min(10000000, policy.budget_microyuan))
            connection.execute("INSERT INTO operations VALUES (?,'model-scope',?,'pending',NULL,1)", (scope_key, _json(scope_payload)))
        else:
            scope_payload = _scope_payload(scope)
        effective_budget = _effective_budget(connection, scope_payload)
        count, used = _totals(connection, scope_id)
        if count >= min(100, policy.max_attempts, scope_payload['max_attempts']) or used + amount > min(20000000, policy.budget_microyuan, effective_budget):
            raise BudgetDenied('trial budget exhausted')
        connection.execute("INSERT INTO operations VALUES (?,'model-attempt',?,'pending',NULL,1)", (permit.attempt_id, _json(payload)))
        connection.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)', ('model-reserved', _json(dict(attempt_id=permit.attempt_id, **payload))))
    return permit


def settle(ledger: Ledger, permit: BudgetPermit, usage: Record | None) -> None:
    row = ledger.get(permit.attempt_id)
    if row is None or row['kind'] != 'model-attempt':
        raise OperationConflict('unknown model permit')
    p = row['payload']
    if (p['scope_id'], p['reserved_microyuan'], p['deadline']) != (permit.scope_id, permit.reserved_microyuan, permit.deadline):
        raise OperationConflict('model permit mismatch')
    if row['status'] != 'pending':
        return
    charged = permit.reserved_microyuan
    known = isinstance(usage, dict)
    dimensions = dict(input_tokens='input', output_tokens='output', cache_read_input_tokens='cache_read', cache_creation_input_tokens='cache_write')
    if known:
        known = (not set(usage) - (set(dimensions) | {'provider_request_id'})
                 and all(type(usage.get(k)) is int and usage[k] >= 0 for k in dimensions))
    if known:
        known = usage['output_tokens'] <= p['max_tokens'] and sum(usage[k] for k in dimensions if k != 'output_tokens') <= p['input_token_bound']
    if known:
        cost = Decimal(0)
        for key, price_key in dimensions.items():
            price = p['prices'][price_key]
            if usage[key] and price is None:
                known = False
                break
            if price is not None:
                cost += usage[key] * rate(price)
        if known:
            charged = int(cost.to_integral_value(rounding=ROUND_CEILING))
            known = charged <= permit.reserved_microyuan
    evidence = dict(charged_microyuan=charged if known else permit.reserved_microyuan, usage_known=known)
    if isinstance(usage, dict) and isinstance(usage.get('provider_request_id'), str):
        evidence['provider_request_id'] = usage['provider_request_id'][:256]
    try:
        ledger.finish(Receipt(permit.attempt_id, 'done' if known else 'uncertain', evidence))
    except OperationConflict:
        # Another consumer settled this immutable attempt first.
        if ledger.get(permit.attempt_id)['status'] == 'pending':
            raise
