"""Exercise real graph checkpoints and short stages with durable accounting."""
import uuid
from collections import Counter

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from myink.db import tenant_session
from myink.models.task_budget import TaskBudget
from myink.providers.base import ModelProvider, ModelResponse, FallbackChain
from myink.task_budget import (TaskBudgetPaused, bind_task_budget, budget_view,
                               ensure_task_budget, reserve_attempt, finish_attempt)
from myink.workflow import nodes, runner, short_runner
from test_task_budget import budget_task  # noqa: F401


class MeteredStub(ModelProvider):
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = 0
    def name(self):
        return "metered-stub"
    def generate(self, messages, *, model_id, max_tokens=None, **kwargs):
        permit = reserve_attempt(model_id, messages, max_tokens or 20)
        self.calls += 1
        response = ModelResponse(content=next(self.replies), model_id=model_id,
                                 input_tokens=10, output_tokens=10)
        finish_attempt(permit, response)
        return response


def _extend(tid, pid, limit=20):
    with tenant_session(pid) as db:
        budget = db.get(TaskBudget, uuid.UUID(tid))
        budget.limits = {**budget.limits, "max_requests": limit}


def test_real_chapter_checkpoint_resumes_after_write(budget_task, monkeypatch):
    from myink.workflow.chapter_graph import build_chapter_graph
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests": 1})
    provider = MeteredStub(["draft", "approved"])
    chain = FallbackChain(provider, ["deepseek-v4-flash"])
    counts = Counter()
    def write(state):
        counts["write"] += 1
        return {"draft": chain.generate([{"role": "user", "content": "write"}], max_tokens=20).content}
    def audit(state):
        chain.generate([{"role": "user", "content": state["draft"]}], max_tokens=20)
        return {"audit_verdict": {"verdict": "pass"}}
    monkeypatch.setattr(nodes, "node_write", write)
    monkeypatch.setattr(nodes, "node_audit", audit)
    for name in ("extract", "validate", "persist", "summarize"):
        monkeypatch.setattr(nodes, "node_"+name, lambda state: {})
    graph = build_chapter_graph(InMemorySaver(), entry="write")
    state = {"project_id": pid, "task_id": tid, "chapter_seq": 1}
    config = {"configurable": {"thread_id": tid}}
    with bind_task_budget(tid, "first"):
        with pytest.raises(TaskBudgetPaused):
            graph.invoke(state, config)
    assert graph.get_state(config).next == ("audit",)
    _extend(tid, pid)
    with bind_task_budget(tid, "second"):
        result = runner.resume_thread(graph, tid, state)
    assert result["draft"] == "draft"
    assert counts["write"] == 1
    assert provider.calls == 2
    assert budget_view(tid)["requests_used"] == 2


@pytest.mark.parametrize("limit", [1, 2])
def test_short_stages_survive_pause_and_restart(budget_task, monkeypatch, limit):
    from myink.short.form import ShortParams
    from test_short_runner import _tagged, _review
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests": limit})
    provider = MeteredStub([_tagged(1), _review("revise", "tighten"), _tagged(1, tag="revised")])
    chain = FallbackChain(provider, ["deepseek-v4-flash"])
    monkeypatch.setattr(short_runner, "make_chain", lambda *args, **kwargs: chain)
    counts = Counter()
    original_call = short_runner._call
    def tracked(*args, **kwargs):
        counts[kwargs["node"]] += 1
        return original_call(*args, **kwargs)
    monkeypatch.setattr(short_runner, "_call", tracked)
    form = ShortParams.resolve(1, 1000)
    with bind_task_budget(tid, "first"):
        with pytest.raises(TaskBudgetPaused):
            short_runner.run_short_story(project_id=pid, task_id=tid, form=form)
    _extend(tid, pid)
    with bind_task_budget(tid, "restarted"):
        result = short_runner.resume_short_story(project_id=pid, task_id=tid, form=form)
    assert "revised" in result["chapters"][0]["body"]
    assert counts["short_write"] == 1
    if limit == 2:
        assert counts["short_review"] == 1
    assert provider.calls == 3
    assert budget_view(tid)["requests_used"] == 3


