"""Infrastructure snapshots keep credentials private and ingress confined."""
from copy import deepcopy
import importlib.util
import pytest
from ops.pi.audit import digest
from test_product_activation import activation_inputs,bootstrap_case,context
from test_product_runtime_snapshot import sample


def api():
    assert importlib.util.find_spec('ops.pi.product_service_snapshot'),'missing complete service recovery material'
    from ops.pi import product_service_snapshot
    return product_service_snapshot


def packet(inputs):
    from ops.pi.product_runtime_snapshot import capture
    plan,c,ctx,n,v,backends=sample(inputs);runtime=capture(plan,c,ctx,'PRE',backends,n,[v])
    rows=[]
    for source in plan['legacy']['containers']:
        if source['service'] not in ('redis','rabbitmq','frontend'):continue
        env=['REDIS_PASSWORD=synthetic'] if source['service']=='redis' else ['RABBITMQ_DEFAULT_USER=myink','RABBITMQ_DEFAULT_PASS=synthetic'] if source['service']=='rabbitmq' else []
        rows.append(dict(Id=source['id'],Image=source['image_id'],Config=dict(Env=env,User='10001',Cmd=['fixed'],Labels={}),HostConfig=dict(Memory=268435456,NanoCpus=1000000000),Mounts=[]))
    ingress=dict(admin={'listen':'127.0.0.1:2019'},apps={'http':{'servers':{'main':{'listen':[':80'],'routes':[{'handle':[{'handler':'reverse_proxy','upstreams':[{'dial':'myink-api:8100'}]}]}]}}}})
    return plan,runtime,rows,ingress


def test_private_service_snapshot_binds_complete_original_images_and_auth(activation_inputs):
    plan,runtime,rows,ingress=packet(activation_inputs);value=api().capture(plan,runtime,rows,ingress)
    assert value['plan_sha256']==digest(plan) and value['runtime_sha256']==digest(runtime)
    assert sorted(value['services'])==['frontend','rabbitmq','redis']
    assert 'synthetic' in str(value)
    isolated=api().isolated_ingress(ingress,[])
    assert isolated['apps']['http']['servers']['main']['listen']==['127.0.0.1:8080']
    assert isolated['apps']['http']['servers']['main']['routes'][0]['handle'][0]['upstreams'][0]['dial']=='127.0.0.1:8100'
    assert ingress['apps']['http']['servers']['main']['listen']==[':80']


@pytest.mark.parametrize('fault',['missing','foreign-id','image','redis-password','rabbit-password','rabbit-user','external-upstream','external-log','tls-without-certificate'])
def test_incomplete_or_unapproved_service_material_is_rejected(activation_inputs,fault):
    plan,runtime,rows,ingress=packet(activation_inputs)
    if fault=='missing':rows.pop()
    elif fault=='foreign-id':rows[0]['Id']='f'*64
    elif fault=='image':rows[0]['Image']='sha256:'+'f'*64
    elif fault in ('redis-password','rabbit-password','rabbit-user'):
        role='redis' if fault=='redis-password' else 'rabbitmq';row=next(v for v in rows if next(s for s in plan['legacy']['containers'] if s['id']==v['Id'])['service']==role)
        key='REDIS_PASSWORD' if role=='redis' else 'RABBITMQ_DEFAULT_USER' if fault=='rabbit-user' else 'RABBITMQ_DEFAULT_PASS';row['Config']['Env']=[v for v in row['Config']['Env'] if not v.startswith(key+'=')]+[key+'=wrong']
    elif fault=='external-upstream':ingress['apps']['http']['servers']['main']['routes'][0]['handle'][0]['upstreams'][0]['dial']='external.invalid:8100'
    elif fault=='external-log':ingress['logging']={'logs':{'default':{'writer':{'output':'net','address':'external.invalid:443'}}}}
    elif fault=='tls-without-certificate':ingress['apps']['http']['servers']['main'].update(listen=[':443'],tls_connection_policies=[{}])
    if fault.startswith('external') or fault=='tls-without-certificate':
        with pytest.raises(ValueError):api().isolated_ingress(ingress,[])
    else:
        with pytest.raises(ValueError):api().capture(plan,runtime,rows,ingress)


def test_redis_snapshot_comparison_allows_only_natural_expiry():
    before={'observed_at_ms':1000,'keys':[{'key_hex':'61','dump_hex':'abcd','expires_at_ms':1500},{'key_hex':'62','dump_hex':'ef','expires_at_ms':None}]}
    api().same_redis(before,{'observed_at_ms':2000,'keys':[before['keys'][1]]})
    for after in ({'observed_at_ms':1100,'keys':[before['keys'][1]]},{'observed_at_ms':2000,'keys':[]},{'observed_at_ms':2000,'keys':[dict(before['keys'][1],dump_hex='00')]}):
        with pytest.raises(ValueError):api().same_redis(before,after)


def test_isolated_https_loads_only_restored_material_and_keeps_routes(activation_inputs):
    _,_,_,ingress=packet(activation_inputs)
    server=ingress['apps']['http']['servers']['main'];server['listen']=[':443']
    ingress['apps']['tls']={'automation':{'policies':[{'issuers':[{'module':'acme'}]}]}}
    certs=[{'certificate':'/data/caddy/certificates/site.crt','key':'/data/caddy/certificates/site.key'}]
    value=api().isolated_ingress(ingress,certs)
    assert value['apps']['tls']=={'certificates':{'load_files':certs}}
    assert value['apps']['http']['servers']['main']['tls_connection_policies']==[{}]
    assert value['apps']['http']['servers']['main']['automatic_https']=={'disable':True}


def test_restored_service_endpoint_uses_only_owned_private_subnet():
    from ops.pi.product_restored_services import _endpoint
    assert _endpoint('redis://:private@127.0.0.1:6379/0','172.29.0.2','172.29.0.0/16')=='redis://:private@172.29.0.2:6379/0'
    for host in ('8.8.8.8','172.28.0.2','127.0.0.1'):
        with pytest.raises(ValueError):_endpoint('redis://:private@127.0.0.1:6379/0',host,'172.29.0.0/16')


@pytest.mark.parametrize('ports,valid',[({},True),({'5432/tcp':None},True),({'6379/tcp':[]},True),({'5432/tcp':[{'HostIp':'0.0.0.0','HostPort':'5432'}]},False)])
def test_exposed_service_ports_are_not_host_publications(ports,valid):
    assert api().unpublished(ports) is valid
