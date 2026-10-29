"""Root-only fixed next-day registry append; model output never supplies paths."""
from datetime import timedelta
import os,stat,tempfile
from pathlib import Path
from .audit import _path,_plain,require,encoded,digest,utc,SHANGHAI,hash_value
from .development_inputs import file_hash,read_json,ledger_snapshot
from .review_lease import _sync,_directory
from . import autonomy_profile as profile
from .followup import _load,_pins,_read

ENV_KEYS={'PI_OBSERVER_RUNTIME_SHA256','PI_FOLLOWUP_ENTRYPOINT','PI_FOLLOWUP_REGISTRY_SHA256'}


def _replace(path,raw,p):
    """Atomic single fixed root config replacement, retaining pair preimages."""
    fd,name=tempfile.mkstemp(prefix='.followup-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            out.write(raw);out.flush();os.fchmod(out.fileno(),0o640 if p['mode']=='ACTUAL' else 0o600)
            if p['mode']=='ACTUAL':os.fchown(out.fileno(),0,profile._owner(p)[1])
            os.fsync(out.fileno())
        os.replace(name,path);_sync(path.parent)
    finally:
        if os.path.exists(name):os.unlink(name)


def register(profile_path,pin,claim_path,lock,*,clock=None):
    from .candidate_review_stage import _admitted,_lock,_scope
    from .manager_completion import inspect as manager_proof
    from .candidate_review_evidence import inspect as review_proof
    pp=_path(profile_path);p,now,fee=profile.load(pp,pin,clock=clock);_lock(p,lock);claim=_directory(claim_path)
    if p['mode']=='ACTUAL':
        from .manager_handoff import BASE
        require(pp==BASE/'config/autonomy-profile.json','canonical root source profile required')
    admitted=_admitted(p,claim);task=admitted['task_id'];cp=claim/'candidate-review-config.json';c=read_json(cp)
    stage=read_json(claim/'completion-prepare/receipt.json');require(stage['config_sha256']==file_hash(cp) and stage['task_id']==task,'original prepared candidate config required')
    original=manager_proof(p['manager_state'],p['host']['ledger_path'],task,c['request_path'],c['request_sha256'],mode=p['mode']);_scope(p,original)
    checked=review_proof(cp,file_hash(cp),clock=clock);candidate=original['development']['candidate_sha256']
    require(checked['authority']=='recommendation_only' and checked['report']['recommendation']=='approve' and checked['report']['candidate_sha256']==candidate==stage['candidate_sha256']
        and checked['config']==c and original['manager_binding']==stage['manager_binding'],'authenticated original candidate approval required')
    root=claim/'followup-registration'
    if root.exists():return dict(status='uncertain',registered=False,reason='existing_registration_claim_no_replay')
    rp=pp.parent/'followup-registry.json';ep=pp.parent/'followup.env'
    if not rp.exists() or not ep.exists():return dict(status='blocked',registered=False,reason='fixed_registry_not_published')
    old=_read(rp);oldenv=_read(ep,8192);config=_load(rp,file_hash(rp),None if p['mode']=='ACTUAL' else lambda *a:None,clock)
    require(config['mode']==p['mode'] and all(config[k]==v for k,v in dict(audit_path=p['audit_path'],export_root=p['export_root'],lock_path=p['lock_path'],billing_path=p['host']['ledger_path'],manager_path=p['manager_state']).items()),'original followup state binding required')
    if p['mode']=='ACTUAL':require(ep.stat().st_uid==0 and stat.S_IMODE(ep.stat().st_mode)==0o640,'root followup env required')
    else:require(stat.S_IMODE(ep.stat().st_mode)==0o600,'private simulated env required')
    lines=oldenv.decode('ascii').splitlines();env={}
    for line in lines:
        key,separator,value=line.partition('=');require(separator and key in ENV_KEYS and key not in env and value and not any(ch.isspace() for ch in value),'closed followup env required');env[key]=value
    require(set(env)==ENV_KEYS and hash_value(env['PI_OBSERVER_RUNTIME_SHA256']) and env['PI_FOLLOWUP_REGISTRY_SHA256']==file_hash(rp),'followup registry/env pair drift')
    if p['mode']=='ACTUAL':
        from .deploy.observer_entry import verify_release
        entry=_path(env['PI_FOLLOWUP_ENTRYPOINT']);require(entry.name=='entry.py' and entry.is_relative_to(BASE/'releases'),'fixed closed followup entry required');verify_release(entry.parent,env['PI_OBSERVER_RUNTIME_SHA256'])
    require(len(config['entries'])<32,'followup registry capacity reached')
    for prior in config['entries']:_pins(prior)
    dc=original['development']['config'];due=(now.astimezone(SHANGHAI)+timedelta(days=1)).replace(hour=3,minute=0,second=0,microsecond=0)
    entry=dict(test_id='fixed-'+candidate[:32],run_id=task,scheduled_for=utc(due).isoformat(),candidate_path=str(Path(dc['root'])/'candidate'),candidate_sha256=candidate,source_path=dc['source_path'],source_sha256=dc['source_sha256'],test_path=dc['test_path'],test_sha256=dc['test_sha256'],test_cases=dc['test_cases'],review_path=str(Path(c['root'])/'result.json'),review_sha256=checked['artifact_pins']['result.json'],checker={k:dc[k] for k in ('docker','endpoint','daemon_id','checker_image_id')})
    require(entry['checker']['checker_image_id']==p['checker_image_id'] and not any(e['test_id']==entry['test_id'] or (e['run_id']==task and e['candidate_sha256']==candidate) for e in config['entries']),'duplicate candidate or checker drift');_pins(entry)
    updated=dict(config,entries=config['entries']+[entry]);raw=encoded(updated);env['PI_FOLLOWUP_REGISTRY_SHA256']=digest(updated);newenv=('\n'.join(k+'='+env[k] for k in sorted(env))+'\n').encode('ascii')
    require(file_hash(pp)==pin and ledger_snapshot(p['host']['ledger_path'])==fee and _read(rp)==old and _read(ep)==oldenv,'registration parent/state revoked')
    root.mkdir(mode=0o700)
    if p['mode']=='ACTUAL':os.chown(root,*profile._owner(p))
    _sync(claim)
    # Exact preimages are private and immutable. Pair interruption never grants a retry.
    from .task_package import _publish_new
    for name,data in (('registry-before-private.json',old),('env-before-private.txt',oldenv)):
        target=root/name;require(not _publish_new(target,data),'registration backup exists')
        if p['mode']=='ACTUAL':os.chown(target,*profile._owner(p))
    intent=dict(schema='pi-candidate-followup-intent-v1',profile_sha256=pin,entry_sha256=digest(entry),old_registry_sha256=file_hash(rp),old_env_sha256=file_hash(ep),new_registry_sha256=digest(updated))
    profile.write(p,root/'intent.json',intent)
    require(file_hash(pp)==pin and _read(rp)==old and _read(ep)==oldenv,'registration revoked before config replacement')
    _replace(rp,raw,p)
    require(file_hash(pp)==pin and _read(rp)==raw and _read(ep)==oldenv,'registration interrupted before env replacement')
    _replace(ep,newenv,p)
    require(_read(rp)==raw and _read(ep)==newenv and file_hash(pp)==pin and ledger_snapshot(p['host']['ledger_path'])==fee,'registration pair/fee verification failed')
    receipt=dict(schema='pi-candidate-followup-registration-v1',status='registered',registered=True,entry=entry,registry_sha256=file_hash(rp),env_sha256=file_hash(ep),intent_sha256=file_hash(root/'intent.json'))
    profile.write(p,root/'receipt.json',receipt);return receipt
