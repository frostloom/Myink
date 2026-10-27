"""Explicit replan intent must survive API admission and worker dispatch."""
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from myink.api import routes_tasks
from myink.worker import processor


def test_api_enqueues_explicit_replan_without_changing_rewrite_admission(monkeypatch):
    captured = {}
    monkeypatch.setattr(routes_tasks, "_assert_writable", lambda *a, **kw: None)
    monkeypatch.setattr(routes_tasks, "_platform_chapter_max", lambda *_: 0)
    monkeypatch.setattr(routes_tasks, "enqueue", lambda **kw: captured.update(kw) or {"task_id": "t"})
    routes_tasks.generate_chapter("p", "c", routes_tasks.ChapterGenerateBody(seq=1, rewrite=True, replan=True),
                                 SimpleNamespace(id="u", tier="pro"))
    assert captured["payload"]["rewrite"] is True
    assert captured["payload"]["replan"] is True


def test_api_rejects_replan_without_existing_chapter_rewrite(monkeypatch):
    monkeypatch.setattr(routes_tasks, "_assert_writable", lambda *a, **kw: None)
    monkeypatch.setattr(routes_tasks, "_platform_chapter_max", lambda *_: 0)
    monkeypatch.setattr(routes_tasks, "enqueue", lambda **kw: pytest.fail("invalid replan reached admission"))
    with pytest.raises(HTTPException) as exc:
        routes_tasks.generate_chapter("p", "c", routes_tasks.ChapterGenerateBody(seq=1, replan=True),
                                     SimpleNamespace(id="u", tier="pro"))
    assert exc.value.status_code == 400


def test_worker_dispatch_preserves_explicit_replan(monkeypatch):
    captured = {}
    monkeypatch.setattr(processor, "budget_managed", lambda: False)
    monkeypatch.setattr(processor, "_guard_write_order", lambda *a, **kw: None)
    monkeypatch.setattr(processor, "generate_chapter", lambda **kw: captured.update(kw) or {})
    processor._dispatch({"project_id": "p", "task_id": "t", "task_type": "chapter_generate",
                         "payload": {"seq": 1, "rewrite": True, "replan": True}})
    assert captured["rewrite"] is True and captured["replan"] is True


def test_runner_keeps_explicit_replan_in_checkpoint_input(monkeypatch):
    from myink.workflow import runner
    captured = {}
    class Graph:
        def invoke(self, state, **kwargs):
            captured.update(state)
            return state
    monkeypatch.setattr(runner, "get_graphs", lambda: (Graph(), None))
    monkeypatch.setattr(runner, "budget_managed", lambda: False)
    monkeypatch.setattr(runner, "_finish_chapter_result", lambda *a: None)
    runner.generate_chapter(project_id="p", chapter_seq=1, task_id="t", rewrite=True, replan=True)
    assert captured["rewrite"] is True and captured["replan_requested"] is True


def test_explicit_replan_can_still_follow_audit_replan_route():
    from myink.workflow.chapter_graph import route_after_audit
    assert route_after_audit({"rewrite": True, "replan_requested": True, "task_id": "t",
        "audit_verdict": {"verdict": "replan", "replan_target": "chapter"}}) == "replan_chapter"
