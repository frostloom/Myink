"""Single-scan service ticks leave the shared lock available while idle."""
from configparser import ConfigParser
from pathlib import Path
import fcntl,shlex,time
from ops.pi import manager
from ops.pi.development_inputs import ledger_snapshot
from ops.pi.tests.test_manager import queue,entry,pack,config_file,result,request_for,publish

DEPLOY=Path(__file__).parents[1]/'deploy'


def unit(name):
    value=ConfigParser(interpolation=None,strict=False);value.optionxform=str
    with (DEPLOY/name).open() as stream:value.read_file(stream)
    return value


def test_manager_service_scans_once_without_waiting_under_shared_lock():
    service=unit('myink-pi-manager.service')['Service'];args=shlex.split(service['ExecStart'])
    assert args[args.index('--component')+1]=='manager' and args[args.index('/usr/bin/python3')+1:args.index('/usr/bin/python3')+4]==['-I','-S','-B']
    # The closed host fixes idle0/max1/2100; functional argument coverage is in test_manager_host.
    assert args[:3]==['/usr/bin/flock','--nonblock','--no-fork'] and args[3].endswith('/control/maintenance.lock')
    assert service['RuntimeMaxSec']=='2400' and service['Restart']=='no' and service['NoNewPrivileges']=='yes'
    assert service['User']=='ubuntu' and service['SupplementaryGroups']=='docker'
    assert unit('myink-pi-manager.timer')['Timer']['OnUnitInactiveSec']=='60'


def test_zero_idle_scans_empty_inbox_once_then_releases_manager_lock_without_fee(queue,monkeypatch):
    state,billing,p,*_=queue;folder=p.parent/'inbox';folder.mkdir(mode=0o700);before=ledger_snapshot(billing);calls=[]
    original=manager._ingest
    def ingest(*args):calls.append(1);return original(*args)
    monkeypatch.setattr(manager,'_ingest',ingest);started=time.monotonic()
    report=manager.run(state,billing,max_tasks=1,seconds=5,inbox=folder,idle_seconds=0,mode='SIMULATED',executor=result)
    assert time.monotonic()-started<2 and report['dispatched']==0 and report['reason']=='idle' and calls==[1]
    assert ledger_snapshot(billing)==before
    # External maintenance.lock belongs to the service; live acceptance covers it.
    with state.with_suffix('.manager.lock').open('rb') as stream:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)


def test_zero_idle_still_admits_approved_ready_inbox_once(queue):
    state,billing,p,*_=queue;folder=p.parent/'inbox';request=request_for(queue,'ready');publish(folder,request,'ready');before=ledger_snapshot(billing);calls=[]
    def execute(*args,**kwargs):calls.append(1);return result(*args,**kwargs)
    report=manager.run(state,billing,max_tasks=1,seconds=2100,inbox=folder,idle_seconds=0,mode='SIMULATED',executor=execute)
    assert report['dispatched']==1 and report['tasks']==['ready'] and calls==[1] and ledger_snapshot(billing)==before
    again=manager.run(state,billing,max_tasks=1,seconds=2100,inbox=folder,idle_seconds=0,mode='SIMULATED',executor=execute)
    assert again['dispatched']==0 and calls==[1]
