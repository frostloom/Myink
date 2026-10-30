"""Human approval metadata only: never a second manager, fee scope or publisher.

The original manager executes tasks. Trusted callers freeze verified artifacts,
read root-issued approvals, and attest actual deployments. Models get none of
these methods. Waiting state persists independently of dates and process restarts.
"""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone,date
from hashlib import sha256
import json,os,sqlite3,stat,sys,uuid
from pathlib import Path
from .audit import _path,_plain,digest,encoded,hash_value,require,strict_json,utc

BASE=Path('/home/ubuntu/myink-pi-managed')
DB_VERSION=7401
ACTIONS=frozenset(('github_push','registry_push','deploy'))
PACKAGE_FIELDS=set('schema baseline_sha256 source_sha256 patch_sha256 evaluation_sha256 image_id image_artifact_sha256 comparison_sha256 changes_sha256'.split())
APPROVAL_FIELDS=set('schema mode issuer cycle_id package_sha256 approved_actions issued_at expires_at'.split())
DEPLOYMENT_FIELDS=set('schema mode issuer cycle_id package_sha256 approval_sha256 image_id source_sha256 comparison_sha256 deployment_id deployed_at'.split())
SCHEMA="""
CREATE TABLE approval_identity(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
CREATE TABLE approval_cycles(cycle_id TEXT PRIMARY KEY,night TEXT NOT NULL UNIQUE,phase TEXT NOT NULL CHECK(phase IN ('preparing','awaiting_approval','awaiting_deployment','observing','completed','blocked')),created_at TEXT NOT NULL,package TEXT,approval TEXT,deployment TEXT,result_sha256 TEXT);
CREATE TABLE approval_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,cycle_id TEXT,kind TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TRIGGER approval_identity_no_update BEFORE UPDATE ON approval_identity BEGIN SELECT RAISE(ABORT,'immutable identity');END;
CREATE TRIGGER approval_identity_no_delete BEFORE DELETE ON approval_identity BEGIN SELECT RAISE(ABORT,'immutable identity');END;
CREATE TRIGGER approval_events_no_update BEFORE UPDATE ON approval_events BEGIN SELECT RAISE(ABORT,'append only');END;
CREATE TRIGGER approval_events_no_delete BEFORE DELETE ON approval_events BEGIN SELECT RAISE(ABORT,'append only');END;
CREATE TRIGGER approval_cycles_no_delete BEFORE DELETE ON approval_cycles BEGIN SELECT RAISE(ABORT,'cycles cannot disappear');END;
CREATE TRIGGER approval_cycles_identity BEFORE UPDATE ON approval_cycles WHEN NEW.cycle_id!=OLD.cycle_id OR NEW.night!=OLD.night OR NEW.created_at!=OLD.created_at BEGIN SELECT RAISE(ABORT,'immutable cycle');END;
CREATE TRIGGER approval_cycles_package BEFORE UPDATE ON approval_cycles WHEN OLD.package IS NOT NULL AND NEW.package IS NOT OLD.package BEGIN SELECT RAISE(ABORT,'immutable package');END;
CREATE TRIGGER approval_cycles_terminal BEFORE UPDATE ON approval_cycles WHEN OLD.phase='completed' BEGIN SELECT RAISE(ABORT,'immutable completed cycle');END;
"""


def _uuid(value):
    require(isinstance(value,str) and str(uuid.UUID(value))==value,'canonical cycle identity required');return value


def _package(value):
    require(isinstance(value,dict) and set(value)==PACKAGE_FIELDS and value['schema']=='pi-nightly-artifact-v1','closed artifact manifest required')
    require(all(hash_value(value[k]) for k in PACKAGE_FIELDS-{'schema','image_id'}),'artifact digests required')
    require(isinstance(value['image_id'],str) and value['image_id'].startswith('sha256:') and hash_value(value['image_id'][7:]),'immutable local image ID required');return value


