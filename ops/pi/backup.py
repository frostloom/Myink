"""Trusted paired collections. Candidate/model code never owns this interface."""
from contextlib import contextmanager, closing
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid
from zoneinfo import ZoneInfo
from .contracts import Identity, Receipt
from .ledger import Ledger, OperationConflict

REQUIRED = {'database','roles','crypto','attachments','config','certificate','ledger'}


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda:stream.read(65536),b''):h.update(part)
    return h.hexdigest()


def private_path(root,relative):
    root=Path(root)
    path=root/relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts:raise ValueError('artifact path escape')
    for item in (path,*path.parents):
        if item.is_symlink() or (hasattr(item,'is_junction') and item.is_junction()):raise ValueError('private link rejected')
        if item==root.parent:break
    if path.exists() and path.is_file() and path.stat().st_nlink!=1:raise ValueError('private hardlink rejected')
    return path


def durable_file(path,raw):
    with path.open('xb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    path.chmod(0o600)


def persist_pair(ledger,pair):
    if (set(pair)!={'release_pair_id','pre_identity','post_identity','plan_hash'}
            or not pair['release_pair_id'] or not pair['plan_hash']
            or pair['pre_identity']['deployment_id']==pair['post_identity']['deployment_id']):raise ValueError('explicit frozen pair required')
    ledger.intent('release-pair:'+pair['release_pair_id'],'release_pair',pair)


def mark_released(ledger,pair_id,candidate,*,context=None,now=None):
    pair=ledger.get('release-pair:'+pair_id)
    if pair is None or pair['payload']['post_identity']!=candidate or not release_allowed(ledger,pair_id,context=context,now=now):
        raise ValueError('candidate requires verified PRE and matching pair')
    operation='release:'+pair_id
    ledger.intent(operation,'release',{'release_pair_id':pair_id,'candidate':candidate})
    ledger.finish(Receipt(operation,'done',{'post_pending':True}))


def _records(ledger,kind):
    with ledger.transaction() as db:
        return [Ledger._record(row) for row in db.execute('SELECT * FROM operations WHERE kind=? ORDER BY rowid',(kind,))]


def _hash(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def _attested(ledger,kind,operation,sha):
    with ledger.transaction() as db:
        rows=[json.loads(row[0]) for row in db.execute('SELECT payload FROM events WHERE kind=?',(kind,))]
    return [row for row in rows if row.get('operation_id')==operation]==[{'operation_id':operation,'sha256':sha}]


def record_recovery_references(ledger,operation_id,*,version,context,complete,stable_ids,referenced_ids):
    """Trusted controller inventory. Explicit complete-empty differs from omission."""
    if (type(version) is not int or version<1 or not _rehearsal_context(context) or type(complete) is not bool
            or any(not isinstance(v,str) or not v for v in [*stable_ids,*referenced_ids])):raise ValueError('invalid trusted reference inventory')
    payload={'version':version,'context':context,'complete':complete,'stable_ids':sorted(set(stable_ids)),'referenced_ids':sorted(set(referenced_ids))}
    old=_records(ledger,'recovery_reference_inventory')
    if old and old[-1]['operation_id']!=operation_id and version<=old[-1]['payload']['version']:raise ValueError('reference version must advance')
    existing=ledger.intent(operation_id,'recovery_reference_inventory',payload)
    if existing['status']!='pending':return Receipt(operation_id,existing['status'],existing['evidence'])
    known={row['payload']['backup_id'] for row in _records(ledger,'backup') if row['status']=='done'}
    valid=complete and set(payload['stable_ids']+payload['referenced_ids']).issubset(known)
    sha=_hash(payload)
    if valid:ledger.append_event('recovery_references_verified',{'operation_id':operation_id,'sha256':sha})
    receipt=Receipt(operation_id,'done' if valid else 'blocked',{'inventory_sha256':sha})
    ledger.finish(receipt);return receipt


def _current_references(ledger,context):
    rows=_records(ledger,'recovery_reference_inventory')
    if not rows:raise ValueError('trusted current references missing')
    latest=rows[-1];payload=latest['payload']
    if (latest['status']!='done' or set(payload)!={'version','context','complete','stable_ids','referenced_ids'}
            or type(payload['version']) is not int or payload['version']<1 or payload['complete'] is not True
            or payload['context']!=context or not _rehearsal_context(context)
            or any(type(row['payload'].get('version')) is not int or row['payload']['version']>=payload['version'] for row in rows[:-1])
            or latest['evidence'].get('inventory_sha256')!=_hash(payload)
            or not _attested(ledger,'recovery_references_verified',latest['operation_id'],_hash(payload))):raise ValueError('references unknown or stale')
    for key in ('stable_ids','referenced_ids'):
        if not isinstance(payload[key],list) or any(not isinstance(v,str) or not v for v in payload[key]) or payload[key]!=sorted(set(payload[key])):raise ValueError('reference IDs invalid')
    return latest


def _latest_restore(ledger,backup):
    matches=[row for row in _records(ledger,'restore_check') if row['payload'].get('backup_operation')==backup['operation_id']
        and row['payload'].get('manifest_sha256')==backup['evidence']['manifest_sha256']]
    return matches[-1] if matches else None


def _completed_restore(row):
    return bool(row and row['status']=='done' and row['evidence'].get('verified') is True)


def _fresh_restore(row,context,now):
    if not _completed_restore(row) or row['payload'].get('rehearsal_context')!=context:return False
    try:completed=datetime.fromisoformat(row['evidence']['rehearsal_completed_at'])
    except (KeyError,TypeError,ValueError):return False
    return completed.tzinfo is not None and timedelta(0)<=now-completed<timedelta(days=7)


def _manifest_binding(ledger,backup,manifest):
    publication=_publication(ledger,backup['operation_id']);pair=ledger.get('release-pair:'+backup['payload']['release_pair_id'])
    if (not publication or not pair or _hash(manifest)!=backup['evidence']['manifest_sha256']
            or publication['manifest_sha256']!=backup['evidence']['manifest_sha256']
            or manifest['backup_id']!=backup['payload']['backup_id'] or manifest['release_pair_id']!=backup['payload']['release_pair_id']
            or manifest['phase']!=backup['payload']['phase'] or manifest['identity']!=backup['payload']['identity']
            or pair['payload'][manifest['phase'].lower()+'_identity']!=manifest['identity']
            or pair['payload']['plan_hash']!=manifest['plan_hash']):raise ValueError('immutable manifest binding missing')


def _classification(ledger,row):
    """A retained canonical classification is provenance, never a debt waiver."""
    if row['status']!='done':return None
    payload=row['payload'];evidence=row['evidence'];sha=_hash({'payload':payload,'archive_ids':evidence['archive_ids']})
    if set(payload)!={'references','classified_at','catalog'} or evidence.get('classification_sha256')!=sha or not _attested(ledger,'recovery_set_classified',row['operation_id'],sha):return None
    references=ledger.get(payload['references']['operation_id'])
    if not references or references['status']!='done' or payload['references']!=_reference_binding(references) or not _attested(ledger,'recovery_references_verified',references['operation_id'],_hash(references['payload'])):return None
    rows=[]
    for operation,item in payload['catalog'].items():
        backup=ledger.get(operation)
        if not backup or backup['status']!='done':return None
        _manifest_binding(ledger,backup,item['manifest'])
        restore=ledger.get(item['restore_operation']) if item['restore_operation'] else None
        if item['restore_sha256']!=(_hash(restore) if restore else None):return None
        if restore and (restore['kind']!='restore_check' or restore['payload']['backup_operation']!=operation or restore['payload']['manifest_sha256']!=backup['evidence']['manifest_sha256']):return None
        rows.append(_retention_manifest(item['manifest'],restore,references['payload']))
    clock=datetime.fromisoformat(payload['classified_at'])
    if clock.tzinfo is None or evidence['archive_ids']!=retention_candidates(rows,clock):return None
    return row


def _reference_binding(row):
    return {'operation_id':row['operation_id'],'version':row['payload']['version'],'inventory_sha256':_hash(row['payload'])}


def _retention_manifest(manifest,restore,references):
    return {**manifest,'restore_status':'done' if _completed_restore(restore) else 'pending',
        'stable':manifest['backup_id'] in references['stable_ids'],'referenced':manifest['backup_id'] in references['referenced_ids'],
        'post_pending':not _completed_restore(restore)}


def _recovery_catalog(ledger,references,*,allow_archive):
    classifications=[]
    if allow_archive:
        for row in _records(ledger,'recovery_set_classification'):
            verified=_classification(ledger,row)
            if verified:classifications.append(verified)
    catalog={};archives=set()
    for backup in _records(ledger,'backup'):
        if backup['status']!='done':continue
        operation=backup['operation_id'];manifest=None
        for row in classifications:
            item=row['payload']['catalog'].get(operation)
            if item:
                manifest=item['manifest']
                if manifest['backup_id'] in row['evidence']['archive_ids']:archives.add(manifest['backup_id'])
        if manifest is None:manifest=json.loads(Path(backup['evidence']['manifest_path']).read_text())
        _manifest_binding(ledger,backup,manifest)
        catalog[operation]={'backup':backup,'manifest':manifest,'restore':_latest_restore(ledger,backup)}
    ids={item['manifest']['backup_id'] for item in catalog.values()}
    if not set(references['payload']['stable_ids']+references['payload']['referenced_ids']).issubset(ids):raise ValueError('unknown required reference')
    return catalog,archives


def classify_recovery_set(ledger,operation_id,*,context,now):
    """Fixed trusted classification; derive eligible IDs, validate files first, delete nothing."""
    if now.tzinfo is None:raise ValueError('aware classification clock required')
    references=_current_references(ledger,context);catalog,_=_recovery_catalog(ledger,references,allow_archive=False)
    payload={'references':_reference_binding(references),'classified_at':now.isoformat(),'catalog':{operation:{'manifest':item['manifest'],
        'restore_operation':item['restore']['operation_id'] if item['restore'] else None,'restore_sha256':_hash(item['restore']) if item['restore'] else None}
        for operation,item in catalog.items()}}
    existing=ledger.intent(operation_id,'recovery_set_classification',payload)
    if existing['status']!='pending':return Receipt(operation_id,existing['status'],existing['evidence'])
    try:
        _validate_recovery_set(ledger,catalog,set(),references,context,now,None)
        archive_ids=retention_candidates([_retention_manifest(item['manifest'],item['restore'],references['payload']) for item in catalog.values()],now)
        evidence={'archive_ids':archive_ids,'classification_sha256':_hash({'payload':payload,'archive_ids':archive_ids})}
        if _reference_binding(_current_references(ledger,context))!=_reference_binding(references):raise ValueError('current references changed during validation')
        ledger.append_event('recovery_set_classified',{'operation_id':operation_id,'sha256':evidence['classification_sha256']})
        receipt=Receipt(operation_id,'done',evidence)
    except (ValueError,OSError,KeyError,TypeError) as exc:receipt=Receipt(operation_id,'blocked',{'reason':'recovery_set_unconfirmed','error_class':type(exc).__name__})
    ledger.finish(receipt);return receipt


def _validate_recovery_set(ledger,catalog,archives,references,context,now,candidate_operation):
    eligible=set(retention_candidates([_retention_manifest(item['manifest'],item['restore'],references['payload']) for item in catalog.values()],now))
    fresh_ids=set(references['payload']['stable_ids']+references['payload']['referenced_ids'])
    releases=_records(ledger,'release')
    for release in releases:
        if release['status']!='done':continue
        post=catalog.get('backup:'+release['payload']['release_pair_id']+':POST')
        if not post or not _completed_restore(post['restore']):raise ValueError('unresolved or reopened POST debt')
    for operation,item in catalog.items():
        backup=item['backup'];manifest=item['manifest'];restore=item['restore']
        fresh=operation==candidate_operation or manifest['backup_id'] in fresh_ids
        if restore and not _completed_restore(restore):raise ValueError('pending or failed recovery attempt')
        if fresh and not _fresh_restore(restore,context,now):raise ValueError('required current qualification missing')
        if manifest['backup_id'] in archives and manifest['backup_id'] in eligible and not fresh:continue
        root=Path(backup['evidence']['manifest_path']).parent.parent
        if revalidate_collection(ledger,backup,root).status!='done':raise ValueError('required recovery collection unavailable')


def release_allowed(ledger,pair_id,*,recovery=False,context=None,now=None):
    if recovery:return True
    if not _rehearsal_context(context):return False
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:return False
    try:
        references=_current_references(ledger,context);catalog,archives=_recovery_catalog(ledger,references,allow_archive=True)
        pair=ledger.get('release-pair:'+pair_id);candidate='backup:'+pair_id+':PRE' if pair else None
        if pair and candidate not in catalog:return False
        _validate_recovery_set(ledger,catalog,archives,references,context,now,candidate)
        if _reference_binding(_current_references(ledger,context))!=_reference_binding(references):return False
        return bool(pair or any(row['status']=='done' for row in _records(ledger,'release')))
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError):return False


@contextmanager
def collection_lock(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    path=private_path(root,'.backup.lock')
    with path.open('a+b') as stream:
        acquired=False
        try:
            if os.name=='nt':
                import msvcrt
                stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
                try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1);acquired=True
                except OSError:pass
            else:
                import fcntl
                try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB);acquired=True
                except BlockingIOError:pass
            yield acquired
        finally:
            if acquired:
                if os.name=='nt':
                    stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(stream,fcntl.LOCK_UN)


