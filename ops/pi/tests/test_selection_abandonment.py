"""Synthetic stopped ACTUAL records; Docker is a fixed read-only test double."""
from dataclasses import asdict
import json,time,sys
from pathlib import Path
from hashlib import sha256
import pytest
from ops.pi import selection_abandonment as recovery,manager
from ops.pi.contracts import Receipt
from ops.pi.development_inputs import digest,file_hash,ledger_snapshot,read_json,authorization_hash
from ops.pi.ledger import Ledger
from ops.pi.selection_launcher import FIELDS,SYSTEM,selection_prompt,wire_system
from ops.pi.tests.test_maintenance_adapters import pack
from ops.pi.tests.test_development_inputs import config_file

REAL_VERIFY_ABSENCE = recovery.verify_absence

@pytest.fixture
def stopped(pack,tmp_path,monkeypatch,request):
    unknown_fee=getattr(request,'param',None)=='unknown'
    adapter,ctx,c,template,_=pack
    def write(p,v):
        p=Path(p);p.write_text(json.dumps(v));p.chmod(0o600);return p
    task=dict(ctx['task']);task['evidence_sha256']=digest(task['baseline']);tasks=[task]
    catalog=write(tmp_path/'catalog.json',tasks);before=ledger_snapshot(c['ledger_path'])
    sc={k:c[k] for k in FIELDS if k in c};sc.update(docker=str(Path(sys.executable).resolve()),schema='pi-maintenance-selection-v1',run_id='selection-stop',root=str(tmp_path/'selection'),catalog_path=str(catalog),catalog_sha256=file_hash(catalog),deadline_seconds=120,review_path=str(tmp_path/'selection-review.json'),review_sha256='0'*64)
    review=dict(source='independent_review',verified=True,result='approved',reviewer='entry-review',authorization_sha256=authorization_hash(sc),plan_hash=digest(tasks),base=c['source_sha256'],candidate_id=sc['run_id'],owner='local-development-controller',generation=1)
    write(sc['review_path'],review);sc['review_sha256']=file_hash(sc['review_path']);sp=write(tmp_path/'selection-config.json',sc)
    templates=write(tmp_path/'templates.json',adapter.templates)
    cycle=dict(schema='pi-local-cycle-v1',cycle_id='stopped',root=str(tmp_path/'cycle'),control_ledger_path=str(tmp_path/'control.sqlite'),selection_config_path=str(sp),selection_config_sha256=file_hash(sp),templates_path=str(templates),templates_sha256=file_hash(templates),deadline_seconds=1800,review_wait_seconds=60)
    request=write(tmp_path/'cycle.json',cycle);state=tmp_path/'manager.sqlite';billing=Path(c['ledger_path']);manager.init(state,billing)
    monkeypatch.setattr(manager,'inspect_cycle',lambda _:(cycle,sc,tasks,adapter.templates));manager.enqueue(state,billing,'stopped',request,file_hash(request))
    main=dict(operation_id='maintenance:stopped',cycle_id='stopped',mode='ACTUAL',source_sha256=c['source_sha256'],catalog_sha256=digest(tasks),deadline=time.monotonic()+1800,billing_ledger_path=str(billing));main['input_hash']=digest(main)
    data=dict(cycle_id='stopped',mode='ACTUAL',source_sha256=c['source_sha256'],catalog_sha256=digest(tasks),deadline=main['deadline'],previous=[],tasks=tasks)
    stage=dict(data,stage='analysis',input_hash=digest(data),operation_id=main['operation_id']+':analysis:'+digest(data))
    selection=Path(sc['root']);selection.mkdir(mode=0o700)
    ledger=Ledger(billing);ledger.intent('attempt-one','model-attempt',dict(scope_id='local-trial-1',reserved_microyuan=100));ledger.finish(Receipt('attempt-one','uncertain' if unknown_fee else 'done',dict(usage_known=not unknown_fee,charged_microyuan=100 if unknown_fee else 2,provider_request_id='synthetic')))
    after=ledger_snapshot(billing)
    result=dict(verified=False,execution_verified=False,contract_valid=False,closed_verified=False,run_id=sc['run_id'],authorization_sha256=authorization_hash(sc),failure_class='ValueError',cleanup=[dict(container_id='a'*64,removed=True,stopped=True,exit_code=0)],policy_restored=True,credential_unchanged=True,original_history_unchanged=True,new_attempts=1,new_unknown=1 if unknown_fee else 0,known_cost_microyuan=0 if unknown_fee else 2,model_posts=[dict(status=200,attempt_id='attempt-one')])
    write(selection/'result.json',result);write(selection/'ledger-before-private.json',before);write(selection/'ledger-after-private.json',after);write(selection/'manifest-private.json',dict(config=sc,context_hash=stage['input_hash'],provenance={}))
    write(selection/'owned-host-0.json',dict(operation_id='00000000-0000-4000-8000-000000000001'))
    prompt=selection_prompt(sc,tasks,stage['input_hash']);body=dict(model='synthetic',max_tokens=2048,messages=[dict(role='user',content=prompt)],system=wire_system(SYSTEM),stream=True);write(selection/'request-private.json',body)
    messages=[dict(role='system',content='',sections=dict(preamble=SYSTEM,cwd='<cwd>\n/work/candidate\n</cwd>'),timestamp=1),
        dict(role='user',content=[dict(type='text',text=prompt)],timestamp=1),
        dict(role='assistant',content=[dict(type='text',text='synthetic selection ignored')],stopReason='stop',timestamp=1)]
    session=json.dumps(dict(type='session',id='synthetic',cwd='/work/candidate'))+'\n'+''.join(json.dumps(dict(type='message',message=m))+'\n' for m in messages)
    rpc=[dict(direction='in',record=dict(type='prompt',id='prompt',message=prompt)),
        dict(direction='out',record=dict(type='response',id='prompt',command='prompt',success=True,data=dict(disposition='started')))]
    rpc.extend(dict(direction='out',record=dict(type='message_end',message=m)) for m in messages)
    rpc.append(dict(direction='out',record=dict(type='agent_settled',aborted=False)))
    for name in ('clear_queue','abort'):
        rpc.extend([dict(direction='in',record=dict(type=name,id=name)),dict(direction='out',record=dict(type='response',id=name,command=name,success=True,**(dict(data=dict(steering=[],followUp=[])) if name=='clear_queue' else {})))])
    evidence=dict(text='synthetic selection ignored',engine='pi',config_hash=digest(dict(authorization=authorization_hash(sc),context=stage['input_hash'])),plan_id=stage['input_hash'],experiment_id='local-trial-1',budget_scope_id='local-trial-1',protocol_failed=True,unexpected_tool=False,verified_tool_calls=[],pending_tool_calls=[],length_continuations=0,process_exited=True,clear_abort_acknowledged=True,returncode=0,session_sha256=sha256(session.encode()).hexdigest())
    write(selection/'worker-frame-private.json',dict(type='result',receipt=dict(operation_id='00000000-0000-4000-8000-000000000002',status='pending',schema_version=1,evidence=evidence),session=session,transcript=''.join(json.dumps(x)+'\n' for x in rpc),network_denied=True))
    analysis=dict(mode='ACTUAL',binding=stage['input_hash'],verified=False,result_path=str(selection/'result.json'),result=result,package_preflight=dict(templates={k:v['sha256'] for k,v in adapter.templates.items()}))
    control=Ledger(Path(cycle['control_ledger_path']));Path(cycle['control_ledger_path']).chmod(0o600);control.intent(main['operation_id'],'iteration_stage',main);control.intent(stage['operation_id'],'iteration_stage',stage);control.finish(Receipt(stage['operation_id'],'uncertain',analysis))
    outcome=asdict(Receipt(main['operation_id'],'uncertain',dict(mode='ACTUAL',released=False,next_action='reconcile',reason='stage_not_complete',stages=[dict(operation_id=stage['operation_id'],status='uncertain',evidence_sha256=digest(analysis))])))
    control.finish(Receipt(main['operation_id'],'uncertain',outcome['evidence']));root=Path(cycle['root']);root.mkdir(mode=0o700);(root/'prepared').mkdir(mode=0o700);write(root/'invocation.json',cycle);write(root/'result.json',outcome)
    _,_,rows,tasks_registered,_=manager._snapshot(state,billing,'ACTUAL');registered=tasks_registered[0];ml=manager.Ledger(state,existing=True);dc=manager._context(registered);ml.intent(dc['operation_id'],'iteration_stage',dc);ml.finish(Receipt(dc['operation_id'],'uncertain',dict(verified=False,binding=dc['input_hash'],mode='ACTUAL',cycle_result_sha256=digest(outcome),next_action='reconcile',released=False,elapsed_ms=10)))
    config=dict(schema='pi-selection-abandonment-v1',state_path=str(state),billing_path=str(billing),task_id='stopped',root=str(tmp_path/'audit'));p=write(tmp_path/'abandonment.json',config)
    monkeypatch.setattr(recovery,'verify_absence',lambda facts:None)
    return p,config,write


