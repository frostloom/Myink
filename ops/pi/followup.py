"""Host-approved fixed regression only. Audit plans cannot authorize execution."""
from contextlib import closing
from datetime import datetime,time,timezone
from hashlib import sha256
from pathlib import Path
import fcntl
import os
import re
import sqlite3
import stat
import time as elapsed
from zoneinfo import ZoneInfo
from .audit import AuditStore,DB_VERSION,_path,_plain,digest,encoded,hash_value,name,require,strict_json,utc
from .audit_export import _publish
from .development_inputs import file_hash,tree_hash,ledger_snapshot
from .unit_feedback import REPORT_FIELDS,validate_report

FIELDS=set('schema mode root audit_path export_root lock_path billing_path manager_path entries'.split())
ENTRY_FIELDS=set('test_id run_id scheduled_for candidate_path candidate_sha256 source_path source_sha256 test_path test_sha256 test_cases review_path review_sha256 checker'.split())
CHECKER_FIELDS=set('docker endpoint daemon_id checker_image_id'.split())
SHANGHAI=ZoneInfo('Asia/Shanghai')


def _read(p,maximum=1048576):
    p=_path(p);_plain(p);require(p.stat().st_size<=maximum,'bounded followup file required')
    raw=p.read_bytes();require(len(raw)<=maximum,'bounded followup file required');return raw


def _directory(p):
    p=_path(p);require(p.is_dir() and stat.S_IMODE(p.stat().st_mode)==0o700,'private followup directory required');return p


