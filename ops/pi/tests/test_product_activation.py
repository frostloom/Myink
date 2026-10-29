"""Fixed cohort factory validates approved resources before native effects."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import importlib.util,json,uuid
import pytest
from ops.pi.audit import digest
from ops.pi.contracts import Identity
from test_product_bootstrap import case as bootstrap_case,NOW
from test_product_runtime import write


def api():
    assert importlib.util.find_spec('ops.pi.product_activation'),'missing fixed native cohort factory'
    from ops.pi import product_activation
    return product_activation


@pytest.fixture
def activation_inputs(bootstrap_case,tmp_path):
    ledger,plan,_=bootstrap_case;project='myink-pi-rehearsal-'+plan['operation_id'];network_id='f'*64
    config=dict(mode='SIMULATED',target='rehearsal',project=project,drain_seconds=10)
    network=dict(Id=network_id,Name=project+'-fixtures',Driver='bridge',Internal=True,Labels={'myink.pi.rehearsal':plan['operation_id']})
    volume=dict(Name=project+'-feedback',Driver='local',Labels={'myink.pi.rehearsal':plan['operation_id']})
    rows=[]
    for index,row in enumerate(plan['legacy']['containers']):
        if row['service'] not in ('api','worker'):continue
        service='myink-api' if row['service']=='api' else 'myink-worker'
        env=['PATH=/usr/local/bin:/usr/bin:/bin','HOME=/home/myink','EMBED_ENABLED=0','DATABASE_URL=postgresql+psycopg://myink_app:synthetic@myink-pg/myink','MODEL_CREDENTIAL_KEY=synthetic-private-value','REDIS_URL=redis://:synthetic@myink-redis/0','AMQP_URL=amqp://myink:synthetic@myink-rabbitmq/']
        if row['service']=='api':env+=['ADMIN_DATABASE_URL=postgresql+psycopg://myink_report:synthetic@myink-pg/myink']
        rows.append(dict(Id=row['id'],Name='/'+project+'-'+str(index),Image=row['image_id'],Config=dict(User='10001',Cmd=['myink-api' if row['service']=='api' else 'myink-worker'],Entrypoint=None,WorkingDir='/app',Env=env,Labels={'com.docker.compose.project':project,'com.docker.compose.service':service}),HostConfig=dict(Privileged=False,PidMode='',IpcMode='private',CapAdd=None,Devices=[],ExtraHosts=None,Memory=536870912,NanoCpus=1000000000,PortBindings={},RestartPolicy={'Name':'unless-stopped'}),Mounts=[dict(Type='volume',Name=volume['Name'],Destination='/data/feedback',RW=True)] if row['service']=='api' else [],NetworkSettings=dict(Networks={network['Name']:dict(NetworkID=network_id,Aliases=[service])})))
    return ledger,plan,config,network,volume,rows


def context(inputs):
    _,plan,c,n,v,rows=inputs
    return api().context_from_inspects(plan,c,rows,n,[v])


def test_context_retains_private_credentials_and_fixed_resource_binding(activation_inputs):
    value=context(activation_inputs)
    assert len(value['templates'])==3 and value['network']['id']=='f'*64
    assert value['configuration_sha256'] and value['rollback_identity']['generation']==activation_inputs[1]['candidate']['generation']+1
    assert value['rollback_identity']['image_ids']['python']==activation_inputs[1]['legacy']['containers'][0]['image_id']
    assert 'synthetic-private-value' in json.dumps(value)


@pytest.mark.parametrize('fault',['public-network','wrong-owner-network','bind','socket','superuser','worker-admin','command','root-user','host-pid','privileged','extra-network','public-port','volume-owner'])
def test_context_rejects_unapproved_rehearsal_resources(activation_inputs,fault):
    _,_,c,n,v,rows=activation_inputs;r=rows[0]
    if fault=='public-network':n['Internal']=False
    elif fault=='wrong-owner-network':n['Labels']['myink.pi.rehearsal']='other'
    elif fault=='bind':r['Mounts']=[dict(Type='bind',Source='/tmp',Destination='/data/feedback',RW=True)]
    elif fault=='socket':r['Mounts']=[dict(Type='bind',Source='/var/run/docker.sock',Destination='/var/run/docker.sock',RW=True)]
    elif fault=='superuser':r['Config']['Env']=[x.replace('myink_app:','myink:') for x in r['Config']['Env']]
    elif fault=='worker-admin':rows[1]['Config']['Env'].append('ADMIN_DATABASE_URL=postgresql+psycopg://myink:synthetic@myink-pg/myink')
    elif fault=='command':r['Config']['Cmd']=['sh','-c','arbitrary']
    elif fault=='root-user':r['Config']['User']='0'
    elif fault=='host-pid':r['HostConfig']['PidMode']='host'
    elif fault=='privileged':r['HostConfig']['Privileged']=True
    elif fault=='extra-network':r['NetworkSettings']['Networks']['other']=dict(NetworkID='e'*64,Aliases=[])
    elif fault=='public-port':r['HostConfig']['PortBindings']={'8100/tcp':[dict(HostIp='0.0.0.0',HostPort='8100')]}
    elif fault=='volume-owner':v['Labels']['myink.pi.rehearsal']='other'
    with pytest.raises(ValueError):context(activation_inputs)


def test_config_and_independent_approval_are_both_required_before_commands(activation_inputs,tmp_path):
    ledger,plan,c,*_=activation_inputs;value=context(activation_inputs)
    plan['candidate']['config_hash']=value['configuration_sha256'];value['plan_sha256']=digest(plan)
    cp=tmp_path/'activation.json';pin=write(cp,value)
    ap=tmp_path/'activation-approval.json';approval=dict(schema='pi-product-activation-approval-v2',mode='SIMULATED',target='rehearsal',plan_sha256=digest(plan),context_sha256=pin,approved_actions=list(api().ACTIONS),expires_at=plan['expires_at']);ap_pin=write(ap,approval)
    root=tmp_path/'operation';root.mkdir(mode=0o700)
    host=SimpleNamespace(plan=plan,config=c,root=root,ledger=ledger,clock=lambda:NOW,authorize=lambda p:None)
    actor=api().NativeActivation(host,cp,pin,ap,ap_pin)
    assert actor.context['plan_sha256']==digest(plan)
    approval['context_sha256']='0'*64;ap_pin=write(ap,approval)
    with pytest.raises(ValueError):api().NativeActivation(host,cp,pin,ap,ap_pin)


def test_native_action_timeout_intent_is_never_redispatched(activation_inputs,tmp_path):
    from ops.pi.product_commands import DockerCommands,DockerCommandError
    import sys
    ledger,plan,c,*_=activation_inputs;value=context(activation_inputs)
    plan['candidate']['config_hash']=value['configuration_sha256'];value['plan_sha256']=digest(plan)
    cp=tmp_path/'context.json';pin=write(cp,value);ap=tmp_path/'approval.json';ap_pin=write(ap,dict(schema='pi-product-activation-approval-v2',mode='SIMULATED',target='rehearsal',plan_sha256=digest(plan),context_sha256=pin,approved_actions=list(api().ACTIONS),expires_at=plan['expires_at']))
    root=tmp_path/'native';root.mkdir(mode=0o700);commands=root/'commands';commands.mkdir(mode=0o700);marker=tmp_path/'dispatches'
    executable=tmp_path/'docker';executable.write_text('#!'+sys.executable+'\nfrom pathlib import Path\nimport time\np=Path('+repr(str(marker))+')\np.write_text(p.read_text()+"x" if p.exists() else "x")\ntime.sleep(10)\n');executable.chmod(0o700)
    transport=DockerCommands(executable,'unix:///tmp/owned-test.sock',commands)
    host=SimpleNamespace(plan=plan,config=c,root=root,ledger=ledger,clock=lambda:NOW,authorize=lambda p:None,_cid=lambda role:'5'*64)
    host._run=lambda args,**kw:transport.run(args,timeout=2)
    host._bytes=lambda result:(commands/result['command_id']/'stdout.bin').read_bytes()
    actor=api().NativeActivation(host,cp,pin,ap,ap_pin)
    with pytest.raises(DockerCommandError):actor.create('candidate')
    row=ledger.get('native:'+plan['operation_id']+':create_candidate');assert row['status']=='uncertain'
    with pytest.raises(ValueError):actor.create('candidate')
    assert marker.read_text()=='x'
    assert ledger.get('candidate:'+plan['operation_id']) is None


def test_created_network_is_bound_before_docker_assigns_endpoint_id():
    from ops.pi.product_activation import _network_bound
    net=dict(id='f'*64,name='owned');value=dict(HostConfig=dict(NetworkMode=net['id']),State=dict(Status='created',Running=False),NetworkSettings=dict(Networks={'owned':dict(NetworkID='',Aliases=['myink-api'])}))
    _network_bound(value,net,'myink-api')
    value['State'].update(Status='running',Running=True);value['NetworkSettings']['Networks']['owned']['NetworkID']=net['id']
    _network_bound(value,net,'myink-api')


@pytest.mark.parametrize('fault',['running-empty','foreign-endpoint','foreign-mode','other-network','alias'])
def test_created_network_exception_cannot_admit_foreign_resources(fault):
    from ops.pi.product_activation import _network_bound
    net=dict(id='f'*64,name='owned');value=dict(HostConfig=dict(NetworkMode=net['id']),State=dict(Status='created',Running=False),NetworkSettings=dict(Networks={'owned':dict(NetworkID='',Aliases=['myink-api'])}))
    if fault=='running-empty':value['State'].update(Status='running',Running=True)
    if fault=='foreign-endpoint':value['NetworkSettings']['Networks']['owned']['NetworkID']='a'*64
    if fault=='foreign-mode':value['HostConfig']['NetworkMode']='other'
    if fault=='other-network':value['NetworkSettings']['Networks']['other']={}
    if fault=='alias':value['NetworkSettings']['Networks']['owned']['Aliases']=[]
    with pytest.raises(ValueError):_network_bound(value,net,'myink-api')
