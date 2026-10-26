"""Trusted frozen-task adapters, using private synthetic config and fee ledgers."""
from copy import deepcopy
from pathlib import Path
from threading import Event
import json,time

import pytest

from ops.pi import maintenance_adapters as adapters
from ops.pi.development_inputs import authorization_hash,digest,file_hash,ledger_snapshot,read_json
from ops.pi.tests.test_development_inputs import config_file


@pytest.fixture
def pack(config_file,tmp_path,monkeypatch):
    template,c=config_file
    baseline=read_json(c['baseline_path']);cases=c['test_cases']
    reproduction=dict(tests=len(cases),cases=cases,failures=1,errors=0,skipped=0,failed_cases=cases,error_cases=[])
    baseline['reproduction']=reproduction;Path(c['baseline_path']).write_text(json.dumps(baseline));c['baseline_sha256']=file_hash(c['baseline_path'])
    template.write_text(json.dumps(c))
    task=dict(task_id='names',problem='registered name mistaken for negation',source_sha256=c['source_sha256'],
        evidence_sha256='b'*64,test_sha256=c['test_sha256'],test_cases=cases,files=['src/a.py'],baseline=reproduction)
    ctx=dict(operation_id='prepare:test',input_hash='c'*64,mode='SIMULATED',task=task,
        deadline=time.monotonic()+1800,cancel=Event())
    root=tmp_path/'prepared';root.mkdir(mode=0o700)
    monkeypatch.setattr(adapters,'verify_source',lambda *a: {})
    def review(path,context):
        value=read_json(path);plan=read_json(value['plan_path'])
        return dict(source='independent_review',verified=True,result='approved',reviewer='synthetic-review',
            authorization_sha256=authorization_hash(value),plan_hash=digest(plan),base=value['source_sha256'],
            candidate_id=value['run_id'],owner='local-development-controller',generation=1)
    adapter=adapters.FrozenDevelopmentAdapter({'names':dict(path=str(template),sha256=file_hash(template))},
        root,c['ledger_path'],review)
    return adapter,ctx,c,template,review


def test_refreshes_checkpoint_and_independent_review(pack):
    adapter,ctx,c,template,_=pack
    from ops.pi.ledger import Ledger
    Ledger(Path(c['ledger_path']),existing=True).intent('new-analysis','synthetic',{})
    result=adapter(ctx);assert result.status=='done'
    frozen=read_json(result.evidence['config_path'])
    assert frozen['ledger_sha256']==ledger_snapshot(c['ledger_path'])['sha256']!=c['ledger_sha256']
    changed={k for k in c if frozen[k]!=c[k]}
    assert changed<= {'ledger_sha256','deadline_seconds','review_path','review_sha256'}
    assert result.evidence['config_sha256']==file_hash(result.evidence['config_path'])
    assert read_json(frozen['review_path'])['authorization_sha256']==authorization_hash(frozen)


@pytest.mark.parametrize('field,value',[('source_sha256','e'*64),('test_sha256','e'*64),('files',['src/wrong.py'])])
def test_wrong_task_rejected_before_review(pack,field,value):
    adapter,ctx,*_=pack;ctx['task'][field]=value
    assert adapter(ctx).status=='blocked'


def test_billing_identity_cannot_change(pack):
    adapter,ctx,c,template,_=pack;value=read_json(template);value['ledger_path']=str(Path(c['ledger_path']).with_name('wrong.sqlite'))
    template.write_text(json.dumps(value));adapter.templates['names']['sha256']=file_hash(template)
    assert adapter(ctx).status=='blocked'


def test_independent_review_rejection_stops(pack):
    adapter,ctx,*_=pack;adapter.reviewer=lambda *a:dict(source='independent_review',result='rejected')
    assert adapter(ctx).status=='blocked'


def test_ledger_drift_during_review_stops(pack):
    adapter,ctx,c,_,review=pack
    def changing(path,context):
        result=review(path,context)
        from ops.pi.ledger import Ledger
        Ledger(Path(c['ledger_path']),existing=True).intent('concurrent','synthetic',{})
        return result
    adapter.reviewer=changing;assert adapter(ctx).status=='blocked'


def test_expired_budget_not_extended(pack):
    adapter,ctx,*_=pack;ctx['deadline']=time.monotonic()+20
    assert adapter(ctx).status=='blocked'


def test_actual_cannot_use_automatic_review_callback(pack):
    adapter,ctx,*_=pack;ctx['mode']='ACTUAL'
    assert adapter(ctx).status=='blocked'


def test_cancelled_file_review_does_not_approve(tmp_path):
    cancel=Event();cancel.set();review=adapters.FileReview()
    with pytest.raises(ValueError):review(tmp_path/'config.json',dict(cancel=cancel,deadline=time.monotonic()+10))


def test_selection_adapter_does_not_claim_execution_failures_as_bad_output(tmp_path,monkeypatch):
    path=tmp_path/'config';path.write_text(json.dumps(dict(root=str(tmp_path/'output'))));ctx=dict(operation_id='a',input_hash='a'*64,mode='SIMULATED')
    value=dict(verified=False,closed_verified=False,new_unknown=0,execution_verified=False,contract_valid=False)
    monkeypatch.setattr(adapters,'run_selection',lambda *a,**k:value)
    adapter=adapters.SelectionAdapter(path,file_hash(path),transport=lambda *a:None)
    assert adapter(ctx).status=='uncertain'
    value.update(closed_verified=True,execution_verified=True)
    assert adapter(ctx).status=='blocked'
    value.update(verified=True,contract_valid=True,proposal={'task_id':None})
    assert adapter(ctx).status=='done'
