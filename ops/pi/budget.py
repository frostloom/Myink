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
            scope_payload = dict(max_attempts=policy.max_attempts, budget_microyuan=policy.budget_microyuan)
            connection.execute("INSERT INTO operations VALUES (?,'model-scope',?,'pending',NULL,1)", (scope_key, _json(scope_payload)))
        else:
            if scope['kind'] != 'model-scope':
                raise OperationConflict('scope identity conflict')
            scope_payload = Ledger._decode(scope['payload'])
        count, used = _totals(connection, scope_id)
        if count >= min(100, policy.max_attempts, scope_payload['max_attempts']) or used + amount > min(10000000, policy.budget_microyuan, scope_payload['budget_microyuan']):
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
