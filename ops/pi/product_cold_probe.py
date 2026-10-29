"""Read-only restored application probes in frozen, isolated business images.

These prove restored read paths, not online generation quality or release
permission. Nothing here is registered as a model tool.
"""
from hashlib import sha256
import os
from pathlib import Path
import tarfile
import time

from .audit import _plain,digest,encoded,require,strict_json
from .backup import durable_file
from .product_runtime import _pinned

LABEL='myink.pi.restore-probe.operation'
WAIT=['python','-B','-c','import time; time.sleep(600)']
UNPACK=r"""
import os,sys,tarfile
from pathlib import Path,PurePosixPath
seen=set();total=0
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as stream:
 for member in stream:
  path=PurePosixPath(member.name)
  if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!='pi-cold' or str(path) in seen or not (member.isdir() or member.isfile()):raise RuntimeError('unsafe probe material')
  seen.add(str(path));total+=member.size
  if len(seen)>22000 or member.size<0 or total>536870912:raise RuntimeError('unpack bound')
  target=Path('/tmp').joinpath(*path.parts)
  if member.isdir():target.mkdir(mode=0o700,parents=True,exist_ok=True);continue
  target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
  fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);left=member.size
  with os.fdopen(fd,'wb') as output,stream.extractfile(member) as source:
   while left:
    chunk=source.read(min(left,65536))
    if not chunk:raise RuntimeError('truncated material')
    output.write(chunk);left-=len(chunk)
   output.flush();os.fsync(output.fileno())
"""
PROBE=r"""
import os,json,hashlib,sys,time
from pathlib import Path
root=Path('/tmp/pi-cold');packet=json.loads((root/'input.json').read_bytes())
for name,pin in packet['files'].items():
 p=root/name
 if not p.is_file() or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=pin:raise RuntimeError('restored material changed')
import myink
package=Path(myink.__file__).parent
files={'src/myink/'+p.relative_to(package).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in package.rglob('*.py') if '__pycache__' not in p.parts and not p.is_symlink()}
if hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=packet['runtime_sha256']:raise RuntimeError('imported runtime mismatch')
from dotenv import dotenv_values
values=dotenv_values(root/'crypto')
if not (values.get('MODEL_CREDENTIAL_KEY') or values.get('JWT_SECRET')):raise RuntimeError('explicit recovery key absent')
if (root/'config/.env').read_bytes()!=(root/'crypto').read_bytes() or not (root/'config/docker-compose.yml').read_bytes():raise RuntimeError('restored configuration differs')
for k,v in values.items():
 if isinstance(v,str):os.environ[k]=v
authentication=packet.get('authentication')
app_url=authentication['app_url'] if authentication else 'postgresql+psycopg://myink_app@127.0.0.1:5432/myink'
report_url=authentication['report_url'] if authentication else 'postgresql+psycopg://'+packet['admin']+'@127.0.0.1:5432/myink'
admin_url=authentication['admin_url'] if authentication else 'postgresql://'+packet['admin']+'@127.0.0.1:5432/myink'
if authentication:
 runtime=json.loads((root/'config/effective-runtime.json').read_bytes())
 for container in runtime['containers']:
  actual=dict(entry.split('=',1) for entry in container['config']['Env'])
  for key in ('MODEL_CREDENTIAL_KEY','JWT_SECRET'):
   if values.get(key) and actual.get(key)!=values[key]:raise RuntimeError('effective runtime recovery key differs')
os.environ.update(DATABASE_URL=app_url,ADMIN_DATABASE_URL=report_url,EMBED_ENABLED='0',PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=10000',OTEL_SDK_DISABLED='true',PYTHONDONTWRITEBYTECODE='1')
for k in ('PLATFORM_MODEL_API_KEY','PLATFORM_MODEL_BASE_URL','LANGFUSE_PUBLIC_KEY','LANGFUSE_SECRET_KEY'):os.environ.pop(k,None)
from myink.providers.credentials import decrypt_api_key,decrypt_totp_secret
from myink.db import tenant_session
from sqlalchemy import text
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
counts=dict(authenticated_roles=0,wrong_passwords_rejected=0,credentials=0,mfa_secrets=0,attachments=0,tls_certificates=0,tenant_tables=0,tenant_cases=0,checkpoints=0,pending_writes=0,task_checkpoint_links=0)
def check(value,message):
 if not value:raise RuntimeError(message)
def walk(value,depth=0):
 check(depth<64,'deep recovery JSON')
 if isinstance(value,dict):
  for k,v in value.items():
   if k=='api_key_encrypted' and v:
    check(isinstance(v,str) and decrypt_api_key(v) is not None,'model credential cannot decrypt');counts['credentials']+=1
   else:walk(v,depth+1)
 elif isinstance(value,list):
  for v in value:walk(v,depth+1)
if authentication:
 for role,url in (('myink_app',app_url),('myink_report',report_url)):
  with psycopg.connect(url.replace('postgresql+psycopg://','postgresql://',1),connect_timeout=3,options='-c statement_timeout=10000') as connection:
   check(connection.execute('SELECT current_user').fetchone()[0]==role,'restored authenticated role differs')
   if role=='myink_report':check(connection.execute('SHOW transaction_read_only').fetchone()[0]=='on','report role is not default read only')
  counts['authenticated_roles']+=1
  try:
   wrong=psycopg.connect(host='127.0.0.1',port=5432,dbname='myink',user=role,password='intentionally_invalid_recovery_password',connect_timeout=3)
  except psycopg.OperationalError as error:
   check('password authentication failed' in str(error),'wrong credential did not fail authentication');counts['wrong_passwords_rejected']+=1
  else:
   wrong.close();raise RuntimeError('restored role still permits unauthenticated access')
with psycopg.connect(admin_url,row_factory=dict_row,options='-c default_transaction_read_only=on -c statement_timeout=10000') as db:
 check(db.execute('SELECT system_identifier::text id FROM pg_control_system()').fetchone()['id']==packet['system_identifier'],'foreign restored database')
 role=db.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='myink_app'").fetchone()
 check(role==dict(rolsuper=False,rolbypassrls=False),'application bypasses RLS')
 columns=db.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' AND data_type IN ('json','jsonb') ORDER BY table_name,column_name").fetchall()
 check(len(columns)<=3000,'too many JSON columns')
 for n,col in enumerate(columns):
  with db.cursor(name='recovery_json_'+str(n)) as cur:
   cur.execute(sql.SQL('SELECT {} value FROM public.{}').format(sql.Identifier(col['column_name']),sql.Identifier(col['table_name'])))
   for i,row in enumerate(cur):check(i<100000,'JSON row bound');walk(row['value'])
 if db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='users' AND column_name='totp_secret'").fetchone():
  for i,row in enumerate(db.execute('SELECT totp_secret FROM users WHERE totp_secret IS NOT NULL')):
   check(i<100000 and decrypt_totp_secret(row['totp_secret']) is not None,'MFA credential cannot decrypt');counts['mfa_secrets']+=1
 if db.execute("SELECT to_regclass('public.feedback') id").fetchone()['id']:
  for i,row in enumerate(db.execute('SELECT id::text,attachments FROM feedback')):
   check(i<100000,'attachment row bound')
   for entry in row['attachments'] or []:
    name=entry.get('stored');size=entry.get('bytes');check(isinstance(name,str) and Path(name).name==name and name not in ('.','..') and type(size) is int and size>=0,'unsafe feedback reference')
    p=root/'attachments/feedback'/row['id']/name
    check(p.is_file() and p.stat().st_size==size,'referenced attachment missing or truncated');counts['attachments']+=1
 project_ids={r['id'] for r in db.execute('SELECT id::text id FROM projects LIMIT 1001')}
 check(len(project_ids)<=1000,'project bound')
 # Match db.enable_row_level_security: tasks/agent_runs are global operational tables.
 tables=db.execute("SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relname NOT IN ('tasks','agent_runs') AND EXISTS(SELECT 1 FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attname='project_id' AND NOT a.attisdropped) AND has_table_privilege('myink_app',c.oid,'SELECT') ORDER BY c.relname").fetchall()
 for table in tables:
  check(table['relrowsecurity'] and table['relforcerowsecurity'],'tenant table not forced RLS');name=table['relname'];quoted='"'+name.replace('"','""')+'"'
  expected=db.execute(sql.SQL('SELECT project_id::text id,count(*) n FROM public.{} WHERE project_id IS NOT NULL GROUP BY project_id').format(sql.Identifier(name))).fetchall()
  check(len(expected)<=1000,'tenant bound');counts['tenant_tables']+=1
  with tenant_session('') as app:check(app.scalar(text('SELECT count(*) FROM public.'+quoted))==0,'absent tenant leaks rows')
  expected={r['id']:r['n'] for r in expected}
  tenants=project_ids|set(expected);check(len(tenants)<=1000,'project scope bound')
  for tenant in sorted(tenants):
   with tenant_session(tenant) as app:check(app.scalar(text('SELECT count(*) FROM public.'+quoted))==expected.get(tenant,0),'tenant read differs')
   counts['tenant_cases']+=1
  check(not db.execute("SELECT has_table_privilege('myink_report',%s,'INSERT') allowed",('public.'+quoted,)).fetchone()['allowed'],'report role can write')
 if db.execute("SELECT to_regclass('public.checkpoints') id").fetchone()['id']:
  from langgraph.checkpoint.postgres import PostgresSaver
  saver=PostgresSaver(db)
  for i,saved in enumerate(saver.list(None,limit=10001)):
   check(i<10000 and isinstance(saved.checkpoint,dict) and isinstance(saved.checkpoint.get('channel_values'),dict),'checkpoint cannot decode');counts['checkpoints']+=1;counts['pending_writes']+=len(saved.pending_writes or [])
   thread=saved.config['configurable']['thread_id']
   if db.execute('SELECT 1 FROM tasks WHERE id::text=%s',(thread,)).fetchone():counts['task_checkpoint_links']+=1
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from datetime import datetime,timezone
active_certificates=0
for p in (root/'certificate').rglob('*.crt'):
 key=p.with_suffix('.key')
 active='/certificates/' in p.as_posix()
 if not key.exists():
  check(not active,'active certificate key absent');continue
 cert=x509.load_pem_x509_certificate(p.read_bytes());private=serialization.load_pem_private_key(key.read_bytes(),password=None)
 check(cert.not_valid_after_utc>datetime.now(timezone.utc),'expired recovered certificate')
 check(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)==private.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo),'certificate key differs');counts['tls_certificates']+=1
 if active:active_certificates+=1
site=str(values.get('SITE_ADDRESS') or '').strip()
check(not site or site.startswith('http://') or active_certificates>0,'configured TLS certificate absent')
import socket,threading,urllib.request,uvicorn
from myink.api.main import app
listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(16)
port=listener.getsockname()[1];server=uvicorn.Server(uvicorn.Config(app,log_config=None,log_level='critical',access_log=False,lifespan='on'))
thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start();until=time.monotonic()+20
try:
 while not server.started:
  check(thread.is_alive() and time.monotonic()<until,'API did not cold start');time.sleep(.1)
 with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/healthz',timeout=5) as reply:check(reply.status==200 and json.load(reply)=={'status':'ok'},'API health differs')
except BaseException:
 import faulthandler;faulthandler.dump_traceback(all_threads=True);raise
finally:
 server.should_exit=True;thread.join(5);listener.close()
check(not thread.is_alive(),'API did not stop')
print(json.dumps(dict(verified=True,api_health=True,runtime_sha256=packet['runtime_sha256'],target_system_identifier=packet['system_identifier'],model_requests=0,**counts)))
"""


