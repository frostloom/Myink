import signal
from threading import Thread

import pytest

from ops.pi.analysis_lifecycle import Lifecycle, signal_scope


def test_wall_rollback_never_extends_execution(monkeypatch):
    from ops.pi import analysis_lifecycle as m
    clock=[100., 10.]
    monkeypatch.setattr(m.time, 'time', lambda: clock[0])
    monkeypatch.setattr(m.time, 'monotonic', lambda: clock[1])
    life=Lifecycle(200.)
    clock[:]=[50., 40.]
    assert life.remaining()==70
    clock[:]=[201., 41.]
    with pytest.raises(TimeoutError): life.check()
    assert life.reason=='deadline_exceeded'


def test_cleanup_has_one_shared_budget_and_first_reason(monkeypatch):
    from ops.pi import analysis_lifecycle as m
    clock=[100., 10.]
    monkeypatch.setattr(m.time, 'time', lambda: clock[0])
    monkeypatch.setattr(m.time, 'monotonic', lambda: clock[1])
    life=Lifecycle(200.)
    life.stop('interrupted');life.begin_cleanup()
    clock[:]=[101., 110.]
    life.stop('cleanup_failed');life.begin_cleanup()
    assert life.reason=='interrupted' and life.cleanup_remaining()==20
    clock[:]=[20., 131.]
    with pytest.raises(TimeoutError): life.cleanup_remaining()


def test_signals_restored_and_only_main_thread():
    before={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
    life=Lifecycle(__import__('time').time()+300)
    with signal_scope(life):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
        signal.getsignal(signal.SIGINT)(signal.SIGINT,None)
        assert life.reason=='interrupted' and life.cancel.is_set()
    assert all(signal.getsignal(s)==h for s,h in before.items())
    errors=[]
    def worker():
        try:
            with signal_scope(life): pass
        except BaseException as e: errors.append(e)
    t=Thread(target=worker);t.start();t.join(1)
    assert not errors and not t.is_alive()


def test_stdio_exchange_observes_cancel_before_deadline():
    import subprocess
    import sys
    from threading import Event
    from ops.pi.container_runtime import exchange
    process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(2)'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    cancel=Event();cancel.set()
    try:
        with pytest.raises(TimeoutError):exchange(process,{},lambda *_: None,seconds=2,cancel=cancel)
    finally:
        process.kill();process.wait(timeout=1);process.stdin.close();process.stdout.close()


def test_signal_does_not_acquire_event_condition_lock():
    import subprocess
    import sys
    script='''import os,signal,time
from ops.pi.analysis_lifecycle import Lifecycle,signal_scope
life=Lifecycle(time.time()+300)
with signal_scope(life):
 with life.cancel._cond:
  os.kill(os.getpid(),signal.SIGTERM)
 assert life.reason=='interrupted' and life.cancel.is_set()
'''
    subprocess.run([sys.executable,'-c',script],timeout=2,check=True)


def test_finish_guard_rolls_back_if_stop_arrives_during_terminal_write(tmp_path,monkeypatch):
    from ops.pi.container_runtime import synthetic_run
    import time
    run,_,slots,*_=synthetic_run(tmp_path/'guard-run')
    assert run.guard(0)(slots[0]['request'])
    life=Lifecycle(time.time()+300)
    finish=run._finish
    def write_then_stop(db,operation_id,status,evidence):
        finish(db,operation_id,status,evidence);life.stop('interrupted')
    monkeypatch.setattr(run,'_finish',write_then_stop)
    with pytest.raises(TimeoutError):run.finish(0,status='done',check=life.check)
    assert run.snapshot()[0]['status']=='UNCERTAIN'


def test_pending_attempt_never_counts_as_settled(tmp_path):
    from types import SimpleNamespace
    from ops.pi.ledger import Ledger
    from ops.pi.analysis_trial_lifecycle import _settled
    ledger=Ledger(tmp_path/'pending.sqlite')
    run=SimpleNamespace(ledger=ledger,_identity={'run_id':'test-run'})
    assert _settled(run) is True
    ledger.intent('pending-attempt','model-attempt',{'analysis_run_id':'test-run'})
    assert _settled(run) is False


def test_server_shutdown_wait_obeys_shared_cleanup_budget():
    from threading import Event, Thread
    import time
    life=Lifecycle(time.time()+300);life.begin_cleanup()
    life._cleanup_end=time.monotonic()+.04
    release=Event();running=Event()
    class Server:
        def shutdown(self):running.set();release.wait(2)
    server_thread=Thread(target=lambda:None);server_thread.start();server_thread.join()
    try:
        started=time.monotonic()
        with pytest.raises(TimeoutError):life.shutdown_server(Server(),server_thread)
        assert time.monotonic()-started < .5
        assert running.is_set()
    finally:release.set()
