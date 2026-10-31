"""Atomic, content-addressed audit projection; never exports billing authority."""
from contextlib import closing
from datetime import datetime,timezone
import fcntl
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import tempfile
from ops.pi.audit import _iter,_path,_plain,_schema,digest,encoded,require,strict_json

PAGE_BYTES=1048576


def indexes(pages,events):
    runs={};days={}
    for page,items in zip(pages,events):
        for event in items:
            run=runs.setdefault(event['run_id'],dict(run_id=event['run_id'],event_count=0,days=set(),pages=[]))
            day=days.setdefault(event['day'],dict(day=event['day'],event_count=0,runs=set(),pages=[]))
            run['event_count']+=1;run['days'].add(event['day'])
            day['event_count']+=1;day['runs'].add(event['run_id'])
            for index in (run,day):
                if page['sha256'] not in index['pages']:index['pages'].append(page['sha256'])
    return ([dict(v,days=sorted(v['days'])) for _,v in sorted(runs.items())],
            [dict(v,runs=sorted(v['runs'])) for _,v in sorted(days.items())])


def _directory(path):
    require(path.resolve()==path,'non-link export directory required')
    path.mkdir(mode=0o700,exist_ok=True)
    require(path.is_dir() and path.stat().st_mode&0o777==0o700,'private export directory required')


def _publish(path,data,immutable=False):
    if path.exists() or path.is_symlink():
        _plain(path)
        if immutable:
            require(path.read_bytes()==data,'immutable audit page conflict');return
    fd,name=tempfile.mkstemp(prefix='.audit-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(name):os.unlink(name)


def export_snapshot(store,root):
    root=_path(root)
    require(not store.path.is_relative_to(root) and not root.is_relative_to(store.path),'separate export root required')
    _directory(root);_directory(root/'pages')
    lock=root/'.export.lock'
    if not lock.exists():
        try:
            fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        except FileExistsError:pass
    _plain(lock)
    with lock.open('rb') as locked:
        fcntl.flock(locked,fcntl.LOCK_EX)
        _plain(store.path)
        pages=[];chunk=[]
        def flush():
            if not chunk:return
            raw=encoded(dict(schema_version=1,authority='audit_only',events=chunk));key=sha256(raw).hexdigest()
            _publish(root/'pages'/(key+'.json'),raw,immutable=True)
            pages.append(dict(sha256=key,event_count=len(chunk),first_sequence=chunk[0]['sequence'],last_sequence=chunk[-1]['sequence'],previous_sha256=chunk[0]['previous_sha256'],last_sha256=chunk[-1]['event_sha256']))
            chunk.clear()
        with closing(sqlite3.connect(store.path.as_uri()+'?mode=ro',uri=True,timeout=5)) as connection:
            connection.row_factory=sqlite3.Row;connection.execute('PRAGMA query_only=ON');connection.execute('BEGIN');_schema(connection)
            for event in _iter(connection):
                candidate=chunk+[event]
                if chunk and (len(candidate)>100 or len(encoded(dict(schema_version=1,authority='audit_only',events=candidate)))>PAGE_BYTES):flush()
                chunk.append(event)
            flush()
        runs,days=indexes(pages,(strict_json((root/'pages'/(p['sha256']+'.json')).read_bytes())['events'] for p in pages))
        manifest=dict(schema_version=1,authority='audit_only',generated_at=datetime.now(timezone.utc).isoformat(),
                      watermark=dict(sequence=pages[-1]['last_sequence'] if pages else 0,event_sha256=pages[-1]['last_sha256'] if pages else None),pages=pages,runs=runs,days=days)
        manifest['snapshot_sha256']=digest(manifest)
        raw=encoded(manifest);require(len(raw)<=8388608 and len(pages)<=10000,'audit manifest exceeds bound')
        _publish(root/'manifest.json',raw)
        return manifest
