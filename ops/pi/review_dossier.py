"""Frozen input for a fresh independent reviewer; never approval or execution.

The private semantic hash excludes only latest fee checkpoint, a bounded lower
remaining deadline and the independently published review location/hash.
"""
from pathlib import Path
from hashlib import sha256
from dataclasses import asdict
import re
from .audit import _plain,digest,encoded,hash_value,require,strict_json
from .development_inputs import FIELDS,authorization_hash,file_hash,path,prepare_template,tree_hash
from .package_baseline import FIELDS as REQUEST_FIELDS,_draft,_stable_inputs
from .maintenance_handoff import _catalog
from .provider_config import load_credentials
from .unit_feedback import REPORT_FIELDS,validate_report

OUTCOME=set('schema verified baseline_id request_sha256 draft_sha256 source_sha256 test_sha256 check_passed eligible_for_selection catalog catalog_rejection checker_report cleanup failure_class cleanup_failure_class requires'.split())
VOLATILE={'ledger_sha256','deadline_seconds','review_path','review_sha256'}
MAX_MODEL_BYTES=24000


def _read(value,maximum=1048576):
    p=path(value,private=True);_plain(p);require(p.stat().st_size<=maximum,'bounded private review input required')
    raw=p.read_bytes();require(len(raw)<=maximum,'bounded private review input required');return raw


def _pin(value,expected):
    require(hash_value(expected),'review input pin required');raw=_read(value)
    require(sha256(raw).hexdigest()==expected,'review input drift');return strict_json(raw)


def semantic_hash(config,*,deadline_ceiling=None):
    require(isinstance(config,dict) and set(config)==FIELDS,'strict development semantics required')
    ceiling=config['deadline_seconds'] if deadline_ceiling is None else deadline_ceiling
    require(type(ceiling) is int and type(config['deadline_seconds']) is int and 1<=config['deadline_seconds']<=ceiling<=1800,'review deadline increase or invalid bound')
    return digest(dict(contract={k:v for k,v in config.items() if k not in VOLATILE},deadline_ceiling=ceiling))


