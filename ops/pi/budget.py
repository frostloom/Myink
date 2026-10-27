"""Atomic shared trial reservations, using the ledger's immutable intents/receipts."""
from dataclasses import asdict, dataclass, replace
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


TRIAL_PHASE_ALLOCATIONS = {'analysis': 15, 'develop': 45, 'experiment': 30, 'reserve': 10}


def _original_phase_fence(connection):
    row = connection.execute('SELECT * FROM operations WHERE operation_id=?',
                             ('c17-phase-admission:local-trial-1',)).fetchone()
    if row is None or row['kind'] != 'phase-fence' or row['status'] != 'pending' or row['evidence'] is not None:
        raise BudgetDenied('fee-only amendment requires original phase fence')
    data = Ledger._decode(row['payload'])
    inherited = data.get('inherited_analysis_attempts')
    if (set(data) != {'scope_id', 'allocations', 'inherited_analysis_attempts'}
            or data['scope_id'] != 'local-trial-1' or data['allocations'] != TRIAL_PHASE_ALLOCATIONS
            or not isinstance(inherited, list) or len(inherited) > 15
            or any(not _trusted_reference(v, 128) for v in inherited)
            or len(set(inherited)) != len(inherited)):
        raise BudgetDenied('invalid original phase fence')
    return data


def _validate_amendment_v2(payload):
    fields = {'amendment_version', 'scope_id', 'expected_original_microyuan',
              'expected_effective_microyuan', 'expected_effective_max_attempts',
              'budget_microyuan', 'max_attempts', 'phase_allocations',
              'authorization_reference', 'approved'}
    if (set(payload) != fields or payload['scope_id'] != 'local-trial-1'
            or payload['approved'] is not True
            or not _trusted_reference(payload['authorization_reference'], 512)
            or any(type(payload[k]) is not int for k in ('amendment_version',
                'expected_original_microyuan', 'expected_effective_microyuan',
                'expected_effective_max_attempts', 'budget_microyuan'))
            or (payload['amendment_version'], payload['expected_original_microyuan'],
                payload['expected_effective_microyuan'], payload['expected_effective_max_attempts'],
                payload['budget_microyuan']) != (2, 10000000, 20000000, 100, 20000000)
            or payload['max_attempts'] is not None or payload['phase_allocations'] is not None):
        raise BudgetDenied('invalid trusted fee-only amendment')


def _amendment_v2_evidence(payload):
    return {k: payload[k] for k in ('amendment_version', 'approved', 'budget_microyuan',
                                    'max_attempts', 'phase_allocations', 'authorization_reference')}


def _fee_only_trial_limits(connection, original):
    effective = _effective_budget(connection, original)  # original v1 approval remains independently valid
    result = dict(max_attempts=original['max_attempts'], budget_microyuan=effective,
                  phase_allocations=dict(TRIAL_PHASE_ALLOCATIONS))
    rows = connection.execute("SELECT * FROM operations WHERE kind='model-budget-amendment-v2'").fetchall()
    if not rows:
        return result
    if len(rows) != 1 or original != dict(max_attempts=100, budget_microyuan=10000000) or effective != 20000000:
        raise BudgetDenied('invalid fee-only amendment history')
    _original_phase_fence(connection)
    row = rows[0]
    payload = Ledger._decode(row['payload'])
    _validate_amendment_v2(payload)
    evidence = _amendment_v2_evidence(payload)
    if (not _trusted_reference(row['operation_id'], 128) or row['status'] != 'done'
            or row['evidence'] is None or _json(Ledger._decode(row['evidence'])) != _json(evidence)):
        raise BudgetDenied('fee-only amendment lacks trusted approval receipt')
    expected = [
        ('intent', dict(operation_id=row['operation_id'], kind='model-budget-amendment-v2',
                        payload=payload, schema_version=1)),
        ('receipt', dict(operation_id=row['operation_id'], status='done', evidence=evidence, schema_version=1)),
    ]
    actual = []
    for event in connection.execute("SELECT kind,payload FROM events WHERE kind IN ('intent','receipt') ORDER BY id"):
        data = Ledger._decode(event['payload'])
        if data.get('operation_id') == row['operation_id']:
            actual.append((event['kind'], data))
    if [(kind, _json(data)) for kind, data in actual] != [(kind, _json(data)) for kind, data in expected]:
        raise BudgetDenied('fee-only amendment approval audit mismatch')
    return dict(max_attempts=None, budget_microyuan=20000000, phase_allocations=None)


