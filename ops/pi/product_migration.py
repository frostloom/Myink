"""Fixed candidate-image migration jobs, never a shell, SDK or HTTP tool."""
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import tarfile
from urllib.parse import quote

from .audit import digest, encoded, require, strict_json
from .backup import durable_file
from .product_backup import LinuxProductBackup
from .product_runtime import _pinned

TABLES={'maintenance_control','admission_intents','maintenance_executions','queue_handoffs'}
LABEL='myink.pi.migration.operation'
SCRIPT=r"""
import hashlib,json,sys
from pathlib import Path
import myink
package=Path(myink.__file__).parent
files={}
for path in package.rglob('*.py'):
 if '__pycache__' not in path.parts:
  if path.is_symlink():raise RuntimeError('linked runtime source')
  files['src/myink/'+path.relative_to(package).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
actual=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
if actual!=sys.argv[1]:raise RuntimeError('installed runtime source differs from candidate')
from sqlalchemy import text
from myink.db import ensure_maintenance_schema,get_admin_engine
from myink.maintenance_pause import PROTOCOL
if PROTOCOL!={'protocol':1,'schema':1,'state':1,'effect_keys':1}:raise RuntimeError('incompatible native protocol')
mode=sys.argv[2];plan=json.loads(sys.argv[3])
if mode=='install':ensure_maintenance_schema()
with get_admin_engine().begin() as db:
 row=db.execute(text('SELECT * FROM public.maintenance_control WHERE id=1 FOR UPDATE')).mappings().one()
 if not (row['generation']==0 and row['owner']=='bootstrap' and row['deployment_id']=='initial' and row['epoch']==''):
  raise RuntimeError('first bootstrap ownership already changed')
 if mode=='install':
  db.execute(text('UPDATE public.maintenance_control SET admission_closed=true,consumer_blocked=true WHERE id=1'))
 elif mode=='bind':
  if row['admission_closed'] is not True or row['consumer_blocked'] is not True:raise RuntimeError('native barrier not closed')
  c=plan['candidate']
  db.execute(text('UPDATE public.maintenance_control SET epoch=:epoch,deployment_id=:deployment,generation=:generation,owner=:owner,image_ids=CAST(:images AS JSON),deadline=CAST(:deadline AS timestamptz) WHERE id=1'),dict(epoch=plan['operation_id'],deployment=c['deployment_id'],generation=c['generation'],owner=c['owner'],images=json.dumps(c['image_ids']),deadline=plan['expires_at']))
 else:raise RuntimeError('unknown native stage')
print(json.dumps(dict(runtime_sha256=actual,protocol=dict(PROTOCOL,serialization='jsonplus'))))
"""


