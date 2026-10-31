"""Manager boundaries, using frozen synthetic cycle artifacts and fake dispatch."""
from pathlib import Path
from threading import Event
import json
import pytest
from ops.pi.tests.test_local_cycle import entry
from ops.pi.tests.test_maintenance_adapters import pack
from ops.pi.tests.test_development_inputs import config_file
from ops.pi.development_inputs import file_hash,read_json
from ops.pi import manager

@pytest.fixture
def queue(entry):
    p,c,sc,*_=entry
    state=p.parent/'manager.sqlite';billing=Path(sc['ledger_path'])
    manager.init(state,billing,mode='SIMULATED')
    return state,billing,p,c

def request_for(queue,name='one'):
    state,billing,p,_=queue
    target=p.with_name('cycle-'+name+'.json')
    if not target.exists():
        c=read_json(p);selection=read_json(c['selection_config_path']);templates=read_json(c['templates_path'])
        selection['run_id']='selection-'+name;selection['root']=str(p.parent/('selection-output-'+name))
        sp=p.with_name('selection-'+name+'.json');sp.write_text(json.dumps(selection));sp.chmod(0o600)
        tmap={}
        for key,value in templates.items():
            tc=read_json(value['path']);tc['root']=str(p.parent/('development-output-'+name));tc['run_id']='development-'+name
            tp=p.with_name('template-'+name+'.json');tp.write_text(json.dumps(tc));tp.chmod(0o600)
            tmap[key]=dict(path=str(tp),sha256=file_hash(tp))
        mp=p.with_name('templates-'+name+'.json');mp.write_text(json.dumps(tmap));mp.chmod(0o600)
        c.update(cycle_id='cycle-'+name,root=str(p.parent/('cycle-output-'+name)),
            selection_config_path=str(sp),selection_config_sha256=file_hash(sp),templates_path=str(mp),templates_sha256=file_hash(mp))
        target.write_text(json.dumps(c));target.chmod(0o600)
    return target

def enqueue(queue,name='one',priority=0):
    state,billing,*_=queue;target=request_for(queue,name)
    return manager.enqueue(state,billing,name,target,file_hash(target),priority=priority,mode='SIMULATED')

def result(request,**kwargs):
    c=read_json(request)
    return dict(operation_id='maintenance:'+c['cycle_id'],schema_version=1,status='done',
        evidence=dict(verified=True,mode='SIMULATED',released=False,next_action='review_candidate'))

def test_init_and_status_private_readonly(queue):
    state,billing,*_=queue
    assert state.stat().st_mode&0o777==0o600
    before={str(p):p.read_bytes() for p in state.parent.rglob('*') if p.is_file()}
    report=manager.status(state,billing,mode='SIMULATED')
    assert report['metrics']['registered_tasks']==0
    assert before=={str(p):p.read_bytes() for p in state.parent.rglob('*') if p.is_file()}

def test_missing_status_does_not_create_state(entry):
    p,c,sc,*_=entry;state=p.parent/'missing.sqlite'
    with pytest.raises((ValueError,OSError)):manager.status(state,Path(sc['ledger_path']))
    assert not state.exists()

def test_enqueue_idempotent_and_binding_immutable(queue):
    first=enqueue(queue);again=enqueue(queue)
    assert first['registered'] and again['registered'] and again['replayed']
    state,billing,p,_=queue
    assert manager.status(state,billing,mode='SIMULATED')['metrics']['registered_tasks']==1
    with pytest.raises(ValueError):enqueue(queue,priority=1)

def test_dispatch_once_across_restarts(queue):
    enqueue(queue);state,billing,*_=queue;calls=[]
    def execute(p,**kw):calls.append(1);return result(p)
    first=manager.run(state,billing,mode='SIMULATED',executor=execute)
    second=manager.run(state,billing,mode='SIMULATED',executor=execute)
    assert first['dispatched']==1 and second['dispatched']==0 and len(calls)==1
    s=manager.status(state,billing,mode='SIMULATED')
    assert s['tasks'][0]['state']=='done' and s['metrics']['dispatch_claims']==1
    assert s['metrics']['model_attempts'] is None

