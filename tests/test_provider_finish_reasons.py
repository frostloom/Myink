"""Provider termination metadata reaches the draft truncation warning."""
import json
from types import SimpleNamespace as NS

import httpx
import pytest

from myink.providers.deepseek import DeepSeekProvider
from myink.providers.openai_compatible import OpenAICompatibleProvider
from myink.providers.anthropic import AnthropicProvider
from myink.workflow.short_runner import _truncation_note


@pytest.mark.parametrize("provider_type", [DeepSeekProvider, OpenAICompatibleProvider])
@pytest.mark.parametrize("reason", ["length", "stop"])
def test_openai_stream_retains_finish_reason_after_usage_frame(provider_type, reason):
    provider = provider_type(api_key="test", base_url="https://example.invalid")
    provider._client.close()
    chunks = [NS(usage=None, choices=[NS(delta=NS(content="【第1章】正文", tool_calls=None), finish_reason=None)]),
              NS(usage=None, choices=[NS(delta=NS(content=None, tool_calls=None), finish_reason=reason)]),
              NS(usage=NS(prompt_tokens=5, completion_tokens=20), choices=[])]
    provider._client = NS(chat=NS(completions=NS(create=lambda **kw: iter(chunks))))
    response = provider.generate_stream([{"role": "user", "content": "写作"}],
                                        model_id="test-model", max_tokens=20, on_delta=lambda text: None)
    assert response.error is None and response.content == "【第1章】正文"
    assert response.finish_reason == reason
    assert (_truncation_note(response, "成稿") is not None) == (reason == "length")


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("reason,expected", [("max_tokens", "length"), ("end_turn", "stop"), ("tool_use", "tool_calls")])
def test_anthropic_stop_reason_reaches_truncation_warning(stream, reason, expected):
    def handle(request):
        if not stream:
            return httpx.Response(200, json={"content": [{"type": "text", "text": "【第1章】正文"}],
                                            "usage": {"input_tokens": 5, "output_tokens": 20}, "stop_reason": reason})
        events = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "【第1章】正文"}},
            {"type": "message_delta", "delta": {"stop_reason": reason}, "usage": {"output_tokens": 20}},
            {"type": "message_stop"},
        ]
        return httpx.Response(200, text="\n\n".join("data: " + json.dumps(event) for event in events))

    provider = AnthropicProvider(api_key="test", base_url="https://example.invalid")
    provider._client.close()
    provider._client = httpx.Client(transport=httpx.MockTransport(handle))
    try:
        kwargs = {"model_id": "test-model", "max_tokens": 20}
        response = (provider.generate_stream([{"role": "user", "content": "写作"}], on_delta=lambda text: None, **kwargs)
                    if stream else provider.generate([{"role": "user", "content": "写作"}], **kwargs))
        assert response.error is None
        assert response.finish_reason == expected
        assert (_truncation_note(response, "成稿") is not None) == (expected == "length")
    finally:
        provider._client.close()
