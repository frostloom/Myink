"""Paired product collections: real SQLite/files, explicit simulated host I/O."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import io
import json
import sqlite3
import tarfile
import uuid

import pytest
from ops.pi.audit import digest
from ops.pi.backup import create_backup, verify_artifacts
from ops.pi.ledger import Ledger
from test_product_bootstrap import case as bootstrap_case, NOW, COUNTS


def api():
    assert importlib.util.find_spec('ops.pi.product_backup'), 'missing Linux paired recovery bridge'
    from ops.pi.product_backup import LinuxProductBackup
    return LinuxProductBackup


def write(path,value):
    path.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode());path.chmod(0o600)
    return sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def product_backup(bootstrap_case,tmp_path):
    _,plan,_=bootstrap_case;root=(tmp_path/'product').resolve();root.mkdir(mode=0o700);(root/'commands').mkdir(mode=0o700)
    control=Ledger(root/'control.sqlite');fee=Ledger(tmp_path/'original-fee.sqlite');manager=Ledger(tmp_path/'original-manager.sqlite')
    fee.path.chmod(0o600);manager.path.chmod(0o600)
    for n in range(9):fee.intent('unknown-'+str(n),'billing',dict(held_microyuan=2000000))
    manager.intent('retained-job','manager',dict(terminal=True))
    compose=tmp_path/'compose';compose.mkdir(mode=0o700)
    env=compose/'.env';env_pin=write(env,b'MODEL_CREDENTIAL_KEY=synthetic-private-key\n')
    conf=compose/'docker-compose.yml';conf_pin=write(conf,b'services: {}\n')
    c=dict(schema='pi-product-backup-v1',release_pair_id=plan['operation_id'],environment_path=str(env),environment_sha256=env_pin,compose_path=str(conf),compose_sha256=conf_pin,billing_ledger_path=str(fee.path.resolve()),manager_state_path=str(manager.path.resolve()),maximum_artifact_bytes=1048576)
    cp=tmp_path/'backup.json';pin=write(cp,c)
    host=SimpleNamespace(root=root,ledger=control,plan=plan,clock=lambda:NOW,config=dict(mode='SIMULATED',target='rehearsal',backup_path=str(cp),backup_sha256=pin,compose_dir=str(compose)),authorize=lambda value:None)
    host.inspect=lambda value:deepcopy(value['legacy'])
    fence=dict(verified=True,plan_sha256=digest(plan),fence_sha256='f'*64)
    quiet=dict(fence,api_exit_code=0,worker_exit_codes=[0,0],**dict.fromkeys(COUNTS,0))
    host.measure_quiet=lambda value,proofs:deepcopy(quiet)
    host._cid=lambda role:next(row['id'] for row in plan['legacy']['containers'] if row['service']==role)
    meta=dict(system_identifier='1234567890123456789',database='myink',size_bytes=1024,tables={'tasks':0,'agent_runs':0},content={'tasks':'d41d8cd98f00b204e9800998ecf8427e','agent_runs':'d41d8cd98f00b204e9800998ecf8427e'},roles={'myink':{'login':True},'myink_app':{'login':True},'myink_report':{'login':True}})
    host._json=lambda args:deepcopy(meta)
    effects=[]
    def run(args,**kwargs):
        effects.append(list(args));body=b''
        if 'pg_dumpall' in args:body=b'-- fixed roles fixture\nCREATE ROLE myink;\n'
        elif 'pg_dump' in args:body=b'-- fixed database fixture\nSELECT 1;\n'
        elif args[0]=='cp':
            path='feedback/attachment.bin' if '/data/feedback' in args[1] else 'data/caddy/cert.pem'
            data=b'fixture-private-material';raw=io.BytesIO()
            with tarfile.open(fileobj=raw,mode='w') as archive:
                entry=tarfile.TarInfo(path);entry.size=len(data);archive.addfile(entry,io.BytesIO(data))
            body=raw.getvalue()
        else:raise AssertionError('unreviewed fake collection command '+str(args))
        command_id=str(uuid.uuid4());folder=root/'commands'/command_id;folder.mkdir(mode=0o700);write(folder/'stdout.bin',body);write(folder/'stderr.bin',b'')
        return dict(command_id=command_id,status='done',returncode=0,stdout=dict(path='stdout.bin',bytes=len(body),sha256=sha256(body).hexdigest()),stderr=dict(path='stderr.bin',bytes=0,sha256=sha256(b'').hexdigest()))
    host._run=run;host._bytes=lambda result:(root/'commands'/result['command_id']/'stdout.bin').read_bytes()
    return host,c,{'close_ingress':fence},fee,manager,quiet,effects


def test_collection_contains_all_material_and_preserves_original_unknowns(product_backup):
    host,c,proofs,fee,manager,_,effects=product_backup
    before=[fee.get('unknown-'+str(n)) for n in range(9)]
    bridge=api()(host,proofs);pair=bridge.pair
    assert pair['pre_identity']['owner'] is None and pair['pre_identity']['generation'] is None
    result=create_backup(host.ledger,'PRE',bridge.legacy,bridge,bridge.collections,pair=pair)
    assert result.status=='done',result
    manifest=json.loads(Path(result.evidence['manifest_path']).read_bytes());folder=Path(result.evidence['manifest_path']).parent
    assert verify_artifacts(manifest,folder)
    assert {'database','roles','crypto','attachments','config','certificate','ledger','billing_snapshot','manager_snapshot'}<=set(manifest['artifacts'])
    assert [fee.get('unknown-'+str(n)) for n in range(9)]==before
    snapshot=folder/manifest['artifacts']['billing_snapshot']['path']
    with sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True) as copied:
        copied.row_factory=sqlite3.Row
        captured=[Ledger._record(copied.execute('SELECT * FROM operations WHERE operation_id=?',('unknown-'+str(n),)).fetchone()) for n in range(9)]
    assert captured==before
    assert verify_artifacts(manifest,folder)
    assert manager.get('retained-job')['status']=='pending'
    assert effects and all(args[0] in ('exec','cp') for args in effects)


@pytest.mark.parametrize('counter',COUNTS)
def test_unsettled_source_never_collects(product_backup,counter):
    host,_,proofs,_,_,quiet,effects=product_backup;quiet[counter]=1
    bridge=api()(host,proofs)
    result=create_backup(host.ledger,'PRE',bridge.legacy,bridge,bridge.collections,pair=bridge.pair)
    assert result.status=='failed' and effects==[]


def test_changed_sealed_environment_cannot_be_collected(product_backup):
    host,c,proofs,_,_,_,effects=product_backup
    Path(c['environment_path']).write_text('changed')
    with pytest.raises(ValueError):api()(host,proofs)
    assert effects==[]


def test_original_fee_file_cannot_double_as_control_ledger(product_backup):
    host,_,proofs,fee,_,_,effects=product_backup;host.ledger=fee
    with pytest.raises(ValueError):api()(host,proofs)
    assert effects==[]


def test_environment_changed_after_backend_construction_blocks_collection(product_backup):
    host,c,proofs,_,_,_,effects=product_backup
    bridge=api()(host,proofs)
    Path(c['environment_path']).write_text('changed-after-sealing')
    result=create_backup(host.ledger,'PRE',bridge.legacy,bridge,bridge.collections,pair=bridge.pair)
    assert result.status=='failed' and effects==[]


def _post_host(host,bridge,proofs,quiet):
    from dataclasses import asdict
    from ops.pi.contracts import Receipt
    host.inspect_candidate=lambda plan:deepcopy(plan['candidate'])
    host.measure_candidate_quiet=lambda plan,p:deepcopy(quiet)
    host.backup_container_id=lambda phase,role:('a'*64 if phase=='POST' and role=='api' else host._cid(role))
    host.ledger.intent('release:'+host.plan['operation_id'],'release',dict(release_pair_id=host.plan['operation_id'],candidate=asdict(bridge.candidate)))
    host.ledger.finish(Receipt('release:'+host.plan['operation_id'],'done',dict(post_pending=True)))


def test_post_collection_binds_candidate_and_uses_new_api_materials(product_backup):
    from dataclasses import asdict
    host,c,proofs,fee,_,quiet,effects=product_backup
    bridge=api()(host,proofs);_post_host(host,bridge,proofs,quiet)
    before=[fee.get('unknown-'+str(n)) for n in range(9)]
    result=create_backup(host.ledger,'POST',bridge.candidate,bridge,bridge.collections,pair=bridge.pair)
    assert result.status=='done',result
    manifest=json.loads(Path(result.evidence['manifest_path']).read_bytes())
    assert manifest['identity']==asdict(bridge.candidate) and manifest['phase']=='POST'
    assert any(args[:2]==['cp','a'*64+':/data/feedback'] for args in effects)
    assert [fee.get('unknown-'+str(n)) for n in range(9)]==before


@pytest.mark.parametrize('drift',['owner','generation','deployment_id','image_ids'])
def test_post_collection_refuses_current_candidate_identity_drift(product_backup,drift):
    host,_,proofs,_,_,quiet,effects=product_backup
    bridge=api()(host,proofs);_post_host(host,bridge,proofs,quiet)
    changed=deepcopy(host.plan['candidate'])
    changed[drift]=9001 if drift=='generation' else {} if drift=='image_ids' else 'manual-release'
    host.inspect_candidate=lambda plan:changed
    result=create_backup(host.ledger,'POST',bridge.candidate,bridge,bridge.collections,pair=bridge.pair)
    assert result.status=='failed' and effects==[]


def test_post_collection_rechecks_quiet_and_never_releases_unknown_fees(product_backup):
    host,_,proofs,fee,_,quiet,effects=product_backup
    bridge=api()(host,proofs);_post_host(host,bridge,proofs,quiet);quiet['unknown']=1
    result=create_backup(host.ledger,'POST',bridge.candidate,bridge,bridge.collections,pair=bridge.pair)
    assert result.status=='failed' and effects==[]
    assert all(fee.get('unknown-'+str(n))['status']=='pending' for n in range(9))


def test_recovery_schema_context_is_not_reset_by_new_owner_or_generation(product_backup):
    host,_,proofs,_,_,_,_=product_backup
    first=api()(host,proofs).context
    host.plan['candidate']['owner']='next-pi-owner';host.plan['candidate']['generation']+=1
    second=api()(host,proofs).context
    assert first==second


def test_recovery_tool_context_includes_application_and_restore_guards(product_backup,tmp_path,monkeypatch):
    import ops.pi.product_backup as module
    controller=tmp_path/'controller';controller.mkdir()
    source=Path(module.__file__).parent
    for name in ('product_lineage.py','product_rollback_lease.py','product_service_snapshot.py','product_restored_services.py','product_restored_api.py','product_business_probe.py','product_runtime_snapshot.py','product_activation.py','product_release.py','product_backup.py','product_restore.py','product_cold_probe.py','product_runtime.py','product_commands.py','product_migration.py','product_bootstrap.py','backup.py','ledger.py','audit.py'):
        (controller/name).write_bytes((source/name).read_bytes())
    monkeypatch.setattr(module,'__file__',str(controller/'product_backup.py'))
    host,_,proofs,_,_,_,_=product_backup
    first=api()(host,proofs).context
    (controller/'product_lineage.py').write_text('changed lineage verification')
    lineage=api()(host,proofs).context
    assert first['tool_context']!=lineage['tool_context']
    (controller/'product_cold_probe.py').write_text('changed application verification')
    second=api()(host,proofs).context
    assert first['tool_context']!=second['tool_context'] and lineage['tool_context']!=second['tool_context']
