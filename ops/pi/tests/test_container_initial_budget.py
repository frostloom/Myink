"""Large retained-report shapes use synthetic metadata, no Docker or paid requests."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ops.pi import analysis_launcher as launcher, container_runtime as runtime
from ops.pi.analysis_execution import _hash, prepare_contract_slots
from ops.pi.lab.container_runtime_worker import prepare_initial
from ops.pi.ledger import LedgerBlocked
from ops.pi.tests.test_analysis_launcher import setup


def large_inputs(config, *, padding=300000):
    inputs = json.loads(Path(config['input_path']).read_text())
    inputs['report']['retained_report_metadata'] = 'x' * padding
    Path(config['input_path']).write_text(json.dumps(inputs))
    config['expected_input_sha256'] = _hash(inputs)
    slots = prepare_contract_slots(inputs['views'], inputs['report'],
        model='deepseek-flash', cwd=Path('/work/candidate'))
    return inputs, slots


def test_launcher_accepts_complete_large_report_without_changing_model_request(setup):
    config, ledger, _, _, _ = setup
    original = json.loads(Path(config['input_path']).read_text())
    old = prepare_contract_slots(original['views'], original['report'],
        model='deepseek-flash', cwd=Path('/work/candidate'))
    inputs, slots = large_inputs(config)
    before = ledger.path.read_bytes()
    result = launcher.launch(config)
    assert result['status'] == 'checked' and not Path(config['root']).exists()
    assert ledger.path.read_bytes() == before
    assert [s['request_sha256'] for s in slots] == [s['request_sha256'] for s in old]
    assert slots[0]['report_sha256'] == _hash(inputs['report']) != old[0]['report_sha256']


def test_worker_retains_complete_large_report_and_frozen_identity(setup):
    config, _, _, _, _ = setup
    inputs, slots = large_inputs(config)
    value = launcher._initial(config, inputs, slots[0], 0, 'a' * 64)
    parsed = prepare_initial(value)
    assert parsed['report'] == inputs['report']
    assert parsed['slot'] == slots[0]
    assert len(parsed['report']['retained_report_metadata']) == 300000


@pytest.mark.parametrize('kind', ['oversize', 'drift'])
def test_large_initial_still_rejects_oversize_or_slot_drift(setup, kind):
    config, _, _, _, _ = setup
    inputs, slots = large_inputs(config, padding=600000 if kind == 'oversize' else 300000)
    value = launcher._initial(config, inputs, slots[0], 0, 'a' * 64)
    if kind == 'drift':
        value['slot']['report_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        prepare_initial(value)
    if kind == 'oversize':
        with pytest.raises(LedgerBlocked):
            launcher.launch(config)


@pytest.mark.parametrize('size,accepted', [(524288, True), (524289, False)])
def test_real_stdio_initial_limit_counts_encoded_bytes_and_newline(size, accepted):
    # Non-ASCII marker catches code-point rather than wire-byte counting.
    initial = {'data': '汉'}
    overhead = len(json.dumps(initial, ensure_ascii=True).encode()) + 1
    initial['data'] += 'x' * (size - overhead)
    assert len(json.dumps(initial, ensure_ascii=True).encode()) + 1 == size
    script = '''import sys,json
raw=sys.stdin.buffer.readline()
print(json.dumps(dict(type='result',result={'bytes':len(raw)},session='',runtime={})),flush=True)
'''
    child = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        if accepted:
            result = runtime.exchange(child, initial, lambda f, s: None, seconds=3)
            assert result['result']['bytes'] == size
        else:
            with pytest.raises(ValueError):
                runtime.exchange(child, initial, lambda f, s: None, seconds=3)
    finally:
        child.kill(); child.wait(); child.stdin.close(); child.stdout.close()


def test_large_allowance_never_applies_to_relay_reply():
    script = '''import sys,json
sys.stdin.readline()
print(json.dumps(dict(type='request',path='/v1/messages',headers=[],body='{}')),flush=True)
sys.stdin.readline()
'''
    child = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        with pytest.raises(ValueError):
            runtime.exchange(child, {}, lambda f, s: {'status': 200, 'body': 'x' * 250000}, seconds=3)
    finally:
        child.kill(); child.wait(); child.stdin.close(); child.stdout.close()
    assert runtime.FRAME_LIMIT == 196608
    with pytest.raises(ValueError):
        runtime.parse_frame(json.dumps(dict(type='result', result={}, session='x' * 200000, runtime={})).encode())