def compile_dossier(template_path,template_sha256,baseline_request_path,baseline_request_sha256,outcome_path,outcome_sha256,*,expected_current_fee_sha256=None):
    frozen=_pin(template_path,template_sha256);c,policy,plan,baseline,*_=prepare_template(template_path,expected_current_fee_sha256=expected_current_fee_sha256)
    require(c==frozen and plan.evidence_domain=='code_regression','functional regression review required')
    request=_pin(baseline_request_path,baseline_request_sha256)
    require(isinstance(request,dict) and set(request)==REQUEST_FIELDS and request['schema']=='pi-package-baseline-request-v1','strict baseline request required')
    require(request['baseline_id']==baseline['id'] and type(request['deadline_seconds']) is int and 1<=request['deadline_seconds']<=300,'baseline identity/deadline drift')
    require(all(request[k]==c[k] for k in ('docker','endpoint','daemon_id','checker_image_id')),'baseline host binding drift')
    root=path(request['root']);require(root.is_dir() and root.stat().st_mode&0o777==0o700,'private completed baseline required')
    require(path(outcome_path,private=True)==root/'outcome.json','fixed baseline outcome required')
    draft=_draft(request['draft_path'],request['draft_sha256'])
    require(all(draft[k]==c[k] for k in ('source_path','source_sha256','test_path','test_sha256'))
        and draft['files']==list(plan.files) and draft['test_case_hints']==c['test_cases'],'draft/template identity drift')
    outcome=_pin(outcome_path,outcome_sha256)
    require(isinstance(outcome,dict) and set(outcome)==OUTCOME and outcome['schema']=='pi-package-baseline-outcome-v1','strict baseline outcome required')
    require(outcome['verified'] is True and outcome['eligible_for_selection'] is True and outcome['check_passed'] is False
        and outcome['failure_class'] is None and outcome['cleanup_failure_class'] is None and outcome['catalog_rejection'] is None
        and outcome['requires']==['fresh_run_identity','independent_reviews','current_runtime'],'verified isolated reproduction required')
    require(outcome['baseline_id']==request['baseline_id'] and outcome['request_sha256']==baseline_request_sha256
        and outcome['draft_sha256']==request['draft_sha256'] and outcome['source_sha256']==c['source_sha256']
        and outcome['test_sha256']==c['test_sha256'],'baseline provenance drift')
    tasks=_catalog(outcome['catalog']);require(len(tasks)==1,'one independently reviewed task required');task=tasks[0]
    require(task['task_id']==draft['task_id'] and task['problem']==draft['problem'] and task['files']==list(plan.files)
        and task['test_cases']==c['test_cases'] and task['source_sha256']==c['source_sha256'] and task['test_sha256']==c['test_sha256']
        and task['baseline']==baseline['reproduction'] and task['evidence_sha256']==baseline['reproduction_sha256'],'reproduced task/template drift')
    report=outcome['checker_report'];require(isinstance(report,dict) and set(report)==REPORT_FIELDS|{'attach_returncode','container_id'},'complete fixed checker report required')
    validate_report({k:report[k] for k in REPORT_FIELDS},report['attach_returncode'],c['test_cases'])
    require(not report['passed'] and not report['load_error'] and report['errors']==report['skipped']==0
        and all(report[k]==baseline['reproduction'][k] for k in baseline['reproduction']) and hash_value(report['container_id']),'actual assertion failure required')
    cleanup=outcome['cleanup'];require(isinstance(cleanup,list) and len(cleanup)==1 and isinstance(cleanup[0],dict)
        and cleanup[0].get('removed') is True and type(cleanup[0].get('exit_code')) is int and cleanup[0]['exit_code']==1
        and cleanup[0].get('container_id')==report['container_id'],'matching owned checker cleanup required')
    require(tree_hash(root/'check/src')==tree_hash(Path(c['source_path'])/'src') and file_hash(root/'check/test.py')==c['test_sha256'],'actual checked copy drift')
    source_files=[]
    for relative in plan.files:
        p=path(Path(c['source_path'])/relative);_plain(p);require(p.stat().st_size<=MAX_MODEL_BYTES,'review source exceeds complete-context bound')
        raw=p.read_bytes();source_files.append(dict(path=relative,sha256=sha256(raw).hexdigest(),text=raw.decode('utf-8')))
    gold_raw=_read(c['test_path'],MAX_MODEL_BYTES);require(sha256(gold_raw).hexdigest()==c['test_sha256'],'review gold text drift')
    gold=gold_raw.decode('utf-8');semantic=semantic_hash(c)
    model_view=dict(schema='pi-independent-review-input-v1',authority='recommendation_only',review_kind='pre_development',
        untrusted_material=True,online_improvement_proven=False,evidence_domain='code_regression',semantic_sha256=semantic,
        source_sha256=c['source_sha256'],test_sha256=c['test_sha256'],plan_hash=plan.plan_hash,baseline_outcome_sha256=outcome_sha256,
        task=dict(task_id=task['task_id'],problem=task['problem'],files=task['files'],test_cases=task['test_cases']),
        plan=asdict(plan),baseline=baseline['reproduction'],source_files=source_files,gold_source=gold)
    raw=encoded(model_view);require(len(raw)<=MAX_MODEL_BYTES,'review complete context exceeds wire bound')
    key=load_credentials(c['credential_path'],policy)['PLATFORM_MODEL_API_KEY']
    require(key not in raw.decode('ascii'),'credential literal in review material')
    combined='\n'.join([gold,*[f['text'] for f in source_files]])
    credential_name=r"\b[A-Za-z0-9_]*(?:api[_-]?key|access[_-]?token|password|secret)[A-Za-z0-9_]*"
    literal=r'''(?:["']?\s*:\s*["'][^"']+["']|(?:\s*:\s*[^=\n]{0,120})?\s*=\s*["'][^"']+["'])'''
    require(not re.search(credential_name+literal,combined,re.IGNORECASE)
        and not re.search(r'''[a-z][a-z0-9+.-]*://[^\s/'"<>]+:[^\s/'"<>]+@''',combined,re.IGNORECASE),'credential-shaped review material')
    # Recheck source/gold/policy/runtime/fee identities after reading all content.
    checked=prepare_template(template_path,expected_current_fee_sha256=expected_current_fee_sha256)[0];require(checked==c,'review template changed during compilation')
    _stable_inputs(baseline_request_path,baseline_request_sha256,request,draft)
    require(tree_hash(root/'check/src')==tree_hash(Path(c['source_path'])/'src') and file_hash(root/'check/test.py')==c['test_sha256'],'actual checked copy drift')
    require(all(file_hash(p)==expected for p,expected in ((template_path,template_sha256),(baseline_request_path,baseline_request_sha256),(outcome_path,outcome_sha256))), 'review input changed during compilation')
    require(all(file_hash(Path(c['source_path'])/f['path'])==f['sha256'] for f in source_files),'review source text drift')
    return dict(schema='pi-review-dossier-v1',authority='none',semantic_sha256=semantic,deadline_ceiling=c['deadline_seconds'],
        initial_authorization_sha256=authorization_hash(c),baseline_request_sha256=baseline_request_sha256,baseline_outcome_sha256=outcome_sha256,
        model_view=model_view,model_view_sha256=digest(model_view))
