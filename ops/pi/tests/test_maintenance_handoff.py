"""Finite handoff control; fake adapters are explicitly SIMULATED."""
from copy import deepcopy
from threading import Event, Thread
from types import SimpleNamespace
from pathlib import Path

import pytest

from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger
from ops.pi.development_inputs import authorization_hash, digest
from ops.pi.tests.test_development_inputs import config_file
from ops.pi import maintenance_handoff as handoff


@pytest.fixture
def cycle(tmp_path, monkeypatch):
    task = dict(task_id='visit', problem='Existing explicit first visit is missed',
        source_sha256='a'*64, evidence_sha256='b'*64, test_sha256='c'*64,
        test_cases=['fixed_development_tests.Case.test_visit'], files=['src/myink/validation/l1.py'],
        baseline=dict(tests=1, cases=['fixed_development_tests.Case.test_visit'], failures=1,
            errors=0, skipped=0, failed_cases=['fixed_development_tests.Case.test_visit'], error_cases=[]))
    c = dict(run_id='fresh-development',source_sha256=task['source_sha256'],test_sha256=task['test_sha256'],
        test_cases=task['test_cases'],ledger_path=str(tmp_path/'paid.sqlite'),deadline_seconds=50)
    plan = SimpleNamespace(files=tuple(task['files']))
    current = [task['source_sha256']]; now = [100.0]; calls=[]
    proposal = dict(task_id='visit',source_sha256=task['source_sha256'],evidence_sha256=task['evidence_sha256'],reason='fix demonstrated omission')
    def receipt(ctx, **evidence):
        return Receipt(ctx['operation_id'],'done',dict(verified=True,mode='SIMULATED',binding=ctx['input_hash'],**evidence))
    def analyze(ctx):
        calls.append('analyze');return receipt(ctx,proposal=deepcopy(proposal))
    config = tmp_path/'development.json';config.write_text('{}');config.chmod(0o600)
    def prepare(ctx):
        calls.append('prepare');return receipt(ctx,config_path=str(config),config_sha256=handoff.file_hash(config))
    result = dict(verified=True,run_id=c['run_id'],authorization_sha256=authorization_hash(c),
        new_unknown=0,policy_restored=True,original_history_unchanged=True,
        cleanup=[dict(removed=True)],candidate_sha256='d'*64,candidate_path=str(tmp_path/'candidate'))
    def execute(path, **kwargs):
        calls.append('execute');assert path==str(config)
        assert kwargs['expected_authorization_sha256']==authorization_hash(c)
        return deepcopy(result)
    monkeypatch.setattr(handoff,'preflight',lambda _: (deepcopy(c),None,plan,dict(reproduction=deepcopy(task['baseline'])),None,None,None))
    (tmp_path/'paid.sqlite').write_bytes(b'simulated billing identity only')
    ledger=Ledger(tmp_path/'control.sqlite')
    opts=dict(billing_ledger_path=str(tmp_path/'paid.sqlite'),source_identity=lambda:current[0],analyze=analyze,prepare_development=prepare,
        mode='SIMULATED',deadline=200.0,clock=lambda:now[0],execute=execute)
    return SimpleNamespace(task=task,c=c,plan=plan,current=current,now=now,calls=calls,
        proposal=proposal,result=result,ledger=ledger,opts=opts,config=config,receipt=receipt)


def run(x, **kwargs):
    return handoff.run_local_development(x.ledger.path,'cycle1',[x.task],**(x.opts|kwargs))


def test_full_handoff_and_no_replay(cycle):
    x=cycle;r=run(x)
    assert r.status=='done' and r.evidence['next_action']=='review_candidate'
    assert r.evidence['mode']=='SIMULATED' and r.evidence['released'] is False
    assert x.calls==['analyze','prepare','execute']
    assert run(x)==r and x.calls==['analyze','prepare','execute']


def test_no_work_never_prepares_or_pays(cycle):
    x=cycle;x.proposal.update(task_id=None,source_sha256=None,evidence_sha256=None)
    r=run(x);assert r.status=='done' and r.evidence['next_action']=='observe'
    assert x.calls==['analyze']


@pytest.mark.parametrize('change',[
    {'task_id':'outside'}, {'source_sha256':'e'*64}, {'evidence_sha256':'f'*64},
    {'permission':'approve'}, {'reason':''}, {'task_id':None}, {'reason':'x'*4097},
])
def test_bad_proposal_never_prepares(cycle,change):
    x=cycle;x.proposal.update(change);r=run(x)
    assert r.status=='blocked' and x.calls==['analyze']