def test_priority_order_and_bounded_batch(queue):
    enqueue(queue,'low',0);enqueue(queue,'high',9);state,billing,*_=queue
    a=manager.run(state,billing,max_tasks=1,mode='SIMULATED',executor=result)
    assert a['tasks']==['high']
    b=manager.run(state,billing,mode='SIMULATED',executor=result)
    assert b['tasks']==['low']

def test_runtime_exception_blocks_queue_without_replay(queue):
    enqueue(queue,'one');enqueue(queue,'two');state,billing,*_=queue;calls=[]
    def crash(*a,**kw):calls.append(1);raise RuntimeError('response lost')
    assert manager.run(state,billing,mode='SIMULATED',executor=crash)['status']=='uncertain'
    again=manager.run(state,billing,mode='SIMULATED',executor=crash)
    assert again['dispatched']==0 and again['reason']=='reconciliation_required' and len(calls)==1

def test_pending_claim_never_calls_executor(queue,monkeypatch):
    enqueue(queue);state,billing,*_=queue
    original=manager._run_action
    def interrupted(ledger,ctx,callback):
        ledger.intent(ctx['operation_id'],'iteration_stage',ctx)
        raise KeyboardInterrupt()
    monkeypatch.setattr(manager,'_run_action',interrupted)
    with pytest.raises(KeyboardInterrupt):manager.run(state,billing,mode='SIMULATED',executor=result)
    monkeypatch.setattr(manager,'_run_action',original)
    assert manager.run(state,billing,mode='SIMULATED',executor=lambda *a,**k:pytest.fail('replay'))['reason']=='reconciliation_required'

@pytest.mark.parametrize('kind',['blocked','uncertain','malformed','wrong_id','wrong_mode','released','schema_bool'])
def test_outcome_validation_and_stop(queue,kind):
    enqueue(queue,'one');enqueue(queue,'two');state,billing,*_=queue
    def execute(p,**kw):
        r=result(p)
        if kind in ('blocked','uncertain'):r['status']=kind;r['evidence']={'mode':'SIMULATED','released':False}
        if kind=='malformed':return None
        if kind=='wrong_id':r['operation_id']='other'
        if kind=='wrong_mode':r['evidence']['mode']='ACTUAL'
        if kind=='released':r['evidence']['released']=True
        if kind=='schema_bool':r['schema_version']=True
        return r
    r=manager.run(state,billing,mode='SIMULATED',executor=execute)
    assert r['dispatched']==1 and r['status']!='done'

@pytest.mark.parametrize('field,value',[('max_tasks',True),('max_tasks',21),('seconds',True),('seconds',3601)])
def test_invalid_bounds_do_not_dispatch(queue,field,value):
    enqueue(queue);state,billing,*_=queue
    with pytest.raises(ValueError):manager.run(state,billing,mode='SIMULATED',executor=result,**{field:value})

def test_cancel_before_dispatch_has_no_claim(queue):
    enqueue(queue);state,billing,*_=queue;cancel=Event();cancel.set()
    r=manager.run(state,billing,cancel=cancel,mode='SIMULATED',executor=result)
    assert r['dispatched']==0 and r['reason']=='cancelled'

def test_config_drift_blocks_before_claim(queue):
    enqueue(queue);state,billing,p,_=queue;p.with_name('cycle-one.json').write_text('{}')
    r=manager.run(state,billing,mode='SIMULATED',executor=lambda *a,**k:pytest.fail('dispatch'))
    assert r['status']=='blocked' and r['dispatched']==0

def test_actual_forbids_injected_executor(queue):
    state,billing,*_=queue
    with pytest.raises(ValueError):manager.run(state,billing,mode='ACTUAL',executor=result)

@pytest.mark.parametrize('suffix',['','-wal','-shm','-journal','.tools.lock'])
def test_state_cannot_occupy_billing_role(entry,suffix):
    p,c,sc,*_=entry;billing=Path(sc['ledger_path'])
    state=billing.with_suffix('.tools.lock') if suffix=='.tools.lock' else Path(str(billing)+suffix)
    before=billing.read_bytes()
    with pytest.raises(ValueError):manager.init(state,billing)
    assert billing.read_bytes()==before

