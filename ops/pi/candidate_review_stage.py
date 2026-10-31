"""Root mechanics from completed manager evidence to one finite review request.

No model is run here. A generated recommendation permit is not code adoption,
FileReview, product deployment or authority to replay a paid candidate claim.
"""
from datetime import timedelta
from pathlib import Path
from threading import Event
import fcntl,os
from .audit import _path,_plain,digest,hash_value,require,utc,SHANGHAI
from .development_inputs import file_hash,read_json,ledger_snapshot
from .review_lease import _read,_directory,_sync
from .autonomy_coordinator import RESULT
from .manager_host import PHASES
from .manager_review_worker import _completed
from .task_package import _publish_new
from .diagnosis_launcher import _unknown
from . import autonomy_profile as profile,manager_completion

RECEIPT=set('schema status model_requests profile_sha256 task_id candidate_sha256 manager_binding config_path config_sha256 artifact_pins'.split())


def _admitted(p,claim):
    require(claim.parent==_path(p['root']) and hash_value(claim.name),'original admitted claim required');fp=claim.name
    require(not (claim/'withdrawal').exists(),'withdrawn admission cannot request candidate review')
    intent=_read(claim/'intent.json')[0];r=_read(claim/'receipt.json')[0]
    require(intent['schema']=='pi-autonomy-intent-v1' and intent['research_fingerprint']==fp and intent['source_sha256']==p['source']['source_sha256']
        and isinstance(r,dict) and set(r)==RESULT and r['schema']=='pi-autonomy-coordinator-result-v1' and r['status']=='admitted' and r['mode']==p['mode']
        and r['research_fingerprint']==fp and r['profile_sha256']==intent['profile_sha256'] and set(r['phases'])==PHASES,'completed source admission required')
    outcomes={}
    for component,pin in r['phases'].items():
        root=claim/('phase-'+component);phase,actual=_read(root/'receipt.json');value,vpin=_read(root/'result-private.json')
        require(actual==pin and phase['schema']=='pi-autonomy-phase-receipt-v1' and phase['mode']==p['mode'] and phase['component']==component and phase['status']=='done'
            and phase['result_sha256']==vpin and value['schema']=='pi-autonomy-worker-result-v1' and value['component']==component and value['mode']==p['mode'] and value['status']=='done','original completed admission phase drift');outcomes[component]=value['outcome']
    cp=_path(p['handoff_root'])/('request-'+fp+'.json');require(file_hash(cp)==r['handoff_request_sha256'],'original handoff request drift')
    q,handoff,issuer,*_=_completed(cp,r['handoff_request_sha256'],None,historical=True)
    require(q['mode']==p['mode'] and q['task_id']=='auto-'+fp[:32] and _path(q['manager_state'])==_path(p['manager_state']) and _path(q['inbox'])==_path(p['inbox'])
        and handoff['cycle_sha256']==r['cycle_sha256'] and handoff['manifest_sha256']==r['manifest_sha256'] and digest(handoff)==digest(outcomes['manager_handoff'])
        and issuer['source_sha256']==p['source']['source_sha256'],'original handoff/source identity drift')
    return dict(task_id=q['task_id'],cycle_sha256=r['cycle_sha256'])


def _lock(p,lock):
    lp=_path(p['lock_path']);_plain(lp);info=os.fstat(lock.fileno());current=lp.stat()
    require(_path(lock.name)==lp and (info.st_dev,info.st_ino)==(current.st_dev,current.st_ino),'canonical maintenance lock descriptor required');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)


