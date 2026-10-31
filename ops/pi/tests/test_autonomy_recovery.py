"""Only the still-uningested exact owned admission may be withdrawn under lock."""
from pathlib import Path
import fcntl,importlib
import pytest
from ops.pi.development_inputs import file_hash,ledger_snapshot,read_json
from ops.pi.tests.test_autonomy_profile import reproduced,proposed,profile,research_config,diagnosis_config,config_file,configured,proof,write,NOW
from ops.pi import manager


def api():return importlib.import_module('ops.pi.autonomy_recovery')


@pytest.fixture
def admitted(reproduced,proof,monkeypatch):
    from ops.pi.tests.test_review_lease import run_review
    ((pp,p,c,context),r,cfg),stage,result=reproduced;builder=importlib.import_module('ops.pi.autonomy_profile');review=builder.review(pp,file_hash(pp),r['claim_path'],clock=lambda:NOW);cp=Path(review['config_path']);rc=read_json(cp)
    run_review(cp,rc,read_json(rc['dossier_path']),proof,monkeypatch,now=NOW);handoff=builder.handoff(pp,file_hash(pp),r['claim_path'],clock=lambda:NOW)
    for module in ('ops.pi.maintenance_adapters','ops.pi.selection_launcher'):monkeypatch.setattr(module+'.verify_source',lambda *args:dict(machine='aarch64'))
    result=importlib.import_module('ops.pi.manager_handoff').publish(handoff['config_path'],handoff['config_sha256'],clock=lambda:NOW)
    return p,r,handoff,result


@pytest.mark.parametrize('partial',[False,True])
def test_owned_admission_is_preserved_and_withdrawn_before_ingest(admitted,partial):
    p,r,handoff,result=admitted;manifest=Path(result['manifest_path']);original=manifest.read_bytes();before=ledger_snapshot(p['host']['ledger_path'])
    if partial:(Path(read_json(handoff['config_path'])['root'])/'receipt.json').unlink()
    with Path(p['lock_path']).open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        value=api().withdraw(p,r['claim_path'],handoff,lock)
        assert value['status']=='withdrawn' and not manifest.exists() and Path(value['retained_manifest_path']).read_bytes()==original
        assert api().withdraw(p,r['claim_path'],handoff,lock)['cached'] is True
        _,_,rows,tasks,_=manager._snapshot(Path(p['manager_state']),Path(p['host']['ledger_path']),'SIMULATED')
        assert not manager._ingest(Path(p['inbox']),Path(p['manager_state']),Path(p['host']['ledger_path']),'SIMULATED',rows,tasks)
    assert ledger_snapshot(p['host']['ledger_path'])==before


@pytest.mark.parametrize('fault',['foreign_manifest','ingested','wrong_lock','foreign_request'])
def test_recovery_never_deletes_foreign_or_registered_admission(admitted,fault):
    p,r,handoff,result=admitted;manifest=Path(result['manifest_path'])
    if fault=='foreign_manifest':write(manifest,dict(schema='foreign',task_id='unowned'))
    elif fault=='ingested':
        m=read_json(manifest);manager.enqueue(p['manager_state'],p['host']['ledger_path'],m['task_id'],m['request_path'],m['request_sha256'],priority=m['priority'],mode='SIMULATED')
    elif fault=='foreign_request':handoff=dict(handoff,config_sha256='f'*64)
    lockpath=Path(p['lock_path'])
    if fault=='wrong_lock':lockpath=Path(r['claim_path'])/'foreign.lock';lockpath.touch(mode=0o600)
    original=manifest.read_bytes()
    with lockpath.open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises((ValueError,OSError,KeyError,TypeError)):api().withdraw(p,r['claim_path'],handoff,lock)
    assert manifest.read_bytes()==original and not (Path(r['claim_path'])/'withdrawal').exists()


def test_competing_maintenance_lock_prevents_withdrawal(admitted):
    p,r,handoff,result=admitted
    with Path(p['lock_path']).open('rb') as held,Path(p['lock_path']).open('rb') as other:
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):api().withdraw(p,r['claim_path'],handoff,other)
    assert Path(result['manifest_path']).exists()
