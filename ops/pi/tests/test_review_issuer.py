"""Exact authorization must remain within the independently reviewed semantics."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import importlib,pytest
from ops.pi.audit import digest
from ops.pi.development_inputs import authorization_hash,ledger_snapshot,read_json,validate_review
from ops.pi.review_dossier import semantic_hash
from ops.pi.tests.test_review_dossier import dossier_input,config_file

NOW=datetime(2026,10,29,tzinfo=timezone.utc)

@pytest.fixture
def scope(dossier_input):
    cp,c,*_=dossier_input;parent=cp.parent/'prepared';parent.mkdir(mode=0o700);target=parent/'value-fix';target.mkdir(mode=0o700)
    prepared=dict(c,deadline_seconds=c['deadline_seconds']-1,review_path=str(target/'review.json'),review_sha256='0'*64)
    plan_hash=digest(read_json(c['plan_path']));fee=ledger_snapshot(c['ledger_path'])
    lease=dict(schema='pi-reviewed-development-scope-v1',authority='host_exact_file_review',mode='SIMULATED',semantic_sha256=semantic_hash(c),deadline_ceiling=c['deadline_seconds'],plan_hash=plan_hash,prepared_parent=str(parent),reviewer='independent-sdk-host-policy',issued_at=(NOW-timedelta(minutes=1)).isoformat(),expires_at=(NOW+timedelta(hours=1)).isoformat(),fee_checkpoint=deepcopy(fee),legacy_unknown_ids=[],allowed_fee_operation_ids=[])
    request=dict(authorization_sha256=authorization_hash(prepared),plan_hash=plan_hash,base=c['source_sha256'],candidate_id=c['run_id'],config_path=str(target/'config.json'),task_id='value-fix')
    return lease,prepared,request,fee


def api():return importlib.import_module('ops.pi.review_issuer')


def test_exact_review_accepts_only_lower_deadline_and_current_checkpoint(scope):
    lease,c,request,fee=scope;before=deepcopy(scope)
    review=api().development_review(lease,c,request,fee,now=NOW)
    validate_review(review,c,lease['plan_hash'],c['source_sha256'])
    assert scope==before and not Path(c['review_path']).exists()


@pytest.mark.parametrize('key',['root','run_id','source_sha256','test_sha256','plan_sha256','policy_sha256','runtime_sha256','credential_sha256','max_requests','max_tools','deadline_seconds'])
def test_semantic_expansion_never_produces_review(scope,key):
    lease,c,request,fee=scope
    if key in ('max_requests','max_tools'):c[key]+=1
    elif key=='deadline_seconds':c[key]=lease['deadline_ceiling']+1
    else:c[key]=c[key]+'changed'
    request['authorization_sha256']=authorization_hash(c)
    with pytest.raises(ValueError):api().development_review(lease,c,request,fee,now=NOW)


@pytest.mark.parametrize('fault',['expired','future','authority','reviewer','location','request','fee_pin','events','operations','limits','unknown','extra'])
def test_untrusted_or_stale_scope_rejected(scope,fault):
    lease,c,request,fee=scope
    if fault=='expired':lease['expires_at']=NOW.isoformat()
    elif fault=='future':lease['issued_at']=(NOW+timedelta(seconds=1)).isoformat()
    elif fault=='authority':lease['authority']='model_recommendation'
    elif fault=='reviewer':lease['reviewer']='model'
    elif fault=='location':c['review_path']=str(Path(lease['prepared_parent']).parent/'escaped.json');request['authorization_sha256']=authorization_hash(c)
    elif fault=='request':request['candidate_id']='other'
    elif fault=='fee_pin':c['ledger_sha256']='f'*64;request['authorization_sha256']=authorization_hash(c)
    elif fault=='events':fee['events'].append(dict(id=-1));lease['fee_checkpoint']['events']=[]
    elif fault=='operations':fee['operations'][0]['status']='changed'
    elif fault=='limits':fee['limits']['budget_microyuan']+=1
    elif fault=='unknown':lease['legacy_unknown_ids']=['new-unknown']
    else:lease['approved']=True
    with pytest.raises(ValueError):api().development_review(lease,c,request,fee,now=NOW)


def post_selection(scope,*,status='done',allowed=True):
    lease,c,request,fee=scope
    operation=dict(operation_id='fixed-selection-attempt',kind='model-attempt',status=status,evidence='{"charged_microyuan":3,"usage_known":true}')
    fee['operations'].append(operation)
    fee['sha256']=digest({k:v for k,v in fee.items() if k!='sha256'})
    c['ledger_sha256']=fee['sha256'];request['authorization_sha256']=authorization_hash(c)
    if allowed:lease['allowed_fee_operation_ids']=[operation['operation_id']]
    return lease,c,request,fee


def test_only_fixed_known_selection_fee_may_follow_paid_review(scope):
    lease,c,request,fee=post_selection(scope)
    value=api().development_review(lease,c,request,fee,now=NOW)
    validate_review(value,c,lease['plan_hash'],c['source_sha256'])


@pytest.mark.parametrize('fault',['unapproved','pending','history'])
def test_fee_refresh_cannot_hide_other_or_unsettled_attempts(scope,fault):
    lease,c,request,fee=post_selection(scope,status='pending' if fault=='pending' else 'done',allowed=fault!='unapproved')
    if fault=='history':
        fee['operations'][0]['status']='changed';fee['sha256']=digest({k:v for k,v in fee.items() if k!='sha256'});c['ledger_sha256']=fee['sha256'];request['authorization_sha256']=authorization_hash(c)
    with pytest.raises(ValueError):api().development_review(lease,c,request,fee,now=NOW)