class NativeProductMigration:
    def __init__(self,host):
        self.host=host;self.plan=host.plan
        if host.config['mode']=='ACTUAL':
            from .product_runtime import LinuxProductHost
            require(type(host) is LinuxProductHost,'canonical native migration host required')

    def _state(self):
        return self.host._json(['exec',self.host._cid('postgres'),'psql','-X','-q','-A','-t','-w','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c','BEGIN READ ONLY;SET LOCAL statement_timeout=3000;SELECT row_to_json(m) FROM maintenance_control m WHERE id=1;ROLLBACK;'])

    def _owned(self,cid,mode):
        result=self.host.commands.run(['inspect',cid],timeout=15)
        values=strict_json(self.host._bytes(result));require(isinstance(values,list) and len(values)==1,'complete migration inspect required');v=values[0]
        require(v['Id']==cid and cid not in {r['id'] for r in self.plan['legacy']['containers']} and v['Image']==self.plan['candidate']['image_ids']['python'],'foreign migration container')
        c=v['HostConfig'];labels=v['Config']['Labels']
        require(labels.get(LABEL)==self.plan['operation_id'] and labels.get('myink.pi.migration.stage')==mode and v['Config']['User']=='10001','migration owner drift')
        require(c['NetworkMode']=='container:'+self.host._cid('postgres') and c['ReadonlyRootfs'] is True and not c.get('Binds') and not c.get('PortBindings') and not c.get('Privileged') and not c.get('ExtraHosts') and all(m['Type']=='tmpfs' for m in v['Mounts']),'migration boundary drift')
        require(c['Memory']==536870912 and c['PidsLimit']==64 and c['CapDrop']==['ALL'] and set(c.get('Tmpfs',{}))=={'/tmp'},'migration resource drift')
        return v

    def _candidate(self,cid):
        h=self.host;c=h.config
        manifest=_pinned(c['candidate_manifest_path'],c['candidate_manifest_sha256'],c['mode']=='ACTUAL')
        require(isinstance(manifest,dict) and set(manifest)=={'source_commit','files'} and manifest['source_commit']==self.plan['candidate']['commit_sha'],'exact candidate manifest required')
        expected={k:v for k,v in manifest['files'].items() if k.startswith('src/myink/')}
        require(expected and all(isinstance(v,str) and len(v)==64 for v in expected.values()),'candidate package source missing')
        result=h._run(['cp',cid+':/app/src','-'],limit=67108864);archive=h.commands.root/result['command_id']/'stdout.bin';files={};total=0
        with tarfile.open(archive,mode='r:') as stream:
            for entry in stream:
                path=PurePosixPath(entry.name)
                require(not path.is_absolute() and '..' not in path.parts and path.parts[0]=='src' and (entry.isfile() or entry.isdir()),'unsafe candidate source archive')
                if entry.isdir() or '__pycache__' in path.parts or path.suffix in ('.pyc','.pyo'):continue
                require(len(files)<10000 and entry.size<=4194304 and str(path) not in files,'bounded candidate source required');total+=entry.size;require(total<=67108864)
                raw=stream.extractfile(entry).read();require(len(raw)==entry.size);files[str(path)]=sha256(raw).hexdigest()
        require({k:v for k,v in files.items() if k.startswith('src/myink/')}==expected,'candidate physical source differs')
        return digest({k:v for k,v in expected.items() if k.endswith('.py')})

    def _environment(self,folder):
        pg=self.host._json(['inspect',self.host._cid('postgres')]);require(isinstance(pg,list) and len(pg)==1,'original PostgreSQL inspect required');v=pg[0]
        original=next(r for r in self.plan['legacy']['containers'] if r['service']=='postgres')
        require(v['Id']==original['id'] and v['Image']==original['image_id'],'original PostgreSQL drift')
        env={}
        for item in v['Config']['Env']:
            k,separator,value=item.partition('=');require(separator and k not in env,'duplicate original database environment');env[k]=value
        require(env.get('POSTGRES_USER')=='myink' and env.get('POSTGRES_DB')=='myink','fixed original database required')
        password=env.get('POSTGRES_PASSWORD')
        if not password:
            require(self.host.config['mode']=='SIMULATED' and env.get('POSTGRES_HOST_AUTH_METHOD')=='trust','original database credential absent');password='isolated-trust-only'
        url='postgresql+psycopg://myink:'+quote(password,safe='')+'@127.0.0.1:5432/myink'
        # Secrets stay in a private env-file, never Docker argv or public audit.
        durable_file(folder/'database.env',('DATABASE_URL='+url+'\nADMIN_DATABASE_URL='+url+'\nEMBED_ENABLED=0\nPYTHONDONTWRITEBYTECODE=1\n').encode())
        return folder/'database.env'

    def _job(self,mode,plan):
        h=self.host;h.authorize(plan);require(plan==self.plan,'migration plan drift')
        action='install_schema' if mode=='install' else 'bind_identity'
        parent=h.ledger.get(plan['operation_id']);step=h.ledger.get(plan['operation_id']+':'+action)
        require(parent and parent['kind']=='product_bootstrap' and parent['status']=='pending' and parent['payload']==dict(plan_sha256=digest(plan)) and step and step['kind']=='product_bootstrap_step' and step['status']=='pending' and step['payload']==dict(plan_sha256=digest(plan),action=action),'original migration intent required')
        folder=h.root/('migration-'+mode)
        try:folder.mkdir(mode=0o700)
        except FileExistsError:raise ValueError('existing migration intent cannot be redispatched') from None
        durable_file(folder/'intent.json',encoded(dict(plan_sha256=digest(plan),stage=mode)))
        cid=None
        try:
            env=self._environment(folder)
            # Candidate source is verified before the job starts or connects.
            manifest=_pinned(h.config['candidate_manifest_path'],h.config['candidate_manifest_sha256'],h.config['mode']=='ACTUAL')
            runtime_pin=digest({k:v for k,v in manifest['files'].items() if k.startswith('src/myink/') and k.endswith('.py')})
            args=['create','--name','myink-pi-migration-'+plan['operation_id']+'-'+mode,'--label',LABEL+'='+plan['operation_id'],'--label','myink.pi.migration.stage='+mode,'--network','container:'+h._cid('postgres'),'--read-only','--tmpfs','/tmp:rw,size=33554432','--memory','536870912','--memory-swap','536870912','--pids-limit','64','--cpus','0.5','--cap-drop','ALL','--security-opt','no-new-privileges','--user','10001','--env-file',str(env),plan['candidate']['image_ids']['python'],'python','-B','-c',SCRIPT,runtime_pin,mode,encoded(plan).decode()]
            result=h._run(args);cid=h._bytes(result).decode().strip();require(len(cid)==64 and all(c in '0123456789abcdef' for c in cid),'actual migration ID required')
            durable_file(folder/'registry.json',encoded(dict(container_id=cid,image_id=plan['candidate']['image_ids']['python'],operation_id=plan['operation_id'],stage=mode)))
            self._owned(cid,mode);require(self._candidate(cid)==runtime_pin,'candidate runtime pin drift')
            output=h._run(['start','--attach',cid],seconds=600);observed=strict_json(h._bytes(output));v=self._owned(cid,mode)
            require(not v['State']['Running'] and v['State']['ExitCode']==0 and not v['State']['OOMKilled'] and observed['runtime_sha256']==runtime_pin and observed['protocol']==dict(protocol=1,schema=1,state=1,effect_keys=1,serialization='jsonplus'),'native migration outcome unconfirmed')
            durable_file(folder/'receipt.json',encoded(observed));return observed
        finally:
            if cid is not None:
                self._owned(cid,mode);h.commands.run(['rm','--force',cid],timeout=30)
                result=h.commands.run(['ps','--all','--quiet','--no-trunc','--filter','label='+LABEL+'='+plan['operation_id'],'--filter','label=myink.pi.migration.stage='+mode],timeout=15)
                require(not h._bytes(result).strip(),'owned migration cleanup unconfirmed')

    def install(self,plan,proofs):
        backend=LinuxProductBackup(self.host,proofs);backend._sealed_configuration()
        before=backend._metadata();require(not set(before['tables'])&TABLES,'first bootstrap schema already exists')
        result=self._job('install',plan);after=backend._metadata()
        require(set(after['tables'])==set(before['tables'])|TABLES and all(after['tables'][k]==v and after['content'][k]==before['content'][k] for k,v in before['tables'].items()),'historical business content changed during schema installation')
        state=self._state();require(state['epoch']=='' and state['generation']==0 and state['owner']=='bootstrap' and state['deployment_id']=='initial' and state['admission_closed'] is True and state['consumer_blocked'] is True,'schema barrier not confirmed')
        return dict(verified=True,plan_sha256=digest(plan),source_commit=plan['candidate']['commit_sha'],historical_provenance_updated=False,protocol=result['protocol'])

    def bind(self,plan,proofs):
        self._job('bind',plan);state=self._state();c=plan['candidate']
        require(state['epoch']==plan['operation_id'] and state['deployment_id']==c['deployment_id'] and state['generation']==c['generation'] and state['owner']==c['owner'] and state['image_ids']==c['image_ids'] and state['admission_closed'] is True and state['consumer_blocked'] is True,'candidate ownership not independently confirmed')
        return dict(verified=True,plan_sha256=digest(plan),identity=c)
