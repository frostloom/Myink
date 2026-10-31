"""Root-issued read-only business cases cannot carry arbitrary requests."""
from copy import deepcopy
import importlib.util,uuid
import pytest
from ops.pi.audit import digest
from test_product_activation import activation_inputs,bootstrap_case,context


def api():
    assert importlib.util.find_spec('ops.pi.product_business_probe'),'missing fixed authenticated business probe'
    from ops.pi import product_business_probe
    return product_business_probe


def packet(plan,context_pin):
    ids=[str(uuid.uuid4()) for _ in range(4)]
    return dict(schema='pi-business-read-probe-v1',mode=plan['mode'],plan_sha256=digest(plan),context_sha256=context_pin,expires_at=plan['expires_at'],cases=[dict(user_id=ids[0],auth_version=1,foreign_user_id=ids[1],foreign_auth_version=1,project_id=ids[2],chapter_id=ids[3],expected_sha256='a'*64)])


def test_case_packet_is_closed_and_bound_to_approved_source(activation_inputs):
    _,plan,*_=activation_inputs;p=packet(plan,'f'*64)
    assert api().validate(p,plan,'f'*64)==p


@pytest.mark.parametrize('fault',['url','method','body','plan','context','empty','duplicate','foreign-is-owner','bad-id','bad-version','bad-sha'])
def test_case_packet_rejects_arbitrary_or_unbound_business_reads(activation_inputs,fault):
    _,plan,*_=activation_inputs;p=packet(plan,'f'*64);case=p['cases'][0]
    if fault in ('url','method','body'):case[fault]='unapproved'
    elif fault=='plan':p['plan_sha256']='0'*64
    elif fault=='context':p['context_sha256']='0'*64
    elif fault=='empty':p['cases']=[]
    elif fault=='duplicate':p['cases'].append(deepcopy(case))
    elif fault=='foreign-is-owner':case['foreign_user_id']=case['user_id']
    elif fault=='bad-id':case['project_id']='../other'
    elif fault=='bad-version':case['auth_version']=True
    elif fault=='bad-sha':case['expected_sha256']='not-a-digest'
    with pytest.raises(ValueError):api().validate(p,plan,'f'*64)
