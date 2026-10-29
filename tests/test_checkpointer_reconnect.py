"""PG checkpointer 的连接生命周期测试。"""

from __future__ import annotations


def test_setup_waits_for_another_process_initializing_the_schema(tmp_path):
    """A second worker must not enter DDL while the first owns schema initialization."""
    import os
    import subprocess
    import sys
    import time
    from psycopg import Connection
    import myink.workflow.checkpointer as module

    import uuid
    table = 'checkpoint_lock_test_' + uuid.uuid4().hex
    started, migrated = tmp_path / 'started', tmp_path / 'migrated'
    program = '''
import sys
from pathlib import Path
import myink.workflow.checkpointer as module
from psycopg.conninfo import make_conninfo
module._CONN_STR = make_conninfo(module._CONN_STR, application_name=sys.argv[3])
class Saver:
    def __init__(self, connection): self.conn = connection
    def setup(self): Path(sys.argv[2]).touch()
module.PostgresSaver = Saver
Path(sys.argv[1]).touch()
saver = module.build_checkpointer()
saver.conn.close()
'''
    with Connection.connect(module._CONN_STR, autocommit=True) as lock:
        lock.execute(f'CREATE TABLE {table} (id integer)')
        lock.execute('SELECT pg_advisory_lock(728165, 1)')
        child = subprocess.Popen([sys.executable, '-c', program, str(started), str(migrated), table], env=os.environ.copy())
        try:
            deadline = time.monotonic() + 15
            while not started.exists():
                assert child.poll() is None, 'initializer exited before starting'
                assert time.monotonic() < deadline, 'initializer failed to start'
                time.sleep(0.02)
            # Observe the initializer connection, including the old blocking behavior.
            # Nonblocking polling must leave an idle, snapshot-free connection.
            while not lock.execute("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE application_name = %s AND (wait_event = 'advisory' OR (state = 'idle' AND query LIKE 'SELECT pg_try_advisory_lock%%')))", (table,)).fetchone()[0]:
                assert not migrated.exists(), 'second worker entered setup while initialization was locked'
                assert time.monotonic() < deadline, 'initializer did not wait for the schema lock'
                time.sleep(0.02)
            assert not migrated.exists()
            lock.execute("SET statement_timeout = '5s'")
            lock.execute(f'CREATE INDEX CONCURRENTLY {table}_idx ON {table}(id)')
            lock.execute('SELECT pg_advisory_unlock(728165, 1)')
            assert child.wait(timeout=15) == 0
            assert migrated.exists()
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=10)
            lock.execute(f'DROP TABLE {table}')


def test_checkpointer_normalizes_localhost_for_background_pool_workers():
    from myink.db_url import normalize_localhost_database_url
    from myink.workflow.checkpointer import _psycopg_conn_str

    assert _psycopg_conn_str(
        "postgresql+psycopg://user:pass@localhost:5432/myink?sslmode=disable"
    ) == "postgresql://user:pass@127.0.0.1:5432/myink?sslmode=disable"
    assert _psycopg_conn_str(
        "postgresql+psycopg://user:pass@myink-postgres:5432/myink"
    ) == "postgresql://user:pass@myink-postgres:5432/myink"
    assert normalize_localhost_database_url(
        "postgresql+psycopg://user:pass@localhost:5432/myink"
    ) == "postgresql+psycopg://user:pass@127.0.0.1:5432/myink"


def test_failed_setup_releases_schema_lock_and_can_retry(monkeypatch):
    import pytest
    from psycopg import Connection
    import myink.workflow.checkpointer as module

    monkeypatch.setattr(module, '_build', {})
    original_setup = module.PostgresSaver.setup
    connections = []

    def fail_setup(saver):
        connections.append(saver.conn)
        raise RuntimeError('migration failed')

    monkeypatch.setattr(module.PostgresSaver, 'setup', fail_setup)
    with pytest.raises(RuntimeError, match='migration failed'):
        module.build_checkpointer()
    assert module._build == {}
    assert connections[0].closed
    with Connection.connect(module._CONN_STR, autocommit=True) as other:
        assert other.execute('SELECT pg_try_advisory_lock(728165, 1)').fetchone()[0]
    monkeypatch.setattr(module.PostgresSaver, 'setup', original_setup)
    saver = module.build_checkpointer()
    try:
        assert module.build_checkpointer() is saver
    finally:
        saver.conn.close()


def test_checkpointer_uses_health_checked_pool(monkeypatch):
    """长期缓存的 saver 必须通过池 checkout 健检，不能永久持有一个失效连接。"""
    import myink.workflow.checkpointer as module

    captured = {}

    from contextlib import contextmanager

    class FakeConnection:
        def execute(self, _sql):
            return self

        def fetchone(self):
            return {"acquired": True}

    class FakePool:
        @staticmethod
        def check_connection(connection):
            return connection

        def __init__(self, **kwargs):
            captured.update(kwargs)

        def wait(self):
            captured["waited"] = True

        @contextmanager
        def connection(self):
            yield FakeConnection()

        def close(self):
            captured["closed"] = True

    class FakeSaver:
        def __init__(self, connection):
            captured["connection"] = connection

        def setup(self):
            captured["setup"] = True

    module._build.clear()
    monkeypatch.setattr(module, "ConnectionPool", FakePool)
    monkeypatch.setattr(module, "PostgresSaver", FakeSaver)
    try:
        first = module.build_checkpointer()
        second = module.build_checkpointer()
    finally:
        module._build.clear()

    assert first is second
    assert captured["check"] is FakePool.check_connection
    assert captured["kwargs"]["autocommit"] is True
    assert captured["kwargs"]["prepare_threshold"] == 0
    assert captured["waited"] is True
    assert captured["setup"] is True
