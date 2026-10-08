"""Tool execution budgets and chapter scope; no database or model service needed."""
import copy
import json
import uuid
from types import SimpleNamespace

import pytest

from myink.providers.base import ModelResponse
from myink.workflow import nodes, tools


class ToolChain:
    chain = []

    def __init__(self, batches):
        self.batches = iter(batches)
        self.messages = []

    def generate(self, messages, **kwargs):
        self.messages.append(copy.deepcopy(messages))
        calls = next(self.batches, []) if kwargs.get("tools") else []
        return ModelResponse(content="final" if not calls else "checking", model_id="fake", tool_calls=calls)


def call(cid, tool_name="inspect_character", **arguments):
    return {"id": cid, "name": tool_name, "arguments": arguments or {"name": "林川"}}


def run_loop(monkeypatch, chain, budget):
    monkeypatch.setattr(nodes, "record_run", lambda *args, **kwargs: None)
    return nodes._run_tool_loop(
        None, {"project_id": str(uuid.uuid4()), "chapter_seq": 7}, "audit", "Auditor",
        chain, [{"role": "user", "content": "check"}], max_tokens=100,
        tools=tools.READ_TOOLS, max_tool_calls=budget,
    )


@pytest.mark.parametrize("budget", [0, 1, 3])
def test_one_response_cannot_exceed_execution_budget(monkeypatch, budget):
    executed = []
    monkeypatch.setattr(nodes, "execute_tool", lambda *args: executed.append(args) or '{}')
    chain = ToolChain([[call(f"c{i}") for i in range(5)]])
    response, trace = run_loop(monkeypatch, chain, budget)
    assert len(executed) == budget
    assert response.content == "final"
    if budget:
        final = chain.messages[-1]
        replies = [m for m in final if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in replies] == [f"c{i}" for i in range(5)]
        assert all("TOOL_BUDGET_EXCEEDED" in m["content"] for m in replies[budget:])
        assert all(t.get("skipped") for t in trace[budget:])


def test_budget_is_shared_across_rounds(monkeypatch):
    executed = []
    monkeypatch.setattr(nodes, "execute_tool", lambda *args: executed.append(args) or '{}')
    chain = ToolChain([[call("a"), call("b")], [call("c"), call("d")]])
    run_loop(monkeypatch, chain, 3)
    assert len(executed) == 3
    assert len(chain.messages) == 3


@pytest.mark.parametrize("name", ["inspect_character", "inspect_facts"])
@pytest.mark.parametrize("explicit", [None, 4])
def test_chapter_default_is_bound_from_state(monkeypatch, name, explicit):
    executed = []
    monkeypatch.setattr(nodes, "execute_tool", lambda *args: executed.append(args) or '{}')
    arguments = {"name": "林川"} if name == "inspect_character" else {"query": "约束"}
    if explicit is not None:
        arguments["chapter_seq"] = explicit
    request = call("a", name, **arguments)
    original = copy.deepcopy(request)
    run_loop(monkeypatch, ToolChain([[request]]), 1)
    assert executed[0][3]["chapter_seq"] == (explicit or 7)
    assert request == original


def test_character_tool_reads_bound_historical_state(monkeypatch):
    pid, cid = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(tools.repo, "get_character", lambda *args: SimpleNamespace(
        id=cid, name="林川", realm_cap="普通人", personality="谨慎"))
    queries = []
    monkeypatch.setattr(tools.repo, "get_character_state", lambda *args: queries.append(args) or {"injury": "扭伤"})
    result = json.loads(tools.execute_tool(None, pid, "inspect_character", {"name": "林川", "chapter_seq": 7}))
    assert result["state"] == {"injury": "扭伤"}
    assert queries == [(None, pid, cid, 7)]


def test_unknown_and_failed_tools_return_errors(monkeypatch):
    pid = uuid.uuid4()
    assert "error" in json.loads(tools.execute_tool(None, pid, "unknown", {}))
    def fail(*args):
        raise ValueError("invalid fixture")
    monkeypatch.setitem(tools._EXECUTORS, "inspect_character", fail)
    assert "error" in json.loads(tools.execute_tool(None, pid, "inspect_character", {}))


def test_tool_error_can_be_followed_by_valid_lookup_without_restarting_budget(monkeypatch):
    chain=ToolChain([[call('bad','unknown')],[call('good')]])
    def execute(_db,_pid,name,args):
        return json.dumps({'error':'UNKNOWN_TOOL'} if name=='unknown' else {'state':{'injury':'扭伤'}})
    monkeypatch.setattr(nodes,'execute_tool',execute)
    response,trace=run_loop(monkeypatch,chain,2)
    assert response.content=='final'
    replies=[m for batch in chain.messages for m in batch if m['role']=='tool']
    assert any('UNKNOWN_TOOL' in r['content'] for r in replies)
    assert any('injury' in r['content'] for r in replies)
    assert len(trace)==2


def test_model_project_argument_cannot_override_server_scope(monkeypatch):
    real_pid=str(uuid.uuid4());foreign=str(uuid.uuid4());seen=[]
    monkeypatch.setattr(nodes,'record_run',lambda *args,**kwargs:None)
    def execute(db,pid,name,args):
        seen.append(str(pid));return '{"state":{"injury":"扭伤"}}'
    monkeypatch.setattr(nodes,'execute_tool',execute)
    chain=ToolChain([[call('lookup',project_id=foreign,name='林川')]])
    nodes._run_tool_loop(None,{'project_id':real_pid,'chapter_seq':7},'audit','Auditor',chain,
        [{'role':'user','content':'check'}],max_tokens=100,tools=tools.READ_TOOLS,max_tool_calls=1)
    assert seen==[real_pid]
