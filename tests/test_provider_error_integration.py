from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIConnectionError

from myink.providers import anthropic, deepseek


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
@pytest.mark.parametrize("stream", [False, True])
def test_generation_error_is_safe_and_retry_count_unchanged(monkeypatch, caplog, kind, stream):
    module = deepseek if kind == "openai" else anthropic
    cls = deepseek.DeepSeekProvider if kind == "openai" else anthropic.AnthropicProvider
    provider = cls(api_key="sk-secret", base_url="https://example.test")
    provider._client.close()
    req = httpx.Request("POST", "https://example.test")
    exc = httpx.ConnectError("private host sk-secret", request=req)
    if kind == "openai":
        wrapped = APIConnectionError(request=req)
        wrapped.__cause__ = exc
        exc = wrapped
    fail = Mock(side_effect=exc)
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fail)), post=fail, stream=fail,
    )
    sleep = Mock()
    monkeypatch.setattr(module.time, "sleep", sleep)
    resets = Mock()
    kwargs = {"model_id": "test-model"}
    with caplog.at_level("WARNING", logger=module.__name__):
        if stream:
            result = provider.generate_stream([{"role": "user", "content": "test"}], on_delta=Mock(), on_reset=resets, **kwargs)
        else:
            result = provider.generate([{"role": "user", "content": "test"}], **kwargs)
    assert "未能连接模型服务" in result.error
    assert "sk-secret" not in result.error + caplog.text
    assert "private host" not in result.error + caplog.text
    assert fail.call_count == 4
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0, 4.0]
    assert resets.call_count == 0


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_partial_stream_still_resets_on_each_failure(monkeypatch, kind):
    module = deepseek if kind == "openai" else anthropic
    cls = deepseek.DeepSeekProvider if kind == "openai" else anthropic.AnthropicProvider
    provider = cls(api_key="sk-secret", base_url="https://example.test")
    provider._client.close()
    error = httpx.ReadError("sk-secret private host")

    def chunks():
        delta = SimpleNamespace(content="正文", reasoning_content=None, reasoning_details=None, tool_calls=None)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)
        raise error

    def lines():
        yield 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"正文"}}'
        raise error

    @contextmanager
    def stream_response(*args, **kwargs):
        yield SimpleNamespace(raise_for_status=lambda: None, iter_lines=lines)

    create = Mock(side_effect=lambda **kwargs: chunks())
    stream = Mock(side_effect=stream_response)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), stream=stream)
    monkeypatch.setattr(module.time, "sleep", Mock())
    resets, deltas = Mock(), Mock()
    result = provider.generate_stream([{"role":"user", "content":"test"}], model_id="test", on_delta=deltas, on_reset=resets)
    assert resets.call_count == 4 and deltas.call_count == 4
    assert (create if kind == "openai" else stream).call_count == 4
    assert "模型通信中断" in result.error and "sk-secret" not in result.error
