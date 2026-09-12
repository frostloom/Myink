from __future__ import annotations

import json

import httpx

from aiink.providers.anthropic import AnthropicProvider, _convert_messages, _messages_url
from aiink.providers.openai_compatible import OpenAICompatibleProvider


def test_anthropic_url_and_message_conversion_support_json_and_tools():
    assert _messages_url("https://api.anthropic.com") == "https://api.anthropic.com/v1/messages"
    assert _messages_url("https://proxy.example/v1") == "https://proxy.example/v1/messages"
    system, messages = _convert_messages([
        {"role": "system", "content": "你是规划器"},
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "call-1", "function": {"name": "lookup", "arguments": '{"chapter": 2}'},
        }]},
        {"role": "tool", "tool_call_id": "call-1", "content": "结果"},
    ], json_mode=True)
    assert "valid JSON" in system
    assert messages[0]["content"][0] == {
        "type": "tool_use", "id": "call-1", "name": "lookup", "input": {"chapter": 2},
    }
    assert messages[1]["content"][0]["type"] == "tool_result"


def test_anthropic_stream_forwards_text_and_collects_usage():
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 12}}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "第一段"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "第二段"}},
        {"type": "message_delta", "usage": {"output_tokens": 8}},
    ]
    body = "\n\n".join(f"data: {json.dumps(event)}" for event in events) + "\n\n"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    provider = AnthropicProvider(api_key="key", base_url="https://api.anthropic.com")
    provider._client.close()
    provider._client = httpx.Client(transport=transport)
    deltas: list[str] = []

    response = provider.generate_stream(
        [{"role": "user", "content": "写作"}], model_id="claude-test", on_delta=deltas.append,
    )

    assert deltas == ["第一段", "第二段"]
    assert response.content == "第一段第二段"
    assert response.input_tokens == 12
    assert response.output_tokens == 8


def test_openai_compatible_payload_does_not_send_deepseek_extension():
    kwargs = OpenAICompatibleProvider._request_kwargs(
        [{"role": "user", "content": "hello"}], model_id="gpt-test",
        max_tokens=100, temperature=0.2, json_mode=True, tools=None,
        disable_thinking=True,
    )
    assert kwargs["response_format"] == {"type": "json_object"}
    assert "extra_body" not in kwargs
