"""Publish a proposal-bound, freshly reviewed ACTUAL cycle to a private inbox."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import stat

from .development_inputs import digest,file_hash,path,read_json
from .development_launcher import atomic_write,require
from .local_cycle import _disjoint,_inspect as inspect_cycle
from .manager import _resources as cycle_resources
from .observations import _read,_name,_sha,_baseline
from .proposals import FIELDS,RULE,REQUIRES,load_observations,_trigger
from .task_package import _stable
from .tool_proof import strict_json

FIELDS_ADMISSION={'schema','proposal_path','proposal_sha256','proposal_id','cycle_path','cycle_sha256','task_id','inbox'}


def eligible(proposal_path,sha,proposal_id):
    """Recheck pinned host rules, original inputs and native failed reproduction."""
    report=strict_json(_read(proposal_path,sha).decode('utf-8'))
    require(report.get('schema')=='pi-proposal-report-v1' and report.get('inputs_current') is True
        and report.get('requires_reconciliation') is False and report.get('automatic_execution') is False,'current proposal evidence required')
    request=report['request_path'];_read(request,report['request_sha256']);c=read_json(request)
    require(set(c)==FIELDS and c['schema']=='pi-proposal-batch-v1'
        and path(proposal_path)==path(c['root'])/'proposals.json'
        and report['observation_path']==c['observation_path'] and report['observation_sha256']==c['observation_sha256'],
        'proposal request binding required')
    observed=load_observations(c['observation_path'],c['observation_sha256'])
    require(not observed['requires_reconciliation'],'reconciliation required')
    candidates=[x for x in report['proposals'] if x['proposal_id']==proposal_id]
    require(len(candidates)==1,'unique proposal required');p=candidates[0]
    require(p['state']=='eligible' and p['requires']==REQUIRES,'qualified proposal required')
    recipe=read_json(p['package_request_path']);_read(p['package_request_path'],p['package_request_sha256'])
    _stable(p['package_request_path'],p['package_request_sha256'],recipe)
    key=digest(dict(source=recipe['source_sha256'],test=recipe['test_sha256'],files=sorted(recipe['files'])))
    require(p['proposal_id']=='proposal-'+key[:24] and p['task_id']==recipe['task_id']
        and p['source_sha256']==recipe['source_sha256'] and p['test_sha256']==recipe['test_sha256']
        and p['files']==recipe['files'] and p['package_root']==recipe['root']
        and p['baseline_root']==str(Path(recipe['root']).with_name(Path(recipe['root']).name+'-baseline')),
        'proposal source binding drift')
    matching=[];contributing=[]
    for rule in c['rules']:
        require(isinstance(rule,dict) and set(rule)==RULE,'strict original host rule required')
        rp=path(rule['package_request_path'],private=True);_read(rp,rule['package_request_sha256']);rc=read_json(rp)
        _stable(rp,rule['package_request_sha256'],rc)
        rk=digest(dict(source=rc['source_sha256'],test=rc['test_sha256'],files=sorted(rc['files'])))
        if rk!=key:continue
        contributing.extend([rp,path(rc['source_path']),path(rc['test_path']),path(rc['root'])])
        rows=[o for o in observed['observations'] if o['source_id']==rule['source_id'] and o['observation_id']==rule['observation_id']]
        if len(rows)==1 and rows[0]['source_sha256']==p['source_sha256'] and _trigger(rule['trigger'],rows[0])[0]:matching.append(rule)
    require(matching and any(a.get('proposal_id')==proposal_id and a.get('decision')=='candidate'
        and a.get('rule_id') in {r['rule_id'] for r in matching} for a in report['assessments']), 'triggered host rule required')
    require(type(p['priority']) is int and 0<=p['priority']<=9
        and p['priority']==max(r['priority'] for r in matching),'host priority drift')
    baseline=path(p['baseline_request_path'],private=True);_read(baseline,p['baseline_request_sha256']);b=read_json(baseline)
    require(path(b['root'])==path(p['baseline_root'])
        and path(b['draft_path'])==path(p['package_root'])/'task-draft.json'
        and path(p['baseline_outcome_path'])==path(b['root'])/'outcome.json','baseline location drift')
    raw=_read(p['baseline_outcome_path'],p['baseline_outcome_sha256'])
    rows,protected=_baseline(dict(request_path=str(baseline),request_sha256=p['baseline_request_sha256'],
        path=p['baseline_outcome_path'],source_sha256=p['source_sha256']),raw)
    outcome=strict_json(raw.decode('utf-8'));draft=read_json(b['draft_path'])
    require(rows[0]['state']=='reproduced_failure' and p['catalog']==outcome['catalog']
        and draft['origin']['request_path']==p['package_request_path']
        and draft['origin']['request_sha256']==p['package_request_sha256']
        and p['staged_source_path']==draft['source_path'] and p['staged_test_path']==draft['test_path'],
        'native baseline provenance drift')
    inputs=[path(proposal_path),path(request),path(c['observation_path']),path(observed['request_path']),
        path(p['package_request_path']),path(recipe['source_path']),path(recipe['test_path']),path(c['root']),*protected,*contributing]
    inputs.extend(path(s['path']) for s in observed['sources'])
    return p,inputs


def _config(request_path):
    request=path(request_path,private=True);sha=file_hash(request);_read(request,sha);c=read_json(request)
    require(isinstance(c,dict) and set(c)==FIELDS_ADMISSION and c['schema']=='pi-proposal-admission-v1'
        and _name(c['task_id']) and _name(c['proposal_id']) and _sha(c['proposal_sha256']) and _sha(c['cycle_sha256']),
        'strict pinned proposal admission required')
    folder=path(c['inbox']);require(folder.is_dir() and stat.S_IMODE(folder.stat().st_mode)==0o700,'private inbox required')
    for p in (request,path(c['proposal_path']),path(c['cycle_path'])):_disjoint(folder,p)
    return request,sha,c,folder


def _prepare(request,sha,c,folder):
    p,inputs=eligible(c['proposal_path'],c['proposal_sha256'],c['proposal_id'])
    _read(c['cycle_path'],c['cycle_sha256']);native,selection,tasks,templates=inspect_cycle(c['cycle_path'])
    require(tasks==p['catalog'],'exact proposal catalog required')
    resources=cycle_resources(path(c['cycle_path']),native,selection,templates)
    for value in inputs+[request,*map(path,resources['inputs']+resources['outputs'])]:_disjoint(folder,value)
    require(file_hash(request)==sha and file_hash(c['proposal_path'])==c['proposal_sha256']
        and file_hash(c['cycle_path'])==c['cycle_sha256'],'admission input drift')
    manifest=dict(schema='pi-manager-admission-v1',task_id=c['task_id'],request_path=c['cycle_path'],
        request_sha256=c['cycle_sha256'],priority=p['priority'],mode='ACTUAL')
    return manifest


def check(request_path):
    request,sha,c,folder=_config(request_path);_prepare(request,sha,c,folder)
    require(not (folder/(c['task_id']+'.task.json')).exists(),'admission already published')
    return dict(ready=True,mode='read-only',proposal_id=c['proposal_id'],automatic_execution=False)


def publish(request_path):
    request,sha,c,folder=_config(request_path)
    lock=folder/'.proposal-publish.lock';target=folder/(c['task_id']+'.task.json');audit=folder/(c['task_id']+'.proposal.json')
    binding=dict(schema='pi-proposal-publication-binding-v1',request_path=str(request),request_sha256=sha,
        proposal_path=c['proposal_path'],proposal_sha256=c['proposal_sha256'],proposal_id=c['proposal_id'],
        cycle_path=c['cycle_path'],cycle_sha256=c['cycle_sha256'])
    if target.exists():
        require(audit.is_file(),'conflicting unbound admission publication')
        existing=read_json(target);_read(target,file_hash(target));_read(audit,file_hash(audit))
        saved=read_json(audit)
        require(saved['binding']==binding and existing==saved['manifest'],'conflicting admission publication')
        return dict(published=True,already_published=True,manifest_path=str(target),ready_rechecked=False)
    _prepare(request,sha,c,folder)
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        s=os.fstat(fd);require(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==0o600,'private single-link publisher lock required')
        fcntl.flock(fd,fcntl.LOCK_EX)
        require(os.stat(lock).st_ino==s.st_ino and os.stat(lock).st_nlink==1,'publisher lock replaced')
        if target.exists():
            require(audit.is_file(),'conflicting unbound admission publication')
            _read(target,file_hash(target));_read(audit,file_hash(audit));saved=read_json(audit)
            require(saved['binding']==binding and read_json(target)==saved['manifest'],'conflicting admission publication')
            return dict(published=True,already_published=True,manifest_path=str(target),ready_rechecked=False)
        manifest=_prepare(request,sha,c,folder)
        record=dict(binding=binding,manifest=manifest)
        if audit.exists():
            _read(audit,file_hash(audit));require(read_json(audit)==record,'conflicting prepared publication')
        else:atomic_write(audit,json.dumps(record,sort_keys=True,indent=2).encode()+b'\n')
        # Publish only complete single-link bytes. The consumer ignores *.proposal.json.
        require(not target.exists() and file_hash(request)==sha,'publication changed during preparation')
        atomic_write(target,json.dumps(manifest,sort_keys=True,indent=2).encode()+b'\n')
        return dict(published=True,already_published=False,manifest_path=str(target),ready_rechecked=True)
    finally:os.close(fd)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--publish',action='store_true');args=parser.parse_args()
    try:result=publish(args.request) if args.publish else check(args.request)
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(json.dumps(dict(ready=False,error_class=type(error).__name__)));return 1
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
