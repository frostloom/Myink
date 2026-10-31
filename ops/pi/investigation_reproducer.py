"""Host-authorized isolated reproduction; output remains unapproved review input."""
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
from hashlib import sha256
import fcntl,os,re
from threading import Event
from .audit import AuditStore,_path,_plain,digest,encoded,require,strict_json,utc,hash_value
from .development_inputs import FIELDS as DEVELOPMENT_FIELDS,file_hash,ledger_snapshot,prepare_template
from .review_lease import _read,_new,_sync
from .diagnosis_launcher import _disjoint
from .investigation_evidence import inspect as inspect_research
from .plans import Plan
from .task_package import freeze as freeze_package
from .package_baseline import execute as run_baseline
from .review_dossier import compile_dossier

FIELDS=set('schema authority mode run_id root research_config_path research_config_sha256 checker_image_id check_seconds max_requests max_tools development_seconds behavior issued_at expires_at'.split())
CANONICAL=Path('/home/ubuntu/myink-pi-managed/reproductions')


def _policy(pp,pin,runner,clock):
    pp=_path(pp);_plain(pp);require(pp.stat().st_size<=65536);raw=pp.read_bytes();require(sha256(raw).hexdigest()==pin,'reproducer policy pin drift');p=strict_json(raw)
    require(isinstance(p,dict) and set(p)==FIELDS and p['schema']=='pi-investigation-reproducer-v1' and p['authority']=='isolated_reproducer' and p['mode'] in ('ACTUAL','SIMULATED'),'isolated reproducer host authority required')
    if p['mode']=='ACTUAL':require(runner is None and clock is None and pp.stat().st_uid==0 and pp.stat().st_mode&0o777==0o640 and pp.parent.stat().st_uid==0 and pp.parent.stat().st_mode&0o777==0o750,'ACTUAL root policy and no injected runner/clock required')
    else:require(callable(runner) and pp.stat().st_mode&0o777==0o600,'explicit simulated checker required')
    now=utc((clock or (lambda:datetime.now(timezone.utc)))());issued=utc(datetime.fromisoformat(p['issued_at']));expires=utc(datetime.fromisoformat(p['expires_at']))
    require(issued<=now<expires and expires-issued<=timedelta(hours=24),'reproducer policy expired or future')
    require(isinstance(p['run_id'],str) and re.fullmatch('[a-z0-9-]{1,60}',p['run_id']) and hash_value(p['research_config_sha256']))
    require(isinstance(p['checker_image_id'],str) and re.fullmatch('sha256:[0-9a-f]{64}',p['checker_image_id']))
    for key,maximum in (('check_seconds',90),('max_requests',100),('max_tools',256),('development_seconds',1800)):require(type(p[key]) is int and 1<=p[key]<=maximum,'bounded reproducer/development limits required')
    require(p['development_seconds']>=120 and isinstance(p['behavior'],str) and 0<len(p['behavior'])<=200)
    return p,now


def _gold(p,text):
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as out:out.write(text.encode());out.flush();os.fsync(out.fileno())
    _sync(p.parent)


def _template(root,p,c,task,baseline_request,outcome_path):
    report=task['baseline'];source=Path(root/'package/source');gold=root/'package/test.py'
    b=dict(id=p['run_id']+'-baseline',metric='fixed_test_failures',evidence_domain='code_regression',source_sha256=task['source_sha256'],test_sha256=task['test_sha256'],reproduction_sha256=digest(report),reproduction=report)
    b['config_hash']=digest({k:b[k] for k in ('source_sha256','test_sha256','reproduction_sha256')});_new(root/'functional-baseline.json',b)
    plan=Plan(task['problem'],'fixed_test_failures',1,.1,1,('fixed_test_errors','fixed_test_skips'),b['id'],b['config_hash'],'stability',tuple(task['files']),('fixed-cases',),'existing behavior only','discard unadopted candidate',min(10,p['max_requests']),120,p['behavior'],evidence_domain='code_regression');_new(root/'plan.json',asdict(plan))
    tc={k:c[k] for k in ('runtime_path','runtime_sha256','ledger_path','policy_path','policy_sha256','credential_path','credential_sha256','docker','endpoint','daemon_id','image_id')}
    tc.update(schema='pi-development-v1',run_id=p['run_id'],root=str(root/'development-output'),source_path=str(source),source_sha256=task['source_sha256'],ledger_sha256=ledger_snapshot(c['ledger_path'])['sha256'],plan_path=str(root/'plan.json'),plan_sha256=file_hash(root/'plan.json'),baseline_path=str(root/'functional-baseline.json'),baseline_sha256=file_hash(root/'functional-baseline.json'),test_path=str(gold),test_sha256=task['test_sha256'],test_cases=task['test_cases'],review_path=str(root/'pending-review.json'),review_sha256='0'*64,checker_image_id=p['checker_image_id'],max_requests=p['max_requests'],max_tools=p['max_tools'],deadline_seconds=p['development_seconds'])
    require(set(tc)==DEVELOPMENT_FIELDS);target=root/'development-template.json';_new(target,tc);prepare_template(target)
    dossier=compile_dossier(target,file_hash(target),baseline_request,file_hash(baseline_request),outcome_path,file_hash(outcome_path));_new(root/'review-dossier.json',dossier)
    return str(target),str(root/'review-dossier.json')


