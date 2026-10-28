"""Host authorization core; callers must authenticate leases before publication.

This pure validator does not read model output, create leases or write FileReview.
The external root-policy publisher remains responsible for lease provenance,
source revalidation, locks, durable claims and exclusive one-use publication.
"""
from datetime import datetime,timedelta
import re
from .audit import _path,digest,hash_value,require,strict_json,utc
from .development_inputs import authorization_hash,validate_review
from .review_dossier import semantic_hash
from .diagnosis_launcher import _unknown

FIELDS=set('schema authority mode semantic_sha256 deadline_ceiling plan_hash prepared_parent reviewer issued_at expires_at fee_checkpoint legacy_unknown_ids allowed_fee_operation_ids'.split())
REQUEST=set('authorization_sha256 plan_hash base candidate_id config_path task_id'.split())


def _snapshot(value):
    require(isinstance(value,dict) and set(value)=={'operations','events','limits','sha256'},'complete original fee snapshot required')
    require(value['sha256']==digest({k:v for k,v in value.items() if k!='sha256'}),'fee snapshot digest drift')
    require(isinstance(value['operations'],list) and isinstance(value['events'],list) and isinstance(value['limits'],dict))
    require(all(isinstance(r,dict) and isinstance(r.get('operation_id'),str) for r in value['operations']))
    result={r['operation_id']:r for r in value['operations']};require(len(result)==len(value['operations']),'duplicate fee operation')
    return result


def development_review(lease,config,request,current_fee,*,now):
    """Produce exact review data only from a host-authenticated reviewed scope."""
    require(isinstance(lease,dict) and set(lease)==FIELDS and lease['schema']=='pi-reviewed-development-scope-v1'
        and lease['authority']=='host_exact_file_review' and lease['mode'] in ('ACTUAL','SIMULATED'),'host reviewed scope required')
    now=utc(now);issued=utc(datetime.fromisoformat(lease['issued_at']));expires=utc(datetime.fromisoformat(lease['expires_at']))
    require(issued<=now<expires and expires-issued<=timedelta(hours=24),'review lease expired or future')
    reviewer=lease['reviewer'];require(isinstance(reviewer,str) and re.fullmatch('[a-zA-Z0-9_-]{1,100}',reviewer)
        and reviewer not in ('model','local-development-controller'),'independent host reviewer required')
    require(hash_value(lease['semantic_sha256']) and hash_value(lease['plan_hash']))
    require(semantic_hash(config,deadline_ceiling=lease['deadline_ceiling'])==lease['semantic_sha256'],'reviewed development semantics changed')
    require(config['review_sha256']=='0'*64,'unreviewed prepared config required')
    require(isinstance(request,dict) and set(request)==REQUEST,'exact review request required')
    parent=_path(lease['prepared_parent']);cp=_path(request['config_path']);review=_path(config['review_path'])
    require(parent.is_dir() and parent.stat().st_mode&0o777==0o700 and cp.name=='config.json'
        and cp.parent.parent==parent and review==cp.parent/'review.json','review publication location outside host scope')
    expected=dict(authorization_sha256=authorization_hash(config),plan_hash=lease['plan_hash'],base=config['source_sha256'],candidate_id=config['run_id'])
    require(all(type(request[k]) is type(v) and request[k]==v for k,v in expected.items()),'prepared review request drift')
    require(isinstance(request['task_id'],str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',request['task_id']) and cp.parent.name==request['task_id'],'prepared task identity drift')
    before=lease['fee_checkpoint'];old=_snapshot(before);current=_snapshot(current_fee)
    require(config['ledger_sha256']==current_fee['sha256'],'prepared current fee checkpoint drift')
    require(current_fee['limits']==before['limits'] and current_fee['events'][:len(before['events'])]==before['events']
        and all(current.get(k)==v for k,v in old.items()),'original fee history changed')
    ids=lease['legacy_unknown_ids'];allowed=lease['allowed_fee_operation_ids']
    require(isinstance(ids,list) and all(isinstance(x,str) for x in ids) and len(ids)==len(set(ids)) and _unknown(before)==_unknown(current_fee)==set(ids),'unknown fee state changed')
    require(isinstance(allowed,list) and len(allowed)<=1 and all(isinstance(x,str) and x not in old for x in allowed) and len(allowed)==len(set(allowed)),'one fixed selection fee operation required')
    new={k:r for k,r in current.items() if k not in old}
    require(set(new)<=set(allowed),'unapproved post-review fee operation')
    for row in new.values():
        require(row['kind']=='model-attempt' and row['status']=='done','unsettled post-review fee operation')
        evidence=strict_json(row['evidence'] or '{}');charge=evidence.get('charged_microyuan')
        require(type(charge) is int and charge>=0,'known post-review fee required')
    if lease['mode']=='ACTUAL':
        require(config['ledger_path']=='/home/ubuntu/myink-pi-managed/state/ledger.sqlite' and before['limits']['budget_microyuan']==50000000 and len(ids)==9,'original50CNY/nineholds required')
    result=dict(source='independent_review',verified=True,result='approved',reviewer=reviewer,
        **expected,owner='local-development-controller',generation=1)
    validate_review(result,config,lease['plan_hash'],config['source_sha256']);return result
