"""Deterministic adapters exercise durable orchestration; all actions SIMULATED."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import pytest
from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger

NOW = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)


def module():
    assert (Path(__file__).parents[1] / 'iteration.py').is_file(), 'iteration dispatcher missing'
    return importlib.import_module('ops.pi.iteration')


def setup(tmp_path, *, fail=None):
    m = module(); ledger = Ledger(tmp_path / 'ledger.sqlite'); calls = []
    identity = dict(main='a'*40, source='b'*64, config='c'*64, owner='pi', generation=1, deployment_id='d1')
    def stage(context):
        calls.append(context['stage'])
        if context['stage'] == fail:
            return Receipt(context['operation_id'], 'blocked', {'reason':'budget_exhausted'})
        return Receipt(context['operation_id'], 'done', dict(verified=True, mode='SIMULATED',
            binding=context['input_hash'], comparison='improved', released=context['stage']=='release'))
    services = dict(mode='SIMULATED', identity=lambda:deepcopy(identity),
        stages={name:stage for name in m.STAGES}, recover=stage,
        hypothesis='cleaned byte fidelity', evidence_hash='e'*64, run_id='day-1', slice_id='capture')
    return m, ledger, services, calls, identity


def test_plan_before_any_patch(tmp_path):
    m, ledger, services, calls, _ = setup(tmp_path)
    result = m.run_iteration(ledger, 'exp1', NOW, services)
    assert result.status == 'done' and result.evidence['mode'] == 'SIMULATED'
    assert calls.index('plan') < calls.index('review') < calls.index('develop')
    assert calls.index('pre') < calls.index('develop')
    assert result.evidence['released'] is False
    assert result.evidence['simulated_release'] is True
    count = len(calls)
    assert m.run_iteration(Ledger(ledger.path), 'exp1', NOW, services) == result
    assert len(calls) == count


def test_pending_side_effect_is_never_blindly_replayed(tmp_path):
    m, ledger, services, calls, _ = setup(tmp_path)
    def crash(context):
        calls.append('develop-crash'); raise KeyboardInterrupt()
    services['stages']['develop'] = crash
    with pytest.raises(KeyboardInterrupt): m.run_iteration(ledger, 'exp1', NOW, services)
    result = m.run_iteration(Ledger(ledger.path), 'exp1', NOW, services)
    assert result.status == 'uncertain'
    assert result.evidence['next_action'] == 'reconcile'
    assert calls.count('develop-crash') == 1


def test_budget_stop_preserves_state_and_recovery(tmp_path):
    m, ledger, services, calls, _ = setup(tmp_path, fail='develop')
    result = m.run_iteration(ledger, 'exp1', NOW, services)
    assert result.status == 'blocked' and result.evidence['recovery']['status'] == 'done'
    assert result.evidence['next_action'] == 'save_and_reconcile'
    assert 'recover' in calls and 'verify' not in calls


@pytest.mark.parametrize('outcome', ['not_improved','regressed'])
def test_no_improvement_generates_diagnosis(tmp_path, outcome):
    m, ledger, services, calls, _ = setup(tmp_path)
    m.run_iteration(ledger, 'exp1', NOW, services)
    result = m.continue_experiment(ledger, 'exp1', dict(status=outcome, evidence_hash='f'*64))
    assert result.evidence['parent_experiment_id'] == 'exp1'
    assert result.evidence['reason'] == outcome
    assert result.evidence['next_action'] == 'diagnose'


def test_insufficient_evidence_extends_observation(tmp_path):
    m, ledger, services, calls, _ = setup(tmp_path)
    m.run_iteration(ledger, 'exp1', NOW, services)
    result = m.continue_experiment(ledger, 'exp1', dict(status='insufficient_evidence', evidence_hash='f'*64))
    assert result.evidence['next_action'] == 'extend_observation'


def test_new_main_rebases_and_retests(tmp_path):
    m, ledger, services, calls, identity = setup(tmp_path)
    first = m.run_iteration(ledger, 'exp1', NOW, services)
    identity['main'] = 'f'*40
    result = m.run_iteration(ledger, 'exp1', NOW, services)
    assert result.evidence['revision'] == 2
    assert result.evidence['parent_revision'] == first.operation_id
    assert calls.count('baseline') == calls.count('review') == calls.count('verify') == 2
    assert result.evidence['attribution'] == 'confounded'


def test_manual_change_confounds_not_blames_pi(tmp_path):
    m, ledger, services, calls, identity = setup(tmp_path, fail='develop')
    original = services['stages']['develop']
    def takeover(context):
        result = original(context); identity.update(owner='human', generation=2); return result
    services['stages']['develop'] = takeover
    result = m.run_iteration(ledger, 'exp1', NOW, services)
    assert result.evidence['attribution'] == 'confounded'
    assert result.evidence['recovery']['status'] == 'blocked'
    assert 'recover' not in calls


def test_same_hypothesis_without_new_evidence_not_repeated(tmp_path):
    m, ledger, services, calls, _ = setup(tmp_path)
    m.run_iteration(ledger, 'exp1', NOW, services)
    observations = dict(status='not_improved', evidence_hash='e'*64)
    result = m.continue_experiment(ledger, 'exp1', observations)
    assert result.evidence['repeat_hypothesis_allowed'] is False
    assert m.continue_experiment(ledger, 'exp1', observations) == result


@pytest.mark.parametrize('route', ['slice_id','scenario'])
def test_fixround1_routing_change_cannot_repeat_optimization(tmp_path,route):
    m,ledger,services,calls,_=setup(tmp_path)
    original=m.run_iteration(ledger,'exp1',NOW,services)
    services[route]='different-route'
    repeated=m.run_iteration(Ledger(ledger.path),'exp1',NOW,services)
    assert repeated==original
    assert calls.count('develop')==1


def test_fixround1_historical_hypothesis_dedup_and_new_evidence(tmp_path):
    m,ledger,services,calls,identity=setup(tmp_path)
    hypothesis=services['hypothesis']
    first=m.run_iteration(ledger,'exp1',NOW,services)
    services['hypothesis']='another falsifiable hypothesis'
    m.run_iteration(ledger,'exp1',NOW,services)
    services['hypothesis']=hypothesis
    assert m.run_iteration(ledger,'exp1',NOW,services)==first
    assert calls.count('develop')==2
    services['evidence_hash']='f'*64
    third=m.run_iteration(ledger,'exp1',NOW,services)
    assert third.evidence['revision']==3 and calls.count('develop')==3
    identity['main']='d'*40
    fourth=m.run_iteration(ledger,'exp1',NOW,services)
    assert fourth.evidence['revision']==4 and calls.count('baseline')==4
    assert calls.count('review')==calls.count('verify')==4


def test_fixround1_routed_pending_claim_never_dispatches_again(tmp_path):
    m,ledger,services,calls,_=setup(tmp_path)
    def crash(context):
        calls.append('develop-crash'); raise KeyboardInterrupt()
    services['stages']['develop']=crash
    with pytest.raises(KeyboardInterrupt): m.run_iteration(ledger,'exp1',NOW,services)
    def wrongly_replayed(context):
        calls.append('develop-crash')
        return Receipt(context['operation_id'],'done',dict(verified=True,mode='SIMULATED',binding=context['input_hash']))
    services['stages']['develop']=wrongly_replayed
    services['slice_id']='new-route'
    result=m.run_iteration(ledger,'exp1',NOW,services)
    assert result.status=='uncertain' and result.evidence['next_action']=='reconcile'
    assert calls.count('develop-crash')==1


def test_live_missing_acceptance_never_calls_adapters(tmp_path):
    m, ledger, services, calls, _ = setup(tmp_path)
    services['mode'] = 'ACTUAL'
    result = m.run_iteration(ledger, 'exp1', NOW, services)
    assert result.status == 'blocked' and not calls


@pytest.mark.parametrize('outcome', ['not_improved', 'regressed'])
def test_fixround2_historical_resume_keeps_followup_parent(tmp_path, monkeypatch, outcome):
    m, ledger, services, calls, identity = setup(tmp_path)
    original = services['stages']['compare']
    def compare(context):
        receipt = original(context)
        return Receipt(receipt.operation_id, receipt.status, dict(receipt.evidence, comparison=outcome))
    services['stages']['compare'] = compare
    services['stages']['diagnose'] = original
    finish = ledger.finish
    class StoppedAfterCompare(RuntimeError): pass
    def interrupted_finish(receipt):
        finish(receipt)
        row = ledger.get(receipt.operation_id)
        if row['kind'] == 'iteration_stage' and row['payload']['stage'] == 'compare':
            raise StoppedAfterCompare()
    monkeypatch.setattr(ledger, 'finish', interrupted_finish)
    with pytest.raises(StoppedAfterCompare):
        m.run_iteration(ledger, 'exp1', NOW, services)
    monkeypatch.setattr(ledger, 'finish', finish)
    first = m._records(ledger, 'iteration_revision', 'exp1')[0]
    assert first['status'] == 'pending'
    committed = m._records(ledger, 'iteration_stage', 'exp1')
    comparison_hash = m.digest([asdict(m._receipt(row)) for row in committed])
    # B deliberately owns A's comparison hash: choosing B would deny repetition,
    # while the same comparison is fresh evidence relative to A's original input.
    later = dict(services, hypothesis='different hypothesis', evidence_hash=comparison_hash,
                 stages=dict(services['stages'], compare=original))
    second = m.run_iteration(ledger, 'exp1', NOW, later)
    assert second.status == 'done' and second.operation_id != first['operation_id']
    count = len(calls)
    resumed = m.run_iteration(Ledger(ledger.path), 'exp1', NOW, services)
    assert resumed.status == 'done' and resumed.operation_id == first['operation_id']
    assert calls[count:] == (['recover', 'diagnose'] if outcome == 'regressed' else ['diagnose'])
    assert all(calls.count(stage) == 2 for stage in m.STAGES)
    followup, = m._records(ledger, 'iteration_followup', 'exp1')
    assert followup['payload']['parent_revision'] == first['operation_id']
    assert followup['evidence']['parent_revision'] == first['operation_id']
    assert followup['evidence']['evidence_hash'] == comparison_hash
    assert followup['evidence']['repeat_hypothesis_allowed'] is True
    for row in m._records(ledger, 'iteration_stage', 'exp1')[len(committed)*2:]:
        assert row['operation_id'].startswith(first['operation_id'] + ':')
        assert row['payload']['input_hash'] == m.digest(dict(
            parent=followup['operation_id'], stage=row['payload']['stage'], identity=identity))
    assert m.run_iteration(ledger, 'exp1', NOW, services) == resumed
    assert len(calls) == count + (2 if outcome == 'regressed' else 1)


def test_fixround2_explicit_parent_and_latest_default(tmp_path):
    m, ledger, services, calls, _ = setup(tmp_path)
    first = m.run_iteration(ledger, 'exp1', NOW, services)
    services['hypothesis'] = 'later hypothesis'
    services['evidence_hash'] = 'f'*64
    second = m.run_iteration(ledger, 'exp1', NOW, services)
    observations = dict(status='not_improved', evidence_hash='e'*64)
    latest = m.continue_experiment(ledger, 'exp1', observations)
    assert latest.evidence['parent_revision'] == second.operation_id
    assert latest.evidence['repeat_hypothesis_allowed'] is True
    bound = m.continue_experiment(ledger, 'exp1', observations, parent_revision=first.operation_id)
    assert bound.evidence['parent_revision'] == first.operation_id
    assert bound.evidence['repeat_hypothesis_allowed'] is False
    assert m.continue_experiment(ledger, 'exp1', observations, parent_revision=first.operation_id) == bound
    foreign = m.run_iteration(ledger, 'exp2', NOW, services)
    count = len(m._records(ledger, 'iteration_followup', 'exp1'))
    for invalid in ('absent-revision', foreign.operation_id, bound.operation_id):
        with pytest.raises(ValueError, match='parent revision'):
            m.continue_experiment(ledger, 'exp1', observations, parent_revision=invalid)
    assert len(m._records(ledger, 'iteration_followup', 'exp1')) == count


def test_cli_simulates_and_resume_keeps_identity(tmp_path, monkeypatch, capsys):
    from ops.pi.control import main
    monkeypatch.setattr('ops.pi.control.state_path_allowed', lambda _:True)
    policy_path=Path(__file__).parents[1]/'policy.example.json'
    try:
        code=main(['trial','run','--state-dir',str(tmp_path),'--policy',str(policy_path),'--scenario','success'])
    except SystemExit: code=2
    assert code==0, 'trial CLI missing'
    first=capsys.readouterr().out
    assert 'SIMULATED' in first and '"released": false' in first
    assert main(['trial','resume','--state-dir',str(tmp_path),'--experiment','local-trial-1'])==0
    assert json.loads(capsys.readouterr().out)==json.loads(first)


def test_cli_live_is_blocked_before_simulated_actions(tmp_path, monkeypatch, capsys):
    from ops.pi.control import main
    monkeypatch.setattr('ops.pi.control.state_path_allowed',lambda _:True)
    try:
        code=main(['trial','run','--state-dir',str(tmp_path),'--policy',str(Path(__file__).parents[1]/'policy.example.json'),
                   '--scenario','success','--live'])
    except SystemExit: code=2
    assert code==1
    assert 'blocked' in capsys.readouterr().out


def test_report_labels_simulated_release_and_canonical_spend():
    from ops.pi.reporting import render_report
    report=render_report([{'kind':'iteration_summary','payload':{'operation_id':'iteration-1','status':'done',
        'evidence':{'mode':'SIMULATED','released':False,'simulated_release':True,'counted_reservations':4,
        'charged_or_reserved_microyuan':6072790,'next_action':'observe_next_window','semantic_quality':'unknown'}}}],[])
    assert 'SIMULATED' in report and '6072790' in report and 'No release' in report


def test_concurrent_dispatch_claims_side_effect_once(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    m=module(); ledger=Ledger(tmp_path/'ledger.sqlite'); gate=Barrier(2); calls=[]
    original=ledger.get
    def racing_get(operation):
        row=original(operation)
        if row is None: gate.wait(timeout=5)
        return row
    monkeypatch.setattr(ledger,'get',racing_get)
    context=dict(operation_id='shared-stage',input_hash='a'*64,mode='SIMULATED',stage='develop')
    def action(context):
        calls.append('side_effect')
        return Receipt('shared-stage','done',{'verified':True,'binding':'a'*64,'mode':'SIMULATED'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts=list(pool.map(lambda _:m._run_action(ledger,context,action),range(2)))
    assert calls==['side_effect']
