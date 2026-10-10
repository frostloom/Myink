"""Kernel resource evidence and the Windows host memory watchdog."""
import ctypes
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import shutil
import sys
import uuid

from .contracts import Receipt

LIMITS = {
    'agent': {'memory.max': 384 * 1024**2, 'memory.swap.max': 0, 'cpu.max': '50000 100000'},
    'heavy': {'memory.max': 1536 * 1024**2, 'memory.swap.max': 256 * 1024**2, 'cpu.max': '200000 100000'},
}

class MemoryWatchdog:
    def __init__(self):
        self.low_since = None

    def observe(self, available, now):
        if available >= 512 * 1024**2:
            self.low_since = None
        elif self.low_since is None:
            self.low_since = now
        return self.low_since is not None and now - self.low_since >= 10


def host_available_memory():
    """Only the real Windows host metric can authorize heavy WSL work."""
    if sys.platform != 'win32':
        raise RuntimeError('Windows host sampler required')
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in
            ('total_phys', 'available_phys', 'total_page', 'available_page', 'total_virtual', 'available_virtual', 'extended')]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError('host memory sampler failed')
    return status.available_phys


def verify_limits(proof, group):
    expected = LIMITS.get(group)
    return bool(expected and proof.get('cgroup_version') == 2
                and all(str(proof.get(k)) == str(v) for k, v in expected.items())
                and proof.get('membership_verified') is True
                and proof.get('ancestor_verified') is True)


def sample_resources(target_id):
    if target_id not in ('agent', 'heavy', 'infra'):
        raise ValueError('unknown resource group')
    root = Path('/sys/fs/cgroup/myinkpi.slice') / f'myinkpi-{target_id}.slice'
    if not root.is_dir():
        raise ValueError('missing cgroup')
    result = {'target_id': target_id, 'cgroup_version': 2, 'path': str(root)}
    for key in ('memory.max', 'memory.swap.max', 'memory.current', 'memory.peak', 'cpu.max', 'cpu.stat', 'memory.events'):
        result[key] = (root / key).read_text().strip()
    pids = sorted({int(p) for path in root.rglob('cgroup.procs') for p in path.read_text().split()})
    result['pids'] = pids
    result['membership_verified'] = bool(pids) and all(
        f'/myinkpi.slice/myinkpi-{target_id}.slice/' in Path(f'/proc/{p}/cgroup').read_text()
        or Path(f'/proc/{p}/cgroup').read_text().strip().endswith(f'/myinkpi.slice/myinkpi-{target_id}.slice')
        for p in pids)
    # No hidden tighter/looser ancestor or non-v2 delegation is accepted.
    result['ancestor_verified'] = (Path('/sys/fs/cgroup/cgroup.controllers').is_file()
                                  and root.parent.name == 'myinkpi.slice')
    return result


def probe_environment(root):
    operation = str(uuid.uuid4())
    try:
        path = Path(root)
        if sys.platform != 'win32' or path.drive.lower() != 'e:' or not path.is_absolute() or '..' in path.parts:
            raise ValueError('explicit E drive lab root required')
        script = Path(__file__).parent / 'lab' / 'preflight.ps1'
        completed = subprocess.run([shutil.which('pwsh.exe') or 'powershell.exe', '-NoProfile', '-File', str(script), '-Root', str(path), '-AdoptPrepared'],
                                   capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120, check=False)
        evidence = json.loads(completed.stdout)
        return Receipt(operation, 'done' if completed.returncode == 0 else 'blocked', evidence)
    except (ValueError, OSError, subprocess.SubprocessError):
        return Receipt(operation, 'blocked', {'reason': 'preflight_failed'})

def _guest_available_memory(meminfo=Path('/proc/meminfo')):
    values = dict(line.split(':', 1) for line in meminfo.read_text().splitlines() if ':' in line)
    value, unit = values['MemAvailable'].split()
    if unit != 'kB' or int(value) < 0:
        raise ValueError('invalid guest memory sample')
    return int(value) * 1024


def _watch_guest(unit, duration):
    import re
    import time
    if not re.fullmatch(r'myinkpi-test-[0-9a-f-]{36}', unit) or not 1 <= duration <= 2700:
        raise ValueError('invalid watched unit')
    base = Path('/opt/myink-pi-lab')
    ownership = json.loads((base / 'current-operation.json').read_text())
    if ownership['unit'] != unit or ownership['lab_uuid'] != json.loads((base / 'lab-env.json').read_text())['lab_uuid']:
        raise ValueError('foreign watcher ownership')
    daemon = subprocess.check_output(['docker', '--host', 'unix:///var/run/docker.sock', 'info', '--format', '{{.ID}}'], text=True).strip()
    if daemon != '364e8400-3844-47e2-b86d-8b626332f61c':
        raise ValueError('foreign daemon')
    watch, started, samples, activated = MemoryWatchdog(), time.monotonic(), [], False
    result = {'unit': unit, 'operation_id': ownership['operation_id'], 'lab_uuid': ownership['lab_uuid'], 'sampler': '/proc/meminfo:MemAvailable', 'status': 'sampler_failure'}
    def active_owned():
        current = json.loads((base / 'current-operation.json').read_text())
        active = subprocess.run(['systemctl', 'is-active', '--quiet', unit]).returncode == 0
        if not active:
            return False
        group = subprocess.check_output(['systemctl', 'show', unit, '--property=ControlGroup', '--value'], text=True).strip()
        return current == ownership and active and group.startswith('/myinkpi.slice/myinkpi-heavy.slice/')
    try:
        while time.monotonic() - started <= duration + 5:
            active = active_owned()
            if not active:
                if activated or time.monotonic() - started > 5:
                    result['status'] = 'done' if activated else 'target_not_started'
                    break
                time.sleep(.1)
                continue
            activated = True
            available = _guest_available_memory()
            samples.append(available)
            if watch.observe(available, time.monotonic()):
                # Parent retains the mutex until this exact watcher stops; recheck operation/unit before effect.
                if not active_owned():
                    result['status'] = 'ownership_lost'
                    break
                Path('/sys/fs/cgroup/myinkpi.slice/myinkpi-heavy.slice/cgroup.kill').write_text('1')
                result['status'] = 'guest_low_memory'
                break
            time.sleep(.2)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        try:
            still_owned = active_owned()
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            still_owned = False
        if still_owned:
            Path('/sys/fs/cgroup/myinkpi.slice/myinkpi-heavy.slice/cgroup.kill').write_text('1')
        result['status'] = 'sampler_failure'
    finally:
        result['minimum_available'] = min(samples) if samples else None
        result['elapsed'] = time.monotonic() - started
        result['finished_at'] = datetime.now(timezone.utc).isoformat()
        (base / 'guest-watchdog.json').write_text(json.dumps(result))
        Path('/mnt/e/tools/myink-pi/evidence/' + ownership['operation_id'] + '.guest.json').write_text(json.dumps(result, indent=2))
        Path('/mnt/e/tools/myink-pi/evidence/b7-guest-watchdog.json').write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != 'watch-guest':
        raise SystemExit('fixed guest watchdog command required')
    _watch_guest(sys.argv[2], int(sys.argv[3]))
