"""Trusted analysis-run limits on canonical model-attempts, never a new scope.

The host must supply explicit limits and the original approved ledger. A run
binding is immutable. Admission and reservation remain separate: a claim whose
reservation fails is consumed, never an invitation to retry.
"""
from dataclasses import asdict
import json
import math
import time

from .analysis_execution import _hash, verify_contract_request
from .budget import BudgetDenied, _scope_payload, _effective_trial_limits
from .ledger import Ledger, OperationConflict, _json


def _scope_identity(db):
    scope = db.execute('SELECT * FROM operations WHERE operation_id=?',
                       ('model-scope:local-trial-1',)).fetchone()
    original = _scope_payload(scope)  # A missing scope must never bootstrap a budget.
    if (original != dict(max_attempts=100, budget_microyuan=10000000)
            or _effective_trial_limits(db, original) not in (dict(
                max_attempts=None, budget_microyuan=20000000, phase_allocations=None),
                dict(max_attempts=None, budget_microyuan=None, phase_allocations=None))):
        raise BudgetDenied('analysis requires original approved fee-only scope')
    rows = db.execute("SELECT * FROM operations WHERE operation_id='model-scope:local-trial-1' "
                      "OR kind IN ('model-budget-amendment','model-budget-amendment-v2','model-budget-amendment-v3') "
                      'ORDER BY operation_id').fetchall()
    return _hash([dict(row) for row in rows])


def _binding(run, db):
    row = db.execute('SELECT * FROM operations WHERE operation_id=?',
                     (run._run_id + ':budget',)).fetchone()
    if row is None:
        return None
    if (row['kind'] != 'analysis_run_budget' or row['status'] != 'pending'
            or row['evidence'] is not None or row['schema_version'] != 1):
        raise BudgetDenied('invalid analysis budget binding')
    return row['payload']


def bind_run_budget(run, policy, *, cap_microyuan, deadline):
    uncapped = policy.schema_version == 3 and policy.budget_microyuan is None
    if ((not (uncapped and cap_microyuan is None)
            and (type(cap_microyuan) is not int or not 0 < cap_microyuan <= 20000000))
            or type(deadline) not in (int, float) or not math.isfinite(deadline)):
        raise BudgetDenied('explicit run fee policy and absolute deadline required')
    if (policy.max_attempts is not None or policy.server_daily_enabled
            or not (uncapped or (policy.schema_version == 2 and policy.budget_microyuan == 20000000))):
        raise BudgetDenied('frozen fee-only policy required')
    payload = dict(identity=run._identity, cap_microyuan=cap_microyuan,
                   deadline=deadline, policy=asdict(policy))
    with run.ledger.transaction() as db:
        states = run._check(db)
        payload['scope_sha256'] = _scope_identity(db)
        if uncapped and _effective_trial_limits(db, _scope_payload(db.execute(
                'SELECT * FROM operations WHERE operation_id=?', ('model-scope:local-trial-1',)).fetchone()))['budget_microyuan'] is not None:
            raise BudgetDenied('no-fee-cap run requires trusted scope approval')
        encoded = _json(payload)  # Snapshot mutable caller policy fields.
        existing = _binding(run, db)
        if existing is not None:
            if existing != encoded:
                raise OperationConflict('analysis budget cannot reset or extend')
            return
        if deadline <= time.time():
            raise BudgetDenied('analysis deadline expired')
        if any(state['status'] != 'NOT_RUN' for state in states):
            raise OperationConflict('budget must bind before any slot admission')
        run._insert(db, run._run_id + ':budget', 'analysis_run_budget', payload)


class AnalysisBudgetSlot:
    """Private host context, captured with a handler, checked in reserve's lock.

    Unbound handlers keep legacy low-level behavior, but cannot ignore a binding
    added after their construction. Bound handlers never fall back on missing
    storage. No field in this context can be selected by a model request.
    """
    def __init__(self, run, slot_index):
        run._index(slot_index)
        self.run, self.index = run, slot_index
        with run.ledger.transaction() as db:
            run._check(db)
            self._encoded = _binding(run, db)

    @property
    def binding(self):
        return json.loads(self._encoded) if self._encoded is not None else None

    @property
    def deadline(self):
        binding = self.binding
        return binding['deadline'] if binding is not None else None

    def authorize(self, db, ledger, body, policy, amount):
        if ledger.path.resolve() != self.run.ledger.path.resolve():
            raise BudgetDenied('analysis context belongs to another ledger')
        if _binding(self.run, db) != self._encoded:
            raise BudgetDenied('analysis budget binding missing or changed')
        if self._encoded is None:
            return {}, None
        binding = self.binding
        if (binding['identity'] != self.run._identity
                or binding['scope_sha256'] != _scope_identity(db)):
            raise BudgetDenied('analysis budget identity changed')
        current, frozen = asdict(policy), binding['policy']
        timeout = current.pop('timeout_seconds')
        if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 0 < timeout <= frozen['timeout_seconds']
                or _json(current) != _json({k:v for k,v in frozen.items() if k != 'timeout_seconds'})):
            raise BudgetDenied('analysis policy drift')
        states = self.run._check(db)
        if (states[self.index]['status'] != 'UNCERTAIN'
                or any(s['status'] not in ('DONE', 'FAILED') for s in states[:self.index])):
            raise BudgetDenied('analysis reservation requires active ordered claim')
        try:
            verify_contract_request(body, self.run._slots[self.index])
        except (ValueError, TypeError, KeyError):
            raise BudgetDenied('analysis request drift') from None
        used = 0
        for row in db.execute("SELECT * FROM operations WHERE kind='model-attempt'"):
            payload = Ledger._decode(row['payload'])
            if payload.get('analysis_run_id') != self.run._identity['run_id']:
                continue
            if payload.get('analysis_slot_index') == self.index:
                raise BudgetDenied('analysis slot already reserved')
            evidence = Ledger._decode(row['evidence']) if row['evidence'] else {}
            if row['status'] != 'done' or evidence.get('usage_known') is not True:
                raise BudgetDenied('preceding analysis billing unresolved')
            used += evidence['charged_microyuan']
        if binding['cap_microyuan'] is not None and used + amount > binding['cap_microyuan']:
            raise BudgetDenied('analysis run budget exhausted')
        # Last check inside BEGIN IMMEDIATE, including time spent waiting for it.
        if time.time() >= binding['deadline']:
            raise BudgetDenied('analysis run deadline expired')
        return dict(analysis_run_id=self.run._identity['run_id'],
                    analysis_slot_index=self.index), binding['deadline']
