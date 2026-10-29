"""Effective config is a private authenticated recovery input, not a permit."""
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
import importlib.util
import pytest
from ops.pi.audit import digest
from test_product_activation import activation_inputs,bootstrap_case,context
from test_product_backup import product_backup,write


def api():
    assert importlib.util.find_spec('ops.pi.product_runtime_snapshot'),'missing private runtime snapshot binding'
    from ops.pi import product_runtime_snapshot
    return product_runtime_snapshot


def sample(inputs):
    _,plan,c,n,v,rows=inputs;ctx=context(inputs)
    plan['candidate']['config_hash']=ctx['configuration_sha256'];ctx['plan_sha256']=digest(plan)
    return plan,c,ctx,n,v,rows


def test_pre_snapshot_preserves_effective_credentials_and_resource_spec(activation_inputs):
    plan,c,ctx,n,v,rows=sample(activation_inputs)
    value=api().capture(plan,c,ctx,'PRE',rows,n,[v])
    assert value['plan_sha256']==digest(plan) and value['phase']=='PRE' and len(value['containers'])==3
    assert all(row['host_config']['Memory']==536870912 for row in value['containers'])
    assert any('synthetic-private-value' in entry for row in value['containers'] for entry in row['config']['Env'])
    settings=api().connection_settings(value)
    assert settings['app']=='postgresql+psycopg://myink_app:synthetic@127.0.0.1:5432/myink'
    assert settings['report']=='postgresql+psycopg://myink_report:synthetic@127.0.0.1:5432/myink'


@pytest.mark.parametrize('fault',['environment','memory','network','volume','missing-backend'])
def test_pre_effective_config_drift_rejected(activation_inputs,fault):
    plan,c,ctx,n,v,rows=sample(activation_inputs)
    if fault=='environment':rows[0]['Config']['Env'].append('UNREVIEWED=1')
    elif fault=='memory':rows[0]['HostConfig']['Memory']=1
    elif fault=='network':n['Id']='a'*64
    elif fault=='volume':v['Labels']['myink.pi.rehearsal']='foreign'
    elif fault=='missing-backend':rows.pop()
    with pytest.raises(ValueError):api().capture(plan,c,ctx,'PRE',rows,n,[v])


@pytest.mark.parametrize('url',[
 'postgresql+psycopg://myink:secret@myink-pg/myink',
 'postgresql+psycopg://myink_app@myink-pg/myink',
 'postgresql+psycopg://myink_app:secret@myink-pg/other',
 'postgresql+psycopg://myink_app:secret@external.invalid/myink',
 'postgresql+psycopg://myink_app:secret@myink-pg/myink?options=unsafe',
 'postgresql+psycopg://myink_app:bad%0Avalue@myink-pg/myink'])
def test_auth_retarget_rejects_role_bypass_and_external_or_incomplete_config(url):
    with pytest.raises(ValueError):api().local_url(url,'myink_app')


def test_auth_retarget_preserves_escaped_password_without_external_endpoint():
    assert api().local_url('postgresql+psycopg://myink_app:a%3Ab%40c%2Fd@myink-pg/myink','myink_app')=='postgresql+psycopg://myink_app:a%3Ab%40c%2Fd@127.0.0.1:5432/myink'


def test_backup_v2_requires_sealed_runtime_context(product_backup,activation_inputs,tmp_path):
    from ops.pi.product_backup import LinuxProductBackup
    h,c,proofs,*_=product_backup;plan,settings,ctx,n,v,rows=sample(activation_inputs)
    h.plan=plan;h.config.update(settings)
    cp=tmp_path/'runtime-context.json';pin=write(cp,ctx)
    c.update(schema='pi-product-backup-v2',release_pair_id=plan['operation_id'],runtime_context_path=str(cp),runtime_context_sha256=pin)
    h.config['backup_sha256']=write(__import__('pathlib').Path(h.config['backup_path']),c)
    backend=LinuxProductBackup(h,proofs)
    assert backend.qualification=='runtime'
    cp.write_text('{}')
    with pytest.raises(ValueError):LinuxProductBackup(h,proofs)


