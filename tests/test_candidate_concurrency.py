"""Real PostgreSQL transactions serialize decisions on one pending candidate."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading

from fastapi import HTTPException

from myink.db import tenant_session
from myink.models import Fact, MemoryCandidate
from myink.workflow import nodes
from myink.api import routes_candidates


def _pending(pid):
    with tenant_session(pid) as db:
        candidate = MemoryCandidate(project_id=pid, source_chapter=1, kind="fact",
                                    payload={"content": "只能批准一次"})
        db.add(candidate)
        db.flush()
        return candidate.id


def test_concurrent_confirms_wait_before_persisting_memory(temp_project, fake_embedder, monkeypatch):
    cid = _pending(temp_project)
    ready, entered_persist = threading.Event(), threading.Event()
    real_persist = nodes._persist_candidates

    def second_persist(*args, **kwargs):
        entered_persist.set()
        return real_persist(*args, **kwargs)

    def second_confirm():
        with tenant_session(temp_project) as db:
            # Keep a stale identity-map row too: a locking query must refresh it.
            cached = db.get(MemoryCandidate, cid)
            assert cached.status == "pending"
            ready.set()
            return nodes.confirm_candidate(db, temp_project, cid) is not None

    with ThreadPoolExecutor(max_workers=1) as pool:
        with tenant_session(temp_project) as first:
            assert nodes.confirm_candidate(first, temp_project, cid) is not None
            first.flush()
            monkeypatch.setattr(nodes, "_persist_candidates", second_persist)
            future = pool.submit(second_confirm)
            try:
                assert ready.wait(5)
                assert not entered_persist.wait(.3), "second confirmation wrote before the first committed"
            finally:
                first.commit()
        assert future.result(timeout=5) is False
    with tenant_session(temp_project) as db:
        assert db.query(Fact).filter_by(content="只能批准一次").count() == 1
        assert db.get(MemoryCandidate, cid).status == "confirmed"


def test_reject_cannot_overwrite_an_inflight_confirmation(temp_project, fake_embedder, monkeypatch):
    cid = _pending(temp_project)
    ready = threading.Event()

    @contextmanager
    def cached_session(pid):
        with tenant_session(pid) as db:
            cached = db.get(MemoryCandidate, cid)
            assert cached.status == "pending"
            ready.set()
            yield db

    def reject():
        try:
            routes_candidates.reject_candidate(temp_project, str(cid))
        except HTTPException as exc:
            return exc.status_code
        return 200

    with ThreadPoolExecutor(max_workers=1) as pool:
        with tenant_session(temp_project) as first:
            assert nodes.confirm_candidate(first, temp_project, cid) is not None
            first.flush()
            monkeypatch.setattr(routes_candidates, "tenant_session", cached_session)
            future = pool.submit(reject)
            try:
                assert ready.wait(5)
            finally:
                first.commit()
        assert future.result(timeout=5) == 409
    with tenant_session(temp_project) as db:
        assert db.get(MemoryCandidate, cid).status == "confirmed"
        assert db.query(Fact).filter_by(content="只能批准一次").count() == 1