def test_queue_state_cannot_enter_cycle_source(entry):
    p,c,sc,*_=entry;state=Path(sc['source_path'])/'queue.sqlite'
    state.parent.chmod(0o700)
    manager.init(state,Path(sc['ledger_path']),mode='SIMULATED')
    with pytest.raises(ValueError):manager.enqueue(state,Path(sc['ledger_path']),'bad',p,file_hash(p),mode='SIMULATED')


def test_reused_native_cycle_is_rejected(queue):
    enqueue(queue,'one');state,billing,p,_=queue;request=p.with_name('cycle-one.json')
    with pytest.raises(ValueError,match='identity reused'):
        manager.enqueue(state,billing,'other',request,file_hash(request),mode='SIMULATED')


def test_insufficient_remaining_time_has_no_claim(queue):
    enqueue(queue);state,billing,*_=queue
    r=manager.run(state,billing,seconds=1,mode='SIMULATED',executor=lambda *a,**k:pytest.fail('too short'))
    assert r['dispatched']==0
    assert manager.status(state,billing,mode='SIMULATED')['metrics']['dispatch_claims']==0


def test_expired_batch_is_not_reported_success(queue,monkeypatch):
    enqueue(queue);state,billing,p,_=queue;original=manager.inspect_cycle
    def inspect(request):
        c,s,t,templates=original(request);c['deadline_seconds']=1;return c,s,t,templates
    # Only this deterministic timer test shortens the synthetic parent contract.
    monkeypatch.setattr(manager,'inspect_cycle',inspect)
    # The stored resources do not contain the live deadline.
    def execute(p,*,cancel):
        assert cancel.wait(3);return result(p)
    r=manager.run(state,billing,seconds=2,max_tasks=1,mode='SIMULATED',executor=execute)
    assert r['status']=='blocked' and r['reason']=='deadline'
    assert manager.status(state,billing,mode='SIMULATED')['tasks'][0]['state']=='done'


def test_actual_native_boundary_requires_saved_receipt(entry,monkeypatch):
    p,c,sc,*_=entry;state=p.parent/'actual-manager.sqlite';billing=Path(sc['ledger_path'])
    manager.init(state,billing);manager.enqueue(state,billing,'actual',p,file_hash(p));before=billing.read_bytes();calls=[]
    def execute(request,**kw):
        calls.append(1);r=result(request);r['evidence']['mode']='ACTUAL'
        root=Path(read_json(request)['root']);root.mkdir(mode=0o700)
        out=root/'result.json';out.write_text(json.dumps(r));out.chmod(0o600)
        return r
    monkeypatch.setattr(manager,'execute_cycle',execute)
    assert manager.run(state,billing)['status']=='done'
    assert manager.run(state,billing)['dispatched']==0 and len(calls)==1 and billing.read_bytes()==before


def test_actual_does_not_trust_returned_dict_without_artifact(entry,monkeypatch):
    p,c,sc,*_=entry;state=p.parent/'actual-manager.sqlite';billing=Path(sc['ledger_path'])
    manager.init(state,billing);manager.enqueue(state,billing,'actual',p,file_hash(p))
    def execute(request,**kw):
        r=result(request);r['evidence']['mode']='ACTUAL';return r
    monkeypatch.setattr(manager,'execute_cycle',execute)
    assert manager.run(state,billing)['status']=='uncertain'
    assert manager.run(state,billing)['reason']=='reconciliation_required'


def test_readonly_status_hardlinks_rejected(queue):
    state,billing,*_=queue;link=state.with_name('alias.sqlite');link.hardlink_to(state)
    with pytest.raises(ValueError):manager.status(state,billing,mode='SIMULATED')


def test_completed_registration_replay_does_not_recheck_used_output(queue,monkeypatch):
    enqueue(queue);state,billing,*_=queue
    manager.run(state,billing,mode='SIMULATED',executor=result)
    monkeypatch.setattr(manager,'inspect_cycle',lambda *a: (_ for _ in ()).throw(ValueError('output exists')))
    assert enqueue(queue)['replayed'] is True


