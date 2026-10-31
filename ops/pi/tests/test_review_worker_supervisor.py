"""Only a finite root-owned queue may activate external review ticks."""
from pathlib import Path
import importlib,pytest
from ops.pi.tests.test_manager_review_worker import published,handoff,completed,review_config,dossier_input,config_file,proof,write,NOW
from ops.pi.development_inputs import file_hash,ledger_snapshot


def api():return importlib.import_module('ops.pi.review_worker_supervisor')


@pytest.fixture
def registry(published):
    request,q,c,tc,r=published;path=request.parent/'review-worker-registry.json';value=dict(schema='pi-review-worker-registry-v1',mode='SIMULATED',entries=[dict(request_path=str(request),request_sha256=file_hash(request))]);write(path,value)
    return path,value,published


def test_finite_worker_queue_waits_without_fee_or_new_claim(registry):
    path,value,published=registry;before=ledger_snapshot(published[3]['ledger_path'])
    result=api().run(path,file_hash(path),clock=lambda:NOW)
    assert result['status']=='waiting' and result['model_requests']==0 and result['results'][0]['status']=='waiting_selection'
    assert ledger_snapshot(published[3]['ledger_path'])==before


@pytest.mark.parametrize('fault',['pin','entry_pin','duplicates','extra','actual_shadow','mode'])
def test_invalid_registry_cannot_dispatch(registry,fault):
    path,value,published=registry
    if fault=='entry_pin':value['entries'][0]['request_sha256']='f'*64
    elif fault=='duplicates':value['entries']*=2
    elif fault=='extra':value['command']='shell'
    elif fault=='actual_shadow':value['mode']='ACTUAL'
    elif fault=='mode':value['mode']='unknown'
    write(path,value);pin='f'*64 if fault=='pin' else file_hash(path)
    with pytest.raises((ValueError,OSError,KeyError,TypeError)):api().run(path,pin,clock=lambda:NOW)
    assert not (Path(published[4]['lease_path']).parent/'binding').exists()


def test_empty_registry_is_bounded_idle(registry):
    path,value,_=registry;value['entries']=[];write(path,value)
    assert api().run(path,file_hash(path),clock=lambda:NOW)['status']=='idle'


def test_verified_entry_dispatches_review_worker_without_model_import_fallback(monkeypatch,tmp_path,capsys):
    from ops.pi.tests.test_observer_entry import module
    entry=module();seen=[];(tmp_path/'vendor').mkdir()
    monkeypatch.setattr(entry,'verify_release',lambda *args:tmp_path/'code')
    monkeypatch.setattr(api(),'run',lambda config,pin:seen.append((config,pin)) or dict(status='idle',model_requests=0))
    monkeypatch.setattr('sys.argv',['entry.py','--component','review_worker','--config','/fixed/registry.json','--config-sha256','a'*64])
    import sys
    old=list(sys.path)
    try:assert entry.main()==0
    finally:sys.path[:]=old
    assert seen==[('/fixed/registry.json','a'*64)] and 'idle' in capsys.readouterr().out


def test_review_service_is_separate_from_manager_maintenance_lock():
    base=Path('ops/pi/deploy');service=(base/'myink-pi-review-worker.service').read_text();timer=(base/'myink-pi-review-worker.timer').read_text()
    assert '-I -S -B' in service and '--component review_worker' in service
    assert 'flock' not in service and 'maintenance.lock' not in service
    assert 'User=ubuntu' in service and 'NoNewPrivileges=yes' in service and 'Restart=no' in service
    assert 'OnUnitInactiveSec=5s' in timer and 'myink-pi-review-worker.service' in timer
