"""Finite host-approved diagnostic queue, deduplicated by actual evidence.

This standard-library supervisor cannot mint execution permits. New unapproved
observations create investigation records only. Pending claims freeze all work.
"""
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import fcntl,os,sqlite3,stat
from .audit import AuditStore,DB_VERSION,_path,_plain,digest,encoded,hash_value,require,strict_json,utc
from .audit_export import _publish
from .development_inputs import file_hash,ledger_snapshot
from .live_diagnosis import inspect_observation
from .live_observer import _load as observer_load

FIELDS=set('schema mode root lock_path ledger_path legacy_unknown_ids observer_config_path observer_config_sha256 observer_controller_sha256 audit_path export_root entries'.split())
ENTRY=set('config_path config_sha256 evidence_fingerprint'.split())
CANONICAL=Path('/home/ubuntu/myink-pi-managed/state/ledger.sqlite')


def _read(p,maximum=1048576):
    p=_path(p);_plain(p);require(p.stat().st_size<=maximum,'bounded supervisor input required');return p.read_bytes()


def _directory(p):
    p=_path(p);require(p.is_dir() and stat.S_IMODE(p.stat().st_mode)==0o700,'private supervisor directory required');return p


def _apart(a,b):
    a,b=_path(a),_path(b);require(not a.is_relative_to(b) and not b.is_relative_to(a),'supervisor output/input overlap')


