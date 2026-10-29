"""Linux bridge to paired recovery collections. Billing snapshots are never restored."""
from dataclasses import asdict
from hashlib import sha256
import gzip
import io
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tarfile

from . import backup
from .audit import _path, _plain, digest, encoded, require, strict_json
from .contracts import Identity
from .product_bootstrap import _facts, COUNTS
from .product_runtime import BASE, _pinned

RECOVERY_COMPONENTS=('product_runtime_snapshot.py','product_activation.py','product_release.py','product_backup.py','product_restore.py','product_cold_probe.py','product_runtime.py','product_commands.py','product_migration.py','product_bootstrap.py','backup.py','ledger.py','audit.py')
FIELDS=set('schema release_pair_id environment_path environment_sha256 compose_path compose_sha256 billing_ledger_path manager_state_path maximum_artifact_bytes'.split())
META_SQL="""BEGIN READ ONLY;SET LOCAL statement_timeout='10s';
SELECT json_build_object('system_identifier',(SELECT system_identifier::text FROM pg_control_system()),'database',current_database(),'size_bytes',pg_database_size(current_database()),
 'tables',(SELECT coalesce(json_object_agg(table_name,(xpath('/row/c/text()',query_to_xml(format('SELECT count(*) AS c FROM public.%I',table_name),false,true,'')))[1]::text::bigint),'{}'::json) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'),
 'content',(SELECT coalesce(json_object_agg(table_name,(xpath('/row/c/text()',query_to_xml(format('SELECT md5(coalesce(string_agg(md5(row_to_json(r)::text),%L ORDER BY md5(row_to_json(r)::text)),%L)) AS c FROM public.%I r','','',table_name),false,true,'')))[1]::text),'{}'::json) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'),
 'roles',(SELECT json_object_agg(rolname,json_build_object('login',rolcanlogin,'superuser',rolsuper,'createdb',rolcreatedb,'createrole',rolcreaterole,'replication',rolreplication,'bypassrls',rolbypassrls,'inherit',rolinherit)) FROM pg_roles WHERE rolname NOT LIKE 'pg_%'));ROLLBACK;"""


def _copy(source,target):
    _plain(source)
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with source.open('rb') as incoming,os.fdopen(fd,'wb') as outgoing:
        shutil.copyfileobj(incoming,outgoing,65536);outgoing.flush();os.fsync(outgoing.fileno())


def _tar_files(target,files):
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as outgoing:
        with tarfile.open(fileobj=outgoing,mode='w') as archive:
            for name,path in files.items():
                _plain(path);info=tarfile.TarInfo(name);info.size=path.stat().st_size;info.mode=0o600
                with path.open('rb') as incoming:archive.addfile(info,incoming)
        outgoing.flush();os.fsync(outgoing.fileno())