def _validate_amendment_v3(payload):
    expected = dict(amendment_version=3, scope_id='local-trial-1',
        expected_effective_microyuan=20000000, budget_microyuan=None,
        max_attempts=None, phase_allocations=None, approved=True)
    if (set(payload) != set(expected) | {'authorization_reference'}
            or any(type(payload.get(k)) is not type(v) or payload.get(k) != v for k,v in expected.items())
            or not _trusted_reference(payload.get('authorization_reference'), 512)):
        raise BudgetDenied('invalid explicit no-fee-cap approval')


def _uncapped_trial_limits(connection, original):
    limits = _fee_only_trial_limits(connection, original)
    rows = connection.execute("SELECT * FROM operations WHERE kind='model-budget-amendment-v3'").fetchall()
    if not rows:
        return limits
    if len(rows) != 1 or limits != dict(max_attempts=None, budget_microyuan=20000000, phase_allocations=None):
        raise BudgetDenied('invalid no-fee-cap approval history')
    row = rows[0]
    payload = Ledger._decode(row['payload'])
    _validate_amendment_v3(payload)
    evidence = _amendment_v2_evidence(payload)
    if (not _trusted_reference(row['operation_id'], 128) or row['schema_version'] != 1
            or row['status'] != 'done' or row['evidence'] is None
            or _json(Ledger._decode(row['evidence'])) != _json(evidence)):
        raise BudgetDenied('no-fee-cap approval receipt mismatch')
    expected = [
        ('intent', dict(operation_id=row['operation_id'], kind='model-budget-amendment-v3', payload=payload, schema_version=1)),
        ('receipt', dict(operation_id=row['operation_id'], status='done', evidence=evidence, schema_version=1))]
    actual = []
    for event in connection.execute("SELECT kind,payload FROM events WHERE kind IN ('intent','receipt') ORDER BY id"):
        data = Ledger._decode(event['payload'])
        if data.get('operation_id') == row['operation_id']:
            actual.append((event['kind'], data))
    if [(k,_json(v)) for k,v in actual] != [(k,_json(v)) for k,v in expected]:
        raise BudgetDenied('no-fee-cap approval audit mismatch')
    return dict(max_attempts=None, budget_microyuan=None, phase_allocations=None)


def amend_local_trial_budget_v3(ledger: Ledger, scope_id: str, *, operation_id: str,
        authorization_reference: str, approved: bool) -> Record:
    """Trusted host only: explicit human removal of monetary caps on the same scope.

    This changes neither original rows nor unknown reservations. A model cannot
    invoke this API. One immutable approval intent/receipt pair is required.
    """
    payload = dict(amendment_version=3, scope_id=scope_id, expected_effective_microyuan=20000000,
        budget_microyuan=None, max_attempts=None, phase_allocations=None,
        authorization_reference=authorization_reference, approved=approved)
    _validate_amendment_v3(payload)
    if not _trusted_reference(operation_id, 128):
        raise BudgetDenied('invalid no-fee-cap approval identity')
    encoded = _json(payload)
    evidence = _amendment_v2_evidence(payload)
    with ledger.transaction() as db:
        original = _scope_payload(db.execute('SELECT * FROM operations WHERE operation_id=?',
            ('model-scope:' + scope_id,)).fetchone())
        limits = _effective_trial_limits(db, original)
        existing = db.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
        if existing is not None:
            if existing['kind'] != 'model-budget-amendment-v3' or existing['payload'] != encoded:
                raise OperationConflict('no-fee-cap approval identity conflict')
            return Ledger._record(existing)
        if limits['budget_microyuan'] is None:
            raise OperationConflict('no-fee-cap approval already recorded')
        if limits != dict(max_attempts=None, budget_microyuan=20000000, phase_allocations=None):
            raise BudgetDenied('no-fee-cap approval requires original fee-only history')
        if db.execute("SELECT 1 FROM operations WHERE status='pending' AND kind IN ('model-attempt','phase-admission')").fetchone():
            raise BudgetDenied('settle active transports before approval')
        db.execute("INSERT INTO operations VALUES (?,'model-budget-amendment-v3',?,'done',?,1)", (operation_id,encoded,_json(evidence)))
        for kind,data in [
            ('intent',dict(operation_id=operation_id,kind='model-budget-amendment-v3',payload=payload,schema_version=1)),
            ('receipt',dict(operation_id=operation_id,status='done',evidence=evidence,schema_version=1))]:
            db.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)', (kind,_json(data)))
        return Ledger._record(db.execute('SELECT * FROM operations WHERE operation_id=?',(operation_id,)).fetchone())