def _audit(c,p,now,policy_sha256,result,error=None):
    event=dict(kind='test',status='failed' if result['eligible_for_review'] else 'no_change' if result['status']=='no_task' else 'blocked',run_id=p['run_id'],occurred_at=now.isoformat(),summary='Fixed isolated baseline only; reproduced assertion failures require independent review, not execution or release permission.',details=dict(reference='investigation.reproduction.v1',decision=result['status'],next_action='independent_review_required' if result['eligible_for_review'] else 'no_development_authority'),version=dict(policy_sha256=policy_sha256),changes=[],evidence=[dict(kind='authenticated_research_config',sha256=p['research_config_sha256'],verified=True,evidence_domain='offline' if p['mode']=='ACTUAL' else 'synthetic')],followups=[],mode=p['mode'],evidence_domain='offline' if p['mode']=='ACTUAL' else 'synthetic')
    event['details'].update(test_id=p['run_id']+'-baseline')
    if result['baseline_outcome_path'] is not None:
        outcome,pin=_read(result['baseline_outcome_path']);report=outcome.get('checker_report')
        if isinstance(report,dict):
            event['details'].update({target:report.get(source) for target,source in (('test_total','tests'),('test_failures','failures'),('test_errors','errors'),('test_skipped','skipped'))})
        event['evidence'].append(dict(kind='fixed_baseline_outcome',sha256=pin,verified=outcome.get('verified') is True,evidence_domain=event['evidence_domain']))
    if error is not None:event.update(status='blocked');event['details'].update(decision='host_guard_failed',reason=type(error).__name__,next_action='no_replay')
    audit=AuditStore(c['audit_path']);audit.append(p['run_id']+':reproduction',event);audit.export(c['export_root'])


def execute(policy_path,policy_sha256,*,runner=None,clock=None,cancel=None):
    cancel=Event() if cancel is None else cancel
    require(not cancel.is_set(),'reproduction cancelled before claim')
    p,now=_policy(policy_path,policy_sha256,runner,clock);c,pin=_read(p['research_config_path'],65536);require(pin==p['research_config_sha256'],'research config binding drift')
    lockpath=_path(c['ledger_path']).with_suffix('.tools.lock');_plain(lockpath)
    with lockpath.open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        proof=inspect_research(p['research_config_path'],p['research_config_sha256'],clock=clock);c=proof['config'];proposal=proof['proposal'];require(c['mode']==p['mode'],'reproducer mode drift')
        root=_path(p['root']);require(root.name=='repro-'+proof['material']['context']['research_fingerprint'] and not root.exists() and root.parent.is_dir() and root.parent.stat().st_mode&0o777==0o700,'fresh permanent reproducer claim required')
        if p['mode']=='ACTUAL':require(root.parent==CANONICAL,'ACTUAL permanent reproduction claims required')
        protected=[_path(policy_path),_path(c['root']),*[_path(c[k]) for k in c if k.endswith('_path') and k!='audit_path'],_path(c['ledger_path']).parent]
        outputs=(root,_path(c['audit_path']),_path(c['export_root']),*[_path(c['audit_path']+s) for s in ('-journal','-wal','-shm')])
        for index,out in enumerate(outputs):
            for other in outputs[index+1:]:_disjoint(out,other)
            for item in protected:_disjoint(out,item)
        require(not cancel.is_set(),'reproduction cancelled before claim')
        root.mkdir(mode=0o700);_sync(root.parent);_new(root/'intent.json',dict(schema='pi-reproduction-intent-v1',policy_sha256=policy_sha256,research_config_sha256=p['research_config_sha256'],research_artifact_pins=proof['artifact_pins']))
        result=dict(schema='pi-reproduction-result-v1',status='no_task',eligible_for_review=False,model_requests=0,template_path=None,dossier_path=None,baseline_outcome_path=None)
        try:
            if proposal['decision']=='task':
                _gold(root/'untrusted-test.py',proposal['test_source'])
                request=dict(schema='pi-task-package-v1',task_id=p['run_id'],problem=proposal['problem'],source_path=c['source_path'],source_sha256=c['source_sha256'],test_path=str(root/'untrusted-test.py'),test_sha256=file_hash(root/'untrusted-test.py'),files=proposal['files'],root=str(root/'package'));_new(root/'package-request.json',request);freeze_package(root/'package-request.json')
                draft=root/'package/task-draft.json';br=dict(schema='pi-package-baseline-request-v1',baseline_id=p['run_id']+'-baseline',draft_path=str(draft),draft_sha256=file_hash(draft),root=str(root/'baseline'),docker=c['docker'],endpoint=c['endpoint'],daemon_id=c['daemon_id'],checker_image_id=p['checker_image_id'],deadline_seconds=p['check_seconds']);_new(root/'baseline-request.json',br)
                require(file_hash(policy_path)==policy_sha256,'reproducer revoked before checker');inspect_research(p['research_config_path'],p['research_config_sha256'],clock=clock)
                (runner or run_baseline)(root/'baseline-request.json',cancel=cancel);outcome_path=root/'baseline/outcome.json';outcome,_=_read(outcome_path);result['baseline_outcome_path']=str(outcome_path)
                if outcome['verified'] is True and outcome['eligible_for_selection'] is True:
                    report=outcome['checker_report'];require(report['errors']==report['skipped']==0 and report['failures']>=1 and not report['load_error'],'assertion failure only')
                    result['template_path'],result['dossier_path']=_template(root,p,c,outcome['catalog'][0],root/'baseline-request.json',outcome_path);result.update(status='reproduced',eligible_for_review=True)
                else:result['status']='not_reproduced'
            require(not cancel.is_set(),'reproduction cancelled')
            _policy(policy_path,policy_sha256,runner,clock);require(ledger_snapshot(c['ledger_path'])==proof['fee'],'fixed reproduction changed original fees')
            inspect_research(p['research_config_path'],p['research_config_sha256'],clock=clock)
        except Exception as error:
            _new(root/'failure.json',dict(failure_class=type(error).__name__));_audit(c,p,now,policy_sha256,result,error);raise
        _audit(c,p,now,policy_sha256,result);_new(root/'receipt.json',result);return result
