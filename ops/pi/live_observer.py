"""One bounded host observation. Audit data never admits models or publishes code."""
import argparse
from contextlib import closing
from dataclasses import dataclass,field
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import stat
from .audit import AuditStore,DB_VERSION,_path,_plain,_version,digest,encoded,hash_value,name,require,strict_json,utc
from .audit_export import _publish
from .metrics import collect_snapshot
from .psql_metrics import PsqlMetricsReader

FIELDS=set('schema mode root audit_path source identity interval_minutes lookback_hours minimum_samples'.split())
OPTIONAL={'export_root'}
RESULT_FIELDS=set('schema run_id mode config_sha256 controller_sha256 status evidence_domain observed_samples minimum_samples availability confounders snapshot_sha256 window automatic_execution export_published receipt_sha256'.split())
IDENTITY_FIELDS=set('deployment_id generation owner image_ids commit_sha schema_id config_hash'.split())
MAX_SNAPSHOT=1048576


@dataclass(frozen=True)
class ObservationIdentity:
    deployment_id:str|None=None
    generation:int|None=None
    owner:str|None=None
    image_ids:dict|None=None
    commit_sha:str|None=None
    schema_id:str|None=None
    config_hash:str|None=None
    schema_version:int=field(default=1,init=False)


def _read(p,maximum):
    p=_path(p);_plain(p);require(p.stat().st_size<=maximum,'bounded private observer input required')
    raw=p.read_bytes();require(len(raw)<=maximum,'observer input exceeds byte bound')
    return raw


def _private_directory(p):
    p=_path(p);require(p.is_dir() and stat.S_IMODE(p.stat().st_mode)==0o700,'private observer directory required');return p


def _identity(value):
    require(isinstance(value,dict) and set(value)<=IDENTITY_FIELDS,'strict observation identity required')
    for key,item in value.items():
        if item is None:continue
        if key=='generation':require(type(item) is int and item>0)
        elif key=='commit_sha':require(hash_value(item,40))
        elif key=='image_ids':require(isinstance(item,dict) and len(item)<=8 and all(name(k) and isinstance(v,str) and re.fullmatch('sha256:[0-9a-f]{64}',v) for k,v in item.items()))
        else:require(name(item))
    _version(dict(source_commit=value.get('commit_sha'),deployment_id=value.get('deployment_id'),generation=value.get('generation'),owner=value.get('owner'),image_ids=value.get('image_ids') or {}))
    for key in ('schema_id','config_hash'):
        if value.get(key) is not None:_version(dict(owner=value[key]))
    return ObservationIdentity(**value)


def _controller():
    files=('live_observer.py','metrics.py','metrics_query.py','metrics_sql.py','psql_metrics.py','audit.py','audit_export.py','contracts.py')
    return digest({p:sha256(_read(Path(__file__).parent/p,1048576)).hexdigest() for p in files})


