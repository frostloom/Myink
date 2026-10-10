from ops.pi.resources import MemoryWatchdog, verify_limits

def test_low_memory_for_ten_seconds_stops_heavy_work():
    watch = MemoryWatchdog()
    assert watch.observe(511 * 1024**2, 0) is False
    assert watch.observe(511 * 1024**2, 9.9) is False
    assert watch.observe(511 * 1024**2, 10) is True

def test_memory_recovery_resets_continuous_window():
    watch = MemoryWatchdog()
    watch.observe(1, 0)
    assert watch.observe(512 * 1024**2, 9) is False
    assert watch.observe(1, 10) is False
    assert watch.observe(1, 19) is False

def test_kernel_limit_proof_required():
    assert verify_limits({}, 'heavy') is False
from pathlib import Path
import os
import subprocess
import sys
import pytest

# Real PowerShell behavior on Windows; Linux's final scope suite excludes these host probes.
@pytest.mark.pi_lab
def test_windows_installer_caller_hash_cannot_authorize_rootfs(tmp_path):
    assert sys.platform=='win32', 'Windows installer acceptance must run on Windows host'
    fake=Path('E:/tools/myink-pi/cache/b7-fake-rootfs.wsl')
    fake.write_bytes(b'not an official image')
    try:
        import hashlib
        caller_hash=hashlib.sha256(fake.read_bytes()).hexdigest()
        script=Path(__file__).parents[1]/'lab/install.ps1'
        result=subprocess.run(['powershell.exe','-NoProfile','-File',str(script),'-Root','E:/tools/myink-pi','-Rootfs',str(fake),'-Sha256',caller_hash,'-VerifyOnly'],capture_output=True)
        assert result.returncode==1
        assert b'official rootfs integrity mismatch' in result.stdout
    finally:
        fake.unlink()

@pytest.mark.pi_lab
def test_windows_actual_watchdog_kills_only_whole_heavy_group(monkeypatch):
    assert sys.platform=='win32', 'Windows host watchdog acceptance runs on Windows'
    from datetime import datetime,timezone,timedelta
    import json,time
    from ops.pi import executor
    from ops.pi.ledger import Ledger
    state=Path('E:/tools/myink-pi/state')
    monkeypatch.setattr(executor,'host_available_memory',lambda:1)
    start=time.monotonic()
    receipt=executor.execute('probe',{'state_dir':str(state),'selection':'watchdog'},datetime.now(timezone.utc)+timedelta(seconds=120),Ledger(state/'b7-watchdog.sqlite'))
    assert receipt.status=='failed' and receipt.evidence['reason']=='host_low_memory'
    assert receipt.evidence['termination_proof']['heavy_empty'] is True
    assert time.monotonic()-start>=10
    identity=json.loads((state/'lab-env.json').read_text())
    command=['wsl.exe','-d','MyinkPiLab','-u','root','--','docker','inspect',identity['sandbox'],identity['gateway']]
    result=subprocess.run(command,capture_output=True,check=True)
    assert all(item['State']['Running'] for item in json.loads(result.stdout))
    (Path('E:/tools/myink-pi/evidence')/'b7-watchdog-actual.json').write_text(json.dumps(receipt.evidence,indent=2))


@pytest.mark.pi_lab
def test_windows_installer_refuses_existing_distribution():
    assert sys.platform=='win32'
    import shutil
    script=Path(__file__).parents[1]/'lab/preflight.ps1'
    result=subprocess.run([shutil.which('pwsh.exe') or 'powershell.exe','-NoProfile','-File',str(script),'-Root','E:/tools/myink-pi'],capture_output=True)
    assert result.returncode==1
    assert b'distribution collision' in result.stdout

def test_guest_sampler_uses_available_not_free_memory(tmp_path):
    from ops.pi.resources import _guest_available_memory
    meminfo=tmp_path/'meminfo'
    meminfo.write_text('MemFree: 1 kB\nMemAvailable: 4096 kB\n')
    assert _guest_available_memory(meminfo)==4194304


def _kernel_sample_fixture(monkeypatch,mode):
    from ops.pi import resources
    from pathlib import Path
    state={'attempts':0,'limits':[]}
    def read(path,*args,**kwargs):
        name=str(path).replace('\\','/')
        if name.endswith('/memory.max'):
            state['attempts']+=1;state['limits'].append(state['attempts'])
            return str((384 if mode=='drift' else 1536)*1024**2)
        if name.endswith('/cgroup.procs'):return '' if mode=='empty' else '101 102'
        if name.startswith('/proc/'):
            if '/101/' in name and (mode=='churn' or mode=='transient' and state['attempts']==1):
                raise FileNotFoundError(2,'vanished',name)
            if '/101/' in name and mode=='permission':raise PermissionError(name)
            return '0::/foreign' if mode=='foreign' else '0::/myinkpi.slice/myinkpi-heavy.slice/owned'
        if name.endswith('/memory.swap.max'):return str(256*1024**2)
        if name.endswith('/cpu.max'):return '200000 100000'
        return '0'
    monkeypatch.setattr(Path,'read_text',read)
    monkeypatch.setattr(Path,'is_dir',lambda p:True)
    monkeypatch.setattr(Path,'is_file',lambda p:True)
    monkeypatch.setattr(Path,'rglob',lambda p,pattern:[p/'owned/cgroup.procs'])
    return resources,state


def test_transient_pid_requires_complete_fresh_resampling(monkeypatch):
    resources,state=_kernel_sample_fixture(monkeypatch,'transient')
    result=None
    try:result=resources.sample_resources('heavy')
    except FileNotFoundError:pass
    assert result is not None, 'vanished sample must be discarded and wholly resampled'
    assert state['limits']==[1,2] and result['sample_attempts']==2
    assert result['vanished_pids']==[{'attempt':1,'pid':101}]
    assert resources.verify_limits(result,'heavy')


@pytest.mark.parametrize('mode',['foreign','empty','drift'])
def test_live_foreign_pid_never_retries_or_authorizes(monkeypatch,mode):
    resources,state=_kernel_sample_fixture(monkeypatch,mode)
    result=resources.sample_resources('heavy')
    assert not resources.verify_limits(result,'heavy') and state['attempts']==1


def test_pid_churn_exhaustion_never_returns_partial_proof(monkeypatch):
    resources,state=_kernel_sample_fixture(monkeypatch,'churn')
    rejected=False
    try:resources.sample_resources('heavy')
    except (ValueError,FileNotFoundError):rejected=True
    assert rejected and state['limits']==[1,2,3], 'exactly three complete samples then fail closed'


def test_pid_permission_error_never_retries(monkeypatch):
    resources,state=_kernel_sample_fixture(monkeypatch,'permission')
    with pytest.raises(PermissionError):resources.sample_resources('heavy')
    assert state['attempts']==1
