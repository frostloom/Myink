"""Stable project/history config; retirement does not enable incomplete upgrades."""
from copy import deepcopy
from pathlib import Path
import json,uuid,fcntl
import pytest
from ops.pi.audit import digest
from ops.pi.contracts import Receipt
from test_product_runtime import runtime_case,bootstrap_case,write,api,NOW
from test_product_lineage import lineage_case
from test_product_activation import activation_inputs,context
from test_product_upgrade import upgrade


def stable(case):
    path,_,c,plan,_=case;c.update(schema='pi-linux-product-host-v2',project_operation_id=plan['operation_id'],lineage_path=None,lineage_sha256=None)
    return api()(path,write(path,c),clock=lambda:NOW)


def test_new_operation_keeps_original_project_and_control_history(runtime_case,lineage_case):
    first=stable(runtime_case);seed,*_=lineage_case(ledger=first.ledger)
    packet=seed.lineage;new=seed.plan;c=deepcopy(first.config)
    root=first.root/'next-operation';root.mkdir(mode=0o700);c['root']=str(root)
    for field,value in (('plan',new),('lineage',packet),('approval',dict(schema='pi-product-release-approval-v1',mode='SIMULATED',target='rehearsal',authority='owned_rehearsal',plan_sha256=digest(new),approved_actions=['close_ingress','drain_legacy','backup_pre','install_schema','bind_identity'],expires_at=new['expires_at']))):
        path=root/(field+'.json');c[field+'_path']=str(path);c[field+'_sha256']=write(path,value)
    original_manifest=json.loads(Path(c['legacy_manifest_path']).read_bytes());original_manifest['source_commit']=new['legacy']['source_commit']
    path=root/'legacy.json';c['legacy_manifest_path']=str(path);c['legacy_manifest_sha256']=write(path,original_manifest)
    hp=Path(runtime_case[0]);second=api()(hp,write(hp,c),clock=lambda:NOW)
    assert second.ledger.path==first.ledger.path and second.config['project']==first.config['project']
    assert second.ledger.get(first.plan['operation_id'])['status']=='done'
    assert not (root/'control.sqlite').exists()
    with second.lock(new):
        with pytest.raises(ValueError,match='continuous upgrade intake qualification pending'):second.preflight()


def test_initial_stable_config_requires_no_lineage_and_original_project(runtime_case):
    h=stable(runtime_case);assert h.ledger.path.parent==h.lock_path.parent
    assert h.config['project_operation_id'] in h.ledger.path.name
    c=deepcopy(h.config);c['project_operation_id']=str(uuid.uuid4());path=Path(runtime_case[0])
    with pytest.raises(ValueError):api()(path,write(path,c),clock=lambda:NOW)


def test_rehearsal_resources_keep_original_namespace_across_operation_ids(activation_inputs):
    _,p,c,*_=activation_inputs;original=p['operation_id'];new=upgrade(p);new['operation_id']=str(uuid.uuid4());p.clear();p.update(new)
    c['project_operation_id']=original
    assert context(activation_inputs)['project']==c['project']
    c['project_operation_id']=str(uuid.uuid4())
    with pytest.raises(ValueError):context(activation_inputs)


def test_retire_entry_holds_original_lock_and_accepts_no_release_controls(runtime_case,monkeypatch):
    from ops.pi import product_entrypoint as entry
    from ops.pi.product_runtime import LinuxProductHost
    path,pin,c,plan,*_=runtime_case
    monkeypatch.setattr(entry,'LinuxProductHost',lambda *a,**kw:LinuxProductHost(*a,clock=lambda:NOW,**kw))
    def retire(h):
        h.authorize(h.plan)
        with h.lock_path.open('rb') as contender:
            with pytest.raises(BlockingIOError):fcntl.flock(contender,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return Receipt(plan['operation_id'],'done',dict(phase='previous_backends_retired'))
    monkeypatch.setattr(entry,'retire_previous',retire,raising=False)
    assert entry.execute('retire',host_path=path,host_sha256=pin).status=='done'
    with pytest.raises(ValueError):entry.execute('retire',host_path=path,host_sha256=pin,control_path=path)
