"""Thinking blocks must survive tool execution without entering public output."""
import json
from types import SimpleNamespace

import httpx
import pytest

from myink.providers.anthropic import AnthropicProvider
from myink.providers.base import FallbackChain, ModelProvider, ModelResponse
from myink.workflow import nodes


BLOCKS = [
    {'type': 'thinking', 'thinking': 'private analysis', 'signature': 'signed-proof'},
    {'type': 'redacted_thinking', 'data': 'opaque-data'},
    {'type': 'text', 'text': 'Checking.'},
    {'type': 'tool_use', 'id': 'lookup-1', 'name': 'lookup', 'input': {'q': 'facts'}},
]
TOOLS = [{'type': 'function', 'function': {'name': 'lookup', 'parameters': {'type': 'object'}}}]


def streamed(blocks, reason):
    events = [{'type': 'message_start', 'message': {'usage': {'input_tokens': 5}}}]
    for index, block in enumerate(blocks):
        start = dict(block)
        deltas = []
        for key, delta_type in [('thinking', 'thinking_delta'), ('signature', 'signature_delta'), ('text', 'text_delta')]:
            if key in start:
                value = start[key]
                start[key] = ''
                deltas.extend({'type': delta_type, key: part} for part in [value[:3], value[3:]])
        if block['type'] == 'tool_use':
            start['input'] = {}
            deltas.append({'type': 'input_json_delta', 'partial_json': json.dumps(block['input'])})
        events.append({'type': 'content_block_start', 'index': index, 'content_block': start})
        events.extend({'type': 'content_block_delta', 'index': index, 'delta': delta} for delta in deltas)
        events.append({'type': 'content_block_stop', 'index': index})
    events.extend([{'type': 'message_delta', 'delta': {'stop_reason': reason}, 'usage': {'output_tokens': 9}}, {'type': 'message_stop'}])
    return '\n\n'.join('data: ' + json.dumps(event) for event in events) + '\n\n'


def provider_with(handler, url='https://example.test/anthropic'):
    provider = AnthropicProvider(api_key='secret-key', base_url=url)
    provider._client.close()
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    return provider


@pytest.mark.parametrize('stream', [False, True])
def test_tool_loop_replays_all_blocks_without_exposing_thinking(monkeypatch, stream):
    requests = []
    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) > 1:
            assistant = next(m for m in payload['messages'] if m['role'] == 'assistant')
            if assistant['content'] != BLOCKS:
                return httpx.Response(400, json={'error': {'message': 'content[].thinking must be passed back'}})
        blocks = BLOCKS if len(requests) == 1 else [{'type': 'text', 'text': 'Final.'}]
        reason = 'tool_use' if len(requests) == 1 else 'end_turn'
        if stream:
            return httpx.Response(200, text=streamed(blocks, reason))
        return httpx.Response(200, json={'content': blocks, 'stop_reason': reason, 'usage': {'input_tokens': 5, 'output_tokens': 9}})
    provider = provider_with(handle)
    chain = FallbackChain(provider, ['thinking-model'], thinking_enabled=True)
    monkeypatch.setattr(nodes, 'execute_tool', lambda *args: 'facts')
    output = []
    emitter = SimpleNamespace(feed=output.append, reset=lambda: output.clear()) if stream else None
    try:
        response, trace = nodes._run_tool_loop(None, {}, 'plan', 'planner', chain,
            [{'role': 'user', 'content': 'Plan'}], max_tokens=100, tools=TOOLS,
            max_tool_calls=2, record_final=False, streamer=emitter)
        assert response.error is None
        assert response.content == 'Final.'
        assert len(requests) == 2
        assert 'thinking' not in requests[0]
        assert len(trace) == 1
        assert 'private analysis' not in ''.join(output)
    finally:
        provider._client.close()


@pytest.mark.parametrize('target', ['other-model', 'other-endpoint', 'openai'])
def test_private_blocks_do_not_cross_model_or_provider_boundary(target):
    source = provider_with(lambda r: httpx.Response(200, json={'content': BLOCKS, 'usage': {}}))
    response = source.generate([], model_id='thinking-model')
    message = nodes._assistant_tool_calls_message(response)
    captured = []
    class OtherProvider(ModelProvider):
        def name(self): return 'openai-compatible'
        def generate(self, messages, **kwargs):
            captured.extend(messages)
            return ModelResponse(content='ok', model_id=kwargs['model_id'])
    def handle(request):
        captured.extend(json.loads(request.content)['messages'])
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'ok'}]})
    other = OtherProvider() if target == 'openai' else provider_with(handle,
        url='https://other.test' if target == 'other-endpoint' else 'https://example.test/anthropic')
    try:
        result = FallbackChain(other, ['other' if target == 'other-model' else 'thinking-model']).generate([message])
        assert result.error is None
        assert 'private analysis' not in json.dumps(captured)
        assert 'signed-proof' not in json.dumps(captured)
        assert 'opaque-data' not in json.dumps(captured)
    finally:
        source._client.close()
        if isinstance(other, AnthropicProvider): other._client.close()


