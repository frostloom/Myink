"""Build mechanical cycle configs from host-frozen evidence; never approve them."""
import argparse
import json
from pathlib import Path
import re
from threading import Event
import time

from .development_inputs import (authorization_hash,digest,file_hash,path,prepare_template,read_json)
from .development_launcher import atomic_write,require
from .local_cycle import _disjoint,_host_roles,_ledger_roles,check as check_cycle
from .maintenance_adapters import FileReview,preflight_templates
from .maintenance_handoff import _catalog
from .selection_launcher import FIELDS as SELECTION_FIELDS,prepare as prepare_selection
from .task_package import _publish_new,_regular

FIELDS=set(('schema root cycle_id selection_run_id template_path template_sha256 '
    'outcome_path outcome_sha256 deadline_seconds review_wait_seconds').split())


def _write(p,value):
    atomic_write(p,json.dumps(value,ensure_ascii=True,indent=2,allow_nan=False).encode()+b'\n')


def _inspect(request_path,*,existing=False):
    request=path(request_path,private=True);_regular(request);sha=file_hash(request);c=read_json(request)
    require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-cycle-bundle-v1','strict bundle request required')
    require(isinstance(c['cycle_id'],str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',c['cycle_id'])
        and isinstance(c['selection_run_id'],str) and re.fullmatch('[a-z0-9-]{1,80}',c['selection_run_id']),
        'fresh bounded cycle and selection identities required')
    require(type(c['deadline_seconds']) is int and 0<c['deadline_seconds']<=3600
        and type(c['review_wait_seconds']) is int and 0<c['review_wait_seconds']<=600,'bounded bundle deadlines required')
    root=path(c['root']);require(root.parent.is_dir() and root.parent.stat().st_mode&0o777==0o700,
        'private bundle parent required')
    require((root.is_dir() and root.stat().st_mode&0o777==0o700) if existing else not root.exists(),
        'fresh private bundle root required')
    for key in ('template','outcome'):
        target=path(c[key+'_path'],private=True);_regular(target)
        require(file_hash(target)==c[key+'_sha256'],key+' drift')
    tc,_,plan,baseline,*_=prepare_template(c['template_path'])
    outcome=read_json(c['outcome_path'])
    require(isinstance(outcome,dict) and outcome.get('schema')=='pi-package-baseline-outcome-v1'
        and outcome.get('verified') is True and outcome.get('eligible_for_selection') is True,
        'eligible isolated baseline required')
    tasks=_catalog(outcome['catalog']);require(len(tasks)==1,'one frozen task per bundle required')
    task=tasks[0]
    require(task['source_sha256']==tc['source_sha256']==outcome['source_sha256']
        and task['test_sha256']==tc['test_sha256']==outcome['test_sha256']
        and task['test_cases']==tc['test_cases'] and task['files']==list(plan.files)
        and digest(task['baseline'])==digest(baseline.get('reproduction')),'baseline template identity drift')
    for value in [request,path(c['template_path']),path(c['outcome_path']),path(tc['root'])]+[
            path(tc[k]) for k in tc if k.endswith('_path')]+_host_roles(tc)+_ledger_roles(tc['ledger_path']):_disjoint(root,value)
    templates={task['task_id']:dict(path=c['template_path'],sha256=c['template_sha256'])}
    proof=preflight_templates(templates,path(tc['ledger_path']),FileReview(c['review_wait_seconds']),
        dict(operation_id='bundle:'+c['cycle_id'],input_hash=sha,mode='ACTUAL',tasks=tasks,
            deadline=time.monotonic()+c['deadline_seconds'],cancel=Event()))
    require(proof.status=='done','bundle task package rejected')
    require(file_hash(request)==sha and all(file_hash(c[k+'_path'])==c[k+'_sha256'] for k in ('template','outcome')),
        'bundle input drift')
    return c,tc,tasks,templates,sha


def check(request_path):
    c,*_=_inspect(request_path)
    return dict(ready=True,mode='read-only',cycle_id=c['cycle_id'])


def freeze(request_path):
    c,tc,tasks,templates,request_sha=_inspect(request_path)
    root=Path(c['root']);root.mkdir(mode=0o700)
    _write(root/'catalog.json',tasks);_write(root/'templates.json',templates)
    selection={k:tc[k] for k in SELECTION_FIELDS if k in tc}
    selection.update(schema='pi-maintenance-selection-v1',run_id=c['selection_run_id'],root=str(root/'selection-output'),
        catalog_path=str(root/'catalog.json'),catalog_sha256=file_hash(root/'catalog.json'),deadline_seconds=120,
        review_path=str(root/'selection-review.json'),review_sha256='0'*64)
    _write(root/'selection-config.json',selection)
    _write(root/'selection-review-request.json',dict(authorization_sha256=authorization_hash(selection),
        plan_hash=digest(tasks),base=selection['source_sha256'],candidate_id=selection['run_id'],
        config_path=str(root/'selection-config.json')))
    meta=dict(schema='pi-cycle-bundle-frozen-v1',request_path=str(request_path),request_sha256=request_sha,
        selection_sha256=file_hash(root/'selection-config.json'),templates_sha256=file_hash(root/'templates.json'))
    retained=_publish_new(root/'bundle.json',json.dumps(meta,indent=2).encode()+b'\n')
    return dict(bundle_path=str(root/'bundle.json'),staging_retained=retained,
        requires=['independent_selection_review','independent_development_review'])


def seal(bundle_path):
    marker=path(bundle_path,private=True);_regular(marker);meta=read_json(marker)
    require(isinstance(meta,dict) and set(meta)=={'schema','request_path','request_sha256','selection_sha256','templates_sha256'}
        and meta['schema']=='pi-cycle-bundle-frozen-v1','frozen bundle marker required')
    require(file_hash(path(meta['request_path'],private=True))==meta['request_sha256'],'bundle request drift')
    c,_,_,_,_=_inspect(meta['request_path'],existing=True);root=Path(c['root'])
    require(marker==root/'bundle.json' and not (root/'cycle.json').exists(),'new cycle seal required')
    require(file_hash(root/'selection-config.json')==meta['selection_sha256']
        and file_hash(root/'templates.json')==meta['templates_sha256'],'frozen bundle drift')
    selection=read_json(root/'selection-config.json')
    selection['review_sha256']=file_hash(path(selection['review_path'],private=True))
    # Keep the original zero-review draft immutable; only the reviewed copy is executable.
    reviewed=root/'selection-reviewed.json';_write(reviewed,selection);prepare_selection(reviewed)
    entry=dict(schema='pi-local-cycle-v1',cycle_id=c['cycle_id'],root=str(root/'cycle-output'),
        control_ledger_path=str(root/'control.sqlite'),selection_config_path=str(reviewed),
        selection_config_sha256=file_hash(reviewed),templates_path=str(root/'templates.json'),
        templates_sha256=meta['templates_sha256'],deadline_seconds=c['deadline_seconds'],
        review_wait_seconds=c['review_wait_seconds'])
    pending=root/'cycle-request.pending.json';_write(pending,entry);check_cycle(pending)
    retained=_publish_new(root/'cycle.json',pending.read_bytes())
    try:check_cycle(root/'cycle.json');ready=True
    except (ValueError,OSError,KeyError,TypeError):ready=False
    return dict(ready=ready,published=True,cycle_path=str(root/'cycle.json'),staging_retained=retained,
        next_action='execute_explicitly' if ready else 'reconcile_publication')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    group=parser.add_mutually_exclusive_group();group.add_argument('--freeze',action='store_true');group.add_argument('--seal',action='store_true')
    args=parser.parse_args()
    try:result=seal(args.request) if args.seal else freeze(args.request) if args.freeze else check(args.request)
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(json.dumps(dict(ready=False,error_class=type(error).__name__)));return 1
    print(json.dumps(result));return 0 if result.get('ready',True) is True else 1


if __name__=='__main__':raise SystemExit(main())