def snapshot_ledger(ledger,path):
    with closing(sqlite3.connect(ledger.path.absolute().as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(path)) as target:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('bad ledger snapshot')
        result={'event_hwm':target.execute('SELECT coalesce(max(id),0) FROM events').fetchone()[0],
                'operation_hwm':target.execute('SELECT coalesce(max(rowid),0) FROM operations').fetchone()[0],
                'operations':target.execute('SELECT count(*) FROM operations').fetchone()[0],
                'source_identity':hashlib.sha256(str(ledger.path.resolve()).encode()).hexdigest()}
    path.chmod(0o600)
    return result


def verify_artifacts(manifest,directory):
    if not REQUIRED.issubset(manifest['artifacts']):raise ValueError('required recovery material missing')
    for role,artifact in manifest['artifacts'].items():
        path=private_path(directory,artifact['path'])
        if not path.is_file() or artifact['bytes']<=0 or path.stat().st_size!=artifact['bytes'] or digest(path)!=artifact['sha256']:
            raise ValueError('artifact integrity mismatch')
    with gzip.open(private_path(directory,manifest['artifacts']['database']['path']),'rb') as stream:
        if not stream.read(1):raise ValueError('empty dump')
        for _ in iter(lambda:stream.read(65536),b''):pass
    snapshot=private_path(directory,manifest['artifacts']['ledger']['path'])
    with sqlite3.connect('file:'+snapshot.as_posix()+'?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('ledger corruption')
        actual=(db.execute('SELECT coalesce(max(id),0) FROM events').fetchone()[0],db.execute('SELECT coalesce(max(rowid),0) FROM operations').fetchone()[0],db.execute('SELECT count(*) FROM operations').fetchone()[0])
        proof=manifest['ledger_snapshot']
        if actual!=(proof['event_hwm'],proof['operation_hwm'],proof['operations']):raise ValueError('snapshot watermark mismatch')
        backup=db.execute('SELECT payload FROM operations WHERE operation_id=?',('backup:'+manifest['release_pair_id']+':'+manifest['phase'],)).fetchone()
        pair=db.execute('SELECT payload FROM operations WHERE operation_id=?',('release-pair:'+manifest['release_pair_id'],)).fetchone()
        if not backup or not pair:raise ValueError('snapshot authority missing')
        captured=json.loads(backup[0]);binding=json.loads(pair[0])
        if (captured['identity']!=manifest['identity'] or captured['backup_id']!=manifest['backup_id']
            or binding[manifest['phase'].lower()+'_identity']!=manifest['identity'] or binding['plan_hash']!=manifest['plan_hash']):raise ValueError('snapshot identity mismatch')
    return True


def _publication(ledger,operation):
    with ledger.transaction() as db:
        rows=db.execute("SELECT payload FROM events WHERE kind='backup_artifacts' ORDER BY id").fetchall()
    return next((json.loads(row[0]) for row in rows if json.loads(row[0])['operation_id']==operation),None)


def create_backup(ledger:Ledger,phase,identity:Identity,executor,root:Path,*,pair)->Receipt:
    if phase not in ('PRE','POST'):raise ValueError('invalid phase')
    persist_pair(ledger,pair)
    if phase=='POST':
        released=ledger.get('release:'+pair['release_pair_id'])
        if not released or released['status']!='done':return Receipt('backup:'+pair['release_pair_id']+':POST','blocked',{'reason':'release_not_confirmed'})
    if asdict(identity)!=pair[phase.lower()+'_identity']:raise ValueError('pair identity mismatch')
    operation='backup:'+pair['release_pair_id']+':'+phase
    existing=ledger.get(operation)
    if existing and existing['status']!='pending':return revalidate_collection(ledger,existing,root)
    backup_id=hashlib.sha256(operation.encode()).hexdigest()
    directory=private_path(root,backup_id)
    with collection_lock(root) as acquired:
        if not acquired:return Receipt(operation,'pending',{'reason':'owner_active'})
        existing=ledger.get(operation)
        if existing and existing['status']!='pending':return revalidate_collection(ledger,existing,root)
        context={'operation_id':operation,'phase':phase,'pair':pair,'identity':asdict(identity),'directory':str(directory)}
        ledger.intent(operation,'backup',{'release_pair_id':pair['release_pair_id'],'phase':phase,'identity':asdict(identity),'backup_id':backup_id})
        evidence={'backup_id':backup_id,'release_pair_id':pair['release_pair_id'],'phase':phase}
        try:
            current=executor('verify_identity',context)
            if not current.get('verified') or not current.get('consistency_id'):raise ValueError('current quiet identity required')
            publication=_publication(ledger,operation)
            final=directory/'manifest.json';partial=directory/'manifest.part'
            if publication:
                path=final if final.exists() else partial
                if digest(path)!=publication['manifest_sha256']:raise ValueError('published manifest mismatch')
                manifest=json.loads(path.read_text())
                verify_artifacts(manifest,directory)
                mirror=private_path(Path(root).parent/'mirror',backup_id)
                verify_artifacts(manifest,mirror)
                if path==partial:partial.replace(final)
                evidence.update(manifest_path=str(final),manifest_sha256=publication['manifest_sha256'],reconciled=True)
            else:
                with ledger.transaction() as db:
                    claimed=any(json.loads(row[0])['operation_id']==operation for row in db.execute("SELECT payload FROM events WHERE kind='backup_claim'"))
                if claimed or directory.exists():return Receipt(operation,'uncertain',{**evidence,'reason':'unpublished_owner_requires_reconciliation'})
                ledger.append_event('backup_claim',{'operation_id':operation,'owner_token':str(uuid.uuid4())})
                directory.mkdir(mode=0o700)
                collected=executor('collect',context)
                if (not collected.get('verified') or collected.get('consistency_id')!=current['consistency_id']
                        or collected.get('dump_exit')!=0 or collected.get('dump_stderr_bytes')!=0 or not collected.get('roles')):
                    raise ValueError('collection not verified')
                paths={**collected['artifacts'],'ledger':'ledger.sqlite'}
                watermark=snapshot_ledger(ledger,directory/'ledger.sqlite')
                artifacts={role:{'path':str(name),'bytes':private_path(directory,name).stat().st_size,'sha256':digest(private_path(directory,name))} for role,name in paths.items()}
                manifest={**evidence,'created_at':datetime.now(timezone.utc).isoformat(),'identity':asdict(identity),'plan_hash':pair['plan_hash'],
                    'source_id':collected['source_id'],'consistency_id':current['consistency_id'],'roles':collected['roles'],
                    'artifacts':artifacts,'ledger_snapshot':watermark,'integrity':'verified','restore_status':'pending',
                    'mirror_status':'verified','offsite_status':'not_configured','not_applicable':collected.get('not_applicable',[])}
                verify_artifacts(manifest,directory)
                # Revalidate ownership/quiet epoch immediately before durable publication.
                if executor('verify_identity',context)!=current:raise ValueError('source superseded')
                mirror=private_path(Path(root).parent/'mirror',backup_id)
                mirror.mkdir(parents=True,mode=0o700)
                for item in artifacts.values():
                    target=private_path(mirror,item['path']);target.parent.mkdir(parents=True,exist_ok=True)
                    with private_path(directory,item['path']).open('rb') as source,target.open('xb') as dest:
                        shutil.copyfileobj(source,dest);dest.flush();os.fsync(dest.fileno())
                    target.chmod(0o600)
                verify_artifacts(manifest,mirror)
                raw=encoded(manifest);durable_file(partial,raw)
                durable_file(mirror/'manifest.json',raw)
                publication={'operation_id':operation,'manifest_sha256':hashlib.sha256(raw).hexdigest(),'backup_id':backup_id,
                             'source_id':manifest['source_id'],'consistency_id':manifest['consistency_id']}
                ledger.append_event('backup_artifacts',publication)
                partial.replace(final)
                evidence.update(manifest_path=str(final),manifest_sha256=publication['manifest_sha256'],offsite_status='not_configured')
            receipt=Receipt(operation,'done',evidence)
            ledger.finish(receipt)
            return receipt
        except Exception as exc:
            receipt=Receipt(operation,'failed',{**evidence,'reason':'backup_unconfirmed','error_class':type(exc).__name__})
            ledger.finish(receipt)
            return receipt


def restore_check(manifest,target,executor)->Receipt:
    operation='restore:'+manifest.get('backup_id','missing')+':'+str(target.get('system_identifier','pending'))
    try:
        if (not target.get('clean') or target.get('system_identifier')==target.get('source_system_identifier')
                or manifest.get('integrity')!='verified'):raise ValueError('fresh distinct verified restore required')
        verify_artifacts(manifest,Path(target['collection_directory']))
        result=executor('restore',{'manifest':manifest,'target':target})
        if not result.get('verified'):raise ValueError('restore assertions incomplete')
        return Receipt(operation,'done',result)
    except Exception as exc:
        return Receipt(operation,'failed',{'reason':'restore_unconfirmed','error_class':type(exc).__name__})


def _rehearsal_context(context):
    return isinstance(context,dict) and set(context)=={'schema_context','tool_context'} and all(isinstance(v,str) and bool(v) for v in context.values())


def start_rehearsal(ledger,backup_receipt,restore_operation,*,context=None):
    """Intent before import; pending/failed/new-context rehearsals close the gate."""
    if context is not None and not _rehearsal_context(context):raise ValueError('trusted schema/tool context required')
    if not restore_operation.startswith('restore:'+backup_receipt.evidence['backup_id']+':'):raise ValueError('restore identity mismatch')
    operation='restore-check:'+restore_operation
    ledger.intent(operation,'restore_check',{'backup_operation':backup_receipt.operation_id,
        'manifest_sha256':backup_receipt.evidence['manifest_sha256'],'rehearsal_context':context})
    return operation


def start_rehearsal_attempt(ledger,backup_receipt,transport_operation,*,context):
    """Claim a planned target before any preparation; no actual target ID is invented."""
    if not _rehearsal_context(context):raise ValueError('trusted schema/tool context required')
    transport=str(uuid.UUID(transport_operation));collection=Path(backup_receipt.evidence['manifest_path']).parent
    case=str(uuid.uuid5(uuid.UUID(transport),'positive'+str(collection)))
    operation='restore-check:attempt:'+case
    ledger.intent(operation,'restore_check',{'backup_operation':backup_receipt.operation_id,'manifest_sha256':backup_receipt.evidence['manifest_sha256'],
        'rehearsal_context':context,'planned_target':{'case_uuid':case,'operation_id':transport,'collection_id':backup_receipt.evidence['backup_id'],'fault':'positive'}})
    return operation


def bind_rehearsal_target(ledger,attempt_operation,target):
    attempt=ledger.get(attempt_operation);planned=attempt['payload']['planned_target'];actual=ledger.get(target['target_operation'])
    if attempt['status']!='pending' or not actual or actual['kind']!='restore_target' or any(actual['payload'].get(k)!=v for k,v in planned.items()):raise ValueError('verified target does not match planned attempt')
    if not target['clean'] or target['system_identifier']==target['source_system_identifier']:raise ValueError('verified target must be clean/distinct')
    with ledger.transaction() as db:created=[json.loads(v[0]) for v in db.execute("SELECT payload FROM events WHERE kind='restore_target_created'")]
    bindings=[v for v in created if v['target_operation']==target['target_operation']]
    if len(bindings)!=1 or bindings[0]['container_id']!=target['container_id']:raise ValueError('actual target creation binding missing')
    ledger.append_event('rehearsal_target_verified',{'attempt_operation':attempt_operation,'target_operation':target['target_operation'],
        'container_id':target['container_id'],'system_identifier':target['system_identifier'],'source_system_identifier':target['source_system_identifier'],'registry_sha256':bindings[0]['registry_sha256']})


def record_restore(ledger,backup_receipt,restore_receipt,*,context=None,now=None,attempt_operation=None):
    """Immutable actual restore qualification, bound to context and completion clock."""
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('aware rehearsal clock required')
    actual_target={}
    if attempt_operation is None:operation=start_rehearsal(ledger,backup_receipt,restore_receipt.operation_id,context=context)
    else:
        operation=attempt_operation;attempt=ledger.get(operation)
        if attempt['payload']['backup_operation']!=backup_receipt.operation_id or attempt['payload']['manifest_sha256']!=backup_receipt.evidence['manifest_sha256'] or attempt['payload']['rehearsal_context']!=context:raise ValueError('attempt binding mismatch')
        with ledger.transaction() as db:targets=[json.loads(v[0]) for v in db.execute("SELECT payload FROM events WHERE kind='rehearsal_target_verified'")]
        matches=[v for v in targets if v['attempt_operation']==operation]
        if (len(matches)!=1 or restore_receipt.operation_id!='restore:'+backup_receipt.evidence['backup_id']+':'+matches[0]['system_identifier']
                or restore_receipt.status=='done' and restore_receipt.evidence.get('target_system_identifier')!=matches[0]['system_identifier']):raise ValueError('actual restore identity missing')
        actual_target={'actual_restore_operation':restore_receipt.operation_id,'verified_target':matches[0]}
    ledger.finish(Receipt(operation,restore_receipt.status,{**restore_receipt.evidence,**actual_target,'rehearsal_completed_at':now.isoformat()}))


def retention_candidates(manifests,now):
    if now.tzinfo is None:raise ValueError('aware retention clock required')
    today=now.astimezone(ZoneInfo('Asia/Shanghai')).date()
    good=lambda m:m.get('integrity')=='verified' and m.get('restore_status')=='done' and m.get('mirror_status')=='verified'
    pairs={}
    for m in manifests:pairs.setdefault(m['release_pair_id'],[]).append(m)
    complete={key:rows for key,rows in pairs.items() if {m['phase'] for m in rows if good(m)}=={'PRE','POST'} and all(good(m) for m in rows)}
    recent=set(sorted(complete,key=lambda p:max(datetime.fromisoformat(m['created_at']) for m in complete[p]),reverse=True)[:5])
    protected=set()
    for m in manifests:
        day=datetime.fromisoformat(m['created_at']).astimezone(ZoneInfo('Asia/Shanghai')).date()
        if (m['release_pair_id'] not in complete or m['release_pair_id'] in recent or m.get('stable') or m.get('post_pending')
                or day>=today-timedelta(days=13) or m.get('referenced')):protected.add(m['release_pair_id'])
    return sorted(m['backup_id'] for m in manifests if m['release_pair_id'] not in protected)


def calendar_gaps(manifests,now):
    today=now.astimezone(ZoneInfo('Asia/Shanghai')).date()
    present={datetime.fromisoformat(m['created_at']).astimezone(ZoneInfo('Asia/Shanghai')).date() for m in manifests if m.get('integrity')=='verified' and m.get('restore_status')=='done' and m.get('mirror_status')=='verified'}
    return [(today-timedelta(days=n)).isoformat() for n in range(14) if today-timedelta(days=n) not in present]


def revalidate_collection(ledger,existing,root):
    operation=existing['operation_id']
    if existing['status']!='done':return Receipt(operation,existing['status'],existing['evidence'])
    try:
        directory=private_path(root,existing['payload']['backup_id'])
        publication=_publication(ledger,operation)
        if not publication or digest(directory/'manifest.json')!=publication['manifest_sha256'] or publication['manifest_sha256']!=existing['evidence']['manifest_sha256']:raise ValueError('publication mismatch')
        manifest=json.loads((directory/'manifest.json').read_text())
        mirror=private_path(Path(root).parent/'mirror',manifest['backup_id'])
        if digest(mirror/'manifest.json')!=publication['manifest_sha256']:raise ValueError('mirror manifest mismatch')
        verify_artifacts(manifest,directory);verify_artifacts(manifest,mirror)
        ledger.append_event('backup_revalidation',{'operation_id':operation,'status':'done','manifest_sha256':publication['manifest_sha256']})
        return Receipt(operation,'done',existing['evidence'])
    except Exception as exc:
        evidence={'reason':'collection_revalidation_failed','error_class':type(exc).__name__}
        ledger.append_event('backup_revalidation',{'operation_id':operation,'status':'blocked',**evidence})
        return Receipt(operation,'blocked',evidence)