def _paths(store,state,billing,mode):
    require(mode in ('ACTUAL','SIMULATED'),'explicit approval mode required');store,state,billing=map(_path,(store,state,billing))
    require(store.parent.is_dir() and stat.S_IMODE(store.parent.stat().st_mode)==0o700,'private approval metadata parent required')
    from .local_cycle import _ledger_roles,_disjoint
    from .manager import _roles
    for left in _ledger_roles(store):
        for right in _roles(state)+_ledger_roles(billing):_disjoint(left,right)
    if mode=='ACTUAL':require(sys.platform=='linux' and store==BASE/'state/nightly-approval.sqlite' and state==BASE/'state/actual-manager.sqlite' and billing==BASE/'state/ledger.sqlite','original ACTUAL manager and fee roles required')
    else:require(not any(v.is_relative_to(BASE) for v in (store,state,billing)),'simulation cannot target original state')
    return store,state,billing


def _binding(state,billing,mode):
    from .manager import _snapshot
    _,_,rows,_,_=_snapshot(state,billing,mode);header=rows['manager:identity']
    return dict(schema='pi-nightly-approval-state-v1',mode=mode,manager_path=str(state),billing_path=str(billing),manager_identity_sha256=digest(dict(payload=header['payload'],evidence=header['evidence'])))


