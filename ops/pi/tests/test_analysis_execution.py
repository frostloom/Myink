"""Contract execution seams; synthetic evidence, no external model calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import json

import pytest

from ops.pi.analysis_trial import GROUPS
from ops.pi.contracts import Receipt
from ops.pi.engine import EngineSession
from ops.pi.tests.test_writing_analysis import fixture, plan


def module():
    assert importlib.util.find_spec('ops.pi.analysis_execution'), 'contract execution seam missing'
    return importlib.import_module('ops.pi.analysis_execution')


def prepared(tmp_path):
    view, report = fixture()
    slots = module().prepare_contract_slots(
        {group: view for group in GROUPS}, report, model='deepseek-v4.1-flash', cwd=tmp_path)
    return slots, view, report


class Engine:
    def __init__(self, result=None, status='done', overrides=None):
        self.calls = []
        self.result = plan() if result is None else result
        self.status = status
        self.overrides = overrides or {}

    def run_phase(self, **kwargs):
        self.calls.append(kwargs)
        evidence = dict(
            process_exited=True, accepted=True, disposition='started', settled=True,
            config_hash=kwargs['session'].config_hash, returncode=0, session_valid=True,
            session_sha256='b' * 64, clear_abort_acknowledged=True,
            unexpected_tool=False, aborted=False, errors=False, protocol_failed=False,
            transcript_failed=False, text=json.dumps(self.result, ensure_ascii=False),
            )
        evidence.update(self.overrides)
        return Receipt('synthetic-operation', self.status, evidence)


def run(tmp_path, slots, view, report, engine, **changes):
    args = dict(slot=slots[0], view=view, report=report, engine=engine,
        session=EngineSession('pi', 'a' * 64, 'analysis', tmp_path / 'new.jsonl'),
        deadline=datetime.now(timezone.utc) + timedelta(seconds=30),
        model='deepseek-v4.1-flash', cwd=tmp_path)
    args.update(changes)
    return module().run_contract_slot(**args)


def test_thirty_slots_alternate_arms_and_keep_actual_system_constant(tmp_path):
    slots, _, _ = prepared(tmp_path)
    assert len(slots) == 30
    assert len({s['slot_id'] for s in slots}) == 30
    for repeat in range(1, 4):
        rows = slots[(repeat - 1) * 10:repeat * 10]
        assert [s['domain'] for s in rows] == [g for g in GROUPS for _ in range(2)]
        assert [s['arm'] for s in rows] == (
            ['baseline', 'candidate'] if repeat != 2 else ['candidate', 'baseline']) * 5
    assert len({s['system_sha256'] for s in slots}) == 1
    assert all(s['request']['max_tokens'] == 2048 for s in slots)
    assert all(s['request']['thinking'] == {'type': 'disabled'} for s in slots)
    assert all('tools' not in s['request'] for s in slots)
    other, _, _ = prepared(tmp_path / 'different-cwd')
    assert other[0]['system_sha256'] != slots[0]['system_sha256']


@pytest.mark.parametrize('change', ['prompt', 'arm', 'view', 'report', 'model', 'cwd'])
def test_drift_is_denied_before_engine_invocation(tmp_path, change):
    slots, view, report = prepared(tmp_path)
    engine = Engine()
    changes = {}
    if change == 'prompt': slots[0]['request']['messages'][0]['content'][0]['text'] += 'changed'
    elif change == 'arm': slots[0]['arm'] = 'candidate'
    elif change == 'view': view['evidence'][0]['excerpts'][0]['text'] = 'other'
    elif change == 'report': report['operations']['write']['success']['value'] = 0.25
    elif change == 'model': changes['model'] = 'other-model'
    elif change == 'cwd': changes['cwd'] = tmp_path / 'other'
    with pytest.raises(ValueError): run(tmp_path, slots, view, report, engine, **changes)
    assert engine.calls == []


@pytest.mark.parametrize('change', ['tools', 'system', 'message', 'extra', 'model', 'max_tokens'])
def test_actual_wire_drift_rejected(tmp_path, change):
    slots, _, _ = prepared(tmp_path)
    body = deepcopy(slots[0]['request'])
    if change == 'tools': body['tools'] = []
    elif change == 'system': body['system'][0]['text'] += '\nchanged'
    elif change == 'message': body['messages'][0]['content'][0]['text'] += 'changed'
    elif change == 'extra': body['temperature'] = 1
    elif change == 'model': body['model'] = 'other-model'
    elif change == 'max_tokens': body['max_tokens'] = 2048.0
    with pytest.raises(ValueError): module().verify_contract_request(body, slots[0])


def test_request_identity_ignores_key_order_only(tmp_path):
    slots, _, _ = prepared(tmp_path)
    body = dict(reversed(list(slots[0]['request'].items())))
    assert module().verify_contract_request(body, slots[0]) == slots[0]['request_sha256']


def test_adapter_done_requires_common_target_scoring(tmp_path):
    slots, view, report = prepared(tmp_path)
    result = plan()
    next(row for row in result['domains'] if row['domain'] == 'operations')['availability'] = 'trace_observation'
    engine = Engine(result)
    receipt = run(tmp_path, slots, view, report, engine)
    assert len(engine.calls) == 1
    assert receipt['contract_valid'] is False
    assert receipt['failure'] == 'target_scope_invalid'
    assert receipt['engine_status'] == 'done'


def test_valid_contract_still_does_not_grant_billing_or_release(tmp_path):
    slots, view, report = prepared(tmp_path)
    engine = Engine()
    receipt = run(tmp_path, slots, view, report, engine)
    assert receipt['contract_valid'] is True
    assert receipt['semantic_metrics'] == 'unknown'
    assert receipt['automatic_execution'] is False and receipt['release_allowed'] is False
    assert receipt['billing_verified'] is False
    call, = engine.calls
    assert call['tools'] == [] and call['phase'] == 'analysis'
    assert call['prompt'] == slots[0]['request']['messages'][0]['content'][0]['text']
    assert call['context'].budget_scope_id == 'local-trial-1'


@pytest.mark.parametrize('mode', ['pending', 'malformed', 'wrong_config'])
def test_failure_preserves_slot_and_never_retries(tmp_path, mode):
    slots, view, report = prepared(tmp_path)
    engine = Engine(status='pending' if mode == 'pending' else 'done')
    if mode == 'malformed': engine.result = {'invalid': True}
    if mode == 'wrong_config': engine.overrides['config_hash'] = 'c' * 64
    receipt = run(tmp_path, slots, view, report, engine)
    assert receipt['slot_id'] == slots[0]['slot_id']
    assert receipt['contract_valid'] is False
    assert len(engine.calls) == 1
    assert receipt['evidence']['text']  # Private raw failure retained, not repaired.


@pytest.mark.parametrize('mode', ['resume', 'existing', 'naive', 'expired', 'too_long'])
def test_invalid_session_or_deadline_never_launches(tmp_path, mode):
    slots, view, report = prepared(tmp_path)
    path = tmp_path / 'new.jsonl'
    changes = {}
    if mode == 'existing': path.write_text('old')
    if mode == 'resume': changes['session'] = EngineSession('pi', 'a' * 64, 'analysis', path, resume=True)
    now = datetime.now(timezone.utc)
    if mode == 'naive': changes['deadline'] = now.replace(tzinfo=None)
    elif mode == 'expired': changes['deadline'] = now - timedelta(seconds=1)
    elif mode == 'too_long': changes['deadline'] = now + timedelta(seconds=91)
    engine = Engine()
    with pytest.raises(ValueError): run(tmp_path, slots, view, report, engine, **changes)
    assert not engine.calls
