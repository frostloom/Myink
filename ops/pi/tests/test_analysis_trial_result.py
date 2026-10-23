"""Trial verdicts must distinguish output errors from broken execution evidence."""
from copy import deepcopy
from hashlib import sha256
import importlib
import json

import pytest

from ops.pi.tests.test_container_runtime import valid_result


def api():
    assert importlib.util.find_spec('ops.pi.analysis_trial_result'), 'trial verifier missing'
    return importlib.import_module('ops.pi.analysis_trial_result')


def set_text(frame, text):
    rows = [json.loads(line) for line in frame['session'].splitlines()]
    rows[-1]['message']['content'][0]['text'] = text
    frame['session'] = ''.join(json.dumps(row) + '\n' for row in rows)
    frame['result']['evidence'].update(text=text, session_sha256=sha256(frame['session'].encode()).hexdigest())


@pytest.fixture
def case(tmp_path):
    frame, slot, view, report = valid_result(tmp_path)
    text = json.dumps(frame['result']['analysis'])
    frame['result']['failure'] = None
    frame['result']['evidence'].update(accepted=True, disposition='started', settled=True,
        config_hash='a'*64, aborted=False, errors=False, protocol_failed=False,
        transcript_failed=False, text=text)
    return frame, slot, view, report


def test_valid_output_remains_a_contract_success(case):
    row = api().verify_trial_result(*case)
    assert row['contract_valid'] is True and row['failure'] is None
    assert row['session_id'] == 'fresh'
    assert 'analysis' not in row and 'text' not in row


@pytest.mark.parametrize('text', ['not JSON', '{}', '{"domains":[],"domains":[]}', 'NaN'])
def test_invalid_output_is_known_failure_only_with_intact_session(case, text):
    frame, slot, view, report = case
    set_text(frame, text)
    frame['result'].update(contract_valid=False, analysis=None, failure='engine_or_output_invalid')
    row = api().verify_trial_result(*case)
    assert row['contract_valid'] is False and row['failure'] == 'output_invalid'
    assert row['session_id'] == 'fresh'


def test_non_target_observation_is_failed_without_repair(case):
    frame, slot, view, report = case
    answer = deepcopy(frame['result']['analysis'])
    row = next(d for d in answer['domains'] if d['domain'] == 'operations')
    row.update(availability='trace_observation', observation='synthetic operations', refs=[])
    set_text(frame, json.dumps(answer))
    frame['result'].update(analysis=answer, contract_valid=False, failure='target_scope_invalid')
    before = deepcopy(frame)
    result = api().verify_trial_result(*case)
    assert result['failure'] == 'target_scope_invalid' and result['contract_valid'] is False
    assert frame == before


@pytest.mark.parametrize('change', ['request', 'fingerprint', 'tool', 'runtime', 'verdict', 'analysis',
    'engine', 'errors', 'protocol', 'text', 'boolean-returncode', 'missing-flag', 'duplicate-session', 'empty-session-id'])
def test_invalid_boundary_or_worker_disagreement_never_becomes_output_failure(case, change):
    frame, slot, view, report = case
    result = frame['result']; evidence = result['evidence']
    if change == 'request': result['request_sha256'] = '0'*64
    elif change == 'fingerprint': frame['session'] += '{}\n'
    elif change == 'tool': evidence['verified_tool_calls'] = ['forbidden']
    elif change == 'runtime': frame['runtime']['network_denied'] = False
    elif change == 'verdict': result['contract_valid'] = False
    elif change == 'analysis': result['analysis'] = {}
    elif change == 'engine': result['engine_status'] = 'failed'
    elif change == 'errors': evidence['errors'] = True
    elif change == 'protocol': evidence['protocol_failed'] = True
    elif change == 'text': evidence['text'] = 'different output'
    elif change == 'boolean-returncode': evidence['returncode'] = False
    elif change == 'missing-flag': del evidence['accepted']
    else:
        rows = [json.loads(line) for line in frame['session'].splitlines()]
        if change == 'duplicate-session': rows.append(rows[0])
        else: rows[0]['id'] = ''
        frame['session'] = ''.join(json.dumps(row)+'\n' for row in rows)
        evidence['session_sha256'] = sha256(frame['session'].encode()).hexdigest()
    with pytest.raises(ValueError): api().verify_trial_result(*case)


@pytest.mark.parametrize('fault', ['missing-newline', 'not-message', 'assistant-error', 'blank-output'])
def test_rejected_engine_session_cannot_be_reclassified_as_ordinary_output_failure(case, fault):
    frame, _, _, _ = case
    set_text(frame, '   ' if fault == 'blank-output' else 'not JSON')
    frame['result'].update(contract_valid=False, analysis=None, failure='engine_or_output_invalid')
    rows = [json.loads(line) for line in frame['session'].splitlines()]
    if fault == 'not-message': rows[-1]['type'] = 'custom'
    elif fault == 'assistant-error': rows[-1]['message']['errorMessage'] = 'execution failed'
    frame['session'] = ''.join(json.dumps(row)+'\n' for row in rows)
    if fault == 'missing-newline': frame['session'] = frame['session'].rstrip('\n')
    frame['result']['evidence']['session_sha256'] = sha256(frame['session'].encode()).hexdigest()
    with pytest.raises(ValueError): api().verify_trial_result(*case)
