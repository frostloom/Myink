"""Trusted single-hop manager relocation; original rows and evidence stay immutable."""
from contextlib import contextmanager,closing
import fcntl
import json
import os
from pathlib import Path
import stat
import sqlite3

from .development_inputs import digest,file_hash,ledger_snapshot,path,read_json
from .ledger import Ledger,_json
from . import state_custody as custody

FIELDS={'schema','transfer_id','mode','source_state','source_billing','destination_state',
        'destination_billing','host_sha256','manager_snapshot_sha256','source_operation_ids',
        'event_hwm','archives','authorization_reference','source_billing_binding','billing_freeze_sha256'}
KIND='manager_relocation'


def require(value,message):
    if not value:raise ValueError(message)


def active(billing):
    with Ledger(billing,existing=True).transaction() as db:custody.guard(db,billing)


def _custody(billing,*,transfer_id=None):
    # Inspection must work with the original ledger mounted read-only. Require
    # a checkpointed snapshot before immutable mode, never ignore live WAL.
    before=ledger_snapshot(billing)
    with closing(sqlite3.connect(Path(billing).as_uri()+'?mode=ro&immutable=1',uri=True,timeout=5)) as db:
        db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        latest,_=custody._chain(db)
        activation=None
        if transfer_id is not None:
            from .tool_proof import strict_json
            values=[strict_json(r['payload']) for r in db.execute("SELECT payload FROM events WHERE kind='state-custody' ORDER BY id")]
            matches=[v for v in values if v['phase']=='active' and v['transfer_id']==transfer_id]
            require(len(matches)==1,'original billing activation proof required')
            activation=matches[0]
    require(ledger_snapshot(billing)==before,'billing changed during custody inspection')
    if transfer_id is not None:return latest,activation
    require(latest is not None,'manager relocation requires billing custody')
    return latest


@contextmanager
def locked(state,billing):
    from . import manager
    state,billing=manager._paths(state,billing)
    lockpath=state.with_suffix('.manager.lock')
    fd=os.open(path(lockpath),os.O_RDWR|os.O_CREAT,0o600)
    with os.fdopen(fd,'a+b') as lock:
        manager._plain(path(lockpath,private=True))
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('manager busy') from None
        yield state,billing


def _retired(rows,tasks):
    from . import manager
    require(not manager._unresolved(rows),'unresolved manager dispatch prevents relocation')
    require(all(r['status']!='pending' for r in rows.values()),'pending manager record prevents relocation')
    for task in tasks:
        key=task['operation_id'];dispatch=rows.get(key+':dispatch')
        require(task['status']=='done' and (rows.get(key+':cancel',{}).get('status')=='done'
            or dispatch and (dispatch['status'] in ('done','blocked','failed')
                            or manager._resolved(rows,key+':dispatch'))),'queued manager task prevents relocation')


def _logical_path(value):
    require(isinstance(value,(str,Path)),'logical identity path required')
    raw=str(value);p=Path(raw)
    require(p.is_absolute() and str(p)==raw and '..' not in p.parts
            and not any(c in raw for c in ',\r\n\0'),'absolute normalized logical identity required')
    return p


def _manifest(value):
    require(isinstance(value,dict) and set(value)==FIELDS and value['schema']=='pi-manager-relocation-v1','invalid relocation schema')
    custody._transfer(value['transfer_id']);custody._reference(value['authorization_reference'])
    require(value['mode'] in ('ACTUAL','SIMULATED'),'invalid relocation mode')
    for name in ('source_state','source_billing','destination_state','destination_billing'):
        require(isinstance(value[name],str),'logical identity string required');_logical_path(value[name])
    require(custody._hex(value['host_sha256']) and custody._hex(value['manager_snapshot_sha256']),'invalid relocation hash')
    custody._binding(value['source_billing_binding'])
    require(value['source_billing_binding']['ledger_path']==value['source_billing'] and custody._hex(value['billing_freeze_sha256']),'invalid original billing freeze binding')
    ids=value['source_operation_ids']
    require(isinstance(ids,list) and 0<len(ids)<=10000 and all(isinstance(x,str) for x in ids)
            and ids==sorted(set(ids)) and type(value['event_hwm']) is int and value['event_hwm']>0,'invalid relocation prefix')
    require(isinstance(value['archives'],dict) and len(value['archives'])<=2000,'invalid evidence archive')
    for original,item in value['archives'].items():
        path(original)
        require(isinstance(item,dict) and set(item)=={'relative_path','sha256'}
                and custody._hex(item['sha256']) and item['relative_path']=='evidence/'+item['sha256']+'.json','invalid archived evidence binding')
    return value


def _prefix(snap,value):
    ids=set(value['source_operation_ids'])
    rows=[r for r in snap['operations'] if r['operation_id'] in ids]
    events=[r for r in snap['events'] if r['id']<=value['event_hwm']]
    require(len(rows)==len(ids) and events and events[-1]['id']==value['event_hwm'],'incomplete relocation prefix')
    from .tool_proof import strict_json
    intents=[strict_json(e['payload']).get('operation_id') for e in events if e['kind']=='intent']
    require(len(intents)==len(ids) and set(intents)==ids,'incomplete source operation coverage')
    require(digest(dict(operations=rows,events=events,limits=None))==value['manager_snapshot_sha256'],'manager source snapshot drift')
    return rows