def test_readonly_check_and_audit_preserve_every_ledger(stopped,monkeypatch):
    p,c,_=stopped;before={str(f):f.read_bytes() for f in p.parent.rglob('*') if f.is_file()}
    monkeypatch.setattr(recovery,'verify_absence',lambda _:pytest.fail('readonly contacted Docker'))
    assert recovery.check(p)['ready_for_audit']
    assert before=={str(f):f.read_bytes() for f in p.parent.rglob('*') if f.is_file()}
    monkeypatch.setattr(recovery,'verify_absence',lambda _:None);r=recovery.audit(p);report=read_json(r['audit_path'])
    assert report['facts']['new_attempts']==1 and report['facts']['known_cost_microyuan']==2
    assert report['facts']['outcome']=='abandoned' and report['facts']['accepted_output'] is False
    assert 'synthetic' not in json.dumps(report['facts'].get('model_output'))
    for f,raw in before.items():assert Path(f).read_bytes()==raw


@pytest.mark.parametrize('bad',['fee_unknown','history','policy','development','extra_stage','frame_tool','cleanup','overlap','hardlink','simulated'])
def test_missing_or_changed_proof_never_creates_audit(stopped,bad):
    p,c,write=stopped;cycle=read_json(p.parent/'cycle.json');selection=p.parent/'selection'
    if bad=='fee_unknown':
        snap=read_json(selection/'ledger-after-private.json');next(r for r in snap['operations'] if r['operation_id']=='attempt-one')['status']='uncertain';write(selection/'ledger-after-private.json',snap)
    if bad=='history':write(selection/'ledger-before-private.json',{})
    if bad=='policy':write(p.parent/'policy.json',{})
    if bad=='development':(p.parent/'output').mkdir(mode=0o700)
    if bad=='extra_stage':Ledger(Path(cycle['control_ledger_path'])).intent('extra','iteration_stage',{})
    if bad=='frame_tool':
        f=read_json(selection/'worker-frame-private.json');f['receipt']['evidence']['pending_tool_calls']=['x'];write(selection/'worker-frame-private.json',f)
    if bad=='cleanup':
        r=read_json(selection/'result.json');r['cleanup'][0]['removed']=False;write(selection/'result.json',r)
    if bad=='overlap':c['root']=str(p.parent/'source/audit');Path(c['root']).parent.chmod(0o700);write(p,c)
    if bad=='hardlink':(selection/'result.alias').hardlink_to(selection/'result.json')
    if bad=='simulated':
        # No other mode may authorize an ACTUAL recovery.
        c['mode']='SIMULATED';write(p,c)
    with pytest.raises((ValueError,OSError,KeyError)):recovery.audit(p)
    assert not Path(c['root']).exists()