def test_cancel_stale_unstarted_task_unblocks_next_job(queue):
    enqueue(queue,'one',9);enqueue(queue,'two');state,billing,p,_=queue
    p.with_name('cycle-one.json').write_text('{}')
    assert manager.run(state,billing,mode='SIMULATED',executor=result)['dispatched']==0
    manager.cancel_task(state,billing,'one','host invalidated stale bytes',mode='SIMULATED')
    r=manager.run(state,billing,mode='SIMULATED',executor=result)
    assert r['tasks']==['two'] and r['status']=='done'
    assert manager.status(state,billing,mode='SIMULATED')['metrics']['cancelled_tasks']==1


def test_unknown_dispatch_cannot_be_cancelled_to_release_queue(queue):
    enqueue(queue);state,billing,*_=queue
    def error(*a,**k):raise RuntimeError()
    manager.run(state,billing,mode='SIMULATED',executor=error)
    with pytest.raises(ValueError):manager.cancel_task(state,billing,'one','skip',mode='SIMULATED')
    assert manager.run(state,billing,mode='SIMULATED',executor=result)['reason']=='reconciliation_required'


@pytest.mark.parametrize('suffix',['-shm','-wal','-journal'])
def test_sidecar_hardlink_rejected_before_any_sqlite_write(queue,suffix):
    state,billing,p,_=queue;c=read_json(p);sc=read_json(c['selection_config_path']);policy=Path(sc['policy_path'])
    original=policy.read_bytes();side=Path(str(state)+suffix);assert not side.exists();side.hardlink_to(policy)
    with pytest.raises(ValueError):enqueue(queue)
    assert policy.read_bytes()==original


def test_sidecar_created_during_executor_is_checked_before_receipt_write(queue):
    enqueue(queue);state,billing,p,_=queue;policy=Path(read_json(read_json(p)['selection_config_path'])['policy_path']);original=policy.read_bytes()
    def execute(request,**kw):
        side=Path(str(state)+'-shm');assert not side.exists();side.hardlink_to(policy);return result(request)
    with pytest.raises(ValueError):manager.run(state,billing,mode='SIMULATED',executor=execute)
    assert policy.read_bytes()==original


def test_foreign_terminal_receipt_is_rejected_on_recovery(queue):
    from ops.pi.ledger import Ledger
    from ops.pi.contracts import Receipt
    enqueue(queue);state,billing,*_=queue
    ledger=Ledger(state,existing=True);_,_,_,tasks,_=manager._snapshot(state,billing,'SIMULATED');ctx=manager._context(tasks[0])
    ledger.intent(ctx['operation_id'],'iteration_stage',ctx)
    ledger.finish(Receipt(ctx['operation_id'],'done',dict(verified=False,mode='ACTUAL',binding='wrong')))
    with pytest.raises(ValueError):manager.status(state,billing,mode='SIMULATED')
    with pytest.raises(ValueError):manager.run(state,billing,mode='SIMULATED',executor=result)


def test_per_dispatch_and_batch_timing_exported(queue):
    enqueue(queue);manager.run(queue[0],queue[1],mode='SIMULATED',executor=result)
    s=manager.status(queue[0],queue[1],mode='SIMULATED')
    assert s['dispatches'][0]['elapsed_ms']>=0 and s['dispatches'][0]['measurement']=='measured'
    assert s['runs'][0]['elapsed_ms']>=s['dispatches'][0]['elapsed_ms']


def test_static_presealed_second_task_stops_when_billing_changes(queue):
    from ops.pi.ledger import Ledger
    enqueue(queue,'one');enqueue(queue,'two');calls=[]
    def execute(p,**kw):
        calls.append(1);Ledger(queue[1],existing=True).append_event('synthetic_settlement',{})
        return result(p)
    r=manager.run(queue[0],queue[1],mode='SIMULATED',executor=execute)
    assert r['status']=='blocked' and r['dispatched']==1 and len(calls)==1


def publish(folder,request,task_id):
    folder.mkdir(mode=0o700,exist_ok=True)
    value=dict(schema='pi-manager-admission-v1',task_id=task_id,request_path=str(request),
        request_sha256=file_hash(request),priority=0,mode='SIMULATED')
    p=folder/(task_id+'.task.json');p.write_text(json.dumps(value));p.chmod(0o600)