def _scope(p,proof):
    development=proof['development'];c=development['config'];fee=development['fee'];plan=development['dossier']['model_view']['plan']
    require(proof['authority']=='completed_manager_development' and proof['executable_approval'] is False and development['authority']=='completed_development_only' and development['mode']==p['mode'],'independently authenticated completed manager/development required')
    require(c['source_sha256']==p['source']['source_sha256'] and set(plan['files'])<=set(p['source']['files']),'candidate outside current root source scope')
    require(all(c[k]==p['host'][k] for k in ('runtime_sha256','ledger_path','policy_path','policy_sha256','credential_path','credential_sha256','docker','endpoint','daemon_id','image_id')),'completed host differs from current root profile')
    require(all(c[k]<=p['limits'][target] for k,target in (('max_requests','max_requests'),('max_tools','max_tools'),('deadline_seconds','development_seconds'))),'completed scope exceeds root phase limits')
    require(fee['limits']['budget_microyuan']==p['budget_microyuan'] and _unknown(fee)==set(p['legacy_unknown_ids']),'original candidate financial scope drift')


def _copy_profile(p,source,target,pin):
    raw=source.read_bytes();require(file_hash(source)==pin,'parent profile revoked before snapshot');require(not _publish_new(target,raw),'profile snapshot staging uncertain')
    if p['mode']=='ACTUAL':
        fd=os.open(target,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fchown(fd,*profile._owner(p));os.fchmod(fd,0o600);os.fsync(fd)
        finally:os.close(fd)
        _sync(target.parent)
    require(file_hash(target)==pin,'parent profile snapshot drift')


def create(profile_path,pin,claim_path,lock,*,clock=None,cancel=None):
    cancel=cancel if cancel is not None else Event();require(not cancel.is_set(),'candidate preparation cancelled')
    pp=_path(profile_path);p,now,fee=profile.load(pp,pin,clock=clock);_lock(p,lock);claim=_directory(claim_path)
    admitted=_admitted(p,claim);task=admitted['task_id'];ready=manager_completion.request(p['manager_state'],p['host']['ledger_path'],task,mode=p['mode'])
    if ready['status']!='candidate_ready':return dict(status=ready['status'],model_requests=0)
    require('cycle_sha256' not in admitted or ready['manager_binding']['cycle_sha256']==admitted['cycle_sha256'],'completed manager is another admitted cycle')
    preparation=claim/'completion-prepare';receipt=preparation/'receipt.json'
    if preparation.exists():
        if not receipt.exists():return dict(status='uncertain',model_requests=0,cached=True)
        old=_read(receipt)[0];require(isinstance(old,dict) and set(old)==RECEIPT and old['schema']=='pi-candidate-review-stage-v1' and old['status']=='prepared'
            and old['task_id']==task and old['manager_binding']==ready['manager_binding'] and file_hash(old['config_path'])==old['config_sha256']
            and all(file_hash(path)==sha for path,sha in old['artifact_pins'].items()),'candidate preparation history drift')
        return dict(old,cached=True)
    preparation.mkdir(mode=0o700)
    if p['mode']=='ACTUAL':os.chown(preparation,*profile._owner(p))
    _sync(claim);profile.write(p,preparation/'intent.json',dict(schema='pi-candidate-preparation-intent-v1',profile_sha256=pin,task_id=task,manager_binding=ready['manager_binding']))
    _copy_profile(p,pp,preparation/'profile-private.json',pin)
    request=claim/'candidate-review-request.json';profile.write(p,request,ready['request'])
    proof=manager_completion.inspect(p['manager_state'],p['host']['ledger_path'],task,request,file_hash(request),mode=p['mode']);_scope(p,proof)
    require(not cancel.is_set() and file_hash(pp)==pin,'parent source profile revoked before candidate permit')
    development=proof['development'];candidate=development['candidate_sha256'];dossier=claim/'candidate-dossier.json';profile.write(p,dossier,development['dossier'])
    parent=_path(p['review_root'])/'candidates'
    if not parent.exists():
        parent.mkdir(mode=0o700)
        if p['mode']=='ACTUAL':os.chown(parent,*profile._owner(p))
        _sync(parent.parent)
    _directory(parent);root=parent/('candidate-'+candidate);require(not root.exists(),'permanent candidate claim exists; no replay')
    c=dict(p['host'],schema='pi-candidate-review-v1',role='candidate_review',mode=p['mode'],run_id='candidate-review-'+candidate[:32],root=str(root),ledger_sha256=fee['sha256'],deadline_seconds=p['limits']['review_seconds'],request_path=str(request),request_sha256=file_hash(request),dossier_path=str(dossier),dossier_sha256=file_hash(dossier),permit_path=str(_path(p['permit_root'])/('candidate-review-'+claim.name+'.json')),permit_sha256='0'*64,audit_path=p['audit_path'],export_root=p['export_root'])
    expiry=min(utc(p['expires_at']),now+timedelta(seconds=c['deadline_seconds']+45))
    permit={k:c[k] for k in ('mode','role','run_id','request_sha256','dossier_sha256','runtime_sha256','policy_sha256','credential_sha256','ledger_path','deadline_seconds')}
    permit.update(schema='pi-candidate-review-permit-v1',authority='independent_candidate_recommendation_only',candidate_sha256=candidate,budget_scope='local-trial-1',budget_microyuan=p['budget_microyuan'],max_model_requests=1,claim_root=str(parent),profile_path=str(pp),profile_sha256=pin,legacy_unknown_ids=p['legacy_unknown_ids'],issued_at=now.isoformat(),expires_at=expiry.isoformat())
    require(not cancel.is_set() and file_hash(pp)==pin and ledger_snapshot(p['host']['ledger_path'])==fee,'candidate preparation revoked or fee drift')
    profile.write(p,Path(c['permit_path']),permit,permit=True);c['permit_sha256']=file_hash(c['permit_path']);cp=claim/'candidate-review-config.json';profile.write(p,cp,c)
    require(not cancel.is_set() and file_hash(pp)==pin,'candidate permit revoked before prepared receipt')
    pins={str(path):file_hash(path) for path in (request,dossier,Path(c['permit_path']),cp,preparation/'profile-private.json')}
    result=dict(schema='pi-candidate-review-stage-v1',status='prepared',model_requests=0,profile_sha256=pin,task_id=task,candidate_sha256=candidate,manager_binding=proof['manager_binding'],config_path=str(cp),config_sha256=file_hash(cp),artifact_pins=pins)
    profile.write(p,receipt,result);return dict(result,cached=False)



def _completion_audit(p,pin,claim,stage,state,now,pins,runner,registration):
    """Project parent linkage and an honest reservation, never a charge or release."""
    from .autonomy_dispatch import run as dispatch
    domain='real_provider_fixed_input' if p['mode']=='ACTUAL' else 'synthetic'
    due=now.astimezone(SHANGHAI)+timedelta(days=1);due=due.replace(hour=3,minute=0,second=0,microsecond=0)
    version=dict(controller_sha256=p['controller_sha256'],policy_sha256=pin,candidate_sha256=stage['candidate_sha256'],sdk_version='1.1.0')
    if p['source'].get('reference_commit'):version['source_commit']=p['source']['reference_commit']
    evidence=[dict(kind=kind,sha256=sha,verified=True,evidence_domain=domain) for kind,sha in (
        ('original_manager_binding',digest(stage['manager_binding'])),('candidate_review_phase',file_hash(claim/'phase-candidate_review/receipt.json')))]
    common=dict(run_id=stage['task_id'],occurred_at=now.isoformat(),version=version,changes=[],evidence=evidence,followups=[],mode=p['mode'],evidence_domain=domain)
    review=dict(common,kind='review',status={'review_approved':'candidate_ready','review_rejected':'failed','needs_evidence':'insufficient_evidence','review_failed':'failed'}.get(state,'uncertain'),summary='Independent candidate recommendation linked to original manager development; product adoption requires separate authority.',details=dict(reference='candidate.host_completion.v1',decision=state,operation_id=claim.name,next_action='fixed_followup_registration' if state=='review_approved' else 'retain_evidence_no_product_adoption'))
    if (claim/'candidate-review-host-failure.json').exists():review['details']['reason']='host_candidate_evidence_unverified'
    plan=dict(common,kind='followup',status='blocked',summary='Next-day candidate regression reserved; no executable registry entry has been published.',details=dict(reference='candidate.nextday_reservation.v1',reason='fixed_registry_not_published',next_action='root_fixed_registry_publication'),followups=[dict(test_id='fixed-'+stage['candidate_sha256'][:32],scheduled_for=utc(due).isoformat(),target_run_id=stage['task_id'],target_version_sha256=stage['candidate_sha256'],criterion='Frozen private candidate regression only; no claim of online product improvement.',kind='regression',status='blocked')])
    if registration['registered']:
        plan.update(status='planned',summary='Root fixed registry published for next-day candidate regression; execution remains separate.')
        plan['details'].update(reason='fixed_registry_published',next_action='wait_for_actual_due_result')
        entry=registration['entry'];plan['followups'][0].update(status='planned',scheduled_for=entry['scheduled_for'])
        plan['evidence']=evidence+[dict(kind='fixed_registry_publication',sha256=file_hash(claim/'followup-registration/receipt.json'),verified=True,evidence_domain=domain)]
    else:plan['details']['reason']=registration['reason']
    cp=claim/'candidate-review-audit.json';profile.write(p,cp,dict(schema='pi-autonomy-audit-v1',mode=p['mode'],audit_path=p['audit_path'],export_root=p['export_root'],events=[dict(record_key='candidate-host-'+claim.name,event=review),dict(record_key='candidate-nextday-'+claim.name,event=plan)]))
    value=dispatch(p,'candidate_audit',dict(config_path=str(cp),config_sha256=file_hash(cp)),claim,cancel=Event(),runner=runner)
    pins[str(cp)]=file_hash(cp);pins[value['receipt_path']]=value['receipt_sha256']
    result=claim/'phase-candidate_audit/result-private.json'
    if result.exists():pins[str(result)]=file_hash(result)
    return value['status']=='done'


def review_once(profile_path,pin,claim_path,lock,*,runner=None,clock=None,cancel=None):
    """Execute one fixed generated review; immutable outcomes never pay again."""
    cancel=cancel if cancel is not None else Event();require(not cancel.is_set(),'candidate review cancelled before completion claim')
    pp=_path(profile_path);p,now,before=profile.load(pp,pin,clock=clock);_lock(p,lock);claim=_directory(claim_path)
    if p['mode']=='ACTUAL':
        require(runner is None and clock is None,'ACTUAL candidate phase forbids injected execution')
        from .maintenance_window import completion_budget
        try:completion_budget(now,p['limits']['review_seconds'])
        except ValueError:return dict(status='outside_window',model_requests=0,executable_approval=False)
    else:require(callable(runner),'explicit isolated simulated candidate kernel required')
    target=claim/'candidate-review-outcome.json'
    if target.exists():
        old=_read(target)[0];require(old['schema']=='pi-candidate-review-outcome-v1' and old['mode']==p['mode'] and old['executable_approval'] is False
            and old['status'] in ('review_approved','review_rejected','needs_evidence','review_failed','uncertain','cancelled') and old['research_fingerprint']==claim.name
            and all(file_hash(path)==sha for path,sha in old['artifact_pins'].items()),'candidate outcome history drift')
        return dict(old,model_requests=0,cached=True)
    stage=create(pp,pin,claim,lock,clock=clock,cancel=cancel)
    if stage['status']!='prepared':return dict(stage,executable_approval=False)
    phase=claim/'phase-candidate_review'
    if phase.exists():return dict(status='uncertain',model_requests=0,executable_approval=False,cached=True)
    require(not cancel.is_set() and file_hash(pp)==pin,'candidate parent revoked before fixed dispatch')
    from .autonomy_dispatch import run as dispatch
    dp=claim/'development-audit.json'
    if (claim/'phase-development_audit').exists():return dict(status='uncertain',model_requests=0,executable_approval=False,cached=True)
    profile.write(p,dp,dict(schema='pi-development-audit-v1',mode=p['mode'],manager_state=p['manager_state'],ledger_path=p['host']['ledger_path'],task_id=stage['task_id'],request_path=str(claim/'candidate-review-request.json'),request_sha256=file_hash(claim/'candidate-review-request.json'),audit_path=p['audit_path'],export_root=p['export_root'],controller_sha256=p['controller_sha256'],profile_sha256=pin,source_commit=p['source'].get('reference_commit')))
    dev=dispatch(p,'development_audit',dict(config_path=str(dp),config_sha256=file_hash(dp)),claim,cancel=cancel,runner=runner)
    if dev['status']!='done':return dict(status='uncertain',model_requests=0,executable_approval=False,cached=False)
    value=dispatch(p,'candidate_review',stage,claim,cancel=cancel,runner=runner);outcome=value.get('outcome');state='uncertain';recommendation=None
    pins=dict(stage['artifact_pins']);pins[str(Path(stage['config_path']).parent/'completion-prepare/receipt.json')]=file_hash(claim/'completion-prepare/receipt.json');pins[value['receipt_path']]=value['receipt_sha256']
    if (phase/'result-private.json').exists():pins[str(phase/'result-private.json')]=file_hash(phase/'result-private.json')
    for path in (dp,claim/'phase-development_audit/receipt.json',claim/'phase-development_audit/result-private.json'):pins[str(path)]=file_hash(path)
    if isinstance(outcome,dict):
        if value['status']=='done' and outcome.get('verified') is True:
            from .candidate_review_evidence import inspect as inspect_review
            try:
                checked=inspect_review(stage['config_path'],stage['config_sha256'],clock=clock);recommendation=checked['report']['recommendation'];state={'approve':'review_approved','reject':'review_rejected','needs_evidence':'needs_evidence'}[recommendation]
                rc=checked['config']
                for name,sha in checked['artifact_pins'].items():pins[str(Path(rc['root'])/name)]=sha
            except (ValueError,OSError,KeyError,TypeError) as error:
                state='uncertain';recommendation=None;failure=claim/'candidate-review-host-failure.json'
                profile.write(p,failure,dict(failure_class=type(error).__name__,reason='host_candidate_evidence_unverified'));pins[str(failure)]=file_hash(failure)
        elif outcome.get('closed_verified') is True:state='review_failed'
        else:state='uncertain'
    if cancel.is_set() or file_hash(pp)!=pin:state='uncertain'
    registration=dict(registered=False,reason='candidate_review_not_approved')
    if state=='review_approved':
        from .candidate_followup import register
        try:registration=register(pp,pin,claim,lock,clock=clock)
        except (ValueError,OSError):registration=dict(registered=False,reason='fixed_registry_publication_unverified')
    for name in ('intent.json','receipt.json','registry-before-private.json','env-before-private.txt'):
        path=claim/'followup-registration'/name
        if path.exists():pins[str(path)]=file_hash(path)
    if not _completion_audit(p,pin,claim,stage,state,now,pins,runner,registration):state='uncertain'
    after=ledger_snapshot(p['host']['ledger_path']);count=outcome.get('new_attempts') if isinstance(outcome,dict) else 0 if before==after else None
    result=dict(schema='pi-candidate-review-outcome-v1',mode=p['mode'],status=state,executable_approval=False,research_fingerprint=claim.name,task_id=stage['task_id'],candidate_sha256=stage['candidate_sha256'],model_requests=count,recommendation=recommendation,config_path=stage['config_path'],config_sha256=stage['config_sha256'],before_fee_sha256=before['sha256'],after_fee_sha256=after['sha256'],artifact_pins=pins,followup_registered=registration['registered'])
    profile.write(p,target,result);return dict(result,cached=False)


def observe_manager(profile_path,pin,claim_path,lock,*,runner=None,clock=None,cancel=None):
    """Retain stopped/abstaining manager facts without certifying partial SDK work."""
    pp=_path(profile_path);p,now,fee=profile.load(pp,pin,clock=clock);_lock(p,lock);claim=_directory(claim_path);admitted=_admitted(p,claim)
    ready=manager_completion.request(p['manager_state'],p['host']['ledger_path'],admitted['task_id'],mode=p['mode'])
    if ready['status'] not in ('execution_stopped','uncertain','no_action','cancelled'):return dict(status=ready['status'],model_requests=0)
    target=claim/'manager-observation.json'
    if target.exists():
        old=_read(target)[0];require(old['schema']=='pi-manager-completion-observation-v1' and all(file_hash(path)==sha for path,sha in old['artifact_pins'].items()),'manager observation drift')
        return dict(old,cached=True)
    if (claim/'phase-manager_audit').exists():return dict(status='uncertain',model_requests=0,cached=True)
    from . import manager
    from .autonomy_dispatch import run as dispatch
    _,_,rows,tasks,_=manager._snapshot(p['manager_state'],p['host']['ledger_path'],p['mode']);task=next(t for t in tasks if t['payload']['task_id']==admitted['task_id']);row=rows.get(task['operation_id']+':dispatch');state=ready['status']
    domain='real_provider_fixed_input' if p['mode']=='ACTUAL' else 'synthetic'
    version=dict(controller_sha256=p['controller_sha256'],policy_sha256=pin,sdk_version='1.1.0',source_commit=p['source'].get('reference_commit'))
    common=dict(run_id=admitted['task_id'],occurred_at=now.isoformat(),version=version,changes=[],evidence=[dict(kind='original_manager_state',sha256=digest(dict(task=task,dispatch=row)),verified=True,evidence_domain=domain)],followups=[],mode=p['mode'],evidence_domain=domain)
    observation=dict(common,kind='development',status={'execution_stopped':'failed','no_action':'no_change','cancelled':'blocked'}.get(state,'uncertain'),summary='Original manager stopped or declined development; partial SDK/tool/fee evidence is private and not certified.',details=dict(reference='manager.completion_observation.v1',decision=state,model_requests=None,known_cost_microyuan=None,range_complete=False,availability='partial_evidence_not_reconciled',next_action='retain_original_claim_no_automatic_replay'))
    release=dict(common,kind='deployment',status='no_release',summary='This manager observation grants no product adoption or rollback.',details=dict(reference='manager.stopped_no_release.v1',decision='no_release'))
    cp=claim/'manager-completion-audit.json';profile.write(p,cp,dict(schema='pi-autonomy-audit-v1',mode=p['mode'],audit_path=p['audit_path'],export_root=p['export_root'],events=[dict(record_key=admitted['task_id']+':manager-observation',event=observation),dict(record_key=admitted['task_id']+':manager-no-release',event=release)]))
    value=dispatch(p,'manager_audit',dict(config_path=str(cp),config_sha256=file_hash(cp)),claim,runner=runner,cancel=Event())
    pins={str(path):file_hash(path) for path in (cp,claim/'phase-manager_audit/receipt.json')}
    if (claim/'phase-manager_audit/result-private.json').exists():pins[str(claim/'phase-manager_audit/result-private.json')]=file_hash(claim/'phase-manager_audit/result-private.json')
    result=dict(schema='pi-manager-completion-observation-v1',status=state if value['status']=='done' and ledger_snapshot(p['host']['ledger_path'])==fee else 'uncertain',model_requests=0,executable_approval=False,artifact_pins=pins)
    profile.write(p,target,result);return dict(result,cached=False)