def _validate_amendment_v4(payload):
    expected = dict(amendment_version=4, scope_id='local-trial-1',
        expected_effective_microyuan=None, budget_microyuan=50000000,
        max_attempts=None, phase_allocations=None, approved=True)
    if (set(payload) != set(expected) | {'authorization_reference'}
            or any(type(payload.get(k)) is not type(v) or payload.get(k) != v for k,v in expected.items())
            or not _trusted_reference(payload.get('authorization_reference'), 512)):
        raise BudgetDenied('invalid explicit finite50 approval')


def _effective_trial_limits(connection, original):
    limits = _uncapped_trial_limits(connection, original)
    rows = connection.execute("SELECT * FROM operations WHERE kind='model-budget-amendment-v4'").fetchall()
    identities={row['operation_id'] for row in rows};actual=[]
    for event in connection.execute("SELECT kind,payload FROM events WHERE kind IN ('intent','receipt') ORDER BY id"):
        data=Ledger._decode(event['payload']);evidence=data.get('evidence')
        declared=(event['kind']=='intent' and data.get('kind')=='model-budget-amendment-v4') or (
            event['kind']=='receipt' and isinstance(evidence,dict) and evidence.get('amendment_version') in (4,'4'))
        if declared or data.get('operation_id') in identities:actual.append((event['kind'],data))
    if not rows:
        if actual:raise BudgetDenied('orphan finite50 approval events')
        return limits
    if len(rows) != 1 or limits != dict(max_attempts=None, budget_microyuan=None, phase_allocations=None):
        raise BudgetDenied('invalid finite50 approval history')
    row = rows[0];payload = Ledger._decode(row['payload']);_validate_amendment_v4(payload)
    evidence = _amendment_v2_evidence(payload)
    if (not _trusted_reference(row['operation_id'],128) or row['schema_version'] != 1
            or row['status'] != 'done' or row['evidence'] is None
            or _json(Ledger._decode(row['evidence'])) != _json(evidence)):
        raise BudgetDenied('finite50 approval receipt mismatch')
    expected = [
        ('intent',dict(operation_id=row['operation_id'],kind='model-budget-amendment-v4',payload=payload,schema_version=1)),
        ('receipt',dict(operation_id=row['operation_id'],status='done',evidence=evidence,schema_version=1))]
    if [(k,_json(v)) for k,v in actual] != [(k,_json(v)) for k,v in expected]:
        raise BudgetDenied('finite50 approval audit mismatch')
    return dict(max_attempts=None,budget_microyuan=50000000,phase_allocations=None)


def amend_local_trial_budget_v4(ledger: Ledger, scope_id: str, *, operation_id: str,
        authorization_reference: str, approved: bool) -> Record:
    """Append explicit finite50 authority, preserving prior unlimited history and holds."""
    payload=dict(amendment_version=4,scope_id=scope_id,expected_effective_microyuan=None,
        budget_microyuan=50000000,max_attempts=None,phase_allocations=None,
        authorization_reference=authorization_reference,approved=approved)
    _validate_amendment_v4(payload)
    if not _trusted_reference(operation_id,128):raise BudgetDenied('invalid finite50 approval identity')
    encoded=_json(payload);evidence=_amendment_v2_evidence(payload)
    with ledger.transaction() as db:
        original=_scope_payload(db.execute('SELECT * FROM operations WHERE operation_id=?',('model-scope:'+scope_id,)).fetchone())
        limits=_effective_trial_limits(db,original)
        existing=db.execute('SELECT * FROM operations WHERE operation_id=?',(operation_id,)).fetchone()
        if existing is not None:
            if existing['kind']!='model-budget-amendment-v4' or existing['payload']!=encoded:
                raise OperationConflict('finite50 approval identity conflict')
            return Ledger._record(existing)
        if limits['budget_microyuan']==50000000:raise OperationConflict('finite50 approval already recorded')
        if limits!=dict(max_attempts=None,budget_microyuan=None,phase_allocations=None):
            raise BudgetDenied('finite50 approval requires original uncapped authority')
        if db.execute("SELECT 1 FROM operations WHERE status='pending' AND kind IN ('model-attempt','phase-admission')").fetchone():
            raise BudgetDenied('settle active transports before finite50 approval')
        if _totals(db,scope_id)[1]>50000000:raise BudgetDenied('existing usage exceeds finite50 ceiling')
        db.execute("INSERT INTO operations VALUES (?,'model-budget-amendment-v4',?,'done',?,1)",(operation_id,encoded,_json(evidence)))
        for kind,data in [
            ('intent',dict(operation_id=operation_id,kind='model-budget-amendment-v4',payload=payload,schema_version=1)),
            ('receipt',dict(operation_id=operation_id,status='done',evidence=evidence,schema_version=1))]:
            db.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',(kind,_json(data)))
        return Ledger._record(db.execute('SELECT * FROM operations WHERE operation_id=?',(operation_id,)).fetchone())


