"""Finite host-owned analysis-to-development handoff; never a model capability.

Adapters authenticate their own Engine/checker/review evidence. Model selection
cannot create tasks, test gold, budgets, approvals or execution paths. No source
adoption, Git, deployment or automatic retry is performed here.
"""
from copy import deepcopy
import math
import json
import os
import re
from threading import Event, Timer
import time

from .contracts import Receipt
from .development_inputs import (authorization_hash, digest, file_hash,
                                 path, prepare as preflight)
from .development_launcher import execute as execute_development
from .iteration import _run_action
from .ledger import Ledger
from .plans import _path


_TASK_FIELDS = {'task_id','problem','source_sha256','evidence_sha256','test_sha256',
                'test_cases','files','baseline'}
_BASE_FIELDS = {'tests','cases','failures','errors','skipped','failed_cases','error_cases'}


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _sha(value):
    return isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value) is not None


def _text(value, limit):
    return isinstance(value,str) and bool(value.strip()) and len(value)<=limit


def _catalog(tasks):
    _require(isinstance(tasks,list) and 0<len(tasks)<=20,'bounded host task catalog required')
    tasks=deepcopy(tasks)
    _require(len(json.dumps(tasks,ensure_ascii=True,allow_nan=False).encode())<=60000,
             'task catalog too large')
    names=[];sources=set()
    for task in tasks:
        _require(isinstance(task,dict) and set(task)==_TASK_FIELDS,'strict host task required')
        name=task['task_id'];names.append(name)
        _require(isinstance(name,str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',name)
                 and _text(task['problem'],2000),'bounded task identity and problem required')
        _require(all(_sha(task[k]) for k in ('source_sha256','evidence_sha256','test_sha256')),
                 'frozen source/evidence/test identity required')
        sources.add(task['source_sha256'])
        files=task['files'];cases=task['test_cases']
        _require(isinstance(files,list) and 0<len(files)<=8 and all(_path(f) for f in files)
                 and len(files)==len(set(files)),'declared task files required')
        _require(isinstance(cases,list) and 0<len(cases)<=1000 and all(
            isinstance(c,str) and re.fullmatch(r'fixed_development_tests\.[A-Za-z0-9_.]{1,240}',c)
            for c in cases) and len(cases)==len(set(cases)),'fixed task inventory required')
        b=task['baseline']
        _require(isinstance(b,dict) and set(b)==_BASE_FIELDS,'reproduced baseline required')
        _require(all(type(b[k]) is int for k in ('tests','failures','errors','skipped'))
                 and b['tests']==len(cases) and b['cases']==cases and b['errors']==b['skipped']==0
                 and 0<b['failures']<=len(cases) and b['error_cases']==[],'actual failed inventory required')
        failed=b['failed_cases']
        _require(isinstance(failed,list) and all(isinstance(c,str) for c in failed)
                 and len(failed)==len(set(failed))==b['failures'] and set(failed)<=set(cases),
                 'exact failed cases required')
    _require(len(names)==len(set(names)) and len(sources)==1,'unique tasks and common source required')
    return tasks


def _selection(proposal,tasks):
    _require(isinstance(proposal,dict) and set(proposal)=={
        'task_id','source_sha256','evidence_sha256','reason'} and _text(proposal['reason'],4096),
        'strict bounded selection required')
    if proposal['task_id'] is None:
        _require(proposal['source_sha256'] is None and proposal['evidence_sha256'] is None,
                 'no-work identity must be empty')
        return None
    task=next((t for t in tasks if t['task_id']==proposal['task_id']),None)
    _require(task is not None and all(proposal[k]==task[k] for k in
             ('source_sha256','evidence_sha256')),'selection outside frozen evidence')
    return task


def _separate(control,billing):
    control,billing=path(control),path(billing)
    _require(control!=billing and (not control.exists() or not billing.exists()
             or not os.path.samefile(control,billing)),'control and billing ledgers must be separate')
    return control,billing


def run_local_development(control_path,cycle_id,tasks,*,billing_ledger_path,
        source_identity,analyze,prepare_development,mode,deadline,cancel=None,
        clock=time.monotonic,execute=None):
    """One durable cycle, with trusted no-tool analysis and freeze/review adapters.

    Deadline is absolute on ``clock`` (monotonic by default). Adapters must honor
    context deadline/cancel cooperatively; Python callbacks cannot be force-killed.
    ACTUAL uses the existing launcher. Only SIMULATED accepts an injected runner.
    ``baseline.reproduction`` must retain the host catalog's exact failed check.
    """
    tasks=_catalog(tasks)
    _require(isinstance(cycle_id,str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',cycle_id),
             'bounded cycle identity required')
    _require(mode in ('ACTUAL','SIMULATED') and all(callable(f) for f in
             (source_identity,analyze,prepare_development,clock)),'explicit mode and trusted adapters required')
    _require((mode=='ACTUAL' and execute is None) or (mode=='SIMULATED' and callable(execute)),
             'simulation runner cannot authorize actual execution')
    _require(type(deadline) in (int,float) and math.isfinite(deadline)
             and deadline-clock()<=3600,'bounded monotonic deadline required')
    control,billing=_separate(control_path,billing_ledger_path)
    ledger=Ledger(control,existing=control.exists())
    source=tasks[0]['source_sha256'];catalog_hash=digest(tasks)
    cancel=cancel if cancel is not None else Event()
    context=dict(operation_id='maintenance:'+cycle_id,cycle_id=cycle_id,mode=mode,
        source_sha256=source,catalog_sha256=catalog_hash,deadline=deadline,
        billing_ledger_path=str(billing))
    context['input_hash']=digest(context)
    runner=execute_development if mode=='ACTUAL' else execute

    def guard():
        _require(not cancel.is_set(),'cancelled')
        _require(clock()<deadline,'deadline expired')
        identity=source_identity()
        _require(not cancel.is_set(),'cancelled')
        _require(clock()<deadline,'deadline expired')
        _require(identity==source,'source identity changed')

    def blocked(ctx,reason):
        return Receipt(ctx['operation_id'],'blocked',dict(reason=reason,mode=mode,released=False))

    def cycle(ctx):
        previous=[]
        def invoke(stage,callback,validate,extra=None):
            data=dict(cycle_id=cycle_id,mode=mode,source_sha256=source,catalog_sha256=catalog_hash,
                      deadline=deadline,previous=deepcopy(previous),**(extra or {}))
            binding=digest(data)
            stage_ctx=dict(data,stage=stage,input_hash=binding,
                           operation_id=ctx['operation_id']+':'+stage+':'+binding)
            def action(value):
                try:guard()
                except ValueError as error:return blocked(value,str(error))
                # Adapter exceptions may have sent a request: _run_action records UNCERTAIN.
                receipt=callback(dict(deepcopy(value),cancel=cancel))
                if (not isinstance(receipt,Receipt) or receipt.status!='done'
                        or not isinstance(receipt.evidence,dict)
                        or receipt.evidence.get('verified') is not True
                        or receipt.evidence.get('binding')!=binding or receipt.evidence.get('mode')!=mode):
                    return receipt
                try:
                    guard();validate(receipt.evidence);guard()
                except (ValueError,KeyError,TypeError,OSError) as error:
                    return blocked(value,'handoff validation failed:'+type(error).__name__)
                return receipt
            result=_run_action(ledger,stage_ctx,action)
            previous.append(dict(operation_id=result.operation_id,status=result.status,
                                 evidence_sha256=digest(result.evidence)))
            return result

        def stop(result):
            return Receipt(ctx['operation_id'],result.status,dict(mode=mode,released=False,
                next_action='reconcile' if result.status=='uncertain' else 'stop',
                reason='stage_not_complete',stages=deepcopy(previous)))

        def analyze_checked(value):
            check=getattr(prepare_development,'preflight',None)
            if not callable(check):
                if mode=='ACTUAL':return blocked(value,'task package preflight required')
                return analyze(value)
            checked=check(dict(value,tasks=deepcopy(value['tasks']),previous=deepcopy(value['previous'])))
            if (not isinstance(checked,Receipt) or checked.operation_id!=value['operation_id']
                    or checked.status!='done' or not isinstance(checked.evidence,dict)
                    or checked.evidence.get('verified') is not True
                    or checked.evidence.get('binding')!=value['input_hash']
                    or checked.evidence.get('mode')!=mode
                    or checked.evidence.get('catalog_sha256')!=catalog_hash):
                return blocked(value,'task package preflight failed')
            try:guard()
            except ValueError as error:return blocked(value,str(error))
            receipt=analyze(value)
            if isinstance(receipt,Receipt) and isinstance(receipt.evidence,dict):
                receipt=Receipt(receipt.operation_id,receipt.status,
                    dict(receipt.evidence,package_preflight=deepcopy(checked.evidence)))
            return receipt

        analysis=invoke('analysis',analyze_checked,lambda e:_selection(e['proposal'],tasks),dict(tasks=tasks))
        if analysis.status!='done':return stop(analysis)
        proposal=analysis.evidence['proposal'];task=_selection(proposal,tasks)
        if task is None:
            return Receipt(ctx['operation_id'],'done',dict(verified=True,mode=mode,binding=ctx['input_hash'],
                released=False,next_action='observe',stages=previous))
        prepared={}
        def validate_config(e):
            config_path=path(e['config_path'],private=True)
            _require(_sha(e['config_sha256']) and file_hash(config_path)==e['config_sha256'],
                     'frozen config drift')
            c,_,plan,baseline,*_=preflight(config_path)
            _require(c['source_sha256']==task['source_sha256'] and c['test_sha256']==task['test_sha256']
                     and c['test_cases']==task['test_cases'] and tuple(plan.files)==tuple(task['files']),
                     'prepared task identity changed')
            _require(isinstance(baseline,dict) and digest(baseline.get('reproduction'))==digest(task['baseline']),
                     'reproduced baseline changed')
            _require(path(c['ledger_path'])==billing,'billing ledger identity changed')
            _separate(control,c['ledger_path'])
            _require(type(c['deadline_seconds']) is int and 0<c['deadline_seconds']<=deadline-clock(),
                     'development exceeds remaining deadline')
            _require(file_hash(config_path)==e['config_sha256'],'config changed during preflight')
            prepared.update(config=c,path=str(config_path),file_hash=e['config_sha256'],
                            authorization=authorization_hash(c))
        freeze=invoke('prepare',prepare_development,validate_config,dict(task=task,proposal=proposal))
        if freeze.status!='done':return stop(freeze)

        def develop(value):
            try:
                guard()
                _require(file_hash(prepared['path'])==prepared['file_hash'],'config drift before execution')
            except (ValueError,OSError) as error:return blocked(value,'execution binding changed')
            result=runner(prepared['path'],cancel=cancel,
                          expected_authorization_sha256=prepared['authorization'])
            if (not isinstance(result,dict) or 'audit_failure_class' in result
                    or type(result.get('new_unknown')) is not int or result['new_unknown']!=0):
                return Receipt(value['operation_id'],'uncertain',dict(mode=mode,
                    reason='billing_outcome_not_proven',result=result))
            return Receipt(value['operation_id'],'done',dict(verified=True,mode=mode,
                binding=value['input_hash'],result=result))
        def validate_result(e):
            r=e['result'];c=prepared['config']
            _require(isinstance(r,dict) and r.get('verified') is True
                and r.get('run_id')==c['run_id'] and r.get('authorization_sha256')==prepared['authorization']
                and type(r.get('new_unknown')) is int and r['new_unknown']==0
                and r.get('policy_restored') is True and r.get('original_history_unchanged') is True,
                'development outcome incomplete')
            clean=r.get('cleanup')
            _require(isinstance(clean,list) and clean and all(isinstance(v,dict) and v.get('removed') is True
                     for v in clean),'owned cleanup incomplete')
            _require(_sha(r.get('candidate_sha256')) and r['candidate_sha256']!=source
                     and _text(r.get('candidate_path'),4096),'nonempty candidate required')
        developed=invoke('develop',develop,validate_result,dict(task_id=task['task_id'],
            config_sha256=prepared['file_hash'],authorization_sha256=prepared['authorization']))
        if developed.status!='done':return stop(developed)
        return Receipt(ctx['operation_id'],'done',dict(verified=True,mode=mode,binding=ctx['input_hash'],
            released=False,next_action='review_candidate',task_id=task['task_id'],
            result=developed.evidence['result'],stages=previous))

    timer=Timer(max(0,deadline-clock()),cancel.set);timer.daemon=True;timer.start()
    try:return _run_action(ledger,context,cycle)
    finally:timer.cancel()
