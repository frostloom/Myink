"""Human-only console over the original gate and read-only audit export.

The local metadata records publication commands, not Pi tasks or model charges.
No request can choose a host path, executable, image tag or deployment settings.
"""
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
import fcntl
import json
import os
import sqlite3
import stat
import uuid

from .audit import AuditStore, _path, _plain, digest, encoded, require, strict_json, hash_value
from .nightly_gate import BASE
from .product_commands import _write

REQUEST_FIELDS = frozenset('request_id actor_id cycle_id package_sha256 image_id source_sha256 comparison_sha256 decision'.split())
CANDIDATE_FIELDS = ('package_sha256', 'image_id', 'source_sha256', 'comparison_sha256')


def _uuid(value):
    require(isinstance(value, str) and str(uuid.UUID(value)) == value, 'canonical identifier required')
    return value


def request(value):
    require(isinstance(value, dict) and set(value) == REQUEST_FIELDS, 'closed publication decision required')
    for key in ('request_id', 'actor_id', 'cycle_id'): _uuid(value[key])
    require(value['decision'] in ('publish', 'defer'), 'human publication decision required')
    require(all(hash_value(value[k]) for k in ('package_sha256', 'source_sha256', 'comparison_sha256')), 'candidate digests required')
    require(isinstance(value['image_id'], str) and value['image_id'].startswith('sha256:') and hash_value(value['image_id'][7:]), 'immutable image required')
    return value


def _read(path):
    path = _path(path); _plain(path)
    require(path.stat().st_size <= 4194304, 'bounded console source required')
    return strict_json(path.read_bytes())