def test_tool_loop_reuses_paid_result_and_read_result(budget_task, monkeypatch):
    import json
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests": 1})
    class ToolStub(MeteredStub):
        def generate(self, messages, **kwargs):
            response = super().generate(messages, **kwargs)
            if self.calls == 1:
                response.tool_calls = [{"id": "call1", "name": "inspect_facts", "arguments": {}}]
            return response
    provider = ToolStub(["checking", '{"verdict":"pass"}'])
    chain = FallbackChain(provider, ["deepseek-v4-flash"])
    counts = Counter()
    def execute(*args):
        counts["tool"] += 1
        return json.dumps({"facts": []})
    monkeypatch.setattr(nodes, "execute_tool", execute)
    from dataclasses import replace
    monkeypatch.setattr(nodes, "settings", replace(nodes.settings, max_tool_calls=1))
    state = {"project_id": pid, "task_id": tid, "chapter_seq": 1}
    def run():
        with tenant_session(pid) as db:
            return nodes._llm(db, state, "audit", "Audit", chain,
                              [{"role":"user", "content":"check"}], tools=[{"type":"function"}])
    with bind_task_budget(tid, "first"):
        with pytest.raises(TaskBudgetPaused):
            run()
    _extend(tid, pid)
    with bind_task_budget(tid, "second"):
        response, trace = run()
    assert response.content == '{"verdict":"pass"}'
    assert counts["tool"] == 1
    assert provider.calls == 2
    assert len(trace) == 1


def test_batch_child_pause_and_final_reflexion_share_root(budget_task, monkeypatch):
    from myink.workflow.chapter_graph import build_chapter_graph
    from myink.workflow import batch_graph as batch
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests": 3})
    provider = MeteredStub(["draft1", "ok1", "draft2", "ok2", "lesson"])
    chain = FallbackChain(provider, ["deepseek-v4-flash"])
    counts = Counter()
    def write(state):
        counts[state["chapter_seq"]] += 1
        return {"draft": chain.generate([{"role":"user", "content":f"write{state['chapter_seq']}"}], max_tokens=20).content}
    def audit(state):
        chain.generate([{"role":"user", "content":state["draft"]}], max_tokens=20)
        return {"audit_verdict":{"verdict":"pass"}}
    def reflexion(state):
        chain.generate([{"role":"user", "content":"reflexion"}], max_tokens=20)
        return {}
    monkeypatch.setattr(nodes, "node_write", write)
    monkeypatch.setattr(nodes, "node_audit", audit)
    for name in ("extract", "validate", "persist", "summarize"):
        monkeypatch.setattr(nodes, "node_"+name, lambda state: {})
    monkeypatch.setattr(batch, "node_batch_plan", lambda state: {"batch_plan":{"chapters":[{"seq":1},{"seq":2}]}})
    monkeypatch.setattr(batch, "node_reflexion", reflexion)
    monkeypatch.setattr(batch, "node_global_audit", lambda state: {})
    monkeypatch.setattr(batch, "node_batch_end", lambda state: {})
    cp = InMemorySaver()
    graph = batch.build_batch_graph(build_chapter_graph(cp, entry="write"), cp)
    state = {"project_id":pid,"batch_task_id":tid,"size":2,"position":0,"start_chapter":1}
    with bind_task_budget(tid, "first"):
        with pytest.raises(TaskBudgetPaused):
            graph.invoke(state, {"configurable":{"thread_id":tid}})
    _extend(tid, pid, 4)
    with bind_task_budget(tid, "second"):
        with pytest.raises(TaskBudgetPaused):
            runner.resume_thread(graph, tid, state)
    assert counts == {1: 1, 2: 1}
    _extend(tid, pid, 5)
    with bind_task_budget(tid, "third"):
        runner.resume_thread(graph, tid, state)
    assert counts == {1: 1, 2: 1}
    assert budget_view(tid)["requests_used"] == provider.calls == 5


