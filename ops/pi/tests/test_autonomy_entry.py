"""Verified entry routes a root coordinator and a separate ordinary manager."""
import importlib,os,signal,sys
from pathlib import Path
import pytest
from ops.pi.tests.test_observer_entry import module


@pytest.mark.parametrize('component,target,function',[('autonomy','ops.pi.autonomy_coordinator','serve'),('manager','ops.pi.manager_host','run')])
def test_closed_entry_routes_only_fixed_host_components(tmp_path,monkeypatch,capsys,component,target,function):
    entry=module();(tmp_path/'vendor').mkdir();seen=[];old=list(sys.path);monkeypatch.setattr(entry,'verify_release',lambda *a:tmp_path/'code')
    host=importlib.import_module(target);monkeypatch.setattr(host,function,lambda *a:seen.append(a) or dict(status='done',model_requests=0))
    monkeypatch.setattr(sys,'argv',['entry.py','--component',component,'--config','/fixed/config.json','--config-sha256','a'*64]);monkeypatch.setattr(sys,'dont_write_bytecode',True)
    try:assert entry.main()==0
    finally:sys.path[:]=old
    assert seen==[('/fixed/config.json','a'*64)]


def test_parent_service_sigterm_sets_event_before_return_and_restores_handler(monkeypatch):
    host=importlib.import_module('ops.pi.autonomy_coordinator');before=signal.getsignal(signal.SIGTERM);seen=[]
    def run(*args,**kwargs):os.kill(os.getpid(),signal.SIGTERM);seen.append(kwargs['cancel'].is_set());return dict(status='cancelled',model_requests=0)
    monkeypatch.setattr(host,'run',run);assert host.serve('/fixed/config','a'*64)['status']=='cancelled' and seen==[True] and signal.getsignal(signal.SIGTERM)==before


def test_root_coordinator_and_ordinary_manager_units_preserve_boundaries():
    deploy=Path('ops/pi/deploy');parent=(deploy/'myink-pi-autonomy.service').read_text();child=(deploy/'myink-pi-manager.service').read_text()
    assert 'User=root' in parent and '--component autonomy' in parent and 'NoNewPrivileges=yes' in parent
    assert '/usr/bin/flock' not in parent and 'KillMode=mixed' in parent
    assert 'User=ubuntu' in child and '--component manager' in child and '-I -S -B' in child and '/control/maintenance.lock' in child
    assert 'OnUnitInactiveSec=15min' in (deploy/'myink-pi-autonomy.timer').read_text()
