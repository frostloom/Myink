"""Local Pi probe gateway must not turn invalid requests into passing evidence."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from ops.pi.analysis_execution import prepare_contract_slots
from ops.pi.analysis_trial import GROUPS
from ops.pi.tests.test_writing_analysis import fixture


def probe():
    path = Path(__file__).parents[1] / 'lab/pi-analysis-contract-probe.py'
    assert path.is_file(), 'actual Pi contract probe missing'
    spec = importlib.util.spec_from_file_location('pi_contract_probe', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def request(tmp_path):
    view, report = fixture()
    slot = prepare_contract_slots({d: view for d in GROUPS}, report,
        model='deepseek-v4.1-flash', cwd=tmp_path)[0]
    return slot, dict(slot=slot, attempts=0, accepted=0), {
        'x-api-key': 'local-contract-probe-only', 'x-pi-scope': 'local-trial-1'}


@pytest.mark.parametrize('bad', ['bind', 'path', 'query', 'token', 'scope', 'payload'])
def test_probe_rejects_wrong_destination_identity_or_payload(tmp_path, bad):
    mod = probe()
    slot, state, headers = request(tmp_path)
    bind, path, body = '127.0.0.1', '/v1/messages?beta=true', deepcopy(slot['request'])
    if bad == 'bind': bind = '0.0.0.0'
    elif bad == 'path': path = '/other'
    elif bad == 'query': path += '&extra=true'
    elif bad == 'token': headers['x-api-key'] = 'wrong'
    elif bad == 'scope': headers['x-pi-scope'] = 'other'
    elif bad == 'payload': body['tools'] = []
    with pytest.raises(ValueError):
        mod.accept_probe_request(bind, path, headers, body, state)
    assert state['accepted'] == 0
    assert state['attempts'] == 1


def test_probe_allows_exactly_one_actual_request_per_slot(tmp_path):
    mod = probe()
    slot, state, headers = request(tmp_path)
    assert mod.accept_probe_request('127.0.0.1', '/v1/messages?beta=true',
        headers, slot['request'], state) == slot['request_sha256']
    with pytest.raises(ValueError):
        mod.accept_probe_request('127.0.0.1', '/v1/messages?beta=true',
            headers, slot['request'], state)
    assert state['accepted'] == 1 and state['attempts'] == 2


def test_probe_import_does_not_require_pytest_runtime():
    import subprocess
    import sys
    root = Path(__file__).parents[3]
    script = root / 'ops/pi/lab/pi-analysis-contract-probe.py'
    code = "import sys,runpy;sys.path.insert(0,sys.argv[1]);sys.modules['pytest']=None;runpy.run_path(sys.argv[2])"
    result = subprocess.run([sys.executable, '-I', '-S', '-c', code, str(root), str(script)],
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode(errors='replace')


def test_post_request_exception_keeps_started_slot_failed(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from urllib.request import Request, urlopen
    mod = probe()
    node, cli = tmp_path / 'node', tmp_path / 'cli.js'
    node.write_bytes(b'synthetic runtime')
    cli.write_bytes(b'synthetic cli')
    root = tmp_path / 'run'
    monkeypatch.setattr(mod, '_check_probe_paths', lambda *args: None)
    monkeypatch.setattr(mod.os, 'getuid', lambda: 65534, raising=False)
    monkeypatch.setattr(mod.os, 'getgid', lambda: 65534, raising=False)
    monkeypatch.setattr(mod, 'PiAdapter', lambda *a, **kw: SimpleNamespace(**kw))
    def crash_after_request(**kwargs):
        models = json.loads((root / 'agent/models.json').read_text())
        url = models['providers']['myink-budget']['baseUrl'] + '/v1/messages?beta=true'
        request = Request(url, data=json.dumps(kwargs['slot']['request']).encode(),
            headers={'x-api-key': mod.MOCK_TOKEN, 'x-pi-scope': 'local-trial-1'})
        with urlopen(request, timeout=5) as response:
            assert response.status == 200
            response.read()
        raise RuntimeError('private untrusted error prose')
    monkeypatch.setattr(mod, 'run_contract_slot', crash_after_request)
    result = mod.run_probe(root, node, cli)
    assert result['passed'] is False
    assert result['not_run_slots'] == 29
    row, = result['results']
    assert row['mock_attempts'] == 1 and row['mock_accepted'] == 1
    assert row['execution_state'] == 'failed'
    assert row['failure_class'] == 'RuntimeError'
    assert 'private untrusted' not in json.dumps(result)
    assert (root / 'probe-summary.json').is_file()
