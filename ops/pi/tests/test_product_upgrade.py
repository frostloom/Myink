"""Frozen previous-generation authority; this does not enable native rollout."""
from copy import deepcopy
import uuid
import pytest
from test_product_bootstrap import case
from ops.pi.product_bootstrap import _plan


def upgrade(plan):
    p=deepcopy(plan);p['schema']='pi-product-upgrade-v2'
    p['previous']=dict(id=1,epoch=str(uuid.uuid4()),deployment_id='previous',generation=4,owner='pi',image_ids=deepcopy(p['candidate']['image_ids']),deadline=p['expires_at'],admission_closed=False,consumer_blocked=False)
    p['candidate']['generation']=5
    return p


def test_upgrade_accepts_exact_next_generation_without_mutating_input(case):
    _,plan,_=case;p=upgrade(plan);before=deepcopy(p)
    assert _plan(p)==before and p==before


@pytest.mark.parametrize('field,value',[
    ('id',True),('id',2),('epoch','manual'),('generation',True),('generation',0),
    ('generation',5),('owner',''),('deployment_id',''),('deadline',None),
    ('admission_closed',True),('consumer_blocked',True),('image_ids',{}),
])
def test_upgrade_rejects_unfrozen_or_ambiguous_previous_identity(case,field,value):
    _,plan,_=case;p=upgrade(plan);p['previous'][field]=value
    with pytest.raises(ValueError):_plan(p)


def test_upgrade_rejects_legacy_image_mismatch_reused_epoch_and_deployment(case):
    _,plan,_=case
    for mutate in (lambda p:p['previous']['image_ids'].update(python='sha256:'+'f'*64),lambda p:p.update(operation_id=p['previous']['epoch']),lambda p:p['candidate'].update(deployment_id=p['previous']['deployment_id'])):
        p=upgrade(plan);mutate(p)
        with pytest.raises(ValueError):_plan(p)


def test_v1_cannot_smuggle_previous_authority(case):
    _,plan,_=case;p=upgrade(plan);p['schema']='pi-product-bootstrap-v1'
    with pytest.raises(ValueError):_plan(p)


from test_product_runtime import runtime_case,bootstrap_case,write,api,NOW


def test_native_upgrade_guard_precedes_output_and_control_ledger_creation(runtime_case):
    from pathlib import Path
    config_path,_,config,plan,_=runtime_case
    p=upgrade(plan);config['plan_sha256']=write(Path(config['plan_path']),p)
    pin=write(config_path,config)
    with pytest.raises(ValueError,match='continuous native cohort admission pending'):
        api()(config_path,pin,clock=lambda:NOW)
    root=Path(config['root'])
    assert not (root/'commands').exists() and not (root/'actions').exists() and not (root/'control.sqlite').exists()


@pytest.mark.parametrize('kind,expected',[
    ('float','DOUBLE PRECISION'),('double','DOUBLE PRECISION'),('real','REAL'),
    ('varchar32','VARCHAR(32)'),('varchar64','VARCHAR(64)'),('json','JSON'),('jsonb','JSONB'),
])
def test_native_column_contract_normalizes_only_pg_float_alias(kind,expected):
    import ast
    from sqlalchemy import Float,String,JSON
    from sqlalchemy.dialects.postgresql import dialect,DOUBLE_PRECISION,REAL,JSONB
    from ops.pi.product_migration import SCRIPT
    definitions=[n for n in ast.parse(SCRIPT).body if isinstance(n,ast.FunctionDef) and n.name=='column_type']
    assert len(definitions)==1,'missing PostgreSQL schema type normalization'
    module=ast.Module(body=definitions,type_ignores=[]);namespace={}
    exec(compile(module,'<fixed native type contract>','exec'),namespace)
    types=dict(float=Float(),double=DOUBLE_PRECISION(),real=REAL(),varchar32=String(32),varchar64=String(64),json=JSON(),jsonb=JSONB())
    assert namespace['column_type'](types[kind],dialect())==expected