def _load(registry_path,expected,runner,clock):
    p=_path(registry_path);raw=_read(p);require(hash_value(expected) and sha256(raw).hexdigest()==expected,'registry digest mismatch')
    c=strict_json(raw);require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-followup-registry-v1','strict followup registry required')
    require(c['mode'] in ('ACTUAL','SIMULATED'))
    if c['mode']=='ACTUAL':
        require(runner is None and clock is None,'ACTUAL followup prohibits injected runner/clock')
        require(p.stat().st_uid==0 and stat.S_IMODE(p.stat().st_mode)==0o640 and p.parent.stat().st_uid==0
            and stat.S_IMODE(p.parent.stat().st_mode)==0o750,'root-owned fixed registry required')
    else:
        require(callable(runner),'SIMULATED followup requires callback')
        require(stat.S_IMODE(p.stat().st_mode)==0o600);_directory(p.parent)
    root=_directory(c['root']);audit=_path(c['audit_path']);export=_path(c['export_root']);_directory(audit.parent);_directory(export.parent)
    if export.exists():_directory(export)
    require(audit.exists(),'existing dedicated audit required')
    with closing(sqlite3.connect(audit.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        require(db.execute('PRAGMA user_version').fetchone()[0]==DB_VERSION,'dedicated audit schema required')
    for key in ('lock_path','billing_path','manager_path'):_plain(_path(c[key]))
    require(isinstance(c['entries'],list) and 0<len(c['entries'])<=32,'bounded followup entries required')
    inputs=[p,audit,export,*[_path(c[k]) for k in ('lock_path','billing_path','manager_path')]];seen=set()
    for e in c['entries']:
        require(isinstance(e,dict) and set(e)==ENTRY_FIELDS,'strict fixed entry required')
        require(name(e['test_id']) and name(e['run_id']) and (e['test_id'],e['run_id']) not in seen);seen.add((e['test_id'],e['run_id']))
        require(isinstance(e['scheduled_for'],str));utc(datetime.fromisoformat(e['scheduled_for']))
        for key in ('candidate_sha256','source_sha256','test_sha256','review_sha256'):require(hash_value(e[key]))
        for key in ('candidate_path','source_path','test_path','review_path'):inputs.append(_path(e[key]))
        cases=e['test_cases'];require(isinstance(cases,list) and 0<len(cases)<=200 and len(set(cases))==len(cases)
            and all(isinstance(case,str) and re.fullmatch(r'fixed_development_tests\.[A-Za-z0-9_.]{1,180}',case) for case in cases),'fixed cases required')
        checker=e['checker'];require(isinstance(checker,dict) and set(checker)==CHECKER_FIELDS)
        require(isinstance(checker['docker'],str) and _path(checker['docker']).is_absolute())
        require(isinstance(checker['endpoint'],str) and re.fullmatch(r'unix:///[^\s?,#\x00]+',checker['endpoint']))
        require(isinstance(checker['daemon_id'],str) and re.fullmatch('[A-Za-z0-9:_-]{1,128}',checker['daemon_id']))
        require(isinstance(checker['checker_image_id'],str) and re.fullmatch('sha256:[0-9a-f]{64}',checker['checker_image_id']))
    for item in inputs:require(not root.is_relative_to(item) and not item.is_relative_to(root),'followup outputs and inputs overlap')
    protected=[p,*[_path(c[k]) for k in ('lock_path','billing_path','manager_path')]]
    protected.extend(_path(c[k]).parent for k in ('billing_path','manager_path'))
    protected.extend(_path(e[k]) for e in c['entries'] for k in ('candidate_path','source_path','test_path','review_path'))
    for destination in (root,export,audit):
        for item in protected:
            require(not destination.is_relative_to(item) and not item.is_relative_to(destination),'writable destination overlaps protected input/state')
    require(not export.is_relative_to(audit) and not audit.is_relative_to(export),'audit database and export overlap')
    require(len({c[k] for k in ('audit_path','billing_path','manager_path','lock_path')})==4,'separate states required')
    return c


def _pins(e):
    require(tree_hash(_path(e['candidate_path']))==e['candidate_sha256'],'candidate drift')
    require(tree_hash(_path(e['source_path']))==e['source_sha256'],'source drift')
    for key,pin in (('test_path','test_sha256'),('review_path','review_sha256')):
        require(sha256(_read(e[key])).hexdigest()==e[pin],'fixed gold/review drift')


def _planned(audit,e):
    return any(plan['test_id']==e['test_id'] and plan['target_run_id']==e['run_id'] and plan['target_version_sha256']==e['candidate_sha256']
        and utc(datetime.fromisoformat(plan['scheduled_for']))==utc(datetime.fromisoformat(e['scheduled_for'])) and plan['status']=='planned'
        for event in audit.events() for plan in event['followups'])


def _cached(root,e,entry_sha):
    if not (root/'intent.json').exists():return dict(test_id=e['test_id'],run_id=e['run_id'],status='uncertain',reason='incomplete_directory_claim_no_replay')
    intent=strict_json(_read(root/'intent.json'));require(intent['entry_sha256']==entry_sha,'followup claim conflict')
    if not (root/'receipt.json').exists():return dict(test_id=e['test_id'],run_id=e['run_id'],status='uncertain',reason='unfinished_claim_no_replay')
    result=strict_json(_read(root/'receipt.json'));proof=result.pop('receipt_sha256',None)
    require(hash_value(proof) and digest(result)==proof and result['entry_sha256']==entry_sha,'followup receipt drift')
    require(sha256(_read(root/'outcome.json')).hexdigest()==result['outcome_sha256'],'followup outcome drift')
    result['receipt_sha256']=proof;return result


def _isolated_check(e,root,write):
    from threading import Event,Timer
    from .development_launcher import _fixed_check,Limits,OwnedHosts
    cancel=Event();limits=Limits(1,1,90,cancel);owners=OwnedHosts(cancel,write)
    timer=Timer(90,cancel.set);timer.daemon=True;timer.start()
    result=None
    try:
        checker=dict(e['checker'],test_path=e['test_path'],test_sha256=e['test_sha256'],test_cases=e['test_cases'])
        result=_fixed_check(checker,Path(e['candidate_path']),root/'check',limits,write,owners)
    finally:
        try:
            cleanup=owners.finish();write('final-sweep-cleanup.json',cleanup)
        finally:timer.cancel()
    limits.alive();require(not owners.failed,'owned checker cleanup failed')
    require(tree_hash(root/'check/src')==tree_hash(Path(e['candidate_path'])/'src')
        and file_hash(root/'check/test.py')==e['test_sha256'],'actual checker input copy drift')
    result['cleanup']=cleanup
    return result


def _execute(c,e,root,registry_sha,now,runner,audit,registry_path,now_fn):
    started=elapsed.monotonic();occurred=now
    entry_sha=digest(e);root.mkdir(mode=0o700)
    fd=os.open(root.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
    _publish(root/'intent.json',encoded(dict(schema='pi-followup-intent-v1',entry_sha256=entry_sha,registry_sha256=registry_sha,occurred_at=now.isoformat())),immutable=True)
    def write(filename,value):_publish(root/filename,encoded(value),immutable=True)
    before={key:ledger_snapshot(c[key]) for key in ('billing_path','manager_path')}
    version=dict(candidate_sha256=e['candidate_sha256'],policy_sha256=registry_sha)
    domain='offline' if c['mode']=='ACTUAL' else 'synthetic'
    def event(kind,status,details,proof=None):
        return dict(kind=kind,status=status,run_id=e['run_id'],occurred_at=occurred.isoformat(),summary='Host-approved fixed regression; no model or product release.',details=details,version=version,changes=[],evidence=proof or [],followups=[],mode=c['mode'],evidence_domain=domain)
    key='followup-'+digest(dict(run_id=e['run_id'],test_id=e['test_id'],candidate=e['candidate_sha256']))
    audit.append(key+':start',event('tool','running',dict(test_id=e['test_id'],tool_name='fixed_checker',model_requests=0)))
    status='blocked';report=None;failure=None;verified=False
    try:
        report=(runner or _isolated_check)(e,root,write)
        require(isinstance(report,dict) and set(report)==REPORT_FIELDS|{'attach_returncode','container_id','cleanup'},'fixed checker result required')
        validate_report({k:report[k] for k in REPORT_FIELDS},report['attach_returncode'],e['test_cases'])
        require(not report['load_error'] and report['errors']==report['skipped']==0,'complete fixed checker required')
        cleanup=report['cleanup'];require(isinstance(cleanup,list) and cleanup and all(x.get('removed') is True and type(x.get('exit_code')) is int and x['exit_code']==report['attach_returncode'] for x in cleanup)
            and any(x.get('container_id')==report['container_id'] for x in cleanup),'checker cleanup unverified')
        _pins(e)
        require(all(ledger_snapshot(c[k])==v for k,v in before.items()),'original state changed during fixed test')
        require(sha256(_read(registry_path)).hexdigest()==registry_sha,'registry changed during fixed test')
        finished=utc(now_fn());end=finished.astimezone(SHANGHAI)
        require(finished>=now and end.date()==now.astimezone(SHANGHAI).date() and end.time().replace(tzinfo=None)<time(6)
            and elapsed.monotonic()-started<300,'fixed test crossed deadline/maintenance end')
        verified=True;status='passed' if report['passed'] else 'failed'
    except Exception as error:failure=type(error).__name__
    occurred=utc(now_fn())
    outcome=dict(status=status,verified=verified,failure_class=failure,report=report,model_requests=0)
    write('outcome.json',outcome);outcome_sha=sha256((root/'outcome.json').read_bytes()).hexdigest()
    proof=[dict(kind='fixed_followup_outcome',sha256=outcome_sha,verified=verified,evidence_domain=domain)]
    details=dict(test_id=e['test_id'],tool_name='fixed_checker',model_requests=0,known_cost_microyuan=0,duration_ms=(elapsed.monotonic()-started)*1000,result_summary=failure or status)
    if verified:details.update(test_total=report['tests'],test_failures=report['failures'],test_errors=report['errors'],test_skipped=report['skipped'])
    audit.append(key+':tool',event('tool',status,details,proof));audit.append(key+':test',event('test',status,details,proof))
    audit.append(key+':version',event('version','no_change',dict(reference='fixed_followup_registry',test_id=e['test_id']),proof))
    audit.export(c['export_root'])
    result=dict(schema='pi-followup-result-v1',entry_sha256=entry_sha,test_id=e['test_id'],run_id=e['run_id'],candidate_sha256=e['candidate_sha256'],status=status,verified=verified,mode=c['mode'],outcome_sha256=outcome_sha,occurred_at=occurred.isoformat(),model_requests=0)
    result['receipt_sha256']=digest(result);write('receipt.json',result);return result


def run_due(registry_path,expected_registry_sha256,*,clock=None,runner=None):
    c=_load(registry_path,expected_registry_sha256,runner,clock)
    now_fn=clock or (lambda:datetime.now(timezone.utc));now=utc(now_fn());local=now.astimezone(SHANGHAI)
    result=dict(schema='pi-followup-tick-v1',mode=c['mode'],status='planned',results=[],model_requests=0)
    due=[e for e in c['entries'] if utc(datetime.fromisoformat(e['scheduled_for']))<=now]
    if not due:return result
    with open(c['lock_path'],'rb') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:result['status']='lock_busy';return result
        audit=AuditStore(c['audit_path'])
        for e in due:
            root=Path(c['root'])/('test-'+digest(dict(run=e['run_id'],test=e['test_id'],candidate=e['candidate_sha256'])))
            if root.exists():
                _directory(root);cached=_cached(root,e,digest(e));result['results'].append(cached)
                if cached['status'] in ('blocked','uncertain'):break
                continue
            if not time(2)<=local.time().replace(tzinfo=None)<time(5,30):result['status']='outside_window';return result
            require(_planned(audit,e),'matching reserved audit plan required')
            _pins(e)
            for key in ('billing_path','manager_path'):ledger_snapshot(c[key])
            require(sha256(_read(registry_path)).hexdigest()==expected_registry_sha256,'registry changed before claim')
            admitted=utc(now_fn());admit_local=admitted.astimezone(SHANGHAI)
            if not time(2)<=admit_local.time().replace(tzinfo=None)<time(5,30):result['status']='outside_window';return result
            require(admitted>=utc(datetime.fromisoformat(e['scheduled_for'])),'followup no longer due')
            result['results'].append(_execute(c,e,root,expected_registry_sha256,admitted,runner,audit,registry_path,now_fn))
            break  # One new bounded check per tick; cached facts never start Docker.
    statuses={x['status'] for x in result['results']}
    result['status']=next((status for status in ('uncertain','blocked','failed') if status in statuses),'completed')
    return result
