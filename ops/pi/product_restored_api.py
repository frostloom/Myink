"""A real restored API main process, confined to the owned PG namespace."""
from pathlib import Path
from urllib.parse import urlsplit,unquote,quote
import os,time,tarfile
from hashlib import sha256
from .audit import digest,encoded,require,strict_json,hash_value
from .backup import durable_file
from .product_activation import environment
from .product_runtime_snapshot import connection_settings,local_url

LABEL='myink.pi.restored-api.operation'


def _local_service(value,scheme,host,port):
    require(isinstance(value,str) and len(value)<=16384,'bounded service URL required')
    p=urlsplit(value);password=unquote(p.password or '')
    require(p.scheme==scheme and p.hostname in (host,'127.0.0.1','localhost') and p.port in (None,port) and password and not any(ord(c)<32 for c in password) and not p.query and not p.fragment,'fixed private service credential required')
    if scheme=='redis':require(p.username in (None,'') and p.path in ('','/0'),'fixed Redis database required')
    else:require(p.username=='myink' and p.path=='/','fixed Rabbit vhost required')
    return scheme+'://'+('myink' if scheme=='amqp' else '')+':'+quote(password,safe='')+'@127.0.0.1:'+str(port)+('/0' if scheme=='redis' else '/')


def api_environment(snapshot,authentication):
    urls=connection_settings(snapshot)
    require(isinstance(authentication,dict) and local_url(authentication['app_url'],'myink_app')==urls['app'] and local_url(authentication['report_url'],'myink_report')==urls['report'],'restored application credentials differ')
    row=next(v for v in snapshot['containers'] if v['service']=='api');c=row['config']
    require(c['Cmd']==['myink-api'] and c['User']=='10001' and c.get('Entrypoint') in (None,[]) and c['WorkingDir']=='/app','fixed main API command required')
    values=environment(c['Env']);require(not any(k in values for k in ('PYTHONPATH','PYTHONHOME','LD_PRELOAD')),'interpreter override rejected')
    values['REDIS_URL']=_local_service(values.get('REDIS_URL'),'redis','myink-redis',6379)
    values['AMQP_URL']=_local_service(values.get('AMQP_URL'),'amqp','myink-rabbitmq',5672)
    # The original application settings are retained. Only isolated endpoints,
    # read-only operation and disabled external providers/telemetry are changed.
    for k in ('PLATFORM_MODEL_API_KEY','PLATFORM_MODEL_BASE_URL','LANGFUSE_PUBLIC_KEY','LANGFUSE_SECRET_KEY'):values.pop(k,None)
    values.update(DATABASE_URL=urls['app'],ADMIN_DATABASE_URL=urls['report'],API_HOST='127.0.0.1',API_PORT='8100',FEEDBACK_DIR='/data/feedback',HOME='/tmp',EMBED_ENABLED='0',PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=10000',OTEL_SDK_DISABLED='true',PYTHONDONTWRITEBYTECODE='1')
    return values


UNPACK=r"""
import sys,tarfile,os
from pathlib import Path,PurePosixPath
seen=set();total=0
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as stream:
 for member in stream:
  path=PurePosixPath(member.name)
  if not path.parts or path.is_absolute() or '..' in path.parts or path.parts[0]!='feedback' or str(path) in seen or not (member.isfile() or member.isdir()):raise RuntimeError('unsafe main API attachment')
  seen.add(str(path));total+=member.size
  if len(seen)>20000 or member.size<0 or total>536870912:raise RuntimeError('main API attachment bound')
  target=Path('/data').joinpath(*path.parts)
  if member.isdir():target.mkdir(mode=0o700,parents=True,exist_ok=True);continue
  target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
  fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as output,stream.extractfile(member) as incoming:
   left=member.size
   while left:
    chunk=incoming.read(min(left,65536))
    if not chunk:raise RuntimeError('truncated main API attachment')
    output.write(chunk);left-=len(chunk)
"""


CHECK=r"""
import sys,os,json,hashlib,time,urllib.request
from pathlib import Path
from datetime import datetime,timezone,timedelta
p=json.loads(sys.stdin.buffer.read(262145))
def check(value,message):
 if not value:raise RuntimeError(message)
cmd=Path('/proc/1/cmdline').read_bytes().split(b'\0');cmd=[v for v in cmd if v]
check(cmd and cmd[-1].rsplit(b'/',1)[-1]==b'myink-api','restored API is not the main process')
actual=dict(v.split('=',1) for v in Path('/proc/1/environ').read_bytes().decode().split('\0') if '=' in v)
check(all(actual.get(k)==v for k,v in p['environment'].items()),'restored main effective environment differs')
import myink
package=Path(myink.__file__).parent
files={'src/myink/'+v.relative_to(package).as_posix():hashlib.sha256(v.read_bytes()).hexdigest() for v in package.rglob('*.py') if '__pycache__' not in v.parts and not v.is_symlink()}
pin=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
check(pin==p['runtime_sha256'],'main API imported source differs')
for name,expected in p['attachments'].items():
 file=Path('/data')/name;check(file.is_file() and not file.is_symlink() and hashlib.sha256(file.read_bytes()).hexdigest()==expected,'main API restored attachment differs')
def get(path,bearer=None):
 request=urllib.request.Request('http://127.0.0.1:8100'+path,headers={'Authorization':'Bearer '+bearer} if bearer else {})
 with urllib.request.urlopen(request,timeout=3) as response:
  data=response.read(4194305);check(len(data)<=4194304 and response.status==200,'restored API response bound');return json.loads(data)
until=time.monotonic()+120
while True:
 try:check(get('/healthz')=={'status':'ok'},'restored main health differs');break
 except (OSError,TimeoutError):check(time.monotonic()<until,'restored main startup unconfirmed');time.sleep(.1)
check(get('/api/v1/projects')==[],'anonymous restored project leak')
import psycopg,jwt
from myink.config import settings
cases=0
with psycopg.connect(settings.database_url.replace('postgresql+psycopg://','postgresql://',1),connect_timeout=3) as db:
 check(db.execute('SELECT current_user').fetchone()[0]=='myink_app','main API role differs')
 users=db.execute('SELECT id::text,auth_version FROM users WHERE id IN (SELECT user_id FROM projects) ORDER BY id LIMIT 17').fetchall()
 check(len(users)<=16,'restored owner read bound')
 for user,version in users:
  expected={v[0] for v in db.execute('SELECT id::text FROM projects WHERE user_id=%s ORDER BY id LIMIT 1001',(user,)).fetchall()};check(len(expected)<=1000,'restored project bound')
  now=datetime.now(timezone.utc);token=jwt.encode(dict(sub=user,ver=version,tier='normal',iss='myink',iat=now,exp=now+timedelta(seconds=60)),settings.jwt_secret,algorithm='HS256')
  got=get('/api/v1/projects',token);check(isinstance(got,list) and {v['id'] for v in got}==expected and len(got)==len(expected),'restored owner projects differ');cases+=1
print(json.dumps(dict(verified=True,api_health=True,main_process=True,effective_environment_sha256=hashlib.sha256(json.dumps(p['environment'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),runtime_sha256=pin,owner_cases=cases,anonymous_rejections=1,attachment_files=len(p['attachments']),model_requests=0)))
"""


class OwnedRestoredAPI:
    def __init__(self,probe):
        self.probe=probe;self.restore=probe.restore;self.host=probe.host;self.plan=probe.plan;self.cid=None

    def _owned(self):
        self.restore._owned();require(self.cid is not None,'owned main API registry required')
        result=self.host.commands.run(['inspect',self.cid],timeout=15);rows=strict_json(self.host._bytes(result));require(isinstance(rows,list) and len(rows)==1,'complete main API inspect required');v=rows[0];c=v['Config'];h=v['HostConfig']
        require(v['Id']==self.cid and self.cid!=self.restore.cid and self.cid not in {v['id'] for v in self.plan['legacy']['containers']} and v['Image']==self.probe.image,'foreign restored main API')
        require(c['Labels'].get(LABEL)==self.plan['operation_id'] and c['Labels'].get('myink.pi.restored-api.role')==self.probe.role and c['User']=='10001' and c['Cmd']==['myink-api'] and c.get('Entrypoint') in (None,[]) and c['WorkingDir']=='/app','main API identity drift')
        require(environment(c['Env'])==self.values,'main API runtime settings drift')
        require(h['NetworkMode']=='container:'+self.restore.cid and h['ReadonlyRootfs'] is True and not h.get('Binds') and not h.get('PortBindings') and not h.get('Privileged') and not h.get('ExtraHosts') and not h.get('PidMode') and h.get('IpcMode','private')=='private','main API isolation drift')
        require(all(m['Type']=='tmpfs' for m in v['Mounts']) and not v['NetworkSettings'].get('Ports') and set(h.get('Tmpfs',{}))=={'/tmp','/data/feedback'},'main API mounts or ports drift')
        require(h['Memory']==h['MemorySwap']==self.resources['Memory'] and h['NanoCpus']==self.resources['NanoCpus'] and h['PidsLimit']==128 and h['CapDrop']==['ALL'] and 'no-new-privileges' in h['SecurityOpt'] and not v['State']['OOMKilled'],'main API resource drift')
        return v

    def check(self,runtime_pin):
        h=self.host;h.authorize(self.plan);self.restore._owned()
        path=self.restore.folder/'config/effective-runtime.json';snapshot=strict_json(path.read_bytes());require(snapshot['plan_sha256']==digest(self.plan),'main API runtime plan differs')
        self.values=api_environment(snapshot,self.restore.authentication);row=next(v for v in snapshot['containers'] if v['service']=='api');self.resources=row['host_config'];require(type(self.resources['Memory']) is int and 0<self.resources['Memory']<=1073741824 and type(self.resources['NanoCpus']) is int and 0<self.resources['NanoCpus']<=2000000000,'bounded recovered API resources required')
        folder=self.restore.folder/('main-api-'+self.probe.role);folder.mkdir(mode=0o700)
        durable_file(folder/'intent.json',encoded(dict(plan_sha256=digest(self.plan),image_id=self.probe.image,target_container_id=self.restore.cid,runtime_sha256=runtime_pin,environment_sha256=digest(self.values))))
        env=folder/'runtime.env';durable_file(env,(''.join(k+'='+v+'\n' for k,v in sorted(self.values.items()))).encode())
        attachments={};source=self.restore.folder/'attachments';archive=folder/'attachments.tar'
        fd=os.open(archive,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as output,tarfile.open(fileobj=output,mode='w') as stream:
            total=0
            for file in sorted(source.rglob('*')):
                require(not file.is_symlink(),'linked restored main attachment')
                if file.is_dir():continue
                name=file.relative_to(source).as_posix();require(name.startswith('feedback/') and file.is_file(),'fixed feedback path required');total+=file.stat().st_size
                require(total<=536870912 and len(attachments)<20000,'bounded main API attachments required');attachments[name]=sha256(file.read_bytes()).hexdigest()
                info=tarfile.TarInfo(name);info.size=file.stat().st_size;info.mode=0o600
                with file.open('rb') as incoming:stream.addfile(info,incoming)
        packet=folder/'check.json';durable_file(packet,encoded(dict(environment=self.values,runtime_sha256=runtime_pin,attachments=attachments)))
        try:
            args=['create','--name','myink-pi-restored-api-'+self.restore.registry['attempt_uuid']+'-'+self.probe.role,'--label',LABEL+'='+self.plan['operation_id'],'--label','myink.pi.restored-api.role='+self.probe.role,'--network','container:'+self.restore.cid,'--read-only','--tmpfs','/tmp:rw,size=67108864','--tmpfs','/data/feedback:rw,size=536870912,uid=10001,gid=10001','--memory',str(self.resources['Memory']),'--memory-swap',str(self.resources['Memory']),'--cpus',str(self.resources['NanoCpus']/1000000000),'--pids-limit','128','--cap-drop','ALL','--security-opt','no-new-privileges','--user','10001','--workdir','/app','--env-file',str(env),self.probe.image,'myink-api']
            result=h._run(args);self.cid=h._bytes(result).decode().strip();require(hash_value(self.cid),'actual main API ID required');durable_file(folder/'registry.json',encoded(dict(container_id=self.cid,image_id=self.probe.image,target_container_id=self.restore.cid)));self._owned()
            h._run(['start',self.cid]);require(self._owned()['State']['Running'],'restored main API exited')
            h._run(['exec','-i',self.cid,'python','-B','-c',UNPACK],stdin_path=archive,seconds=90);self._owned()
            result=h._run(['exec','-i',self.cid,'python','-B','-c',CHECK],stdin_path=packet,seconds=150);observed=strict_json(h._bytes(result))
            require(isinstance(observed,dict) and set(observed)=={'verified','api_health','main_process','effective_environment_sha256','runtime_sha256','owner_cases','anonymous_rejections','attachment_files','model_requests'} and observed['verified'] is True and observed['api_health'] is True and observed['main_process'] is True and observed['effective_environment_sha256']==digest(self.values) and observed['runtime_sha256']==runtime_pin and type(observed['owner_cases']) is int and 0<=observed['owner_cases']<=16 and observed['anonymous_rejections']==1 and observed['attachment_files']==len(attachments) and observed['model_requests']==0,'restored main API assertions unconfirmed')
            h._run(['stop','--signal','SIGTERM','--timeout','-1',self.cid],seconds=30);state=self._owned()['State'];require(not state['Running'] and state['ExitCode']==0,'restored main API did not exit naturally')
            result=dict(observed,natural_exit_code=0,scope='restored_main_api_reads_only');durable_file(folder/'receipt.json',encoded(result));return result
        finally:
            if self.cid is not None:
                self._owned()
                try:
                    logs=h.commands.run(['logs','--tail','200',self.cid],timeout=15,output_limit=65536)
                    durable_file(folder/'diagnostic-logs.json',encoded(logs))
                finally:
                    self._owned();h.commands.run(['rm','--force',self.cid],timeout=30)
                value=h.commands.run(['ps','--all','--quiet','--no-trunc','--filter','label='+LABEL+'='+self.plan['operation_id'],'--filter','label=myink.pi.restored-api.role='+self.probe.role],timeout=15);require(not h._bytes(value).strip(),'restored main API cleanup unconfirmed')
