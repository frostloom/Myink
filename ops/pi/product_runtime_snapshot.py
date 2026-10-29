"""Private effective deployment material and fixed local recovery credentials."""
from copy import deepcopy
import re
from urllib.parse import urlsplit,unquote,quote
from .audit import digest,encoded,require,hash_value
from .product_activation import context_from_inspects,verify_cohort_container,environment


def local_url(value,role):
    require(isinstance(value,str) and len(value)<=16384,'bounded runtime database URL required')
    p=urlsplit(value);password=unquote(p.password or '')
    require(p.scheme in ('postgresql','postgresql+psycopg') and p.username==role and password and not any(ord(c)<32 for c in password) and p.hostname in ('myink-pg','127.0.0.1','localhost') and p.port in (None,5432) and p.path=='/myink' and not p.query and not p.fragment,'fixed authenticated database role and endpoint required')
    return 'postgresql+psycopg://'+role+':'+quote(password,safe='')+'@127.0.0.1:5432/myink'


def capture(plan,config,context,phase,rows,network,volumes,*,bindings=None):
    require(phase in ('PRE','POST') and isinstance(rows,list) and len(rows)==3,'complete phase runtime material required')
    basis=context_from_inspects(plan,config,rows if phase=='PRE' else context['templates'],network,volumes)
    require(basis==context and context['plan_sha256']==digest(plan) and context['configuration_sha256']==plan['candidate']['config_hash'],'approved effective runtime drift')
    if phase=='POST':
        require(isinstance(bindings,dict) and set(bindings)=={v['Id'] for v in context['templates']} and len(set(bindings.values()))==3 and all(hash_value(v) for v in bindings.values()),'durable post template binding required')
        by_id={v['Id']:v for v in rows};require(set(by_id)==set(bindings.values()),'post runtime census differs')
        for t in context['templates']:verify_cohort_container(by_id[bindings[t['Id']]],plan,config,context,t,plan['candidate'],'candidate')
    output=[]
    for v in sorted(rows,key=lambda v:v['Id']):
        service=v['Config']['Labels']['com.docker.compose.service'];require(service in ('myink-api','myink-worker'),'fixed runtime service required')
        output.append(dict(id=v['Id'],service='api' if service=='myink-api' else 'worker',image_id=v['Image'],config=deepcopy(v['Config']),host_config=deepcopy(v['HostConfig']),mounts=deepcopy(v['Mounts']),networks=deepcopy(v['NetworkSettings']['Networks'])))
    snapshot=dict(schema='pi-effective-runtime-v1',phase=phase,plan_sha256=digest(plan),context_sha256=digest(context),network=context['network'],volumes=context['volumes'],containers=output)
    require(len(encoded(snapshot))<=1048576,'bounded private runtime snapshot required');connection_settings(snapshot)
    return snapshot


def connection_settings(snapshot):
    require(isinstance(snapshot,dict) and set(snapshot)=={'schema','phase','plan_sha256','context_sha256','network','volumes','containers'} and snapshot['schema']=='pi-effective-runtime-v1' and snapshot['phase'] in ('PRE','POST') and hash_value(snapshot['plan_sha256']) and hash_value(snapshot['context_sha256']),'fixed private runtime snapshot required')
    rows=snapshot['containers'];require(isinstance(rows,list) and len(rows)==3 and sorted(v['service'] for v in rows)==['api','worker','worker'] and len({v['id'] for v in rows})==3,'complete runtime roles required')
    apps=[];report=None
    for row in rows:
        e=environment(row['config']['Env']);apps.append(local_url(e.get('DATABASE_URL'),'myink_app'))
        if row['service']=='api':report=local_url(e.get('ADMIN_DATABASE_URL'),'myink_report')
    require(len(set(apps))==1 and report is not None,'runtime database credential disagreement')
    return dict(app=apps[0],report=report)


def authentication(snapshot,plan_sha256,phase,admin,password):
    settings=connection_settings(snapshot)
    require(snapshot['plan_sha256']==plan_sha256 and snapshot['phase']==phase,'runtime material phase or plan differs')
    require(isinstance(admin,str) and re.fullmatch(r'pi_restore_[0-9a-f]{32}',admin) and isinstance(password,str) and re.fullmatch(r'[A-Za-z0-9_-]{32,128}',password),'ephemeral owned target administrator required')
    hba='local all all trust\n'+'host myink myink_app,myink_report,'+admin+' 127.0.0.1/32 scram-sha-256\n'+'host all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n'
    return dict(app_url=settings['app'],report_url=settings['report'],admin_url='postgresql://'+admin+':'+password+'@127.0.0.1:5432/myink',hba=hba)
