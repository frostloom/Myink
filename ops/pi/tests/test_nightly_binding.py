"""Postdeployment config issuance cannot precede human approval or deployment."""
from pathlib import Path
import json
import pytest
from ops.pi.tests.test_nightly_deployment import deployed_case,bundle_case,finished,stopped,completed,config_file,Image,confirm,IDENTITY
from ops.pi.development_inputs import file_hash,ledger_snapshot


@pytest.fixture
def binding_case(deployed_case):
    case,calls=deployed_case;g,cycle,root,*_=case
    template=root/'template.json'
    value=dict(schema='pi-live-observer-v1',mode='SIMULATED',root=str(root/'old-metrics'),audit_path=str(root/'audit.sqlite'),source=dict(docker='/bin/echo',endpoint='unix:///fixture.sock',daemon_id='fixture-daemon',container_id='a'*64,image_id='sha256:'+'2'*64,database='myink',database_user='myink_metrics',view_sha256='3'*64),identity=dict(deployment_id='old-version'),interval_minutes=15,lookback_hours=1,minimum_samples=20)
    template.write_text(json.dumps(value));template.chmod(0o600)
    return deployed_case,template


def bind(case):
    from ops.pi.nightly_binding import bind
    deployed,template=case;g,cycle,root,*_=deployed[0]
    return bind(g,cycle,root/'bundle',template,file_hash(template))


def test_unconfirmed_or_undeployed_candidate_cannot_issue_observer_config(binding_case):
    with pytest.raises(ValueError):bind(binding_case)
    assert not (binding_case[0][0][2]/'observer-binding.json').exists()


def test_verified_deployment_binds_exact_process_identity_and_keeps_reader_scope(binding_case):
    confirm(binding_case[0]);before=tuple(ledger_snapshot(p) for p in binding_case[0][0][4][:2])
    result=bind(binding_case);config=json.loads(Path(result['path']).read_bytes());template=json.loads(binding_case[1].read_bytes())
    assert config['identity']==IDENTITY and config['source']==template['source']
    assert config['root']!=template['root'] and Path(config['root']).is_dir()
    assert result==bind(binding_case) and result['sha256']==file_hash(result['path'])
    assert tuple(ledger_snapshot(p) for p in binding_case[0][0][4][:2])==before


@pytest.mark.parametrize('fault',['config','context','template'])
def test_binding_drift_never_silently_reissues_or_overwrites(binding_case,fault):
    confirm(binding_case[0]);result=bind(binding_case);root=binding_case[0][0][2]
    path=Path(result['path']) if fault=='config' else root/'deployment-context.json' if fault=='context' else binding_case[1]
    value=json.loads(path.read_bytes());value['drift']=True;path.write_text(json.dumps(value))
    with pytest.raises(ValueError):bind(binding_case)


def test_interrupted_binding_is_retained_without_replacing_unknown_config(binding_case):
    confirm(binding_case[0]);root=binding_case[0][0][2];(root/'observer-binding-intent.json').write_text('{}');(root/'observer-binding-intent.json').chmod(0o600)
    with pytest.raises(ValueError):bind(binding_case)


def test_actual_collector_hands_off_metrics_and_fixed_audit_files(binding_case,monkeypatch):
    from ops.pi import nightly_binding as binding
    from ops.pi import live_observer
    confirm(binding_case[0]);p=bind(binding_case);config=json.loads(Path(p['path']).read_bytes());root=Path(config['root'])/'observer-fixture';root.mkdir(mode=0o700)
    for name in ('intent.json','metrics.json','receipt.json'):(root/name).write_text('{}')
    auditfiles=_audit_fixture(binding,config,Path(p['path']),monkeypatch);p['sha256']=file_hash(p['path'])
    changed=[];monkeypatch.setattr(binding,'_ordinary',lambda path,mode:changed.append(path));monkeypatch.setattr(live_observer,'observe',lambda *a,**k:dict(run_id=root.name,status='passed'))
    assert binding.collect(p['path'],p['sha256'],mode='ACTUAL')['status']=='passed'
    assert set(changed)=={root,*root.iterdir(),*auditfiles} and Path(p['path']) not in changed