class ErrorStream(httpx.SyncByteStream):
    def __init__(self, endless=False, fail=False):
        self.closed = False
        self.reads = 0
        self.endless = endless
        self.fail = fail
    def __iter__(self):
        self.reads += 1
        yield b'{"error":{"message":"content[].thinking must be passed back secret-key"}}'
        if self.fail:
            raise httpx.ReadError('private transport details')
        if self.endless:
            for _ in range(100):
                self.reads += 1
                yield b'x' * 4096
    def close(self): self.closed = True


@pytest.mark.parametrize('endless,fail', [(False, False), (True, False), (False, True)])
def test_stream_http_error_has_bounded_sanitized_detail_and_closes(endless, fail):
    body = ErrorStream(endless, fail)
    provider = provider_with(lambda r: httpx.Response(400, stream=body))
    try:
        result = provider.generate_stream([], model_id='thinking-model', on_delta=lambda x: None)
        assert 'HTTP 400' in result.error
        assert 'content[].thinking must be passed back' in result.error
        assert 'secret-key' not in result.error
        assert 'private transport details' not in result.error
        assert len(result.error) <= 300
        assert body.closed
        assert body.reads < 10
    finally:
        provider._client.close()


def test_diagnostics_omit_private_protocol_context(monkeypatch):
    provider = provider_with(lambda r: httpx.Response(200, json={'content': BLOCKS, 'usage': {}}))
    try:
        response = provider.generate([], model_id='thinking-model')
        message = nodes._assistant_tool_calls_message(response)
        rows = []
        monkeypatch.setattr(nodes, '_owner_ids', lambda **kwargs: (None, None))
        monkeypatch.setattr(nodes, 'capture_detail', lambda detail: detail)
        nodes.record_run(SimpleNamespace(add=rows.append), node='plan', role='planner',
                         resp=response, messages=[message])
        detail = json.dumps(rows[0].detail)
        assert 'private analysis' not in detail
        assert 'signed-proof' not in detail
        assert 'Checking.' in detail
        assert 'lookup' in detail
    finally:
        provider._client.close()


@pytest.mark.parametrize('stream', [False, True])
def test_failed_continuation_falls_back_without_private_blocks(stream):
    count = 0
    def primary(request):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(200, json={'content': BLOCKS, 'usage': {}})
        return httpx.Response(400, json={'error': {'message': 'unavailable'}})
    provider = provider_with(primary)
    calls = []
    class Backup(ModelProvider):
        def name(self): return 'backup'
        def generate(self, messages, **kwargs):
            calls.extend(messages)
            return ModelResponse(content='Recovered', model_id=kwargs['model_id'])
    try:
        message = nodes._assistant_tool_calls_message(provider.generate([], model_id='primary'))
        chain = FallbackChain(provider, ['primary', 'backup'], providers=[provider, Backup()], thinking_enabled=True)
        deltas = []
        if stream:
            result = chain.generate_stream([message], on_delta=deltas.append)
            assert deltas == ['Recovered']
        else:
            result = chain.generate([message])
        assert result.content == 'Recovered'
        assert result.degraded
        assert calls == [{'role': 'assistant', 'content': 'Checking.', 'tool_calls': [
            {'id': 'lookup-1', 'type': 'function', 'function': {'name': 'lookup', 'arguments': '{"q": "facts"}'}}]}]
    finally:
        provider._client.close()


def test_error_body_read_preserves_budget_pause_and_closes(monkeypatch):
    from myink.providers import anthropic
    from myink.task_budget import TaskBudgetPaused
    body = ErrorStream()
    provider = provider_with(lambda r: httpx.Response(400, stream=body))
    def pause(permit, iterable):
        raise TaskBudgetPaused('time_limit', None)
    monkeypatch.setattr(anthropic, 'budget_iter', pause)
    try:
        with pytest.raises(TaskBudgetPaused):
            provider.generate_stream([], model_id='thinking-model', on_delta=lambda x: None)
        assert body.closed
    finally:
        provider._client.close()