def approved(stopped):
    p,c,write=stopped;r=recovery.audit(p);report=read_json(r['audit_path']);f=report['facts']
    review=dict(schema='pi-selection-abandonment-review-v1',source='independent_review',verified=True,result='approved',reviewer='external-review',audit_sha256=r['audit_sha256'],task_binding=f['task_binding'],dispatch_sha256=f['dispatch_sha256'],billing_sha256=f['billing_sha256'],outcome='abandoned')
    rp=write(p.parent/'independent-abandonment.json',review)
    return p,c,rp


def test_append_only_abandonment_does_not_claim_success_or_replay(stopped):
    p,c,rp=approved(stopped);billing=ledger_snapshot(c['billing_path']);old=ledger_snapshot(c['state_path'])
    result=recovery.apply(p,rp);assert result['abandoned'] and not result['replayed']
    after=ledger_snapshot(c['state_path']);current={r['operation_id']:r for r in after['operations']}
    assert all(current[r['operation_id']]==r for r in old['operations']) and after['events'][:len(old['events'])]==old['events']
    assert ledger_snapshot(c['billing_path'])==billing
    s=manager.status(c['state_path'],c['billing_path']);assert s['tasks'][0]['state']=='uncertain' and s['tasks'][0]['resolution']=='abandoned'
    assert s['metrics']['outcomes']['done']==0 and s['metrics']['abandoned_tasks']==1 and s['metrics']['unresolved_dispatches']==0
    assert manager.run(c['state_path'],c['billing_path'],seconds=5)['dispatched']==0
    before=ledger_snapshot(c['state_path']);assert recovery.apply(p,rp)['replayed'];assert ledger_snapshot(c['state_path'])==before