class OwnedApplicationProbe:
    def __init__(self,restore):
        self.restore=restore;self.host=restore.host;self.plan=restore.plan;self.cid=None;self.role=None

    def _owned(self):
        self.restore._owned()
        require(self.cid is not None and self.role in ('legacy','candidate'),'owned probe binding required')
        result=self.host.commands.run(['inspect',self.cid],timeout=15);rows=strict_json(self.host._bytes(result));require(isinstance(rows,list) and len(rows)==1,'complete application inspect required');v=rows[0];c=v['HostConfig'];labels=v['Config']['Labels']
        require(v['Id']==self.cid and self.cid!=self.restore.cid and self.cid not in {r['id'] for r in self.plan['legacy']['containers']} and v['Image']==self.image,'foreign application probe')
        require(labels.get(LABEL)==self.plan['operation_id'] and labels.get('myink.pi.restore-probe.role')==self.role and v['Config']['User']=='10001','application probe owner drift')
        require(c['NetworkMode']=='container:'+self.restore.cid and c['ReadonlyRootfs'] is True and not c.get('Binds') and not c.get('PortBindings') and not c.get('Privileged') and not c.get('ExtraHosts') and all(m['Type']=='tmpfs' for m in v['Mounts']),'application probe isolation drift')
        require(c['Memory']==536870912 and c['MemorySwap']==536870912 and c['PidsLimit']==64 and c['NanoCpus']==1000000000 and c['CapDrop']==['ALL'] and set(c.get('Tmpfs',{}))=={'/tmp'},'application resource drift')
        return v

    def _pack(self,folder,target,runtime_pin):
        source=self.restore.folder;paths=[source/'crypto']
        for role in ('attachments','config','certificate'):paths.extend(sorted((source/role).rglob('*')))
        files={};total=0
        for p in paths:
            require(not p.is_symlink(),'linked probe material')
            if p.is_dir():continue
            _plain(p);total+=p.stat().st_size;require(len(files)<20000 and total<=self.restore.backend.config['maximum_artifact_bytes'],'bounded application material pack required')
            files[p.relative_to(source).as_posix()]=sha256(p.read_bytes()).hexdigest()
        packet=dict(files=files,admin=self.restore.admin,system_identifier=target['system_identifier'],runtime_sha256=runtime_pin,authentication=self.restore.authentication)
        durable_file(folder/'input.json',encoded(packet));durable_file(folder/'probe.py',PROBE.encode());archive=folder/'materials.tar'
        fd=os.open(archive,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as outgoing:
            with tarfile.open(fileobj=outgoing,mode='w') as stream:
                names=[('pi-cold',None)]+[(str(Path('pi-cold')/p.relative_to(source)),p) for p in paths]+[('pi-cold/input.json',folder/'input.json'),('pi-cold/probe.py',folder/'probe.py')]
                for name,p in names:
                    entry=tarfile.TarInfo(name);entry.uid=entry.gid=10001;entry.mode=0o700 if p is None or p.is_dir() else 0o600
                    if p is None or p.is_dir():entry.type=tarfile.DIRTYPE;stream.addfile(entry)
                    else:
                        entry.size=p.stat().st_size
                        with p.open('rb') as incoming:stream.addfile(entry,incoming)
            outgoing.flush();os.fsync(outgoing.fileno())
        require(archive.stat().st_size<=536870912,'packed material exceeds native transport bound')
        return archive

    def check(self,role,target):
        require(role in ('legacy','candidate'),'fixed application image role required');self.role=role;h=self.host;h.authorize(self.plan);self.restore._owned()
        require(target['container_id']==self.restore.cid and target['system_identifier']!=target['source_system_identifier'],'exact distinct restored target required')
        self.image=self.plan['candidate']['image_ids']['python'] if role=='candidate' else next(r['image_id'] for r in self.plan['legacy']['containers'] if r['service']=='api')
        manifest=_pinned(h.config[role+'_manifest_path'],h.config[role+'_manifest_sha256'],h.config['mode']=='ACTUAL')
        expected_commit=self.plan['candidate']['commit_sha'] if role=='candidate' else self.plan['legacy']['source_commit']
        require(isinstance(manifest,dict) and set(manifest)=={'source_commit','files'} and manifest['source_commit']==expected_commit,'frozen application source required')
        files={k:v for k,v in manifest['files'].items() if k.startswith('src/myink/') and k.endswith('.py')};require(files,'application source absent');runtime_pin=digest(files)
        folder=self.restore.folder/('application-'+role);folder.mkdir(mode=0o700);durable_file(folder/'intent.json',encoded(dict(plan_sha256=digest(self.plan),target_system_identifier=target['system_identifier'],image_id=self.image,runtime_sha256=runtime_pin)))
        archive=self._pack(folder,target,runtime_pin)
        require(len(PROBE.encode())<=32768,'bounded fixed application program required')
        try:
            result=h._run(['create','--name','myink-pi-restore-probe-'+self.restore.registry['attempt_uuid']+'-'+role,'--label',LABEL+'='+self.plan['operation_id'],'--label','myink.pi.restore-probe.role='+role,'--network','container:'+self.restore.cid,'--read-only','--tmpfs','/tmp:rw,size=536870912','--memory','536870912','--memory-swap','536870912','--cpus','1.0','--pids-limit','64','--cap-drop','ALL','--security-opt','no-new-privileges','--user','10001','--env','HOME=/tmp',self.image,*WAIT]);self.cid=h._bytes(result).decode().strip();require(len(self.cid)==64 and all(c in '0123456789abcdef' for c in self.cid),'actual probe ID required')
            durable_file(folder/'registry.json',encoded(dict(container_id=self.cid,image_id=self.image,target_container_id=self.restore.cid,role=role)));self._owned()
            h._run(['start',self.cid]);self._owned()
            h._run(['exec','-i',self.cid,'python','-B','-c',UNPACK],stdin_path=archive,seconds=90);self._owned()
            bootstrap="import hashlib,sys;from pathlib import Path;p=Path('/tmp/pi-cold/probe.py');raw=p.read_bytes();assert hashlib.sha256(raw).hexdigest()==sys.argv[1];exec(compile(raw,str(p),'exec'),{'__name__':'__main__'})"
            result=h._run(['exec',self.cid,'python','-B','-c',bootstrap,sha256(PROBE.encode()).hexdigest()],seconds=180);observed=strict_json(h._bytes(result))
            counts={'authenticated_roles','wrong_passwords_rejected','credentials','mfa_secrets','attachments','tls_certificates','tenant_tables','tenant_cases','checkpoints','pending_writes','task_checkpoint_links','model_requests'}
            require(isinstance(observed,dict) and set(observed)==counts|{'verified','api_health','runtime_sha256','target_system_identifier'} and observed['verified'] is True and observed['api_health'] is True and observed['runtime_sha256']==runtime_pin and observed['target_system_identifier']==target['system_identifier'] and all(type(observed[k]) is int and observed[k]>=0 for k in counts) and observed['model_requests']==0,'application assertions unconfirmed')
            if self.restore.authentication is not None:require(observed['authenticated_roles']==observed['wrong_passwords_rejected']==2,'real restored role authentication unconfirmed')
            if self.restore.authentication is not None:
                from .product_restored_api import OwnedRestoredAPI
                observed=dict(observed,main_api=OwnedRestoredAPI(self).check(runtime_pin))
            durable_file(folder/'receipt.json',encoded(observed));return observed
        finally:
            if self.cid is not None:
                self._owned();h.commands.run(['rm','--force',self.cid],timeout=30)
                result=h.commands.run(['ps','--all','--quiet','--no-trunc','--filter','label='+LABEL+'='+self.plan['operation_id'],'--filter','label=myink.pi.restore-probe.role='+role],timeout=15)
                require(not h._bytes(result).strip(),'application probe cleanup unconfirmed')