class Console:
    def __init__(self, gate, root, audit_path, export_root, metadata_path, *, publisher=None, publication_pin=None):
        self.gate = gate; self.root = _path(root); self.audit_path = _path(audit_path)
        self.export_root = _path(export_root); self.path = _path(metadata_path)
        require(self.path.parent.is_dir() and stat.S_IMODE(self.path.parent.stat().st_mode) == 0o700, 'private console metadata parent required')
        require(self.path not in (gate.path, gate.state, gate.billing), 'console metadata cannot replace original state')
        if gate.mode == 'ACTUAL':
            require(os.geteuid() == 0 and publisher is None and self.root == BASE/'nightly' and self.path == BASE/'state/admin-console.sqlite' and self.audit_path == BASE/'audit/state/events.sqlite' and self.export_root == BASE/'audit/export', 'fixed root console roles required')
            from .admin_publication import NativePublication
            publisher = NativePublication(gate, publication_pin)
            self._host_lock = (BASE/'control/admin-console.lock').open('rb')
            fcntl.flock(self._host_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            require(publisher is not None and not any(p.is_relative_to(BASE) for p in (self.root,self.path,self.audit_path,self.export_root)), 'isolated console publisher required')
        self.publisher = publisher
        if not self.path.exists():
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600); os.close(fd)
            with sqlite3.connect(self.path) as db:
                db.executescript("""CREATE TABLE console_commands(request_id TEXT PRIMARY KEY,input_sha256 TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,completed_at TEXT,reason TEXT,result TEXT);
                    CREATE UNIQUE INDEX one_active_publication ON console_commands(json_extract(payload,'$.cycle_id')) WHERE json_extract(payload,'$.decision')='publish' AND status IN ('recording','queued','running','uncertain','succeeded');
                    PRAGMA user_version=1;""")
        _plain(self.path)
        require(stat.S_IMODE(self.path.stat().st_mode) == 0o600, 'private console metadata required')
        with self._db() as db:
            db.execute("UPDATE console_commands SET status='uncertain',reason='host_restarted' WHERE status IN ('recording','queued','running')")

    @contextmanager
    def _db(self):
        _plain(self.path)
        db = sqlite3.connect(self.path.as_uri()+'?mode=rw', uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            require(db.execute('PRAGMA user_version').fetchone()[0] == 1, 'console metadata format required')
            db.execute('PRAGMA synchronous=FULL'); db.execute('BEGIN IMMEDIATE')
            yield db; db.commit()
        except BaseException: db.rollback(); raise
        finally: db.close()

    @contextmanager
    def _publication_lock(self):
        if self.gate.mode != 'ACTUAL': yield; return
        with (BASE/'control/nightly.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def _candidate(self, state):
        if state['package_sha256'] is None: return None
        folder = self.root/state['cycle_id']/'bundle'; manifest = _read(folder/'manifest.json')
        require(digest(manifest) == state['package_sha256'], 'sealed console candidate changed')
        result = dict(package_sha256=state['package_sha256'])
        result.update({k: manifest[k] for k in ('image_id','source_sha256','comparison_sha256','baseline_sha256')})
        for file, key in (('changes','changes_sha256'), ('evaluation','evaluation_sha256'), ('comparison','comparison_sha256')):
            value = _read(folder/(file+'.json')); require(digest(value) == manifest[key], 'candidate review data changed')
            if file == 'evaluation':
                result[file] = {k:value[k] for k in ('checker','independent_review','sdk_verified','model_requests','known_cost_microyuan','tool_count','evidence_domain','online_improvement_proven')}
            elif file == 'comparison':
                result[file] = {k: value[k] for k in ('anchor','day_offset','status','online_improvement_proven','test_cases')}
            else: result[file] = value
        result['publication_available'] = state['phase'] == 'awaiting_approval' and self.publisher.available()
        return result

    def status(self):
        state = self.gate.status(); candidate = self._candidate(state)
        with self._db() as db:
            latest = db.execute('SELECT request_id FROM console_commands ORDER BY rowid DESC LIMIT 1').fetchone()
        saved = self._deployment(state['cycle_id']) if state['cycle_id'] else None
        deployment = {k:saved['packet'][k] for k in ('deployment_id','deployed_at','image_id','source_sha256','comparison_sha256')} if saved else None
        return dict(schema_version=1, observed_at=self.gate.clock().isoformat(), **state, candidate=candidate, deployment=deployment,
                    next_assessment_at=self._due(saved['packet']['deployed_at']) if saved and state['phase']=='observing' else None,
                    latest_operation=self.operation(latest[0]) if latest else None)

    def _deployment(self, cycle):
        with self.gate._connection() as db:
            row=self.gate._row(db,cycle)
            return strict_json(row['deployment']) if row['deployment'] else None

    @staticmethod
    def _due(deployed_at):
        from .audit import utc, SHANGHAI
        return utc((utc(deployed_at).astimezone(SHANGHAI)+timedelta(days=1)).replace(hour=3,minute=0,second=0,microsecond=0)).isoformat()

    def operation(self, identity):
        _uuid(identity)
        with self._db() as db: row = db.execute('SELECT * FROM console_commands WHERE request_id=?', (identity,)).fetchone()
        if row is None: raise LookupError('unknown console operation')
        payload = strict_json(row['payload'])
        return dict(request_id=identity, actor_id=payload['actor_id'], cycle_id=payload['cycle_id'], package_sha256=payload['package_sha256'], decision=payload['decision'],
                    status=row['status'], created_at=row['created_at'], completed_at=row['completed_at'], reason=row['reason'])

    def _finish(self, identity, status, reason=None):
        with self._db() as db: db.execute('UPDATE console_commands SET status=?,reason=?,completed_at=? WHERE request_id=?', (status,reason,self.gate.clock().isoformat(),identity))
        return self.operation(identity)

    def _audit(self, packet, stage, status):
        event = dict(kind='plan' if stage != 'deployed' else 'deployment', status=status, run_id='admin-'+packet['request_id'], occurred_at=self.gate.clock().isoformat(),
            summary='Administrator publication decision and verified host outcome.',
            details=dict(reference='admin.publication.'+stage+'.v1',operation_id=packet['cycle_id'],decision=packet['decision'],request_summary='administrator:'+packet['actor_id'],model_requests=0,known_cost_microyuan=0),
            version=dict(candidate_sha256=packet['source_sha256'],image_ids=dict(python=packet['image_id'])),changes=[],
            evidence=[dict(kind='authenticated_admin_decision',sha256=digest(packet),verified=True,evidence_domain='offline' if self.gate.mode=='ACTUAL' else 'synthetic')],followups=[],mode=self.gate.mode,
            evidence_domain='online_business' if stage=='deployed' and self.gate.mode=='ACTUAL' else 'offline' if self.gate.mode=='ACTUAL' else 'synthetic')
        if stage=='deployed':
            saved=self._deployment(packet['cycle_id']);require(saved is not None,'verified deployment receipt required')
            event['version']['deployment_id']=saved['packet']['deployment_id']
            event['evidence'].append(dict(kind='physical_deployment_receipt',sha256=saved['sha256'],verified=True,evidence_domain=event['evidence_domain']))
            event['followups']=[dict(test_id='nightly-'+kind+'-'+packet['cycle_id'],scheduled_for=self._due(saved['packet']['deployed_at']),target_run_id=self.gate.status()['task_id'] or packet['cycle_id'],target_version_sha256=packet['source_sha256'],criterion='Frozen regression and cleanup.' if kind=='regression' else 'At least 20 version-bound complete business samples without confounders.',kind=kind,status='planned') for kind in ('regression','metrics')]
        store=AuditStore(self.audit_path);store.append('admin:'+packet['request_id']+':'+stage,event);store.export(self.export_root)
        if self.gate.mode=='ACTUAL':
            from .nightly_binding import _audit_outputs, _ordinary
            for path in _audit_outputs(dict(audit_path=str(self.audit_path),export_root=str(self.export_root))): _ordinary(path,self.gate.mode)

    def submit(self, packet):
        request(packet); pin = digest(packet)
        with self._db() as db:
            old = db.execute('SELECT input_sha256 FROM console_commands WHERE request_id=?',(packet['request_id'],)).fetchone()
        if old:
            require(old[0] == pin, 'console request identity conflict')
            return self.operation(packet['request_id'])
        state=self.gate.status();require(state['phase']=='awaiting_approval' and state['cycle_id']==packet['cycle_id'], 'candidate is not waiting for publication')
        candidate=self._candidate(state);require(all(packet[k]==candidate[k] for k in CANDIDATE_FIELDS), 'stale console candidate')
        require(packet['decision']=='defer' or candidate['publication_available'], 'publication channel unavailable')
        try:
            with self._db() as db:
                active=db.execute("SELECT request_id FROM console_commands WHERE json_extract(payload,'$.cycle_id')=? AND json_extract(payload,'$.decision')='publish' AND status IN ('recording','queued','running','uncertain','succeeded')",(packet['cycle_id'],)).fetchone()
                require(active is None or active[0]==packet['request_id'],'publication already accepted; defer is not cancellation')
                db.execute('INSERT INTO console_commands(request_id,input_sha256,payload,status,created_at) VALUES(?,?,?,?,?)', (packet['request_id'],pin,encoded(packet).decode(),'recording',self.gate.clock().isoformat()))
        except sqlite3.IntegrityError:
            with self._db() as db:
                old=db.execute('SELECT input_sha256 FROM console_commands WHERE request_id=?',(packet['request_id'],)).fetchone()
            require(old is not None and old[0]==pin, 'another publication command already exists')
            return self.operation(packet['request_id'])
        try: self._audit(packet,'decision','no_release' if packet['decision']=='defer' else 'planned')
        except Exception:
            self._finish(packet['request_id'],'uncertain','audit_unavailable');raise
        if packet['decision']=='defer':return self._finish(packet['request_id'],'deferred')
        with self._db() as db:db.execute("UPDATE console_commands SET status='queued' WHERE request_id=? AND status='recording'",(packet['request_id'],))
        return self.operation(packet['request_id'])

    def process(self, identity):
        _uuid(identity)
        with self._db() as db:
            row=db.execute('SELECT * FROM console_commands WHERE request_id=?',(identity,)).fetchone()
            if row is None: raise LookupError('unknown console operation')
            if row['status']!='queued': packet=None
            else:
                packet=strict_json(row['payload']);db.execute("UPDATE console_commands SET status='running' WHERE request_id=?",(identity,))
        if packet is None:return self.operation(identity)
        try:
            with self._publication_lock():
                state=self.gate.status();candidate=self._candidate(state)
                require(state['phase']=='awaiting_approval' and state['cycle_id']==packet['cycle_id'] and candidate is not None and all(candidate[k]==packet[k] for k in CANDIDATE_FIELDS), 'candidate changed before execution')
                self._audit(packet,'started','running')
                bundle=self.root/packet['cycle_id']/'bundle';plan=self.publisher.prepare(packet['cycle_id'],bundle)
                folder=BASE/'config/human-approvals' if self.gate.mode=='ACTUAL' else bundle.parent/'human-approvals'
                if not folder.exists(): folder.mkdir(mode=0o750 if self.gate.mode=='ACTUAL' else 0o700)
                approval=dict(schema='pi-nightly-human-approval-v1',mode=self.gate.mode,issuer='human_operator',cycle_id=packet['cycle_id'],package_sha256=packet['package_sha256'],approved_actions=['deploy'],issued_at=self.gate.clock().isoformat(),expires_at=(self.gate.clock()+timedelta(hours=1)).isoformat())
                path=folder/('console-'+identity+'.json');_write(path,approval)
                if self.gate.mode=='ACTUAL':
                    import pwd
                    os.chown(path,0,pwd.getpwnam('ubuntu').pw_gid);path.chmod(0o640)
                self.gate.approve(packet['cycle_id'],path,digest(approval))
                self.publisher.publish(packet['cycle_id'],bundle,plan)
                require(self.gate.status()['phase']=='observing','deployment is not physically verified')
                self._audit(packet,'deployed','passed')
            return self._finish(identity,'succeeded')
        except Exception:
            try:phase=self.gate.status()['phase']
            except Exception:phase='unknown'
            status='uncertain' if phase!='awaiting_approval' else 'failed'
            self._finish(identity,status,'publication_unconfirmed')
            try:self._audit(packet,'failed','uncertain' if status=='uncertain' else 'failed')
            except Exception:pass
            return self.operation(identity)
