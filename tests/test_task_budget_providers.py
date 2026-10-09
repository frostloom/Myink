"""Every real retry must obtain a durable budget permit."""
import json

import httpx
import pytest

from myink.providers.anthropic import AnthropicProvider
from myink.task_budget import (
    TaskBudgetPaused, bind_task_budget, bind_budget_operation, ensure_task_budget,
    budget_view, reserve_attempt, finish_attempt,
)
from test_task_budget import budget_task  # noqa: F401


def _provider(handler):
    provider = AnthropicProvider(api_key="test", base_url="https://example.invalid")
    provider._client.close()
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    return provider


def _reply():
    return httpx.Response(200, json={
        "content": [{"type": "text", "text": "result"}],
        "usage": {"input_tokens": 10, "output_tokens": 10},
    })


def test_request_limit_blocks_retry_before_http(budget_task, monkeypatch):
    import myink.providers.anthropic as module
    monkeypatch.setattr(module.time, "sleep", lambda delay: None)
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests": 1})
    requests = []
    provider = _provider(lambda request: requests.append(request) or httpx.Response(503))
    try:
        with bind_task_budget(tid, "owner"):
            with pytest.raises(TaskBudgetPaused, match="request_limit"):
                provider.generate([{"role": "user", "content": "hello"}],
                                  model_id="deepseek-v4.1-flash", max_tokens=20)
        assert len(requests) == 1
        assert budget_view(tid)["requests_used"] == 1
    finally:
        provider._client.close()


def test_usage_settles_reservation(budget_task):
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests": 2})
    provider = _provider(lambda request: _reply())
    try:
        with bind_task_budget(tid, "owner"):
            response = provider.generate([{"role": "user", "content": "hello"}],
                                         model_id="deepseek-v4.1-flash", max_tokens=20)
        assert response.error is None
        view = budget_view(tid)
        assert view["requests_used"] == 1
        assert view["cost_reserved_yuan"] == 0
        assert view["cost_used_yuan"] > 0
    finally:
        provider._client.close()


def test_cost_limit_blocks_first_http(budget_task):
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_cost_yuan": "0.000001"})
    requests = []
    provider = _provider(lambda request: requests.append(request) or _reply())
    try:
        with bind_task_budget(tid, "owner"):
            with pytest.raises(TaskBudgetPaused, match="cost_limit"):
                provider.generate([{"role": "user", "content": "hello"}],
                                  model_id="deepseek-v4.1-flash", max_tokens=20)
        assert not requests
    finally:
        provider._client.close()


def test_missing_usage_keeps_reservation(budget_task):
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {})
    with bind_task_budget(tid, "owner"):
        permit = reserve_attempt("unknown-real-model", [{"role": "user", "content": "hello"}], 20)
        finish_attempt(permit, None)
        finish_attempt(permit, None)
    view = budget_view(tid)
    assert view["requests_used"] == 1
    assert view["cost_reserved_yuan"] > 0


def test_streaming_retry_and_fallback_share_request_limit(budget_task, monkeypatch):
    from myink.providers.base import FallbackChain
    import myink.providers.anthropic as module
    monkeypatch.setattr(module, "MAX_RETRIES", 0)
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests": 1})
    requests = []
    provider = _provider(lambda request: requests.append(request) or httpx.Response(503))
    chain = FallbackChain(provider, ["deepseek-v4.1-flash", "deepseek-v4-flash"])
    try:
        with bind_task_budget(tid, "owner"):
            with pytest.raises(TaskBudgetPaused, match="request_limit"):
                chain.generate_stream([{"role": "user", "content": "hello"}],
                                      max_tokens=20, on_delta=lambda text: None)
        assert len(requests) == 1
    finally:
        provider._client.close()


def test_completed_call_reused_without_charge(budget_task):
    from myink.providers.base import FallbackChain
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests": 1})
    requests = []
    provider = _provider(lambda request: requests.append(request) or _reply())
    chain = FallbackChain(provider, ["deepseek-v4.1-flash"])
    try:
        with bind_task_budget(tid, "first"), bind_budget_operation("write:chapter1:round0:0"):
            first = chain.generate([{"role": "user", "content": "hello"}], max_tokens=20)
        with bind_task_budget(tid, "second"), bind_budget_operation("write:chapter1:round0:0"):
            replay = chain.generate([{"role": "user", "content": "hello"}], max_tokens=20)
        assert first.content == replay.content == "result"
        assert replay.budget_replayed is True
        assert replay.input_tokens == replay.output_tokens == 0
        assert len(requests) == 1
    finally:
        provider._client.close()


def test_remaining_runtime_limits_http_timeout(budget_task):
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_runtime_seconds": 5})
    requests = []
    provider = _provider(lambda request: requests.append(request) or _reply())
    try:
        with bind_task_budget(tid, "owner"):
            provider.generate([{"role": "user", "content": "hello"}],
                              model_id="deepseek-v4.1-flash", max_tokens=20)
        assert 0 < requests[0].extensions["timeout"]["read"] <= 5
    finally:
        provider._client.close()


