import multiprocessing
import sqlite3
import time

import pytest

from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger, LedgerBlocked, OperationConflict


def race(path, queue, barrier):
    # Synchronize the actual fresh-file WAL transition, not process spawning.
    original_connect = sqlite3.connect

    class SynchronizedConnection(sqlite3.Connection):
        first_wal = True

        def execute(self, sql, parameters=()):
            if sql == 'PRAGMA journal_mode=WAL' and SynchronizedConnection.first_wal:
                SynchronizedConnection.first_wal = False
                barrier.wait(timeout=20)
            return super().execute(sql, parameters)

    def connect(*args, **kwargs):
        return original_connect(*args, **kwargs, factory=SynchronizedConnection)

    sqlite3.connect = connect
    try:
        queue.put(Ledger(path).intent('same', 'build', {'sha': 'abc'}))
    except Exception as exc:
        queue.put({'error': type(exc).__name__, 'cause': str(exc.__cause__),
                   'code': getattr(exc.__cause__, 'sqlite_errorcode', None)})


def test_intent_survives_restart(tmp_path):
    path = tmp_path / 'ledger.sqlite'
    Ledger(path).intent('build-1', 'build', {'sha': 'abc'})
    record = Ledger(path).get('build-1')
    assert record['status'] == 'pending'
    assert record['payload'] == {'sha': 'abc'}
    assert record['schema_version'] == 1