def effective_limits_in_connection(connection, scope_id='local-trial-1'):
    """SELECT-only limits for a host's existing snapshot transaction; no new scope."""
    if scope_id != 'local-trial-1':
        raise BudgetDenied('scope disabled')
    row = connection.execute('SELECT * FROM operations WHERE operation_id=?',
                             ('model-scope:' + scope_id,)).fetchone()
    if row is None:
        if connection.execute("SELECT 1 FROM operations WHERE kind IN ('model-budget-amendment','model-budget-amendment-v2','model-budget-amendment-v3','model-budget-amendment-v4')").fetchone():
            raise BudgetDenied('amendment without original scope')
        return dict(max_attempts=100, budget_microyuan=10000000,
                    phase_allocations=dict(TRIAL_PHASE_ALLOCATIONS))
    return _effective_trial_limits(connection, _scope_payload(row))


def effective_trial_limits(ledger: Ledger, scope_id='local-trial-1'):
    with ledger.transaction() as connection:
        return effective_limits_in_connection(connection, scope_id)


def amend_local_trial_budget_v2(ledger: Ledger, scope_id: str, *, operation_id: str,
        expected_original_microyuan: int, expected_effective_microyuan: int,
        expected_effective_max_attempts: int, budget_microyuan: int,
        max_attempts: None, phase_allocations: None, authorization_reference: str,
        approved: bool) -> Record:
    """Trusted host only: append explicit fee-only authority, never a model tool/API.

    Database schema1 and immutable original scope/v1/fence/attempts stay intact.
    Null is an explicit removal of cumulative request quotas, not a new money pool.
    The protected host ledger/policy and tool allowlist form the trust boundary.
    """
    payload = dict(amendment_version=2, scope_id=scope_id,
        expected_original_microyuan=expected_original_microyuan,
        expected_effective_microyuan=expected_effective_microyuan,
        expected_effective_max_attempts=expected_effective_max_attempts,
        budget_microyuan=budget_microyuan, max_attempts=max_attempts,
        phase_allocations=phase_allocations, authorization_reference=authorization_reference,
        approved=approved)
    _validate_amendment_v2(payload)
    if not _trusted_reference(operation_id, 128):
        raise BudgetDenied('invalid fee-only amendment identity')
    encoded = _json(payload)
    evidence = _amendment_v2_evidence(payload)
    with ledger.transaction() as connection:
        row = connection.execute('SELECT * FROM operations WHERE operation_id=?',
                                 ('model-scope:' + scope_id,)).fetchone()
        original = _scope_payload(row)
        existing = connection.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
        if existing is not None and (existing['kind'] != 'model-budget-amendment-v2' or existing['payload'] != encoded):
            raise OperationConflict('fee-only amendment identity conflict')
        limits = _effective_trial_limits(connection, original)
        if existing is not None:
            return Ledger._record(existing)
        if limits['max_attempts'] is None:
            raise OperationConflict('fee-only amendment already approved')
        if original != dict(max_attempts=100, budget_microyuan=10000000) or limits != dict(
                max_attempts=100, budget_microyuan=20000000, phase_allocations=TRIAL_PHASE_ALLOCATIONS):
            raise BudgetDenied('fee-only amendment requires original approved100/20 scope')
        _original_phase_fence(connection)
        for pending in connection.execute("SELECT kind,payload FROM operations WHERE status='pending' AND kind IN ('model-attempt','phase-admission')"):
            if pending['kind'] == 'phase-admission' or Ledger._decode(pending['payload']).get('scope_id') == scope_id:
                raise BudgetDenied('settle current model/phase transport before amendment')
        connection.execute("INSERT INTO operations VALUES (?,'model-budget-amendment-v2',?,'pending',NULL,1)", (operation_id, encoded))
        connection.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',
            ('intent', _json(dict(operation_id=operation_id, kind='model-budget-amendment-v2', payload=payload, schema_version=1))))
        connection.execute("UPDATE operations SET status='done',evidence=? WHERE operation_id=?", (_json(evidence), operation_id))
        connection.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',
            ('receipt', _json(dict(operation_id=operation_id, status='done', evidence=evidence, schema_version=1))))
        return Ledger._record(connection.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone())