def _snapshot(source,target):
    _plain(source);require(stat.S_IMODE(source.stat().st_mode)==0o600,'private original SQLite required')
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as original,sqlite3.connect(target) as copied:
        original.execute('PRAGMA query_only=ON');original.backup(copied)
        require(copied.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SQLite preservation snapshot invalid')
    with target.open('rb') as stream:os.fsync(stream.fileno())


class LinuxProductBackup:
    def __init__(self,host,proofs=None):
        self.host=host;self.plan=host.plan;self.root=_path(host.root);self.proofs=proofs or {}
        actual=host.config['mode']=='ACTUAL'
        if actual:
            from .product_runtime import LinuxProductHost
            require(type(host) is LinuxProductHost,'canonical native backup host required')
        self.config=_pinned(host.config['backup_path'],host.config['backup_sha256'],actual);c=self.config
        runtime=isinstance(c,dict) and c.get('schema')=='pi-product-backup-v2'
        require(isinstance(c,dict) and set(c)==(FIELDS|{'runtime_context_path','runtime_context_sha256'} if runtime else FIELDS) and c['schema'] in ('pi-product-backup-v1','pi-product-backup-v2') and c['release_pair_id']==self.plan['operation_id'] and (not actual or runtime),'closed qualified backup settings required')
        self.qualification='runtime' if runtime else 'application'
        self.runtime_context=_pinned(c['runtime_context_path'],c['runtime_context_sha256'],actual) if runtime else None
        if runtime:require(self.runtime_context.get('plan_sha256')==digest(self.plan),'runtime context plan differs')
        require(type(c['maximum_artifact_bytes']) is int and 0<c['maximum_artifact_bytes']<=536870912,'bounded recovery artifacts required')
        for key in ('environment','compose'):
            path=_path(c[key+'_path']);_plain(path);require(path.parent==_path(host.config['compose_dir']) and path.stat().st_size<=1048576 and sha256(path.read_bytes()).hexdigest()==c[key+'_sha256'],'sealed product configuration drift')
        require(Path(c['environment_path']).name=='.env' and Path(c['compose_path']).name=='docker-compose.yml','fixed product configuration names required')
        for key,canonical in (('billing_ledger',BASE/'state/ledger.sqlite'),('manager_state',BASE/'state/actual-manager.sqlite')):
            path=_path(c[key+'_path']);_plain(path)
            require(path!=_path(host.ledger.path) and not path.samefile(host.ledger.path),'original state cannot be product control ledger')
            require(path.is_relative_to(BASE)==actual,'original state domain mismatch')
            if actual:require(path==canonical,'original canonical state required')
        self.collections=self.root/'collections';self.collections.mkdir(mode=0o700,exist_ok=True)
        roles={}
        for row in self.plan['legacy']['containers']:roles['python' if row['service'] in ('api','worker') else row['service']]=row['image_id']
        # This is an observed collection identity, not a claim of historical
        # deployment ownership. Unknown owner/generation remain JSON null.
        self.legacy=Identity('legacy-observation-'+digest(self.plan['legacy'])[:32],None,None,roles,commit_sha=self.plan['legacy']['source_commit'])
        candidate={k:v for k,v in self.plan['candidate'].items() if k!='schema_version'}
        self.candidate=Identity(**candidate)
        self.pair=dict(release_pair_id=self.plan['operation_id'],pre_identity=asdict(self.legacy),post_identity=asdict(self.candidate),plan_hash=digest(self.plan))
        self.context=dict(schema_context=digest(dict(protocol=1,schema=1,state=1,effect_keys=1,serialization='jsonplus',recovery_contract=2 if runtime else 1,product_schema_id=self.plan['candidate']['schema_id'],postgres_image=roles['postgres'])),tool_context=digest({name:sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in RECOVERY_COMPONENTS}))

    def preflight(self):
        self.host.authorize(self.plan)
        require(shutil.disk_usage(self.root).free>=4*self.config['maximum_artifact_bytes']+5*1024**3,'paired recovery disk reserve unavailable')
        if self.host.config['mode']=='ACTUAL':
            from .product_restore import OwnedPostgresRestore
            require(callable(getattr(OwnedPostgresRestore,'restore',None)),'native restore implementation required')
            require(callable(getattr(self.host,'apply_schema',None)) and callable(getattr(self.host,'bind_identity',None)),'native migration implementation required')

    def _metadata(self):
        value=self.host._json(['exec',self.host._cid('postgres'),'psql','-X','-q','-A','-t','-w','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c',META_SQL])
        require(isinstance(value,dict) and set(value)=={'system_identifier','database','size_bytes','tables','content','roles'} and isinstance(value['system_identifier'],str) and value['system_identifier'].isdigit() and value['database']=='myink','complete source database identity required')
        require(type(value['size_bytes']) is int and value['size_bytes']>0 and isinstance(value['tables'],dict) and len(value['tables'])<=1000 and all(isinstance(k,str) and type(v) is int and v>=0 for k,v in value['tables'].items()),'complete relation census required')
        require(isinstance(value['content'],dict) and set(value['content'])==set(value['tables']) and all(isinstance(v,str) and len(v)==32 and all(c in '0123456789abcdef' for c in v) for v in value['content'].values()),'complete relation content fingerprints required')
        require(isinstance(value['roles'],dict) and {'myink','myink_app','myink_report'}<=set(value['roles']),'original product roles missing')
        return value

    def _sealed_configuration(self):
        for key in ('environment','compose'):
            path=_path(self.config[key+'_path']);_plain(path)
            require(path.stat().st_size<=1048576 and sha256(path.read_bytes()).hexdigest()==self.config[key+'_sha256'],'sealed configuration changed during collection')

    def _runtime_material(self,phase):
        if self.runtime_context is None:return None
        from .product_runtime_snapshot import capture
        context=_pinned(self.config['runtime_context_path'],self.config['runtime_context_sha256'],self.host.config['mode']=='ACTUAL')
        require(context==self.runtime_context,'private runtime context drift')
        if phase=='PRE':ids=[v['Id'] for v in context['templates']];bindings=None
        else:
            bindings={}
            for t in context['templates']:
                row=self.host.ledger.get('candidate:'+self.plan['operation_id']+':'+t['Id'])
                require(row and row['kind']=='product_cohort_container' and row['status']=='done' and row['payload']==dict(plan_sha256=digest(self.plan),context_sha256=self.config['runtime_context_sha256'],role='candidate',source_id=t['Id']),'original post template intent required')
                bindings[t['Id']]=row['evidence']['id']
            ids=list(bindings.values())
            require(set(ids)=={v['id'] for v in self.host._candidate_cohort()},'post runtime registry differs')
        rows=self.host._json(['inspect',*ids]);network=self.host._json(['network','inspect',context['network']['id']])
        require(isinstance(network,list) and len(network)==1,'single runtime network required')
        volumes=self.host._json(['volume','inspect',*[v['name'] for v in context['volumes']]]) if context['volumes'] else []
        return capture(self.plan,self.host.config,context,phase,rows,network[0],volumes,bindings=bindings)

    def _quiet(self,phase="PRE"):
        self._sealed_configuration()
        self.host.authorize(self.plan)
        observed=self.host.inspect(self.plan) if phase=='PRE' else self.host.inspect_candidate(self.plan)
        require(observed==(self.plan['legacy'] if phase=='PRE' else self.plan['candidate']),'recovery source identity drift')
        facts=(self.host.measure_quiet if phase=='PRE' else self.host.measure_candidate_quiet)(self.plan,self.proofs);_facts('drain_legacy',facts,self.plan,self.proofs)
        meta=self._metadata()
        configuration={k:self.config[k] for k in ('environment_sha256','compose_sha256')}
        runtime=self._runtime_material(phase)
        if runtime is not None:configuration['effective_runtime_sha256']=digest(runtime)
        basis=dict(source=observed,phase=phase,fence=facts['fence_sha256'],database=meta['system_identifier'],tables=meta['tables'],content=meta['content'],roles=meta['roles'],configuration=configuration)
        return dict(verified=True,consistency_id=digest(basis)),meta

    def __call__(self,action,context):
        self.preflight()
        phase=context.get('phase');require(phase in ('PRE','POST') and context.get('identity')==asdict(self.legacy if phase=='PRE' else self.candidate) and context.get('pair')==self.pair,'fixed paired recovery context required')
        if phase=='POST':
            release=self.host.ledger.get('release:'+self.plan['operation_id'])
            require(release and release['kind']=='release' and release['status']=='done' and release['payload']==dict(release_pair_id=self.plan['operation_id'],candidate=asdict(self.candidate)),'original published candidate release required')
        if action=='verify_identity':return self._quiet(phase)[0]
        if action=='collect':return self._collect(context)
        raise ValueError('unsupported collection operation')

    def _artifact(self,args,target):
        result=self.host._run(args,limit=self.config['maximum_artifact_bytes'],seconds=600)
        require(result['status']=='done' and result['returncode']==0 and result['stderr']['bytes']==0,'native artifact command unconfirmed')
        source=self.root/'commands'/result['command_id']/'stdout.bin';_plain(source)
        require(source.stat().st_size==result['stdout']['bytes'] and source.stat().st_size>0 and backup.digest(source)==result['stdout']['sha256'],'native artifact drift')
        _copy(source,target);return result

    def _collect(self,context):
        phase=context['phase'];quiet,meta=self._quiet(phase);directory=_path(context['directory'])
        require(directory.parent==self.collections and directory.name==sha256(context['operation_id'].encode()).hexdigest(),'fixed private collection directory required')
        def cid(role):return self.host.backup_container_id(phase,role) if hasattr(self.host,'backup_container_id') else self.host._cid(role)
        pg=cid('postgres')
        raw=directory/'database.sql';self._artifact(['exec',pg,'pg_dump','-U','myink','-d','myink','--clean','--if-exists'],raw)
        fd=os.open(directory/'database.sql.gz',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as outgoing:
            with raw.open('rb') as incoming,gzip.GzipFile(fileobj=outgoing,mode='wb',mtime=0) as compressed:shutil.copyfileobj(incoming,compressed,65536)
            outgoing.flush();os.fsync(outgoing.fileno())
        self._artifact(['exec',pg,'pg_dumpall','-U','myink','--globals-only'],directory/'roles.sql')
        self._artifact(['cp',cid('api')+':/data/feedback','-'],directory/'attachments.tar')
        self._artifact(['cp',cid('frontend')+':/data','-'],directory/'certificate.tar')
        _copy(Path(self.config['environment_path']),directory/'crypto.env')
        configuration={'docker-compose.yml':Path(self.config['compose_path']),'.env':Path(self.config['environment_path'])}
        runtime=self._runtime_material(phase)
        if runtime is not None:
            backup.durable_file(directory/'effective-runtime.json',encoded(runtime));configuration['effective-runtime.json']=directory/'effective-runtime.json'
        _tar_files(directory/'configuration.tar',configuration)
        _snapshot(Path(self.config['billing_ledger_path']),directory/'billing.sqlite')
        _snapshot(Path(self.config['manager_state_path']),directory/'manager.sqlite')
        backup.durable_file(directory/'source-metadata.json',encoded(meta))
        require(self._quiet(phase)[0]==quiet,'source changed during material collection')
        return dict(verified=True,consistency_id=quiet['consistency_id'],dump_exit=0,dump_stderr_bytes=0,roles=sorted(meta['roles']),source_id=meta['system_identifier'],artifacts=dict(database='database.sql.gz',roles='roles.sql',crypto='crypto.env',attachments='attachments.tar',config='configuration.tar',certificate='certificate.tar',billing_snapshot='billing.sqlite',manager_snapshot='manager.sqlite',source_metadata='source-metadata.json'))

    def perform(self,action,plan,proofs):
        require(plan==self.plan,'backup plan drift');self.proofs=proofs
        if action=='backup_pre':
            receipt=backup.create_backup(self.host.ledger,'PRE',self.legacy,self,self.collections,pair=self.pair)
            require(receipt.status=='done','PRE collection incomplete')
            from .product_restore import OwnedPostgresRestore
            result=OwnedPostgresRestore(self).restore(receipt,qualification=self.qualification)
            require(result.status=='done','current restore qualification incomplete')
            return dict(verified=True,plan_sha256=digest(plan),release_pair_id=plan['operation_id'],manifest_sha256=receipt.evidence['manifest_sha256'],restore_operation_id=result.operation_id,source_sha256=plan['legacy']['source_sha256'])
        if action=='install_schema':return self.host.apply_schema(plan,proofs)
        if action=='bind_identity':return self.host.bind_identity(plan,proofs)
        raise ValueError('unapproved recovery operation')
