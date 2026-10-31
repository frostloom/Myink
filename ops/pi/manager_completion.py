"""Readonly original-manager completion binding; never candidate/product permission.

Only after this binding and stopped SDK/tool/fee reconciliation may the root
source coordinator issue a separate finite recommendation-only review permit.
"""
from pathlib import Path
import re
from .audit import _path,digest,require
from .development_inputs import file_hash,FIELDS as DEVELOPMENT_FIELDS
from .review_lease import _read
from .review_dossier import semantic_hash
from .local_cycle import FIELDS as CYCLE_FIELDS
from .manager_handoff import BASE
from . import manager,development_evidence



def request(state,billing,task_id,*,mode='ACTUAL'):
    require(mode in ('ACTUAL','SIMULATED') and isinstance(task_id,str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',task_id),'fixed manager completion identity required')
    state,billing=map(_path,(state,billing))
    actual_state=BASE/'state/actual-manager.sqlite';actual_fee=BASE/'state/ledger.sqlite'
    if mode=='ACTUAL':require(state==actual_state and billing==actual_fee,'original ACTUAL manager/fee state required')
    else:require(state!=actual_state and billing!=actual_fee,'SIMULATED completion requires isolated state')
    _,_,rows,tasks,_=manager._snapshot(state,billing,mode);task=next((t for t in tasks if t['payload']['task_id']==task_id),None)
    def status(value):return dict(authority='request_only',status=value,task_id=task_id,model_requests=0)
    if task is None:return status('not_registered')
    op=task['operation_id'];dispatch=rows.get(op+':dispatch')
    if op+':cancel' in rows:return status('cancelled')
    if task['status']!='done' or dispatch is None:return status('waiting_manager')
    if dispatch['status'] in ('pending','uncertain'):return status('uncertain')
    if dispatch['status']!='done':return status('execution_stopped')
    payload=task['payload'];pins={}
    def read(path,pin=None):
        value,actual=_read(path);require(pin is None or actual==pin,'original manager completion artifact drift');pins[str(_path(path))]=actual;return value
    cp=_path(payload['request_path']);cycle=read(cp,payload['request_sha256'])
    require(isinstance(cycle,dict) and set(cycle)==CYCLE_FIELDS and cycle['schema']=='pi-local-cycle-v1' and cycle['cycle_id']==payload['cycle_id'],'original sealed cycle required')
    output=_path(cycle['root']);resources=payload['resources'];require(isinstance(resources,dict) and set(resources)=={'inputs','outputs','identities'} and str(output) in resources['outputs'],'cycle output outside registered resources')
    result=read(output/'result.json');e=dispatch['evidence']
    require(isinstance(result,dict) and set(result)=={'operation_id','status','evidence','schema_version'} and type(result['schema_version']) is int and result['schema_version']==1
        and result['operation_id']=='maintenance:'+cycle['cycle_id'] and result['status']=='done' and digest(result)==e['cycle_result_sha256'],'completed registered dispatch/cycle mismatch')
    ce=result['evidence'];require(isinstance(ce,dict) and ce.get('verified') is True and ce.get('mode')==mode and ce.get('released') is False,'actual nonrelease cycle required')
    if ce.get('next_action')=='observe':return status('no_action')
    require(ce.get('next_action')=='review_candidate' and e.get('next_action')=='review_candidate','completed candidate-review action required')
    selected=ce.get('task_id');require(isinstance(selected,str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',selected),'fixed selected development task required')
    prepared=output/'prepared'/selected/'config.json';dc=read(prepared)
    require(isinstance(dc,dict) and set(dc)==DEVELOPMENT_FIELDS and dc['schema']=='pi-development-v1' and _path(dc['ledger_path'])==billing
        and _path(dc['review_path'])==prepared.parent/'review.json' and str(_path(dc['root'])) in resources['outputs'] and str(_path(dc['source_path'])) in resources['inputs'],'prepared development outside original manager resources')
    templates=read(cycle['templates_path'],cycle['templates_sha256']);require(isinstance(templates,dict) and selected in templates,'selected original template required')
    template=templates[selected];require(isinstance(template,dict) and set(template)=={'path','sha256'},'pinned original template required');tc=read(template['path'],template['sha256'])
    require(semantic_hash(dc,deadline_ceiling=tc['deadline_seconds'])==semantic_hash(tc),'completed prepared scope differs from original frozen template')
    development=read(_path(dc['root'])/'result.json');require(isinstance(ce.get('result'),dict) and digest(ce['result'])==digest(development),'development differs from completed manager result')
    checks=list(_path(dc['root']).glob('check-*-receipt.json'));require(0<len(checks)<=dc['max_tools'] and all(re.fullmatch(r'check-[1-9][0-9]{0,2}-receipt\.json',p.name) for p in checks),'bounded complete checker receipts required')
    final=max(checks,key=lambda p:int(p.name.split('-')[1]));phase=read(_path(dc['root'])/'phase-verification.json');check=read(final)
    q=dict(schema='pi-candidate-review-request-v1',mode=mode,config_path=str(prepared),config_sha256=pins[str(prepared)],result_sha256=pins[str(_path(dc['root'])/'result.json')],phase_sha256=pins[str(_path(dc['root'])/'phase-verification.json')],check_id=final.name.removesuffix('-receipt.json'),check_sha256=pins[str(final)])
    _,_,current,*_=manager._snapshot(state,billing,mode)
    require(current.get(op)==task and current.get(op+':dispatch')==dispatch and all(file_hash(p)==pin for p,pin in pins.items()),'manager completion changed while reading')
    return dict(status('candidate_ready'),request=q,config=dc,cycle_result=result,artifact_pins=pins,manager_binding=dict(task_id=task_id,task_sha256=digest(task),dispatch_sha256=digest(dispatch),cycle_sha256=payload['request_sha256'],cycle_result_sha256=digest(result)))


def inspect(state,billing,task_id,request_path,request_sha256,*,mode='ACTUAL'):
    finished=request(state,billing,task_id,mode=mode);require(finished['status']=='candidate_ready','manager has no completed candidate')
    q,pin=_read(request_path);require(pin==request_sha256 and digest(q)==digest(finished['request']),'candidate review request differs from original manager')
    proof=development_evidence.inspect(request_path,request_sha256)
    require(proof['mode']==mode and digest(proof['config'])==digest(finished['config']),'completed manager/development identity drift')
    again=request(state,billing,task_id,mode=mode)
    require(again['status']=='candidate_ready' and again['manager_binding']==finished['manager_binding'] and again['request']==q,'manager result changed during SDK reconciliation')
    return dict(authority='completed_manager_development',executable_approval=False,task_id=task_id,manager_binding=finished['manager_binding'],artifact_pins=finished['artifact_pins'],development=proof)
