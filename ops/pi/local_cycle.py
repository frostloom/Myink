"""One finite ACTUAL maintenance cycle; check is read-only, never auto-adopts."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
from threading import Event
import time
import unicodedata
from urllib.parse import urlsplit

from .development_inputs import file_hash,ledger_snapshot,path,read_json,tree_hash
from .development_launcher import atomic_write,require
from .maintenance_adapters import (FileReview,FrozenDevelopmentAdapter,SelectionAdapter,
                                   preflight_templates)
from .ledger import Ledger
from .maintenance_handoff import _separate,run_local_development
from .selection_launcher import prepare as prepare_selection
from .task_package import _regular

FIELDS=set(('schema cycle_id root control_ledger_path selection_config_path '
    'selection_config_sha256 templates_path templates_sha256 deadline_seconds review_wait_seconds').split())


def _disjoint(a,b):
    # Conservative on case-sensitive volumes too: macOS aliases must never
    # turn a supposedly separate output into a write inside a frozen input.
    def normalized(p):
        try:p=Path(p).resolve()
        except (OSError,RuntimeError) as error:raise ValueError('unresolvable role path') from error
        return Path(unicodedata.normalize('NFC',str(p)).casefold())
    a,b=normalized(a),normalized(b)
    require(a!=b and a not in b.parents and b not in a.parents,'cycle input/output overlap')


def _ledger_roles(p):
    p=Path(p)
    return [p,*[p.with_name(p.name+suffix) for suffix in ('-wal','-shm','-journal')],
            p.with_suffix('.tools.lock')]


def _host_roles(c):
    endpoint=urlsplit(c['endpoint'])
    require(endpoint.scheme=='unix' and endpoint.path.startswith('/'),'local Unix socket required')
    return [path(c['docker']),Path(endpoint.path)]


def _inspect(request_path):
    request=path(request_path,private=True);_regular(request);request_sha=file_hash(request)
    c=read_json(request)
    require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-local-cycle-v1',
            'strict local cycle config required')
    require(isinstance(c['cycle_id'],str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',c['cycle_id']),
            'bounded cycle identity required')
    require(type(c['deadline_seconds']) is int and 0<c['deadline_seconds']<=3600
        and type(c['review_wait_seconds']) is int and 0<c['review_wait_seconds']<=600,
        'bounded cycle and review deadlines required')
    inputs=[request]
    for key in ('selection_config','templates'):
        p=path(c[key+'_path'],private=True);_regular(p)
        require(file_hash(p)==c[key+'_sha256'],key+' drift');inputs.append(p)
    selection,_,tasks,*_=prepare_selection(c['selection_config_path'])
    templates=read_json(c['templates_path'])
    require(isinstance(templates,dict) and set(templates)=={t['task_id'] for t in tasks},
            'exact catalog templates required')
    billing=path(selection['ledger_path'],private=True)
    control,_=_separate(c['control_ledger_path'],billing)
    require(control.parent.is_dir() and control.parent.stat().st_mode&0o777==0o700,
            'private control ledger parent required')
    if control.exists():
        _regular(path(control,private=True));ledger_snapshot(control)
    outputs=[path(c['root']),path(selection['root'])]
    for task in tasks:
        template=templates[task['task_id']]
        require(isinstance(template,dict) and set(template)=={'path','sha256'},'strict template pin required')
        target=path(template['path'],private=True);_regular(target);inputs.append(target)
        require(file_hash(target)==template['sha256'],'trusted template drift')
        tc=read_json(target)
        outputs.append(path(tc['root']))
        inputs.extend(path(tc[k]) for k in tc if k.endswith('_path') and k!='review_path')
        inputs.extend(_host_roles(tc))
    inputs.extend(path(selection[k]) for k in selection if k.endswith('_path'))
    inputs.extend(_ledger_roles(billing)+_host_roles(selection))
    control_roles=_ledger_roles(control)
    # Missing review paths are still reserved inputs, never output locations.
    inputs.extend(path(read_json(t['path'])['review_path']) for t in templates.values())
    for i,output in enumerate(outputs):
        require(not output.exists() and output.parent.is_dir()
            and output.parent.stat().st_mode&0o777==0o700,'fresh private phase root required')
        for other in outputs[:i]+inputs+control_roles:_disjoint(output,other)
    for role in control_roles:
        for value in inputs:_disjoint(role,value)
    context=dict(operation_id='check:'+c['cycle_id'],input_hash=request_sha,mode='ACTUAL',
        tasks=tasks,cancel=Event(),deadline=time.monotonic()+c['deadline_seconds'])
    proof=preflight_templates(templates,billing,FileReview(c['review_wait_seconds']),context)
    require(proof.status=='done' and proof.evidence.get('verified') is True,'task package preflight failed')
    require(file_hash(request)==request_sha and all(file_hash(c[k+'_path'])==c[k+'_sha256']
        for k in ('selection_config','templates')),'cycle input drift')
    return c,selection,tasks,templates


def check(request_path):
    c,_,tasks,_=_inspect(request_path)
    return dict(ready=True,mode='read-only',cycle_id=c['cycle_id'],tasks=len(tasks))


def execute(request_path,*,cancel=None):
    c,selection,tasks,templates=_inspect(request_path)
    root=Path(c['root']);root.mkdir(mode=0o700)
    prepared=root/'prepared';prepared.mkdir(mode=0o700)
    atomic_write(root/'invocation.json',json.dumps(c,ensure_ascii=True,indent=2).encode()+b'\n')
    control=Path(c['control_ledger_path'])
    if not control.exists():
        fd=os.open(control,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        Ledger(control)
    receipt=run_local_development(c['control_ledger_path'],c['cycle_id'],tasks,
        billing_ledger_path=selection['ledger_path'],
        source_identity=lambda:tree_hash(selection['source_path']),
        analyze=SelectionAdapter(c['selection_config_path'],c['selection_config_sha256']),
        prepare_development=FrozenDevelopmentAdapter(templates,prepared,selection['ledger_path'],
            FileReview(c['review_wait_seconds'])),mode='ACTUAL',
        deadline=time.monotonic()+c['deadline_seconds'],cancel=cancel)
    result=asdict(receipt)
    atomic_write(root/'result.json',json.dumps(result,ensure_ascii=True,indent=2,allow_nan=False).encode()+b'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True);parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    result=execute(args.request) if args.execute else check(args.request)
    print(json.dumps(result,ensure_ascii=True,sort_keys=True))
    return 0 if result.get('ready') is True or (result.get('status')=='done'
        and result.get('evidence',{}).get('verified') is True) else 1


if __name__=='__main__':raise SystemExit(main())