def test_recovery_auth_binds_phase_and_uses_only_ephemeral_admin(activation_inputs):
    plan,c,ctx,n,v,rows=sample(activation_inputs);snapshot=api().capture(plan,c,ctx,'PRE',rows,n,[v])
    auth=api().authentication(snapshot,digest(plan),'PRE','pi_restore_'+'a'*32,'temporary_target_only_password_123456')
    assert auth['app_url'].startswith('postgresql+psycopg://myink_app:')
    assert auth['report_url'].startswith('postgresql+psycopg://myink_report:')
    assert 'temporary_target_only_password_123456' in auth['admin_url']
    assert 'trust' not in auth['hba'].split('\n',1)[1]
    assert 'scram-sha-256' in auth['hba']
    for pin,phase,admin in [(digest(plan),'POST','pi_restore_'+'a'*32),('0'*64,'PRE','pi_restore_'+'a'*32),(digest(plan),'PRE','myink')]:
        with pytest.raises(ValueError):api().authentication(snapshot,pin,phase,admin,'temporary_target_only_password_123456')


def post_rows(plan,ctx):
    from ops.pi.product_activation import cohort_environment
    result=[];bindings={}
    for index,t in enumerate(ctx['templates']):
        row=deepcopy(t);row['Id']=format(index+10,'x')*64;bindings[t['Id']]=row['Id'];row['Image']=plan['candidate']['image_ids']['python']
        row['Config']['Env']=[k+'='+v for k,v in cohort_environment(t,plan['candidate']).items()]
        row['Config']['Labels'].update({'myink.pi.release.operation':plan['operation_id'],'myink.pi.release.role':'candidate'})
        row['HostConfig'].update(ReadonlyRootfs=True,MemorySwap=t['HostConfig']['Memory'],PidsLimit=128,CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],Tmpfs={'/tmp':'rw'},NetworkMode=ctx['network']['id'])
        row['State']=dict(Status='created',Running=False,ExitCode=0,OOMKilled=False);result.append(row)
    return result,bindings


def test_post_snapshot_uses_verified_adopted_environment(activation_inputs):
    plan,c,ctx,n,v,_=sample(activation_inputs);rows,bindings=post_rows(plan,ctx)
    value=api().capture(plan,c,ctx,'POST',rows,n,[v],bindings=bindings)
    assert value['phase']=='POST'
    assert all('DEPLOYMENT_GENERATION=1' in row['config']['Env'] for row in value['containers'])


@pytest.mark.parametrize('fault',['role','environment','privilege','volume','old-id','unbound'])
def test_post_snapshot_rejects_adopted_identity_or_resource_drift(activation_inputs,fault):
    plan,c,ctx,n,v,_=sample(activation_inputs);rows,bindings=post_rows(plan,ctx)
    if fault=='role':rows[0]['Config']['Labels']['myink.pi.release.role']='rollback'
    elif fault=='environment':rows[0]['Config']['Env'].append('EXTRA_UNAPPROVED=1')
    elif fault=='privilege':rows[0]['HostConfig']['Privileged']=True
    elif fault=='volume':rows[0]['Mounts'].append(dict(Type='bind',Source='/tmp',Destination='/host',RW=True))
    elif fault=='old-id':rows[0]['Id']=ctx['templates'][0]['Id'];bindings[ctx['templates'][0]['Id']]=rows[0]['Id']
    elif fault=='unbound':bindings.pop(next(iter(bindings)))
    with pytest.raises(ValueError):api().capture(plan,c,ctx,'POST',rows,n,[v],bindings=bindings)


def test_runtime_contract_invalidates_weak_application_context(product_backup,activation_inputs,tmp_path):
    from ops.pi.product_backup import LinuxProductBackup
    h,c,proofs,*_=product_backup;plan,settings,ctx,*_=sample(activation_inputs);h.plan=plan;h.config.update(settings)
    c['release_pair_id']=plan['operation_id'];h.config['backup_sha256']=write(__import__('pathlib').Path(h.config['backup_path']),c)
    before=LinuxProductBackup(h,proofs).context
    cp=tmp_path/'runtime-contract.json';pin=write(cp,ctx);c.update(schema='pi-product-backup-v2',runtime_context_path=str(cp),runtime_context_sha256=pin)
    h.config['backup_sha256']=write(__import__('pathlib').Path(h.config['backup_path']),c)
    after=LinuxProductBackup(h,proofs).context
    assert before['schema_context']!=after['schema_context']
