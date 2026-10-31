"""Original immutable manager history must bind the finished candidate's proof."""
from pathlib import Path
import importlib
import pytest
from ops.pi import manager
from ops.pi.audit import digest
from ops.pi.contracts import Receipt
from ops.pi.development_inputs import file_hash,read_json,ledger_snapshot
from ops.pi.tests.test_development_evidence import stopped,completed,config_file,write


def api():return importlib.import_module('ops.pi.manager_completion')


@pytest.fixture
def finished(stopped):
    qp,q,c,r,frame=stopped;parent=qp.parent;output=parent/'cycle-output';output.mkdir(mode=0o700);prepared=output/'prepared';prepared.mkdir(mode=0o700);taskdir=prepared/'value-fix';taskdir.mkdir(mode=0o700)
    write(taskdir/'review.json',read_json(c['review_path']));c['review_path']=str(taskdir/'review.json');cp=taskdir/'config.json';write(cp,c)
    manifest=read_json(Path(c['root'])/'manifest-private.json');manifest['config']=dict(c);write(Path(c['root'])/'manifest-private.json',manifest);q.update(config_path=str(cp),config_sha256=file_hash(cp));write(qp,q)
    template=parent/'template.json';write(template,dict(c,review_path=str(parent/'pending-review.json'),review_sha256='0'*64));templates=parent/'templates.json';write(templates,{'value-fix':dict(path=str(template),sha256=file_hash(template))})
    cycle=dict(schema='pi-local-cycle-v1',cycle_id='auto-'+'a'*32,root=str(output),control_ledger_path=str(parent/'control.sqlite'),selection_config_path=str(parent/'selection.json'),selection_config_sha256='1'*64,templates_path=str(templates),templates_sha256=file_hash(templates),deadline_seconds=900,review_wait_seconds=60)
    cyclepath=parent/'cycle.json';write(cyclepath,cycle)
    result=dict(operation_id='maintenance:'+cycle['cycle_id'],schema_version=1,status='done',evidence=dict(verified=True,mode='SIMULATED',released=False,next_action='review_candidate',task_id='value-fix',result=r,stages=[]));write(output/'result.json',result)
    state=parent/'state/manager.sqlite';billing=Path(c['ledger_path']);manager.init(state,billing,mode='SIMULATED');ledger=manager.Ledger(state,existing=True);taskid='auto-'+'a'*32;op='manager:task:'+taskid
    payload=dict(task_id=taskid,request_path=str(cyclepath),request_sha256=file_hash(cyclepath),priority=1,cycle_id=cycle['cycle_id'],mode='SIMULATED',billing_path=str(billing),resources=dict(inputs=[str(cyclepath),str(templates),c['source_path']],outputs=[str(output),c['root']],identities=[cycle['cycle_id'],c['run_id']]))
    ledger.intent(op,'manager_task',payload);ledger.finish(Receipt(op,'done',dict(verified=True,binding=digest(payload))))
    task=dict(operation_id=op,payload=payload);ledger.intent(op+':dispatch','iteration_stage',manager._context(task));ledger.finish(Receipt(op+':dispatch','done',dict(verified=True,mode='SIMULATED',binding=digest(payload),released=False,cycle_result_sha256=digest(result),elapsed_ms=10,next_action='review_candidate')))
    return state,billing,taskid,qp,q,c,result


def test_completed_manager_and_sdk_proofs_are_both_readonly_and_candidate_bound(finished):
    state,billing,taskid,qp,q,c,result=finished;before={p:p.read_bytes() for p in qp.parent.rglob('*') if p.is_file()}
    proposal=api().request(state,billing,taskid,mode='SIMULATED');assert proposal['status']=='candidate_ready' and proposal['authority']=='request_only' and proposal['request']==q
    proof=api().inspect(state,billing,taskid,qp,file_hash(qp),mode='SIMULATED')
    assert proof['authority']=='completed_manager_development' and proof['development']['model_requests']==7 and proof['task_id']==taskid
    assert before=={p:p.read_bytes() for p in qp.parent.rglob('*') if p.is_file()}


@pytest.mark.parametrize('fault',['cycle','result','config','manifest','template','template_hash','prepared','review','result_candidate','manager_task','mode','request','check_copy'])
def test_other_or_changed_task_cannot_create_candidate_review_authority(finished,fault):
    state,billing,taskid,qp,q,c,result=finished;root=qp.parent
    if fault=='cycle':p=root/'cycle.json';v=read_json(p);v['cycle_id']='other';write(p,v)
    elif fault=='result':v=dict(result,status='blocked');write(root/'cycle-output/result.json',v)
    elif fault=='config':v=read_json(q['config_path']);v['root']=str(root/'other-output');write(Path(q['config_path']),v)
    elif fault=='manifest':p=Path(c['root'])/'manifest-private.json';v=read_json(p);v['config']['run_id']='foreign';write(p,v)
    elif fault=='template':p=root/'template.json';v=read_json(p);v['source_sha256']='f'*64;write(p,v)
    elif fault=='template_hash':v=read_json(root/'templates.json');v['value-fix']['sha256']='f'*64;write(root/'templates.json',v)
    elif fault=='prepared':Path(q['config_path']).rename(Path(q['config_path']).with_name('lost.json'))
    elif fault=='review':Path(c['review_path']).write_text('{}')
    elif fault=='result_candidate':p=Path(c['root'])/'result.json';v=read_json(p);v['candidate_sha256']='f'*64;write(p,v)
    elif fault=='manager_task':taskid='foreign'
    elif fault=='request':q['config_path']=str(root/'config.json');q['config_sha256']=file_hash(root/'config.json');write(qp,q)
    elif fault=='check_copy':(Path(c['root'])/'check-1/src/a.py').write_text('stale')
    with pytest.raises((ValueError,OSError)):api().inspect(state,billing,taskid,qp,file_hash(qp),mode='ACTUAL' if fault=='mode' else 'SIMULATED')


def test_unknown_task_and_pending_dispatch_do_not_generate_a_request(finished):
    state,billing,taskid,qp,q,c,result=finished;assert api().request(state,billing,'missing',mode='SIMULATED')['status']=='not_registered'
    # A separate genuine append-only manager has a registered task without dispatch.
    other=qp.parent/'state/pending-manager.sqlite';manager.init(other,billing,mode='SIMULATED');_,_,rows,*_=manager._snapshot(state,billing,'SIMULATED');old=rows['manager:task:'+taskid];ledger=manager.Ledger(other,existing=True);ledger.intent(old['operation_id'],old['kind'],old['payload']);ledger.finish(Receipt(old['operation_id'],'done',old['evidence']))
    before=ledger_snapshot(billing);value=api().request(other,billing,taskid,mode='SIMULATED');assert value['status']=='waiting_manager' and 'request' not in value and ledger_snapshot(billing)==before
