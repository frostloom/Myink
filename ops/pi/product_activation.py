"""Fixed native cohort lifecycle. Not registered as a model or HTTP tool."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

from .audit import digest,encoded,hash_value,name,require,strict_json,utc,_plain
from .contracts import Identity,Receipt
from .product_bootstrap import _plan
from .product_runtime import _pinned,_save,SERVICES

ACTIONS=('create_candidate','start_candidate','stop_candidate','create_rollback','start_rollback','stop_rollback')
LABEL='myink.pi.release.operation'


def environment(values):
    require(isinstance(values,list) and len(values)<=256,'bounded service environment required');result={}
    for item in values:
        require(isinstance(item,str) and 0<len(item)<=16384 and not any(c in item for c in '\x00\r\n'),'single-line service environment required')
        key,sep,value=item.partition('=')
        require(sep and key and all(c.isalnum() or c=='_' for c in key) and key not in result,'unique service environment required');result[key]=value
    require(len(encoded(result))<=131072,'bounded environment bytes required');return result


def _network_bound(value,network,alias):
    networks=value['NetworkSettings']['Networks']
    require(value['HostConfig']['NetworkMode']==network['id'] and set(networks)=={network['name']},'cohort network mode changed')
    endpoint=networks[network['name']];pending=value['State']['Status']=='created' and value['State']['Running'] is False
    # Docker allocates NetworkID when starting a created container. Its fixed
    # HostConfig network ID and resolved network name are already inspectable.
    require(endpoint['NetworkID']==network['id'] or pending and endpoint['NetworkID']=='','cohort network endpoint changed')
    require(alias in (endpoint.get('Aliases') or []),'cohort network alias changed')


def context_from_inspects(plan,config,rows,network,volumes):
    plan=_plan(plan);project=config['project'];target=config['target'];mode=config['mode'];op=plan['operation_id']
    require(mode==plan['mode'] and target in ('rehearsal','production') and project==('myink' if target=='production' else 'myink-pi-rehearsal-'+op),'fixed target namespace required')
    require(isinstance(network,dict) and hash_value(network.get('Id')) and network.get('Driver')=='bridge' and isinstance(network.get('Name'),str) and type(network.get('Internal')) is bool and isinstance(network.get('Labels'),(dict,type(None))),'fixed bridge identity required')
    labels=network.get('Labels') or {}
    if target=='rehearsal':require(network['Internal'] is True and labels.get('myink.pi.rehearsal')==op,'owned internal rehearsal network required')
    else:require(labels.get('com.docker.compose.project')==project,'original product network required')
    net=dict(id=network['Id'],name=network['Name'],driver='bridge',internal=network['Internal'],labels=labels)
    require(isinstance(volumes,list) and len(volumes)<=1,'single feedback volume required');owned={}
    for volume in volumes:
        require(isinstance(volume,dict) and volume.get('Driver')=='local' and name(volume.get('Name')) and isinstance(volume.get('Labels'),(dict,type(None))),'fixed named local volume required')
        labels=volume.get('Labels') or {}
        require(labels.get('myink.pi.rehearsal')==op if target=='rehearsal' else labels.get('com.docker.compose.project')==project,'feedback volume ownership mismatch')
        owned[volume['Name']]=dict(name=volume['Name'],driver='local',labels=labels)
    expected={r['id']:r for r in plan['legacy']['containers'] if r['service'] in ('api','worker')};templates=[];seen=set()
    require(isinstance(rows,list) and len(rows)==3,'complete original backend templates required')
    for v in rows:
        require(isinstance(v,dict) and v.get('Id') in expected and v['Id'] not in seen and v.get('Image')==expected[v['Id']]['image_id'],'original backend drift');seen.add(v['Id']);role=expected[v['Id']]['service'];c=v['Config'];h=v['HostConfig'];e=environment(c['Env'])
        require(c['User']=='10001' and c['Cmd']==['myink-api' if role=='api' else 'myink-worker'] and c.get('Entrypoint') in (None,[]) and c.get('WorkingDir')=='/app','fixed nonroot backend command required')
        require(c['Labels'].get('com.docker.compose.project')==project and c['Labels'].get('com.docker.compose.service')==('myink-api' if role=='api' else 'myink-worker'),'original service label drift')
        require(not h.get('Privileged') and h.get('PidMode','')=='' and h.get('IpcMode','private')=='private' and not any(h.get(k) for k in ('CapAdd','Devices','ExtraHosts','Links','VolumesFrom')),'unreviewed backend privileges')
        require(type(h['Memory']) is int and 0<h['Memory']<=1073741824 and type(h['NanoCpus']) is int and 0<h['NanoCpus']<=2000000000,'bounded backend resources required')
        require(urlsplit(e.get('DATABASE_URL','')).username=='myink_app','application database role must remain tenant limited')
        admin=e.get('ADMIN_DATABASE_URL','')
        require((role=='api' and urlsplit(admin).username=='myink_report') or (role=='worker' and (not admin or urlsplit(admin).username=='myink_report')),'backend cannot carry migration credentials')
        require(not any(k in e for k in ('PYTHONPATH','PYTHONHOME','LD_PRELOAD')),'unreviewed interpreter override')
        networks=v['NetworkSettings']['Networks'];require(isinstance(networks,dict) and len(networks)==1 and network['Name'] in networks and networks[network['Name']]['NetworkID']==network['Id'],'backend network drift')
        mounts=v['Mounts'];require(isinstance(mounts,list) and len(mounts)==(1 if role=='api' else 0),'fixed feedback mount only')
        normal=[]
        for m in mounts:
            require(m['Type']=='volume' and m.get('Name') in owned and m['Destination']=='/data/feedback' and m['RW'] is True,'host/socket or foreign mount rejected')
            normal.append(dict(Type='volume',Name=m['Name'],Destination='/data/feedback',RW=True))
        ports=h.get('PortBindings') or {};require(isinstance(ports,dict) and (not ports or role=='api' and set(ports)=={'8100/tcp'}),'fixed API binding only')
        for bindings in ports.values():
            require(isinstance(bindings,list) and len(bindings)<=2,'bounded original port binding required')
            for b in bindings:require(target=='production' and set(b)=={'HostIp','HostPort'} and b['HostIp'] in ('127.0.0.1','::1') and isinstance(b['HostPort'],str) and b['HostPort'].isdigit() and 0<int(b['HostPort'])<=65535,'rehearsal/public host ports rejected')
        restart=h.get('RestartPolicy',{}).get('Name','no');require(restart in ('no','unless-stopped'),'fixed restart policy required')
        templates.append(dict(Id=v['Id'],Name=v['Name'],Image=v['Image'],Config=dict(User='10001',Cmd=c['Cmd'],Entrypoint=None,WorkingDir='/app',Env=list(c['Env']),Labels=dict(c['Labels'])),HostConfig=dict(Privileged=False,PidMode='',IpcMode='private',CapAdd=None,Devices=[],ExtraHosts=None,Memory=h['Memory'],NanoCpus=h['NanoCpus'],PortBindings=ports,RestartPolicy={'Name':restart}),Mounts=normal,NetworkSettings=dict(Networks={network['Name']:dict(NetworkID=net['id'],Aliases=list(networks[network['Name']].get('Aliases') or []))})))
    templates.sort(key=lambda v:v['Id']);owned=sorted(owned.values(),key=lambda v:v['name'])
    configuration=digest(dict(network=net,volumes=owned,templates=templates))
    images={}
    for v in plan['legacy']['containers']:images['python' if v['service'] in ('api','worker') else v['service']]=v['image_id']
    rollback=asdict(Identity('rollback-'+op,plan['candidate']['generation']+1,'pi-rollback-'+op,images,commit_sha=plan['legacy']['source_commit'],schema_id=plan['candidate']['schema_id'],config_hash=configuration))
    return dict(schema='pi-product-activation-context-v1',mode=mode,target=target,project=project,plan_sha256=digest(plan),configuration_sha256=configuration,network=net,volumes=owned,templates=templates,rollback_identity=rollback)


class NativeActivation:
    def __init__(self,host,context_path,context_sha256,approval_path,approval_sha256):
        self.host=host;self.plan=_plan(host.plan);self.context_path=Path(context_path);self.context_pin=context_sha256;self.approval_path=Path(approval_path);self.approval_pin=approval_sha256
        actual=host.config['mode']=='ACTUAL'
        if actual:
            from .product_runtime import LinuxProductHost
            require(type(host) is LinuxProductHost,'canonical native activation host required')
        else:require(host.config['target']=='rehearsal','simulation may only mutate owned rehearsal resources')
        self.context=_pinned(context_path,context_sha256,actual);v=self.context
        require(isinstance(v,dict) and set(v)=={'schema','mode','target','project','plan_sha256','configuration_sha256','network','volumes','templates','rollback_identity'},'closed native activation context required')
        n=v['network'];network=dict(Id=n['id'],Name=n['name'],Driver=n['driver'],Internal=n['internal'],Labels=n['labels']);volumes=[dict(Name=x['name'],Driver=x['driver'],Labels=x['labels']) for x in v['volumes']]
        require(v==context_from_inspects(self.plan,host.config,v['templates'],network,volumes) and v['configuration_sha256']==self.plan['candidate']['config_hash'],'native configuration binding mismatch')
        self._authority()

    def _authority(self):
        h=self.host;h.authorize(self.plan);actual=h.config['mode']=='ACTUAL'
        require(_pinned(self.context_path,self.context_pin,actual)==self.context,'activation context drift')
        value=_pinned(self.approval_path,self.approval_pin,actual)
        require(isinstance(value,dict) and set(value)=={'schema','mode','target','plan_sha256','context_sha256','approved_actions','expires_at'} and value['schema']=='pi-product-activation-approval-v1' and value['mode']==h.config['mode'] and value['target']==h.config['target'] and value['plan_sha256']==digest(self.plan) and value['context_sha256']==self.context_pin,'independent exact activation approval required')
        require(isinstance(value['approved_actions'],list) and len(value['approved_actions'])==len(ACTIONS) and set(value['approved_actions'])==set(ACTIONS) and utc(h.clock())<min(utc(value['expires_at']),utc(self.plan['expires_at'])),'activation actions or expiry mismatch')

    def _run(self,args,**kwargs):
        self._authority();return self.host._run(args,**kwargs)

    def _json(self,args):return strict_json(self.host._bytes(self._run(args)))

    def identity(self,role):
        require(role in ('candidate','rollback'),'fixed cohort role required')
        return deepcopy(self.plan['candidate'] if role=='candidate' else self.context['rollback_identity'])

    def _control(self,role):
        v=self._json(['exec',self.host._cid('postgres'),'psql','-X','-q','-A','-t','-w','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c','BEGIN READ ONLY;SET LOCAL statement_timeout=3000;SELECT row_to_json(m) FROM maintenance_control m WHERE id=1;ROLLBACK;'])
        identity=self.identity(role);epoch=self.plan['operation_id'] if role=='candidate' else 'rollback-'+self.plan['operation_id']
        require(isinstance(v,dict) and type(v.get('generation')) is int and v.get('deployment_id')==identity['deployment_id'] and v['generation']==identity['generation'] and v.get('owner')==identity['owner'] and v.get('image_ids')==identity['image_ids'] and v.get('epoch')==epoch and v.get('admission_closed') is True and v.get('consumer_blocked') is True and utc(v['deadline'])==utc(self.plan['expires_at']),'closed current owner no longer held')
        return v

    def _parent(self,role):return ('candidate:' if role=='candidate' else 'rollback-cohort:')+self.plan['operation_id']

    def _cohort(self,role,*,required=True):
        row=self.host.ledger.get(self._parent(role))
        if row is None and not required:return []
        require(row and row['kind']==('product_candidate' if role=='candidate' else 'product_rollback_cohort') and row['status']=='done' and row['payload']==dict(plan_sha256=digest(self.plan)),'cohort creation unfinished or unknown')
        path=self.host.root/('candidate-cohort.json' if role=='candidate' else 'rollback-cohort.json')
        _plain(path);require(path.is_file() and path.stat().st_size<=65536,'bounded durable cohort registry required');v=strict_json(path.read_bytes())
        require(set(v)=={'schema','plan_sha256','containers'} and v['schema']==('pi-product-candidate-cohort-v1' if role=='candidate' else 'pi-product-rollback-cohort-v1') and v['plan_sha256']==digest(self.plan) and row['evidence'].get('cohort_sha256')==digest(v),'cohort registry mismatch')
        require(len(v['containers'])==3 and Counter(x['service'] for x in v['containers'])==Counter(api=1,worker=2),'complete role cohort required')
        templates={x['Id']:x for x in self.context['templates']};seen=set()
        for container in v['containers']:
            require(set(container)=={'id','service','image_id'} and hash_value(container['id']) and container['id'] not in seen and container['image_id']==self.identity(role)['image_ids']['python'],'typed exact cohort required');seen.add(container['id'])
            matches=[]
            for old in templates:
                child=self.host.ledger.get(self._parent(role)+':'+old)
                if child and child['status']=='done' and child['kind']=='product_cohort_container' and child['evidence'].get('id')==container['id']:matches.append(child)
            require(len(matches)==1 and matches[0]['payload']==dict(plan_sha256=digest(self.plan),context_sha256=self.context_pin,role=role,source_id=matches[0]['payload']['source_id']) and matches[0]['payload']['source_id'] in templates,'original template binding missing')
        return v['containers']

    def _environment(self,template,role):
        values=environment(template['Config']['Env']);identity=self.identity(role)
        values.update(DEPLOYMENT_ID=identity['deployment_id'],DEPLOYMENT_GENERATION=str(identity['generation']),DEPLOYMENT_OWNER=identity['owner'],DEPLOYMENT_IMAGE_IDS=encoded(identity['image_ids']).decode(),DEPLOYMENT_COMMIT_SHA=identity['commit_sha'],OBSERVATION_CONFIG_ID=identity['config_hash'],OBSERVATION_SCHEMA_ID=identity['schema_id'],PYTHONDONTWRITEBYTECODE='1',HOME='/tmp')
        return values

    def _template(self,role,cid):
        for template in self.context['templates']:
            row=self.host.ledger.get(self._parent(role)+':'+template['Id'])
            if row and row['status']=='done' and row['evidence'].get('id')==cid:return template
        raise ValueError('container has no original template binding')

    def _new(self,value,role,template):
        c=value['Config'];h=value['HostConfig'];n=self.context['network'];labels=c['Labels'];expected_role=SERVICES[template['Config']['Labels']['com.docker.compose.service']]
        require(value['Image']==self.identity(role)['image_ids']['python'] and value['Id'] not in {r['id'] for r in self.plan['legacy']['containers']},'foreign cohort image or ID')
        require(labels.get(LABEL)==self.plan['operation_id'] and labels.get('myink.pi.release.role')==role and labels.get('com.docker.compose.project')==self.host.config['project'] and labels.get('com.docker.compose.service')==('myink-api' if expected_role=='api' else 'myink-worker'),'cohort labels superseded')
        require(c['User']=='10001' and c['WorkingDir']=='/app' and c['Cmd']==template['Config']['Cmd'] and c.get('Entrypoint') in (None,[]) and environment(c['Env'])==self._environment(template,role),'cohort command or effective configuration changed')
        require(h['ReadonlyRootfs'] is True and not h['Privileged'] and h.get('PidMode','')=='' and h.get('IpcMode','private')=='private' and not any(h.get(k) for k in ('CapAdd','Devices','ExtraHosts','Links','VolumesFrom')) and h['CapDrop']==['ALL'] and 'no-new-privileges' in h['SecurityOpt'],'cohort privilege boundary changed')
        require(h['Memory']==template['HostConfig']['Memory'] and h['MemorySwap']==h['Memory'] and h['NanoCpus']==template['HostConfig']['NanoCpus'] and h['PidsLimit']==128 and set(h.get('Tmpfs') or {})=={'/tmp'} and (h.get('PortBindings') or {})==template['HostConfig']['PortBindings'],'cohort resource boundary changed')
        require(h['RestartPolicy']['Name']==template['HostConfig']['RestartPolicy']['Name'],'restart policy changed')
        _network_bound(value,n,'myink-api' if expected_role=='api' else 'myink-worker')
        mounts=[dict(Type=m['Type'],Name=m.get('Name'),Destination=m['Destination'],RW=m['RW']) for m in value['Mounts'] if m['Type']!='tmpfs']
        require(mounts==template['Mounts'] and value['State']['OOMKilled'] is False,'cohort mounts or OOM failure')
        return value

    def _scope(self,creating=None):
        self._authority();h=self.host;n=self.context['network']
        info=self._json(['info','--format','{{json .}}']);require(info.get('ID')==h.config['daemon_id'],'Docker daemon changed')
        ids=h._bytes(self._run(['ps','--all','--no-trunc','--filter','label=com.docker.compose.project='+h.config['project'],'--format','{{.ID}}'])).decode().splitlines()
        require(len(ids)<=24 and len(ids)==len(set(ids)) and all(hash_value(v) for v in ids),'bounded complete cohort census required')
        rows=self._json(['inspect',*ids]);require(isinstance(rows,list) and len(rows)==len(ids) and {v['Id'] for v in rows}==set(ids),'incomplete native cohort inspect');by_id={v['Id']:v for v in rows}
        base={r['id']:r for r in self.plan['legacy']['containers']};expected=set(base);known={}
        for role in ('candidate','rollback'):
            if creating is not None and role==creating[0]:cohort=creating[1]
            else:cohort=self._cohort(role,required=False)
            for row in cohort:
                require(row['id'] not in expected,'cohort identity collision');expected.add(row['id']);known[row['id']]=role
        extras=[v for v in rows if v['Id'] not in expected]
        require(len(extras)<=1 and all(v['Config']['Labels'].get('com.docker.compose.service')=='myink-migrate' and not v['State']['Running'] and v['State']['ExitCode']==0 for v in extras),'manual or unknown cohort supersedes operation')
        require(expected.issubset(by_id),'frozen cohort missing')
        for cid,old in base.items():
            v=by_id[cid];require(v['Image']==old['image_id'] and v['Config']['Labels'].get('com.docker.compose.project')==h.config['project'] and SERVICES.get(v['Config']['Labels'].get('com.docker.compose.service'))==old['service'] and v['State']['OOMKilled'] is False,'original cohort changed')
            if old['service'] in ('api','worker'):require(not v['State']['Running'] and v['State']['ExitCode']==0,'old process is no longer drained')
            else:require(v['State']['Running'],'infrastructure stopped')
        net=self._json(['network','inspect',n['id']]);volumes=self._json(['volume','inspect',*[x['name'] for x in self.context['volumes']]]) if self.context['volumes'] else []
        require(isinstance(net,list) and len(net)==1,'exact network inspect required')
        actual=context_from_inspects(self.plan,h.config,[by_id[t['Id']] for t in self.context['templates']],net[0],volumes)
        require(actual==self.context,'original templates or resource ownership changed')
        for cid,role in known.items():self._new(by_id[cid],role,self._template(role,cid))
        return by_id

    def _claim(self,action):
        require(action in ACTIONS,'fixed action required');self._authority();h=self.host
        root=h.root/'native-actions';root.mkdir(mode=0o700,exist_ok=True);folder=root/action
        try:folder.mkdir(mode=0o700)
        except FileExistsError:raise ValueError('native action already claimed; no redispatch') from None
        operation='native:'+self.plan['operation_id']+':'+action;payload=dict(plan_sha256=digest(self.plan),context_sha256=self.context_pin,action=action)
        require(h.ledger.get(operation) is None,'original action intent exists');h.ledger.intent(operation,'product_native_action',payload);_save(folder/'intent.json',payload)
        return operation,folder

    def create(self,role):
        require(role in ('candidate','rollback'),'fixed cohort required');action='create_'+role;operation,folder=self._claim(action);h=self.host;parent=self._parent(role)
        try:
            self._control('candidate');self._scope()
            prepared=h.ledger.get(self.plan['operation_id']);require(prepared and prepared['kind']=='product_bootstrap' and prepared['status']=='done' and prepared['payload']==dict(plan_sha256=digest(self.plan)),'prepared original bootstrap required')
            if role=='rollback':
                rows=self._scope();require(all(not rows[v['id']]['State']['Running'] and rows[v['id']]['State']['ExitCode']==0 for v in self._cohort('candidate')),'candidate must be stopped before rollback cohort creation')
            require(h.ledger.get(parent) is None,'cohort already exists');h.ledger.intent(parent,'product_candidate' if role=='candidate' else 'product_rollback_cohort',dict(plan_sha256=digest(self.plan)));cohort=[]
            for index,template in enumerate(self.context['templates']):
                self._control('candidate');self._scope((role,cohort));source=template['Id'];child=parent+':'+source;payload=dict(plan_sha256=digest(self.plan),context_sha256=self.context_pin,role=role,source_id=source);require(h.ledger.get(child) is None,'container intent already exists');h.ledger.intent(child,'product_cohort_container',payload)
                values=self._environment(template,role);envfile=folder/('environment-'+str(index));fd=os.open(envfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb') as stream:stream.write(''.join(k+'='+v+'\n' for k,v in values.items()).encode());stream.flush();os.fsync(stream.fileno())
                service=SERVICES[template['Config']['Labels']['com.docker.compose.service']];name_value='myink-pi-'+role+'-'+service+'-'+self.plan['operation_id']+'-'+str(index)
                a=['create','--pull','never','--name',name_value,'--label',LABEL+'='+self.plan['operation_id'],'--label','myink.pi.release.role='+role,'--label','com.docker.compose.project='+h.config['project'],'--label','com.docker.compose.service='+('myink-api' if service=='api' else 'myink-worker'),'--network',self.context['network']['id'],'--network-alias','myink-api' if service=='api' else 'myink-worker','--read-only','--tmpfs','/tmp:rw,size=268435456,uid=10001,gid=10001','--memory',str(template['HostConfig']['Memory']),'--memory-swap',str(template['HostConfig']['Memory']),'--cpus',str(template['HostConfig']['NanoCpus']/1000000000),'--pids-limit','128','--cap-drop','ALL','--security-opt','no-new-privileges','--user','10001','--workdir','/app','--restart',template['HostConfig']['RestartPolicy']['Name'],'--env-file',str(envfile)]
                if h.config['target']=='rehearsal':a+=['--label','myink.pi.rehearsal='+self.plan['operation_id']]
                for m in template['Mounts']:a+=['--mount','type=volume,source='+m['Name']+',target='+m['Destination']]
                for port,bindings in template['HostConfig']['PortBindings'].items():
                    for binding in bindings:a+=['--publish',binding['HostIp']+':'+binding['HostPort']+':'+port]
                result=self._run([*a,self.identity(role)['image_ids']['python'],*template['Config']['Cmd']]);cid=h._bytes(result).decode().strip();require(hash_value(cid),'actual native container ID required')
                raw=self._json(['inspect',cid]);require(isinstance(raw,list) and len(raw)==1 and raw[0]['Id']==cid,'actual created container inspect required');self._new(raw[0],role,template);require(not raw[0]['State']['Running'],'candidate ran before explicit start')
                h.ledger.finish(Receipt(child,'done',dict(id=cid)));cohort.append(dict(id=cid,service=service,image_id=self.identity(role)['image_ids']['python']))
            value=dict(schema='pi-product-candidate-cohort-v1' if role=='candidate' else 'pi-product-rollback-cohort-v1',plan_sha256=digest(self.plan),containers=cohort);_save(h.root/('candidate-cohort.json' if role=='candidate' else 'rollback-cohort.json'),value);h.ledger.finish(Receipt(parent,'done',dict(cohort_sha256=digest(value))));self._scope();_save(folder/'receipt.json',value);h.ledger.finish(Receipt(operation,'done',dict(verified=True,role=role,cohort_sha256=digest(value))));return cohort
        except Exception as error:
            h.ledger.finish(Receipt(operation,'uncertain',dict(reason='cohort_creation_unconfirmed',error_class=type(error).__name__)))
            # Original pending child/parent intents remain authoritative. Never
            # retry a create or remove a running cohort as generic cleanup.
            raise

    def _runtime(self,cid,role,service):
        manifest_key='candidate' if role=='candidate' else 'legacy';h=self.host
        m=_pinned(h.config[manifest_key+'_manifest_path'],h.config[manifest_key+'_manifest_sha256'],h.config['mode']=='ACTUAL');pin=digest({k:v for k,v in m['files'].items() if k.startswith('src/myink/') and k.endswith('.py')})
        script=r"""import hashlib,json,importlib.util,socket,sys
