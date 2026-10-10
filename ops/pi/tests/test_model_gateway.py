from dataclasses import replace
import httpx
import pytest

from ops.pi.model_gateway import forward_messages
from ops.pi.budget import totals
from ops.pi.tests.test_budget import policy, ledger, request


def transport(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    def send(body, timeout):
        req = client.build_request('POST', 'https://provider.example/v1/messages', json=body, timeout=timeout)
        return client.send(req, stream=True, follow_redirects=False)
    return send



def _expire_during_entered_transport(ledger, policy, monkeypatch, send):
    """Exercise acquisition expiry after real reservation, independent of disk speed."""
    import threading
    import time
    import ops.pi.model_gateway as gateway
    elapsed = [0.0]
    wall_start, monotonic_start = time.time(), time.monotonic()
    monkeypatch.setattr(time, 'time', lambda: wall_start + elapsed[0])
    monkeypatch.setattr(time, 'monotonic', lambda: monotonic_start + elapsed[0])
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    results, errors = [], []
    producer_returned = threading.Event()
    real_receive = gateway._DeadlineUpstream.receive
    def receive_after_transport_entry(upstream):
        assert entered.wait(3), 'transport entry precedes remaining acquisition wait'
        elapsed[0] = 119.95  #50ms remains on the original120s permit.
        return real_receive(upstream)
    monkeypatch.setattr(gateway._DeadlineUpstream, 'receive', receive_after_transport_entry)
    def blocked_send(body, timeout):
        entered.set()
        release.wait()  # Only finally may release the producer.
        producer_returned.set()
        return send(body, timeout)
    def forward():
        try:
            results.append(forward_messages(request(), 'local-trial-1', ledger=ledger,
                                            policy=policy, transport=blocked_send))
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()
    caller = threading.Thread(target=forward, daemon=True)
    caller.start()
    try:
        assert entered.wait(3), 'the actual transport acquisition must be entered'
        assert not producer_returned.is_set(), 'the transport producer must remain blocked'
        assert finished.wait(3), 'caller acquisition must return while producer stays blocked'
        assert not release.is_set() and not producer_returned.is_set()
        assert errors == []
        assert len(results) == 1 and results[0].status_code == 502
        record = ledger.get(results[0].attempt_id)
        assert record['payload']['deadline'] == wall_start + 120
        assert record['status'] == 'uncertain'
        assert totals(ledger, 'local-trial-1') == (1, 10000)
        return results[0]
    finally:
        release.set()
        caller.join(3)


def success(_):
    return httpx.Response(200, json=dict(id='provider-id', usage=dict(input_tokens=1, output_tokens=1,
                         cache_read_input_tokens=0, cache_creation_input_tokens=0)))


def test_101st_http_attempt_denied(ledger, policy):
    calls = []
    def handler(req):
        calls.append(req)
        return success(req)
    send = transport(handler)
    for _ in range(100):
        assert forward_messages(request(), 'local-trial-1', ledger=ledger, policy=policy, transport=send).status_code == 200
    assert forward_messages(request(), 'local-trial-1', ledger=ledger, policy=policy, transport=send).status_code == 429
    assert len(calls) == 100
    assert totals(ledger, 'local-trial-1')[0] == 100


def test_missing_confirmed_prices_blocks_live(ledger, policy):
    p = replace(policy, live_enabled=True, input_bound_calibrated=True)
    result = forward_messages(request(), 'local-trial-1', ledger=ledger, policy=p, transport=transport(success))
    assert result.status_code == 403
    assert totals(ledger, 'local-trial-1') == (0, 0)


@pytest.mark.parametrize('change', [dict(model='evil'), dict(prices={}), dict(base_url='https://evil'),
                                   dict(tools=[dict(type='web_search_20250305', name='web_search')]),
                                   dict(messages=[dict(role='user', content=[dict(type='text', text='hi', cache_control=dict(type='ephemeral'))])])])
def test_client_cannot_change_model_or_prices(ledger, policy, change):
    body = request() | change
    result = forward_messages(body, 'local-trial-1', ledger=ledger, policy=policy, transport=transport(success))
    assert result.status_code == 400
    assert totals(ledger, 'local-trial-1') == (0, 0)


def test_proxy_restart_keeps_scope(ledger, policy):
    from ops.pi.ledger import Ledger
    forward_messages(request(), 'local-trial-1', ledger=ledger, policy=policy, transport=transport(success))
    assert totals(Ledger(ledger.path), 'local-trial-1') == (1, 10)


class Chunks(httpx.SyncByteStream):
    def __init__(self, disconnect=False):
        self.reads = 0
        self.disconnect = disconnect
    def __iter__(self):
        self.reads += 1
        yield b'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":1,"output_tokens":0,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n\n'
        self.reads += 1
        if self.disconnect:
            raise httpx.ReadError('offline disconnect')
        yield b'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":1}}\n\nevent: message_stop\ndata: {"type":"message_stop"}\n\n'


def test_stream_is_progressive_and_settles_at_eof(ledger, policy):
    stream = Chunks()
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger,
                                policy=policy, transport=transport(lambda _: httpx.Response(200, headers={'content-type':'text/event-stream'}, stream=stream)))
    assert stream.reads == 0
    iterator = iter(response.body)
    assert next(iterator).startswith(b'event: message_start')
    assert stream.reads == 1
    assert ledger.get(response.attempt_id)['status'] == 'pending'
    list(iterator)
    assert totals(ledger, 'local-trial-1') == (1, 10)


