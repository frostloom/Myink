from datetime import datetime, timezone, timedelta
import pytest
from ops.pi.executor import execute, safe_source, sandbox_environment, validate_daemon

def test_unknown_command_rejected():
    assert execute('shell', {'command': 'echo unsafe'}, datetime.now(timezone.utc) + timedelta(seconds=30), None).status == 'blocked'

@pytest.mark.parametrize('path', ['../secret', '/secret'])
def test_path_escape_and_symlink_rejected(tmp_path, path):
    with pytest.raises(ValueError):
        safe_source(tmp_path, path)

def test_symlink_rejected(tmp_path):
    link = tmp_path / 'link'
    try:
        link.symlink_to(tmp_path.parent, target_is_directory=True)
    except OSError:
        import subprocess
        subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(tmp_path.parent)], check=True, capture_output=True)
    with pytest.raises(ValueError):
        safe_source(tmp_path, 'link/secret')

def test_secret_env_not_inherited():
    assert 'PLATFORM_MODEL_API_KEY' not in sandbox_environment({'PLATFORM_MODEL_API_KEY': 'never-forward', 'EMBED_ENABLED': '0'})

def test_foreign_docker_target_rejected():
    assert validate_daemon('private-daemon', {'ID': 'foreign-daemon', 'CgroupVersion': '2', 'CgroupDriver': 'systemd'}) is False

def _controller_fixture(monkeypatch, tmp_path, proof):
    import json
    from types import SimpleNamespace
    from ops.pi import executor
    identity = {'lab_uuid': 'lab-test', 'daemon_id': executor.DAEMON_ID, 'distribution': 'MyinkPiLab'}
    (tmp_path.parent/'evidence').mkdir(exist_ok=True)
    (tmp_path/'lab-env.json').write_text(json.dumps(identity))
    class State:
        drive = 'E:'
        parts = ('E:', 'state')
        parent = tmp_path.parent
        def is_absolute(self): return True
        def __truediv__(self, name): return tmp_path/name
    monkeypatch.setattr(executor, 'Path', lambda _: State())
    monkeypatch.setattr(executor.sys, 'platform', 'win32')
    monkeypatch.setattr(executor.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=json.dumps({**identity, 'kernel_proof': proof}), returncode=0))
    return executor, SimpleNamespace(append_event=lambda *a: None)


def test_missing_cgroup_proof_blocks_execution(monkeypatch, tmp_path):
    executor, ledger = _controller_fixture(monkeypatch, tmp_path, {})
    receipt = executor.execute('test', {'state_dir': 'E:/state'}, datetime.now(timezone.utc)+timedelta(seconds=30), ledger)
    assert receipt.evidence['reason'] == 'missing_cgroup_proof'


def test_short_phase_deadline_bounds_preflight(monkeypatch, tmp_path):
    executor, ledger = _controller_fixture(monkeypatch, tmp_path, {})
    def delayed_preflight(*args, **kwargs):
        import subprocess
        assert kwargs['timeout'] <= .25
        raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])
    monkeypatch.setattr(executor.subprocess, 'run', delayed_preflight)
    receipt = executor.execute('test', {'state_dir': 'E:/state'}, datetime.now(timezone.utc)+timedelta(seconds=.25), ledger)
    assert receipt.evidence['reason'] == 'deadline_expired'


def test_host_cancel_passes_immutable_operation_and_lab(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace
    from ops.pi.resources import LIMITS
    proof={'cgroup_version':2,'membership_verified':True,'ancestor_verified':True,**LIMITS['heavy']}
    executor,ledger=_controller_fixture(monkeypatch,tmp_path,proof)
    identity={'lab_uuid':'lab-test','daemon_id':executor.DAEMON_ID,'distribution':'MyinkPiLab','kernel_proof':proof}
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(identity if args[-1]=='preflight' else {'heavy_empty':True,'status':'done'}),returncode=0)
    class Process:
        returncode=None
        def poll(self): return self.returncode
        def kill(self): self.returncode=137
        def communicate(self,**kw): return b'',b''
    monkeypatch.setattr(executor.subprocess,'run',run)
    monkeypatch.setattr(executor.subprocess,'Popen',lambda *a,**kw: Process())
    monkeypatch.setattr(executor,'host_available_memory',lambda:1)
    monkeypatch.setattr(executor,'MemoryWatchdog',lambda:SimpleNamespace(observe=lambda *a:True))
    receipt=executor.execute('probe',{'state_dir':'E:/state','selection':'watchdog'},datetime.now(timezone.utc)+timedelta(seconds=30),ledger)
    assert receipt.evidence['reason']=='host_low_memory'
    cancellation=[c for c in calls if 'stop-heavy' in c][0]
    assert cancellation[-2:]==[receipt.operation_id,'lab-test']