@pytest.mark.parametrize('bad',['reviewer','audit_hash','expired','fee_changed','report_drift','source_drift','review_hardlink'])
def test_apply_rejects_stale_or_unreviewed_evidence(stopped,bad,monkeypatch):
    p,c,rp=approved(stopped);write=stopped[2]
    if bad=='reviewer':v=read_json(rp);v['reviewer']='model';write(rp,v)
    if bad=='audit_hash':v=read_json(rp);v['audit_sha256']='0'*64;write(rp,v)
    if bad=='expired':monkeypatch.setattr(recovery.time,'time',lambda:read_json(Path(c['root'])/'audit.json')['expires_at']+1)
    if bad=='fee_changed':Ledger(Path(c['billing_path'])).intent('another','test',{})
    if bad=='report_drift':v=read_json(Path(c['root'])/'audit.json');v['facts']['known_cost_microyuan']=0;write(Path(c['root'])/'audit.json',v)
    if bad=='source_drift':(p.parent/'source/src/a.py').write_text('changed=True\n')
    if bad=='review_hardlink':rp.with_suffix('.alias').hardlink_to(rp)
    before=ledger_snapshot(c['state_path'])
    with pytest.raises((ValueError,OSError)):recovery.apply(p,rp)
    assert ledger_snapshot(c['state_path'])==before
    assert manager.run(c['state_path'],c['billing_path'],seconds=5)['reason']=='reconciliation_required'


def test_pending_abandonment_survives_crash_without_unlock(stopped,monkeypatch):
    p,c,rp=approved(stopped);original=manager.Ledger.finish
    def crash(self,receipt):
        if receipt.operation_id.endswith(':reconciliation'):raise KeyboardInterrupt()
        return original(self,receipt)
    monkeypatch.setattr(manager.Ledger,'finish',crash)
    with pytest.raises(KeyboardInterrupt):recovery.apply(p,rp)
    assert manager.run(c['state_path'],c['billing_path'],seconds=5)['reason']=='reconciliation_incomplete'
    monkeypatch.setattr(manager.Ledger,'finish',original)
    assert recovery.apply(p,rp)['abandoned']
    assert manager.status(c['state_path'],c['billing_path'])['metrics']['unresolved_dispatches']==0


def test_resolution_proof_missing_or_replaced_freezes_recovery(stopped):
    p,c,rp=approved(stopped);recovery.apply(p,rp);rp.unlink()
    with pytest.raises((ValueError,OSError)):manager.status(c['state_path'],c['billing_path'])


def test_reconciliation_respects_live_manager_lock(stopped):
    import fcntl
    p,c,rp=approved(stopped);lock=Path(c['state_path']).with_suffix('.manager.lock')
    with lock.open('a+b') as held:
        lock.chmod(0o600);fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(ValueError,match='busy'):recovery.apply(p,rp)


@pytest.mark.parametrize('bad',['clear','daemon','exists','inspect_error','operation'])
def test_current_daemon_and_exact_resources_must_be_absent(stopped,monkeypatch,bad):
    p,c,_=stopped;value=recovery.facts(p)
    def output(code=0,stdout='',stderr=''):return type('Output',(),dict(returncode=code,stdout=stdout,stderr=stderr))()
    class Host:
        def __init__(self,**kwargs):pass
        def _daemon(self):
            if bad=='daemon':raise RuntimeError('wrong daemon')
        def _call(self,*args,**kwargs):
            if args[0]=='inspect':return output(0) if bad=='exists' else output(1,stderr='permission denied') if bad=='inspect_error' else output(1,stderr='No such object')
            return output(stdout='unreconciled' if bad=='operation' else '')
    monkeypatch.setattr(recovery,'ProbeHost',Host)
    if bad=='clear':REAL_VERIFY_ABSENCE(value)
    else:
        with pytest.raises((ValueError,RuntimeError)):REAL_VERIFY_ABSENCE(value)


