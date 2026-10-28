"""Phase subprocesses have a fixed dispatch table and cooperative signal cleanup."""
from pathlib import Path
from threading import Event
import importlib,os,signal
import pytest
from ops.pi.audit import encoded
from ops.pi.development_inputs import file_hash


def api():return importlib.import_module('ops.pi.autonomy_worker')


def config(tmp_path,mode='ACTUAL'):
    p=tmp_path/'phase.json';p.write_bytes(encoded(dict(schema='pi-investigation-v1',mode=mode)));p.chmod(0o600);return p


@pytest.mark.parametrize('fault',['component','mode','pin','cancelled'])
def test_bad_phase_cannot_dispatch_or_create_output(tmp_path,fault):
    cp=config(tmp_path,'SIMULATED' if fault=='mode' else 'ACTUAL');event=Event()
    if fault=='cancelled':event.set()
    with pytest.raises((ValueError,OSError,KeyError)):api().run('arbitrary_shell' if fault=='component' else 'investigation',cp,'f'*64 if fault=='pin' else file_hash(cp),cancel=event)
    assert set(p.name for p in tmp_path.iterdir())=={'phase.json'}


def test_sigterm_reaches_original_role_cancel_and_handlers_are_restored(tmp_path,monkeypatch):
    cp=config(tmp_path);module=api();monkeypatch.setattr(module,'_identity',lambda:None);before=signal.getsignal(signal.SIGTERM);seen=[]
    def execute(path,**kwargs):
        seen.append(kwargs);os.kill(os.getpid(),signal.SIGTERM)
        assert kwargs['cancel'].is_set() and kwargs['expected_config_sha256']==file_hash(cp)
        return dict(verified=False,closed_verified=True,new_attempts=0,new_unknown=0)
    monkeypatch.setattr('ops.pi.investigation_launcher.execute',execute)
    result=module.run('investigation',cp,file_hash(cp))
    assert result['status']=='failed' and result['model_requests']==0 and result['outcome']['new_attempts']==0 and len(seen)==1
    assert signal.getsignal(signal.SIGTERM)==before


def test_kernel_exception_restores_original_signal_handler(tmp_path,monkeypatch):
    cp=config(tmp_path);module=api();monkeypatch.setattr(module,'_identity',lambda:None);before=signal.getsignal(signal.SIGTERM)
    def execute(*args,**kwargs):raise RuntimeError('synthetic kernel failure')
    monkeypatch.setattr('ops.pi.investigation_launcher.execute',execute)
    with pytest.raises(RuntimeError):module.run('investigation',cp,file_hash(cp))
    assert signal.getsignal(signal.SIGTERM)==before


@pytest.mark.parametrize('component',['investigation','reproducer','sdk_review','manager_handoff'])
def test_verified_entry_only_routes_fixed_phase_components(tmp_path,monkeypatch,capsys,component):
    from ops.pi.tests.test_observer_entry import module
    import sys
    entry=module();(tmp_path/'vendor').mkdir();seen=[];old=list(sys.path)
    monkeypatch.setattr(entry,'verify_release',lambda *args:tmp_path/'code')
    monkeypatch.setattr(api(),'run',lambda *args:seen.append(args) or dict(status='done',model_requests=0))
    monkeypatch.setattr(sys,'argv',['entry.py','--component',component,'--config','/fixed/phase.json','--config-sha256','a'*64])
    monkeypatch.setattr(sys,'dont_write_bytecode',True)
    try:assert entry.main()==0
    finally:sys.path[:]=old
    assert seen==[(component,'/fixed/phase.json','a'*64)] and 'done' in capsys.readouterr().out
