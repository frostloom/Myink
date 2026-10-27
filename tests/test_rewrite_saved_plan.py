"""Explicit rewrite must reuse the chapter's persisted plan through the real graph."""
import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from myink.db import tenant_session
from myink.models import AgentRun, Chapter
from myink.providers.base import FallbackChain, ModelProvider, ModelResponse
from myink.workflow import nodes, runner
from myink.workflow.chapter_graph import build_chapter_graph


class RewriteProvider(ModelProvider):
    def __init__(self):
        self.calls = []
        self.writer_messages = []

    def name(self):
        return "rewrite-plan-test"

    def generate(self, messages, *, model_id, **kwargs):
        system = messages[0]["content"]
        if "出场人物 Agent" in system or "规划 Agent" in system:
            self.calls.append("planner")
            raise AssertionError("explicit rewrite must never invoke Planner")
        if "记忆抽取" in system:
            node, content = "extract", '{"candidates":[]}'
        elif "审核中枢" in system:
            node, content = "audit", '{"verdict":"pass","findings":[],"reasons":[],"confidence":1}'
        elif "章节摘要" in system:
            node, content = "summarize", '{"summary":"重新写好的正文"}'
        else:
            node, content = "write", "重新写好的正文。" * 100
            self.writer_messages.append(messages)
        self.calls.append(node)
        return ModelResponse(content=content, model_id=model_id)


def stored_plan(pid, goal="保存的批准计划"):
    return {"project_id": pid, "chapter_seq": 1, "goals": [goal], "scenes": [],
            "characters": [], "hooks_to_plant": [], "hooks_to_resolve": [],
            "expected_events": ["保留原来的情节"], "hard_constraints": []}


def prepare(monkeypatch):
    provider = RewriteProvider()
    monkeypatch.setattr(nodes, "make_chain", lambda *a, **kw: FallbackChain(provider, ["rewrite-plan-test"]))
    graph = build_chapter_graph(checkpointer=InMemorySaver())
    monkeypatch.setattr(runner, "get_graphs", lambda: (graph, None))
    return provider


@pytest.mark.parametrize("mode", ["auto", "manual"])
@pytest.mark.parametrize("original_task", ["original", "batch:ch1"])
def test_generate_rewrite_reuses_approved_saved_plan(temp_project, monkeypatch, fake_embedder, mode, original_task):
    provider = prepare(monkeypatch)
    plan = stored_plan(temp_project)
    with tenant_session(temp_project) as db:
        db.add(Chapter(project_id=uuid.UUID(temp_project), chapter_seq=1, content="旧正文", status="confirmed"))
        for node, detail in [
            ("plan_chapter", {"plan": stored_plan(temp_project, "批准前计划"), "plan_attempt": 1}),
            ("plan_review", {"approved_plan": plan, "plan_attempt": 1}),
            ("persist", {"status": "auto_confirm"}),
        ]:
            db.add(AgentRun(project_id=uuid.UUID(temp_project), task_id=original_task, node=node, detail=detail))
        db.flush()
        # A failed later task must not replace the plan of the saved chapter.
        db.add(AgentRun(project_id=uuid.UUID(temp_project), task_id="failed-later", node="plan_chapter",
                        detail={"plan": stored_plan(temp_project, "未保存的新计划")}))
        other_plan = {**stored_plan(temp_project, "第二章已保存计划"), "chapter_seq": 2}
        db.add(AgentRun(project_id=uuid.UUID(temp_project), task_id="batch:ch2", node="persist", detail={"plan": other_plan}))
    result = runner.generate_chapter(project_id=temp_project, chapter_seq=1, task_id=str(uuid.uuid4()),
                                     rewrite=True, writing_mode=mode)
    assert not result.get("error"), result.get("error")
    assert not result.get("__interrupt__")
    assert result["plan"] == plan
    assert "planner" not in provider.calls
    assert provider.writer_messages and "保存的批准计划" in str(provider.writer_messages)
    assert "未保存的新计划" not in str(provider.writer_messages)
    assert result.get("persisted") is True
    with tenant_session(temp_project) as db:
        persisted = db.query(AgentRun).filter_by(project_id=uuid.UUID(temp_project), node="persist").order_by(AgentRun.id.desc()).first()
        assert persisted.detail["plan"] == plan


def test_rewrite_without_saved_plan_preserves_old_body_and_explains_missing_plan(temp_project, monkeypatch):
    provider = prepare(monkeypatch)
    with tenant_session(temp_project) as db:
        db.add(Chapter(project_id=uuid.UUID(temp_project), chapter_seq=1, content="历史正文不可丢", status="confirmed"))
    result = runner.generate_chapter(project_id=temp_project, chapter_seq=1, task_id=str(uuid.uuid4()), rewrite=True)
    assert "缺少已保存的章节计划" in result.get("error", "")
    assert provider.calls == []
    with tenant_session(temp_project) as db:
        chapter = db.query(Chapter).filter_by(project_id=uuid.UUID(temp_project), chapter_seq=1).one()
        assert chapter.content == "历史正文不可丢" and chapter.status == "confirmed"


def test_explicit_rewrite_does_not_silently_replan_after_audit():
    from myink.workflow.chapter_graph import route_after_audit
    assert route_after_audit({"rewrite": True, "task_id": "rewrite", "audit_verdict": {
        "verdict": "replan", "replan_target": "chapter"}}) == "needs_review"


@pytest.mark.parametrize("mode", ["auto", "manual"])
def test_explicit_replan_recovers_legacy_chapter_and_keeps_intent_on_resume(temp_project, monkeypatch, fake_embedder, mode):
    import json
    prepare(monkeypatch)
    class ReplanProvider(RewriteProvider):
        def generate(self, messages, *, model_id, **kwargs):
            system = messages[0]["content"]
            if "出场人物 Agent" in system:
                self.calls.append("planner")
                return ModelResponse(content='{"cast":["林川"],"locations":["河畔"]}', model_id=model_id)
            if "规划 Agent" in system:
                self.calls.append("planner")
                return ModelResponse(content=json.dumps(stored_plan(temp_project, "显式重新规划的新计划")), model_id=model_id)
            return super().generate(messages, model_id=model_id, **kwargs)
    provider = ReplanProvider()
    monkeypatch.setattr(nodes, "make_chain", lambda *a, **kw: FallbackChain(provider, ["rewrite-plan-test"]))
    with tenant_session(temp_project) as db:
        db.add(Chapter(project_id=uuid.UUID(temp_project), chapter_seq=1, content="没有历史计划的正文", status="confirmed"))
    tid = str(uuid.uuid4())
    result = runner.generate_chapter(project_id=temp_project, chapter_seq=1, task_id=tid, rewrite=True, replan=True, writing_mode=mode)
    assert provider.calls.count("planner") == 2
    if mode == "manual":
        assert result.get("__interrupt__")
        assert result["replan_requested"] is True
        result = runner.resume_chapter_plan(project_id=temp_project, task_id=tid, approved_plan=result["plan"])
        assert provider.calls.count("planner") == 2
    assert not result.get("error"), result.get("error")
    assert result["replan_requested"] is True and result["persisted"] is True
    assert "显式重新规划的新计划" in str(provider.writer_messages)