@pytest.mark.parametrize('change',[
    {'source_sha256':'e'*64}, {'test_sha256':'f'*64},
    {'test_cases':['fixed_development_tests.Case.test_wrong']}, {'deadline_seconds':101},
])
def test_prepared_wrong_task_or_time_never_executes(cycle,change):
    x=cycle;x.c.update(change);r=run(x)
    assert r.status=='blocked' and x.calls==['analyze','prepare']


def test_prepared_other_files_never_executes(cycle):
    x=cycle;x.plan.files=('src/other.py',);assert run(x).status=='blocked'
    assert 'execute' not in x.calls


def test_config_drift_before_handoff_never_executes(cycle):
    x=cycle;original=x.opts['prepare_development']
    def prepare(ctx):
        r=original(ctx);x.config.write_text('{"changed":true}');return r
    assert run(x,prepare_development=prepare).status=='blocked'
    assert 'execute' not in x.calls


@pytest.mark.parametrize('stage',['analyze','prepare_development'])
def test_unverified_stage_never_pays(cycle,stage):
    x=cycle
    def invalid(ctx):return Receipt(ctx['operation_id'],'done',dict(verified=True,mode='ACTUAL',binding=ctx['input_hash']))
    assert run(x,**{stage:invalid}).status=='blocked';assert 'execute' not in x.calls


def test_review_preflight_rejection_never_pays(cycle,monkeypatch):
    monkeypatch.setattr(handoff,'preflight',lambda _: (_ for _ in ()).throw(ValueError('independent review denied')))
    assert run(cycle).status=='blocked';assert 'execute' not in cycle.calls


def test_identity_change_after_analysis_stops_prepare(cycle):
    x=cycle;old=x.opts['analyze']
    def analyze(ctx):r=old(ctx);x.current[0]='e'*64;return r
    assert run(x,analyze=analyze).status=='blocked';assert x.calls==['analyze']


def test_cancellation_before_analysis(cycle):
    cancel=Event();cancel.set();assert run(cycle,cancel=cancel).status=='blocked'
    assert cycle.calls==[]


def test_deadline_after_analysis_stops_prepare(cycle):
    x=cycle;old=x.opts['analyze']
    def analyze(ctx):r=old(ctx);x.now[0]=201;return r
    assert run(x,analyze=analyze).status=='blocked';assert x.calls==['analyze']


def test_pending_cycle_is_uncertain_and_not_replayed(cycle):
    x=cycle
    def crash(ctx):raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):run(x,analyze=crash)
    assert run(x).status=='uncertain';assert x.calls==[]


def test_adapter_exception_stays_uncertain(cycle):
    x=cycle
    def fail(ctx):raise RuntimeError('not known whether a request was sent')
    r=run(x,analyze=fail);assert r.status=='uncertain'
    assert run(x)==r and x.calls==[]


@pytest.mark.parametrize('field,value',[
    ('verified',False),('verified',1),('new_unknown',1),('new_unknown',False),
    ('policy_restored',False),('original_history_unchanged',False),('cleanup',[]),
    ('cleanup',[{'removed':False}]),('cleanup',[{'removed':1}]),
    ('run_id','wrong'),('authorization_sha256','e'*64),('candidate_sha256','a'*64),
])
def test_development_incomplete_is_never_success(cycle,field,value):
    x=cycle;x.result[field]=value;r=run(x)
    assert r.status!='done' and x.calls==['analyze','prepare','execute']
    assert run(x)==r and x.calls.count('execute')==1


def test_concurrent_cycle_runs_analysis_once(cycle):
    x=cycle;entered=Event();release=Event();results=[];old=x.opts['analyze']
    def analyze(ctx):entered.set();assert release.wait(5);return old(ctx)
    thread=Thread(target=lambda:results.append(run(x,analyze=analyze)));thread.start()
    assert entered.wait(5)
    try:assert run(x).status=='uncertain' and not x.calls
    finally:release.set();thread.join(5)
    assert not thread.is_alive() and results[0].status=='done' and x.calls.count('execute')==1


def test_input_mutation_is_not_authority(cycle):
    x=cycle;old=x.opts['analyze']
    def analyze(ctx):ctx['tasks'][0]['files']=['ops/pi/budget.py'];return old(ctx)
    assert run(x,analyze=analyze).status=='done' and x.plan.files==tuple(x.task['files'])


def test_same_cycle_changed_catalog_rejected(cycle):
    x=cycle;run(x);x.task['problem']='different'
    with pytest.raises(ValueError,match='collision'):run(x)
    assert x.calls.count('execute')==1


