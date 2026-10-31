"""Retire authenticated terminal queue entries without deleting their evidence."""
from datetime import timedelta
from pathlib import Path
import importlib
import pytest
from ops.pi.development_inputs import file_hash,read_json,ledger_snapshot
from ops.pi.tests.test_manager_review_worker import published,handoff,completed,review_config,dossier_input,config_file,proof,select,prepared_config,write,NOW


def api():return importlib.import_module('ops.pi.autonomy_coordinator')


@pytest.fixture
def registration(published):
    parent=published[0].parent;config=parent/'registration-config';config.mkdir(mode=0o700);permit=config/'permits';permit.mkdir(mode=0o700);handoffs=parent/'registration-handoffs';handoffs.mkdir(mode=0o700);claims=parent/'registration-claims';claims.mkdir(mode=0o700)
    return dict(mode='SIMULATED',permit_root=str(permit),handoff_root=str(handoffs),root=str(claims),worker_entry_path=published[3]['docker'],controller_sha256='a'*64)


def registry(p,published):
    entry=dict(request_path=str(published[0]),request_sha256=file_hash(published[0]));path=Path(p['permit_root']).parent/'review-worker-registry.json';write(path,dict(schema='pi-review-worker-registry-v1',mode='SIMULATED',entries=[entry]));return path,entry


def new_stage(p):
    claim=Path(p['root'])/('b'*64);claim.mkdir(mode=0o700);cp=Path(p['handoff_root'])/'new-request.json';write(cp,dict(mode='SIMULATED'));return claim,dict(config_path=str(cp),config_sha256=file_hash(cp))


def test_expired_terminal_entry_is_archived_and_retired_before_new_registration(registration,published,proof,monkeypatch):
    sp,sc,task=select(published,proof,monkeypatch,abstain=True);worker=importlib.import_module('ops.pi.manager_review_worker');assert worker.tick(published[0],file_hash(published[0]),clock=lambda:NOW)['status']=='no_action'
    path,old=registry(registration,published);claim,stage=new_stage(registration);before=ledger_snapshot(sc['ledger_path'])
    api()._register(registration,claim,stage,clock=lambda:NOW+timedelta(days=2))
    assert read_json(path)['entries']==[dict(request_path=stage['config_path'],request_sha256=stage['config_sha256'])]
    assert read_json(claim/'registry-before-private.json')['entries']==[old] and published[0].exists() and ledger_snapshot(sc['ledger_path'])==before


def test_pending_entry_is_never_retired_or_advanced_by_registry_maintenance(registration,published,proof,monkeypatch):
    sp,sc,task=select(published,proof,monkeypatch);path,old=registry(registration,published);claim,stage=new_stage(registration)
    api()._register(registration,claim,stage,clock=lambda:NOW)
    assert read_json(path)['entries'][0]==old and len(read_json(path)['entries'])==2
    assert not (Path(published[4]['lease_path']).parent/'binding').exists()


def test_expired_pending_entry_blocks_registration_without_rewriting_queue(registration,published):
    path,old=registry(registration,published);claim,stage=new_stage(registration);original=path.read_bytes()
    with pytest.raises(ValueError):api()._register(registration,claim,stage,clock=lambda:NOW+timedelta(days=2))
    assert path.read_bytes()==original and not (claim/'registry-before-private.json').exists()