def test_completed_abandonment_is_idempotent_after_new_billing_activity(stopped):
    p,c,rp=approved(stopped);recovery.apply(p,rp);Ledger(Path(c['billing_path'])).intent('later','test',{})
    assert recovery.apply(p,rp)['replayed']
    assert manager.status(c['state_path'],c['billing_path'])['metrics']['abandoned_tasks']==1


def test_prepared_resolution_can_finalize_after_expiry_only_with_identical_fresh_facts(stopped,monkeypatch):
    p,c,rp=approved(stopped);original=manager.Ledger.finish
    def crash(self,receipt):
        if receipt.operation_id.endswith(':reconciliation'):raise KeyboardInterrupt()
        return original(self,receipt)
    monkeypatch.setattr(manager.Ledger,'finish',crash)
    with pytest.raises(KeyboardInterrupt):recovery.apply(p,rp)
    monkeypatch.setattr(manager.Ledger,'finish',original)
    expires=read_json(Path(c['root'])/'audit.json')['expires_at'];monkeypatch.setattr(recovery.time,'time',lambda:expires+1)
    assert recovery.apply(p,rp)['abandoned']


def test_same_queue_requires_resolution_then_accepts_only_new_native_identity(stopped,monkeypatch):
    from ops.pi.tests.test_manager import request_for
    p,c,write=stopped;state=Path(c['state_path']);billing=Path(c['billing_path'])
    fresh=request_for((state,billing,p.parent/'cycle.json',{}),'fresh')
    def inspect(target):
        nc=read_json(target);sc=read_json(nc['selection_config_path']);tmap=read_json(nc['templates_path'])
        return nc,sc,read_json(sc['catalog_path']),tmap
    monkeypatch.setattr(manager,'inspect_cycle',inspect)
    with pytest.raises(ValueError,match='unresolved'):manager.enqueue(state,billing,'fresh',fresh,file_hash(fresh))
    p,c,rp=approved(stopped);recovery.apply(p,rp)
    assert manager.enqueue(state,billing,'fresh',fresh,file_hash(fresh))['registered']
    result=manager.status(state,billing);assert result['metrics']['registered_tasks']==2
    assert result['metrics']['abandoned_tasks']==1 and result['metrics']['outcomes']['done']==0
    assert {t['task_id']:t['state'] for t in result['tasks']}==dict(stopped='uncertain',fresh='queued')


@pytest.mark.parametrize('where,kind',[('session','toolResult'),('session','toolCall'),('rpc','toolResult'),('rpc','toolCall')])
def test_raw_session_or_rpc_tool_evidence_cannot_be_abandoned(stopped,where,kind):
    p,c,write=stopped;target=p.parent/'selection/worker-frame-private.json';f=read_json(target)
    message=dict(role='toolResult',toolName='bash',content=[dict(type='text',text='unexpected external action')]) if kind=='toolResult' else dict(role='assistant',content=[dict(type='toolCall',id='unexpected',name='bash',arguments={})])
    if where=='session':
        f['session']+=json.dumps(dict(type='message',message=message))+'\n';f['receipt']['evidence']['session_sha256']=sha256(f['session'].encode()).hexdigest()
    else:f['transcript']+=json.dumps(dict(direction='out',record=dict(type='message_end',message=message)))+'\n'
    write(target,f)
    with pytest.raises(ValueError):recovery.audit(p)


@pytest.mark.parametrize('stopped',['unknown'],indirect=True)
def test_self_consistent_unknown_charge_snapshot_is_never_abandoned(stopped):
    p,c,_=stopped
    before=ledger_snapshot(c['billing_path'])
    with pytest.raises(ValueError,match='settled selection'):recovery.audit(p)
    assert ledger_snapshot(c['billing_path'])==before and not Path(c['root']).exists()


@pytest.mark.parametrize('where',['session_metadata','rpc_stream_event'])
def test_tool_evidence_outside_message_end_is_also_rejected(stopped,where):
    p,c,write=stopped;target=p.parent/'selection/worker-frame-private.json';f=read_json(target)
    if where=='session_metadata':
        f['session']+=json.dumps(dict(type='tool_result',name='bash'))+'\n';f['receipt']['evidence']['session_sha256']=sha256(f['session'].encode()).hexdigest()
    else:f['transcript']+=json.dumps(dict(direction='out',record=dict(type='message_update',assistantMessageEvent=dict(type='toolcall_start',name='bash'))))+'\n'
    write(target,f)
    with pytest.raises(ValueError):recovery.audit(p)