def test_stream_disconnect_no_refund(ledger, policy):
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger,
                                policy=policy, transport=transport(lambda _: httpx.Response(200, stream=Chunks(True))))
    with pytest.raises(httpx.ReadError):
        list(response.body)
    assert totals(ledger, 'local-trial-1') == (1, 10000)


@pytest.mark.parametrize('status', [302, 402, 500])
def test_error_preserves_reservation(ledger, policy, status):
    result = forward_messages(request(), 'local-trial-1', ledger=ledger, policy=policy,
                              transport=transport(lambda _: httpx.Response(status, headers={'location':'https://evil'})))
    assert result.status_code == (502 if status == 302 else status)
    assert totals(ledger, 'local-trial-1') == (1, 10000)

def test_cli_http_handler_uses_fixed_scope_and_rejects_content_type(ledger, policy):
    import io
    from ops.pi.control import make_gateway_handler
    class Socket:
        def __init__(self, raw):
            self.raw = io.BytesIO(raw)
            self.output = bytearray()
        def makefile(self, *args):
            return self.raw
        def sendall(self, data):
            self.output.extend(data)
        def settimeout(self, value):
            pass
    handler = make_gateway_handler(ledger, policy, transport(success))
    import json
    body = json.dumps(request()).encode()
    sock = Socket(b'POST /v1/messages HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
    handler(sock, ('127.0.0.1', 1), object())
    assert b'200 OK' in sock.output
    assert totals(ledger, 'local-trial-1') == (1, 10)
    bad = Socket(b'POST /v1/messages HTTP/1.0\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\n{}')
    handler(bad, ('127.0.0.1', 1), object())
    assert b'400 Bad Request' in bad.output
    assert totals(ledger, 'local-trial-1') == (1, 10)


def test_live_disabled_cli_does_not_read_credentials(tmp_path, monkeypatch):
    import json
    from ops.pi import control
    # Policy is disabled even with a credential path that does not exist.
    path = tmp_path / 'policy.json'
    data = dict(schema_version=1, live_enabled=False, server_daily_enabled=False,
                model='deepseek-v4.1-flash', protocol='anthropic', base_url='https://provider.example',
                max_attempts=100, budget_microyuan=10000000, timeout_seconds=120,
                max_body_bytes=65536, input_token_bound=1000, input_bound_source='offline fixture',
                input_bound_calibrated=False, max_tokens=1000, price_source='offline fixture',
                prices=dict(input='2', output='8', cache_read='0.2', cache_write=None),
                grace_seconds=900, soft_production_files=3, soft_production_lines=150,
                hard_tracked_files=8, hard_production_lines=300,
                protected_paths=['ops/pi', '.github', 'AGENTS.md', '.agents', '.codex', 'docs/team-workflow.md'],
                high_risk_types=['schema', 'authentication', 'billing', 'external_api', 'infrastructure', 'deployment', 'policy'])
    path.write_text(json.dumps(data))
    monkeypatch.setattr(control, 'state_path_allowed', lambda state: state.is_absolute() and state == tmp_path)
    from ops.pi.policy import load_policy
    assert control.live_ready(load_policy(path)) is False
    with pytest.raises(ValueError, match='live configuration incomplete'):
        control.serve_gateway(None, load_policy(path), tmp_path / 'missing-secret.json')
    monkeypatch.setattr(control, 'serve_gateway', lambda *a, **k: pytest.fail('live server started'))
    assert control.main(['model-gateway', '--state-dir', str(tmp_path), '--policy', str(path),
                         '--credential-file', str(tmp_path / 'missing-secret.json')]) == 1

@pytest.mark.parametrize('change', [dict(stream=1), dict(max_tokens=True), dict(max_tokens=1001),
                                   dict(messages='bad'), dict(temperature=True), dict(top_p=2),
                                   dict(stop_sequences='x'), dict(messages=[dict(role='user', content='x'*65536)])])
def test_invalid_request_never_spends_attempt(ledger, policy, change):
    result = forward_messages(request() | change, 'local-trial-1', ledger=ledger, policy=policy, transport=transport(success))
    assert result.status_code == 400
    assert totals(ledger, 'local-trial-1') == (0, 0)


def test_sse_oversize_event_forwards_but_never_refunds(ledger, policy):
    class Huge(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: ' + b'x'*70000 + b'\n\n'
            yield b'data: {"type":"message_stop"}\n\n'
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger, policy=policy,
                                transport=transport(lambda _: httpx.Response(200, stream=Huge())))
    output = list(response.body)
    assert len(output) == 2
    assert totals(ledger, 'local-trial-1') == (1, 10000)


def test_error_request_id_retained_for_reconciliation(ledger, policy):
    response = forward_messages(request(), 'local-trial-1', ledger=ledger, policy=policy,
                                transport=transport(lambda _: httpx.Response(402, headers={'request-id':'paid-unknown'})))
    assert ledger.get(response.attempt_id)['evidence']['provider_request_id'] == 'paid-unknown'


def test_deadline_exceeded_never_refunds(ledger, policy, monkeypatch):
    import ops.pi.model_gateway as gateway
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger, policy=policy,
                                transport=transport(lambda _: httpx.Response(200, stream=Chunks())))
    monkeypatch.setattr(gateway.time, 'time', lambda: 999999999999)
    with pytest.raises(TimeoutError):
        list(response.body)
    assert totals(ledger, 'local-trial-1') == (1, 10000)


