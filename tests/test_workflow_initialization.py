"""Concurrent callers must see one complete workflow initialization."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event

import pytest


def test_concurrent_checkpointer_callers_share_one_pool(monkeypatch):
    from myink.workflow import checkpointer as module

    monkeypatch.setattr(module, '_build', {})
    first_setup, release, second_pool, attempting = Event(), Event(), Event(), Event()
    pools = []

    class Pool:
        check_connection = staticmethod(lambda conn: None)

        def __init__(self, **kwargs):
            pools.append(self)
            if len(pools) > 1:
                second_pool.set()

        def wait(self): pass
        def close(self): pass

        @contextmanager
        def connection(self):
            yield self

        def execute(self, sql): return self
        def fetchone(self): return {"acquired": True}

    class Saver:
        def __init__(self, conn): self.conn = conn

        def setup(self):
            first_setup.set()
            assert release.wait(5)

    monkeypatch.setattr(module, 'ConnectionPool', Pool)
    monkeypatch.setattr(module, 'PostgresSaver', Saver)

    def second():
        attempting.set()
        return module.build_checkpointer()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(module.build_checkpointer)
        try:
            assert first_setup.wait(5)
            other = executor.submit(second)
            assert attempting.wait(5)
            second_pool.wait(0.2)
        finally:
            release.set()
        assert first.result() is other.result()
        assert len(pools) == 1


def test_graphs_are_not_published_until_both_are_compiled(monkeypatch):
    from myink.workflow import runner

    monkeypatch.setattr(runner, '_chapter_graph', None)
    monkeypatch.setattr(runner, '_batch_graph', None)
    chapter, batch = object(), object()
    entered, release, attempting = Event(), Event(), Event()
    monkeypatch.setattr(runner, 'build_checkpointer', lambda: object())
    monkeypatch.setattr(runner, 'build_chapter_graph', lambda **kwargs: chapter)

    def build_batch(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return batch

    monkeypatch.setattr(runner, 'build_batch_graph', build_batch)

    def second():
        attempting.set()
        return runner.get_graphs()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(runner.get_graphs)
        try:
            assert entered.wait(5)
            other = executor.submit(second)
            assert attempting.wait(5)
            # Before the second graph exists no caller may observe a half pair.
            assert runner._chapter_graph is None
            assert runner._batch_graph is None
        finally:
            release.set()
        assert first.result() == other.result() == (chapter, batch)


def test_failed_batch_compilation_can_retry_without_partial_cache(monkeypatch):
    from myink.workflow import runner

    monkeypatch.setattr(runner, '_chapter_graph', None)
    monkeypatch.setattr(runner, '_batch_graph', None)
    chapter, batch = object(), object()
    monkeypatch.setattr(runner, 'build_checkpointer', lambda: object())
    monkeypatch.setattr(runner, 'build_chapter_graph', lambda **kwargs: chapter)

    def fail(*args, **kwargs): raise RuntimeError('batch compilation failed')

    monkeypatch.setattr(runner, 'build_batch_graph', fail)
    with pytest.raises(RuntimeError, match='batch compilation failed'):
        runner.get_graphs()
    monkeypatch.setattr(runner, 'build_batch_graph', lambda *args, **kwargs: batch)
    assert runner.get_graphs() == (chapter, batch)