def test_done_is_immutable(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    ledger.intent('x', 'build', {})
    receipt = Receipt('x', 'done', {'image': 'a'})
    ledger.finish(receipt)
    ledger.finish(receipt)
    with pytest.raises(OperationConflict):
        ledger.finish(Receipt('x', 'failed', {}))
    assert ledger.get('x')['evidence'] == {'image': 'a'}


def test_disk_error_blocks_mutation(tmp_path):
    path = tmp_path / 'ledger.sqlite'
    ledger = Ledger(path)
    path.unlink()
    path.mkdir()
    effects = []
    with pytest.raises(LedgerBlocked):
        ledger.intent('x', 'build', {})
        effects.append('executed')
    assert effects == []


def test_conflicting_intent_and_missing_receipt(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    ledger.intent('x', 'build', {})
    with pytest.raises(OperationConflict):
        ledger.intent('x', 'other', {})
    with pytest.raises(OperationConflict):
        ledger.finish(Receipt('unknown', 'done', {}))


def test_transaction_rolls_back_and_audit_is_append_only(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    assert ledger.append_event('check', {'ok': True}) == 1
    with pytest.raises(RuntimeError):
        with ledger.transaction() as connection:
            connection.execute("INSERT INTO events(kind,payload,schema_version) VALUES ('x','{}',1)")
            raise RuntimeError('abort')
    with ledger.transaction() as connection:
        assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert connection.execute('PRAGMA synchronous').fetchone()[0] == 2
        assert connection.execute('SELECT count(*) FROM events').fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute('DELETE FROM events')


@pytest.mark.parametrize('damage', ['corrupt', 'version', 'schema'])
def test_invalid_database_fails_closed(tmp_path, damage):
    path = tmp_path / 'ledger.sqlite'
    Ledger(path)
    if damage == 'corrupt':
        path.write_bytes(b'not sqlite')
    else:
        with sqlite3.connect(path) as connection:
            connection.execute('PRAGMA user_version=2' if damage == 'version' else 'DROP TABLE events')
    with pytest.raises(LedgerBlocked):
        Ledger(path)


def test_two_processes_share_one_identity(tmp_path):
    path = tmp_path / 'ledger.sqlite'
    context = multiprocessing.get_context('spawn')
    queue = context.Queue()
    barrier = context.Barrier(2)
    processes = [context.Process(target=race, args=(path, queue, barrier)) for _ in range(2)]
    for process in processes:
        process.start()
    try:
        results = [queue.get(timeout=40) for _ in processes]
        for process in processes:
            process.join(40)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(5)
        queue.close()
        queue.join_thread()
    assert all(result.get('status') == 'pending' for result in results), results
    assert results[0] == results[1]
    with Ledger(path).transaction() as connection:
        assert connection.execute('SELECT count(*) FROM operations').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM events').fetchone()[0] == 1


def test_malformed_record_fails_closed(tmp_path):
    path = tmp_path / 'ledger.sqlite'
    ledger = Ledger(path)
    ledger.intent('x', 'build', {})
    with sqlite3.connect(path) as connection:
        trigger = connection.execute("SELECT sql FROM sqlite_master WHERE name='operations_identity'").fetchone()[0]
        connection.execute("DROP TRIGGER operations_identity")
        connection.execute("UPDATE operations SET payload='invalid'")
        connection.execute(trigger)
    with pytest.raises(LedgerBlocked):
        Ledger(path)


def test_cli_checks_storage_and_rejects_implicit_path(tmp_path, capsys, monkeypatch):
    from ops.pi import control
    # Simulate the approved lab root while exercising real temporary SQLite.
    monkeypatch.setattr(control, 'state_path_allowed', lambda state: state.is_absolute() and state == tmp_path)
    main = control.main
    assert main(['ledger-check', '--state-dir', 'relative']) == 1
    assert 'blocked' in capsys.readouterr().out
    assert main(['ledger-check', '--state-dir', str(tmp_path)]) == 0
    assert 'done' in capsys.readouterr().out
    (tmp_path / 'ledger.sqlite').write_bytes(b'broken')
    assert main(['ledger-check', '--state-dir', str(tmp_path)]) == 1
    assert 'blocked' in capsys.readouterr().out


def test_intent_identity_cannot_be_rewritten(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    ledger.intent('x', 'build', {'sha': 'a'})
    with ledger.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE operations SET payload='{}' WHERE operation_id='x'")
    assert ledger.get('x')['payload'] == {'sha': 'a'}



def test_replaced_safeguard_fails_closed(tmp_path):
    path = tmp_path / 'ledger.sqlite'
    Ledger(path)
    with sqlite3.connect(path) as connection:
        connection.execute('DROP TRIGGER events_no_delete')
        connection.execute('CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT 1; END')
    with pytest.raises(LedgerBlocked):
        Ledger(path)


def test_replacement_cannot_overwrite_audit_event(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    event_id = ledger.append_event('original', {'ok': True})
    with ledger.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                'INSERT OR REPLACE INTO events(id,kind,payload,schema_version) VALUES (?, ?, ?, 1)',
                (event_id, 'replaced', '{}'),
            )
    with ledger.transaction() as connection:
        row = connection.execute('SELECT kind,payload FROM events WHERE id=?', (event_id,)).fetchone()
        assert tuple(row) == ('original', '{"ok":true}')
        assert connection.execute('PRAGMA recursive_triggers').fetchone()[0] == 1


def test_replacement_cannot_reset_completed_operation(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    ledger.intent('x', 'build', {'sha': 'a'})
    ledger.finish(Receipt('x', 'done', {'image': 'a'}))
    with ledger.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT OR REPLACE INTO operations VALUES ('x','other','{}','pending',NULL,1)"
            )
    record = Ledger(tmp_path / 'ledger.sqlite').get('x')
    assert record['kind'] == 'build'
    assert record['payload'] == {'sha': 'a'}
    assert record['status'] == 'done'
    assert record['evidence'] == {'image': 'a'}


@pytest.mark.parametrize('path,platform,allowed', [('/mnt/e/tools/myink-pi/state', 'linux', True),
                                                ('/mnt/e/tools/../outside', 'linux', False),
                                                ('/mnt/evil/state', 'linux', False),
                                                ('/mnt/c/tools/state', 'linux', False),
                                                ('/tmp/state', 'linux', False),
                                                ('relative', 'linux', False),
                                                ('E:/tools/myink-pi/state', 'win32', True),
                                                ('E:relative', 'win32', False),
                                                ('C:/tools/state', 'win32', False)])
def test_cli_state_boundary_maps_only_e_drive(path, platform, allowed):
    from pathlib import PurePosixPath, PureWindowsPath
    from ops.pi.control import state_path_allowed
    candidate = PureWindowsPath(path) if platform == 'win32' else PurePosixPath(path)
    assert state_path_allowed(candidate, platform=platform) is allowed


@pytest.mark.parametrize('code', [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_LOCKED])
def test_initialization_failure_is_bounded_and_fails_closed(tmp_path, monkeypatch, code):
    original_connect = sqlite3.connect
    clock = [0.0]
    attempts = []
    effects = []
    failure = sqlite3.OperationalError('injected storage failure')
    failure.sqlite_errorcode = code

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql == 'PRAGMA journal_mode=WAL':
                attempts.append(clock[0])
                raise failure
            return super().execute(sql, parameters)

    def connect(*args, **kwargs):
        return original_connect(*args, **kwargs, factory=FailingConnection)

    def advance(delay):
        # Accelerate the clock only; no real 30-second wait or SQLite effects.
        clock[0] += 5

    monkeypatch.setattr(sqlite3, 'connect', connect)
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(time, 'sleep', advance)
    with pytest.raises(LedgerBlocked) as caught:
        ledger = Ledger(tmp_path / 'ledger.sqlite')
        ledger.intent('unsafe', 'build', {})
        effects.append('executed')
    assert caught.value.__cause__ is failure
    assert effects == []
    if code == sqlite3.SQLITE_BUSY:
        assert len(attempts) > 1
        assert clock[0] == 30
        assert max(attempts) <= 30
    else:
        assert attempts == [0.0]
        assert clock[0] == 0
    with original_connect(tmp_path / 'ledger.sqlite') as connection:
        assert connection.execute('SELECT count(*) FROM sqlite_master').fetchone()[0] == 0


def test_busy_transaction_body_is_not_retried(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    entries = []
    failure = sqlite3.OperationalError('database is locked')
    failure.sqlite_errorcode = sqlite3.SQLITE_BUSY
    with pytest.raises(LedgerBlocked) as caught:
        with ledger.transaction() as connection:
            entries.append('entered')
            connection.execute("INSERT INTO events(kind,payload,schema_version) VALUES ('x','{}',1)")
            raise failure
    assert caught.value.__cause__ is failure
    assert entries == ['entered']
    with ledger.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM events').fetchone()[0] == 0



def test_wal_recovery_keeps_remaining_contention_budget(tmp_path, monkeypatch):
    original_connect = sqlite3.connect
    clock = [0.0]
    failure = sqlite3.OperationalError('database is locked')
    failure.sqlite_errorcode = sqlite3.SQLITE_BUSY

    class ContendedConnection(sqlite3.Connection):
        first_wal = True

        def execute(self, sql, parameters=()):
            if sql == 'PRAGMA journal_mode=WAL' and self.first_wal:
                self.first_wal = False
                raise failure
            return super().execute(sql, parameters)

    def connect(*args, **kwargs):
        return original_connect(*args, **kwargs, factory=ContendedConnection)

    def advance(delay):
        clock[0] += 25

    monkeypatch.setattr(sqlite3, 'connect', connect)
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(time, 'sleep', advance)
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    with ledger.transaction() as connection:
        # A successful WAL retry must not grant BEGIN another 30 seconds.
        assert connection.execute('PRAGMA busy_timeout').fetchone()[0] == 5000
        assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        connection.execute("INSERT INTO events(kind,payload,schema_version) VALUES ('recovered','{}',1)")
    with original_connect(tmp_path / 'ledger.sqlite') as connection:
        assert connection.execute('SELECT kind FROM events').fetchall() == [('recovered',)]