def test_worker_budget_pause_is_terminal_without_retry(budget_task, monkeypatch):
    from myink.worker import processor
    from myink.models import Task
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests": 1})
    provider = MeteredStub(["draft", "bad-repeat"])
    chain = FallbackChain(provider, ["deepseek-v4-flash"])
    def dispatch(body):
        chain.generate([{"role":"user","content":"first"}], max_tokens=20)
        chain.generate([{"role":"user","content":"second"}], max_tokens=20)
        return {}
    monkeypatch.setattr(processor, "_dispatch", dispatch)
    body = {"task_id":tid,"project_id":pid,"user_id":uid,"task_type":"chapter_generate","payload":{"seq":1}}
    assert processor.process(body) == "terminal"
    with tenant_session(pid) as db:
        assert db.get(Task, uuid.UUID(tid)).status == "paused"
    assert budget_view(tid)["pause_reason"] == "request_limit"
    assert processor.process(body) == "skip"
    assert provider.calls == 1


def test_managed_short_persist_does_not_repeat_version(budget_task):
    from myink.models import Chapter
    from sqlalchemy import select
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {})
    result = {"chapters":[{"chapter_seq":1,"title":"one","body":"completed text"}]}
    with bind_task_budget(tid, "owner"):
        short_runner.persist_short_story(project_id=pid, result=result)
        short_runner.persist_short_story(project_id=pid, result=result)
    with tenant_session(pid) as db:
        chapter = db.scalar(select(Chapter).where(Chapter.project_id==uuid.UUID(pid), Chapter.chapter_seq==1))
        assert chapter.version == 1


def test_worker_cancellation_wins_budget_pause(budget_task, monkeypatch):
    from myink.worker import processor
    from myink.models import Task
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {})
    def dispatch(body):
        with tenant_session(pid) as db:
            db.get(Task, uuid.UUID(tid)).status = "cancelled"
        raise TaskBudgetPaused("request_limit", "audit")
    monkeypatch.setattr(processor, "_dispatch", dispatch)
    body = {"task_id":tid,"project_id":pid,"user_id":uid,"task_type":"chapter_generate","payload":{"seq":1}}
    assert processor.process(body) == "terminal"
    with tenant_session(pid) as db:
        assert db.get(Task, uuid.UUID(tid)).status == "cancelled"


def test_stale_worker_cannot_replay_cached_calls(budget_task):
    from myink.task_budget import release_budget, claim_budget, TaskBudgetUnavailable
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {})
    provider = MeteredStub(["draft", "repeated"])
    chain = FallbackChain(provider, ["deepseek-v4-flash"])
    from myink.task_budget import bind_budget_operation
    with bind_task_budget(tid, "old"), bind_budget_operation("write"):
        chain.generate([{"role":"user","content":"write"}], max_tokens=20)
        release_budget(tid, "old")
        claim_budget(tid, "new")
        try:
            with pytest.raises(TaskBudgetUnavailable):
                chain.generate([{"role":"user","content":"write"}], max_tokens=20)
        finally:
            release_budget(tid, "new")
    assert provider.calls == 1


def test_paused_task_cost_accumulation_is_incremental(budget_task):
    from datetime import date
    from myink.worker import processor
    from myink.worker.redis_client import get_redis, cost_key
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {})
    provider = MeteredStub(["first", "second"])
    chain = FallbackChain(provider, ["deepseek-v4-flash"])
    body = {"task_id":tid}
    redis = get_redis()
    key = cost_key(date.today().isoformat())
    before = float(redis.get(key) or 0)
    try:
        with bind_task_budget(tid, "first"):
            chain.generate([{"role":"user","content":"first"}], max_tokens=20)
        processor._accumulate_cost(body)
        processor._accumulate_cost(body)
        one = float(redis.get(key) or 0) - before
        with bind_task_budget(tid, "second"):
            chain.generate([{"role":"user","content":"second"}], max_tokens=20)
        processor._accumulate_cost(body)
        total = float(redis.get(key) or 0) - before
        assert one > 0
        assert total == pytest.approx(one * 2)
    finally:
        redis.delete(f"rate:taskcost:{tid}")


def test_cli_budget_pause_updates_task_status(budget_task):
    from myink.task_budget import budget_execution
    from myink.models import Task
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {})
    @budget_execution
    def command(*, task_id):
        raise TaskBudgetPaused("time_limit", "write")
    with pytest.raises(TaskBudgetPaused):
        command(task_id=tid)
    with tenant_session(pid) as db:
        assert db.get(Task, uuid.UUID(tid)).status == "paused"


