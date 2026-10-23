"""Durable, at-most-once slot admission. This is not a paid-run grant.

Only the trusted host can create a run, bind a guard to a slot, or finish it.
The host can bind explicit whole-run limits to the canonical ledger.
Containment and outcome verification remain with that host. An unfinished
claim is uncertain, never permission to resend.
"""
from hashlib import sha256
import json
import re

from .analysis_execution import _hash, verify_contract_request
from .analysis_trial import GROUPS
from .ledger import LedgerBlocked, OperationConflict, _json


class AnalysisRun:
    @classmethod
    def _bound(cls, ledger, run_id, slots, source_sha256, config_sha256):
        if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', run_id):
            raise ValueError('bounded host run identity required')
        for digest in (source_sha256, config_sha256):
            if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise ValueError('source and config SHA256 required')
        if not isinstance(slots, list) or len(slots) != 30:
            raise ValueError('exact thirty frozen slots required')
        # Snapshot caller-owned mutable inputs, including all request content.
        slots = json.loads(_json(slots))
        for index, slot in enumerate(slots):
            repeat, offset = divmod(index, 10)
            arms = ('candidate', 'baseline') if repeat == 1 else ('baseline', 'candidate')
            expected = f'r{repeat + 1}:{GROUPS[offset // 2]}:{arms[offset % 2]}'
            if slot['slot_id'] != expected:
                raise ValueError('frozen slot order required')
            verify_contract_request(slot['request'], slot)
        self = cls()
        self.ledger = ledger
        self._slots = slots
        self._run_id = 'analysis:' + run_id
        self._identity = dict(run_id=run_id, scope_id='local-trial-1',
            source_sha256=source_sha256, config_sha256=config_sha256,
            slots_sha256=_hash(slots), slot_count=30)
        return self

    @classmethod
    def create(cls, ledger, run_id, slots, *, source_sha256, config_sha256):
        """Register all slots atomically. A run identity can never be reset."""
        self = cls._bound(ledger, run_id, slots, source_sha256, config_sha256)
        with ledger.transaction() as db:
            if db.execute('SELECT 1 FROM operations WHERE operation_id=?', (self._run_id,)).fetchone():
                raise OperationConflict('analysis run already exists')
            self._insert(db, self._run_id, 'analysis_run', self._identity)
            for index in range(30):
                self._insert(db, self._slot_id(index), 'analysis_slot', self._payload(index))
        return self

    @classmethod
    def open(cls, ledger, run_id, slots, *, source_sha256, config_sha256):
        """Reopen the exact run; missing or drifted state cannot authorize work."""
        self = cls._bound(ledger, run_id, slots, source_sha256, config_sha256)
        with ledger.transaction() as db:
            self._check(db)
        return self

    def _slot_id(self, index):
        return f'{self._run_id}:slot:{index:02d}'

    def _payload(self, index):
        slot = self._slots[index]
        return dict(run_id=self._identity['run_id'], slot_index=index,
            slot_id=slot['slot_id'], request_sha256=slot['request_sha256'],
            slots_sha256=self._identity['slots_sha256'])

    @staticmethod
    def _index(index):
        if type(index) is not int or not 0 <= index < 30:
            raise ValueError('trusted slot index from 0 to 29 required')

    @staticmethod
    def _insert(db, operation_id, kind, payload):
        db.execute("INSERT INTO operations VALUES (?,?,?,'pending',NULL,1)",
                   (operation_id, kind, _json(payload)))
        db.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',
            ('intent', _json(dict(operation_id=operation_id, kind=kind,
                                payload=payload, schema_version=1))))

    @staticmethod
    def _finish(db, operation_id, status, evidence):
        db.execute('UPDATE operations SET status=?,evidence=? WHERE operation_id=?',
                   (status, _json(evidence), operation_id))
        db.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',
            ('receipt', _json(dict(operation_id=operation_id, status=status, evidence=evidence,
                                 schema_version=1))))

    def _check(self, db):
        def exact(operation_id, kind, payload):
            row = db.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
            if (row is None or row['kind'] != kind or row['payload'] != _json(payload)
                    or row['schema_version'] != 1):
                raise OperationConflict('missing or changed analysis identity')
            return row
        run = exact(self._run_id, 'analysis_run', self._identity)
        if run['status'] != 'pending' or run['evidence'] is not None:
            raise LedgerBlocked('invalid analysis run state')
        states = []
        for index in range(30):
            operation_id = self._slot_id(index)
            slot = exact(operation_id, 'analysis_slot', self._payload(index))
            claim = db.execute('SELECT * FROM operations WHERE operation_id=?',
                               (operation_id + ':claim',)).fetchone()
            if claim is not None:
                exact(operation_id + ':claim', 'analysis_slot_claim', self._payload(index))
                if claim['status'] != 'done' or claim['evidence'] != _json({'admitted': True}):
                    raise LedgerBlocked('invalid analysis claim state')
            if slot['status'] == 'pending' and slot['evidence'] is None:
                state = 'UNCERTAIN' if claim is not None else 'NOT_RUN'
            elif (claim is not None and slot['status'] in ('done', 'failed', 'uncertain', 'blocked')
                  and slot['evidence'] == _json({'host_status': slot['status']})):
                state = slot['status'].upper()
            else:
                raise LedgerBlocked('invalid analysis slot state')
            states.append(dict(slot_index=index, slot_id=self._slots[index]['slot_id'], status=state))
        return states

    def bind_budget(self, policy, *, cap_microyuan, deadline):
        """Freeze explicit host limits before admission; never a paid-run grant."""
        from .analysis_budget import bind_run_budget
        bind_run_budget(self, policy, cap_microyuan=cap_microyuan, deadline=deadline)

    def gateway_handler(self, slot_index, policy, transport, *, scope_token, usage_observer=None, cancel=None):
        """Build the existing gateway with a distinct private token per slot.

        Persist only the token digest. The host supplies a fresh unguessable
        token to this handler and that slot's new Pi session; no other slot or
        run in this ledger may reuse it. A body alone cannot distinguish the
        identical baseline requests across slots.
        """
        from .control import make_gateway_handler
        self._index(slot_index)
        if (not isinstance(scope_token, str) or not 32 <= len(scope_token) <= 4096
                or any(not 33 <= ord(char) <= 126 for char in scope_token)):
            raise ValueError('private bounded per-slot token required')
        digest = sha256(scope_token.encode('ascii')).hexdigest()
        payload = self._payload(slot_index) | {'token_sha256': digest}
        bindings = ((self._slot_id(slot_index) + ':gateway', 'analysis_slot_gateway'),
                    ('analysis:gateway-token:' + digest, 'analysis_gateway_token'))
        with self.ledger.transaction() as db:
            self._check(db)
            for operation_id, kind in bindings:
                row = db.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
                if row is None:
                    self._insert(db, operation_id, kind, payload)
                elif (row['kind'] != kind or row['payload'] != _json(payload)
                      or row['status'] != 'pending' or row['evidence'] is not None):
                    raise OperationConflict('gateway token already bound to a different slot')
        from .analysis_budget import AnalysisBudgetSlot
        return make_gateway_handler(self.ledger, policy, transport,
            scope_token=scope_token, usage_observer=usage_observer, request_guard=self.guard(slot_index),
            analysis_slot=AnalysisBudgetSlot(self, slot_index), cancel=cancel)

    def guard(self, slot_index):
        """Low-level body guard for a trusted host-selected slot.

        HTTP callers should use gateway_handler to also bind per-slot tokens.

        Return True only after its admission claim commits durably. Any later
        failure still consumes that admission; restarting cannot resend it.
        """
        self._index(slot_index)
        def admit(body):
            with self.ledger.transaction() as db:
                states = self._check(db)
                if (states[slot_index]['status'] != 'NOT_RUN'
                        or any(s['status'] not in ('DONE', 'FAILED') for s in states[:slot_index])):
                    raise OperationConflict('slot already claimed or preceding outcome unresolved')
                verify_contract_request(body, self._slots[slot_index])
                claim_id = self._slot_id(slot_index) + ':claim'
                self._insert(db, claim_id, 'analysis_slot_claim', self._payload(slot_index))
                self._finish(db, claim_id, 'done', {'admitted': True})
            return True
        return admit

    def finish(self, slot_index, *, status, check=None):
        """Host records a known outcome; this does not certify billing/quality.

        'done' and 'failed' allow the next slot. 'uncertain' and 'blocked' stop
        the run. All terminal outcomes are immutable, including on reopen.
        """
        self._index(slot_index)
        if status not in ('done', 'failed', 'uncertain', 'blocked'):
            raise ValueError('terminal host status required')
        with self.ledger.transaction() as db:
            states = self._check(db)
            operation_id = self._slot_id(slot_index)
            row = db.execute('SELECT status FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
            if states[slot_index]['status'] == 'NOT_RUN':
                raise OperationConflict('slot outcome requires a durable claim')
            if row['status'] != 'pending':
                if row['status'] == status:
                    return
                raise OperationConflict('terminal slot outcome is immutable')
            if check is not None: check()
            self._finish(db, operation_id, status, {'host_status': status})
            if check is not None: check()

    def snapshot(self):
        """Return all thirty body-free states, including unrun slots."""
        with self.ledger.transaction() as db:
            return self._check(db)