def _load(config_path):
    p=_path(config_path);_private_directory(p.parent)
    require(stat.S_IMODE(p.stat().st_mode)==0o600,'private observer config required')
    raw=_read(p,65536);config=strict_json(raw)
    require(isinstance(config,dict) and FIELDS<=set(config)<=FIELDS|OPTIONAL and config['schema']=='pi-live-observer-v1','strict observer config required')
    require(config['mode'] in ('ACTUAL','SIMULATED'))
    require(type(config['interval_minutes']) is int and config['interval_minutes']==15
        and type(config['lookback_hours']) is int and 1<=config['lookback_hours']<=24
        and type(config['minimum_samples']) is int and 20<=config['minimum_samples']<=500,'bounded observer policy required')
    root=_private_directory(config['root']);audit=_path(config['audit_path']);_private_directory(audit.parent)
    require(not p.is_relative_to(root) and not audit.is_relative_to(root) and audit!=p,'separate observer outputs required')
    export=_path(config.get('export_root',audit.parent/'export'));_private_directory(export.parent)
    if export.exists():_private_directory(export)
    require(not root.is_relative_to(export) and not export.is_relative_to(root) and not audit.is_relative_to(export) and not p.is_relative_to(export),'separate audit export required')
    _identity(config['identity']);PsqlMetricsReader(config['source'],run=lambda *args,**kwargs:None)
    if audit.exists():
        _plain(audit)
        try:
            with closing(sqlite3.connect(audit.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
                require(db.execute('PRAGMA user_version').fetchone()[0]==DB_VERSION,'dedicated audit database required')
        except sqlite3.DatabaseError:raise ValueError('dedicated audit database required') from None
    return p,config,sha256(raw).hexdigest(),root,audit,export


def _cached(root,run_id,config_sha,controller):
    receipt=strict_json(_read(root/'receipt.json',65536))
    require(isinstance(receipt,dict) and RESULT_FIELDS<=set(receipt)<=RESULT_FIELDS|{'failure_class'},'invalid observer result shape')
    require(hash_value(receipt['receipt_sha256']) and digest({k:v for k,v in receipt.items() if k!='receipt_sha256'})==receipt['receipt_sha256'],'observer receipt content changed')
    require(type(receipt['export_published']) is bool and receipt['status'] in ('passed','insufficient_evidence','blocked') and (receipt['observed_samples'] is None or type(receipt['observed_samples']) is int and receipt['observed_samples']>=0),'invalid observer result types')
    require(receipt.get('schema')=='pi-live-observer-result-v1'
        and receipt.get('run_id')==run_id and receipt.get('config_sha256')==config_sha
        and receipt.get('controller_sha256')==controller and receipt.get('automatic_execution') is False,'observer receipt identity mismatch')
    snapshot_sha=receipt.get('snapshot_sha256')
    if snapshot_sha is not None:
        require(hash_value(snapshot_sha) and sha256(_read(root/'metrics.json',MAX_SNAPSHOT)).hexdigest()==snapshot_sha,'observer snapshot changed')
    return receipt


def observe(config_path,*,clock=None,reader=None,expected_config_sha256=None):
    path,c,raw_sha,base,audit_path,export=_load(config_path)
    require(c['mode']!='ACTUAL' or reader is None,'ACTUAL observer cannot inject its source')
    require(c['mode']!='SIMULATED' or callable(reader),'SIMULATED observer requires an explicit test source')
    require(c['mode']!='ACTUAL' or expected_config_sha256 is not None,'ACTUAL observer requires a pinned config digest')
    if expected_config_sha256 is not None:require(hash_value(expected_config_sha256) and raw_sha==expected_config_sha256,'observer config digest mismatch')
    source=PsqlMetricsReader(c['source']) if c['mode']=='ACTUAL' else reader
    now=utc((clock or (lambda:datetime.now(timezone.utc)))())
    end=datetime.fromtimestamp(int(now.timestamp())//900*900,tz=timezone.utc)-timedelta(minutes=1)
    start=end-timedelta(hours=c['lookback_hours']);config_sha=digest(c);controller=_controller()
    run_id='observer-'+end.strftime('%Y%m%dT%H%M%SZ')+'-'+digest(dict(config=config_sha,controller=controller))[:12]
    root=_path(base/run_id)
    if root.exists():
        _private_directory(root)
        require((root/'receipt.json').exists(),'unfinished observation window retained; no automatic replay')
        return _cached(root,run_id,config_sha,controller)
    audit=AuditStore(audit_path);root.mkdir(mode=0o700)
    _publish(root/'intent.json',encoded(dict(schema='pi-observer-intent-v1',run_id=run_id,config_sha256=config_sha,controller_sha256=controller,mode=c['mode'],window=dict(start=start.isoformat(),end=end.isoformat()))),immutable=True)
    identity=_identity(c['identity'])
    version=dict(source_commit=identity.commit_sha,deployment_id=identity.deployment_id,generation=identity.generation,owner=identity.owner,image_ids=identity.image_ids or {},controller_sha256=controller,policy_sha256=config_sha)
    def event(kind,status,summary,details=None,proof=None,domain='unknown'):
        return dict(kind=kind,status=status,run_id=run_id,occurred_at=now.isoformat(),summary=summary,
            details=details or {},version=version,changes=[],evidence=proof or [],followups=[],mode=c['mode'],evidence_domain=domain)
    audit.append(run_id+':start',event('observation','running','Started fixed, read-only metric collection.',dict(model_requests=0,known_cost_microyuan=0)))
    result=dict(schema='pi-live-observer-result-v1',run_id=run_id,mode=c['mode'],config_sha256=config_sha,controller_sha256=controller,
        status='blocked',evidence_domain='unknown',observed_samples=None,minimum_samples=c['minimum_samples'],availability='unknown',
        confounders=[],snapshot_sha256=None,window=dict(start=start.isoformat(),end=end.isoformat()),automatic_execution=False,export_published=False)
    types=set();cohort=set();missing_type=False;missing_status=False;missing_model=False
    def collect(request):
        nonlocal missing_type,missing_status,missing_model
        rows=list(source(request))
        if request['source']=='tasks':
            for row in rows:
                task=row.get('id');parent=row.get('batch_task_id')
                require(isinstance(task,str) and 0<len(task)<=256 and (parent is None or isinstance(parent,str) and 0<len(parent)<=256),'bounded task cohort identifiers required')
                cohort.add((task,parent));require(len(cohort)<=1000,'bounded cohort required')
                if row.get('status') not in ('done','failed','cancelled','paused','queued','awaiting_plan','awaiting_review','running'):missing_status=True
                if row.get('batch_task_id') is not None:continue
                value=row.get('task_type')
                if not isinstance(value,str) or not name(value):missing_type=True
                else:types.add(value)
        elif request['source']=='agent_runs':
            for row in rows:
                if isinstance(row.get('measurement'),dict) and row['measurement'].get('kind')=='model' and not row.get('model_id'):missing_model=True
        return rows
    try:
        snapshot=collect_snapshot(collect,dict(id=run_id,start=start,end=end,page_size=500,max_pages=2,query_timeout_ms=5000,
            evidence_domain='online' if c['mode']=='ACTUAL' else 'synthetic'),identity)
        if len(types)>1:snapshot['confounders'].append('mixed_task_types')
        if missing_type:snapshot['confounders'].append('unknown_task_type')
        if missing_status:snapshot['confounders'].append('unknown_task_status')
        if missing_model:snapshot['confounders'].append('unknown_model_id')
        if snapshot['planned']!=snapshot['completed']+snapshot['failed']:snapshot['confounders'].append('unfinished_tasks')
        snapshot['confounders']=sorted(set(snapshot['confounders']))
        if snapshot['confounders']:snapshot['availability']='unknown'
        snapshot['task_type_range']=sorted(types)
        snapshot['cohort_sha256']=digest(sorted(cohort,key=lambda pair:(pair[0],pair[1] or '')))
        raw=encoded(snapshot);require(len(raw)<=MAX_SNAPSHOT,'metric snapshot exceeds byte bound')
        require(sha256(_read(path,65536)).hexdigest()==raw_sha,'observer config changed during collection')
        _publish(root/'metrics.json',raw,immutable=True)
        domain='online_business' if c['mode']=='ACTUAL' else 'synthetic'
        status='passed' if snapshot['availability']=='measured' and not snapshot['confounders'] and snapshot['complete_tasks']>=c['minimum_samples'] and len(types)==1 else 'insufficient_evidence'
        proof=[dict(kind='fixed_metric_snapshot',sha256=sha256(raw).hexdigest(),verified=True,evidence_domain=domain),dict(kind='observation_cohort',sha256=snapshot['cohort_sha256'],verified=True,evidence_domain=domain)]
        details=dict(reference='metrics.rolling_window.v1',request_summary=start.isoformat()+' / '+end.isoformat(),observed_samples=snapshot['complete_tasks'],minimum_samples=c['minimum_samples'],availability=snapshot['availability'],model_requests=0,known_cost_microyuan=0,
            decision='observed' if status=='passed' else 'needs_evidence',next_action='observe',reason=','.join(snapshot['confounders']) or 'cohort_sample_threshold')
        audit.append(run_id+':observation',event('observation',status,'Completed read-only metric collection; individual availability remains explicit.',details,proof,domain))
        audit.append(run_id+':version',event('version','no_change','Recorded observer/controller and available deployment identity.',dict(reference='observer_config'),proof,domain))
        audit.append(run_id+':capability',event('enhancement','passed' if c['mode']=='ACTUAL' else 'no_change','Fixed PostgreSQL metadata collection; no model or release capability.',dict(reference='collector.postgresql.fixed_views',availability='active' if c['mode']=='ACTUAL' else 'implemented'),proof,domain))
        result.update(status=status,evidence_domain=domain,observed_samples=snapshot['complete_tasks'],availability=snapshot['availability'],confounders=snapshot['confounders'],snapshot_sha256=proof[0]['sha256'])
        audit.export(export);result['export_published']=True
    except Exception as error:
        result.update(status='blocked',evidence_domain='unknown',availability='unknown',failure_class=type(error).__name__)
        audit.append(run_id+':failure',event('observation','blocked','Metric collection or publication failed; original evidence retained.',dict(reason='metric_collection_or_publication_failed',result_summary=type(error).__name__,next_action='inspect_source')))
        try:audit.export(export);result['export_published']=True
        except (ValueError,OSError,sqlite3.DatabaseError):pass
    result['receipt_sha256']=digest(result)
    _publish(root/'receipt.json',encoded(result),immutable=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True);parser.add_argument('--config-sha256');args=parser.parse_args()
    try:result=observe(Path(args.config),expected_config_sha256=args.config_sha256)
    except (ValueError,OSError,sqlite3.DatabaseError) as error:
        print(json.dumps(dict(status='blocked',failure_class=type(error).__name__,automatic_execution=False)));return 1
    print(json.dumps(result));return 1 if result['status']=='blocked' else 0


if __name__=='__main__':raise SystemExit(main())
