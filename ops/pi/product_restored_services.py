"""Owned Redis/Rabbit/workers/Caddy for a restored API; no external network."""
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit,unquote
import os,tarfile,time,ipaddress
from urllib.parse import urlunsplit
from .audit import digest,encoded,require,strict_json,hash_value
from .backup import durable_file
from .product_activation import environment
from .product_restored_api import api_environment
from .product_service_snapshot import capture,isolated_ingress,_redis,unpublished

LABEL='myink.pi.restored-service.operation'
WAIT_REDIS='while [ ! -f /tmp/service-ready ]; do sleep 0.1; done; exec redis-server /tmp/redis.conf'
WAIT_CADDY='while [ ! -f /tmp/service-ready ]; do sleep 0.1; done; cp /usr/bin/caddy /run/pi-caddy/owned-caddy && cmp /usr/bin/caddy /run/pi-caddy/owned-caddy && exec /run/pi-caddy/owned-caddy run --config /tmp/service.json'
SETUP=r"""
import sys,json,time,redis,pika
p=json.loads(sys.stdin.buffer.read(33554433));r=redis.Redis.from_url(p['environment']['REDIS_URL'],socket_connect_timeout=2,socket_timeout=3)
until=time.monotonic()+90
while True:
 try:r.ping();break
 except redis.ConnectionError:
  if time.monotonic()>=until:raise
  time.sleep(.2)
if r.dbsize()!=0:raise RuntimeError('restored Redis was not fresh')
for row in p['redis']['keys']:
 expiry=row['expires_at_ms'];now=int(r.time()[0]*1000)
 if expiry is not None and expiry<=now:continue
 r.restore(bytes.fromhex(row['key_hex']),0 if expiry is None else expiry,bytes.fromhex(row['dump_hex']),absttl=expiry is not None)
from urllib.parse import urlsplit
wrong=redis.Redis(host=urlsplit(p['environment']['REDIS_URL']).hostname,port=6379,password='intentionally_invalid_service_password',socket_connect_timeout=2,socket_timeout=3)
try:wrong.ping()
except redis.AuthenticationError:pass
else:raise RuntimeError('restored Redis accepted wrong credential')
params=pika.URLParameters(p['environment']['AMQP_URL']);params.socket_timeout=2;params.connection_attempts=1;params.blocked_connection_timeout=3;params.heartbeat=30
until=time.monotonic()+120
while True:
 try:connection=pika.BlockingConnection(params);break
 except pika.exceptions.AMQPConnectionError:
  if time.monotonic()>=until:raise
  time.sleep(.5)
# Use frozen application's real topology, not a model-defined queue declaration.
import os
os.environ.update(p['environment'])
from myink.worker import amqp
with connection:
 channel=connection.channel();amqp.declare_topology(channel)
 for name in (amqp.main_queue(),amqp.vip_queue(),amqp.delay_queue(),amqp.vip_delay_queue(),amqp.dlq_queue()):
  value=channel.queue_declare(name,passive=True).method
  if value.message_count!=0 or value.consumer_count!=0:raise RuntimeError('owned restored queue not empty')
bad=pika.URLParameters(p['environment']['AMQP_URL']);bad.credentials=pika.PlainCredentials('myink','intentionally_invalid_service_password');bad.socket_timeout=2;bad.connection_attempts=1
try:wrong=pika.BlockingConnection(bad)
except (pika.exceptions.ProbableAuthenticationError,pika.exceptions.ProbableAccessDeniedError):pass
else:wrong.close();raise RuntimeError('restored Rabbit accepted wrong credential')
print(json.dumps(dict(verified=True,redis_authenticated=True,rabbit_authenticated=True,wrong_passwords_rejected=2,empty_queues=5,model_requests=0)))
"""
VERIFY=r"""
import sys,json,time,redis,urllib.request,ssl,socket,http.client,hashlib
p=json.loads(sys.stdin.buffer.read(33554433));r=redis.Redis.from_url(p['environment']['REDIS_URL'],socket_connect_timeout=2,socket_timeout=3)
until=time.monotonic()+120
while True:
 if all(r.get('queue:heartbeat:'+host+'-1')==b'1' for host in p['workers']):break
 if time.monotonic()>=until:raise RuntimeError('actual restored worker heartbeat absent')
 time.sleep(.2)
with urllib.request.urlopen('http://127.0.0.1:8100/readyz',timeout=3) as response:
 value=json.load(response)
 if response.status!=200 or value!={'status':'ok','checks':{'redis':'ok','db':'ok','worker':'ok'}}:raise RuntimeError('restored dependency readiness differs')
url=p['site'];host=url.split('://',1)[-1].split('/',1)[0].split(':',1)[0]
until=time.monotonic()+30
while True:
 try:
  if p['https']:
   context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
   raw=socket.create_connection(('127.0.0.1',8443),timeout=3);connection=context.wrap_socket(raw,server_hostname=host)
   if hashlib.sha256(connection.getpeercert(binary_form=True)).hexdigest() not in p['certificate_pins']:raise RuntimeError('restored TLS certificate differs')
   connection.sendall(('GET /readyz HTTP/1.1\r\nHost: '+host+'\r\nConnection: close\r\n\r\n').encode());response=http.client.HTTPResponse(connection);response.begin();code=response.status;body=response.read(1048577);connection.close()
  else:
   request=urllib.request.Request('http://127.0.0.1:8080/readyz',headers={'Host':host})
   with urllib.request.urlopen(request,timeout=3) as response:code=response.status;body=response.read(1048577)
  if code!=200 or len(body)>1048576 or json.loads(body)!=value:raise RuntimeError('restored Caddy dependency route differs')
  break
 except (OSError,TimeoutError):
  if time.monotonic()>=until:raise
  time.sleep(.2)
# Source counters/quotas retain values and absolute TTLs. Only this cohort's
# genuine worker heartbeat keys may be new; no fake heartbeat is inserted.
now=r.time();now=now[0]*1000+now[1]//1000;expected={bytes.fromhex(v['key_hex']):v for v in p['redis']['keys'] if v['expires_at_ms'] is None or v['expires_at_ms']>now}
allowed={('queue:heartbeat:'+host+'-1').encode() for host in p['workers']}
if set(r.scan_iter())!=set(expected)|allowed:raise RuntimeError('restored Redis key census differs')
for key,row in expected.items():
 if r.dump(key).hex()!=row['dump_hex'] or (r.pexpiretime(key) if row['expires_at_ms'] is not None else None)!=row['expires_at_ms']:raise RuntimeError('restored quota/value/expiry changed')
print(json.dumps(dict(verified=True,ready=True,caddy_ready=True,worker_heartbeats=len(p['workers']),retained_redis_keys=len(expected),tls_pinned=p['https'],model_requests=0)))
"""


