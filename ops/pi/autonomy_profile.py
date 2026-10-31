"""Trusted fixed source profile and mechanical stage construction; no model calls."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import os,re,stat
from .audit import _path,_plain,digest,hash_value,require,utc
from .development_inputs import file_hash,ledger_snapshot,read_json,tree_hash
from .review_lease import _read,_new,_sync,_directory
from .diagnosis_launcher import _unknown
from .local_cycle import _disjoint
from .policy import load_policy
from .provider_config import load_credentials
from .investigation_inputs import compile_context
from .live_diagnosis import inspect_observation
from .manager_handoff import BASE

FIELDS=set('schema authority mode root permit_root handoff_root review_root investigation_root reproduction_root host observer source audit_path export_root manager_state inbox lock_path budget_microyuan legacy_unknown_ids limits issued_at expires_at worker_entry_path controller_sha256 checker_image_id'.split())
HOST=set('runtime_path runtime_sha256 ledger_path policy_path policy_sha256 credential_path credential_sha256 docker endpoint daemon_id image_id'.split())
OBSERVER=set('observer_config_path observer_config_sha256 observer_controller_sha256'.split())
SOURCE=set('source_path source_sha256 files reference_commit pending_path pending_sha256 behavior'.split())
MAXIMA=dict(investigation_seconds=120,review_seconds=120,checker_seconds=90,max_requests=100,max_tools=256,development_seconds=1800,cycle_seconds=2100,review_wait_seconds=600,priority=9)
ROOTS=('root','permit_root','handoff_root','review_root','investigation_root','reproduction_root')
ACTUAL_ROOTS=dict(root=BASE/'autonomy',permit_root=BASE/'config/autonomy-permits',handoff_root=BASE/'handoffs',review_root=BASE/'reviews',investigation_root=BASE/'investigations',reproduction_root=BASE/'reproductions')


def load(profile_path,pin,*,clock=None):
    path=_path(profile_path);_plain(path);require(path.stat().st_size<=65536 and file_hash(path)==pin,'autonomy profile pin drift');p=read_json(path)
    require(isinstance(p,dict) and set(p)==FIELDS and p['schema']=='pi-autonomy-profile-v1' and p['authority']=='bounded_source_investigation_and_review' and p['mode'] in ('ACTUAL','SIMULATED'),'fixed source profile required')
    if p['mode']=='ACTUAL':
        require(clock is None and os.geteuid()==0 and path.stat().st_uid==0 and stat.S_IMODE(path.stat().st_mode)==0o640 and path.parent.stat().st_uid==0 and stat.S_IMODE(path.parent.stat().st_mode)==0o750,'ACTUAL root coordinator profile required')
        require(all(_path(p[k])==v for k,v in ACTUAL_ROOTS.items()) and _path(p['manager_state'])==BASE/'state/actual-manager.sqlite' and _path(p['inbox'])==BASE/'inbox' and _path(p['lock_path'])==BASE/'control/maintenance.lock','original actual roots required')
        require(p['budget_microyuan']==50000000 and len(p['legacy_unknown_ids'])==9,'original50CNY/nineholds required')
    else:require(stat.S_IMODE(path.stat().st_mode)==0o600,'private simulated profile required')
    now=utc((clock or (lambda:datetime.now(timezone.utc)))());issued=utc(p['issued_at']);expires=utc(p['expires_at']);require(issued<=now<expires and expires-issued<=timedelta(hours=24),'profile expired or future')
    require(isinstance(p['host'],dict) and set(p['host'])==HOST and isinstance(p['observer'],dict) and set(p['observer'])==OBSERVER and isinstance(p['source'],dict) and set(p['source'])==SOURCE,'closed profile input scopes required')
    require(isinstance(p['checker_image_id'],str) and re.fullmatch('sha256:[0-9a-f]{64}',p['checker_image_id']),'immutable checker required')
    h=p['host'];s=p['source'];o=p['observer']
    require(isinstance(p['limits'],dict) and set(p['limits'])==set(MAXIMA) and all(type(p['limits'][k]) is int and (0 if k=='priority' else 1)<=p['limits'][k]<=v for k,v in MAXIMA.items()) and p['limits']['development_seconds']>=120,'bounded phase limits required')
    require(isinstance(s['files'],list) and 0<len(s['files'])<=3 and len(set(s['files']))==len(s['files']) and all(isinstance(f,str) and re.fullmatch(r'src/[A-Za-z0-9_./-]+\.py',f) and '..' not in Path(f).parts for f in s['files']),'fixed bounded research source files required')
    require(isinstance(s['behavior'],str) and 0<len(s['behavior'])<=200 and (s['reference_commit'] is None or hash_value(s['reference_commit'],40)))
    for values in (h,s,o):
        for k,v in values.items():
            if k.endswith('_sha256'):require(hash_value(v),'profile input digest required')
    source=_path(s['source_path']);require(hash_value(s['source_sha256']) and source.is_dir() and {x.name for x in source.iterdir()}=={'src'} and tree_hash(source)==s['source_sha256'],'closed source profile drift')
    for f in s['files']:_plain(_path(source/f))
    require(file_hash(s['pending_path'])==s['pending_sha256'] and hash_value(p['controller_sha256']),'pending findings pin drift')
    for k in ('policy','credential'):require(file_hash(h[k+'_path'])==h[k+'_sha256'],'host identity drift')
    policy=load_policy(_path(h['policy_path']));require(not policy.live_enabled and not policy.server_daily_enabled and policy.input_bound_calibrated,'closed calibrated policy required');load_credentials(h['credential_path'],policy)
    fee=ledger_snapshot(h['ledger_path']);ids=p['legacy_unknown_ids'];require(isinstance(ids,list) and len(ids)==len(set(ids)) and all(isinstance(i,str) for i in ids) and _unknown(fee)==set(ids),'unknown fee scope drift')
    require(type(p['budget_microyuan']) is int and p['budget_microyuan']==policy.budget_microyuan==fee['limits']['budget_microyuan'] and fee['limits']['max_attempts']==policy.max_attempts,'original financial scope required')
    if p['mode']=='ACTUAL':require(_path(h['ledger_path'])==BASE/'state/ledger.sqlite','original actual ledger required')
    else:require(_path(h['ledger_path'])!=BASE/'state/ledger.sqlite','isolated simulated ledger required')
    entry=_path(p['worker_entry_path']);_plain(entry);require(entry.is_file(),'fixed worker entry required')
    if p['mode']=='ACTUAL':
        from .deploy.observer_entry import verify_release
        require(entry.name=='entry.py' and entry.is_relative_to(BASE/'releases'),'closed actual phase entry required');verify_release(entry.parent,p['controller_sha256'])
    from .live_observer import _load
    _,oc,op,observations,*_=_load(o['observer_config_path']);require(oc['mode']==p['mode'] and op==o['observer_config_sha256'],'observer profile drift')
    _plain(_path(p['manager_state']));_plain(_path(p['lock_path']));_directory(p['inbox'])
    protected=[path,source,_path(s['pending_path']),_path(h['runtime_path']),_path(h['ledger_path']).parent,_path(h['policy_path']),_path(h['credential_path']),_path(o['observer_config_path']),observations,entry,_path(p['manager_state']).parent,_path(p['lock_path'])]
    audit=_path(p['audit_path']);outputs=[_path(p[k]) for k in ROOTS]+[audit,_path(p['export_root']),_path(p['inbox']),*[_path(str(audit)+suffix) for suffix in ('-journal','-wal','-shm')]]
    for output in [_path(p[k]) for k in ROOTS]+[_path(p['inbox'])]:_disjoint(output,audit.parent)
    for k in ROOTS:
        out=_path(p[k])
        if k=='permit_root' and p['mode']=='ACTUAL':require(out.is_dir() and out.stat().st_uid==0 and out.stat().st_gid==_owner(p)[1] and stat.S_IMODE(out.stat().st_mode)==0o750,'root permit directory required')
        else:
            _directory(out)
            if p['mode']=='ACTUAL':require(out.stat().st_uid==_owner(p)[0] and out.stat().st_gid==_owner(p)[1],'ordinary worker must own its private stage roots')
    for i,out in enumerate(outputs):
        for item in protected:_disjoint(out,item)
        for other in outputs[i+1:]:_disjoint(out,other)
    require(file_hash(profile_path)==pin and ledger_snapshot(h['ledger_path'])==fee,'profile changed while loading')
    return p,now,fee


def _owner(p):
    if p['mode']=='ACTUAL':
        import pwd
        user=pwd.getpwnam('ubuntu');return user.pw_uid,user.pw_gid
    return os.geteuid(),os.getegid()


def write(p,path,value,*,permit=False):
    """Exclusive host file; permits stay root-owned, worker inputs belong to ubuntu."""
    _new(path,value)
    if p['mode']=='ACTUAL':
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            os.fchmod(fd,0o640 if permit else 0o600)
            uid,gid=_owner(p);os.fchown(fd,0 if permit else uid,gid)
            os.fsync(fd)
        finally:os.close(fd)
        _sync(path.parent)


def research(profile_path,pin,receipt_path,*,clock=None):
    p,now,fee=load(profile_path,pin,clock=clock);h=p['host'];s=p['source'];o=p['observer']
    e=inspect_observation(o['observer_config_path'],o['observer_config_sha256'],receipt_path,expected_controller_sha256=o['observer_controller_sha256'],clock=clock)
    credentials=load_credentials(h['credential_path'],load_policy(_path(h['policy_path'])))
    context=compile_context(s['source_path'],s['source_sha256'],s['files'],e,reference_commit=s['reference_commit'],pending=read_json(s['pending_path']),credential_literal=credentials['PLATFORM_MODEL_API_KEY']);fp=context['research_fingerprint']
    claim=_path(p['root'])/fp;root=_path(p['investigation_root'])/('research-'+fp)
    require(not claim.exists() and not root.exists(),'permanent research claim exists; no replay')
    require(file_hash(profile_path)==pin and ledger_snapshot(h['ledger_path'])==fee,'profile revoked before claim')
    claim.mkdir(mode=0o700)
    if p['mode']=='ACTUAL':os.chown(claim,*_owner(p))
    _sync(claim.parent);write(p,claim/'intent.json',dict(schema='pi-autonomy-intent-v1',profile_sha256=pin,research_fingerprint=fp,source_sha256=s['source_sha256'],occurred_at=now.isoformat()))
    write(p,claim/'evidence.json',e);write(p,claim/'research-input.json',context)
    permit=_path(p['permit_root'])/('research-'+fp+'.json');c=dict(h,**o,schema='pi-investigation-v1',role='investigation',mode=p['mode'],run_id='research-'+fp[:32],root=str(root),ledger_sha256=fee['sha256'],observation_receipt_path=str(receipt_path),evidence_path=str(claim/'evidence.json'),evidence_sha256=file_hash(claim/'evidence.json'),**{k:v for k,v in s.items() if k!='behavior'},input_path=str(claim/'research-input.json'),input_sha256=file_hash(claim/'research-input.json'),permit_path=str(permit),permit_sha256='0'*64,deadline_seconds=p['limits']['investigation_seconds'],audit_path=p['audit_path'],export_root=p['export_root'])
    authority={k:c[k] for k in ('mode','role','run_id','input_sha256','evidence_sha256','source_sha256','pending_sha256','runtime_sha256','policy_sha256','credential_sha256','ledger_path','deadline_seconds')}
    authority.update(schema='pi-investigation-permit-v1',authority='test_proposal_only',research_fingerprint=fp,evidence_fingerprint=e['evidence_fingerprint'],claim_root=p['investigation_root'],budget_scope='local-trial-1',budget_microyuan=p['budget_microyuan'],max_model_requests=1,legacy_unknown_ids=p['legacy_unknown_ids'],issued_at=now.isoformat(),expires_at=p['expires_at'])
    write(p,permit,authority,permit=True);c['permit_sha256']=file_hash(permit);config=claim/'research-config.json';write(p,config,c)
    return dict(claim_path=str(claim),config_path=str(config),config_sha256=file_hash(config),research_fingerprint=fp)


def claim_scope(p,pin,claim):
    claim=_directory(claim);intent,_=_read(claim/'intent.json')
    require(claim.parent==_path(p['root']) and hash_value(claim.name) and intent['schema']=='pi-autonomy-intent-v1' and intent['profile_sha256']==pin and intent['research_fingerprint']==claim.name and intent['source_sha256']==p['source']['source_sha256'],'original coordinator claim required')
    return claim,claim.name


def reproducer(profile_path,pin,config_path,config_sha256,*,clock=None):
    p,now,fee=load(profile_path,pin,clock=clock);claim,fp=claim_scope(p,pin,_path(config_path).parent)
    require(_path(config_path)==claim/'research-config.json' and file_hash(config_path)==config_sha256,'original generated research config required')
    from .investigation_evidence import inspect
    proof=inspect(config_path,config_sha256,clock=clock);c=proof['config']
    require(all(c[k]==v for k,v in {**p['host'],**p['observer'],**{k:v for k,v in p['source'].items() if k!='behavior'}}.items()) and proof['material']['context']['research_fingerprint']==fp,'research outside source profile')
    require(proof['proposal']['decision']=='task','no-task proposal needs no checker permission')
    out=_path(p['permit_root'])/('reproducer-'+fp+'.json');limits=p['limits']
    value=dict(schema='pi-investigation-reproducer-v1',authority='isolated_reproducer',mode=p['mode'],run_id='repair-'+fp[:32],root=str(_path(p['reproduction_root'])/('repro-'+fp)),research_config_path=str(config_path),research_config_sha256=config_sha256,checker_image_id=p['checker_image_id'],check_seconds=limits['checker_seconds'],max_requests=limits['max_requests'],max_tools=limits['max_tools'],development_seconds=limits['development_seconds'],behavior=p['source']['behavior'],issued_at=now.isoformat(),expires_at=p['expires_at'])
    require(file_hash(profile_path)==pin and ledger_snapshot(c['ledger_path'])==fee,'reproducer authority revoked');write(p,out,value,permit=True)
    result=dict(config_path=str(out),config_sha256=file_hash(out));write(p,claim/'reproducer-stage.json',result);return result


def review(profile_path,pin,claim_path,*,clock=None):
    p,now,fee=load(profile_path,pin,clock=clock);claim,fp=claim_scope(p,pin,claim_path);stage=_read(claim/'reproducer-stage.json')[0];rp=_path(p['permit_root'])/('reproducer-'+fp+'.json')
    require(_path(stage['config_path'])==rp and file_hash(rp)==stage['config_sha256'],'original reproducer policy required')
    policy=read_json(rp);root=_path(p['reproduction_root'])/('repro-'+fp);receipt,receipt_pin=_read(root/'receipt.json')
    expected=dict(schema='pi-reproduction-result-v1',status='reproduced',eligible_for_review=True,model_requests=0,template_path=str(root/'development-template.json'),dossier_path=str(root/'review-dossier.json'),baseline_outcome_path=str(root/'baseline/outcome.json'))
    require(digest(receipt)==digest(expected) and policy['root']==str(root) and policy['research_config_path']==str(claim/'research-config.json'),'complete reproduced task required')
    from .investigation_evidence import inspect
    inspect(policy['research_config_path'],policy['research_config_sha256'],clock=clock)
    from .review_dossier import compile_dossier
    tc=read_json(receipt['template_path']);plan=read_json(tc['plan_path'])
    require(tc['source_sha256']==p['source']['source_sha256'] and _path(tc['root'])==root/'development-output' and set(plan['files'])<=set(p['source']['files']) and all(tc[k]<=p['limits'][limit] for k,limit in (('max_requests','max_requests'),('max_tools','max_tools'),('deadline_seconds','development_seconds'))) and all(tc[k]==v for k,v in p['host'].items()),'reproduction exceeded root source profile')
    bq=root/'baseline-request.json';dossier=compile_dossier(receipt['template_path'],file_hash(receipt['template_path']),bq,file_hash(bq),receipt['baseline_outcome_path'],file_hash(receipt['baseline_outcome_path']))
    require(digest(read_json(receipt['dossier_path']))==digest(dossier),'reproduction dossier drift')
    h=p['host'];limits=p['limits'];handoffs=_path(p['handoff_root']);permit=_path(p['permit_root'])/('review-'+fp+'.json');cp=handoffs/('review-config-'+fp+'.json')
    c=dict(h,schema='pi-sdk-review-v1',role='independent_review',mode=p['mode'],run_id='review-'+fp[:32],root=str(claim/'review-output'),ledger_sha256=fee['sha256'],deadline_seconds=limits['review_seconds'],template_path=receipt['template_path'],template_sha256=file_hash(receipt['template_path']),baseline_request_path=str(bq),baseline_request_sha256=file_hash(bq),outcome_path=receipt['baseline_outcome_path'],outcome_sha256=file_hash(receipt['baseline_outcome_path']),dossier_path=receipt['dossier_path'],dossier_sha256=file_hash(receipt['dossier_path']),permit_path=str(permit),permit_sha256='0'*64,audit_path=p['audit_path'],export_root=p['export_root'])
    authority={k:c[k] for k in ('mode','role','run_id','dossier_sha256','runtime_sha256','policy_sha256','credential_sha256','ledger_path','deadline_seconds')};authority.update(schema='pi-sdk-review-permit-v1',authority='independent_review_recommendation_only',semantic_sha256=dossier['semantic_sha256'],budget_scope='local-trial-1',budget_microyuan=p['budget_microyuan'],max_model_requests=1,legacy_unknown_ids=p['legacy_unknown_ids'],issued_at=now.isoformat(),expires_at=p['expires_at'])
    issuer=dict(schema='pi-review-issuer-policy-v1',authority='host_reviewed_development',mode=p['mode'],root=p['review_root'],prepared_parent=str(handoffs/('handoff-'+fp)/'bundle/cycle-output/prepared'),review_config_parent=str(handoffs),source_sha256=tc['source_sha256'],allowed_files=read_json(tc['plan_path'])['files'],runtime_sha256=h['runtime_sha256'],policy_sha256=h['policy_sha256'],credential_sha256=h['credential_sha256'],ledger_path=h['ledger_path'],budget_microyuan=p['budget_microyuan'],legacy_unknown_ids=p['legacy_unknown_ids'],max_requests=limits['max_requests'],max_tools=limits['max_tools'],deadline_seconds=limits['development_seconds'],issued_at=now.isoformat(),expires_at=p['expires_at'])
    require(file_hash(profile_path)==pin and file_hash(root/'receipt.json')==receipt_pin and ledger_snapshot(h['ledger_path'])==fee,'review authority revoked')
    write(p,permit,authority,permit=True);c['permit_sha256']=file_hash(permit);write(p,cp,c);ip=_path(p['permit_root'])/('issuer-'+fp+'.json');write(p,ip,issuer,permit=True)
    result=dict(config_path=str(cp),config_sha256=file_hash(cp),issuer_policy_path=str(ip),issuer_policy_sha256=file_hash(ip),reproduction_receipt_path=str(root/'receipt.json'),reproduction_receipt_sha256=receipt_pin)
    write(p,claim/'review-stage.json',result);return result


def handoff(profile_path,pin,claim_path,*,clock=None):
    p,now,fee=load(profile_path,pin,clock=clock);claim,fp=claim_scope(p,pin,claim_path);stage=_read(claim/'review-stage.json')[0]
    require(_path(stage['config_path'])==_path(p['handoff_root'])/('review-config-'+fp+'.json') and _path(stage['issuer_policy_path'])==_path(p['permit_root'])/('issuer-'+fp+'.json'),'original generated review required')
    from .review_lease import inspect_review
    inspect_review(stage['issuer_policy_path'],stage['issuer_policy_sha256'],stage['config_path'],stage['config_sha256'],clock=clock)
    limits=p['limits'];root=_path(p['handoff_root'])/('handoff-'+fp);config=_path(p['handoff_root'])/('request-'+fp+'.json')
    cycle_seconds=min(limits['cycle_seconds'],2090)
    if p['mode']=='ACTUAL':
        from .maintenance_window import cycle_deadline
        cycle_seconds=cycle_deadline(now,cycle_seconds)
    value=dict(schema='pi-reviewed-manager-handoff-v1',mode=p['mode'],root=str(root),issuer_policy_path=stage['issuer_policy_path'],issuer_policy_sha256=stage['issuer_policy_sha256'],review_config_path=stage['config_path'],review_config_sha256=stage['config_sha256'],reproduction_receipt_path=stage['reproduction_receipt_path'],reproduction_receipt_sha256=stage['reproduction_receipt_sha256'],cycle_id='auto-'+fp[:32],selection_run_id='select-'+fp[:32],task_id='auto-'+fp[:32],manager_state=p['manager_state'],inbox=p['inbox'],deadline_seconds=cycle_seconds,review_wait_seconds=limits['review_wait_seconds'],priority=limits['priority'])
    require(file_hash(profile_path)==pin and ledger_snapshot(p['host']['ledger_path'])==fee,'handoff authority revoked');write(p,config,value)
    result=dict(config_path=str(config),config_sha256=file_hash(config));write(p,claim/'handoff-stage.json',result);return result