from pathlib import Path
import myink
package=Path(myink.__file__).parent
files={'src/myink/'+p.relative_to(package).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in package.rglob('*.py') if '__pycache__' not in p.parts and not p.is_symlink()}
pin=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
if pin!=sys.argv[1]:raise RuntimeError('actual imported source differs')
from myink.config import settings
provenance=None
if importlib.util.find_spec('myink.observability'):
 from myink.observability import run_provenance
 provenance=run_provenance(settings)
heartbeat=True;queues={}
if sys.argv[2]=='worker':
 from myink.worker.redis_client import get_redis
 r=get_redis();key='queue:heartbeat:'+socket.gethostname()+'-1';heartbeat=r.get(key)=='1' and r.ttl(key)>0
 from myink.worker.amqp import connect
 connection=connect()
 try:
  ch=connection.channel()
  for q in ('queue:tasks','queue:tasks:vip','queue:delay','queue:delay:vip','queue:dlq'):
   result=ch.queue_declare(queue=q,passive=True);queues[q]=result.method.message_count
 finally:connection.close()
print(json.dumps(dict(runtime_sha256=pin,provenance=provenance,heartbeat=bool(heartbeat),queues=queues)))
"""
        observed=self._json(['exec',cid,'python','-B','-c',script,pin,service]);identity=self.identity(role)
        require(isinstance(observed,dict) and set(observed)=={'runtime_sha256','provenance','heartbeat','queues'} and observed['runtime_sha256']==pin and observed['heartbeat'] is True,'source or worker-specific heartbeat unconfirmed')
        provenance=observed['provenance']
        if provenance is not None:
            require(all(provenance.get(k)==identity[k] for k in ('deployment_id','generation','owner','image_ids','commit_sha')) and provenance.get('config_id')==identity['config_hash'],'actual process provenance differs')
        else:require(role=='rollback','new candidate must emit provenance')
        if service=='worker':require(set(observed['queues'])=={'queue:tasks','queue:tasks:vip','queue:delay','queue:delay:vip','queue:dlq'} and all(type(n) is int and n==0 for n in observed['queues'].values()),'worker broker access or empty queue census unconfirmed')
        return dict(observed,identity=identity)

    def _ready(self,role):
        h=self.host;cohort=self._cohort(role);results=[];until=time.monotonic()+120
        while True:
            self._control(role);rows=self._scope();require(all(rows[v['id']]['State']['Running'] for v in cohort),'cohort failed after start')
            try:
                results=[self._runtime(v['id'],role,v['service']) for v in cohort]
                cid=next(v['id'] for v in cohort if v['service']=='api')
                script="import json,urllib.request;print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8100/readyz',timeout=3))))"
                response=self._json(['exec',cid,'python','-B','-c',script]);require(response==dict(status='ok',checks={'redis':'ok','db':'ok','worker':'ok'}),'actual API database/Redis/worker readiness failed')
                upstream=self._json(['exec',h._cid('frontend'),'/usr/bin/curl','-fsS','--max-time','3','http://myink-api:8100/readyz']);require(upstream==response,'frontend cannot reach the current API');break
            except Exception:
                require(time.monotonic()<until,'native readiness deadline');time.sleep(.5)
        self._control(role);self._scope();return dict(verified=True,role=role,backends=results,api_ready=True,scope='isolated_closed_cohort_only')

    def start(self,role):
        operation,folder=self._claim('start_'+role);h=self.host
        try:
            self._control(role);self._scope();cohort=self._cohort(role)
            for v in cohort:
                self._control(role);rows=self._scope();require(not rows[v['id']]['State']['Running'] and rows[v['id']]['State']['ExitCode']==0,'cohort process already active or failed')
                self._run(['start',v['id']])
            result=self._ready(role);_save(folder/'receipt.json',result);h.ledger.finish(Receipt(operation,'done',result));return result
        except Exception as error:h.ledger.finish(Receipt(operation,'uncertain',dict(reason='cohort_start_unconfirmed',error_class=type(error).__name__)));raise

    def stop(self,role):
        operation,folder=self._claim('stop_'+role);h=self.host
        try:
            self._control(role);rows=self._scope();cohort=self._cohort(role)
            for v in sorted(cohort,key=lambda v:v['service']!='api'):
                self._control(role);self._scope();self._run(['stop','--signal','SIGTERM','--timeout','-1',v['id']],seconds=h.config['drain_seconds'])
                actual=self._scope()[v['id']];require(not actual['State']['Running'] and actual['State']['ExitCode']==0 and actual['State']['OOMKilled'] is False,'cohort process did not exit naturally')
            result=dict(verified=True,role=role,identity=self.identity(role),natural_exits=[0,0,0],scope='stopped_processes_only');_save(folder/'receipt.json',result);h.ledger.finish(Receipt(operation,'done',result));return result
        except Exception as error:h.ledger.finish(Receipt(operation,'uncertain',dict(reason='cohort_stop_unconfirmed',error_class=type(error).__name__)));raise
