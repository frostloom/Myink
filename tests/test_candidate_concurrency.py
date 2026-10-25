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


def test_concurrent_corrections_create_one_pending_proposal(temp_project):
    import uuid
    from concurrent.futures import TimeoutError
    from myink.memory import correction
    ready = threading.Event()
    def correct(db, confidence):
        return correction.correct_chapter_memory(db, project_id=uuid.UUID(temp_project), chapter_seq=1,
            new_candidates=[{"kind": "fact", "payload": {"content": "并发校正事实", "confidence": confidence}}])
    def second():
        with tenant_session(temp_project) as db:
            ready.set()
            return correct(db, .8)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with tenant_session(temp_project) as first:
            assert correct(first, .9)["pool"]["add_to_pool"] == 1
            first.flush()
            future = pool.submit(second)
            try:
                assert ready.wait(5)
                try:
                    future.result(timeout=.3)
                except TimeoutError:
                    pass
                else:
                    raise AssertionError("second correction completed before the first committed")
            finally:
                first.commit()
        assert future.result(timeout=5)["pool"]["add_to_pool"] == 0
    with tenant_session(temp_project) as db:
        assert db.query(MemoryCandidate).filter_by(status="pending").count() == 1


def test_correction_lock_allows_unrelated_chapter_candidate_inserts(temp_project):
    import uuid
    from myink.memory import correction
    def correct():
        with tenant_session(temp_project) as db:
            return correction.correct_chapter_memory(db, project_id=uuid.UUID(temp_project), chapter_seq=1,
                new_candidates=[{"kind": "fact", "payload": {"content": "本章校正"}}])
    with ThreadPoolExecutor(max_workers=1) as pool:
        with tenant_session(temp_project) as writer:
            writer.add(MemoryCandidate(project_id=temp_project, source_chapter=99, kind="fact",
                                       payload={"content": "另一章节正在写入"}))
            writer.flush()  # The actual FK check holds a project KEY SHARE lock.
            future = pool.submit(correct)
            try:
                assert future.result(timeout=1)["pool"]["add_to_pool"] == 1
            finally:
                writer.commit()