def context(state,billing,mode,snap,rows):
    records=[r for r in rows.values() if r['kind']==KIND]
    if not records:return None
    require(len(records)==1,'subsequent manager relocation needs explicit support')
    row=records[0];payload=row['payload']
    from .tool_proof import strict_json
    raw=next(r for r in snap['operations'] if r['operation_id']==row['operation_id'])
    require(strict_json(raw['payload'])==payload and strict_json(raw['evidence'])==row['evidence'],'strict relocation record required')
    require(isinstance(payload,dict) and set(payload)==FIELDS|{'archive_root','destination_authorization_reference'},'invalid relocation record')
    custody._reference(payload['destination_authorization_reference'])
    value=_manifest({k:v for k,v in payload.items() if k not in ('archive_root','destination_authorization_reference')})
    require(row['operation_id']=='manager:relocation:'+value['transfer_id'] and row['status']=='done'
            and row['evidence']==dict(verified=True,binding=digest(payload)),'invalid relocation receipt')
    expected_events={
        'intent':dict(operation_id=row['operation_id'],kind=KIND,payload=payload,schema_version=1),
        'receipt':dict(operation_id=row['operation_id'],status='done',evidence=row['evidence'],schema_version=1)}
    mirror_ids={}
    for kind,expected in expected_events.items():
        matches=[]
        for event in snap['events']:
            if event['kind']==kind:
                decoded=Ledger._decode(event['payload'])
                if decoded.get('operation_id')==row['operation_id']:
                    matches.append(strict_json(event['payload']));mirror_ids[kind]=event['id']
        require(matches==[expected],'relocation intent or receipt event mismatch')
    require(mirror_ids==dict(intent=value['event_hwm']+1,receipt=value['event_hwm']+2),'incomplete relocation transition prefix')
    require(mode==value['mode'] and str(state)==value['destination_state']
            and str(billing)==value['destination_billing'],'manager relocation destination drift')
    current=custody.current_binding(billing)
    require(current==dict(host_sha256=value['host_sha256'],ledger_path=str(billing)),'manager relocation native owner drift')
    owner,activation=_custody(billing,transfer_id=value['transfer_id'])
    require(activation['source']==value['source_billing_binding'] and activation['parent_sha256']==value['billing_freeze_sha256'],
            'original billing freeze identity drift')
    require((owner['phase']=='active' and owner['transfer_id']==value['transfer_id'] and owner['destination']==current)
            or (owner['phase']=='frozen' and owner['source']==current),'manager relocation billing custody drift')
    old=_prefix(snap,value);oldrows={r['operation_id']:Ledger._decode(r['payload']) for r in old}
    retired={r['operation_id']:dict(r,payload=Ledger._decode(r['payload']),evidence=Ledger._decode(r['evidence']) if r['evidence'] is not None else None) for r in old}
    _retired(retired,[r for r in retired.values() if r['kind']=='manager_task'])
    require(row['operation_id'] not in oldrows,'self-referential relocation prefix')
    archive_root=path(payload['archive_root'])
    require(archive_root.is_dir() and stat.S_IMODE(archive_root.stat().st_mode)==0o700,'private archive root required')
    from . import manager
    for protected in manager._roles(state)+manager._ledger_roles(billing):manager._disjoint(archive_root,protected)
    needed={}
    for item in old:
        if item['kind']=='manager_reconciliation':
            p=oldrows[item['operation_id']]
            needed.update({p['audit_path']:p['audit_sha256'],p['review_path']:p['review_sha256']})
    require(set(needed)==set(value['archives']),'incomplete historical evidence archive')
    mapped={}
    from .selection_abandonment import _artifact
    for original,sha in needed.items():
        entry=value['archives'][original];require(entry['sha256']==sha,'historical evidence identity drift')
        target=archive_root/entry['relative_path'];_artifact(target,sha);mapped[original]=str(target)
    return dict(value=value,known={row['operation_id']},ids=set(oldrows),artifacts=mapped,archive_root=archive_root)


