"""Host-only abandonment of a stopped selection; never replay or accept its output."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

from .container_probe import ProbeHost
from .contracts import Receipt
from .development_inputs import authorization_hash,digest,file_hash,ledger_snapshot,path,read_json,tree_hash,validate_review
from .development_launcher import atomic_write,require
from .local_cycle import _disjoint,_ledger_roles,FIELDS as CYCLE_FIELDS
from .maintenance_handoff import _catalog
from .observations import _read,_name
from .selection_launcher import FIELDS as SELECTION_FIELDS,SYSTEM,request_matches,selection_prompt,text
from .tool_proof import strict_json

FIELDS={'schema','state_path','billing_path','task_id','root'}
OUTCOME='abandoned'


def _config(request_path):
    request=path(request_path,private=True);_artifact(request);c=read_json(request)
    require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-selection-abandonment-v1'
        and _name(c['task_id']),'strict host abandonment request required')
    root=path(c['root']);require(root.parent.is_dir() and stat.S_IMODE(root.parent.stat().st_mode)==0o700,
        'private audit parent required')
    from . import manager
    state,billing=manager._paths(c['state_path'],c['billing_path'])
    for p in [request,*manager._roles(state),*_ledger_roles(billing)]:_disjoint(root,p)
    return request,c,state,billing,root


def _snapshot_document(value):
    require(isinstance(value,dict) and set(value)=={'operations','events','limits','sha256'}
        and value['sha256']==digest({k:v for k,v in value.items() if k!='sha256'}),'saved billing snapshot drift')
    return value


def facts(request_path):
    from . import manager
    request,c,state,billing,root=_config(request_path)
    _,_,rows,tasks,_=manager._snapshot(state,billing,'ACTUAL')
    task=rows.get('manager:task:'+c['task_id']);require(task and task['status']=='done','registered task required')
    dispatch=rows.get(manager._dispatch_id(task));require(dispatch and dispatch['status']=='uncertain'
        and dispatch['payload']==manager._context(task),'stopped uncertain dispatch required')
    p=task['payload'];require(dispatch['evidence'].get('binding')==digest(p)
        and dispatch['evidence'].get('mode')=='ACTUAL' and dispatch['evidence'].get('released') is False,'dispatch binding drift')
    pins={}
    def pin(target,expected=None):
        target=path(target,private=True);raw=_artifact(target,expected);pins[str(target)]=sha256(raw).hexdigest();return raw
    def read(target,expected=None):return strict_json(pin(target,expected).decode('utf-8'))
    cycle=read(p['request_path'],p['request_sha256']);require(set(cycle)==CYCLE_FIELDS
        and cycle['schema']=='pi-local-cycle-v1' and cycle['cycle_id']==p['cycle_id'],'original cycle drift')
    native=path(cycle['root']);require(read(native/'invocation.json')==cycle,'native invocation drift')
    outcome=read(native/'result.json');require(outcome==dict(operation_id='maintenance:'+cycle['cycle_id'],
        schema_version=1,status='uncertain',evidence=outcome['evidence'])
        and digest(outcome)==dispatch['evidence'].get('cycle_result_sha256'),'native stopped result drift')
    require(outcome['evidence'].get('mode')=='ACTUAL' and outcome['evidence'].get('released') is False
        and outcome['evidence'].get('next_action')=='reconcile','stopped cycle required')
    selection=read(cycle['selection_config_path'],cycle['selection_config_sha256'])
    require(set(selection)==SELECTION_FIELDS and selection['schema']=='pi-maintenance-selection-v1'
        and path(selection['ledger_path'])==billing,'original selection identity drift')
    templates=read(cycle['templates_path'],cycle['templates_sha256'])
    catalog=_catalog(read(selection['catalog_path'],selection['catalog_sha256']))
    require(set(templates)=={t['task_id'] for t in catalog},'exact original templates required')
    validate_review(read(selection['review_path'],selection['review_sha256']),selection,digest(catalog),selection['source_sha256'])
    sources={};development=[]
    for t in catalog:
        require(t['source_sha256']==selection['source_sha256'],'catalog source drift')
        tc=read(templates[t['task_id']]['path'],templates[t['task_id']]['sha256'])
        require(tc['source_sha256']==t['source_sha256'] and tc['test_sha256']==t['test_sha256']
            and tc['test_cases']==t['test_cases'] and path(tc['ledger_path'])==billing,'original development template drift')
        for key in ('plan','baseline','policy','credential','test'):pin(tc[key+'_path'],tc[key+'_sha256'])
        sources[tc['source_path']]=tc['source_sha256'];development.append(path(tc['root']))
    sources[selection['source_path']]=selection['source_sha256']
    require(all(tree_hash(p)==s for p,s in sources.items()),'original source drift')
    require(all(not p.exists() for p in development) and (native/'prepared').is_dir()
        and not any((native/'prepared').iterdir()),'development may have started')
    resources=manager._resources(path(p['request_path']),cycle,selection,templates)
    require(resources==p['resources'],'registered resource drift')
    for value in resources['inputs']+resources['outputs']+list(sources):_disjoint(root,Path(value))
    control=path(cycle['control_ledger_path'],private=True)
    for role in _ledger_roles(control):
        path(role)
        if role.exists():manager._plain(path(role,private=True))
    snap=ledger_snapshot(control);control_rows={r['operation_id']:manager.Ledger._record(r) for r in snap['operations']}
    main=control_rows.get(outcome['operation_id']);require(main and main['status']=='uncertain'
        and main['kind']=='iteration_stage' and main['evidence']==outcome['evidence'],'original control cycle drift')
    m=main['payload'];require(m.get('mode')=='ACTUAL' and m.get('billing_ledger_path')==str(billing)
        and m.get('catalog_sha256')==digest(catalog) and m.get('source_sha256')==selection['source_sha256']
        and m['input_hash']==digest({k:v for k,v in m.items() if k!='input_hash'}),'control identity drift')
    stages=outcome['evidence'].get('stages');require(isinstance(stages,list) and len(stages)==1,'only stopped analysis allowed')
    stage=control_rows.get(stages[0]['operation_id']);require(stage and stage['kind']=='iteration_stage'
        and stage['status']=='uncertain' and len(control_rows)==2,'additional or unresolved control execution')
    s=stage['payload'];e=stage['evidence'];data={k:v for k,v in s.items() if k not in ('stage','input_hash','operation_id')}
    require(s.get('stage')=='analysis' and s.get('mode')=='ACTUAL' and s.get('cycle_id')==cycle['cycle_id']
        and s.get('previous')==[] and s.get('tasks')==catalog and s['input_hash']==digest(data)
        and stage['operation_id']==main['operation_id']+':analysis:'+s['input_hash']
        and stages[0]==dict(operation_id=stage['operation_id'],status='uncertain',evidence_sha256=digest(e))
        and e.get('binding')==s['input_hash'] and e.get('mode')=='ACTUAL' and e.get('verified') is False,
        'analysis control binding drift')
    output=path(selection['root']);r=read(output/'result.json')
    require(path(e['result_path'])==output/'result.json' and e['result']==r
        and r.get('run_id')==selection['run_id'] and r.get('authorization_sha256')==authorization_hash(selection)
        and r.get('verified') is False and r.get('execution_verified') is False and r.get('closed_verified') is False
        and isinstance(r.get('failure_class'),str),'only unverified stopped selection can be abandoned')
    require(all(r.get(k) is True for k in ('policy_restored','credential_unchanged','original_history_unchanged'))
        and not r.get('cleanup_failure_class') and not r.get('audit_failure_class'),'selection audit incomplete')
    manifest=read(output/'manifest-private.json');require(manifest['config']==selection
        and manifest['context_hash']==s['input_hash'],'selection execution manifest drift')
    policy=read(selection['policy_path'],selection['policy_sha256']);pin(selection['credential_path'],selection['credential_sha256'])
    require(policy.get('live_enabled') is False and policy.get('server_daily_enabled') is False,'original policy must be closed')
    before=_snapshot_document(read(output/'ledger-before-private.json'));after=_snapshot_document(read(output/'ledger-after-private.json'))
    require(before['sha256']==selection['ledger_sha256'] and ledger_snapshot(billing)==after,'current original billing checkpoint drift')
    old={x['operation_id']:x for x in before['operations']};current={x['operation_id']:x for x in after['operations']}
    require(all(current.get(k)==v for k,v in old.items()) and after['events'][:len(before['events'])]==before['events'],
        'original billing history changed')
    new=[v for k,v in current.items() if k not in old]
    require(len(new)==1 and new[0]['kind']=='model-attempt' and new[0]['status']=='done','one settled selection attempt required')
    charge=manager.Ledger._decode(new[0]['evidence']);attempt=manager.Ledger._decode(new[0]['payload'])
    require(charge.get('usage_known') is True and type(charge.get('charged_microyuan')) is int and charge['charged_microyuan']>=0
        and attempt.get('scope_id')=='local-trial-1' and r.get('new_unknown')==0 and type(r['new_unknown']) is int
        and r.get('new_attempts')==1 and type(r['new_attempts']) is int and r.get('known_cost_microyuan')==charge['charged_microyuan']
        and r.get('model_posts')==[dict(status=200,attempt_id=new[0]['operation_id'])],'selection fee identity mismatch')
    frame=read(output/'worker-frame-private.json');wr=frame['receipt'];we=wr['evidence']
    require(frame.get('type')=='result' and frame.get('network_denied') is True and wr.get('status') in ('pending','uncertain','failed')
        and we.get('protocol_failed') is True and we.get('engine')=='pi' and we.get('plan_id')==s['input_hash']
        and we.get('config_hash')==digest(dict(authorization=authorization_hash(selection),context=s['input_hash']))
        and we.get('verified_tool_calls')==we.get('pending_tool_calls')==[] and we.get('unexpected_tool') is False
        and we.get('length_continuations')==0 and all(we.get(k) is True for k in ('process_exited','clear_abort_acknowledged'))
        and type(we.get('returncode')) is int and we['returncode']==0,'owned stopped no-tool selection required')
    request_matches(read(output/'request-private.json'),dict(system=SYSTEM,prompt=selection_prompt(selection,catalog,s['input_hash'])))
    verify_stopped_artifacts(frame,selection,s['input_hash'])
    cleanup=r.get('cleanup');require(isinstance(cleanup,list) and len(cleanup)==1 and cleanup[0].get('removed') is True
        and type(cleanup[0].get('exit_code')) is int and cleanup[0]['exit_code']==0
        and re.fullmatch('[a-f0-9]{64}',cleanup[0].get('container_id','')),'exact closed selection container required')
    require({x.name for x in output.glob('owned-host-*.json')}=={'owned-host-0.json'},'extra owned hosts require reconciliation')
    owner=read(output/'owned-host-0.json');require(set(owner)=={'operation_id'}
        and str(uuid.UUID(owner['operation_id']))==owner['operation_id'],'fixed owned operation required')
    host={k:selection[k] for k in ('docker','endpoint','daemon_id','image_id')};host.update(container_id=cleanup[0]['container_id'],operation_id=owner['operation_id'],docker_sha256=file_hash(path(selection['docker'])))
    ProbeHost(docker=path(host['docker']),endpoint=host['endpoint'],daemon_id=host['daemon_id'],image_id=host['image_id'],operation_id=host['operation_id'])
    for target in pins:_disjoint(root,path(target))
    require(all(file_hash(k)==v for k,v in pins.items()) and ledger_snapshot(control)==snap and ledger_snapshot(billing)==after,
        'abandonment inputs changed during inspection')
    return dict(mode='ACTUAL',state_path=str(state),billing_path=str(billing),task_id=c['task_id'],task_binding=digest(p),
        dispatch_sha256=digest(dispatch),control_sha256=snap['sha256'],billing_sha256=after['sha256'],new_attempts=1,
        known_cost_microyuan=charge['charged_microyuan'],new_unknown=0,outcome=OUTCOME,accepted_output=False,
        request_path=str(request),request_sha256=file_hash(request),artifact_pins=pins,source_pins=sources,
        development_roots=list(map(str,development)),host=host)


def _no_tool_nodes(value):
    stack=[(value,0)]
    while stack:
        node,depth=stack.pop();require(depth<=64,'stopped artifact nesting bound')
        if isinstance(node,dict):
            require(not any(isinstance(node.get(k),str) and node[k].casefold().startswith('tool') for k in ('type','role')),
                'raw artifact contains tool evidence')
            stack.extend((v,depth+1) for v in node.values())
        elif isinstance(node,list):stack.extend((v,depth+1) for v in node)


def verify_stopped_artifacts(frame,selection,context_hash):
    """Reject any extra execution evidence without upgrading the old receipt."""
    e=frame['receipt']['evidence'];raw=frame['session'];rpc=frame['transcript']
    require(isinstance(raw,str) and raw.endswith('\n') and 0<len(raw.encode())<=262144
        and sha256(raw.encode()).hexdigest()==e.get('session_sha256')
        and isinstance(rpc,str) and rpc.endswith('\n') and 0<len(rpc.encode())<=1048576,'bounded stopped artifact hashes required')
    rows=[strict_json(line) for line in raw.split('\n')[:-1]]
    require(rows and all(isinstance(r,dict) for r in rows) and rows[0].get('type')=='session'
        and isinstance(rows[0].get('id'),str) and rows[0]['id'] and rows[0].get('cwd')=='/work/candidate'
        and sum(r.get('type')=='session' for r in rows)==1,'owned selection session required')
    _no_tool_nodes(rows)
    messages=[r.get('message') for r in rows if r.get('type')=='message']
    prompt=selection_prompt(selection,_catalog(read_json(selection['catalog_path'])),context_hash)
    require(len(messages)==3 and all(isinstance(m,dict) for m in messages)
        and set(messages[0])=={'role','content','sections','timestamp'} and messages[0]['role']=='system'
        and messages[0]['content']=='' and type(messages[0]['timestamp']) is int
        and messages[0]['sections']==dict(preamble=SYSTEM,cwd='<cwd>\n/work/candidate\n</cwd>')
        and messages[1].get('role')=='user' and text(messages[1].get('content'))==prompt
        and messages[2].get('role')=='assistant' and messages[2].get('stopReason')=='stop'
        and not messages[2].get('errorMessage') and text(messages[2].get('content'))==e.get('text'),
        'exact no-tool selection messages required')
    commands={};responses={};ends=[];settled=[]
    for n,line in enumerate(rpc.split('\n')[:-1]):
        item=strict_json(line);_no_tool_nodes(item)
        require(isinstance(item,dict) and set(item)=={'direction','record'} and item['direction'] in ('in','out')
            and isinstance(item['record'],dict),'strict stopped RPC required')
        record=item['record'];kind=record.get('type');require(isinstance(kind,str) and not kind.startswith('tool_'),'tool execution cannot be abandoned')
        if item['direction']=='in':
            require(kind in ('prompt','clear_queue','abort') and kind not in commands and isinstance(record.get('id'),str),'unexpected selection command')
            commands[kind]=(n,record)
        elif kind=='response':
            name=record.get('command');require(name in ('prompt','clear_queue','abort') and name not in responses,'duplicate or unknown response')
            responses[name]=(n,record)
        elif kind=='message_end':ends.append((n,record.get('message')))
        elif kind=='agent_settled':
            require(record.get('aborted') is False,'aborted selection cannot be abandoned');settled.append(n)
    require(set(commands)==set(responses)=={'prompt','clear_queue','abort'}
        and len({v[1]['id'] for v in commands.values()})==3,'complete selection acknowledgements required')
    for name in commands:
        a,command=commands[name];b,response=responses[name]
        require(a<b and response.get('id')==command['id'] and response.get('success') is True,'selection acknowledgement mismatch')
    require(commands['prompt'][1].get('message')==prompt and responses['prompt'][1].get('data',{}).get('disposition')=='started'
        and responses['clear_queue'][1].get('data')==dict(steering=[],followUp=[])
        and len(ends)==3 and len(settled)==1 and [m for _,m in ends]==messages
        and responses['prompt'][0]<ends[0][0]<ends[1][0]<ends[2][0]<settled[0]<commands['clear_queue'][0]
        and responses['clear_queue'][0]<commands['abort'][0],'stopped session/RPC execution mismatch')


def verify_absence(value):
    c=value['host'];require(file_hash(path(c['docker']))==c['docker_sha256'],'Docker executable changed');host=ProbeHost(docker=path(c['docker']),endpoint=c['endpoint'],daemon_id=c['daemon_id'],image_id=c['image_id'],operation_id=c['operation_id'])
    host._daemon();r=host._call('inspect',c['container_id'],check=False)
    require(r.returncode!=0 and ('no such object' in r.stderr.lower() or 'no such container' in r.stderr.lower()),
        'owned selection container still exists or inspect failed')
    require(not host._call('ps','-aq','--filter','label=myink.pi.operation='+c['operation_id']).stdout.strip(),
        'owned selection operation still exists')


def check(request_path):
    value=facts(request_path)
    return dict(ready_for_audit=True,mode='read-only',outcome=OUTCOME,new_attempts=value['new_attempts'],known_cost_microyuan=value['known_cost_microyuan'])


def audit(request_path):
    request,c,_,_,root=_config(request_path);require(not root.exists(),'new audit root required')
    value=facts(request);verify_absence(value);require(facts(request)==value,'audit inputs drift')
    created=time.time();report=dict(schema='pi-selection-abandonment-audit-v1',created_at=created,expires_at=created+600,facts=value,resources_closed=True)
    root.mkdir(mode=0o700);target=root/'audit.json';atomic_write(target,json.dumps(report,sort_keys=True,indent=2).encode()+b'\n')
    review_request=dict(schema='pi-selection-abandonment-review-request-v1',audit_path=str(target),audit_sha256=file_hash(target),task_binding=value['task_binding'],dispatch_sha256=value['dispatch_sha256'],billing_sha256=value['billing_sha256'],outcome=OUTCOME)
    atomic_write(root/'review-request.json',json.dumps(review_request,sort_keys=True,indent=2).encode()+b'\n')
    return dict(audit_path=str(target),audit_sha256=file_hash(target),requires='independent_abandonment_review',outcome=OUTCOME)


REVIEW_FIELDS={'schema','source','verified','result','reviewer','audit_sha256','task_binding','dispatch_sha256','billing_sha256','outcome'}
PAYLOAD_FIELDS={'schema','mode','task_binding','dispatch_sha256','audit_path','audit_sha256','review_path','review_sha256','outcome'}


def _artifact(target,expected=None):
    target=path(target,private=True);s=target.stat()
    require(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=8*1024**2,'bounded single-link evidence required')
    return _read(target,expected or file_hash(target))


def _load_report(target,expected=None):
    r=strict_json(_artifact(target,expected).decode('utf-8'))
    require(isinstance(r,dict) and set(r)=={'schema','created_at','expires_at','facts','resources_closed'}
        and r['schema']=='pi-selection-abandonment-audit-v1' and r['resources_closed'] is True
        and type(r['created_at']) in (float,int) and type(r['expires_at']) in (float,int)
        and r['expires_at']-r['created_at']==600,'bounded original audit required')
    f=r['facts'];require(f.get('mode')=='ACTUAL' and f.get('outcome')==OUTCOME and f.get('accepted_output') is False
        and type(f.get('new_unknown')) is int and f['new_unknown']==0
        and type(f.get('new_attempts')) is int and f['new_attempts']==1,'selection abandonment facts required')
    return r


def _review(target,sha,report,audit_sha):
    r=strict_json(_artifact(target,sha).decode('utf-8'));f=report['facts']
    expected=dict(schema='pi-selection-abandonment-review-v1',source='independent_review',verified=True,result='approved',
        audit_sha256=audit_sha,task_binding=f['task_binding'],dispatch_sha256=f['dispatch_sha256'],billing_sha256=f['billing_sha256'],outcome=OUTCOME)
    require(isinstance(r,dict) and set(r)==REVIEW_FIELDS and all(type(r.get(k)) is type(v) and r[k]==v for k,v in expected.items())
        and isinstance(r['reviewer'],str) and 0<len(r['reviewer'].strip())<=200
        and r['reviewer'] not in ('model','local-development-controller'),'independent abandonment review required')
    return r


def validate_resolution(task,dispatch,row,state,billing):
    """Immutable admission evidence stays required on every manager recovery."""
    p=row['payload'];require(row['kind']=='manager_reconciliation' and row['operation_id']==task['operation_id']+':reconciliation'
        and row['status'] in ('pending','done') and set(p)==PAYLOAD_FIELDS and p['schema']=='pi-selection-abandonment-record-v1'
        and p['mode']==task['payload']['mode']=='ACTUAL' and p['outcome']==OUTCOME
        and dispatch['status']=='uncertain' and p['task_binding']==digest(task['payload'])
        and p['dispatch_sha256']==digest(dispatch),'reconciliation record binding drift')
    report=_load_report(p['audit_path'],p['audit_sha256']);f=report['facts']
    require(f['state_path']==str(state) and f['billing_path']==str(billing)
        and f['task_id']==task['payload']['task_id'] and f['task_binding']==p['task_binding']
        and f['dispatch_sha256']==p['dispatch_sha256'],'reconciliation audit identity drift')
    _review(p['review_path'],p['review_sha256'],report,p['audit_sha256'])
    if row['status']=='done':require(row['evidence']==dict(verified=True,binding=digest(p),outcome=OUTCOME,mode='ACTUAL'),
        'reconciliation receipt drift')
    return report


def apply(request_path,review_path):
    import fcntl
    from . import manager
    request,c,state,billing,root=_config(request_path)
    target=root/'audit.json';report=_load_report(target);audit_sha=file_hash(target)
    rp=path(review_path,private=True);_artifact(rp);review_sha=file_hash(rp);_review(rp,review_sha,report,audit_sha)
    _,_,rows,_,_=manager._snapshot(state,billing,'ACTUAL');op='manager:task:'+c['task_id']+':reconciliation'
    payload=dict(schema='pi-selection-abandonment-record-v1',mode='ACTUAL',task_binding=report['facts']['task_binding'],
        dispatch_sha256=report['facts']['dispatch_sha256'],audit_path=str(target),audit_sha256=audit_sha,
        review_path=str(rp),review_sha256=review_sha,outcome=OUTCOME)
    require(report['facts']['request_path']==str(request) and report['facts']['request_sha256']==file_hash(request),
        'abandonment request drift')
    old=rows.get(op)
    if old:
        require(old['payload']==payload,'reconciliation identity conflict')
        if old['status']=='done':return dict(abandoned=True,replayed=True,task_id=c['task_id'],original_status='uncertain')
    require(old is not None or report['created_at']<=time.time()<report['expires_at'],'abandonment audit expired or future')
    # All file/role checks precede creation of the shared manager lock.
    require(facts(request)==report['facts'],'abandonment audit stale')
    lock_path=state.with_suffix('.manager.lock');path(lock_path)
    fd=os.open(lock_path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        manager._plain(path(lock_path,private=True))
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:raise ValueError('manager busy') from error
        require(os.fstat(fd).st_ino==lock_path.stat().st_ino,'manager lock replaced')
        _,_,rows,_,_=manager._snapshot(state,billing,'ACTUAL');old=rows.get(op)
        if old:
            require(old['payload']==payload,'reconciliation identity conflict')
            if old['status']=='done':return dict(abandoned=True,replayed=True,task_id=c['task_id'],original_status='uncertain')
        current=facts(request);require(current==report['facts'],'abandonment inputs changed')
        verify_absence(current)
        require(facts(request)==current and (old is not None or report['created_at']<=time.time()<report['expires_at'])
            and file_hash(target)==audit_sha and file_hash(rp)==review_sha,'review or checkpoint changed during closure audit')
        ledger=manager.Ledger(state,existing=True);ledger.intent(op,'manager_reconciliation',payload)
        ledger.finish(Receipt(op,'done',dict(verified=True,binding=digest(payload),outcome=OUTCOME,mode='ACTUAL')))
        return dict(abandoned=True,replayed=False,task_id=c['task_id'],original_status='uncertain')
    finally:os.close(fd)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True);g=p.add_mutually_exclusive_group();g.add_argument('--audit',action='store_true');g.add_argument('--apply',action='store_true');p.add_argument('--review');a=p.parse_args()
    try:
        require(not a.apply or a.review,'independent review path required')
        r=apply(a.request,a.review) if a.apply else audit(a.request) if a.audit else check(a.request)
    except (ValueError,OSError,KeyError,TypeError,RuntimeError) as error:
        print(json.dumps(dict(ready=False,error_class=type(error).__name__)));return 1
    print(json.dumps(r,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
