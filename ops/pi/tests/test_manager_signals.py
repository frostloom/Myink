"""Real OS stop signals on empty synthetic ACTUAL queues; no model transport."""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import pytest
from ops.pi import manager
from ops.pi.ledger import Ledger
from ops.pi.development_inputs import ledger_snapshot


@pytest.mark.parametrize('stop_signal',[signal.SIGTERM,signal.SIGINT])
def test_cli_stop_cancels_and_persists_without_fee_effect(tmp_path,stop_signal):
    tmp_path.chmod(0o700);billing=tmp_path/'billing.sqlite'
    Ledger(billing);billing.chmod(0o600)
    state=tmp_path/'manager.sqlite';manager.init(state,billing)
    inbox=tmp_path/'inbox';inbox.mkdir(mode=0o700);before=ledger_snapshot(billing)
    env=dict(os.environ,PYTHONPATH=str(Path.cwd()),PYTHONDONTWRITEBYTECODE='1')
    process=subprocess.Popen([sys.executable,'-m','ops.pi.manager','--state',str(state),'--billing',str(billing),
        'run','--seconds','600','--max-tasks','1','--inbox',str(inbox),'--idle-seconds','600'],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
    try:
        until=time.monotonic()+10;locked=False
        while time.monotonic()<until:
            assert process.poll() is None,'manager exited before signal'
            target=state.with_suffix('.manager.lock')
            if target.exists():
                with target.open('rb') as stream:
                    try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:locked=True
                if locked:break
            time.sleep(.02)
        assert locked,'live manager did not acquire its lock'
        process.send_signal(stop_signal)
        out,err=process.communicate(timeout=10)
        assert process.returncode==1,(process.returncode,out,err)
        value=json.loads(out)
        assert value['status']=='blocked' and value['reason']=='cancelled' and value['dispatched']==0
        assert 'Traceback' not in err and ledger_snapshot(billing)==before
        status=manager.status(state,billing)
        assert status['metrics']['recorded_runs']==1 and status['runs'][-1]['reason']=='cancelled'
    finally:
        if process.poll() is None:process.kill();process.communicate(timeout=5)


@pytest.mark.parametrize('failure',[False,True])
def test_run_cli_restores_handlers_after_return_or_refusal(monkeypatch,capsys,failure):
    previous={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
    def run(*args,**kwargs):
        cancel=kwargs['cancel']
        handler=signal.getsignal(signal.SIGTERM)
        assert handler is not previous[signal.SIGTERM]
        handler(signal.SIGTERM,None);assert cancel.is_set()
        if failure:raise ValueError('synthetic refusal')
        return dict(status='blocked',reason='cancelled',dispatched=0)
    monkeypatch.setattr(manager,'run',run)
    monkeypatch.setattr(sys,'argv',['manager','--state','/unused/state.sqlite','--billing','/unused/billing.sqlite','run'])
    try:
        assert manager.main()==1
        value=json.loads(capsys.readouterr().out)
        assert value.get('reason')=='cancelled' if not failure else value['error_class']=='ValueError'
        assert all(signal.getsignal(sig) is handler for sig,handler in previous.items())
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)
