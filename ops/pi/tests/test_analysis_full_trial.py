"""Full trial through real SQLite, loopback gateway and stdio children."""
import json
from pathlib import Path
import time

import pytest

from ops.pi.tests import test_analysis_launcher as pilot
from ops.pi.tests.test_analysis_launcher import setup  # Shared isolated synthetic inputs only.
from ops.pi.ledger import LedgerBlocked


def trial_config(config):
    return config | dict(schema='pi-analysis-trial-v1', failure_policy='continue_known_contract_failure')


def install(monkeypatch, failures=None, mode='known', fault=None):
    # Only the worker/container and external provider are simulated. Real host
    # verifier, gateway, at-most-once claims, budget and cleanup remain active.
    script = pilot.CHILD.replace('answer=fixture().synthetic_answer()', '''answer=fixture().synthetic_answer()
refs=answer['hypothesis']['refs']
for d in answer['domains']:
 d.update(availability='unknown',refs=[])
target=next(d for d in answer['domains'] if d['domain']==s['domain'])
target.update(availability='trace_observation',refs=refs)
failures=FAILURES
kind=failures.get(str(x['slot_index']))
if kind=='target':
 other='operations' if s['domain']!='operations' else 'recall.events'
 next(d for d in answer['domains'] if d['domain']==other).update(availability='trace_observation',refs=refs)
output_text='not JSON' if kind=='json' else '{}' if kind=='schema' else json.dumps(answer)
if kind in ('json','schema'): answer=None
valid=kind is None
failure=None if valid else 'target_scope_invalid' if kind=='target' else 'engine_or_output_invalid'
'''.replace('FAILURES', repr(failures or {})))
    script = script.replace('text=json.dumps(answer)', 'text=output_text')
    script = script.replace("engine_status='done',contract_valid=True,analysis=answer,",
        "engine_status='done',contract_valid=valid,analysis=answer,failure=failure,")
    script = script.replace("print(json.dumps(dict(type='result'", """r['evidence'].update(accepted=True,disposition='started',settled=True,config_hash='a'*64,
 aborted=False,errors=False,protocol_failed=False,transcript_failed=False,text=output_text)
print(json.dumps(dict(type='result'""")
    if fault is not None:
        script = script.replace("print(json.dumps(dict(type='result'", fault + "\nprint(json.dumps(dict(type='result'")
    monkeypatch.setattr(pilot, 'CHILD', script)
    return pilot.install_external_boundaries(monkeypatch, mode)


def test_trial_check_selects_all_thirty_without_side_effects(setup, monkeypatch):
    config, ledger, _, _, _ = setup
    config = trial_config(config)
    before = ledger.path.read_bytes()
    def forbidden(*args, **kwargs): pytest.fail('read-only check crossed execution boundary')
    m = pilot.api()
    monkeypatch.setattr(m, '_provider', forbidden)
    monkeypatch.setattr(m, 'Ledger', forbidden)
    monkeypatch.setattr(m.ProbeHost, 'create', forbidden)
    result = m.launch(config)
    assert result['status'] == 'checked' and result['selected_slots'] == 30
    assert before == ledger.path.read_bytes() and not Path(config['root']).exists()


@pytest.mark.parametrize('failures,expected', [({}, ['DONE']*30),
    ({'0':'target','1':'json','2':'schema'}, ['FAILED']*3+['DONE']*27)])
def test_trial_records_all_outcomes_and_continues_after_known_output_failure(setup, monkeypatch, failures, expected):
    config, ledger, _, _, _ = setup
    processes, calls, daemon = install(monkeypatch, failures)
    result = pilot.api().launch(trial_config(config), execute=True)
    assert result['status'] == 'completed'
    assert [s['status'] for s in result['slots']] == expected
    assert len(calls) == 30 and len(processes) == 30
    assert all(p.poll() == 0 for p in processes) and not daemon.objects
    assert len({row['session_id'] for row in result['cases']}) == 30
    assert all(row['http_statuses'] == [403,403,200,403] for row in result['cases'])
    summary = result['summary']
    assert summary['planned_slots'] == 30 and summary['not_run'] == 0 and summary['uncertain'] == 0
    assert summary['failed'] == len(failures) and summary['done'] == 30-len(failures)
    assert all(row['planned_slots'] == 15 for row in summary['by_arm'].values())
    assert all(row['planned_slots'] == 6 for row in summary['by_domain'].values())
    if failures:
        assert summary['by_arm']['baseline']['failed'] == 2
        assert summary['by_arm']['candidate']['failed'] == 1
        assert [row['failure'] for row in result['cases'][:3]] == ['target_scope_invalid','output_invalid','output_invalid']
        private = json.loads((Path(config['root'])/'slot-1-private.json').read_text())
        assert 'not JSON' in private['session']
    with ledger.transaction() as db:
        rows = db.execute("SELECT * FROM operations WHERE kind='model-attempt'").fetchall()
        assert len(rows) == 30 and all(row['status'] == 'done' for row in rows)
    public = json.dumps(result)
    assert 'not JSON' not in public and 'sk-synthetic' not in public and str(ledger.path) not in public
    with pytest.raises(LedgerBlocked):
        pilot.api().launch(trial_config(config)|{'root':str(Path(config['root']).with_name('retry'))}, execute=True)
    assert len(calls) == 30