def test_actual_disallows_injected_executor(cycle):
    with pytest.raises(ValueError):run(cycle,mode='ACTUAL')
    assert cycle.calls==[]


def test_simulation_requires_explicit_fake_executor(cycle):
    with pytest.raises(ValueError):run(cycle,execute=None)
    assert cycle.calls==[]


def test_no_control_and_billing_ledger_alias(cycle):
    x=cycle;x.c['ledger_path']=str(x.ledger.path)
    assert run(x).status=='blocked' and 'execute' not in x.calls


@pytest.mark.parametrize('field,value',[
    ('source_sha256','bad'),('files',['../escape']),('files',[]),('test_cases',[]),
    ('problem',''),('baseline',{'failures':0}),('task_id','../escape'),
])
def test_invalid_catalog_rejected_without_adapters(cycle,field,value):
    x=cycle;x.task[field]=value
    with pytest.raises(ValueError):run(x)
    assert x.calls==[]


def test_real_preflight_checks_existing_frozen_configuration(cycle,config_file,monkeypatch):
    from ops.pi.development_inputs import prepare
    x=cycle;path,c=config_file
    from ops.pi.development_inputs import read_json
    plan=read_json(c['plan_path']);x.task.update(source_sha256=c['source_sha256'],test_sha256=c['test_sha256'],test_cases=c['test_cases'],files=plan['files'])
    x.task['baseline'].update(tests=1,cases=c['test_cases'],failed_cases=c['test_cases'])
    x.current[0]=c['source_sha256'];x.proposal.update(source_sha256=c['source_sha256'])
    from ops.pi.development_inputs import file_hash
    import json
    baseline=read_json(c['baseline_path']);baseline['reproduction']=deepcopy(x.task['baseline'])
    Path(c['baseline_path']).write_text(json.dumps(baseline));c['baseline_sha256']=file_hash(c['baseline_path'])
    review=read_json(c['review_path']);review['authorization_sha256']=authorization_hash(c)
    Path(c['review_path']).write_text(json.dumps(review));c['review_sha256']=file_hash(c['review_path'])
    path.write_text(json.dumps(c))
    x.opts['billing_ledger_path']=c['ledger_path']
    def freeze(ctx):return x.receipt(ctx,config_path=str(path),config_sha256=handoff.file_hash(path))
    monkeypatch.setattr(handoff,'preflight',prepare)
    r=run(x,prepare_development=freeze,deadline=1200.0,execute=lambda *a,**k:dict(x.result,run_id=c['run_id'],authorization_sha256=authorization_hash(c)))
    assert r.status=='done'


def test_expected_authorization_checked_before_launcher_mutation(config_file):
    from ops.pi.development_launcher import execute
    path,c=config_file
    with pytest.raises(ValueError,match='authorization'):
        execute(path,expected_authorization_sha256='f'*64)
    from pathlib import Path
    assert not Path(c['root']).exists()
    assert not Path(c['ledger_path']).with_suffix('.tools.lock').exists()


def test_mismatched_reproduction_blocked_before_stage_done(cycle,monkeypatch):
    x=cycle;old=handoff.preflight
    def changed(path):
        values=list(old(path));values[3]['reproduction']['failures']=0;return tuple(values)
    monkeypatch.setattr(handoff,'preflight',changed)
    assert run(x).status=='blocked' and 'execute' not in x.calls
    with x.ledger.transaction() as db:
        stages=[dict(v) for v in db.execute("SELECT * FROM operations WHERE operation_id LIKE 'maintenance:cycle1:prepare:%'")]
    assert len(stages)==1 and stages[0]['status']=='blocked'


def test_bad_selection_not_persisted_as_analysis_done(cycle):
    x=cycle;x.proposal['task_id']='wrong';assert run(x).status=='blocked'
    with x.ledger.transaction() as db:
        rows=list(db.execute("SELECT status FROM operations WHERE operation_id LIKE 'maintenance:cycle1:analysis:%'"))
    assert len(rows)==1 and rows[0]['status']=='blocked'


def test_billing_alias_rejected_before_ledger_constructor(cycle,monkeypatch):
    x=cycle
    monkeypatch.setattr(handoff,'Ledger',lambda *a,**k:pytest.fail('must not construct aliased ledger'))
    with pytest.raises(ValueError,match='separate'):
        handoff.run_local_development(x.ledger.path,'alias',[x.task],**(x.opts|{'billing_ledger_path':str(x.ledger.path)}))
    assert x.calls==[]