def _load(p,pin,runner,clock):
    p=_path(p);raw=_read(p);require(hash_value(pin) and file_hash(p)==pin,'supervisor registry drift')
    c=strict_json(raw);require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-diagnosis-registry-v1','strict supervisor registry required')
    require(c['mode'] in ('ACTUAL','SIMULATED'))
    if c['mode']=='ACTUAL':
        require(runner is None and clock is None,'ACTUAL supervisor forbids injected execution')
        require(p.stat().st_uid==0 and stat.S_IMODE(p.stat().st_mode)==0o640 and p.parent.stat().st_uid==0 and stat.S_IMODE(p.parent.stat().st_mode)==0o750,'root supervisor registry required')
        require(_path(c['ledger_path'])==CANONICAL,'original canonical ledger required')
    else:require(callable(runner) and stat.S_IMODE(p.stat().st_mode)==0o600 and _directory(p.parent))
    require(hash_value(c['observer_config_sha256']) and hash_value(c['observer_controller_sha256']))
    require(isinstance(c['legacy_unknown_ids'],list) and len(c['legacy_unknown_ids'])<=32 and all(isinstance(x,str) for x in c['legacy_unknown_ids']) and len(set(c['legacy_unknown_ids']))==len(c['legacy_unknown_ids']))
    root=_directory(c['root']);audit=_path(c['audit_path']);export=_path(c['export_root']);_directory(audit.parent);_directory(export.parent)
    if export.exists():_directory(export)
    _plain(audit)
    with closing(sqlite3.connect(audit.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:require(db.execute('PRAGMA user_version').fetchone()[0]==DB_VERSION,'dedicated audit required')
    require(isinstance(c['entries'],list) and len(c['entries'])<=32,'finite approved queue required');seen=set()
    _,observer_config,_,observation_root,*_=observer_load(c['observer_config_path'])
    require(observer_config['mode']==c['mode'])
    inputs=[p,observation_root,*[_path(c[k]) for k in ('lock_path','ledger_path','observer_config_path')],_path(c['ledger_path']).parent]
    for e in c['entries']:
        require(isinstance(e,dict) and set(e)==ENTRY and hash_value(e['config_sha256']) and hash_value(e['evidence_fingerprint']))
        require(e['evidence_fingerprint'] not in seen,'one permit per fingerprint');seen.add(e['evidence_fingerprint']);inputs.append(_path(e['config_path']))
        require(file_hash(e['config_path'])==e['config_sha256'],'approved diagnosis config drift')
        launch=strict_json(_read(e['config_path']))
        for key in ('runtime_path','ledger_path','policy_path','credential_path','observer_config_path','observation_receipt_path','evidence_path','memory_path','permit_path'):
            inputs.append(_path(launch[key]))
        _apart(root,launch['root']);_apart(audit,launch['root']);_apart(export,launch['root'])
    for output in (root,audit,export,*[_path(str(audit)+suffix) for suffix in ('-journal','-wal','-shm')]):
        for item in inputs:_apart(output,item)
    _apart(root,audit);_apart(root,export);_apart(audit,export)
    _plain(_path(c['lock_path']));return c


def _unknown(snapshot):
    return {r['operation_id'] for r in snapshot['operations'] if r['kind']=='model-attempt' and (r['status']!='done' or strict_json(r['evidence'] or '{}').get('usage_known') is not True)}


def _cached(root):
    if not (root/'receipt.json').exists():return dict(status='uncertain')
    receipt=strict_json(_read(root/'receipt.json'));require(isinstance(receipt,dict) and set(receipt)=={'schema','fingerprint','config_sha256','status','outcome_sha256','receipt_sha256'} and receipt['schema']=='pi-diagnosis-claim-v1')
    require(root.name==receipt['fingerprint'] and hash_value(receipt['config_sha256']) and hash_value(receipt['outcome_sha256']))
    core={k:v for k,v in receipt.items() if k!='receipt_sha256'};require(digest(core)==receipt['receipt_sha256'] and file_hash(root/'outcome.json')==receipt['outcome_sha256'],'diagnosis claim receipt drift')
    require(receipt['status'] in ('passed','failed','blocked','uncertain'));return receipt


def _investigation(c,e,now):
    audit=AuditStore(c['audit_path']);record=dict(kind='plan',status='blocked',run_id=e['observation_run_id'],occurred_at=now.isoformat(),summary='Gather source-bound reproducer and independent review; diagnosis is not repair approval.',
        details=dict(decision='investigate',reason=','.join(e['gaps']) or 'no_actionable_signal',next_action='source_bound_reproducer_then_independent_review'),version=dict(source_commit=e['source_commit']),changes=[],
        evidence=[dict(kind='diagnostic_evidence',sha256=e['evidence_fingerprint'],verified=True,evidence_domain=e['evidence_domain'])],followups=[],mode=c['mode'],evidence_domain=e['evidence_domain'])
    key='investigation:'+e['observation_run_id']
    if not any(event['record_key']==key for event in audit.events(run_id=e['observation_run_id'])):audit.append(key,record)
    audit.export(c['export_root'])


def run(registry_path,expected_registry_sha256,*,runner=None,clock=None):
    c=_load(registry_path,expected_registry_sha256,runner,clock);root=Path(c['root']);out=dict(schema='pi-diagnosis-tick-v1',mode=c['mode'],status='blocked',model_requests=0,development_dispatches=0)
    with Path(c['lock_path']).open('rb') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return dict(out,status='lock_busy')
        if (root/'freeze.json').exists():_read(root/'freeze.json');return out
        claims={}
        children=list(root.iterdir());require(len(children)<=4096,'bounded diagnostic history required')
        for child in children:
            require(hash_value(child.name) and child.is_dir(),'unexpected supervisor state');_directory(child);cached=_cached(child)
            if cached['status'] in ('uncertain','blocked'):return dict(out,status=cached['status'])
            claims[child.name]=cached
        before=ledger_snapshot(c['ledger_path'])
        if _unknown(before)!=set(c['legacy_unknown_ids']):
            _publish(root/'freeze.json',encoded(dict(reason='new_unknown_billing',model_requests=0)),immutable=True);return out
        _,oc,_,base,*_=observer_load(c['observer_config_path']);require(oc['mode']==c['mode'])
        candidates=[p for p in base.iterdir() if p.is_dir() and (p/'receipt.json').exists()]
        require(0<len(candidates)<=4096,'bounded completed observation required')
        latest=max(candidates,key=lambda p:p.name)
        evidence=inspect_observation(c['observer_config_path'],c['observer_config_sha256'],latest/'receipt.json',expected_controller_sha256=c['observer_controller_sha256'],clock=clock)
        fingerprint=evidence['evidence_fingerprint'];out['evidence_fingerprint']=fingerprint
        if fingerprint in claims:return dict(out,status='cached',previous_status=claims[fingerprint]['status'])
        now=utc((clock or (lambda:datetime.now(timezone.utc)))());_investigation(c,evidence,now)
        entry=next((e for e in c['entries'] if e['evidence_fingerprint']==fingerprint),None)
        if entry is None:return dict(out,status='no_permit')
        require(file_hash(entry['config_path'])==entry['config_sha256'],'approved diagnosis config drift')
        config=strict_json(_read(entry['config_path']));require(config['mode']==c['mode'] and config['ledger_path']==c['ledger_path'] and config['audit_path']==c['audit_path'] and config['export_root']==c['export_root'] and config['observer_config_path']==c['observer_config_path'] and config['observer_config_sha256']==c['observer_config_sha256'] and config['observer_controller_sha256']==c['observer_controller_sha256'],'approved diagnosis scope drift')
        frozen=strict_json(_read(config['evidence_path']));require(frozen['evidence_fingerprint']==fingerprint,'approved evidence drift')
        require(file_hash(registry_path)==expected_registry_sha256,'registry revoked before claim')
        claim=root/fingerprint;claim.mkdir(mode=0o700);fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        _publish(claim/'intent.json',encoded(dict(fingerprint=fingerprint,config_sha256=entry['config_sha256'],registry_sha256=expected_registry_sha256)),immutable=True)
        try:
            require(file_hash(registry_path)==expected_registry_sha256,'registry revoked before execution')
            if runner is None:
                # Paid imports only after host authorization and durable once-only claim.
                from .diagnosis_launcher import execute
                result=execute(entry['config_path'],expected_config_sha256=entry['config_sha256'])
            else:result=runner(entry['config_path'],entry['config_sha256'])
            require(isinstance(result,dict) and result['schema']=='pi-diagnosis-result-v1' and result['mode']==c['mode'] and result['evidence_fingerprint']==fingerprint and result['run_id']==config['run_id'])
            require(type(result['verified']) is bool and type(result['closed_verified']) is bool and type(result['new_unknown']) is int and type(result['new_attempts']) is int and 0<=result['new_attempts']<=1)
            require(0<=result['new_unknown']<=result['new_attempts'] and (not result['verified'] or result['closed_verified'] and result['new_unknown']==0 and result['new_attempts']==1),'inconsistent diagnosis success')
            out['model_requests']=result['new_attempts'];out['status']='passed' if result['verified'] else 'failed' if result['closed_verified'] else 'blocked'
            if not result['closed_verified'] or result['new_unknown']!=0:
                _publish(root/'freeze.json',encoded(dict(reason='unverified_paid_execution',fingerprint=fingerprint)),immutable=True)
        except Exception as error:
            result=dict(failure_class=type(error).__name__);out['status']='uncertain'
            _publish(root/'freeze.json',encoded(dict(reason='interrupted_paid_execution',fingerprint=fingerprint)),immutable=True)
        _publish(claim/'outcome.json',encoded(result),immutable=True)
        receipt=dict(schema='pi-diagnosis-claim-v1',fingerprint=fingerprint,config_sha256=entry['config_sha256'],status=out['status'],outcome_sha256=file_hash(claim/'outcome.json'))
        receipt['receipt_sha256']=digest(receipt);_publish(claim/'receipt.json',encoded(receipt),immutable=True);return out
