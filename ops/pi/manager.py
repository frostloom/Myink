"""Host-owned finite queue. Pending dispatches stop; candidates never auto-adopt."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat
from threading import Event,Timer
import time

from .contracts import Receipt
from .development_inputs import digest,file_hash,ledger_snapshot,path,read_json
from .development_launcher import require
from .iteration import _run_action
from .ledger import Ledger as BaseLedger
from .local_cycle import (_disjoint,_host_roles,_inspect as inspect_cycle,_ledger_roles,
                          execute as execute_cycle)

MODES=('ACTUAL','SIMULATED')
MAX_TASKS=1000


def _plain(p):
    info=p.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=64*1024**2,
            'bounded single-link regular ledger required')


def _roles(state):
    return _ledger_roles(state)+[state.with_suffix('.manager.lock')]


def _private_state_roles(state):
    for role in _roles(state):
        path(role)
        if role.exists():_plain(path(role,private=True))


class Ledger(BaseLedger):
    """Recheck SQLite aliases before every transaction, including after callbacks."""
    @contextmanager
    def transaction(self):
        _private_state_roles(self.path)
        with super().transaction() as connection:yield connection


def _paths(state,billing):
    state,billing=path(state),path(billing,private=True);_plain(billing)
    require(state.parent.is_dir() and stat.S_IMODE(state.parent.stat().st_mode)==0o700,
            'private manager parent required')
    for a in _roles(state):
        for b in _ledger_roles(billing):_disjoint(a,b)
    _private_state_roles(state)
    for role in _ledger_roles(billing):
        path(role)
        if role.exists():_plain(path(role,private=True))
    return state,billing


def _identity(billing,mode):
    require(mode in MODES,'explicit manager mode required')
    return dict(schema='pi-manager-v1',billing_path=str(billing),mode=mode)


def init(state,billing,*,mode='ACTUAL'):
    state,billing=_paths(state,billing);identity=_identity(billing,mode)
    require(not state.exists(),'new manager state required');ledger_snapshot(billing)
    fd=os.open(state,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    ledger=Ledger(state);ledger.intent('manager:identity','manager_identity',identity)
    ledger.finish(Receipt('manager:identity','done',dict(verified=True,binding=digest(identity))))
    return dict(initialized=True,mode=mode)


def _snapshot(state,billing,mode):
    state,billing=_paths(state,billing);expected=_identity(billing,mode)
    snap=ledger_snapshot(state)
    rows={r['operation_id']:dict(r,payload=Ledger._decode(r['payload']),
        evidence=Ledger._decode(r['evidence']) if r['evidence'] is not None else None) for r in snap['operations']}
    header=rows.get('manager:identity')
    require(header and header['kind']=='manager_identity' and header['status']=='done'
        and header['payload']==expected and header['evidence']==dict(verified=True,binding=digest(expected)),
        'manager identity drift or incomplete initialization')
    sequence={}
    for event in snap['events']:
        if event['kind']=='intent':
            value=Ledger._decode(event['payload']);sequence[value['operation_id']]=event['id']
    tasks=[r for r in rows.values() if r['kind']=='manager_task']
    require(len(tasks)<=MAX_TASKS,'manager history limit')
    tasks.sort(key=lambda r:(-r['payload']['priority'],sequence[r['operation_id']]))
    known={'manager:identity'}
    for task in tasks:
        require(task['status'] in ('pending','done'),'invalid registration state')
        payload=task['payload'];known.add(task['operation_id'])
        if task['status']=='done':require(task['evidence']==dict(verified=True,binding=digest(payload)),'invalid task registration receipt')
        require(task['operation_id']=='manager:task:'+payload['task_id'] and payload['mode']==mode
            and payload['billing_path']==str(billing),'foreign manager registration')
        for suffix,kind in ((':dispatch','iteration_stage'),(':cancel','manager_cancel'),(':reconciliation','manager_reconciliation')):
            key=task['operation_id']+suffix
            if key not in rows:continue
            row=rows[key];known.add(key)
            require(row['kind']==kind,'foreign manager operation')
            if suffix==':dispatch':
                require(row['payload']==_context(task),'dispatch input identity drift')
                if row['status'] in ('done','blocked','failed'):
                    e=row['evidence'];require(isinstance(e,dict) and e.get('mode')==mode
                        and e.get('binding')==digest(payload) and e.get('released') is False
                        and e.get('verified') is (row['status']=='done')
                        and isinstance(e.get('cycle_result_sha256'),str) and re.fullmatch('[a-f0-9]{64}',e['cycle_result_sha256']),
                        'invalid terminal dispatch receipt')
                    require(type(e.get('elapsed_ms')) in (int,float) and math.isfinite(e['elapsed_ms']) and e['elapsed_ms']>=0,
                        'invalid dispatch timing')
                    if row['status']=='done':require(e.get('next_action') in ('observe','review_candidate'),'invalid completed dispatch action')
            elif suffix==':cancel':
                require(row['payload'].get('task_binding')==digest(payload) and row['payload'].get('mode')==mode,'cancellation identity drift')
                if row['status']=='done':require(row['evidence']==dict(verified=True,binding=digest(row['payload'])),'invalid cancellation receipt')
            else:
                from .selection_abandonment import validate_resolution
                require(task['operation_id']+':dispatch' in rows,'reconciliation requires a dispatch')
                validate_resolution(task,rows[task['operation_id']+':dispatch'],row,state,billing)
    require(set(rows)==known,'foreign operations in manager state')
    return state,billing,rows,tasks,snap


def _resources(request,c,selection,templates):
    outputs=[path(c['root']),path(selection['root'])]
    inputs=[request]+_ledger_roles(path(c['control_ledger_path']))
    for value in [selection,*[read_json(t['path']) for t in templates.values()]]:
        inputs.extend(path(value[k]) for k in value if k.endswith('_path'))
        inputs.extend(_host_roles(value))
    inputs.extend([path(c['selection_config_path']),path(c['templates_path'])])
    for template in templates.values():
        target=path(template['path']);inputs.append(target);outputs.append(path(read_json(target)['root']))
    identities=[c['cycle_id'],selection['run_id']]+[read_json(t['path'])['run_id'] for t in templates.values()]
    return dict(inputs=sorted(set(map(str,inputs))),outputs=sorted(set(map(str,outputs))),identities=identities)


def _package(state,billing,request,sha):
    request=path(request,private=True)
    require(file_hash(request)==sha,'manager request drift')
    c,selection,_,templates=inspect_cycle(request)
    require(path(selection['ledger_path'],private=True)==billing,'manager billing identity drift')
    resources=_resources(request,c,selection,templates)
    for role in _roles(state):
        for value in resources['inputs']+resources['outputs']:_disjoint(role,Path(value))
    require(file_hash(request)==sha,'manager request changed during check')
    return c,resources


def _enqueue(state,billing,task_id,request,sha256,*,priority=0,mode='ACTUAL'):
    require(isinstance(task_id,str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',task_id),'bounded task id required')
    require(type(priority) is int and 0<=priority<=9,'bounded priority required')
    require(isinstance(sha256,str) and re.fullmatch('[a-f0-9]{64}',sha256),'frozen request digest required')
    state,billing,rows,tasks,_=_snapshot(state,billing,mode)
    c,resources=_package(state,billing,request,sha256)
    payload=dict(task_id=task_id,request_path=str(request),request_sha256=sha256,priority=priority,
        cycle_id=c['cycle_id'],mode=mode,billing_path=str(billing),resources=resources)
    op='manager:task:'+task_id;old=rows.get(op)
    if old:
        require(old['kind']=='manager_task' and old['payload']==payload,'manager task identity conflict')
        if old['status']=='done':return dict(registered=True,task_id=task_id,replayed=True)
        require(old['status']=='pending','invalid task registration')
    else:
        require(not _unresolved(rows),'unresolved dispatch requires reconciliation before new registration')
        if mode=='ACTUAL':
            require(not any(_dispatch_id(t) not in rows and t['operation_id']+':cancel' not in rows for t in tasks),
                'only one ready ACTUAL request; publish next after fresh independent checkpoint review')
        require(len(tasks)<MAX_TASKS,'manager history limit')
        for task in tasks:
            prior=task['payload']['resources']
            require(not set(prior['identities'])&set(resources['identities']),'native cycle/run identity reused')
            for output in resources['outputs']:
                for value in prior['inputs']+prior['outputs']:_disjoint(Path(output),Path(value))
            for output in prior['outputs']:
                for value in resources['inputs']:_disjoint(Path(output),Path(value))
        for prior in rows.values():
            if prior['kind']=='manager_reconciliation':
                for output in resources['outputs']:
                    for protected in (path(prior['payload']['audit_path']).parent,path(prior['payload']['review_path'])):
                        _disjoint(Path(output),protected)
    ledger=Ledger(state,existing=True);ledger.intent(op,'manager_task',payload)
    # Registration has no external side effect. A pending registration can be
    # completed only by explicit enqueue after the same full input preflight.
    ledger.finish(Receipt(op,'done',dict(verified=True,binding=digest(payload))))
    return dict(registered=True,task_id=task_id,replayed=old is not None)


def enqueue(state,billing,task_id,request,sha256,*,priority=0,mode='ACTUAL'):
    require(isinstance(task_id,str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',task_id),'bounded task id required')
    require(type(priority) is int and 0<=priority<=9,'bounded priority required')
    state,billing,rows,_,_=_snapshot(state,billing,mode)
    old=rows.get('manager:task:'+task_id)
    if old and old['status']=='done':
        payload=old['payload']
        require(payload['request_path']==str(path(request)) and payload['request_sha256']==sha256
            and payload['priority']==priority,'manager task identity conflict')
        return dict(registered=True,task_id=task_id,replayed=True)
    # Validate role isolation before even creating the manager lock pathname.
    _package(state,billing,request,sha256)
    lock_path=state.with_suffix('.manager.lock');path(lock_path)
    fd=os.open(lock_path,os.O_RDWR|os.O_CREAT,0o600)
    with os.fdopen(fd,'a+b') as lock:
        _plain(path(lock_path,private=True))
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:raise ValueError('manager busy') from error
        # Repeat registration checks under the same lock used by dispatch.
        return _enqueue(state,billing,task_id,request,sha256,priority=priority,mode=mode)


def _dispatch_id(task):return task['operation_id']+':dispatch'


def _resolved(rows,dispatch_id):
    return rows.get(dispatch_id.removesuffix(':dispatch')+':reconciliation',{}).get('status')=='done'


def _unresolved(rows):
    return [r for r in rows.values() if r['kind']=='iteration_stage' and r['status'] in ('pending','uncertain')
        and not _resolved(rows,r['operation_id'])]


def _context(task):
    p=task['payload']
    return dict(operation_id=_dispatch_id(task),mode=p['mode'],input_hash=digest(p),task_id=p['task_id'],
                request_path=p['request_path'],request_sha256=p['request_sha256'])


def cancel_task(state,billing,task_id,reason,*,mode='ACTUAL'):
    require(isinstance(reason,str) and 0<len(reason.strip())<=1000,'bounded host cancellation reason required')
    state,billing,_,_,_=_snapshot(state,billing,mode)
    lock_path=state.with_suffix('.manager.lock');path(lock_path)
    fd=os.open(lock_path,os.O_RDWR|os.O_CREAT,0o600)
    with os.fdopen(fd,'a+b') as lock:
        _plain(path(lock_path,private=True))
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:raise ValueError('manager busy') from error
        _,_,rows,_,_=_snapshot(state,billing,mode);task=rows.get('manager:task:'+task_id)
        require(task and task['kind']=='manager_task' and task['status']=='done','registered task required')
        require(_dispatch_id(task) not in rows,'started dispatch requires reconciliation, never cancellation')
        op=task['operation_id']+':cancel';old=rows.get(op)
        if old and old['status']=='done':return dict(cancelled=True,task_id=task_id,replayed=True)
        payload=dict(task_binding=digest(task['payload']),reason=reason,mode=mode)
        ledger=Ledger(state,existing=True);ledger.intent(op,'manager_cancel',payload)
        ledger.finish(Receipt(op,'done',dict(verified=True,binding=digest(payload))))
        return dict(cancelled=True,task_id=task_id,replayed=False)


def status(state,billing,*,mode='ACTUAL'):
    _,_,rows,tasks,snap=_snapshot(state,billing,mode)
    dispatches=[r for r in rows.values() if r['kind']=='iteration_stage']
    counts={key:sum(r['status']==key for r in dispatches) for key in ('done','blocked','failed','pending','uncertain')}
    runs=[Ledger._decode(e['payload']) for e in snap['events'] if e['kind']=='manager_run']
    return dict(schema='pi-manager-status-v1',mode=mode,state_sha256=snap['sha256'],tasks=[dict(
        task_id=t['payload']['task_id'],priority=t['payload']['priority'],request_sha256=t['payload']['request_sha256'],
        resolution='abandoned' if _resolved(rows,_dispatch_id(t)) else None,
        state='cancelled' if rows.get(t['operation_id']+':cancel',{}).get('status')=='done' else 'registration_pending' if t['status']!='done' else rows.get(_dispatch_id(t),{}).get('status','queued')) for t in tasks],
        dispatches=[dict(task_id=r['payload']['task_id'],status=r['status'],mode=mode,
            elapsed_ms=(r.get('evidence') or {}).get('elapsed_ms'),
            measurement='measured' if (r.get('evidence') or {}).get('elapsed_ms') is not None else 'unknown') for r in dispatches],
        runs=runs,metrics=dict(cancelled_tasks=sum(r['kind']=='manager_cancel' and r['status']=='done' for r in rows.values()),registered_tasks=sum(t['status']=='done' for t in tasks),dispatch_claims=len(dispatches),
            outcomes=counts,abandoned_tasks=sum(_resolved(rows,_dispatch_id(t)) for t in tasks),unresolved_dispatches=len(_unresolved(rows)),recorded_runs=len(runs),reconciliation_stops=sum(r['reason']=='reconciliation_required' for r in runs),
            model_attempts=None,known_cost_microyuan=None,model_measurement='not_collected_by_queue'))


def _inbox_path(folder,state,billing,tasks):
    folder=path(folder)
    require(folder.is_dir() and stat.S_IMODE(folder.stat().st_mode)==0o700,'private inbox directory required')
    for role in _roles(state)+_ledger_roles(billing):_disjoint(folder,role)
    for task in tasks:
        for value in task['payload']['resources']['inputs']+task['payload']['resources']['outputs']:_disjoint(folder,Path(value))
    return folder


def _ingest(folder,state,billing,mode,rows,tasks):
    folder=_inbox_path(folder,state,billing,tasks);files=sorted(folder.glob('*.task.json'))
    require(len(files)<=MAX_TASKS,'bounded inbox required');candidates=[]
    for p in files:
        _plain(path(p,private=True));require(p.stat().st_size<=1048576,'bounded admission manifest required')
        m=read_json(p)
        require(isinstance(m,dict) and set(m)=={'schema','task_id','request_path','request_sha256','priority','mode'}
            and m['schema']=='pi-manager-admission-v1' and m['mode']==mode,'strict host admission required')
        require(isinstance(m['task_id'],str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',m['task_id'])
            and type(m['priority']) is int and 0<=m['priority']<=9,'bounded admission identity required')
        old=rows.get('manager:task:'+m['task_id'])
        if old:
            previous=old['payload'];require(previous['request_path']==m['request_path']
                and previous['request_sha256']==m['request_sha256'] and previous['priority']==m['priority'],
                'inbox task identity conflict')
            continue
        candidates.append(m)
    if not candidates:return False
    m=sorted(candidates,key=lambda x:(-x['priority'],x['task_id']))[0]
    _,resources=_package(state,billing,m['request_path'],m['request_sha256'])
    for value in resources['inputs']+resources['outputs']:_disjoint(folder,Path(value))
    _enqueue(state,billing,m['task_id'],m['request_path'],m['request_sha256'],priority=m['priority'],mode=mode)
    return True


def run(state,billing,*,max_tasks=20,seconds=3600,cancel=None,mode='ACTUAL',executor=None,inbox=None,idle_seconds=0):
    require(type(max_tasks) is int and 0<max_tasks<=20 and type(seconds) is int and 0<seconds<=3600,
            'bounded manager run required')
    require((mode=='ACTUAL' and executor is None) or (mode=='SIMULATED' and callable(executor)),
            'actual execution cannot inject a runner')
    require(type(idle_seconds) is int and 0<=idle_seconds<=600,'bounded inbox wait required')
    state,billing,_,tasks,_=_snapshot(state,billing,mode)
    if inbox is not None:_inbox_path(inbox,state,billing,tasks)
    lock_path=state.with_suffix('.manager.lock');path(lock_path)
    fd=os.open(lock_path,os.O_RDWR|os.O_CREAT,0o600)
    with os.fdopen(fd,'a+b') as lock:
        _plain(path(lock_path,private=True))
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return dict(status='blocked',reason='manager_busy',dispatched=0,tasks=[],mode=mode)
        started=time.monotonic();until=started+seconds;cancel=cancel if cancel is not None else Event()
        timer=Timer(seconds,cancel.set);timer.daemon=True;timer.start();used=[];final='done';reason='idle'
        ledger=Ledger(state,existing=True)
        def stop():
            if time.monotonic()>=until:return 'deadline'
            if cancel.is_set():return 'cancelled'
            return None
        try:
            while len(used)<max_tasks:
                reason=stop()
                if reason:final='blocked';break
                _,_,rows,tasks,_=_snapshot(state,billing,mode)
                if any(r['kind']=='manager_reconciliation' and r['status']=='pending' for r in rows.values()):
                    final='uncertain';reason='reconciliation_incomplete';break
                pending=_unresolved(rows)
                if pending:final='uncertain';reason='reconciliation_required';break
                if any(r['kind']=='manager_cancel' and r['status']=='pending' for r in rows.values()):
                    final='blocked';reason='cancellation_incomplete';break
                if any(t['status']!='done' for t in tasks):final='blocked';reason='registration_incomplete';break
                task=next((t for t in tasks if _dispatch_id(t) not in rows and t['operation_id']+':cancel' not in rows),None)
                if task is None:
                    if inbox is not None:
                        wait_until=min(until,time.monotonic()+idle_seconds)
                        try:
                            while True:
                                if _ingest(inbox,state,billing,mode,rows,tasks):break
                                reason=stop()
                                if reason or time.monotonic()>=wait_until:break
                                cancel.wait(min(.1,max(0,wait_until-time.monotonic())))
                        except (ValueError,OSError,KeyError,TypeError):
                            final='blocked';reason='inbox_admission_rejected';break
                        if reason in ('cancelled','deadline'):final='blocked';break
                        _,_,new_rows,new_tasks,_=_snapshot(state,billing,mode)
                        if any(_dispatch_id(t) not in new_rows and t['operation_id']+':cancel' not in new_rows for t in new_tasks):continue
                    reason='idle';break
                p=task['payload']
                try:
                    c,resources=_package(state,billing,p['request_path'],p['request_sha256'])
                    require(resources==p['resources'],'task resource identity drift')
                    require(c['deadline_seconds']<=until-time.monotonic(),'insufficient remaining task time')
                except (ValueError,OSError,KeyError,TypeError):
                    final='blocked';reason='task_preflight_rejected';break
                reason=stop()
                if reason:final='blocked';break
                context=_context(task)
                used.append(p['task_id'])
                def _execute(ctx):
                    require(file_hash(p['request_path'])==p['request_sha256'],'request drift before dispatch')
                    output=(execute_cycle if mode=='ACTUAL' else executor)(p['request_path'],cancel=cancel)
                    valid=isinstance(output,dict) and set(output)=={'operation_id','status','evidence','schema_version'} and output.get('operation_id')=='maintenance:'+c['cycle_id'] and type(output.get('schema_version')) is int and output['schema_version']==1
                    e=output.get('evidence') if valid else None
                    valid=valid and isinstance(e,dict) and e.get('mode')==mode and e.get('released') is False
                    if not valid:return Receipt(ctx['operation_id'],'uncertain',dict(reason='unbound_cycle_result'))
                    state_name=output.get('status')
                    if state_name=='done':
                        valid=e.get('verified') is True and e.get('next_action') in ('observe','review_candidate')
                        if not valid:return Receipt(ctx['operation_id'],'uncertain',dict(reason='unverified_cycle_result'))
                    elif state_name not in ('blocked','failed','uncertain'):
                        return Receipt(ctx['operation_id'],'uncertain',dict(reason='invalid_cycle_status'))
                    if mode=='ACTUAL':
                        saved=Path(c['root'])/'result.json'
                        if digest(read_json(path(saved,private=True)))!=digest(output):
                            return Receipt(ctx['operation_id'],'uncertain',dict(reason='cycle_result_artifact_mismatch'))
                    return Receipt(ctx['operation_id'],state_name,dict(verified=state_name=='done',binding=ctx['input_hash'],
                        mode=mode,cycle_result_sha256=digest(output),next_action=e.get('next_action'),released=False))
                def execute(ctx):
                    tick=time.monotonic()
                    try:receipt=_execute(ctx)
                    except Exception as error:
                        receipt=Receipt(ctx['operation_id'],'uncertain',dict(reason='adapter_outcome_unknown',error_class=type(error).__name__))
                    return Receipt(receipt.operation_id,receipt.status,dict(receipt.evidence,
                        mode=mode,binding=ctx['input_hash'],elapsed_ms=round((time.monotonic()-tick)*1000,3)))
                receipt=_run_action(ledger,context,execute)
                if receipt.status!='done':final=receipt.status;reason='cycle_not_complete';break
                reason=stop()
                if reason:final='blocked';break
                reason='batch_limit'
        finally:
            timer.cancel()
        result=dict(status=final,reason=reason,dispatched=len(used),tasks=used,mode=mode,
                    elapsed_ms=round((time.monotonic()-started)*1000,3))
        ledger.append_event('manager_run',result)
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',required=True);p.add_argument('--billing',required=True)
    sub=p.add_subparsers(dest='action',required=True);sub.add_parser('init');sub.add_parser('status')
    e=sub.add_parser('enqueue');e.add_argument('--task-id',required=True);e.add_argument('--request',required=True)
    e.add_argument('--sha256',required=True);e.add_argument('--priority',type=int,default=0)
    cancel=sub.add_parser('cancel');cancel.add_argument('--task-id',required=True);cancel.add_argument('--reason',required=True)
    r=sub.add_parser('run');r.add_argument('--max-tasks',type=int,default=20);r.add_argument('--seconds',type=int,default=3600)
    r.add_argument('--inbox');r.add_argument('--idle-seconds',type=int,default=0)
    a=p.parse_args()
    try:
        if a.action=='init':value=init(a.state,a.billing)
        elif a.action=='status':value=status(a.state,a.billing)
        elif a.action=='cancel':value=cancel_task(a.state,a.billing,a.task_id,a.reason)
        elif a.action=='enqueue':value=enqueue(a.state,a.billing,a.task_id,a.request,a.sha256,priority=a.priority)
        else:value=run(a.state,a.billing,max_tasks=a.max_tasks,seconds=a.seconds,inbox=a.inbox,idle_seconds=a.idle_seconds)
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(json.dumps(dict(status='blocked',error_class=type(error).__name__)));return 1
    print(json.dumps(value,sort_keys=True));return 0 if value.get('status','done')=='done' else 1


if __name__=='__main__':raise SystemExit(main())
