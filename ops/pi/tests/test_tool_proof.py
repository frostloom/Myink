"""No network: exercise actual HTTP handler framing and immutable broker lookup."""
from copy import deepcopy
from dataclasses import asdict
import importlib
import io
import json
from pathlib import Path
import pytest
from ops.pi.tests.test_budget import policy
from ops.pi.tests.test_tools import setup, call
from ops.pi.tests.test_pi_gateway import Socket
from ops.pi.control import make_gateway_handler


def send(broker, policy, body, token='scoped-only', path='/v1/tool-proof'):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    headers = (('x-api-key: ' + token + '\r\n') if token else '') + 'X-Pi-Scope: local-trial-1\r\n'
    sock = Socket(headers.encode(), raw)
    sock.raw = io.BytesIO(sock.raw.getvalue().replace(b'/v1/messages', path.encode(), 1))
    make_gateway_handler(broker.ledger, policy, lambda *_: pytest.fail('proof reached model'),
                         scope_token='model-only', tool_broker=broker)(sock, ('127.0.0.1', 1), object())
    return sock.output


@pytest.mark.parametrize('fault', ['ok', 'blocked', 'missing', 'foreign', 'args', 'receipt', 'extra', 'oversize', 'authless', 'model_token', 'duplicate', 'nan', 'path'])
def test_proof_is_authenticated_readonly_exact_lookup(tmp_path, policy, fault):
    broker, cap, _, _ = setup(tmp_path, policy, phase='analysis')
    name = 'read_source' if fault == 'blocked' else 'candidate_status'
    args = {'path':'missing.py', 'start_line':1, 'end_line':1} if fault == 'blocked' else {}
    result = call(broker, cap, name, args, 'proof-1')
    body = dict(call_id='proof-1', name=name, arguments=args, receipt=asdict(result))
    with broker.ledger.transaction() as db:
        before = [tuple(r) for r in db.execute('SELECT * FROM operations')]
    token, path = 'scoped-only', '/v1/tool-proof'
    if fault == 'missing': body['call_id'] = 'absent'
    if fault == 'foreign': body['call_id'] = 'other-session'
    if fault == 'args': body['arguments'] = {'changed':True}
    if fault == 'receipt': body['receipt']['status'] = 'failed'
    if fault == 'extra': body['approve'] = True
    if fault == 'oversize': body['arguments'] = {'text':'x' * 32768}
    if fault == 'authless': token = None
    if fault == 'model_token': token = 'model-only'
    if fault == 'duplicate': body = b'{"call_id":"proof-1","call_id":"proof-1"}'
    if fault == 'nan': body['arguments'] = {'x':float('nan')}
    if fault == 'path': path += '?approve=true'
    output = send(broker, policy, body, token, path)
    if fault in ('ok', 'blocked'):
        assert b'200 OK' in output
        assert json.loads(output.split(b'\r\n\r\n', 1)[1]) == {'verified':True}
    else:
        assert b'"verified": true' not in output
    with broker.ledger.transaction() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM operations')] == before


def test_proof_client_rejects_oversize_and_non_boolean_response():
    path = Path(__file__).parents[1] / 'tool_proof.py'
    assert path.is_file(), 'fixed proof client missing'
    m = importlib.import_module('ops.pi.tool_proof')
    assert m.proof_bytes('id', 'candidate_status', {}, {})
    with pytest.raises(ValueError): m.proof_bytes('id', 'candidate_status', {'x':'a'*32768}, {})
    assert m.verified_response(b'{"verified":true}') is True
    for raw in (b'{"verified":1}', b'{"verified":"true"}', b'{"verified":true,"extra":0}', b'{"verified":true,"verified":true}'):
        assert m.verified_response(raw) is False