def test_expired_runtime_blocks_before_http(budget_task, monkeypatch):
    import myink.task_budget as budget
    now = [1000.0]
    monkeypatch.setattr(budget.time, "time", lambda: now[0])
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_runtime_seconds": 1})
    requests = []
    provider = _provider(lambda request: requests.append(request) or _reply())
    try:
        with bind_task_budget(tid, "owner"):
            now[0] += 2
            with pytest.raises(TaskBudgetPaused, match="time_limit"):
                provider.generate([{"role": "user", "content": "hello"}],
                                  model_id="deepseek-v4.1-flash", max_tokens=20)
        assert not requests
    finally:
        provider._client.close()


def test_concurrent_reservations_cannot_exceed_limit(budget_task):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests": 1})
    def reserve():
        try:
            reserve_attempt("deepseek-v4.1-flash", [{"role": "user", "content": "hello"}], 20)
            return "allowed"
        except TaskBudgetPaused:
            return "paused"
    with bind_task_budget(tid, "owner"):
        contexts = [copy_context(), copy_context()]
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda ctx: ctx.run(reserve), contexts))
    assert sorted(values) == ["allowed", "paused"]
    assert budget_view(tid)["requests_used"] == 1



def test_tools_are_included_in_fee_reservation(budget_task):
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_cost_yuan": "0.005"})
    requests = []
    provider = _provider(lambda request: requests.append(request) or _reply())
    try:
        with bind_task_budget(tid, "owner"):
            with pytest.raises(TaskBudgetPaused, match="cost_limit"):
                provider.generate([{"role": "user", "content": "hello"}],
                                  model_id="deepseek-v4-flash", max_tokens=20,
                                  tools=[{"type": "function", "function": {
                                      "name": "lookup", "description": "x" * 20000}}])
        assert not requests
    finally:
        provider._client.close()


def test_storage_failure_does_not_send_http(budget_task, monkeypatch):
    import myink.task_budget as module
    from myink.task_budget import TaskBudgetUnavailable
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {})
    requests = []
    provider = _provider(lambda request: requests.append(request) or _reply())
    try:
        with bind_task_budget(tid, "owner"):
            with monkeypatch.context() as patch:
                patch.setattr(module, "_locked", lambda *args: (_ for _ in ()).throw(OSError("offline")))
                with pytest.raises(TaskBudgetUnavailable):
                    provider.generate([{"role": "user", "content": "hello"}],
                                      model_id="deepseek-v4.1-flash", max_tokens=20)
        assert not requests
    finally:
        provider._client.close()


@pytest.mark.parametrize("changed", ["input", "temperature"])
def test_changed_input_does_not_reuse_cached_call(budget_task, changed):
    from myink.providers.base import FallbackChain
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests": 1})
    requests = []
    provider = _provider(lambda request: requests.append(request) or _reply())
    chain = FallbackChain(provider, ["deepseek-v4.1-flash"])
    try:
        with bind_task_budget(tid, "first"), bind_budget_operation("write:1"):
            chain.generate([{"role": "user", "content": "first"}], max_tokens=20)
        with bind_task_budget(tid, "second"), bind_budget_operation("write:1"):
            with pytest.raises(TaskBudgetPaused, match="request_limit"):
                chain.generate([{"role": "user", "content": "changed" if changed == "input" else "first"}],
                               max_tokens=20, **({"temperature": 0.5} if changed == "temperature" else {}))
        assert len(requests) == 1
    finally:
        provider._client.close()


def test_openai_sdk_retry_has_no_hidden_attempts(budget_task, monkeypatch):
    import myink.providers.deepseek as module
    from openai import OpenAI
    from myink.providers.deepseek import DeepSeekProvider
    monkeypatch.setattr(module.time, "sleep", lambda delay: None)
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {"max_requests": 1})
    requests = []
    provider = DeepSeekProvider(api_key="test")
    assert provider._client.max_retries == 0
    provider._client.close()
    provider._client = OpenAI(api_key="test", base_url="https://example.invalid", max_retries=0,
                             http_client=httpx.Client(transport=httpx.MockTransport(
                                 lambda request: requests.append(request) or httpx.Response(503))))
    try:
        with bind_task_budget(tid, "owner"):
            with pytest.raises(TaskBudgetPaused, match="request_limit"):
                provider.generate([{"role": "user", "content": "hello"}],
                                  model_id="deepseek-v4.1-flash", max_tokens=20)
        assert len(requests) == 1
    finally:
        provider._client.close()


def test_openai_stream_closed_on_partial_failure(budget_task, monkeypatch):
    from types import SimpleNamespace
    from myink.providers.deepseek import DeepSeekProvider
    import myink.providers.deepseek as module
    monkeypatch.setattr(module, "MAX_RETRIES", 0)
    tid, pid, uid = budget_task
    ensure_task_budget(tid, pid, uid, {})
    class BrokenStream:
        closed = False
        def __iter__(self):
            yield SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content="part"))])
            raise OSError("stream lost")
        def close(self):
            self.closed = True
    stream = BrokenStream()
    provider = DeepSeekProvider(api_key="test")
    monkeypatch.setattr(provider._client.chat.completions, "create", lambda **kwargs: stream)
    try:
        with bind_task_budget(tid, "owner"):
            response = provider.generate_stream([{"role": "user", "content": "hello"}],
                         model_id="deepseek-v4-flash", max_tokens=20, on_delta=lambda text: None)
        assert response.error
        assert stream.closed
        assert budget_view(tid)["cost_reserved_yuan"] > 0
    finally:
        provider._client.close()
