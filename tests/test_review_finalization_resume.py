"""Review persistence and its remaining summary phase survive a budget pause."""
import uuid

import pytest
from langgraph.graph import START, END, StateGraph
from langgraph.checkpoint.memory import InMemorySaver

from myink.db import tenant_session
from myink.models import Chapter
from myink.task_budget import TaskBudgetPaused
from myink.workflow import runner, nodes
from myink.workflow.state import ChapterState
from myink.worker import processor


def test_review_resume_retries_summary_after_chapter_was_confirmed(temp_project, monkeypatch):
    tid = str(uuid.uuid4())
    builder = StateGraph(ChapterState)
    builder.add_node("persist", lambda state: {"persisted": True, "needs_review": True})
    builder.add_node("summarize", lambda state: {})
    builder.add_edge(START, "persist")
    builder.add_edge("persist", "summarize")
    builder.add_edge("summarize", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": tid}}
    graph.invoke({"project_id": temp_project, "chapter_seq": 1, "task_id": tid,
                  "draft": "已审核正文", "candidates": []}, config)
    with tenant_session(temp_project) as db:
        db.add(Chapter(project_id=temp_project, chapter_seq=1, status="awaiting_review", content="已审核正文"))
    for module in (runner, processor):
        monkeypatch.setattr(module, "get_graphs", lambda: (graph, None))
        monkeypatch.setattr(module, "budget_managed", lambda: True)
    summaries = []

    def summarize(state):
        summaries.append(state["draft"])
        if len(summaries) == 1:
            raise TaskBudgetPaused("request_limit", "summarize")
        return {}

    monkeypatch.setattr(nodes, "node_summarize", summarize)
    body = {"project_id": temp_project, "task_id": tid, "task_type": "chapter_resume", "payload": {"seq": 1}}
    with pytest.raises(TaskBudgetPaused):
        processor._dispatch(body)
    with tenant_session(temp_project) as db:
        assert db.query(Chapter).one().status == "confirmed"
        version = db.query(Chapter).one().version
    result = processor._dispatch(body)
    assert summaries == ["已审核正文", "已审核正文"]
    assert result["needs_review"] is False
    assert graph.get_state(config).values["needs_review"] is False
    # A later redelivery is complete and does not summarize or persist again.
    assert processor._dispatch(body)["needs_review"] is False
    assert len(summaries) == 2
    with tenant_session(temp_project) as db:
        assert db.query(Chapter).one().version == version


def _completed_summary_graph(pid, tid, draft, **extra):
    builder = StateGraph(ChapterState)
    builder.add_node("summarize", lambda state: {})
    builder.add_edge(START, "summarize")
    builder.add_edge("summarize", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    graph.invoke({"project_id": pid, "chapter_seq": 1, "task_id": tid,
                  "draft": draft, "candidates": [], **extra}, {"configurable": {"thread_id": tid}})
    return graph


@pytest.mark.parametrize("restored_content", ["旧稿：张三生还", "新稿：张三死亡"])
def test_paused_review_summary_preserves_history_restore(temp_project, monkeypatch, restored_content):
    from myink.api.routes_chapters import restore_chapter_version
    from myink.models import ChapterVersion
    draft, tid = "新稿：张三死亡", str(uuid.uuid4())
    graph = _completed_summary_graph(temp_project, tid, draft, needs_review=True)
    with tenant_session(temp_project) as db:
        chapter = Chapter(project_id=temp_project, chapter_seq=1, content=draft,
                          status="awaiting_review", version=2)
        db.add(chapter)
        db.flush()
        cid = chapter.id
        db.add(ChapterVersion(project_id=temp_project, chapter_id=cid, version=1,
                              content=restored_content, summary="历史摘要：张三生还"))
    for module in (runner, processor):
        monkeypatch.setattr(module, "get_graphs", lambda: (graph, None))
        monkeypatch.setattr(module, "budget_managed", lambda: True)
    monkeypatch.setattr(nodes, "make_chain", lambda *a, **kw: None)
    calls = []
    def summary_llm(*args, **kwargs):
        from myink.providers.base import ModelResponse
        calls.append(args[5])
        if len(calls) == 1:
            raise TaskBudgetPaused("request_limit", "summarize")
        return ModelResponse(content='{"summary":"旧 checkpoint 摘要：张三死亡"}', model_id="stub"), None
    monkeypatch.setattr(nodes, "_llm", summary_llm)
    body = {"project_id": temp_project, "task_id": tid, "task_type": "chapter_resume", "payload": {"seq": 1}}
    with pytest.raises(TaskBudgetPaused):
        processor._dispatch(body)
    restore_chapter_version(temp_project, str(cid), 1)
    result = processor._dispatch(body)
    assert not result["needs_review"]
    with tenant_session(temp_project) as db:
        current = db.get(Chapter, cid)
        assert current.content == restored_content
        assert current.summary == "历史摘要：张三生还"
        assert current.version == 3
    assert len(calls) == 1, "stale resumed summary must not call the model again"


def test_legacy_pending_summary_without_version_keeps_existing_summary(temp_project, monkeypatch):
    from myink.providers.base import ModelResponse
    tid, draft = str(uuid.uuid4()), "同一正文"
    graph = _completed_summary_graph(temp_project, tid, draft, review_finalization_pending=True, needs_review=False)
    monkeypatch.setattr(runner, "get_graphs", lambda: (graph, None))
    monkeypatch.setattr(nodes, "make_chain", lambda *a, **kw: None)
    monkeypatch.setattr(nodes, "_llm", lambda *a, **kw: (ModelResponse(content='{"summary":"旧任务结果"}', model_id="stub"), None))
    with tenant_session(temp_project) as db:
        db.add(Chapter(project_id=temp_project, chapter_seq=1, content=draft, summary="已恢复的摘要",
                       version=3, status="confirmed"))
    result = runner.finalize_chapter_review(project_id=temp_project, task_id=tid, chapter_seq=1)
    assert not result["review_finalization_pending"]
    with tenant_session(temp_project) as db:
        assert db.query(Chapter).one().summary == "已恢复的摘要"