def test_inbox_just_in_time_after_billing_change(queue):
    from ops.pi.ledger import Ledger
    from ops.pi.development_inputs import ledger_snapshot
    enqueue(queue,'one');state,billing,p,_=queue;two=request_for(queue,'two');folder=p.parent/'inbox'
    folder.mkdir(mode=0o700);calls=[]
    def execute(request,**kw):
        calls.append(Path(request).name)
        if len(calls)==1:
            Ledger(billing,existing=True).append_event('synthetic_settlement',{})
            sha=ledger_snapshot(billing)['sha256'];c=read_json(two);sc=read_json(c['selection_config_path'])
            sc['ledger_sha256']=sha;sp=Path(c['selection_config_path']);sp.write_text(json.dumps(sc))
            c['selection_config_sha256']=file_hash(sp);mapping=read_json(c['templates_path'])
            for pin in mapping.values():
                tp=Path(pin['path']);t=read_json(tp);t['ledger_sha256']=sha;tp.write_text(json.dumps(t));pin['sha256']=file_hash(tp)
            mp=Path(c['templates_path']);mp.write_text(json.dumps(mapping));c['templates_sha256']=file_hash(mp)
            two.write_text(json.dumps(c));publish(folder,two,'two')
        return result(request)
    r=manager.run(state,billing,max_tasks=2,inbox=folder,idle_seconds=1,mode='SIMULATED',executor=execute)
    assert r['status']=='done' and r['tasks']==['one','two'] and len(calls)==2


def test_actual_only_one_presealed_pending_request(entry):
    p,c,sc,*_=entry;state=p.parent/'actual-manager.sqlite';billing=Path(sc['ledger_path'])
    manager.init(state,billing);synthetic=(state,billing,p,c)
    one=request_for(synthetic,'one');two=request_for(synthetic,'two')
    manager.enqueue(state,billing,'one',one,file_hash(one))
    with pytest.raises(ValueError,match='one ready'):
        manager.enqueue(state,billing,'two',two,file_hash(two))


def test_unknown_dispatch_blocks_inbox(queue):
    enqueue(queue);state,billing,p,_=queue;folder=p.parent/'inbox';folder.mkdir(mode=0o700)
    def crash(*a,**kw):raise RuntimeError()
    manager.run(state,billing,mode='SIMULATED',executor=crash)
    publish(folder,request_for(queue,'two'),'two')
    r=manager.run(state,billing,inbox=folder,idle_seconds=1,mode='SIMULATED',executor=result)
    assert r['reason']=='reconciliation_required' and manager.status(state,billing,mode='SIMULATED')['metrics']['registered_tasks']==1


def test_pending_dispatch_timing_is_unknown(queue,monkeypatch):
    enqueue(queue);state,billing,*_=queue
    def stop(ledger,ctx,callback):
        ledger.intent(ctx['operation_id'],'iteration_stage',ctx);raise KeyboardInterrupt()
    monkeypatch.setattr(manager,'_run_action',stop)
    with pytest.raises(KeyboardInterrupt):manager.run(state,billing,mode='SIMULATED',executor=result)
    item=manager.status(state,billing,mode='SIMULATED')['dispatches'][0]
    assert item['elapsed_ms'] is None and item['measurement']=='unknown'


def test_empty_inbox_cancel_wait_is_bounded(queue):
    import threading
    state,billing,p,_=queue;folder=p.parent/'inbox';folder.mkdir(mode=0o700);cancel=Event()
    timer=threading.Timer(.1,cancel.set);timer.start()
    try:r=manager.run(state,billing,inbox=folder,idle_seconds=1,cancel=cancel,mode='SIMULATED',executor=result)
    finally:timer.cancel()
    assert r['reason']=='cancelled' and r['dispatched']==0


def test_inbox_manifest_cannot_change_completed_identity(queue):
    enqueue(queue);state,billing,p,_=queue;manager.run(state,billing,mode='SIMULATED',executor=result)
    folder=p.parent/'inbox';request=p.with_name('cycle-one.json');publish(folder,request,'one')
    item=folder/'one.task.json';m=read_json(item);m['request_sha256']='0'*64;item.write_text(json.dumps(m))
    assert manager.run(state,billing,inbox=folder,mode='SIMULATED',executor=result)['reason']=='inbox_admission_rejected'
