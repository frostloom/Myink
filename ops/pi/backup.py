"""Trusted paired collections. Candidate/model code never owns this interface."""
from contextlib import contextmanager
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


def mark_released(ledger,pair_id,candidate):
    pair=ledger.get('release-pair:'+pair_id)
    if pair is None or pair['payload']['post_identity']!=candidate or not release_allowed(ledger,pair_id):
        raise ValueError('candidate requires verified PRE and matching pair')
    operation='release:'+pair_id
    ledger.intent(operation,'release',{'release_pair_id':pair_id,'candidate':candidate})
    ledger.finish(Receipt(operation,'done',{'post_pending':True}))


def release_allowed(ledger,pair_id,*,recovery=False):
    if recovery:return True
    with ledger.transaction() as db:
        releases=[Ledger._record(row) for row in db.execute("SELECT * FROM operations WHERE kind='release' AND status='done'")]
        pair=Ledger._record(db.execute('SELECT * FROM operations WHERE operation_id=?',('release-pair:'+pair_id,)).fetchone())
    def restored(backup):
        if not backup or backup['status']!='done':return False
        with ledger.transaction() as db:
            checks=[Ledger._record(row) for row in db.execute("SELECT * FROM operations WHERE kind='restore_check' ORDER BY rowid")]
        matching=[row for row in checks if row['payload']['backup_operation']==backup['operation_id'] and row['payload']['manifest_sha256']==backup['evidence']['manifest_sha256']]
        return bool(matching and matching[-1]['status']=='done')
    for row in releases:
        post=ledger.get('backup:'+row['payload']['release_pair_id']+':POST')
        if not restored(post):return False
    if pair:
        pre=ledger.get('backup:'+pair_id+':PRE')
        return restored(pre)
    return True


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
    with sqlite3.connect(ledger.path) as source,sqlite3.connect(path) as target:
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


def record_restore(ledger,backup_receipt,restore_receipt):
    """Immutable restore event, separate from the original collection manifest."""
    operation='restore-check:'+restore_receipt.operation_id
    ledger.intent(operation,'restore_check',{'backup_operation':backup_receipt.operation_id,'manifest_sha256':backup_receipt.evidence['manifest_sha256']})
    ledger.finish(Receipt(operation,restore_receipt.status,restore_receipt.evidence))


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
        verify_artifacts(manifest,directory);verify_artifacts(manifest,private_path(Path(root).parent/'mirror',manifest['backup_id']))
        return Receipt(operation,'done',existing['evidence'])
    except Exception as exc:
        evidence={'reason':'collection_revalidation_failed','error_class':type(exc).__name__}
        ledger.append_event('backup_revalidation',{'operation_id':operation,'status':'blocked',**evidence})
        return Receipt(operation,'blocked',evidence)
