import multiprocessing
import sqlite3

import pytest

from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger, LedgerBlocked, OperationConflict


def race(path, queue):
    try:
        queue.put(Ledger(path).intent('same', 'build', {'sha': 'abc'}))
    except Exception as exc:
        queue.put(str(exc))


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
    processes = [context.Process(target=race, args=(path, queue)) for _ in range(2)]
    for process in processes:
        process.start()
    results = [queue.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    assert all(isinstance(result, dict) for result in results), results
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


def test_cli_checks_storage_and_rejects_implicit_path(tmp_path, capsys):
    from ops.pi.control import main
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
