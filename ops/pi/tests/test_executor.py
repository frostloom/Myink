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


@pytest.mark.parametrize('failure', ['stop_timeout', 'stop_oserror', 'probe_wait', 'stop_timeout_after_done', 'file_failure', 'ledger_failure', 'both_failure', 'done_file_failure', 'done_ledger_failure', 'done_ledger_correction_failure'])
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
    completed = failure in ('stop_timeout_after_done','done_file_failure','done_ledger_failure','done_ledger_correction_failure')
    if completed:
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
            if failure in ('stop_timeout','stop_timeout_after_done','file_failure','ledger_failure','both_failure'): raise subprocess.TimeoutExpired(args,10)
            if failure=='stop_oserror': raise OSError('probe cleanup unavailable')
        return SimpleNamespace(stdout=json.dumps({'lab_uuid':'lab-test','daemon_id':executor.DAEMON_ID,'kernel_proof':proof}),returncode=0)
    monkeypatch.setattr(executor.subprocess,'run',run)
    def sample():
        if completed: return 10**10
        raise OSError('primary sampler failure')
    monkeypatch.setattr(executor,'host_available_memory',sample)
    publications=[]
    from pathlib import Path
    original_write=Path.write_text
    def write(path,*args,**kw):
        if path.name.endswith('.receipt.json'):
            publications.append('file')
            if failure=='done_ledger_correction_failure' and publications.count('file')==2: raise OSError('correction unavailable')
            if failure in ('file_failure','both_failure','done_file_failure'): raise OSError('receipt unavailable')
        return original_write(path,*args,**kw)
    monkeypatch.setattr(Path,'write_text',write)
    def append(kind,payload):
        if kind=='tool_receipt':
            publications.append('ledger')
            if failure in ('ledger_failure','both_failure','done_ledger_failure','done_ledger_correction_failure'): raise RuntimeError('ledger unavailable')
    ledger.append_event=append
    escaped=None
    try:
        receipt=executor.execute('test',{'state_dir':'E:/state'},datetime.now(timezone.utc)+timedelta(seconds=30),ledger)
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        escaped=error
    assert escaped is None, 'cleanup exception bypassed remaining owned cleanup'
    assert probe.terminated
    if completed:
        assert receipt.status=='failed'
        assert receipt.evidence['reason']==('cleanup_unconfirmed' if failure=='stop_timeout_after_done' else 'publication_unconfirmed')
        if failure=='stop_timeout_after_done':
            saved=json.loads((tmp_path.parent/'evidence'/'completed-operation.receipt.json').read_text())
            assert saved['status']=='failed'
    else:
        assert heavy.killed
        assert [c for c in calls if 'stop-heavy' in c][0][-2:]==[receipt.operation_id,'lab-test']
        assert receipt.status=='blocked' and receipt.evidence['reason']=='lab_preflight_failed'
    if not completed or failure=='stop_timeout_after_done':
        assert receipt.evidence['cleanup_errors']
    if 'failure' in failure:
        assert publications==(['file','ledger','file'] if failure in ('ledger_failure','done_ledger_failure','done_ledger_correction_failure') else ['file','ledger'])
        if failure=='done_ledger_failure':
            saved=json.loads((tmp_path.parent/'evidence'/'completed-operation.receipt.json').read_text())
            assert saved['status']=='failed'
        if failure=='done_ledger_correction_failure':
            assert receipt.evidence['publication_errors'][-1]['step']=='receipt_file_correction'
        assert receipt.evidence['publication_errors']
        assert receipt.evidence['publication']['file']==(failure not in ('file_failure','both_failure','done_file_failure','done_ledger_correction_failure'))
        assert receipt.evidence['publication']['ledger']==(failure not in ('ledger_failure','both_failure','done_ledger_failure','done_ledger_correction_failure'))


def test_large_child_diagnostics_do_not_block_guardian(monkeypatch,tmp_path):
    import subprocess,sys
    from types import SimpleNamespace
    from ops.pi.resources import LIMITS
    proof={'cgroup_version':2,'membership_verified':True,'ancestor_verified':True,**LIMITS['heavy']}
    executor,ledger=_controller_fixture(monkeypatch,tmp_path,proof)
    real_popen=subprocess.Popen
    def launch(*args,**kwargs):
        return real_popen([sys.executable,'-c',"import os;os.write(1,b'O'*1048576);os.write(2,b'E'*1048576)"],**kwargs)
    monkeypatch.setattr(executor.subprocess,'Popen',launch)
    monkeypatch.setattr(executor,'host_available_memory',lambda:2**30)
    receipt=executor.execute('test',{'state_dir':'E:/state','selection':'b8-red'},datetime.now(timezone.utc)+timedelta(seconds=2),ledger)
    assert receipt.evidence['returncode']==0,receipt
    assert (tmp_path/(receipt.operation_id+'.stdout')).read_bytes()==b'O'*1048576
    assert (tmp_path/(receipt.operation_id+'.stderr')).read_bytes()==b'E'*1048576


