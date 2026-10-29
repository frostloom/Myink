"""Readonly final diff/context compiler; pinned host receipts are not release authority.

The caller must separately authenticate the completed SDK/manager/fee provenance.
This compiler never imports candidate code or promotes a declared result to an
independent acceptance. Its output is input to a fresh recommendation-only role.
"""
from dataclasses import fields,asdict
from difflib import SequenceMatcher,unified_diff
from pathlib import Path
import re
from .audit import digest,encoded,require,hash_value,_plain
from .development_inputs import FIELDS as CONFIG,authorization_hash,file_hash,path,tree_hash,validate_review
from .review_dossier import _pin,MAX_MODEL_BYTES
from .investigation_inputs import _secrets
from .plans import Plan,validate_plan,check_diff
from .policy import load_policy
from .provider_config import load_credentials
from .unit_feedback import REPORT_FIELDS,validate_report

FIELDS=set('schema mode config_path config_sha256 result_sha256 phase_sha256 check_id check_sha256'.split())


def compile_dossier(request_path,request_sha256):
    q=_pin(request_path,request_sha256)
    require(isinstance(q,dict) and set(q)==FIELDS and q['schema']=='pi-candidate-review-request-v1' and q['mode'] in ('ACTUAL','SIMULATED'),'fixed candidate review request required')
    require(isinstance(q['check_id'],str) and re.fullmatch(r'check-[1-9][0-9]{0,2}',q['check_id']),'fixed completed checker identity required')
    c=_pin(q['config_path'],q['config_sha256']);require(isinstance(c,dict) and set(c)==CONFIG and c['schema']=='pi-development-v1','strict completed development config required')
    root=path(c['root']);require(root.is_dir() and root.stat().st_mode&0o777==0o700,'private completed development root required')
    pins={str(path(request_path)):request_sha256,str(path(q['config_path'])):q['config_sha256']}
    def pinned(p,pin=None):
        p=path(p,private=True);pin=file_hash(p) if pin is None else pin;v=_pin(p,pin);pins[str(p)]=pin;return v
    result=pinned(root/'result.json',q['result_sha256']);phase=pinned(root/'phase-verification.json',q['phase_sha256']);manifest=pinned(root/'manifest-private.json')
    require(manifest.get('config')==c,'completed manifest/config drift')
    require(result.get('verified') is True and result.get('run_id')==c['run_id'] and result.get('authorization_sha256')==authorization_hash(c)
        and all(result.get(k) is True for k in ('policy_restored','original_history_unchanged'))
        and not any(v is not None for k,v in result.items() if k.endswith('failure_class')),'unverified completed development')
    require(type(result.get('new_unknown')) is int and result['new_unknown']==0
        and type(result.get('new_attempts')) is int and 0<result['new_attempts']<=c['max_requests']
        and type(result.get('known_cost_microyuan')) is int and result['known_cost_microyuan']>=0,'unsettled completed development')
    cleanup=result.get('cleanup');require(isinstance(cleanup,list) and bool(cleanup) and all(isinstance(v,dict) and v.get('removed') is True and hash_value(v.get('container_id')) for v in cleanup),'completed owned cleanup required')
    require(phase.get('verified') is True and phase.get('mode')=='ACTUAL','verified fixed SDK phase required')
    source=path(c['source_path']);candidate=path(root/'candidate')
    require(result.get('candidate_path')==str(candidate) and hash_value(result.get('candidate_sha256')),'fixed candidate location required')
    require({p.name for p in source.iterdir()}=={p.name for p in candidate.iterdir()}=={'src'}
        and tree_hash(source)==c['source_sha256'] and tree_hash(candidate)==result['candidate_sha256'],'source/candidate drift')
    pinned(c['policy_path'],c['policy_sha256']);policy=load_policy(Path(c['policy_path']))
    require(not policy.live_enabled and not policy.server_daily_enabled and policy.input_bound_calibrated,'closed calibrated policy required')
    raw_plan=pinned(c['plan_path'],c['plan_sha256']);require(isinstance(raw_plan,dict) and set(raw_plan)=={f.name for f in fields(Plan)},'strict completed Plan required')
    plan=Plan(**{k:tuple(v) if k in ('guard_metrics','files','slice_ids','change_types') and isinstance(v,list) else v for k,v in raw_plan.items()})
    baseline=pinned(c['baseline_path'],c['baseline_sha256']);require(validate_plan(plan,baseline,policy).status=='done','invalid completed Plan')
    if plan.evidence_domain=='code_regression':require(baseline['source_sha256']==c['source_sha256'] and baseline['test_sha256']==c['test_sha256'],'functional baseline binding drift')
    review=pinned(c['review_path'],c['review_sha256']);validate_review(review,c,plan.plan_hash,c['source_sha256'])
    pinned(c['credential_path'],c['credential_sha256']);literal=load_credentials(c['credential_path'],policy)['PLATFORM_MODEL_API_KEY']
    gold=path(c['test_path'],private=True);_plain(gold);raw=gold.read_bytes();require(len(raw)<=MAX_MODEL_BYTES and file_hash(gold)==c['test_sha256'],'frozen gold drift');pins[str(gold)]=c['test_sha256'];gold_text=raw.decode('utf-8');_secrets(gold_text,literal)
    check=pinned(root/(q['check_id']+'-receipt.json'),q['check_sha256']);require(set(check)==REPORT_FIELDS|{'attach_returncode','container_id','cleanup'},'complete fixed checker receipt required')
    validate_report({k:check[k] for k in REPORT_FIELDS},check['attach_returncode'],c['test_cases'])
    require(check['passed'] is True and check['tests']>0 and check['failures']==check['errors']==check['skipped']==0 and not check['load_error'],'complete passing fixed inventory required')
    checked=root/q['check_id'];require(tree_hash(checked/'src')==tree_hash(candidate/'src') and file_hash(checked/'test.py')==c['test_sha256'],'green check belongs to another candidate/gold')
    require(isinstance(check['cleanup'],list) and len(check['cleanup'])==1 and check['cleanup'][0].get('container_id')==check['container_id'] and hash_value(check['container_id']) and check['cleanup'][0].get('removed') is True and type(check['cleanup'][0].get('exit_code')) is int and check['cleanup'][0]['exit_code']==0,'matching final checker cleanup required')
    names={p.relative_to(t).as_posix() for t in (source,candidate) for p in t.rglob('*') if p.is_file()};changes=[];diff=[];originals=[];finals=[]
    for relative in sorted(names):
        left=source/relative;right=candidate/relative
        same=left.is_file() and right.is_file() and file_hash(left)==file_hash(right)
        if not same:
            require(relative in plan.files and left.is_file() and right.is_file(),'candidate changes outside reviewed existing files')
            require(left.stat().st_size<=MAX_MODEL_BYTES and right.stat().st_size<=MAX_MODEL_BYTES,'bounded complete candidate context required')
            a=left.read_text();b=right.read_text();_secrets(a,literal);_secrets(b,literal)
            added=deleted=0
            for tag,i,j,k,l in SequenceMatcher(a=a.splitlines(),b=b.splitlines(),autojunk=False).get_opcodes():
                if tag!='equal':deleted+=j-i;added+=l-k
            changes.append(dict(path=relative,category='production',added=added,deleted=deleted));diff.extend(unified_diff(a.splitlines(),b.splitlines(),fromfile=relative,tofile=relative,lineterm=''))
        if relative in plan.files:
            require(left.is_file() and right.is_file() and max(left.stat().st_size,right.stat().st_size)<=MAX_MODEL_BYTES,'complete selected source required')
            a=left.read_text();b=right.read_text();_secrets(a,literal);_secrets(b,literal)
            originals.append(dict(path=relative,sha256=file_hash(left),text=a));finals.append(dict(path=relative,sha256=file_hash(right),text=b))
    require(changes and check_diff(plan,dict(plan_hash=plan.plan_hash,files=[x['path'] for x in changes],production_added=sum(x['added'] for x in changes),production_deleted=sum(x['deleted'] for x in changes),tracked_files=len(changes)),policy).status=='done','candidate diff violates frozen scope')
    view=dict(schema='pi-candidate-review-input-v1',authority='recommendation_only',review_kind='post_development',untrusted_material=True,online_improvement_proven=False,evidence_domain=plan.evidence_domain,source_sha256=c['source_sha256'],candidate_sha256=result['candidate_sha256'],test_sha256=c['test_sha256'],plan_hash=plan.plan_hash,plan=asdict(plan),baseline=baseline,source_files=originals,candidate_files=finals,gold_source=gold_text,diff='\n'.join(diff),changes=changes,final_check={k:check[k] for k in REPORT_FIELDS},development_result_sha256=q['result_sha256'])
    require(len(encoded(view))<=MAX_MODEL_BYTES,'complete final review context exceeds bound')
    require(all(file_hash(p)==pin for p,pin in pins.items()) and tree_hash(source)==c['source_sha256'] and tree_hash(candidate)==result['candidate_sha256'] and tree_hash(checked/'src')==tree_hash(candidate/'src') and file_hash(checked/'test.py')==c['test_sha256'],'candidate review inputs changed while reading')
    return dict(schema='pi-candidate-dossier-v1',authority='none',candidate_sha256=result['candidate_sha256'],model_view=view,model_view_sha256=digest(view),artifact_pins=pins)
