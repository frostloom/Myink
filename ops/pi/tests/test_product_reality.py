"""Observed product reality is component-specific and never deployment authority."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import importlib,json
import pytest
from ops.pi.audit import encoded
from ops.pi.development_inputs import file_hash,read_json

NOW=datetime(2026,10,29,4,tzinfo=timezone.utc)
DAEMON='original-product-daemon'
SERVICES=['myink-api','myink-worker','myink-worker','myink-caddy','myink-pg','myink-redis','myink-rabbitmq','myink-migrate']

def api():return importlib.import_module('ops.pi.product_reality')

def write(path,value):path.write_bytes(encoded(value));path.chmod(0o600)


@pytest.fixture
def product(tmp_path):
    root=tmp_path/'observations';root.mkdir(mode=0o700);audit=tmp_path/'audit';audit.mkdir(mode=0o700)
    c=dict(schema='pi-product-observer-v1',mode='SIMULATED',docker='/usr/bin/docker',endpoint='unix:///isolated/product.sock',daemon_id=DAEMON,root=str(root),audit_path=str(audit/'events.sqlite'),export_root=str(audit/'export'),worker_replicas=2)
    cp=tmp_path/'product.json';write(cp,c);containers=[];images={}
    for n,service in enumerate(SERVICES,1):
        role=service.removeprefix('myink-');image='sha256:'+str(1 if role in ('api','worker') else n)*64
        containers.append(dict(id=f'{n:064x}',image_id=image,running=role!='migrate',status='exited' if role=='migrate' else 'running',healthy=None if role in ('worker','migrate') else 'healthy',project='myink',service=service))
        images[image]=dict(id=image,revision='a'*40 if role in ('api','worker') else 'b'*40)
    meta=dict(maintenance_control=False,maintenance_executions=False,maintenance_lock_function=False,task_provenance=False,agent_run_provenance=False)
    return cp,c,containers,images,meta


def runner(product,*,fault=None):
    cp,c,containers,images,meta=product;calls=[];inspects=0;ps_calls=0
    def execute(argv,seconds):
        nonlocal inspects,ps_calls
        assert argv[:3]==[c['docker'],'--host',c['endpoint']] and 0<seconds<=45;args=argv[3:];calls.append(args)
        if args[0]=='info':data=json.dumps(dict(ID='other' if fault=='daemon' else DAEMON))
        elif args[0]=='ps':
            ps_calls+=1
            assert args==['ps','--all','--no-trunc','--filter','label=com.docker.compose.project=myink','--format','{{.ID}}'];data='\n'.join(row['id'] for row in containers[::-1]) if fault=='reordered' and ps_calls==2 else '\n'.join(row['id'] for row in containers)
        elif args[0]=='inspect':
            inspects+=1;rows=deepcopy(containers)
            if fault=='drift' and inspects==2:rows[0]['image_id']='sha256:'+'f'*64
            assert args[1]=='--format' and set(args[3:])=={row['id'] for row in containers};assert 'Env' not in args[2] and 'Cmd' not in args[2];data='\n'.join(json.dumps(row) for row in rows)
        elif args[:2]==['image','inspect']:
            assert args[2]=='--format' and set(args[4:])==set(images);data='\n'.join(json.dumps(row) for row in images.values())
        elif args[0]=='exec':
            assert args[1]==containers[4]['id'] and args[2:11]==['psql','-X','-A','-t','-w','-U','myink','-d','myink'];query=args[-1];assert 'BEGIN READ ONLY;' in query and 'ROLLBACK;' in query and all(token not in query.upper() for token in ('UPDATE ','INSERT ','DELETE ','CREATE ','ALTER '))
            if fault=='metadata_error':return dict(returncode=1,stdout='',stderr='private failure password=hidden-value')
            data='BEGIN\nSET\n'+json.dumps(dict(meta,maintenance_control='true') if fault=='metadata_shape' else meta)+'\nROLLBACK\n'
        else:pytest.fail('arbitrary command route')
        return dict(returncode=0,stdout=data,stderr='')
    return execute,calls


def observe(product,callback=None,**kwargs):
    cp,*_=product;return api().observe(cp,file_hash(cp),runner=callback or runner(product)[0],clock=lambda:NOW,**kwargs)


def test_real_shaped_inventory_keeps_component_revisions_and_unknown_authority(product):
    execute,calls=runner(product);r=observe(product,execute)
    assert r['status']=='observed' and r['authority']=='none' and r['mode']=='SIMULATED' and r['model_requests']==0
    assert len(r['containers'])==7 and len(r['excluded'])==1 and r['excluded'][0]['reason']=='not_running_migration'
    assert r['images']['python']['revision_claim']=='a'*40 and r['images']['frontend']['revision_claim']=='b'*40
    assert all(r[k] is None for k in ('deployment_id','generation','owner','source_commit','source_sha256','config_sha256','maintenance_epoch'))
    assert r['metadata']==product[4] and r['metadata_status']=='observed' and r['release_allowed'] is False
    assert [x['healthy'] for x in r['containers'] if x['service']=='myink-worker']==[None,None]
    assert [a[0] for a in calls]==['info','ps','inspect','image','exec','ps','inspect']
    saved=read_json(Path(r['observation_path'])/'outcome.json');assert saved['observation_sha256']==r['observation_sha256']


@pytest.mark.parametrize('fault',['daemon','drift','metadata_shape','metadata_error'])
def test_mismatched_or_unknown_read_evidence_never_claims_ready(product,fault):
    r=observe(product,runner(product,fault=fault)[0]);assert not r['release_allowed'] and r['authority']=='none'
    if fault=='drift':assert r['status']=='confounded'
    elif fault in ('metadata_shape','metadata_error'):assert r['metadata_status']=='unknown' and r['metadata'] is None
    else:assert r['status']=='blocked'
    assert 'hidden-value' not in json.dumps(r)


@pytest.mark.parametrize('fault',['extra_service','missing_worker','mixed_worker_image','duplicate_id','bad_image','wrong_project','running_migration'])
def test_partial_duplicate_or_mixed_inventory_is_not_a_coherent_release_base(product,fault):
    cp,c,containers,images,meta=product
    if fault=='extra_service':containers[0]['service']='myink-unreviewed'
    elif fault=='missing_worker':containers.pop(2)
    elif fault=='mixed_worker_image':containers[1]['image_id']='sha256:'+'f'*64;images['sha256:'+'f'*64]=dict(id='sha256:'+'f'*64,revision='c'*40)
    elif fault=='duplicate_id':containers[1]['id']=containers[0]['id']
    elif fault=='bad_image':containers[0]['image_id']='--host=remote'
    elif fault=='wrong_project':containers[0]['project']='other'
    else:containers[-1].update(running=True,status='running')
    r=observe(product);assert r['status'] in ('blocked','confounded') and not r['release_allowed']


def test_untrusted_image_label_cannot_be_source_attestation_or_leak_prose(product):
    secret='Bearer sk-private-value-must-never-export';product[3]['sha256:'+'1'*64]['revision']=secret
    r=observe(product);assert r['status']=='observed' and r['source_commit'] is None and r['images']['python']['revision_claim'] is None
    assert secret not in json.dumps(r) and r['images']['python']['source_attested'] is False


@pytest.mark.parametrize('fault',['schema','extra','root_link','output_overlap','pin','mode','actual_runner','actual_clock'])
def test_untrusted_config_stops_before_any_docker_or_sql(product,fault,tmp_path):
    cp,c,*_=product;execute,calls=runner(product)
    if fault=='schema':c['schema']='model-release-v1'
    elif fault=='extra':c['query']='DROP TABLE tasks'
    elif fault=='root_link':alias=tmp_path/'link';alias.symlink_to(c['root']);c['root']=str(alias)
    elif fault=='output_overlap':c['root']=str(cp.parent)
    elif fault in ('actual_runner','actual_clock'):c['mode']='ACTUAL'
    elif fault=='mode':c['mode']='UNKNOWN'
    write(cp,c)
    with pytest.raises((ValueError,OSError)):
        api().observe(cp,'f'*64 if fault=='pin' else file_hash(cp),runner=None if fault=='actual_clock' else execute,clock=lambda:NOW)
    assert calls==[] and list(Path(product[1]['root']).glob('observation-*'))==[]


def test_same_containers_in_different_ps_order_are_a_coherent_snapshot(product):
    r=observe(product,runner(product,fault='reordered')[0]);assert r['status']=='observed' and r['cohort_sha256']


def test_revoked_config_prevents_the_next_read_command(product):
    cp,c,*_=product;original,calls=runner(product)
    def revoke(argv,seconds):
        value=original(argv,seconds)
        if argv[3]=='ps':write(cp,dict(c,worker_replicas=1))
        return value
    r=observe(product,revoke);assert r['status']=='blocked' and [a[0] for a in calls]==['info','ps']


def test_metadata_error_cannot_mask_revocation_before_the_next_census(product):
    cp,c,*_=product;original,calls=runner(product,fault='metadata_error')
    def revoke(argv,seconds):
        value=original(argv,seconds)
        if argv[3]=='exec':write(cp,dict(c,worker_replicas=1))
        return value
    r=observe(product,revoke);assert r['status']=='blocked' and [a[0] for a in calls]==['info','ps','inspect','image','exec']


def test_product_observer_imports_with_stdlib_only_without_paid_or_application_modules():
    import subprocess,sys
    project=Path(__file__).resolve().parents[3]
    code="import sys;sys.path.insert(0,sys.argv[1]);import ops.pi.product_reality;assert not any(k in sys.modules for k in ('httpx','sqlalchemy','ops.pi.selection_launcher','ops.pi.model_gateway','ops.pi.no_tool_host','myink.db'))"
    result=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(project)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_simulation_cannot_target_original_audit_state(product,tmp_path,monkeypatch):
    cp,c,*_=product;canonical=tmp_path/'original';(canonical/'audit/state').mkdir(mode=0o700,parents=True);original=canonical/'audit/state/events.sqlite';original.write_text('original-private-state');original.chmod(0o600)
    monkeypatch.setattr(api(),'BASE',canonical);c['audit_path']=str(original);write(cp,c);execute,calls=runner(product)
    with pytest.raises(ValueError):observe(product,execute)
    assert calls==[] and original.read_text()=='original-private-state'