def test_expired_host_probe_poll_cleans_only_its_own_process(monkeypatch,tmp_path):
    import time
    from ops.pi.resources import LIMITS
    proof={'cgroup_version':2,'membership_verified':True,'ancestor_verified':True,**LIMITS['heavy']}
    executor,ledger=_controller_fixture(monkeypatch,tmp_path,proof)
    class Probe:
        pid=7654321
        terminated=False
        def poll(self): return None
        def terminate(self): self.terminated=True
        def wait(self,**kwargs): return 0
    probe=Probe()
    monkeypatch.setattr(executor.subprocess,'CREATE_NO_WINDOW',0,raising=False)
    monkeypatch.setattr(executor.subprocess,'Popen',lambda *a,**kw:probe)
    started=time.monotonic()
    receipt=executor.execute('test',{'state_dir':'E:/state'},datetime.now(timezone.utc)+timedelta(seconds=.03),ledger)
    assert receipt.evidence['reason']=='deadline_expired'
    assert probe.terminated and time.monotonic()-started<.3


def test_sampler_failure_finally_uses_owned_cancellation(monkeypatch,tmp_path):
    import json
    from types import SimpleNamespace
    from ops.pi.resources import LIMITS
    proof={'cgroup_version':2,'membership_verified':True,'ancestor_verified':True,**LIMITS['heavy']}
    executor,ledger=_controller_fixture(monkeypatch,tmp_path,proof)
    calls=[]
    def run(args,**kw):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps({'lab_uuid':'lab-test','daemon_id':executor.DAEMON_ID,'kernel_proof':proof}),returncode=0)
    class Process:
        returncode=None
        def poll(self): return self.returncode
        def kill(self): self.returncode=137
        def communicate(self,**kw): return b'',b''
    monkeypatch.setattr(executor.subprocess,'run',run)
    monkeypatch.setattr(executor.subprocess,'Popen',lambda *a,**kw:Process())
    def failed_sample(): raise OSError('controlled sampler failure')
    monkeypatch.setattr(executor,'host_available_memory',failed_sample)
    receipt=executor.execute('probe',{'state_dir':'E:/state','selection':'watchdog'},datetime.now(timezone.utc)+timedelta(seconds=30),ledger)
    assert receipt.status=='blocked'
    assert [c for c in calls if 'stop-heavy' in c][0][-2:]==[receipt.operation_id,'lab-test']


@pytest.mark.parametrize('failure', ['stop_timeout', 'stop_oserror', 'probe_wait', 'stop_timeout_after_done'])
def test_failed_probe_cleanup_still_cancels_owned_heavy(monkeypatch, tmp_path, failure):
    import json
    import subprocess
    from types import SimpleNamespace
    from ops.pi.resources import LIMITS
    proof={'cgroup_version':2,'membership_verified':True,'ancestor_verified':True,**LIMITS['heavy']}
    executor,ledger=_controller_fixture(monkeypatch,tmp_path,proof)
    calls=[]
    class Process:
        pid=12345
        returncode=None
        terminated=False
        killed=False
        def poll(self): return self.returncode
        def terminate(self): self.terminated=True
        def wait(self, **kw):
            if failure=='probe_wait': raise subprocess.TimeoutExpired('probe',2)
            self.returncode=0
        def kill(self): self.killed=True; self.returncode=137
        def communicate(self, **kw): return b'',b''
    probe,heavy=Process(),Process()
    if failure=='stop_timeout_after_done':
        heavy.returncode=0
        monkeypatch.setattr(executor.uuid,'uuid4',lambda:'completed-operation')
        (tmp_path.parent/'evidence'/'completed-operation.guest.json').write_text(json.dumps({'operation_id':'completed-operation','lab_uuid':'lab-test','status':'done'}))
    (tmp_path.parent/'evidence'/'b7-host-server.json').write_text(json.dumps({'pid':probe.pid}))
    processes=iter([probe,heavy])
    monkeypatch.setattr(executor.subprocess,'CREATE_NO_WINDOW',0,raising=False)
    monkeypatch.setattr(executor.subprocess,'Popen',lambda *a,**kw:next(processes))
    def run(args,**kw):
        calls.append(args)
        if 'stop-probes' in args:
            if failure in ('stop_timeout','stop_timeout_after_done'): raise subprocess.TimeoutExpired(args,10)
            if failure=='stop_oserror': raise OSError('probe cleanup unavailable')
        return SimpleNamespace(stdout=json.dumps({'lab_uuid':'lab-test','daemon_id':executor.DAEMON_ID,'kernel_proof':proof}),returncode=0)
    monkeypatch.setattr(executor.subprocess,'run',run)
    def sample():
        if failure=='stop_timeout_after_done': return 10**10
        raise OSError('primary sampler failure')
    monkeypatch.setattr(executor,'host_available_memory',sample)
    escaped=None
    try:
        receipt=executor.execute('test',{'state_dir':'E:/state'},datetime.now(timezone.utc)+timedelta(seconds=30),ledger)
    except (OSError, subprocess.SubprocessError) as error:
        escaped=error
    assert escaped is None, 'cleanup exception bypassed remaining owned cleanup'
    assert probe.terminated
    if failure=='stop_timeout_after_done':
        assert receipt.status=='failed' and receipt.evidence['reason']=='cleanup_unconfirmed'
        saved=json.loads((tmp_path.parent/'evidence'/'completed-operation.receipt.json').read_text())
        assert saved['status']=='failed'
    else:
        assert heavy.killed
        assert [c for c in calls if 'stop-heavy' in c][0][-2:]==[receipt.operation_id,'lab-test']
        assert receipt.status=='blocked' and receipt.evidence['reason']=='lab_preflight_failed'
    assert receipt.evidence['cleanup_errors']