def test_blocked_transport_cannot_exceed_request_deadline(ledger, policy, monkeypatch):
    result = _expire_during_entered_transport(ledger, policy, monkeypatch,
                                             lambda body, timeout: httpx.Response(200, json={'usage':{}}))
    assert result.status_code == 502
    assert ledger.get(result.attempt_id)['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)



def test_blocked_stream_read_cannot_exceed_request_deadline(ledger, policy, monkeypatch):
    import threading
    import time
    import ops.pi.model_gateway as gateway
    elapsed = [0.0]
    wall_start, monotonic_start = time.time(), time.monotonic()
    monkeypatch.setattr(time, 'time', lambda: wall_start + elapsed[0])
    monkeypatch.setattr(time, 'monotonic', lambda: monotonic_start + elapsed[0])
    release, entered, finished = threading.Event(), threading.Event(), threading.Event()
    delivered, errors = [], []
    real_receive = gateway._DeadlineUpstream.receive
    receive_calls = [0]
    def receive_after_read_entry(upstream):
        receive_calls[0] += 1
        if receive_calls[0] > 1:
            assert entered.wait(3), 'read entry precedes the remaining wait budget'
            elapsed[0] = 119.95  # Only50ms remains on the original120s permit.
        return real_receive(upstream)
    monkeypatch.setattr(gateway._DeadlineUpstream, 'receive', receive_after_read_entry)
    class Blocked(httpx.SyncByteStream):
        def __iter__(self):
            entered.set()
            release.wait(3)
            yield b'event: ping\ndata: {"type":"ping"}\n\n'
    # Real SQLite remains in this test; virtual time does not conflate its
    # filesystem latency with the specific blocked-read phase being exercised.
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger,
                                policy=policy,
                                transport=transport(lambda _: httpx.Response(200, stream=Blocked())))
    assert response.status_code == 200
    assert not isinstance(response.body, bytes)
    assert ledger.get(response.attempt_id)['payload']['deadline'] == wall_start + 120
    def consume():
        try:
            delivered.extend(response.body)
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()
    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()
    try:
        assert entered.wait(3), 'the actual upstream read must be entered'
        assert not finished.is_set(), 'the upstream read must still be blocked'
        assert finished.wait(3)
        assert not release.is_set(), 'caller must time out while producer stays blocked'
        assert len(errors) == 1 and isinstance(errors[0], TimeoutError)
        assert delivered == []
        assert ledger.get(response.attempt_id)['status'] == 'uncertain'
        assert totals(ledger, 'local-trial-1') == (1, 10000)
    finally:
        release.set()
        consumer.join(3)