def test_old_worker_cannot_pause_new_execution(budget_task):
    from myink.task_budget import claim_budget, release_budget, record_budget_pause, TaskBudgetUnavailable
    from myink.models import Task
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {})
    claim_budget(tid, "new-worker")
    try:
        status = record_budget_pause(tid, TaskBudgetUnavailable("lease lost"), expected_owner="old-worker")
        assert status == "superseded"
        with tenant_session(pid) as db:
            assert db.get(Task, uuid.UUID(tid)).status == "queued"
    finally:
        release_budget(tid, "new-worker")


def test_short_pause_keeps_completed_stage_run(budget_task, monkeypatch):
    from myink.models import AgentRun
    from sqlalchemy import select
    from myink.short.form import ShortParams
    from test_short_runner import _tagged
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests":1})
    provider = MeteredStub([_tagged(1)])
    chain = FallbackChain(provider, ["deepseek-v4-flash"])
    monkeypatch.setattr(short_runner, "make_chain", lambda *args, **kwargs:chain)
    with bind_task_budget(tid, "first"):
        with pytest.raises(TaskBudgetPaused):
            short_runner.run_short_story(project_id=pid, task_id=tid, form=ShortParams.resolve(1,1000))
    with tenant_session(pid) as db:
        runs = db.scalars(select(AgentRun).where(AgentRun.task_id==tid)).all()
        assert [run.node for run in runs] == ["short_write"]


def test_persist_receipt_covers_commit_before_checkpoint(budget_task):
    from myink.models import Chapter, AgentRun
    from sqlalchemy import select
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {})
    state = {"task_id":tid, "project_id":pid, "chapter_seq":1,
             "draft":"completed draft", "candidates":[], "audit_verdict":{"verdict":"pass"}}
    with bind_task_budget(tid, "owner"):
        nodes.node_persist(state)
        nodes.node_persist(state)  # replay after database commit but before graph checkpoint
    with tenant_session(pid) as db:
        chapter = db.scalar(select(Chapter).where(Chapter.project_id==uuid.UUID(pid),Chapter.chapter_seq==1))
        assert chapter.version == 1
        runs = db.scalars(select(AgentRun).where(AgentRun.task_id==tid,AgentRun.node=="persist")).all()
        assert len(runs) == 1


def test_released_new_owner_fences_old_pause_report(budget_task):
    from myink.task_budget import claim_budget,release_budget,record_budget_pause,TaskBudgetUnavailable
    from myink.models import Task
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{})
    claim_budget(tid,"new");release_budget(tid,"new")
    with tenant_session(pid) as db:
        db.get(Task,uuid.UUID(tid)).status="done"
    assert record_budget_pause(tid,TaskBudgetUnavailable("old"),expected_owner="old") == "superseded"
    with tenant_session(pid) as db: assert db.get(Task,uuid.UUID(tid)).status == "done"


def test_batch_replan_starts_new_child_generation(budget_task,monkeypatch):
    from myink.workflow import batch_graph as batch
    from myink.workflow.chapter_graph import build_chapter_graph
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{})
    seen=[]
    monkeypatch.setattr(nodes,"node_write",lambda state: seen.append(state.get("batch_goal")) or {"draft":"draft","replan_batch":False,"audit_verdict":{"verdict":"pass"}})
    for name in ("extract","validate","audit","persist","summarize"):
        monkeypatch.setattr(nodes,"node_"+name,lambda state:{})
    graph=build_chapter_graph(InMemorySaver(),entry="write")
    run=batch.make_chapter_runner(graph)
    state={"project_id":pid,"batch_task_id":tid,"start_chapter":1,"position":0,"size":1,"batch_plan":{"chapters":[{"seq":1,"goal":"old"}]}}
    with bind_task_budget(tid,"owner"):
        run(state)
        state.update(batch_replan_count=1,batch_plan={"chapters":[{"seq":1,"goal":"new"}]})
        run(state)
    assert seen == ["old","new"]
