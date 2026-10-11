"""Text-only Pi wire compatibility through the real metering boundary."""
from dataclasses import replace
import io
import json

import httpx
import pytest

from ops.pi.budget import totals
from ops.pi.control import make_gateway_handler
from ops.pi.model_gateway import forward_messages
from ops.pi.tests.test_budget import ledger, policy
from ops.pi.tests.test_model_gateway import transport


def pi_request():
    return dict(model='deepseek-v4.1-flash', max_tokens=1000, stream=True,
                system=[dict(type='text', text='Review the supplied source.')],
                messages=[dict(role='user', content=[dict(type='text', text='Read only.')])],
                thinking=dict(type='disabled'))


class PiStream(httpx.SyncByteStream):
    def __init__(self, usage):
        self.usage = usage

    def __iter__(self):
        events = [dict(type='message_start', message=dict(id='pi-provider-id', type='message',
                       role='assistant', model='deepseek-v4.1-flash', content=[],
                       stop_reason=None, stop_sequence=None, usage=self.usage)),
                  dict(type='content_block_start', index=0, content_block=dict(type='text', text='')),
                  dict(type='content_block_delta', index=0, delta=dict(type='text_delta', text='Reviewed.')),
                  dict(type='content_block_stop', index=0),
                  dict(type='message_delta', delta=dict(stop_reason='end_turn', stop_sequence=None),
                       usage=dict(output_tokens=5)),
                  dict(type='message_stop')]
        for event in events:
            yield ('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode()


def test_disabled_thinking_pi_text_stream_uses_all_four_usage_dimensions(ledger, policy):
    # Dropping either cache dimension or rejecting the Pi disabled-thinking
    # envelope must fail this metered end-to-end assertion.
    p = replace(policy, prices={**policy.prices, 'cache_write': '3'})
    def provider(req):
        assert json.loads(req.content)['thinking'] == {'type': 'disabled'}
        assert totals(ledger, 'local-trial-1') == (1, 11000)
        return httpx.Response(200, headers={'content-type': 'text/event-stream',
                                         'request-id': 'pi-provider-id'},
                              stream=PiStream(dict(input_tokens=7, output_tokens=0,
                                                   cache_read_input_tokens=11, cache_creation_input_tokens=13)))
    response = forward_messages(pi_request(), 'local-trial-1', ledger=ledger, policy=p,
                                transport=transport(provider))
    assert response.status_code == 200
    assert ledger.get(response.attempt_id)['status'] == 'pending'
    assert b'Reviewed.' in b''.join(response.body)
    assert ledger.get(response.attempt_id)['status'] == 'done'
    # 7*2 + 5*8 + 11*0.2 + 13*3 = 95.2 microyuan, rounded up once.
    assert totals(ledger, 'local-trial-1') == (1, 96)


@pytest.mark.parametrize('thinking', [{'type': 'enabled', 'budget_tokens': 128},
                                     {'type': 'adaptive'}, {'type': 'disabled', 'budget_tokens': 0},
                                     {'type': 'unknown'}, None])
def test_pi_non_disabled_thinking_rejected_before_reservation(ledger, policy, thinking):
    response = forward_messages(pi_request() | dict(thinking=thinking), 'local-trial-1',
                                ledger=ledger, policy=policy,
                                transport=lambda *_: pytest.fail('invalid request reached provider'))
    assert response.status_code == 400
    assert totals(ledger, 'local-trial-1') == (0, 0)


@pytest.mark.parametrize('change', [dict(system=[dict(type='text', text='x', cache_control={'type': 'ephemeral'})]),
                                   dict(messages=[dict(role='user', content=[dict(type='image', source={})])]),
                                   dict(tools=[dict(name='read', input_schema={})]), dict(metadata={})])
def test_pi_text_preview_rejects_extra_authority_before_reservation(ledger, policy, change):
    response = forward_messages(pi_request() | change, 'local-trial-1', ledger=ledger,
                                policy=policy, transport=lambda *_: pytest.fail('invalid request reached provider'))
    assert response.status_code == 400
    assert totals(ledger, 'local-trial-1') == (0, 0)


def test_disabled_thinking_still_counts_in_full_body_limit(ledger, policy):
    body = pi_request()
    without_thinking = {key: value for key, value in body.items() if key != 'thinking'}
    p = replace(policy, max_body_bytes=len(json.dumps(without_thinking, separators=(',', ':')).encode()))
    response = forward_messages(body, 'local-trial-1', ledger=ledger, policy=p,
                                transport=lambda *_: pytest.fail('oversized request reached provider'))
    assert response.status_code == 400
    assert totals(ledger, 'local-trial-1') == (0, 0)


@pytest.mark.parametrize('usage', [dict(input_tokens=7, output_tokens=0, cache_read_input_tokens=0),
                                  dict(input_tokens=7, output_tokens=0, cache_read_input_tokens=0,
                                       cache_creation_input_tokens=0, server_tool_use={'web_search_requests': 1})])
def test_pi_unknown_raw_usage_retains_full_reservation(ledger, policy, usage):
    response = forward_messages(pi_request(), 'local-trial-1', ledger=ledger, policy=policy,
                                transport=transport(lambda _: httpx.Response(200, stream=PiStream(usage))))
    assert response.status_code == 200
    assert b'Reviewed.' in b''.join(response.body)
    assert ledger.get(response.attempt_id)['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)


class Socket:
    def __init__(self, headers, body=b'{}'):
        self.raw = io.BytesIO(b'POST /v1/messages HTTP/1.0\r\nContent-Type: application/json\r\n'
                              + b'Content-Length: ' + str(len(body)).encode() + b'\r\n'
                              + headers + b'\r\n' + body)
        self.output = bytearray()

    def makefile(self, *args):
        return self.raw

    def sendall(self, data):
        self.output.extend(data)

    def settimeout(self, value):
        pass


def test_pi_scope_token_authenticated_request_is_metered(ledger, policy):
    def provider(req):
        assert 'synthetic-preview-token' not in req.content.decode()
        return httpx.Response(200, stream=PiStream(dict(input_tokens=7, output_tokens=0,
                                                      cache_read_input_tokens=0, cache_creation_input_tokens=0)))
    sock = Socket(b'x-api-key: synthetic-preview-token\r\nX-Pi-Scope: local-trial-1\r\n',
                  json.dumps(pi_request()).encode())
    make_gateway_handler(ledger, policy, transport(provider), scope_token='synthetic-preview-token')(
        sock, ('127.0.0.1', 1), object())
    assert b'200 OK' in sock.output
    assert totals(ledger, 'local-trial-1') == (1, 54)


@pytest.mark.parametrize('headers', [b'X-Pi-Scope: local-trial-1\r\n',
                                     b'x-api-key: wrong\r\nX-Pi-Scope: local-trial-1\r\n',
                                     b'x-api-key: synthetic-preview-token\r\n',
                                     b'x-api-key: synthetic-preview-token\r\nX-Pi-Scope: foreign\r\n',
                                     b'x-api-key: synthetic-preview-token\r\nx-api-key: synthetic-preview-token\r\nX-Pi-Scope: local-trial-1\r\n',
                                     b'x-api-key: synthetic-preview-token\r\nX-Pi-Scope: local-trial-1\r\nX-Pi-Scope: local-trial-1\r\n'])
def test_pi_scope_authentication_rejected_before_body_and_reservation(ledger, policy, headers):
    # Malformed JSON would return400 if authentication ran after body decoding.
    sock = Socket(headers, b'{')
    make_gateway_handler(ledger, policy, lambda *_: pytest.fail('unauthenticated request reached provider'),
                         scope_token='synthetic-preview-token')(sock, ('127.0.0.1', 1), object())
    assert b'403 Forbidden' in sock.output
    assert totals(ledger, 'local-trial-1') == (0, 0)


@pytest.mark.parametrize('token', ['', 'x'*4097, 'line\nbreak', 123],
                         ids=['empty', 'oversized', 'newline', 'non-string'])
def test_pi_scope_token_must_be_bounded_nonempty_header_value(ledger, policy, token):
    with pytest.raises(ValueError, match='invalid scope token'):
        make_gateway_handler(ledger, policy, lambda *_: pytest.fail('invalid host token used'), scope_token=token)