def test_late_response_is_closed_without_refund(ledger, policy, monkeypatch):
    import threading
    closed = threading.Event()
    class Late(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}'
        def close(self):
            closed.set()
    response = _expire_during_entered_transport(ledger, policy, monkeypatch,
                                              lambda body, timeout: httpx.Response(200, stream=Late()))
    assert closed.wait(3)
    assert ledger.get(response.attempt_id)['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)



def test_client_abandons_sse_no_refund(ledger, policy):
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger,
                                policy=policy, transport=transport(lambda _: httpx.Response(200, stream=Chunks())))
    iterator = iter(response.body)
    next(iterator)
    iterator.close()
    assert ledger.get(response.attempt_id)['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)


def test_trusted_server_transport_reads_only_credential_file(tmp_path, ledger, policy, monkeypatch):
    import io
    import json
    from ops.pi import control
    live = replace(policy, live_enabled=True, input_bound_calibrated=True,
                   base_url='https://maas.qianwenaiapi.com/apps/anthropic',
                   prices=policy.prices | dict(cache_write='2'))
    credential = tmp_path / 'trusted.json'
    credential.write_text(json.dumps(dict(PLATFORM_MODEL_API_KEY='test-credential',
                                         PLATFORM_MODEL_BASE_URL='https://maas.qianwenaiapi.com/apps/anthropic',
                                         PLATFORM_MODEL_NAME=live.model, PLATFORM_MODEL_PROTOCOL='anthropic')))
    monkeypatch.setenv('PLATFORM_MODEL_API_KEY', 'untrusted-environment')
    client_type = httpx.Client
    requests = []
    def handler(req):
        requests.append(req)
        return success(req)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return client_type(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(control.httpx, 'Client', client)
    class Socket:
        def __init__(self):
            body = json.dumps(request()).encode()
            self.raw = io.BytesIO(b'POST /v1/messages HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
            self.output = bytearray()
        def makefile(self, *args): return self.raw
        def sendall(self, data): self.output.extend(data)
        def settimeout(self, timeout): pass
    class Server:
        def __init__(self, address, handler):
            assert address == ('127.0.0.1', 8765)
            self.handler = handler
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def serve_forever(self):
            socket = Socket()
            self.handler(socket, ('127.0.0.1', 1), self)
            assert b'200 OK' in socket.output
    monkeypatch.setattr(control, 'ThreadingHTTPServer', Server)
    control.serve_gateway(ledger, live, credential)
    assert str(requests[0].url) == 'https://maas.qianwenaiapi.com/apps/anthropic/v1/messages'
    assert requests[0].headers['x-api-key'] == 'test-credential'
    assert requests[0].headers['anthropic-version'] == '2023-06-01'
    assert totals(ledger, 'local-trial-1') == (1, 10)


def test_cleanup_exception_never_leaks_background_context(ledger, policy, monkeypatch):
    import threading
    import ops.pi.model_gateway as gateway
    threads = []
    failures = []
    real_thread = threading.Thread
    def make_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        threads.append(thread)
        return thread
    monkeypatch.setattr(gateway, 'Thread', make_thread)
    monkeypatch.setattr(threading, 'excepthook', failures.append)
    class BrokenClose(httpx.SyncByteStream):
        def __iter__(self):
            yield b''
        def close(self):
            raise RuntimeError('sensitive-upstream-context')
    response = _expire_during_entered_transport(ledger, policy, monkeypatch,
                                              lambda body, timeout: httpx.Response(200, stream=BrokenClose()))
    for thread in threads:
        thread.join(1)
    assert failures == []
    assert totals(ledger, 'local-trial-1') == (1, 10000)


def test_sse_missing_final_output_usage_never_refunds(ledger, policy):
    class MissingFinal(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"type":"message_start","message":{"usage":{"input_tokens":1,"output_tokens":0,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n\n'
            yield b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"paid output"}}\n\n'
            yield b'data: {"type":"message_stop"}\n\n'
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger, policy=policy,
                                transport=transport(lambda _: httpx.Response(200, stream=MissingFinal())))
    assert b'paid output' in b''.join(response.body)
    assert totals(ledger, 'local-trial-1') == (1, 10000)
    assert ledger.get(response.attempt_id)['status'] == 'uncertain'


def test_downstream_write_uses_remaining_absolute_deadline(ledger, policy, monkeypatch):
    import io
    import json
    import time
    from ops.pi import control
    now = [time.monotonic()]
    monkeypatch.setattr(time, 'monotonic', lambda: now[0])
    class Socket:
        def __init__(self):
            body = json.dumps(request() | dict(stream=True)).encode()
            self.raw = io.BytesIO(b'POST /v1/messages HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
            self.output = bytearray()
            self.timeout = None
            self.body_timeouts = []
        def makefile(self, *args): return self.raw
        def settimeout(self, value): self.timeout = value
        def sendall(self, data):
            if data.startswith(b'HTTP/'):
                now[0] += 119
            elif data.startswith(b'event:'):
                self.body_timeouts.append(self.timeout)
                if len(self.body_timeouts) == 1:
                    now[0] += 0.5
                else:
                    # A late downstream write completes after the one absolute deadline.
                    now[0] += 1
            self.output.extend(data)
    sock = Socket()
    handler = control.make_gateway_handler(ledger, policy, transport(lambda _: httpx.Response(200, stream=Chunks())))
    handler(sock, ('127.0.0.1', 1), object())
    assert len(sock.body_timeouts) == 2
    assert 0 < sock.body_timeouts[0] <= 1
    assert 0 < sock.body_timeouts[1] <= 0.5
    assert totals(ledger, 'local-trial-1') == (1, 10000)
    with ledger.transaction() as connection:
        rows = list(connection.execute("SELECT status FROM operations WHERE kind='model-attempt'"))
    assert [r['status'] for r in rows] == ['uncertain']


def test_sse_output_usage_before_paid_content_is_not_final(ledger, policy):
    class EarlyUsage(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"type":"message_start","message":{"usage":{"input_tokens":1,"output_tokens":0,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n\n'
            yield b'data: {"type":"message_delta","usage":{"output_tokens":0}}\n\n'
            yield b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"paid after usage"}}\n\n'
            yield b'data: {"type":"message_stop"}\n\n'
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger, policy=policy,
                                transport=transport(lambda _: httpx.Response(200, stream=EarlyUsage())))
    assert b'paid after usage' in b''.join(response.body)
    assert totals(ledger, 'local-trial-1') == (1, 10000)


@pytest.mark.parametrize('body_elapsed', [119, 121])
def test_http_body_acquisition_shares_model_request_deadline(ledger, policy, monkeypatch, body_elapsed):
    import io
    import json
    import time
    from ops.pi import control
    now = [time.monotonic()]
    monkeypatch.setattr(time, 'monotonic', lambda: now[0])
    class SlowInput(io.BytesIO):
        def read(self, *args):
            now[0] += body_elapsed
            return super().read(*args)
    class Socket:
        def __init__(self):
            body = json.dumps(request() | dict(stream=True)).encode()
            self.raw = SlowInput(b'POST /v1/messages HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
            self.output = bytearray()
        def makefile(self, *args): return self.raw
        def settimeout(self, value): pass
        def sendall(self, data): self.output.extend(data)
    timeouts = []
    mock = transport(lambda _: httpx.Response(200, stream=Chunks()))
    def send(body, timeout):
        timeouts.append(timeout)
        return mock(body, timeout)
    sock = Socket()
    control.make_gateway_handler(ledger, policy, send)(sock, ('127.0.0.1', 1), object())
    if body_elapsed < 120:
        assert len(timeouts) == 1
        assert 0 < timeouts[0] <= 1
        assert b'200 OK' in sock.output
        assert totals(ledger, 'local-trial-1') == (1, 10)
    else:
        assert timeouts == []
        assert sock.output == b''
        assert totals(ledger, 'local-trial-1') == (0, 0)


def test_late_header_write_marks_attempt_uncertain(ledger, policy, monkeypatch):
    import io
    import json
    import time
    from ops.pi import control
    now = [time.monotonic()]
    monkeypatch.setattr(time, 'monotonic', lambda: now[0])
    class Socket:
        def __init__(self):
            body = json.dumps(request() | dict(stream=True)).encode()
            self.raw = io.BytesIO(b'POST /v1/messages HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
            self.writes = 0
        def makefile(self, *args): return self.raw
        def settimeout(self, value): pass
        def sendall(self, data):
            self.writes += 1
            now[0] += 121
    sock = Socket()
    control.make_gateway_handler(ledger, policy, transport(lambda _: httpx.Response(200, stream=Chunks())))(sock, ('127.0.0.1', 1), object())
    assert sock.writes == 1
    assert totals(ledger, 'local-trial-1') == (1, 10000)
    with ledger.transaction() as connection:
        rows = list(connection.execute("SELECT status FROM operations WHERE kind='model-attempt'"))
    assert [r['status'] for r in rows] == ['uncertain']


def test_expired_durable_permit_never_starts_transport(ledger, policy, monkeypatch):
    import time
    import ops.pi.model_gateway as gateway
    elapsed = [0.0]
    wall_start, monotonic_start = time.time(), time.monotonic()
    monkeypatch.setattr(time, 'time', lambda: wall_start + elapsed[0])
    monkeypatch.setattr(time, 'monotonic', lambda: monotonic_start + elapsed[0])
    real_reserve = gateway.reserve
    def slow_durable_reserve(*args):
        permit = real_reserve(*args)
        # The durable reservation commits after its existing absolute deadline.
        elapsed[0] = policy.timeout_seconds + 1
        return permit
    monkeypatch.setattr(gateway, 'reserve', slow_durable_reserve)
    calls = []
    def send(body, timeout):
        calls.append(body)
        return httpx.Response(200, json={'usage':{}})
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger,
                                policy=policy, transport=send)
    assert response.status_code == 502
    assert calls == []
    assert ledger.get(response.attempt_id)['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)