def test_config_changed_during_collection_cannot_redirect_permission_handoff(binding_case,monkeypatch):
    from ops.pi import nightly_binding as binding
    from ops.pi import live_observer
    confirm(binding_case[0]);p=bind(binding_case);path=Path(p['path']);config=json.loads(path.read_bytes());root=Path(config['root'])/'observer-fixture';root.mkdir(mode=0o700);(root/'receipt.json').write_text('{}');changed=[]
    def observe(*a,**k):config['minimum_samples']=500;path.write_text(json.dumps(config));return dict(run_id=root.name,status='passed')
    monkeypatch.setattr(live_observer,'observe',observe);monkeypatch.setattr(binding,'_ordinary',lambda *a:changed.append(a))
    with pytest.raises(ValueError):binding.collect(path,p['sha256'],mode='ACTUAL')
    assert changed==[]


def _audit_fixture(binding,config,path,monkeypatch):
    from ops.pi.audit import AuditStore
    base=path.parent/'fixed-base';state=base/'audit/state';state.mkdir(parents=True,mode=0o700);export=base/'audit/export';audit=state/'events.sqlite';store=AuditStore(audit)
    store.append('fixture',dict(kind='version',status='no_release',run_id='fixture',occurred_at=None,summary='Fixture audit only.',details={},version={},changes=[],evidence=[],followups=[],mode='ACTUAL',evidence_domain='offline'));store.export(export)
    config.update(audit_path=str(audit),export_root=str(export));path.write_text(json.dumps(config));monkeypatch.setattr(binding,'BASE',base)
    return {audit,export/'manifest.json',*(export/'pages').glob('*.json')}


@pytest.mark.parametrize('fault',['outside','linked_page','page_traversal'])
def test_actual_audit_handoff_cannot_change_unrelated_files(binding_case,monkeypatch,fault):
    from ops.pi import nightly_binding as binding,live_observer
    confirm(binding_case[0]);p=bind(binding_case);path=Path(p['path']);config=json.loads(path.read_bytes());root=Path(config['root'])/'observer-fixture';root.mkdir(mode=0o700);(root/'receipt.json').write_text('{}');_audit_fixture(binding,config,path,monkeypatch)
    export=Path(config['export_root']);outside=path.parent/'unrelated.json';outside.write_text('{}')
    if fault=='outside':config['audit_path']=str(outside);path.write_text(json.dumps(config))
    elif fault=='linked_page':page=next((export/'pages').glob('*.json'));page.unlink();page.symlink_to(outside)
    else:
        manifest=export/'manifest.json';value=json.loads(manifest.read_bytes());value['pages'][0]['sha256']='../unrelated';manifest.write_text(json.dumps(value))
    changed=[];monkeypatch.setattr(binding,'_ordinary',lambda *a:changed.append(a));monkeypatch.setattr(live_observer,'observe',lambda *a,**k:dict(run_id=root.name,status='passed'))
    with pytest.raises(ValueError):binding.collect(path,file_hash(path),mode='ACTUAL')
    assert changed==[]


def test_audit_handoff_accepts_exporters_valid_manifest_above_one_megabyte(binding_case,monkeypatch):
    from ops.pi import nightly_binding as binding,live_observer
    from ops.pi.audit import AuditStore
    confirm(binding_case[0]);p=bind(binding_case);path=Path(p['path']);config=json.loads(path.read_bytes());root=Path(config['root'])/'observer-fixture';root.mkdir(mode=0o700);(root/'receipt.json').write_text('{}');_audit_fixture(binding,config,path,monkeypatch)
    store=AuditStore(config['audit_path']);event=dict(kind='version',status='no_release',run_id='fixture',occurred_at=None,summary='History.',details={},version={},changes=[],evidence=[],followups=[],mode='ACTUAL',evidence_domain='offline')
    for index in range(2600):store.append('history-'+str(index),dict(event,run_id='long-'+str(index).zfill(4)+'x'*148))
    store.export(config['export_root']);manifest=Path(config['export_root'])/'manifest.json';assert 1048576<manifest.stat().st_size<=8388608
    changed=[];monkeypatch.setattr(binding,'_ordinary',lambda path,mode:changed.append(path));monkeypatch.setattr(live_observer,'observe',lambda *a,**k:dict(run_id=root.name,status='passed'))
    assert binding.collect(path,file_hash(path),mode='ACTUAL')['status']=='passed' and manifest in changed