def prepare(state,billing,*,destination_state,root,mode='ACTUAL',authorization_reference):
    from . import manager
    from .backup import snapshot_ledger
    custody._reference(authorization_reference);root=path(root);destination_state=_logical_path(destination_state)
    with locked(state,billing) as (state,billing):
        _,_,rows,tasks,snap=manager._snapshot(state,billing,mode)
        require(not any(r['kind']==KIND for r in rows.values()),'subsequent manager relocation needs explicit support')
        _retired(rows,tasks)
        owner=_custody(billing)
        require(owner['phase']=='frozen' and owner['source']==custody.current_binding(billing),'source billing must be frozen at original owner')
        for protected in manager._roles(state)+manager._ledger_roles(billing):manager._disjoint(root,protected)
        for task in tasks:
            for protected in task['payload']['resources']['inputs']+task['payload']['resources']['outputs']:
                manager._disjoint(root,Path(protected))
        require(not root.exists() and root.parent.is_dir() and stat.S_IMODE(root.parent.stat().st_mode)==0o700,'fresh private export root required')
        archives={};contents={};total=0
        from .selection_abandonment import _artifact
        for row in rows.values():
            if row['kind']=='manager_reconciliation':
                p=row['payload']
                for key in ('audit','review'):
                    original=p[key+'_path'];sha=p[key+'_sha256'];raw=_artifact(original,sha)
                    archives[original]=dict(relative_path='evidence/'+sha+'.json',sha256=sha)
                    contents[sha]=raw;total+=len(raw)
        require(total<=16*1024**2,'bounded evidence export required')
        value=dict(schema='pi-manager-relocation-v1',transfer_id=owner['transfer_id'],mode=mode,
            source_state=str(state),source_billing=str(billing),destination_state=str(destination_state),
            destination_billing=owner['destination']['ledger_path'],host_sha256=owner['destination']['host_sha256'],
            manager_snapshot_sha256=snap['sha256'],source_operation_ids=sorted(rows),event_hwm=snap['events'][-1]['id'],
            archives=archives,authorization_reference=authorization_reference,
            source_billing_binding=owner['source'],billing_freeze_sha256=custody._hash(owner))
        _manifest(value)
        root.mkdir(mode=0o700);(root/'evidence').mkdir(mode=0o700)
        for sha,raw in contents.items():
            target=root/'evidence'/ (sha+'.json')
            with target.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            target.chmod(0o600)
        export=root/'manager.sqlite';snapshot_ledger(manager.Ledger(state,existing=True),export)
        require(ledger_snapshot(export)['sha256']==snap['sha256'],'manager changed during export')
        target=root/'manifest.json'
        with target.open('x') as stream:json.dump(value,stream,sort_keys=True,allow_nan=False);stream.flush();os.fsync(stream.fileno())
        target.chmod(0o600)
        return dict(manifest_path=str(target),manager_path=str(export))


def apply(state,billing,manifest_path,*,mode='ACTUAL',authorization_reference):
    from . import manager
    custody._reference(authorization_reference)
    manifest_path=path(manifest_path,private=True);manager._plain(manifest_path)
    value=_manifest(read_json(manifest_path))
    with locked(state,billing) as (state,billing):
        require(mode==value['mode'] and str(state)==value['destination_state']
                and str(billing)==value['destination_billing'],'manager relocation destination mismatch')
        active(billing);owner=_custody(billing)
        require(owner['transfer_id']==value['transfer_id'],'manager relocation transfer mismatch')
        snap=ledger_snapshot(state);require(snap['sha256']==value['manager_snapshot_sha256'],'manager source snapshot changed')
        payload=dict(value,archive_root=str(manifest_path.parent),destination_authorization_reference=authorization_reference)
        op='manager:relocation:'+value['transfer_id']
        record=dict(operation_id=op,kind=KIND,payload=_json(payload),status='done',
                    evidence=_json(dict(verified=True,binding=digest(payload))),schema_version=1)
        hwm=snap['events'][-1]['id']
        mirrors=[dict(id=hwm+1,kind='intent',payload=_json(dict(operation_id=op,kind=KIND,payload=payload,schema_version=1)),schema_version=1),
                 dict(id=hwm+2,kind='receipt',payload=_json(dict(operation_id=op,status='done',evidence=Ledger._decode(record['evidence']),schema_version=1)),schema_version=1)]
        simulated=dict(snap,operations=sorted(snap['operations']+[record],key=lambda r:r['operation_id']),events=snap['events']+mirrors)
        manager._validate_snapshot(state,billing,mode,simulated)
        decoded={r['operation_id']:dict(r,payload=Ledger._decode(r['payload'])) for r in snap['operations']}
        _retired(decoded,[r for r in decoded.values() if r['kind']=='manager_task'])
        with manager.Ledger(state,existing=True).transaction() as db:
            current=dict(operations=[dict(r) for r in db.execute('SELECT * FROM operations ORDER BY operation_id')],
                         events=[dict(r) for r in db.execute('SELECT * FROM events ORDER BY id')],limits=None)
            require(digest(current)==snap['sha256'],'manager changed before relocation commit')
            db.execute('INSERT INTO operations VALUES (?,?,?,?,?,1)',(op,KIND,_json(payload),'done',record['evidence']))
            for offset,(kind,event) in enumerate([
                    ('intent',dict(operation_id=op,kind=KIND,payload=payload,schema_version=1)),
                    ('receipt',dict(operation_id=op,status='done',evidence=Ledger._decode(record['evidence']),schema_version=1))],1):
                cursor=db.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',(kind,_json(event)))
                require(cursor.lastrowid==hwm+offset,'actual relocation transition id drift')
            actual=dict(operations=[dict(r) for r in db.execute('SELECT * FROM operations ORDER BY operation_id')],
                        events=[dict(r) for r in db.execute('SELECT * FROM events ORDER BY id')],limits=None)
            require(digest(actual)==digest({k:simulated[k] for k in actual}),'actual relocation transition content drift')
        return dict(relocated=True,transfer_id=value['transfer_id'],mode=mode)