def test_hardlink_billing_alias_rejected_before_claim(cycle,monkeypatch):
    import os
    x=cycle;alias=x.ledger.path.with_name('alias.sqlite');os.link(x.ledger.path,alias)
    monkeypatch.setattr(handoff,'Ledger',lambda *a,**k:pytest.fail('must not construct aliased ledger'))
    with pytest.raises(ValueError,match='separate'):run(x,billing_ledger_path=str(alias))
    assert x.calls==[]


def test_linked_billing_identity_rejected(cycle):
    x=cycle;alias=x.ledger.path.with_name('link.sqlite');alias.symlink_to(x.opts['billing_ledger_path'])
    with pytest.raises(ValueError,match='non-link'):run(x,billing_ledger_path=str(alias))
    assert x.calls==[]


def test_deadline_timer_signal_reaches_analyzer(cycle):
    import time
    x=cycle;seen=[]
    def analyze(ctx):
        seen.append(ctx['cancel'].wait(1))
        return x.receipt(ctx,proposal=deepcopy(x.proposal))
    r=run(x,analyze=analyze,clock=time.monotonic,deadline=time.monotonic()+.05)
    assert r.status=='blocked' and seen==[True] and 'execute' not in x.calls


def test_shared_cancel_and_expected_identity_reach_development(cycle):
    x=cycle;cancel=Event();old=x.opts['execute']
    def execute(*args,**kwargs):
        assert kwargs['cancel'] is cancel
        return old(*args,**kwargs)
    assert run(x,execute=execute,cancel=cancel).status=='done'


def test_cancelled_after_paid_return_not_success(cycle):
    x=cycle;cancel=Event();old=x.opts['execute']
    def execute(*args,**kwargs):
        result=old(*args,**kwargs);cancel.set();return result
    assert run(x,execute=execute,cancel=cancel).status=='blocked'
    assert x.calls.count('execute')==1


def test_completed_stage_then_parent_crash_is_not_replayed(cycle,monkeypatch):
    x=cycle;old=handoff._run_action
    def crash_after_stage(ledger,ctx,callback):
        result=old(ledger,ctx,callback)
        if ctx.get('stage')=='analysis':raise KeyboardInterrupt()
        return result
    monkeypatch.setattr(handoff,'_run_action',crash_after_stage)
    with pytest.raises(KeyboardInterrupt):run(x)
    monkeypatch.setattr(handoff,'_run_action',old)
    assert run(x).status=='uncertain' and x.calls==['analyze']


def test_mode_cannot_reuse_simulated_cycle(cycle):
    x=cycle;run(x)
    with pytest.raises(ValueError,match='collision'):run(x,mode='ACTUAL',execute=None)
    assert x.calls.count('execute')==1


def test_development_unknown_exception_is_not_retried(cycle):
    x=cycle
    def fail(*args,**kwargs):x.calls.append('execute');raise TimeoutError('unknown provider outcome')
    r=run(x,execute=fail);assert r.status=='uncertain'
    assert run(x)==r and x.calls.count('execute')==1


def test_reported_unknown_billing_preserves_uncertain_result(cycle):
    x=cycle;x.result.update(verified=False,new_unknown=1)
    r=run(x);assert r.status=='uncertain'
    with x.ledger.transaction() as db:
        rows=[x.ledger._record(v) for v in db.execute("SELECT * FROM operations WHERE operation_id LIKE 'maintenance:cycle1:develop:%'")]
    assert len(rows)==1 and rows[0]['status']=='uncertain'
    assert rows[0]['evidence']['result']['new_unknown']==1
    assert run(x)==r and x.calls.count('execute')==1


def test_slow_identity_check_cannot_start_analysis_after_deadline(cycle):
    x=cycle
    def identity():x.now[0]=201;return x.task['source_sha256']
    assert run(x,source_identity=identity).status=='blocked'
    assert x.calls==[]


@pytest.mark.parametrize('keep_zero',[False,True])
def test_audit_failure_is_uncertain_and_not_replayed(cycle,keep_zero):
    x=cycle;x.result.update(verified=False,audit_failure_class='OSError')
    if not keep_zero:x.result.pop('new_unknown')
    r=run(x);assert r.status=='uncertain' and r.evidence['next_action']=='reconcile'
    with x.ledger.transaction() as db:
        rows=[x.ledger._record(v) for v in db.execute("SELECT * FROM operations WHERE operation_id LIKE 'maintenance:cycle1:develop:%'")]
    assert len(rows)==1 and rows[0]['status']=='uncertain'
    assert rows[0]['evidence']['result']['audit_failure_class']=='OSError'
    assert run(x)==r and x.calls.count('execute')==1
