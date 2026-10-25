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
