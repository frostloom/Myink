"""Durable intents and immutable outcomes. Pending always needs reconciliation."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
from typing import ContextManager

from .contracts import Receipt, Record


class LedgerBlocked(RuntimeError):
    """Storage cannot safely authorize a mutation."""


class OperationConflict(ValueError):
    """An identity or terminal outcome cannot be replaced."""


def _json(value: Record) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


_SCHEMA = (
    'CREATE TABLE operations(operation_id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, evidence TEXT, schema_version INTEGER NOT NULL CHECK(schema_version=1))',
    'CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, payload TEXT NOT NULL, schema_version INTEGER NOT NULL CHECK(schema_version=1))',
    "CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append only'); END",
    "CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append only'); END",
    "CREATE TRIGGER operations_identity BEFORE UPDATE ON operations WHEN NEW.operation_id != OLD.operation_id OR NEW.kind != OLD.kind OR NEW.payload != OLD.payload OR NEW.schema_version != OLD.schema_version BEGIN SELECT RAISE(ABORT,'immutable intent'); END",
    "CREATE TRIGGER operations_terminal BEFORE UPDATE ON operations WHEN OLD.status != 'pending' BEGIN SELECT RAISE(ABORT,'immutable receipt'); END",
    "CREATE TRIGGER operations_no_delete BEFORE DELETE ON operations BEGIN SELECT RAISE(ABORT,'immutable intent'); END",
    'PRAGMA user_version=1',
)


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        # Parent creation is deliberately the caller's explicit responsibility.
        with self.transaction() as connection:
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version == 0 and not tables:
                for statement in _SCHEMA:
                    connection.execute(statement)
            elif version != 1 or not {'operations', 'events'}.issubset(tables):
                raise LedgerBlocked('unsupported ledger schema')
            if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise LedgerBlocked('ledger integrity check failed')
            expected = {
                'operations': ['operation_id', 'kind', 'payload', 'status', 'evidence', 'schema_version'],
                'events': ['id', 'kind', 'payload', 'schema_version'],
            }
            for table, columns in expected.items():
                if [row[1] for row in connection.execute(f'PRAGMA table_info({table})')] != columns:
                    raise LedgerBlocked('unsupported ledger schema')
                if connection.execute(f'SELECT 1 FROM {table} WHERE schema_version != 1 LIMIT 1').fetchone():
                    raise LedgerBlocked('unsupported record version')
            for row in connection.execute('SELECT * FROM operations'):
                self._record(row)
                if row['status'] not in ('pending', 'done', 'failed', 'uncertain', 'blocked'):
                    raise LedgerBlocked('invalid operation status')
                if (row['status'] == 'pending') != (row['evidence'] is None):
                    raise LedgerBlocked('invalid operation receipt')
            for row in connection.execute('SELECT payload FROM events'):
                self._decode(row[0])
            actual = {row[0]: row[1] for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'trigger')"
            )}
            for statement in _SCHEMA:
                if statement.startswith('CREATE '):
                    name = statement.split()[2].split('(')[0]
                    if actual.get(name) != statement:
                        raise LedgerBlocked('unsupported ledger schema')

    @contextmanager
    def transaction(self) -> ContextManager[sqlite3.Connection]:
        connection = None
        try:
            deadline = time.monotonic() + 30
            connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            connection.row_factory = sqlite3.Row
            # SQLite can return BUSY immediately during the fresh-file WAL
            # transition despite busy_timeout. Retry only this pre-BEGIN step.
            while True:
                remaining = max(0, deadline - time.monotonic())
                connection.execute(f'PRAGMA busy_timeout={int(remaining * 1000)}')
                try:
                    connection.execute('PRAGMA journal_mode=WAL')
                    break
                except sqlite3.OperationalError as exc:
                    remaining = deadline - time.monotonic()
                    if getattr(exc, 'sqlite_errorcode', None) != sqlite3.SQLITE_BUSY or remaining <= 0:
                        raise
                    time.sleep(min(0.01, remaining))
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('PRAGMA recursive_triggers=ON')
            if connection.execute('PRAGMA recursive_triggers').fetchone()[0] != 1:
                raise LedgerBlocked('ledger safeguards unavailable')
            # WAL retries and BEGIN share the original contention wait budget.
            remaining = max(0, deadline - time.monotonic())
            connection.execute(f'PRAGMA busy_timeout={int(remaining * 1000)}')
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.rollback()
            raise LedgerBlocked('ledger storage unavailable') from exc
        except BaseException:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _decode(encoded: str) -> Record:
        try:
            result = json.loads(encoded)
            if not isinstance(result, dict):
                raise ValueError('record must be an object')
            _json(result)
            return result
        except (ValueError, TypeError) as exc:
            raise LedgerBlocked('invalid ledger record') from exc

    @staticmethod
    def _record(row) -> Record | None:
        if row is None:
            return None
        result = dict(row)
        result['payload'] = Ledger._decode(result['payload'])
        result['evidence'] = Ledger._decode(result['evidence']) if result['evidence'] is not None else None
        return result

    def intent(self, operation_id: str, kind: str, payload: Record) -> Record:
        encoded = _json(payload)
        with self.transaction() as connection:
            row = connection.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
            if row is not None:
                if row['kind'] != kind or row['payload'] != encoded:
                    raise OperationConflict('operation identity already has a different intent')
                return self._record(row)
            connection.execute("INSERT INTO operations VALUES (?,?,?,'pending',NULL,1)", (operation_id, kind, encoded))
            connection.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)', ('intent', _json({'operation_id': operation_id, 'kind': kind, 'payload': payload, 'schema_version': 1})))
            return self._record(connection.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone())

    def finish(self, receipt: Receipt) -> None:
        if receipt.status not in ('done', 'failed', 'uncertain', 'blocked'):
            raise ValueError('invalid receipt status')
        encoded = _json(receipt.evidence)
        with self.transaction() as connection:
            row = connection.execute('SELECT * FROM operations WHERE operation_id=?', (receipt.operation_id,)).fetchone()
            if row is None:
                raise OperationConflict('receipt requires a durable intent')
            if row['status'] != 'pending':
                if row['status'] == receipt.status and row['evidence'] == encoded:
                    return
                raise OperationConflict('terminal receipt is immutable')
            connection.execute('UPDATE operations SET status=?, evidence=? WHERE operation_id=?', (receipt.status, encoded, receipt.operation_id))
            connection.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)', ('receipt', _json({'operation_id': receipt.operation_id, 'status': receipt.status, 'evidence': receipt.evidence, 'schema_version': 1})))

    def get(self, operation_id: str) -> Record | None:
        with self.transaction() as connection:
            return self._record(connection.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone())

    def append_event(self, kind: str, payload: Record) -> int:
        with self.transaction() as connection:
            cursor = connection.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)', (kind, _json(payload)))
            return cursor.lastrowid
