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
DB_VERSION=7402
ACTIONS=frozenset(('github_push','registry_push','deploy'))
PACKAGE_FIELDS=set('schema baseline_sha256 source_sha256 patch_sha256 evaluation_sha256 image_id image_artifact_sha256 comparison_sha256 changes_sha256'.split())
APPROVAL_FIELDS=set('schema mode issuer cycle_id package_sha256 approved_actions issued_at expires_at'.split())
DEPLOYMENT_FIELDS=set('schema mode issuer cycle_id package_sha256 approval_sha256 image_id source_sha256 comparison_sha256 deployment_id deployed_at'.split())
REBUILD_FIELDS=set('schema mode issuer action cycle_id package_sha256 new_cycle_id night base_image_id compatibility_sha256 issued_at expires_at'.split())
SCHEMA="""
CREATE TABLE approval_identity(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
CREATE TABLE approval_cycles(cycle_id TEXT PRIMARY KEY,night TEXT NOT NULL UNIQUE,phase TEXT NOT NULL CHECK(phase IN ('preparing','awaiting_approval','awaiting_deployment','observing','completed','blocked')),created_at TEXT NOT NULL,task_id TEXT,package TEXT,approval TEXT,deployment TEXT,result_sha256 TEXT);
CREATE TABLE approval_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,cycle_id TEXT,kind TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TRIGGER approval_identity_no_update BEFORE UPDATE ON approval_identity BEGIN SELECT RAISE(ABORT,'immutable identity');END;
CREATE TRIGGER approval_identity_no_delete BEFORE DELETE ON approval_identity BEGIN SELECT RAISE(ABORT,'immutable identity');END;
CREATE TRIGGER approval_events_no_update BEFORE UPDATE ON approval_events BEGIN SELECT RAISE(ABORT,'append only');END;
CREATE TRIGGER approval_events_no_delete BEFORE DELETE ON approval_events BEGIN SELECT RAISE(ABORT,'append only');END;
CREATE TRIGGER approval_cycles_no_delete BEFORE DELETE ON approval_cycles BEGIN SELECT RAISE(ABORT,'cycles cannot disappear');END;
CREATE TRIGGER approval_cycles_identity BEFORE UPDATE ON approval_cycles WHEN NEW.cycle_id!=OLD.cycle_id OR NEW.night!=OLD.night OR NEW.created_at!=OLD.created_at BEGIN SELECT RAISE(ABORT,'immutable cycle');END;
CREATE TRIGGER approval_cycles_task BEFORE UPDATE ON approval_cycles WHEN OLD.task_id IS NOT NULL AND NEW.task_id IS NOT OLD.task_id BEGIN SELECT RAISE(ABORT,'immutable original task');END;
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
            version=c.execute('PRAGMA user_version').fetchone()[0]
            require(version in (DB_VERSION,7403) and {v[0] for v in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}=={'approval_identity','approval_cycles','approval_events','sqlite_sequence'}|({'approval_rebuilds'} if version==7403 else set()),'approval metadata format required')
            if write:c.execute('PRAGMA synchronous=FULL');c.execute('BEGIN IMMEDIATE')
            yield c
            if write:c.commit()
        except BaseException:
            if write:c.rollback()
            raise
        finally:c.close()

    def _record(self,c,cycle,kind,value):c.execute('INSERT INTO approval_events(cycle_id,kind,payload) VALUES(?,?,?)',(cycle,kind,encoded(value).decode()))

    def _current(self,c):
        extra=" AND NOT EXISTS(SELECT 1 FROM approval_rebuilds r WHERE r.old_cycle_id=approval_cycles.cycle_id)" if c.execute('PRAGMA user_version').fetchone()[0]==7403 else ''
        rows=c.execute("SELECT * FROM approval_cycles WHERE phase!='completed'"+extra+" ORDER BY rowid LIMIT 2").fetchall();require(len(rows)<=1,'multiple active approval cycles');return rows[0] if rows else None

    def _row(self,c,cycle):
        _uuid(cycle);row=c.execute('SELECT * FROM approval_cycles WHERE cycle_id=?',(cycle,)).fetchone();require(row is not None,'unknown cycle');return row

    def _trusted(self,path,pin,kind):
        path=_path(path);_plain(path);s=path.stat();require(s.st_size<=65536 and hash_value(pin) and sha256(path.read_bytes()).hexdigest()==pin,'operator receipt drift')
        folders=dict(approval='human-approvals',deployment='deployment-receipts',rebuild='rebuild-approvals',bootstrap='bootstrap-instructions',compatibility='compatible-bases',handoff='manual-handoffs');require(kind in folders,'known operator receipt role required')
        if self.mode=='ACTUAL':require(path.parent==BASE/'config'/folders[kind] and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o640 and path.parent.stat().st_uid==0 and stat.S_IMODE(path.parent.stat().st_mode)==0o750,'root-issued operator receipt required')
        else:require(stat.S_IMODE(s.st_mode)==0o600 and stat.S_IMODE(path.parent.stat().st_mode)==0o700 and s.st_uid==os.geteuid(),'private simulated operator receipt required')
        return strict_json(path.read_bytes())

    def _not_archived(self,c,cycle):
        if c.execute('PRAGMA user_version').fetchone()[0]==7403:require(c.execute('SELECT 1 FROM approval_rebuilds WHERE old_cycle_id=?',(cycle,)).fetchone() is None,'historical candidate archived by human; no action authority')

    def rebuild_info(self,cycle):
        with self._connection() as c:
            if c.execute('PRAGMA user_version').fetchone()[0]!=7403:return None
            row=c.execute('SELECT payload FROM approval_rebuilds WHERE new_cycle_id=?',(cycle,)).fetchone()
            if row is None:return None
            saved=strict_json(row[0]);kind='bootstrap' if saved['packet']['schema']=='pi-nightly-operator-bootstrap-v1' else 'rebuild';require(self._trusted(saved['path'],saved['sha256'],kind)==saved['packet'],'rebuild instruction changed');return saved

    def begin_rebuild(self,cycle,path,pin):
        require(self.mode!='ACTUAL' or os.geteuid()==0,'root operator must claim approved rebuild')
        a=self._trusted(path,pin,'rebuild');require(isinstance(a,dict) and set(a)==REBUILD_FIELDS and a['schema']=='pi-nightly-human-rebuild-v1' and a['mode']==self.mode and a['issuer']=='human_operator' and a['action']=='prepare_same_candidate' and a['cycle_id']==cycle,'closed human rebuild permission required')
        return self._claim_rebuild(cycle,path,pin,a)

    def begin_bootstrap(self,cycle,path,pin,report_path):
        """One fixed local telemetry bootstrap under standing preparation authority."""
        require(self.mode!='ACTUAL' or os.geteuid()==0,'root operator must claim bootstrap preparation')
        a=self._trusted(path,pin,'bootstrap');require(isinstance(a,dict) and set(a)==REBUILD_FIELDS and a['schema']=='pi-nightly-operator-bootstrap-v1' and a['mode']==self.mode and a['issuer']=='trusted_compatibility_builder' and a['action']=='prepare_same_candidate' and a['cycle_id']==cycle,'closed operator bootstrap instruction required')
        from .nightly_compatibility import PREIMAGES,CANDIDATES,PATCH
        from .nightly_rebuild import FIELDS
        report=self._trusted(report_path,a['compatibility_sha256'],'compatibility')
        require(isinstance(report,dict) and set(report)==FIELDS and report['schema']=='pi-nightly-compatible-base-v1' and report['mode']==self.mode and report['issuer']=='trusted_compatibility_builder' and report['cycle_id']==cycle and report['package_sha256']==a['package_sha256'] and report['image_id']==a['base_image_id'] and report['patch_sha256']==PATCH and report['changes']=={p:dict(before=PREIMAGES[p],after=CANDIDATES[p]) for p in CANDIDATES},'fixed companion bootstrap report required')
        if self.mode=='ACTUAL':require(_path(report_path).name==a['base_image_id'].removeprefix('sha256:')+'.json','fixed bootstrap report filename required')
        return self._claim_rebuild(cycle,path,pin,a,bootstrap=True)

    def _claim_rebuild(self,cycle,path,pin,a,*,bootstrap=False):
        new=_uuid(a['new_cycle_id']);require(new!=cycle and date.fromisoformat(a['night']).isoformat()==a['night'] and isinstance(a['base_image_id'],str) and a['base_image_id'].startswith('sha256:') and hash_value(a['base_image_id'][7:]) and hash_value(a['compatibility_sha256']),'bounded replacement identity required')
        saved=dict(path=str(_path(path)),sha256=pin,packet=a)
        with self._connection(True) as c:
            if bootstrap and c.execute('PRAGMA user_version').fetchone()[0]==7403:require(c.execute('SELECT 1 FROM approval_rebuilds WHERE new_cycle_id=?',(cycle,)).fetchone() is None,'bootstrap cannot iterate a replacement cycle')
            old=self._row(c,cycle);require(old['package'] is not None and digest(strict_json(old['package']))==a['package_sha256'],'rebuild does not bind old package')
            if c.execute('PRAGMA user_version').fetchone()[0]==7403:
                existing=c.execute('SELECT new_cycle_id,payload FROM approval_rebuilds WHERE old_cycle_id=?',(cycle,)).fetchone()
                if existing is not None:
                    require(existing['new_cycle_id']==new and strict_json(existing['payload'])==saved,'existing rebuild cannot change');return self._description(self._row(c,new))
            issued,expires=utc(a['issued_at']),utc(a['expires_at']);now=utc(self.clock())
            require(issued<=now<expires and expires-issued<=timedelta(hours=24),'fresh finite human rebuild permission required')
            require(old['phase']=='awaiting_approval' and old['approval'] is None and old['deployment'] is None and old['task_id'] is not None and self._current(c)['cycle_id']==cycle,'only original unapproved pending candidate can be rebuilt')
            require(not c.execute('SELECT 1 FROM approval_cycles WHERE cycle_id=? OR night=?',(new,a['night'])).fetchone(),'replacement cycle/night already exists')
            require(_binding(self.state,self.billing,self.mode)==self.identity,'original manager binding changed')
            if c.execute('PRAGMA user_version').fetchone()[0]==7402:
                c.execute('CREATE TABLE approval_rebuilds(old_cycle_id TEXT PRIMARY KEY REFERENCES approval_cycles(cycle_id),new_cycle_id TEXT NOT NULL UNIQUE REFERENCES approval_cycles(cycle_id),payload TEXT NOT NULL)')
                for name,operation,message in (('no_update','UPDATE','immutable rebuild'),('no_delete','DELETE','rebuild history retained')):c.execute("CREATE TRIGGER approval_rebuilds_"+name+" BEFORE "+operation+" ON approval_rebuilds BEGIN SELECT RAISE(ABORT,'"+message+"');END")
                c.execute("CREATE TRIGGER approval_archived_no_update BEFORE UPDATE ON approval_cycles WHEN EXISTS(SELECT 1 FROM approval_rebuilds WHERE old_cycle_id=OLD.cycle_id) BEGIN SELECT RAISE(ABORT,'archived cycle retained');END")
                c.execute('PRAGMA user_version=7403')
            c.execute("INSERT INTO approval_cycles(cycle_id,night,phase,created_at,task_id) VALUES(?,?,'preparing',?,?)",(new,a['night'],now.isoformat(),old['task_id']))
            c.execute('INSERT INTO approval_rebuilds VALUES(?,?,?)',(cycle,new,encoded(saved).decode()))
            self._record(c,cycle,'operator_bootstrap_archived' if bootstrap else 'human_archived_for_rebuild',dict(new_cycle_id=new,permission_sha256=pin,old_package_sha256=a['package_sha256']))
            self._record(c,new,'operator_bootstrap_claimed' if bootstrap else 'human_rebuild_claimed',dict(old_cycle_id=cycle,permission_sha256=pin,base_image_id=a['base_image_id'],compatibility_sha256=a['compatibility_sha256'],task_id=old['task_id']))
        return self.status()

    def require_preparation(self,cycle,task,base):
        state=self.status();require(state['phase']=='preparing' and state['cycle_id']==cycle and state['task_id'] in (None,task),'one bound task preparation required')
        saved=self.rebuild_info(cycle)
        if saved is not None:require(saved['packet']['base_image_id']==base and utc(self.clock())<utc(saved['packet']['expires_at']),'approved rebuild base or validity changed')

    def _approval(self,row,*,current=True):
        require(row['approval'] is not None,'human approval required');saved=strict_json(row['approval']);a=self._trusted(saved['path'],saved['sha256'],'approval')
        require(a==saved['packet'] and set(a)==APPROVAL_FIELDS and a['schema']=='pi-nightly-human-approval-v1' and a['mode']==self.mode and a['issuer']=='human_operator' and a['cycle_id']==row['cycle_id'] and a['package_sha256']==digest(strict_json(row['package'])),'approval is not bound to this artifact')
        acts=a['approved_actions'];require(isinstance(acts,list) and acts and len(acts)==len(set(acts)) and set(acts)<=ACTIONS,'fixed human-approved actions required')
        issued,expires=utc(a['issued_at']),utc(a['expires_at']);require(issued<expires and expires-issued<=timedelta(days=7) and issued<=utc(self.clock()),'invalid approval lifetime')
        if current:require(utc(self.clock())<expires,'human approval expired')
        return saved

    def _description(self,row):
        if row is None or row['phase']=='completed':return dict(phase='idle',cycle_id=None,package_sha256=None,task_id=None)
        phase=row['phase'];package=strict_json(row['package']) if row['package'] else None
        if phase=='awaiting_deployment':
            try:self._approval(row)
            except (ValueError,OSError,TypeError,KeyError):phase='awaiting_approval'
        if phase=='observing':
            try:
                d=strict_json(row['deployment']);require(self._trusted(d['path'],d['sha256'],'deployment')==d['packet'],'deployment receipt drift')
            except (ValueError,OSError,TypeError,KeyError):phase='blocked'
        return dict(phase=phase,cycle_id=row['cycle_id'],package_sha256=digest(package) if package else None,task_id=row['task_id'])

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

    def bind_task(self,cycle,task_id):
        import re
        require(isinstance(task_id,str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',task_id),'fixed original manager task identity required')
        with self._connection(True) as c:
            row=self._row(c,cycle);require(row['phase']=='preparing','task binding requires preparation')
            if row['task_id'] is not None:require(row['task_id']==task_id,'original task cannot change within a round')
            else:
                c.execute('UPDATE approval_cycles SET task_id=? WHERE cycle_id=?',(task_id,cycle));self._record(c,cycle,'original_task_bound',dict(task_id=task_id))
        return self.status()

    def ready(self,cycle,package):
        _package(package);raw=encoded(package).decode()
        with self._connection(True) as c:
            self._not_archived(c,cycle);row=self._row(c,cycle)
            if c.execute('PRAGMA user_version').fetchone()[0]==7403:
                rebuild=c.execute('SELECT old_cycle_id FROM approval_rebuilds WHERE new_cycle_id=?',(cycle,)).fetchone()
                if rebuild is not None:
                    old=strict_json(self._row(c,rebuild[0])['package']);require(all(package[k]==old[k] for k in ('baseline_sha256','source_sha256','patch_sha256','changes_sha256')),'rebuild must retain original candidate fix')
            if row['package'] is not None:require(row['package']==raw,'sealed artifact cannot change')
            else:
                require(row['phase']=='preparing','preparation is no longer active');c.execute("UPDATE approval_cycles SET phase='awaiting_approval',package=? WHERE cycle_id=?",(raw,cycle));self._record(c,cycle,'artifact_ready',dict(package_sha256=digest(package)))
        return self.status()

    def approve(self,cycle,path,pin):
        a=self._trusted(path,pin,'approval');saved=dict(path=str(_path(path)),sha256=pin,packet=a)
        with self._connection(True) as c:
            self._not_archived(c,cycle);row=self._row(c,cycle);require(row['phase'] in ('awaiting_approval','awaiting_deployment'),'artifact is not waiting for approval')
            proposed=dict(row);proposed['approval']=encoded(saved).decode();self._approval(proposed)
            if row['approval']!=proposed['approval']:
                c.execute("UPDATE approval_cycles SET phase='awaiting_deployment',approval=? WHERE cycle_id=?",(proposed['approval'],cycle));self._record(c,cycle,'human_approved',dict(approval_sha256=pin,package_sha256=a['package_sha256'],actions=a['approved_actions']))
        return self.status()

    def require_action(self,cycle,action):
        require(action in ACTIONS|{'observe_metrics'},'unknown gated action')
        with self._connection() as c:
            self._not_archived(c,cycle);row=self._row(c,cycle);phase=self._description(row)['phase']
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

    def no_release(self,cycle,reason,result_sha256):
        require(hash_value(result_sha256) and reason in ('no_task','not_reproduced','no_evidence','outside_window','lock_busy','cached'),'known no-release receipt required')
        with self._connection(True) as c:
            row=self._row(c,cycle);require(row['phase']=='preparing' and row['task_id'] is None and row['package'] is None,'only unadmitted preparation can close without publication')
            c.execute("UPDATE approval_cycles SET phase='completed',result_sha256=? WHERE cycle_id=?",(result_sha256,cycle));self._record(c,cycle,'no_release',dict(reason=reason,result_sha256=result_sha256))
        return self.status()

    def handoff_permission(self,cycle,path,pin,*,current=True):
        value=self._trusted(path,pin,'handoff')
        fields=set('schema mode issuer action operation_id cycle_id package_sha256 deployment_sha256 new_identity new_package_sha256 driver_sha256 profile_sha256 issued_at expires_at'.split())
        require(isinstance(value,dict) and set(value)==fields and value['schema']=='pi-nightly-manual-handoff-v1' and value['mode']==self.mode and value['issuer']=='human_operator' and value['action']=='interrupt_for_manual_main_release' and value['cycle_id']==cycle,'exact human manual-update permission required')
        _uuid(value['operation_id']);_uuid(cycle)
        require(all(hash_value(value[k]) for k in ('package_sha256','deployment_sha256','new_package_sha256','driver_sha256','profile_sha256')),'exact manual-update pins required')
        from .live_observer import _identity
        identity=value['new_identity'];_identity(identity)
        require(set(identity)==set('deployment_id generation owner image_ids commit_sha schema_id config_hash'.split()) and all(v is not None for v in identity.values()) and 'python' in identity['image_ids'],'complete new deployed identity required')
        issued,expires=utc(value['issued_at']),utc(value['expires_at']);now=utc(self.clock())
        require(issued<=now and issued<expires and expires-issued<=timedelta(hours=1),'bounded human handoff lifetime required')
        if current:require(now<expires,'human handoff permission expired')
        return value

    def interrupt_observation(self,cycle,path,pin,result_sha256):
        require(hash_value(result_sha256),'verified manual-update result required')
        value=self.handoff_permission(cycle,path,pin,current=False)
        event=dict(operation_id=value['operation_id'],decision='insufficient_evidence',reason='manual_main_release',permission_sha256=pin,result_sha256=result_sha256,new_driver_sha256=value['driver_sha256'],new_profile_sha256=value['profile_sha256'],new_identity=value['new_identity'])
        with self._connection(True) as c:
            self._not_archived(c,cycle);row=self._row(c,cycle)
            require(row['package'] is not None and row['deployment'] is not None and digest(strict_json(row['package']))==value['package_sha256'] and strict_json(row['deployment'])['sha256']==value['deployment_sha256'],'old observation identity changed')
            saved=strict_json(row['deployment']);require(self._trusted(saved['path'],saved['sha256'],'deployment')==saved['packet'] and value['new_identity']['deployment_id']!=saved['packet']['deployment_id'],'new main must differ from retained old deployment')
            if row['phase']=='completed':
                matches=c.execute("SELECT payload FROM approval_events WHERE cycle_id=? AND kind='observation_interrupted'",(cycle,)).fetchall()
                require(len(matches)==1 and strict_json(matches[0][0])==event and row['result_sha256']==result_sha256,'unrelated completed observation cannot be replaced')
            else:
                require(row['phase'] in ('observing','blocked') and self._current(c)['cycle_id']==cycle,'only the current deployed observation may be interrupted')
                self.handoff_permission(cycle,path,pin)
                c.execute("UPDATE approval_cycles SET phase='completed',result_sha256=? WHERE cycle_id=?",(result_sha256,cycle))
                self._record(c,cycle,'observation_interrupted',event)
        return self.status()

    def block(self,cycle,reason):
        require(isinstance(reason,str) and 0<len(reason)<=200,'bounded failure reason required')
        with self._connection(True) as c:
            row=self._row(c,cycle);require(row['phase']!='completed','completed cycle is immutable');c.execute("UPDATE approval_cycles SET phase='blocked' WHERE cycle_id=?",(cycle,));self._record(c,cycle,'blocked',dict(reason=reason))
        return self.status()