def _policy_attempt_limit(policy):
    if policy.max_attempts is None:
        if (policy.server_daily_enabled or not (
                (policy.schema_version == 2 and policy.budget_microyuan == 20000000)
                or (policy.schema_version == 3 and policy.budget_microyuan is None)
                or (type(policy.schema_version) is int and policy.schema_version == 4
                    and type(policy.budget_microyuan) is int and policy.budget_microyuan == 50000000))):
            raise BudgetDenied('explicit local fee-only policy required')
        return None
    if type(policy.max_attempts) is not int or policy.max_attempts <= 0 or policy.schema_version != 1:
        raise BudgetDenied('invalid policy attempt limit')
    return min(100, policy.max_attempts)


def reserve(ledger: Ledger, scope_id: str, request: Record, policy: Policy, *, analysis_slot=None) -> BudgetPermit:
    # No date-derived reset in this trial; future daily scopes remain disabled.
    if scope_id != 'local-trial-1':
        raise BudgetDenied('scope disabled')
    if analysis_slot is not None:
        # Use one private snapshot for pricing, identity checks and the intent.
        policy = Policy(**asdict(policy))
        request = Ledger._decode(_json(request))
    policy_attempts = _policy_attempt_limit(policy)
    tokens = request.get('max_tokens')
    if type(tokens) is not int or not 0 < tokens <= policy.max_tokens:
        raise ValueError('invalid max_tokens')
    input_rate = max(rate(v) for k, v in policy.prices.items() if k != 'output' and v is not None)
    amount = int((input_rate * policy.input_token_bound + rate(policy.prices['output']) * tokens).to_integral_value(rounding=ROUND_CEILING))
    permit = BudgetPermit(str(uuid.uuid4()), scope_id, amount, time.time() + policy.timeout_seconds)
    payload = dict(scope_id=scope_id, reserved_microyuan=amount, deadline=permit.deadline,
                   prices=dict(policy.prices), input_token_bound=policy.input_token_bound, max_tokens=tokens)
    with ledger.transaction() as connection:
        if analysis_slot is not None:
            metadata, run_deadline = analysis_slot.authorize(connection, ledger, request, policy, amount)
            if run_deadline is not None:
                permit = replace(permit, deadline=min(permit.deadline, run_deadline))
                payload['deadline'] = permit.deadline
            payload.update(metadata)
        scope_key = 'model-scope:' + scope_id
        scope = connection.execute('SELECT * FROM operations WHERE operation_id=?', (scope_key,)).fetchone()
        if scope is None:
            scope_payload = dict(max_attempts=100 if policy_attempts is None else policy_attempts, budget_microyuan=10000000 if policy.budget_microyuan is None else min(10000000, policy.budget_microyuan))
            connection.execute("INSERT INTO operations VALUES (?,'model-scope',?,'pending',NULL,1)", (scope_key, _json(scope_payload)))
        else:
            scope_payload = _scope_payload(scope)
        limits = _effective_trial_limits(connection, scope_payload)
        attempt_bounds = [v for v in (policy_attempts, limits['max_attempts']) if v is not None]
        count, used = _totals(connection, scope_id)
        fee_bounds = [v for v in (policy.budget_microyuan, limits['budget_microyuan']) if v is not None]
        if policy.schema_version not in (3,4):
            fee_bounds.append(20000000)
        if (attempt_bounds and count >= min(attempt_bounds)) or (fee_bounds and used + amount > min(fee_bounds)):
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
