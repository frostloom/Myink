"""Bounded host-pinned observations. No source execution, models or permissions."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import stat
import xml.etree.ElementTree as ET

from .development_inputs import digest,file_hash,path,read_json,tree_hash
from .development_launcher import atomic_write,require
from .local_cycle import _disjoint
from .package_baseline import _draft,BASE_FIELDS
from .maintenance_handoff import _catalog
from .tool_proof import strict_json
from .unit_feedback import REPORT_FIELDS,validate_report

MAX_BYTES=8*1024**2
FIELDS={'schema','batch_id','sources','root'}
SOURCE_FIELDS={'source_id','kind','path','sha256','source_sha256'}


def _name(value):return isinstance(value,str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',value)
def _sha(value):return isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value)


def _read(p,expected):
    p=path(p,private=True);s=p.stat()
    require(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=MAX_BYTES,'bounded private single-link artifact required')
    with p.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    require(len(raw)<=MAX_BYTES and _sha(expected) and sha256(raw).hexdigest()==expected,'observation artifact drift')
    return raw


def _junit(raw):
    text=raw.decode('utf-8')
    require('\0' not in text and '<!DOCTYPE' not in text.upper() and '<!ENTITY' not in text.upper(),'XML declarations/entities forbidden')
    try:root=ET.fromstring(text)
    except ET.ParseError as error:raise ValueError('parseable JUnit required') from error
    require(root.tag in ('testsuites','testsuite'),'JUnit root required')
    stack=[(root,0)]
    while stack:
        node,depth=stack.pop();require(depth<=64,'XML nesting bound');stack.extend((c,depth+1) for c in node)
    result=[];seen=Counter();testcases=list(root.iter('testcase'));require(len(testcases)<=10000,'bounded JUnit inventory required')
    for node in testcases:
        name=node.get('name');cls=node.get('classname','')
        require(isinstance(name,str) and 0<len(name)<=512 and len(cls)<=512,'bounded JUnit identity required')
        identity=cls+'::'+name;seen[identity]+=1
        marks=[child for child in node if child.tag in ('failure','error','skipped')]
        require(len(marks)<=1,'ambiguous JUnit outcome')
        state={'failure':'failed','error':'error','skipped':'skipped'}.get(marks[0].tag,'passed') if marks else 'passed'
        diagnostic=ET.tostring(marks[0],encoding='utf-8') if marks else b''
        result.append(dict(observation_id=identity,occurrence=seen[identity],state=state,
            diagnostic_sha256=sha256(diagnostic).hexdigest() if diagnostic else None))
    for suite in root.iter('testsuite'):
        for mark in suite:
            if mark.tag in ('failure','error'):
                result.append(dict(observation_id='collection-error:'+str(len(result)),occurrence=1,
                    state='collection_error',diagnostic_sha256=sha256(ET.tostring(mark,encoding='utf-8')).hexdigest()))
    return result or [dict(observation_id='empty',occurrence=1,state='empty',diagnostic_sha256=None)]


def _cycle(raw):
    c=strict_json(raw.decode('utf-8'))
    require(isinstance(c,dict) and set(c)=={'operation_id','status','schema_version','evidence'}
        and type(c['schema_version']) is int and c['schema_version']==1 and isinstance(c['operation_id'],str)
        and c['status'] in ('done','failed','blocked','uncertain') and isinstance(c['evidence'],dict),'native cycle receipt required')
    e=c['evidence'];unknown=c['status']=='uncertain' or (c['status']=='done' and e.get('verified') is not True)
    nested=e.get('result')
    if isinstance(nested,dict) and ('new_unknown' not in nested or type(nested['new_unknown']) is not int or nested['new_unknown']!=0):unknown=True
    state='execution_unknown' if unknown else 'candidate_ready' if c['status']=='done' and e.get('next_action')=='review_candidate' else 'observed_no_work' if c['status']=='done' else 'execution_stopped'
    return [dict(observation_id='cycle',occurrence=1,state=state,diagnostic_sha256=digest(c),
        declared_mode=e.get('mode') if e.get('mode') in ('ACTUAL','SIMULATED') else 'unknown')]


def _metrics(raw):
    m=strict_json(raw.decode('utf-8'))
    require(isinstance(m,dict) and isinstance(m.get('measurements'),dict) and 0<len(m['measurements'])<=64
        and m.get('availability') in ('measured','unknown') and isinstance(m.get('confounders'),list)
        and all(isinstance(x,str) and len(x)<=128 for x in m['confounders']),'bounded metric snapshot required')
    result=[]
    for name,value in sorted(m['measurements'].items()):
        require(isinstance(name,str) and re.fullmatch('[A-Za-z0-9_.-]{1,80}',name) and isinstance(value,dict),'metric shape required')
        v=value.get('value');samples=value.get('samples')
        require((v is None or type(v) in (int,float) and math.isfinite(v) and v>=0)
            and type(samples) is int and samples>=0 and value.get('availability') in ('measured','unknown')
            and value.get('direction') in ('lower','higher'),'known metric types required')
        state='confounded' if m['confounders'] else 'measured' if m['availability']==value['availability']=='measured' and v is not None and samples>0 else 'unknown'
        result.append(dict(observation_id='metric:'+name,occurrence=1,state=state,value=v,samples=samples,
            direction=value['direction'],evidence_domain=m.get('evidence_domain','unknown'),diagnostic_sha256=None))
    return result


def _baseline(item,raw):
    request=path(item['request_path'],private=True);_read(request,item['request_sha256']);c=read_json(request)
    require(isinstance(c,dict) and c.get('schema')=='pi-package-baseline-request-v1'
        and path(item['path'])==path(c['root'])/'outcome.json','baseline output identity required')
    o=strict_json(raw.decode('utf-8'))
    require(isinstance(o,dict) and o.get('schema')=='pi-package-baseline-outcome-v1'
        and o.get('request_sha256')==item['request_sha256'] and o.get('draft_sha256')==c['draft_sha256'],
        'baseline request binding required')
    d=_draft(c['draft_path'],c['draft_sha256'])
    require(tree_hash(d['source_path'])==d['source_sha256']==item['source_sha256']==o['source_sha256']
        and file_hash(d['test_path'])==d['test_sha256']==o['test_sha256'],'baseline source or test drift')
    report=o.get('checker_report');qualified=False
    if report is not None:
        validate_report({k:report[k] for k in REPORT_FIELDS},report['attach_returncode'],d['test_case_hints'])
        require(tree_hash(Path(c['root'])/'check/src')==tree_hash(Path(d['source_path'])/'src')
            and file_hash(Path(c['root'])/'check/test.py')==d['test_sha256'],'baseline checker input copy drift')
        if o.get('verified') is True and o.get('eligible_for_selection') is True:
            tasks=_catalog(o['catalog']);require(len(tasks)==1,'single baseline task required');t=tasks[0]
            require(t['source_sha256']==d['source_sha256'] and t['test_sha256']==d['test_sha256']
                and t['files']==d['files'] and t['test_cases']==d['test_case_hints']
                and t['baseline']=={k:report[k] for k in BASE_FIELDS},'baseline catalog drift')
            clean=o.get('cleanup');qualified=bool(clean and all(x.get('removed') is True
                and x.get('exit_code')==report['attach_returncode'] for x in clean)
                and any(x.get('container_id')==report.get('container_id') for x in clean)
                and not o.get('failure_class') and not o.get('cleanup_failure_class'))
    state='reproduced_failure' if qualified else 'baseline_unqualified'
    return [dict(observation_id='baseline',occurrence=1,state=state,diagnostic_sha256=digest(o))], [request,Path(c['draft_path']),Path(d['source_path']),Path(d['test_path']),Path(c['root'])]


def collect(request_path,*,existing=False):
    request=path(request_path,private=True);sha=file_hash(request);_read(request,sha);c=read_json(request)
    require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-observation-intake-v1'
        and _name(c['batch_id']) and isinstance(c['sources'],list) and 0<len(c['sources'])<=20,'strict observation intake required')
    root=path(c['root']);require(root.parent.is_dir() and stat.S_IMODE(root.parent.stat().st_mode)==0o700
        and ((root.is_dir() and stat.S_IMODE(root.stat().st_mode)==0o700) if existing else not root.exists()),'new private observation root required')
    names=set();records=[];pins=[];protected=[request]
    for item in c['sources']:
        require(isinstance(item,dict) and item.get('kind') in ('junit','cycle','metrics','baseline'),'supported observation source required')
        fields=SOURCE_FIELDS|({'request_path','request_sha256'} if item['kind']=='baseline' else set())
        require(set(item)==fields and _name(item['source_id']) and item['source_id'] not in names
            and _sha(item['source_sha256']),'unique bounded observation source required')
        names.add(item['source_id']);raw=_read(item['path'],item['sha256']);protected.append(Path(item['path']))
        if item['kind']=='junit':rows=_junit(raw)
        elif item['kind']=='cycle':rows=_cycle(raw)
        elif item['kind']=='metrics':rows=_metrics(raw)
        else:
            rows,extra=_baseline(item,raw);protected.extend(extra)
        records.extend(dict(row,source_id=item['source_id'],source_kind=item['kind'],source_sha256=item['source_sha256'],artifact_sha256=item['sha256']) for row in rows)
        pins.append(dict(item))
    for value in protected:_disjoint(root,value)
    require(file_hash(request)==sha and all(sha256(_read(p['path'],p['sha256'])).hexdigest()==p['sha256'] for p in pins),'observation inputs changed')
    result=dict(schema='pi-observation-report-v1',batch_id=c['batch_id'],request_path=str(request),request_sha256=sha,sources=pins,
        observations=records,counts=dict(sorted(Counter(x['state'] for x in records).items())),
        requires_reconciliation=any(x['state']=='execution_unknown' for x in records),automatic_execution=False)
    require(len(json.dumps(result,ensure_ascii=True).encode())<=MAX_BYTES,'normalized observation bound')
    return c,result


def check(request_path):
    _,r=collect(request_path)
    return dict(ready=True,mode='read-only',counts=r['counts'],requires_reconciliation=r['requires_reconciliation'])


def freeze(request_path):
    c,r=collect(request_path);root=Path(c['root']);root.mkdir(mode=0o700)
    target=root/'observations.json';atomic_write(target,json.dumps(r,ensure_ascii=True,indent=2).encode()+b'\n')
    return dict(report_path=str(target),report_sha256=file_hash(target),counts=r['counts'],automatic_execution=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True);p.add_argument('--freeze',action='store_true');a=p.parse_args()
    try:r=freeze(a.request) if a.freeze else check(a.request)
    except (ValueError,OSError,KeyError,TypeError) as e:
        print(json.dumps(dict(ready=False,error_class=type(e).__name__)));return 1
    print(json.dumps(r,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
