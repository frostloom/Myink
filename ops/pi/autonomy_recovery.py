"""Preserve and withdraw only this coordinator's still-unregistered admission."""
from pathlib import Path
import fcntl,os
from .audit import _path,_plain,hash_value,require,encoded
from .development_inputs import file_hash,read_json
from .review_lease import _read,_directory,_sync
from .autonomy_profile import write,_owner
from .manager_handoff import FIELDS
from .manager import _snapshot
from .task_package import _publish_new


def withdraw(p,claim_path,stage,lock):
    claim=_directory(claim_path);require(claim.parent==_path(p['root']) and hash_value(claim.name),'original coordinator recovery claim required')
    lp=_path(p['lock_path']);_plain(lp);info=os.fstat(lock.fileno());current=lp.stat()
    require(_path(lock.name)==lp and (info.st_dev,info.st_ino)==(current.st_dev,current.st_ino),'canonical maintenance lock descriptor required')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    fp=claim.name;cp=_path(stage['config_path']);require(cp==_path(p['handoff_root'])/('request-'+fp+'.json') and file_hash(cp)==stage['config_sha256'],'original handoff input required')
    q=read_json(cp);root=_path(p['handoff_root'])/('handoff-'+fp);cycle=root/'bundle/cycle.json'
    require(isinstance(q,dict) and set(q)==FIELDS and q['mode']==p['mode'] and _path(q['root'])==root and q['task_id']=='auto-'+fp[:32] and _path(q['inbox'])==_path(p['inbox']) and _path(q['manager_state'])==_path(p['manager_state']),'owned handoff identity required')
    destination=_path(p['inbox'])/(q['task_id']+'.task.json');recovery=claim/'withdrawal'
    if recovery.exists():
        if not (recovery/'receipt.json').exists():return dict(status='uncertain',model_requests=0)
        receipt=_read(recovery/'receipt.json')[0];saved=recovery/'admission-private.task.json'
        require(receipt['status']=='withdrawn' and not destination.exists() and file_hash(saved)==receipt['manifest_sha256'],'withdrawal history drift')
        return dict(receipt,cached=True)
    if not destination.exists():return dict(status='absent',model_requests=0)
    _plain(destination);require(destination.stat().st_mode&0o777==0o600,'private owned admission required');raw=destination.read_bytes();pin=file_hash(destination);identity=destination.stat()
    expected=dict(schema='pi-manager-admission-v1',task_id=q['task_id'],request_path=str(cycle),request_sha256=file_hash(cycle),priority=q['priority'],mode=p['mode'])
    require(read_json(destination)==expected,'unowned admission must not be withdrawn')
    rows=_snapshot(Path(p['manager_state']),Path(p['host']['ledger_path']),p['mode'])[2]
    require('manager:task:'+q['task_id'] not in rows,'registered admission cannot be withdrawn')
    recovery.mkdir(mode=0o700)
    if p['mode']=='ACTUAL':os.chown(recovery,*_owner(p))
    _sync(claim);write(p,recovery/'intent.json',dict(schema='pi-admission-withdrawal-intent-v1',task_id=q['task_id'],manifest_sha256=pin,handoff_request_sha256=stage['config_sha256']))
    saved=recovery/'admission-private.task.json';retained=_publish_new(saved,raw);require(not retained,'withdrawal staging uncertain')
    if p['mode']=='ACTUAL':
        fd=os.open(saved,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fchown(fd,*_owner(p));os.fsync(fd)
        finally:os.close(fd)
    require(file_hash(saved)==pin and file_hash(destination)==pin and (destination.stat().st_dev,destination.stat().st_ino)==(identity.st_dev,identity.st_ino),'admission changed during withdrawal')
    require('manager:task:'+q['task_id'] not in _snapshot(Path(p['manager_state']),Path(p['host']['ledger_path']),p['mode'])[2],'admission registered during withdrawal')
    destination.unlink();_sync(destination.parent)
    receipt=dict(schema='pi-admission-withdrawal-result-v1',status='withdrawn',model_requests=0,task_id=q['task_id'],manifest_sha256=pin,retained_manifest_path=str(saved))
    write(p,recovery/'receipt.json',receipt);return dict(receipt,cached=False)