def test_child_diagnostics_truncate_without_stopping_pipe_drain(tmp_path):
    import subprocess,sys
    from ops.pi.executor import _Diagnostics
    child=subprocess.Popen([sys.executable,'-c',"import os;os.write(1,b'O'*8388608);os.write(2,b'E'*8388608)"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    diagnostics=_Diagnostics(child,tmp_path,'bounded')
    assert child.wait(timeout=5)==0
    diagnostics.finish()
    assert set(diagnostics.truncated)=={'stdout','stderr'}
    assert (tmp_path/'bounded.stdout').stat().st_size==4194304
    assert (tmp_path/'bounded.stderr').stat().st_size==4194304


@pytest.mark.parametrize('guarded,expected',[(False,'-mp-'),(True,'-pi-synthetic-')])
def test_business_fixture_prefix_preserves_only_guarded_override(monkeypatch,guarded,expected):
    import os
    from pathlib import Path
    monkeypatch.setenv('QUEUE_PREFIX','-pi-synthetic-')
    if guarded:monkeypatch.setenv('PI_LAB_ENV','synthetic-guard')
    else:monkeypatch.delenv('PI_LAB_ENV',raising=False)
    prefix=(Path(__file__).parents[3]/'tests/conftest.py').read_text(encoding='utf-8').split('\nimport uuid',1)[0]
    exec(compile(prefix,'tests/conftest.py','exec'),{})
    assert os.environ['QUEUE_PREFIX']==expected


@pytest.mark.parametrize('fault',['memory.max','memory.swap.max','cpu.max','membership_verified','ancestor_verified'])
def test_runtime_rejects_infra_parent_limit_or_membership_drift(monkeypatch,tmp_path,fault):
    import json
    from types import SimpleNamespace
    from ops.pi.lab import verify
    from ops.pi import resources
    # Drive the existing full verifier to acceptance with otherwise valid proof.
    # Only the parent kernel accounting field is changed; no kernel mutation.
    class TrustedPath:
        def __init__(self,path):self.path=path
        def __truediv__(self,name):return TrustedPath(self.path/name)
        def read_text(self):return self.path.read_text()
        def is_symlink(self):return False
        def stat(self):return SimpleNamespace(st_uid=0,st_mode=0o100600)
    identity={'daemon_id':verify.DAEMON,'lab_uuid':'owned','project':'project','test_containers':[],'sandbox':'agent','gateway':'gateway'}
    candidate={'user':'65534:65534','host':{'ReadonlyRootfs':True,'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges'],'Dns':['127.0.0.1']},'networks':{'project-agent':'172.29.220.10'}}
    (tmp_path/'lab-env.json').write_text(json.dumps(identity))
    (tmp_path/'runtime-manifest.json').write_text(json.dumps({'lab_uuid':'owned','containers':{'agent':candidate,'gateway':{},'project-denied':{}}}))
    monkeypatch.setattr(verify,'BASE',TrustedPath(tmp_path))
    monkeypatch.setattr(verify,'verify_container',lambda *args:None)
    monkeypatch.setattr(verify,'verify_firewall',lambda:None)
    def docker(*args):
        if args[0]=='info':return {'ID':verify.DAEMON,'CgroupVersion':'2','CgroupDriver':'systemd','DockerRootDir':'/var/lib/docker'}
        if args[0]=='inspect':return [{}]
        suffix=args[2].removeprefix('project-')
        return [{'Labels':{'myink.pi.lab':'owned'},'Internal':suffix=='agent','EnableIPv6':False,'Options':{'com.docker.network.bridge.name':'pi-lab-'+suffix}}]
    monkeypatch.setattr(verify,'_docker',docker)
    proof={'memory.max':str(768*1024**2),'memory.swap.max':'0','cpu.max':'100000 100000','membership_verified':True,'ancestor_verified':True}
    proof[fault]=False if fault.endswith('verified') else 'unlimited'
    monkeypatch.setattr(resources,'sample_resources',lambda group:proof if group=='infra' else {})
    monkeypatch.setattr(resources,'verify_limits',lambda *args:True)
    with pytest.raises(ValueError,match='infra parent'):
        verify.verify_runtime()