WORKER_CHECK=r"""
import json,os
from pathlib import Path
from urllib.parse import urlsplit
import psycopg,redis,pika
from myink.config import settings
from myink.worker import amqp
cmd=[v for v in Path('/proc/1/cmdline').read_bytes().split(b'\0') if v]
if not cmd or cmd[-1].rsplit(b'/',1)[-1]!=b'myink-worker':raise RuntimeError('restored worker is not main process')
with psycopg.connect(settings.database_url.replace('postgresql+psycopg://','postgresql://',1),connect_timeout=3) as db:
 if db.execute('SELECT current_user').fetchone()[0]!='myink_app' or db.execute('SHOW transaction_read_only').fetchone()[0]!='on':raise RuntimeError('restored worker database role/boundary differs')
p=urlsplit(settings.database_url)
try:bad=psycopg.connect(host=p.hostname,port=p.port or 5432,dbname='myink',user='myink_app',password='intentionally_invalid_worker_password',connect_timeout=3)
except psycopg.OperationalError as error:
 if 'password authentication failed' not in str(error):raise RuntimeError('worker bad credential did not reach authentication')
else:bad.close();raise RuntimeError('worker database accepted wrong password')
if not redis.Redis.from_url(settings.redis_url,socket_connect_timeout=2,socket_timeout=3).ping():raise RuntimeError('worker Redis authentication failed')
params=pika.URLParameters(settings.amqp_url);params.socket_timeout=2;params.connection_attempts=1;params.blocked_connection_timeout=3
with pika.BlockingConnection(params) as connection:
 channel=connection.channel()
 for name in (amqp.main_queue(),amqp.vip_queue(),amqp.delay_queue(),amqp.vip_delay_queue(),amqp.dlq_queue()):
  if channel.queue_declare(name,passive=True).method.message_count!=0:raise RuntimeError('worker restored queue not empty')
print(json.dumps(dict(verified=True,main_process=True,application_role='myink_app',read_only=True,redis_authenticated=True,rabbit_authenticated=True,empty_queues=5,wrong_database_password_rejected=True,model_requests=0)))
"""