def test_pilot_still_stops_at_the_same_contract_failure(setup, monkeypatch):
    config, _, _, _, _ = setup
    processes, calls, daemon = install(monkeypatch, {'0':'target'})
    result = pilot.api().launch(config, execute=True)
    assert result['status'] == 'blocked'
    assert [s['status'] for s in result['slots']] == ['UNCERTAIN']+['NOT_RUN']*29
    assert len(calls) == 1 and len(processes) == 1 and not daemon.objects


@pytest.mark.parametrize('mode', ['unknown','cleanup-failure','duplicate-session'])
def test_trial_does_not_continue_past_execution_or_billing_failures(setup, monkeypatch, mode):
    config, _, _, _, _ = setup
    processes, calls, daemon = install(monkeypatch, {'0':'target'}, mode)
    result = pilot.api().launch(trial_config(config), execute=True)
    assert result['status'] == 'blocked'
    if mode == 'duplicate-session':
        assert [s['status'] for s in result['slots']] == ['FAILED','UNCERTAIN']+['NOT_RUN']*28
        assert len(calls) == 2
    else:
        assert [s['status'] for s in result['slots']] == ['UNCERTAIN']+['NOT_RUN']*29
        assert len(calls) == 1
    assert result['summary']['not_run'] == 30-len(calls)
    assert all(p.poll() is not None for p in processes)
    if mode != 'cleanup-failure': assert not daemon.objects


@pytest.mark.parametrize('change', [{'failure_policy':'continue_any_failure'}, {'failure_policy':True},
    {'selected_slots':2}, {'schema':'pi-analysis-launch-v1'}, {'schema':'pi-analysis-launch-v2'}])
def test_trial_policy_is_explicit_and_cannot_be_downgraded(setup, change):
    config, ledger, _, _, _ = setup
    before = ledger.path.read_bytes()
    with pytest.raises(LedgerBlocked): pilot.api().launch(trial_config(config)|change, execute=True)
    assert ledger.path.read_bytes() == before and not Path(config['root']).exists()


def test_partial_budget_keeps_unrun_denominator_and_never_retries(setup, monkeypatch):
    config, _, _, _, _ = setup
    processes, calls, daemon = install(monkeypatch, {'0':'target'})
    result = pilot.api().launch(trial_config(config)|{'cap_microyuan':19384}, execute=True)
    assert result['status'] == 'blocked' and 0 < len(calls) < 30
    assert result['slots'][0]['status'] == 'FAILED'
    assert result['summary']['planned_slots'] == 30
    assert result['summary']['not_run']+result['summary']['done']+result['summary']['failed']+result['summary']['uncertain'] == 30
    assert all(p.poll() is not None for p in processes) and not daemon.objects


@pytest.mark.parametrize('fault', ["r['request_sha256']='0'*64", "r['evidence']['session_sha256']='0'*64",
    "r['evidence']['errors']=True", "r['evidence']['verified_tool_calls']=['forbidden']",
    "r['contract_valid']=True"])
def test_output_failure_does_not_mask_invalid_protocol_evidence(setup, monkeypatch, fault):
    config, _, _, _, _ = setup
    processes, calls, daemon = install(monkeypatch, {'0':'target'}, fault=fault)
    result = pilot.api().launch(trial_config(config), execute=True)
    assert result['status'] == 'blocked'
    assert [s['status'] for s in result['slots']] == ['UNCERTAIN']+['NOT_RUN']*29
    assert result['summary']['failed'] == 0 and result['summary']['uncertain'] == 1
    assert len(calls) == 1 and all(p.poll() is not None for p in processes) and not daemon.objects


def test_deadline_expiring_during_cleanup_blocks_even_known_output_failure(setup, monkeypatch):
    config, _, _, _, _ = setup
    processes, calls, daemon = install(monkeypatch, {'0':'target'})
    m = pilot.api()
    original = m.ProbeHost.cleanup
    def cleanup(self, cid):
        cleaned = original(self, cid)
        monkeypatch.setattr(m.time, 'time', lambda: config['deadline']+1)
        return cleaned
    monkeypatch.setattr(m.ProbeHost, 'cleanup', cleanup)
    result = m.launch(trial_config(config), execute=True)
    assert result['status'] == 'blocked'
    assert [s['status'] for s in result['slots']] == ['UNCERTAIN']+['NOT_RUN']*29
    assert result['summary']['failed'] == 0
    assert len(calls) == 1 and all(p.poll() is not None for p in processes) and not daemon.objects


def test_raw_session_error_stops_after_one_known_output_failure(setup, monkeypatch):
    config, _, _, _, _ = setup
    fault = ("session=session.replace('\"stopReason\": \"stop\"', "
        "'\"stopReason\": \"stop\", \"errorMessage\": \"execution failed\"');"
        "r['evidence']['session_sha256']=hashlib.sha256(session.encode()).hexdigest()")
    processes, calls, daemon = install(monkeypatch, {'0':'target'}, fault=fault)
    result = pilot.api().launch(trial_config(config), execute=True)
    assert result['status'] == 'blocked'
    assert [s['status'] for s in result['slots']] == ['UNCERTAIN']+['NOT_RUN']*29
    assert len(calls) == 1 and all(p.poll() is not None for p in processes) and not daemon.objects