class ApprovalGate:
    @staticmethod
    def initialize(store,state,billing,*,mode):
        store,state,billing=_paths(store,state,billing,mode);require(not store.exists(),'new approval metadata required');binding=_binding(state,billing,mode)
        fd=os.open(store,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
        with sqlite3.connect(store) as c:
            c.executescript(SCHEMA);c.execute('PRAGMA user_version='+str(DB_VERSION));c.execute('INSERT INTO approval_identity VALUES(1,?)',(encoded(binding).decode(),))
            c.execute('INSERT INTO approval_events(cycle_id,kind,payload) VALUES(NULL,?,?)',('initialized',encoded(binding).decode()))
        return dict(initialized=True,authority='approval_metadata_only')

    def __init__(self,store,state,billing,*,mode,clock=None):
        require(mode!='ACTUAL' or clock is None,'ACTUAL forbids an injected clock')
        self.path,self.state,self.billing=_paths(store,state,billing,mode);self.mode=mode;self.clock=clock or (lambda:datetime.now(timezone.utc))
        with self._connection() as c:
            identity=strict_json(c.execute('SELECT payload FROM approval_identity WHERE id=1').fetchone()[0])
            require(identity==_binding(self.state,self.billing,mode),'original manager binding changed');self.identity=identity

    @contextmanager
    def _connection(self,write=False):
        _plain(self.path);require(stat.S_IMODE(self.path.stat().st_mode)==0o600 and self.path.stat().st_size<=64*1024**2,'bounded private approval metadata required')
        c=sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=5,isolation_level=None);c.row_factory=sqlite3.Row
        try:
            require(c.execute('PRAGMA user_version').fetchone()[0]==DB_VERSION and {v[0] for v in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}=={'approval_identity','approval_cycles','approval_events','sqlite_sequence'},'approval metadata format required')
            if write:c.execute('PRAGMA synchronous=FULL');c.execute('BEGIN IMMEDIATE')
            yield c
            if write:c.commit()
        except BaseException:
            if write:c.rollback()
            raise
        finally:c.close()

    def _record(self,c,cycle,kind,value):c.execute('INSERT INTO approval_events(cycle_id,kind,payload) VALUES(?,?,?)',(cycle,kind,encoded(value).decode()))

    def _current(self,c):
        rows=c.execute("SELECT * FROM approval_cycles WHERE phase!='completed' ORDER BY rowid LIMIT 2").fetchall();require(len(rows)<=1,'multiple active approval cycles');return rows[0] if rows else None

    def _row(self,c,cycle):
        _uuid(cycle);row=c.execute('SELECT * FROM approval_cycles WHERE cycle_id=?',(cycle,)).fetchone();require(row is not None,'unknown cycle');return row

    def _trusted(self,path,pin,kind):
        path=_path(path);_plain(path);s=path.stat();require(s.st_size<=65536 and hash_value(pin) and sha256(path.read_bytes()).hexdigest()==pin,'operator receipt drift')
        if self.mode=='ACTUAL':require(path.parent==BASE/'config'/('human-approvals' if kind=='approval' else 'deployment-receipts') and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o640 and path.parent.stat().st_uid==0 and stat.S_IMODE(path.parent.stat().st_mode)==0o750,'root-issued operator receipt required')
        else:require(stat.S_IMODE(s.st_mode)==0o600 and stat.S_IMODE(path.parent.stat().st_mode)==0o700 and s.st_uid==os.geteuid(),'private simulated operator receipt required')
        return strict_json(path.read_bytes())

    def _approval(self,row,*,current=True):
        require(row['approval'] is not None,'human approval required');saved=strict_json(row['approval']);a=self._trusted(saved['path'],saved['sha256'],'approval')
        require(a==saved['packet'] and set(a)==APPROVAL_FIELDS and a['schema']=='pi-nightly-human-approval-v1' and a['mode']==self.mode and a['issuer']=='human_operator' and a['cycle_id']==row['cycle_id'] and a['package_sha256']==digest(strict_json(row['package'])),'approval is not bound to this artifact')
        acts=a['approved_actions'];require(isinstance(acts,list) and acts and len(acts)==len(set(acts)) and set(acts)<=ACTIONS,'fixed human-approved actions required')
        issued,expires=utc(a['issued_at']),utc(a['expires_at']);require(issued<expires and expires-issued<=timedelta(days=7) and issued<=utc(self.clock()),'invalid approval lifetime')
        if current:require(utc(self.clock())<expires,'human approval expired')
        return saved

    def _description(self,row):
        if row is None or row['phase']=='completed':return dict(phase='idle',cycle_id=None,package_sha256=None)
        phase=row['phase'];package=strict_json(row['package']) if row['package'] else None
        if phase=='awaiting_deployment':
            try:self._approval(row)
            except (ValueError,OSError,TypeError,KeyError):phase='awaiting_approval'
        if phase=='observing':
            try:
                d=strict_json(row['deployment']);require(self._trusted(d['path'],d['sha256'],'deployment')==d['packet'],'deployment receipt drift')
            except (ValueError,OSError,TypeError,KeyError):phase='blocked'
        return dict(phase=phase,cycle_id=row['cycle_id'],package_sha256=digest(package) if package else None)

    def status(self):
        with self._connection() as c:return self._description(self._current(c))

    def begin(self,cycle,night):
        _uuid(cycle);require(isinstance(night,str) and date.fromisoformat(night).isoformat()==night,'canonical night date required')
        with self._connection(True) as c:
            active=self._current(c)
            if active is not None:return dict(self._description(active),claimed=False)
            if c.execute('SELECT 1 FROM approval_cycles WHERE night=? OR cycle_id=?',(night,cycle)).fetchone():return dict(phase='idle',cycle_id=None,package_sha256=None,claimed=False)
            require(_binding(self.state,self.billing,self.mode)==self.identity,'manager binding revoked')
            c.execute("INSERT INTO approval_cycles(cycle_id,night,phase,created_at) VALUES(?,?,'preparing',?)",(cycle,night,utc(self.clock()).isoformat()));self._record(c,cycle,'claimed',dict(night=night))
        return dict(self.status(),claimed=True)

    def ready(self,cycle,package):
        _package(package);raw=encoded(package).decode()
        with self._connection(True) as c:
            row=self._row(c,cycle)
            if row['package'] is not None:require(row['package']==raw,'sealed artifact cannot change')
            else:
                require(row['phase']=='preparing','preparation is no longer active');c.execute("UPDATE approval_cycles SET phase='awaiting_approval',package=? WHERE cycle_id=?",(raw,cycle));self._record(c,cycle,'artifact_ready',dict(package_sha256=digest(package)))
        return self.status()

    def approve(self,cycle,path,pin):
        a=self._trusted(path,pin,'approval');saved=dict(path=str(_path(path)),sha256=pin,packet=a)
        with self._connection(True) as c:
            row=self._row(c,cycle);require(row['phase'] in ('awaiting_approval','awaiting_deployment'),'artifact is not waiting for approval')
            proposed=dict(row);proposed['approval']=encoded(saved).decode();self._approval(proposed)
            if row['approval']!=proposed['approval']:
                c.execute("UPDATE approval_cycles SET phase='awaiting_deployment',approval=? WHERE cycle_id=?",(proposed['approval'],cycle));self._record(c,cycle,'human_approved',dict(approval_sha256=pin,package_sha256=a['package_sha256'],actions=a['approved_actions']))
        return self.status()

    def require_action(self,cycle,action):
        require(action in ACTIONS|{'observe_metrics'},'unknown gated action')
        with self._connection() as c:
            row=self._row(c,cycle);phase=self._description(row)['phase']
            if action=='observe_metrics':require(phase=='observing','verified actual deployment required before observing')
            else:require(phase=='awaiting_deployment' and action in self._approval(row)['packet']['approved_actions'],'this action lacks current human approval')
        return dict(allowed=True,cycle_id=cycle,action=action)

    def deployed(self,cycle,path,pin):
        d=self._trusted(path,pin,'deployment');require(isinstance(d,dict) and set(d)==DEPLOYMENT_FIELDS and d['schema']=='pi-nightly-deployment-receipt-v1' and d['mode']==self.mode and d['issuer']=='trusted_deployment_verifier' and d['cycle_id']==cycle and isinstance(d['deployment_id'],str) and 0<len(d['deployment_id'])<=128,'trusted deployment receipt required')
        saved=dict(path=str(_path(path)),sha256=pin,packet=d)
        with self._connection(True) as c:
            row=self._row(c,cycle);require(row['phase'] in ('awaiting_deployment','observing'),'cycle is not waiting for deployment');a=self._approval(row,current=False);package=_package(strict_json(row['package']))
            require('deploy' in a['packet']['approved_actions'] and d['approval_sha256']==a['sha256'] and d['package_sha256']==digest(package) and all(d[k]==package[k] for k in ('image_id','source_sha256','comparison_sha256')),'deployed image/source/parameters do not match approval')
            require(utc(a['packet']['issued_at'])<=utc(d['deployed_at'])<utc(a['packet']['expires_at']) and utc(d['deployed_at'])<=utc(self.clock()),'deployment outside approved lifetime')
            raw=encoded(saved).decode()
            if row['deployment'] is not None:require(row['deployment']==raw,'deployment receipt cannot change')
            else:c.execute("UPDATE approval_cycles SET phase='observing',deployment=? WHERE cycle_id=?",(raw,cycle));self._record(c,cycle,'deployment_verified',dict(receipt_sha256=pin,deployment_id=d['deployment_id']))
        return self.status()

    def complete(self,cycle,result_sha256):
        require(hash_value(result_sha256),'verified comparison digest required');self.require_action(cycle,'observe_metrics')
        with self._connection(True) as c:
            row=self._row(c,cycle);require(row['phase']=='observing','observation not active');c.execute("UPDATE approval_cycles SET phase='completed',result_sha256=? WHERE cycle_id=?",(result_sha256,cycle));self._record(c,cycle,'comparison_complete',dict(result_sha256=result_sha256))
        return self.status()

    def block(self,cycle,reason):
        require(isinstance(reason,str) and 0<len(reason)<=200,'bounded failure reason required')
        with self._connection(True) as c:
            row=self._row(c,cycle);require(row['phase']!='completed','completed cycle is immutable');c.execute("UPDATE approval_cycles SET phase='blocked' WHERE cycle_id=?",(cycle,));self._record(c,cycle,'blocked',dict(reason=reason))
        return self.status()