def _endpoint(value,host,subnet):
    address=ipaddress.ip_address(host);network=ipaddress.ip_network(subnet);require(address.version==4 and address.is_private and address in network,'owned service address required')
    parsed=urlsplit(value);require(parsed.hostname=='127.0.0.1','original isolated endpoint required')
    credentials=parsed.netloc.rsplit('@',1)[0]+'@' if '@' in parsed.netloc else ''
    return urlunsplit((parsed.scheme,credentials+str(address)+(':'+str(parsed.port) if parsed.port else ''),parsed.path,parsed.query,parsed.fragment))


class OwnedServiceCohort:
    def __init__(self,api,runtime):
        self.api=api;self.restore=api.restore;self.probe=api.probe;self.host=api.host;self.plan=api.plan;self.runtime=runtime;self.rows=[]
        self.folder=self.restore.folder/('services-'+self.probe.role);self.folder.mkdir(mode=0o700)
        require(self.restore.network is not None,'private runtime recovery network required');self.network=self.restore.network
        self.material=strict_json((self.restore.folder/'config/effective-services.json').read_bytes());self.redis=strict_json((self.restore.folder/'config/redis-state.json').read_bytes());_redis(self.redis)
        m=self.material;raw=[dict(Id=v['id'],Image=v['image_id'],Config=v['config'],HostConfig=v['host_config'],Mounts=v['mounts']) for v in m['services'].values()]
        require(m==capture(self.plan,runtime,raw,m['ingress']),'restored infrastructure binding differs')
        durable_file(self.folder/'intent.json',encoded(dict(plan_sha256=digest(self.plan),service_material_sha256=digest(m),redis_state_sha256=digest(self.redis))))

    def _owned(self,row):
        self.restore._owned();h=self.host;result=h.commands.run(['inspect',row['id']],timeout=15);values=strict_json(h._bytes(result));require(isinstance(values,list) and len(values)==1,'complete restored service inspect required');v=values[0];c=v['Config'];hc=v['HostConfig']
        require(v['Id']==row['id'] and v['Image']==row['image'] and row['id'] not in {v['id'] for v in self.plan['legacy']['containers']} and c['Labels'].get(LABEL)==self.plan['operation_id'] and c['Labels'].get('myink.pi.restored-service.member')==row['member'] and c['Labels'].get('myink.pi.restored-service.cohort')==self.probe.role,'foreign restored service')
        require(c['User']==row['user'] and c['Cmd']==row['command'] and c.get('Entrypoint')==row['entrypoint'] and environment(c['Env'])==row['environment'],'restored service command/environment drift')
        mode='container:'+self.restore.cid if row['member']=='caddy' else self.network['id']
        require(hc['NetworkMode']==mode and not hc.get('PortBindings') and not hc.get('Binds') and not hc.get('Privileged') and not hc.get('ExtraHosts') and not hc.get('PidMode') and hc.get('IpcMode','private')=='private' and hc['ReadonlyRootfs'] is True,'restored service isolation drift')
        require(hc['Memory']==hc['MemorySwap']==row['memory'] and hc['NanoCpus']==1000000000 and hc['PidsLimit']==256 and hc['CapDrop']==['ALL'] and 'no-new-privileges' in hc['SecurityOpt'] and set(hc.get('Tmpfs',{}))==set(row['tmpfs']) and all(v['Type']=='tmpfs' for v in v['Mounts']) and unpublished(v['NetworkSettings'].get('Ports') or {}),'restored service resource/mount drift')
        return v

    def _create(self,member,image,values,command,*,user,entrypoint,tmpfs,memory=536870912):
        folder=self.folder/member;folder.mkdir(mode=0o700);env=folder/'runtime.env';durable_file(env,(''.join(k+'='+v+'\n' for k,v in sorted(values.items()))).encode());durable_file(folder/'intent.json',encoded(dict(member=member,image_id=image,environment_sha256=digest(values),plan_sha256=digest(self.plan))))
        args=['create','--name','myink-pi-restored-'+self.restore.registry['attempt_uuid']+'-'+self.probe.role+'-'+member,'--label',LABEL+'='+self.plan['operation_id'],'--label','myink.pi.restored-service.member='+member,'--label','myink.pi.restored-service.cohort='+self.probe.role,'--network',('container:'+self.restore.cid if member=='caddy' else self.network['id']),'--read-only','--memory',str(memory),'--memory-swap',str(memory),'--cpus','1','--pids-limit','256','--cap-drop','ALL','--security-opt','no-new-privileges','--user',user,'--env-file',str(env)]
        for path,options in tmpfs.items():args+=['--tmpfs',path+':'+options]
        if entrypoint is not None:args+=['--entrypoint',entrypoint[0]]
        result=self.host._run(args+[image]+command);cid=self.host._bytes(result).decode().strip();require(hash_value(cid),'actual restored service ID required')
        row=dict(id=cid,image=image,environment=values,command=command,user=user,entrypoint=entrypoint,tmpfs=tmpfs,memory=memory,member=member);self.rows.append(row);self.restore.network_members.add(cid);durable_file(folder/'registry.json',encoded(dict(container_id=cid,image_id=image,member=member)));self._owned(row);self.host._run(['start',cid]);require(self._owned(row)['State']['Running'],'restored service exited');return row

    def _address(self,row):
        v=self._owned(row);endpoint=v['NetworkSettings']['Networks'][self.network['name']];require(endpoint['NetworkID']==self.network['id'],'service endpoint changed');address=endpoint['IPAddress'];require(ipaddress.ip_address(address) in ipaddress.ip_network(self.restore._network_owned()),'service address outside owned network');return address

    def _packet(self,name,value):
        path=self.folder/(name+'.json');durable_file(path,encoded(value));return path

    def _check(self,program,packet,seconds):
        self.restore._owned();result=self.host._run(['exec','-i',self.probe.cid,'python','-B','-c',program],stdin_path=packet,seconds=seconds);return strict_json(self.host._bytes(result))

    def prepare(self):
        services=self.material['services'];h=self.host
        values=environment(services['redis']['config']['Env']);row=self._create('redis',services['redis']['image_id'],values,['-c',WAIT_REDIS],user='redis',entrypoint=['/bin/sh'],tmpfs={'/tmp':'rw,size=16777216','/data':'rw,size=16777216,mode=1777'},memory=134217728)
        config=self.folder/'redis.conf';password=unquote(urlsplit(self.api.values['REDIS_URL']).password);durable_file(config,('bind 0.0.0.0\nport 6379\nrequirepass '+__import__('json').dumps(password,ensure_ascii=False)+'\nsave ""\nappendonly no\n').encode())
        h._run(['exec','-i',row['id'],'sh','-c','cat > /tmp/redis.conf && touch /tmp/service-ready'],stdin_path=config);self._owned(row)
        self.api.values['REDIS_URL']=_endpoint(self.api.values['REDIS_URL'],self._address(row),self.restore._network_owned())
        values=environment(services['rabbitmq']['config']['Env']);values.update(RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS='+S 2:2')
        rabbit=self._create('rabbit',services['rabbitmq']['image_id'],values,['rabbitmq-server'],user='rabbitmq',entrypoint=['/usr/local/bin/docker-entrypoint.sh'],tmpfs={'/tmp':'rw,size=33554432','/var/lib/rabbitmq':'rw,size=134217728,mode=1777','/var/log/rabbitmq':'rw,size=16777216,mode=1777'})
        self.api.values['AMQP_URL']=_endpoint(self.api.values['AMQP_URL'],self._address(rabbit),self.restore._network_owned())
        result=self._check(SETUP,self._packet('setup',dict(environment=self.api.values,redis=self.redis)),180)
        require(result==dict(verified=True,redis_authenticated=True,rabbit_authenticated=True,wrong_passwords_rejected=2,empty_queues=5,model_requests=0),'restored service authentication unconfirmed');self.authentication=result
        self.workers=[]
        for index,original in enumerate(v for v in self.runtime['containers'] if v['service']=='worker'):
            require(original['config']['Cmd']==['myink-worker'] and original['config']['User']=='10001','fixed original worker command required')
            template=deepcopy(self.runtime);api=next(v for v in template['containers'] if v['service']=='api');api['config']=deepcopy(original['config']);api['config']['Cmd']=['myink-api']
            # The API-only report role is isolated, never an admin role. Preserve
            # its absence on a worker that did not originally have this setting.
            had_report=any(v.startswith('ADMIN_DATABASE_URL=') for v in original['config']['Env'])
            if not had_report:api['config']['Env'].append('ADMIN_DATABASE_URL='+self.restore.authentication['report_url'])
            values=api_environment(template,self.restore.authentication)
            if not had_report:values.pop('ADMIN_DATABASE_URL')
            pg=self.restore._owned()['NetworkSettings']['Networks'][self.network['name']]['IPAddress'];subnet=self.restore._network_owned()
            values['DATABASE_URL']=_endpoint(values['DATABASE_URL'],pg,subnet)
            if had_report:values['ADMIN_DATABASE_URL']=_endpoint(values['ADMIN_DATABASE_URL'],pg,subnet)
            values.update(REDIS_URL=self.api.values['REDIS_URL'],AMQP_URL=self.api.values['AMQP_URL'])
            row=self._create('worker'+str(index),self.probe.image,values,['myink-worker'],user='10001',entrypoint=None,tmpfs={'/tmp':'rw,size=67108864'})
            inspected=self._owned(row);self.workers.append(inspected['Config']['Hostname'])
        require(len(set(self.workers))==2,'distinct actual worker identities required')
        return result

    def start_frontend(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        source=self.restore.folder/'certificate';certificates=[];pins=[]
        for cert in source.rglob('*.crt'):
            key=cert.with_suffix('.key')
            if '/certificates/' in cert.as_posix() and key.is_file():
                relative='/'+cert.relative_to(source).as_posix();certificates.append(dict(certificate=relative,key='/'+key.relative_to(source).as_posix()));pins.append(__import__('hashlib').sha256(x509.load_pem_x509_certificate(cert.read_bytes()).public_bytes(serialization.Encoding.DER)).hexdigest())
        config=isolated_ingress(self.material['ingress'],certificates);self.https=any(':8443' in v for s in config['apps']['http']['servers'].values() for v in s['listen']);self.pins=pins
        values=environment(self.material['services']['frontend']['config']['Env']);values.update(HOME='/tmp',XDG_DATA_HOME='/data',XDG_CONFIG_HOME='/config')
        row=self._create('caddy',self.material['services']['frontend']['image_id'],values,['-c',WAIT_CADDY],user='10001',entrypoint=['/bin/sh'],tmpfs={'/tmp':'rw,size=16777216','/run/pi-caddy':'rw,exec,size=134217728,mode=0700,uid=10001,gid=10001','/data':'rw,size=134217728,uid=10001,gid=10001','/config':'rw,size=16777216,uid=10001,gid=10001'},memory=268435456)
        path=self.folder/'caddy.json';durable_file(path,encoded(config));archive=self.folder/'frontend.tar';fd=os.open(archive,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as output,tarfile.open(fileobj=output,mode='w') as stream:
            entries=[(str(v.relative_to(source)),v) for v in sorted(source.rglob('*')) if v.is_file()]+[('tmp/service.json',path),('tmp/service-ready',None)]
            for name,file in entries:
                require((name.startswith('data/') or name.startswith('tmp/')) and '..' not in Path(name).parts and (file is None or not file.is_symlink()),'safe restored frontend material required');info=tarfile.TarInfo(name);info.uid=info.gid=10001;info.mode=0o600;info.size=file.stat().st_size if file else 0
                if file:
                    with file.open('rb') as incoming:stream.addfile(info,incoming)
                else:stream.addfile(info)
        self.host._run(['exec','-i',row['id'],'tar','-xmo','-f','-','-C','/'],stdin_path=archive,seconds=90);self._owned(row)

    def verify(self):
        connections=[]
        for row in self.rows:
            if not row['member'].startswith('worker'):continue
            self._owned(row);response=self.host._run(['exec',row['id'],'python','-B','-c',WORKER_CHECK],seconds=60);proof=strict_json(self.host._bytes(response))
            require(proof==dict(verified=True,main_process=True,application_role='myink_app',read_only=True,redis_authenticated=True,rabbit_authenticated=True,empty_queues=5,wrong_database_password_rejected=True,model_requests=0),'actual worker connections unconfirmed');connections.append(proof)
            durable_file(self.folder/(row['member']+'-connections.json'),encoded(proof))
        require(len(connections)==2,'two actual worker connection proofs required')
        site=self.api.values.get('SITE_ADDRESS','http://localhost');require(isinstance(site,str) and not any(ord(c)<32 for c in site),'fixed restored site required')
        result=self._check(VERIFY,self._packet('verify',dict(environment=self.api.values,redis=self.redis,workers=self.workers,site=site,https=self.https,certificate_pins=self.pins)),180)
        require(result.get('verified') is True and result.get('ready') is True and result.get('caddy_ready') is True and result.get('worker_heartbeats')==2 and type(result.get('retained_redis_keys')) is int and result.get('tls_pinned') is self.https and result.get('model_requests')==0,'actual restored cohort readiness unconfirmed')
        for row in self.rows:require(self._owned(row)['State']['Running'],'restored cohort member exited')
        exits=[]
        for row in self.rows:
            if not row['member'].startswith('worker'):continue
            self.host._run(['stop','--signal','SIGTERM','--timeout','-1',row['id']],seconds=30)
            state=self._owned(row)['State'];require(not state['Running'] and state['ExitCode']==0 and state['OOMKilled'] is False,'restored worker did not exit naturally');exits.append(0)
        require(exits==[0,0],'two natural worker exits required')
        proof=dict(result,authentication=self.authentication,worker_connections=connections,worker_exit_codes=exits,scope='restored_services_authentication_and_readiness');durable_file(self.folder/'receipt.json',encoded(proof));return proof

    def cleanup(self):
        for row in reversed(self.rows):
            self._owned(row)
            try:
                logs=self.host.commands.run(['logs','--tail','100',row['id']],timeout=15,output_limit=65536);durable_file(self.folder/(row['member']+'-diagnostic.json'),encoded(logs))
            finally:
                self._owned(row);self.host.commands.run(['rm','--force',row['id']],timeout=30)
        result=self.host.commands.run(['ps','--all','--quiet','--no-trunc','--filter','label='+LABEL+'='+self.plan['operation_id'],'--filter','label=myink.pi.restored-service.cohort='+self.probe.role],timeout=15);require(not self.host._bytes(result).strip(),'restored service cleanup unconfirmed')
