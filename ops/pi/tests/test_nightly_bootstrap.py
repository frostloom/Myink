"""Standing local preparation does not impersonate human publication approval."""
from pathlib import Path
import json,uuid
import pytest
from ops.pi.tests.test_nightly_rebuild import rebuild_case,bundle_case,finished,stopped,completed,config_file,run
from ops.pi.nightly_compatibility import PREIMAGES,CANDIDATES,PATCH
from ops.pi.development_inputs import file_hash,ledger_snapshot


def setup(case):
    original,new,permission,rp,*_=case
    report=json.loads(rp.read_bytes());report['patch_sha256']=PATCH;report['changes']={p:dict(before=PREIMAGES[p],after=CANDIDATES[p]) for p in CANDIDATES};rp.write_text(json.dumps(report))
    request=json.loads(permission.read_bytes());request.update(schema='pi-nightly-operator-bootstrap-v1',issuer='trusted_compatibility_builder',compatibility_sha256=file_hash(rp));permission.write_text(json.dumps(request))
    return case


def test_local_bootstrap_finishes_same_task_and_waits_without_human_approval(rebuild_case):
    c=setup(rebuild_case);g,old,root,*_=c[0];before=ledger_snapshot(g.state),ledger_snapshot(g.billing);oldbytes=(root/'bundle/manifest.json').read_bytes()
    result=run(c)
    assert result['status']=='awaiting_approval' and result['model_requests']==0
    assert (ledger_snapshot(g.state),ledger_snapshot(g.billing))==before and (root/'bundle/manifest.json').read_bytes()==oldbytes
    with g._connection() as db:
        events=[r[0] for r in db.execute('SELECT kind FROM approval_events')]
        assert 'operator_bootstrap_claimed' in events and 'human_rebuild_claimed' not in events and 'human_approved' not in events
    event=json.loads((root.parent/c[1]/'rebuild-audit.json').read_bytes())['records'][0]['event']
    assert event['evidence'][0]['kind']=='operator_bootstrap_instruction'
    for action in ('github_push','registry_push','deploy','observe_metrics'):
        with pytest.raises(ValueError):g.require_action(c[1],action)
    assert run(c)==result


@pytest.mark.parametrize('fault',['patch','scope','issuer','human_api'])
def test_bootstrap_is_only_the_fixed_companion_and_cannot_claim_human_authority(rebuild_case,fault):
    c=setup(rebuild_case);g,old,*_=c[0];permission,rp=c[2:4]
    if fault in ('patch','scope'):
        report=json.loads(rp.read_bytes())
        if fault=='patch':report['patch_sha256']='0'*64
        else:report['changes']['src/myink/config.py']['after']='0'*64
        rp.write_text(json.dumps(report));request=json.loads(permission.read_bytes());request['compatibility_sha256']=file_hash(rp);permission.write_text(json.dumps(request))
    if fault=='issuer':request=json.loads(permission.read_bytes());request['issuer']='model';permission.write_text(json.dumps(request))
    with pytest.raises(ValueError):
        if fault=='human_api':g.begin_rebuild(old,permission,file_hash(permission))
        else:run(c)
    assert g.status()['cycle_id']==old


def test_bootstrap_cannot_start_another_iteration_from_a_replacement(rebuild_case):
    c=setup(rebuild_case);run(c);g,old,*_=c[0];permission,rp=c[2:4];request=json.loads(permission.read_bytes());report=json.loads(rp.read_bytes());new=c[1]
    report.update(cycle_id=new,package_sha256=g.status()['package_sha256']);rp.write_text(json.dumps(report))
    request.update(cycle_id=new,new_cycle_id=str(uuid.uuid4()),night='2026-11-02',package_sha256=g.status()['package_sha256'],compatibility_sha256=file_hash(rp));permission.write_text(json.dumps(request))
    with pytest.raises(ValueError):g.begin_bootstrap(new,permission,file_hash(permission),rp)
    assert g.status()['cycle_id']==new and g.status()['phase']=='awaiting_approval'
