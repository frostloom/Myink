"""Authenticate a closed SDK review under host policy; create a private lease only."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from hashlib import sha256
import fcntl,os,re
from .audit import _path,_plain,digest,encoded,hash_value,require,strict_json,utc
from .development_inputs import path,file_hash,ledger_snapshot,read_json
from .review_issuer import _snapshot
from .review_dossier import semantic_hash
from .selection_launcher import verify_selection
from .diagnosis_launcher import _unknown,_disjoint
from . import sdk_review_launcher as sdk

POLICY=set('schema authority mode root prepared_parent review_config_parent source_sha256 allowed_files runtime_sha256 policy_sha256 credential_sha256 ledger_path budget_microyuan legacy_unknown_ids max_requests max_tools deadline_seconds issued_at expires_at'.split())
ARTIFACTS=('intent.json','manifest-private.json','initial-private.json','worker-frame-private.json','request-private.json','verification.json','result.json','ledger-before-private.json','ledger-after-private.json')


def _read(value,maximum=16777216):
    p=path(value,private=True);_plain(p);require(p.stat().st_size<=maximum,'bounded lease input required');raw=p.read_bytes();require(len(raw)<=maximum)
    return strict_json(raw),sha256(raw).hexdigest()


def _directory(value):
    p=_path(value);require(p.is_dir() and p.stat().st_mode&0o777==0o700,'private host lease directory required');return p


def _sync(p):
    fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def _new(p,value):
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as out:out.write(encoded(value)+b'\n');out.flush();os.fsync(out.fileno())
    _sync(p.parent)


def load_policy(policy_path,expected,clock=None):
    pp=path(policy_path);_plain(pp);raw=pp.read_bytes();require(len(raw)<=65536 and hash_value(expected) and sha256(raw).hexdigest()==expected,'issuer policy pin drift');p=strict_json(raw)
    require(isinstance(p,dict) and set(p)==POLICY and p['schema']=='pi-review-issuer-policy-v1' and p['authority']=='host_reviewed_development','host execution policy required')
    require(p['mode'] in ('ACTUAL','SIMULATED'))
    if p['mode']=='ACTUAL':
        require(clock is None and pp.stat().st_uid==0 and pp.stat().st_mode&0o777==0o640 and pp.parent.stat().st_uid==0 and pp.parent.stat().st_mode&0o777==0o750,'root issuer policy and real clock required')
        require(p['ledger_path']==str(sdk.CANONICAL) and p['budget_microyuan']==50000000 and len(p['legacy_unknown_ids'])==9,'original50CNY/nineholds required')
    else:require(pp.stat().st_mode&0o777==0o600,'private simulated policy required')
    now=utc((clock or (lambda:datetime.now(timezone.utc)))());issued=utc(datetime.fromisoformat(p['issued_at']));expires=utc(datetime.fromisoformat(p['expires_at']))
    require(issued<=now<expires and expires-issued<=timedelta(hours=24),'issuer policy expired or future')
    for key in ('source_sha256','runtime_sha256','policy_sha256','credential_sha256'):require(hash_value(p[key]))
    for key,maximum in (('max_requests',100),('max_tools',256),('deadline_seconds',1800)):require(type(p[key]) is int and 1<=p[key]<=maximum,'issuer phase limit invalid')
    require(type(p['budget_microyuan']) is int and p['budget_microyuan']>0)
    files=p['allowed_files'];require(isinstance(files,list) and 0<len(files)<=8 and len(set(files))==len(files) and all(isinstance(f,str) and re.fullmatch(r'src/[A-Za-z0-9_./-]+\.py',f) and '..' not in Path(f).parts for f in files),'bounded host source scope required')
    ids=p['legacy_unknown_ids'];require(isinstance(ids,list) and all(isinstance(i,str) for i in ids) and len(ids)==len(set(ids)))
    for key in ('root','prepared_parent','review_config_parent'):_directory(p[key])
    _disjoint(p['root'],p['prepared_parent']);_disjoint(p['root'],pp);_disjoint(p['root'],_path(p['ledger_path']).parent)
    return p,now


def inspect_review(policy_path,policy_sha256,review_config_path,review_config_sha256,*,clock=None,allow_fee_append=False):
    p,now=load_policy(policy_path,policy_sha256,clock);cp=path(review_config_path,private=True)
    require(cp.parent==_path(p['review_config_parent']) and file_hash(cp)==review_config_sha256,'host review config scope drift')
    c=read_json(cp);fee=ledger_snapshot(p['ledger_path'])
    c,policy,material,permit,current,provenance=sdk.prepare(cp,clock=clock,fresh=False,expected_fee_sha256=fee['sha256'])
    require(c['mode']==p['mode'] and all(c[k]==p[k] for k in ('runtime_sha256','policy_sha256','credential_sha256','ledger_path')),'host SDK identity drift')
    require(current==fee and fee['limits']['budget_microyuan']==p['budget_microyuan'] and _unknown(fee)==set(p['legacy_unknown_ids']),'host original fee scope drift')
    tc=read_json(c['template_path']);plan=read_json(tc['plan_path'])
    require(tc['source_sha256']==p['source_sha256'] and set(plan['files'])<=set(p['allowed_files']) and all(tc[k]<=p[k] for k in ('max_requests','max_tools','deadline_seconds')),'review exceeds host execution policy')
    root=_directory(c['root']);protected=[cp,_path(policy_path),root,*[_path(c[k]) for k in c if k.endswith('_path')],*[_path(tc[k]) for k in tc if k.endswith('_path')],_path(tc['root'])]
    protected.extend(_path(c['audit_path']+suffix) for suffix in ('-journal','-wal','-shm'))
    for item in protected:_disjoint(p['root'],item);_disjoint(p['prepared_parent'],item)
    values={};pins={}
    for name in ARTIFACTS:values[name],pins[name]=_read(root/name)
    intent=values['intent.json'];require(intent==dict(role=c['role'],config_sha256=review_config_sha256,input_sha256=sdk.input_hash(c,material)),'review intent drift')
    manifest=values['manifest-private.json'];require(manifest==dict(config=c,permit=permit,provenance=provenance),'review manifest drift')
    initial=values['initial-private.json'];require(initial['system']==sdk.SYSTEM and initial['prompt']==sdk.prompt(c,material) and initial['context_hash']==sdk.input_hash(c,material) and initial['config_hash']==digest(c) and initial['model']==policy.model and initial['max_tokens']==policy.max_tokens,'review initial input drift')
    proof=verify_selection(values['worker-frame-private.json'],initial,values['request-private.json']);require(proof==values['verification.json'],'review verification drift')
    report=sdk.validate_output(strict_json(proof['text']),c,material);require(report['recommendation']=='approve','independent review did not approve')
    result=values['result.json'];require(result.get('schema')=='pi-no-tool-result-v1' and all(result.get(k) is True for k in ('verified','execution_verified','contract_valid','closed_verified','policy_restored','credential_unchanged','original_history_unchanged')) and result.get('executable_approval') is False,'closed verified independent review required')
    require(result['mode']==c['mode'] and result['role']==c['role'] and result['run_id']==c['run_id'] and result['input_sha256']==sdk.input_hash(c,material) and result['report']==report and type(result['new_attempts']) is int and result['new_attempts']==1 and type(result['new_unknown']) is int and result['new_unknown']==0,'review result identity drift')
    require(isinstance(result['cleanup'],list) and bool(result['cleanup']) and all(isinstance(r,dict) and r.get('removed') is True and hash_value(r.get('container_id')) for r in result['cleanup']) and not any(k.endswith('failure_class') for k in result),'review cleanup uncertain')
    before=values['ledger-before-private.json'];after=values['ledger-after-private.json'];old=_snapshot(before);new=_snapshot(after)
    require(before['sha256']==c['ledger_sha256'] and (after==fee or allow_fee_append) and before['limits']==after['limits'] and after['events'][:len(before['events'])]==before['events'] and all(new.get(k)==v for k,v in old.items()) and _unknown(before)==_unknown(after)==set(p['legacy_unknown_ids']),'review fee history drift')
    added={k:v for k,v in new.items() if k not in old};posts=result['model_posts'];require(len(added)==1 and isinstance(posts,list) and len(posts)==1 and posts[0]['status']==200 and posts[0]['attempt_id'] in added,'review paid request binding drift')
    row=added[posts[0]['attempt_id']];e=strict_json(row['evidence'] or '{}');require(row['kind']=='model-attempt' and row['status']=='done' and e.get('usage_known') is True and type(e.get('charged_microyuan')) is int and e['charged_microyuan']>=0 and type(result['known_cost_microyuan']) is int and result['known_cost_microyuan']==e['charged_microyuan'],'review known charge required')
    require(file_hash(policy_path)==policy_sha256 and file_hash(cp)==review_config_sha256 and ledger_snapshot(p['ledger_path'])==fee and all(file_hash(root/name)==pin for name,pin in pins.items()),'review changed during lease inspection')
    return p,now,c,tc,material,fee,pins


def create(policy_path,policy_sha256,review_config_path,review_config_sha256,*,selection_operation_id,clock=None):
    p,_=load_policy(policy_path,policy_sha256,clock)
    require(isinstance(selection_operation_id,str) and re.fullmatch('[A-Za-z0-9:_-]{1,160}',selection_operation_id),'fixed host selection identity required')
    lockpath=_path(p['ledger_path']).with_suffix('.tools.lock');_plain(lockpath)
    with lockpath.open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        p,now,c,tc,material,fee,pins=inspect_review(policy_path,policy_sha256,review_config_path,review_config_sha256,clock=clock)
        require(selection_operation_id not in {r['operation_id'] for r in fee['operations']},'fresh selection fee identity required')
        scope=dict(schema='pi-reviewed-development-scope-v1',authority='host_exact_file_review',mode=p['mode'],semantic_sha256=semantic_hash(tc),deadline_ceiling=tc['deadline_seconds'],plan_hash=material['dossier']['model_view']['plan_hash'],prepared_parent=p['prepared_parent'],reviewer='independent-sdk-host-policy',issued_at=now.isoformat(),expires_at=p['expires_at'],fee_checkpoint=fee,legacy_unknown_ids=p['legacy_unknown_ids'],allowed_fee_operation_ids=[selection_operation_id])
        root=_path(p['root'])/('lease-'+digest(dict(review_config_sha256=review_config_sha256,semantic_sha256=scope['semantic_sha256'])))
        require(not root.exists(),'review lease claim exists; no replay');root.mkdir(mode=0o700);_sync(root.parent)
        _new(root/'intent.json',dict(schema='pi-review-lease-intent-v1',policy_sha256=policy_sha256,review_config_sha256=review_config_sha256,semantic_sha256=scope['semantic_sha256']))
        record=dict(schema='pi-review-lease-record-v1',policy_path=str(policy_path),policy_sha256=policy_sha256,review_config_path=str(review_config_path),review_config_sha256=review_config_sha256,artifact_pins=pins,scope=scope)
        _new(root/'lease.json',record)
        return dict(authority='lease_only',lease_path=str(root/'lease.json'),lease_sha256=file_hash(root/'lease.json'))
