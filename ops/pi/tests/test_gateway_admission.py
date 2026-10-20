"""Host admission must precede canonical billing, using real HTTP requests."""
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from http.server import ThreadingHTTPServer
import json
from threading import Thread

import httpx
import pytest

from ops.pi import control
from ops.pi.analysis_execution import verify_contract_request
from ops.pi.budget import totals
from ops.pi.tests.test_budget import ledger, policy
from ops.pi.tests.test_model_gateway import transport
from ops.pi.tests.test_pi_gateway import PiStream, pi_request


TOKEN = 'synthetic-admission-token'
HEADERS = {'x-api-key': TOKEN, 'X-Pi-Scope': 'local-trial-1'}


@contextmanager
def gateway(ledger, policy, guard, calls):
    def provider(request):
        calls.append(json.loads(request.content))
        assert totals(ledger, 'local-trial-1') == (1, 10000)
        return httpx.Response(200, stream=PiStream(dict(input_tokens=7, output_tokens=0,
            cache_read_input_tokens=0, cache_creation_input_tokens=0)))

    handler = control.make_gateway_handler(ledger, policy, transport(provider),
        scope_token=TOKEN, request_guard=guard)
    with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
        server.daemon_threads = True
        worker = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        worker.start()
        try:
            with httpx.Client(trust_env=False, timeout=3) as client:
                yield client, 'http://127.0.0.1:' + str(server.server_port)
        finally:
            server.shutdown()
            worker.join(3)


@pytest.mark.parametrize('route', ['/v1/messages', '/v1/messages?beta=true'])
def test_frozen_request_guard_precedes_reservation(ledger, policy, route):
    body = pi_request()
    digest = sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                              separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    slot = {'request': body, 'request_sha256': digest}
    admitted, calls = [], []

    def guard(actual):
        assert totals(ledger, 'local-trial-1') == (0, 0)
        verify_contract_request(actual, slot)
        admitted.append(actual)
        return True

    with gateway(ledger, policy, guard, calls) as (client, base):
        for drift in [dict(max_tokens=999), dict(model='foreign'), dict(metadata={})]:
            response = client.post(base + route, headers=HEADERS, json=body | drift)
            assert response.status_code == 403
            assert totals(ledger, 'local-trial-1') == (0, 0)
            assert calls == []
        response = client.post(base + route, headers=HEADERS, json=body)
        assert response.status_code == 200 and 'Reviewed.' in response.text
    assert admitted == [body] and calls == [body]
    assert totals(ledger, 'local-trial-1') == (1, 54)


@pytest.mark.parametrize('result', [False, None, 1, 'approved', {}])
def test_non_true_admission_never_reserves(ledger, policy, result):
    calls = []
    with gateway(ledger, policy, lambda _: result, calls) as (client, base):
        response = client.post(base + '/v1/messages', headers=HEADERS, json=pi_request())
    assert response.status_code == 403 and calls == []
    assert totals(ledger, 'local-trial-1') == (0, 0)


@pytest.mark.parametrize('error', [ValueError, RuntimeError, TimeoutError])
def test_guard_exception_is_redacted_and_never_reserves(ledger, policy, error):
    calls = []
    def guard(_):
        raise error('private-body-and-secret')
    with gateway(ledger, policy, guard, calls) as (client, base):
        response = client.post(base + '/v1/messages', headers=HEADERS, json=pi_request())
    assert response.status_code == 403 and 'private-body-and-secret' not in response.text
    assert calls == [] and totals(ledger, 'local-trial-1') == (0, 0)


def test_authentication_and_strict_json_precede_guard(ledger, policy):
    calls, guards = [], []
    with gateway(ledger, policy, lambda body: guards.append(body) or True, calls) as (client, base):
        response = client.post(base + '/v1/messages', headers=HEADERS | {'x-api-key': 'wrong'},
                               json=pi_request())
        assert response.status_code == 403
        response = client.post(base + '/v1/messages', headers=HEADERS | {'Content-Type': 'application/json'},
                               content=b'{"model":"first","model":"second"}')
        assert response.status_code == 400
    assert guards == [] and calls == []
    assert totals(ledger, 'local-trial-1') == (0, 0)


@pytest.mark.parametrize('guard,token', [(True, TOKEN), (False, TOKEN), (lambda _: True, None)])
def test_invalid_host_guard_configuration_fails_at_startup(ledger, policy, guard, token):
    with pytest.raises(ValueError, match='request guard'):
        control.make_gateway_handler(ledger, policy, lambda *_: pytest.fail('provider'),
            scope_token=token, request_guard=guard)


def test_serve_gateway_wires_host_guard(tmp_path, ledger, policy, monkeypatch):
    guard = lambda _: True
    live = replace(policy, live_enabled=True, input_bound_calibrated=True,
                   prices=policy.prices | {'cache_write': '2'})
    credential = tmp_path / 'credentials.json'
    credential.write_text(json.dumps(dict(PLATFORM_MODEL_API_KEY='synthetic-only',
        PLATFORM_MODEL_BASE_URL=live.base_url, PLATFORM_MODEL_NAME=live.model,
        PLATFORM_MODEL_PROTOCOL=live.protocol)))
    received = []
    def handler(*args, **kwargs):
        received.append(kwargs)
        return object()
    class Server:
        def __init__(self, address, handler): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def serve_forever(self): pass
    monkeypatch.setattr(control, 'make_gateway_handler', handler)
    monkeypatch.setattr(control, 'ThreadingHTTPServer', Server)
    control.serve_gateway(ledger, live, credential, scope_token=TOKEN, request_guard=guard)
    assert received[0]['request_guard'] is guard
