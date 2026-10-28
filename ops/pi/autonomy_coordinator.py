"""Finite root coordinator: authenticated evidence to original manager, never release."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from threading import Event
import fcntl,os,re,tempfile
from .audit import _path,_plain,digest,encoded,hash_value,require,utc
from .development_inputs import file_hash,ledger_snapshot,read_json
from .review_lease import _read,_directory,_sync
from . import autonomy_profile as profile
from .autonomy_dispatch import run as dispatch
from .autonomy_recovery import withdraw
from .diagnosis_launcher import _unknown
from .investigation_inputs import compile_context
from .live_diagnosis import inspect_observation
from .provider_config import load_credentials
from .policy import load_policy
from .manager_handoff import BASE

RESULT=set('schema mode status profile_sha256 research_fingerprint model_requests before_fee_sha256 after_fee_sha256 phases pending_file_hashes manifest_sha256 handoff_request_sha256 cycle_sha256'.split())


def _atomic(p,path,raw):
    fd,name=tempfile.mkstemp(prefix='.autonomy-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            out.write(raw);out.flush();os.fchmod(out.fileno(),0o640 if p['mode']=='ACTUAL' else 0o600)
            if p['mode']=='ACTUAL':os.fchown(out.fileno(),0,profile._owner(p)[1])
            os.fsync(out.fileno())
        os.replace(name,path);_sync(path.parent)
    finally:
        if os.path.exists(name):os.unlink(name)


def _active_entries(p,entries,clock=None):
    from .manager_review_worker import inspect_terminal,_completed
    require(isinstance(entries,list) and len(entries)<=16,'finite worker queue required');active=[];retired=[];seen=set()
    for entry in entries:
        require(isinstance(entry,dict) and set(entry)=={'request_path','request_sha256'} and hash_value(entry['request_sha256']) and entry['request_path'] not in seen,'closed unique worker entry required');seen.add(entry['request_path'])
        require(read_json(entry['request_path'])['mode']==p['mode'],'mixed worker queue modes forbidden')
        result=inspect_terminal(entry['request_path'],entry['request_sha256'],clock=clock)
        if result is not None:
            require(result['status'] in ('published','no_action') and result.get('cached') is True,'uncertain worker queue freezes admission');retired.append(dict(entry,status=result['status']))
        else:
            _completed(entry['request_path'],entry['request_sha256'],clock);active.append(entry)
    return active,retired


def _register(p,claim,stage,*,clock=None):
    directory=_path(p['permit_root']).parent;registry=directory/'review-worker-registry.json';envpath=directory/'review-worker.env'
    old=dict(schema='pi-review-worker-registry-v1',mode=p['mode'],entries=[])
    if registry.exists():
        _plain(registry);require(registry.stat().st_size<=65536);old=read_json(registry)
        if p['mode']=='ACTUAL':require(registry.stat().st_uid==0 and registry.stat().st_mode&0o777==0o640,'root worker registry required')
    require(isinstance(old,dict) and set(old)=={'schema','mode','entries'} and old['schema']=='pi-review-worker-registry-v1' and old['mode']==p['mode'] and isinstance(old['entries'],list) and len(old['entries'])<=16,'finite original worker registry required')
    active,retired=_active_entries(p,old['entries'],clock);require(len(active)<16,'active worker queue full')
    entry=dict(request_path=stage['config_path'],request_sha256=stage['config_sha256']);require(all(e.get('request_path')!=entry['request_path'] for e in old['entries']),'worker admission already registered; no replay')
    profile.write(p,claim/'registry-before-private.json',old)
    if envpath.exists():
        _plain(envpath);require(envpath.stat().st_size<=65536)
        if p['mode']=='ACTUAL':require(envpath.stat().st_uid==0 and envpath.stat().st_mode&0o777==0o640,'root worker environment required')
        text=envpath.read_text();allowed={'PI_OBSERVER_RUNTIME_SHA256','PI_REVIEW_WORKER_ENTRYPOINT','PI_REVIEW_WORKER_REGISTRY_SHA256'}
        require(all('=' in row and row.split('=',1)[0] in allowed for row in text.splitlines() if row),'fixed worker environment required');profile.write(p,claim/'environment-before-private.json',dict(text=text))
    profile.write(p,claim/'retired-worker-entries.json',retired)
    new=dict(old,entries=active+[entry]);_atomic(p,registry,encoded(new)+b'\n');pin=file_hash(registry)
    require(re.fullmatch('/[A-Za-z0-9_./-]+',p['worker_entry_path']) is not None,'fixed environment entry path required')
    env=('PI_OBSERVER_RUNTIME_SHA256='+p['controller_sha256']+'\nPI_REVIEW_WORKER_ENTRYPOINT='+p['worker_entry_path']+'\nPI_REVIEW_WORKER_REGISTRY_SHA256='+pin+'\n').encode();_atomic(p,envpath,env)
    require(file_hash(registry)==pin and envpath.read_bytes()==env,'worker registration uncertain')
    profile.write(p,claim/'worker-registration.json',dict(registry_sha256=pin,environment_sha256=file_hash(envpath),handoff_request_sha256=stage['config_sha256']))


def _window(p,now):
    local=now.astimezone(timezone(timedelta(hours=8)));start=local.replace(hour=2,minute=0,second=0,microsecond=0);cutoff=local.replace(hour=5,minute=30,second=0,microsecond=0)
    prep=p['limits']['investigation_seconds']+p['limits']['review_seconds']+p['limits']['checker_seconds']+270
    return start<=local and local+timedelta(seconds=prep)<cutoff


def _history(root):
    children=list(root.iterdir());require(len(children)<=4096,'bounded coordinator history required');records={}
    for child in children:
        require(hash_value(child.name),'unexpected coordinator state');_directory(child)
        if not (child/'receipt.json').exists():return records,False
        value=_read(child/'receipt.json')[0];intent=_read(child/'intent.json')[0]
        require(isinstance(value,dict) and set(value)==RESULT and value['schema']=='pi-autonomy-coordinator-result-v1' and value['research_fingerprint']==child.name and value['profile_sha256']==intent['profile_sha256'],'coordinator history drift')
        for component,pin in value['phases'].items():require(file_hash(child/('phase-'+component)/'receipt.json')==pin,'phase history drift')
        records[child.name]=value
        if value['status'] in ('uncertain','blocked'):return records,False
    return records,True


def _audit(p,pin,claim,state,phases,runner,cancel,now):
    event_state='planned' if state=='admitted' else 'no_change' if state in ('no_task','not_reproduced') else 'blocked' if state in ('review_rejected','blocked') else 'uncertain' if state=='uncertain' else 'failed'
    run='auto-'+claim.name[:32];domain='real_provider_fixed_input' if p['mode']=='ACTUAL' else 'synthetic'
    event=dict(kind='plan',status=event_state,run_id=run,occurred_at=now.isoformat(),summary='Finite source investigation and independent review; candidate/product acceptance remains separate.',details=dict(reference='autonomy.coordinator.v1',decision=state,operation_id=claim.name,next_action='original_manager_selection' if state=='admitted' else 'no_development_authority',result_summary='Stages: '+','.join(phases)),version=dict(controller_sha256=p['controller_sha256'],policy_sha256=pin,sdk_version='1.1.0'),changes=[],evidence=[dict(kind=kind,sha256=sha,verified=True,evidence_domain=domain) for kind,sha in [('root_source_profile',pin)]+[('phase_'+name,sha) for name,sha in phases.items()]],followups=[],mode=p['mode'],evidence_domain=domain)
    version=dict(event,kind='version',status='no_change',summary='Controller/source-profile context; no product release.',details=dict(reference='autonomy.controller.v1',decision='recorded',next_action='none'))
    cp=claim/'coordinator-audit.json';profile.write(p,cp,dict(schema='pi-autonomy-audit-v1',mode=p['mode'],audit_path=p['audit_path'],export_root=p['export_root'],events=[dict(record_key=run+':coordinator',event=event),dict(record_key=run+':controller-context',event=version)]))
    value=dispatch(p,'coordinator_audit',dict(config_path=str(cp),config_sha256=file_hash(cp)),claim,runner=runner,cancel=Event())
    phases['coordinator_audit']=value['receipt_sha256'];require(value['status']=='done','coordinator audit unavailable')


def run(profile_path,pin,*,runner=None,clock=None,cancel=None):
    cancel=cancel if cancel is not None else Event();pp=_path(profile_path);_plain(pp);require(pp.stat().st_size<=65536 and file_hash(pp)==pin,'coordinator profile pin drift');raw=read_json(pp)
    require(isinstance(raw,dict) and set(raw)==profile.FIELDS and raw['mode'] in ('ACTUAL','SIMULATED'),'closed coordinator profile required')
    mode=raw['mode'];out=dict(schema='pi-autonomy-coordinator-tick-v1',mode=mode,status='blocked',model_requests=0)
    if mode=='ACTUAL':require(runner is None and clock is None and os.geteuid()==0 and pp.stat().st_uid==0 and pp.stat().st_mode&0o777==0o640 and pp.parent.stat().st_mode&0o777==0o750,'ACTUAL root finite coordinator required')
    else:require(callable(runner),'explicit simulated phases required')
    if cancel.is_set():return dict(out,status='cancelled')
    lp=BASE/'control/maintenance.lock' if mode=='ACTUAL' else _path(raw['lock_path']);_plain(lp)
    with lp.open('rb') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return dict(out,status='lock_busy')
        p,now,before=profile.load(pp,pin,clock=clock)
        from .manager import status as manager_status
        if manager_status(p['manager_state'],p['host']['ledger_path'],mode=mode)['metrics']['unresolved_dispatches']:return dict(out,status='uncertain')
        active_entries=[];registry=_path(p['permit_root']).parent/'review-worker-registry.json'
        if registry.exists():
            _plain(registry);require(registry.stat().st_size<=65536,'bounded existing review queue required');queue=read_json(registry)
            require(set(queue)=={'schema','mode','entries'} and queue['schema']=='pi-review-worker-registry-v1' and queue['mode']==mode,'existing review queue drift')
            if mode=='ACTUAL':require(registry.stat().st_uid==0 and registry.stat().st_mode&0o777==0o640,'root existing review queue required')
            active_entries,_=_active_entries(p,queue['entries'],clock)
        if mode=='ACTUAL' and not _window(p,now):return dict(out,status='outside_window')
        records,closed=_history(_directory(p['root']))
        if not closed:return dict(out,status='uncertain')
        from .live_observer import _load
        _,_,_,base,*_=_load(p['observer']['observer_config_path']);candidates=[d/'receipt.json' for d in base.iterdir() if d.is_dir() and (d/'receipt.json').exists()];require(len(candidates)<=4096,'bounded observations required')
        if not candidates:return dict(out,status='no_evidence')
        receipt=max(candidates,key=lambda path:path.parent.name);o=p['observer'];s=p['source'];h=p['host']
        evidence=inspect_observation(o['observer_config_path'],o['observer_config_sha256'],receipt,expected_controller_sha256=o['observer_controller_sha256'],clock=clock)
        credentials=load_credentials(h['credential_path'],load_policy(_path(h['policy_path'])));context=compile_context(s['source_path'],s['source_sha256'],s['files'],evidence,reference_commit=s['reference_commit'],pending=read_json(s['pending_path']),credential_literal=credentials['PLATFORM_MODEL_API_KEY']);fp=context['research_fingerprint']
        if fp in records:return dict(out,status='cached',previous_status=records[fp]['status'])
        if active_entries:return dict(out,status='awaiting_manager_cycle')
        current_files={v['path']:v['sha256'] for v in context['files']}
        if any(value['status']=='admitted' and any(current_files.get(path)==sha for path,sha in value['pending_file_hashes'].items()) for value in records.values()):return dict(out,status='awaiting_candidate_adoption')
        require(not cancel.is_set(),'coordinator cancelled before claim');research=profile.research(pp,pin,receipt,clock=clock);claim=Path(research['claim_path']);profile.write(p,claim/'ledger-before-private.json',before)
        phases={};handoff=None;admission=None;pending={};state='uncertain';failure=None
        def execute(component,stage):
            require(not cancel.is_set() and file_hash(pp)==pin,'coordinator revoked before phase')
            value=dispatch(p,component,stage,claim,runner=runner,cancel=cancel);phases[component]=value['receipt_sha256']
            require(value['status']=='done','phase did not complete');return value['outcome']
        try:
            value=execute('investigation',research)
            from .investigation_evidence import inspect
            proposal=inspect(research['config_path'],research['config_sha256'],clock=clock)['proposal']
            if proposal['decision']=='no_task':state='no_task'
            else:
                stage=profile.reproducer(pp,pin,research['config_path'],research['config_sha256'],clock=clock);value=execute('reproducer',stage)
                if not value['eligible_for_review']:state='not_reproduced'
                else:
                    stage=profile.review(pp,pin,claim,clock=clock);value=execute('sdk_review',stage)
                    if value['report']['recommendation']!='approve':state='review_rejected'
                    else:
                        handoff=profile.handoff(pp,pin,claim,clock=clock);value=execute('manager_handoff',handoff)
                        from .manager_review_worker import _completed
                        _,admission,*_=_completed(handoff['config_path'],handoff['config_sha256'],clock)
                        tc=read_json(admission['template_path']);plan=read_json(tc['plan_path']);pending={path:file_hash(Path(s['source_path'])/path) for path in plan['files']}
                        require(not cancel.is_set() and file_hash(pp)==pin,'admission cancelled/revoked');_register(p,claim,handoff,clock=clock);state='admitted'
        except Exception as error:
            failure=type(error).__name__;state='uncertain'
            if phases:
                last=_read(claim/('phase-'+next(reversed(phases)))/'receipt.json')[0]
                if last['status'] in ('failed','blocked'):state=last['status']
            if handoff is not None:
                try:withdraw(p,claim,handoff,lock)
                except Exception as recovery_error:profile.write(p,claim/'withdrawal-failure.json',dict(failure_class=type(recovery_error).__name__))
            profile.write(p,claim/'failure.json',dict(failure_class=failure))
        try:_audit(p,pin,claim,state,phases,runner,cancel,now)
        except Exception as error:
            state='uncertain';profile.write(p,claim/'audit-failure.json',dict(failure_class=type(error).__name__))
            if handoff is not None:
                try:withdraw(p,claim,handoff,lock)
                except Exception:pass
        after=ledger_snapshot(h['ledger_path']);old={r['operation_id'] for r in before['operations']};count=sum(r['kind']=='model-attempt' and r['operation_id'] not in old for r in after['operations'])
        if _unknown(after)!=set(p['legacy_unknown_ids']):state='blocked'
        result=dict(schema='pi-autonomy-coordinator-result-v1',mode=mode,status=state,profile_sha256=pin,research_fingerprint=fp,model_requests=count,before_fee_sha256=before['sha256'],after_fee_sha256=after['sha256'],phases=phases,pending_file_hashes=pending if state=='admitted' else {},manifest_sha256=admission['manifest_sha256'] if state=='admitted' else None,handoff_request_sha256=handoff['config_sha256'] if state=='admitted' else None,cycle_sha256=admission['cycle_sha256'] if state=='admitted' else None)
        profile.write(p,claim/'receipt.json',result);return result


def serve(profile_path,pin):
    import signal
    cancel=Event();previous={}
    def stop(*_):cancel.set()
    try:
        for signum in (signal.SIGINT,signal.SIGTERM):previous[signum]=signal.signal(signum,stop)
        return run(profile_path,pin,cancel=cancel)
    finally:
        for signum,handler in previous.items():signal.signal(signum,handler)
