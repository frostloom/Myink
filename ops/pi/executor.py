"""Trusted typed command boundary. No client shell, executable or Docker context."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import threading
import uuid

from .contracts import Receipt
from .resources import MemoryWatchdog, host_available_memory, verify_limits

COMMANDS = {'test': 2700, 'probe': 120, 'data-read': 120, 'git': 120, 'build': 2700, 'backup': 600, 'restore': 600}
RESERVED = {'git', 'build', 'backup', 'restore'}
EXCLUDED = {'.git', '.superpowers', '.env', '.agents', '.codex', '__pycache__', 'node_modules',
            'credentials', 'backups', 'ledger.sqlite', 'ledger.sqlite-wal', 'ledger.sqlite-shm', 'policy.example.json'}
ENVIRONMENT = {'DATABASE_URL', 'ADMIN_DATABASE_URL', 'REDIS_URL', 'AMQP_URL', 'QUEUE_PREFIX',
               'JWT_SECRET', 'EMBED_ENABLED', 'PYTHONPATH', 'TMPDIR', 'PYTHONPYCACHEPREFIX'}
DAEMON_ID = '364e8400-3844-47e2-b86d-8b626332f61c'


def safe_source(root, path):
    root = Path(root).resolve(strict=True)
    relative = Path(path)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('source path escape')
    candidate = root / relative
    for part in (candidate, *candidate.parents):
        if part == root:
            break
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('source link rejected')
    if not candidate.resolve().is_relative_to(root):
        raise ValueError('source path escape')
    return candidate


def sandbox_environment(values):
    return {k: str(v) for k, v in values.items() if k in ENVIRONMENT}


def validate_daemon(expected, actual):
    return bool(expected == DAEMON_ID and actual.get('ID') == expected
                and actual.get('CgroupVersion') == '2' and actual.get('CgroupDriver') == 'systemd'
                and actual.get('DockerRootDir') == '/var/lib/docker')


def stage_source(source, destination):
    """Fresh native candidate only; fail on links rather than following history/secrets."""
    source, destination = Path(source).resolve(strict=True), Path(destination)
    if destination.exists() or not str(destination).startswith('/opt/myink-pi-lab/candidates/'):
        raise ValueError('fresh private candidate required')
    files = []
    for root, dirs, names in os.walk(source, followlinks=False):
        rel = Path(root).relative_to(source)
        for name in list(dirs):
            if name in EXCLUDED or name.startswith('.env'):
                dirs.remove(name)
                continue
            safe_source(source, rel / name)
        for name in names:
            if name in EXCLUDED or name.startswith('.env') or name.endswith(('.pem', '.key', '.sqlite')):
                continue
            path = safe_source(source, rel / name)
            if path.stat().st_nlink != 1:
                raise ValueError('hardlinked source rejected')
            files.append((path, rel / name))
    destination.mkdir(parents=True)
    for path, relative in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return len(files)


class _Diagnostics:
    """Drain both pipes while the guardian runs; retain at most 4 MiB per stream."""
    limit = 4 * 1024 * 1024

    def __init__(self, process, state, operation):
        self.threads = []
        self.errors = []
        self.truncated = []
        for name in ('stdout', 'stderr'):
            pipe = getattr(process, name, None)
            if pipe is not None:
                thread = threading.Thread(target=self._drain,
                    args=(pipe, state / (operation + '.' + name), name), daemon=True)
                thread.start()
                self.threads.append(thread)

    def _drain(self, pipe, path, name):
        retained = 0
        try:
            with path.open('wb') as output:
                while True:
                    chunk = pipe.read(65536)
                    if not chunk:
                        break
                    keep = chunk[:max(0, self.limit - retained)]
                    output.write(keep)
                    retained += len(keep)
                    if len(keep) < len(chunk) and name not in self.truncated:
                        self.truncated.append(name)
        except OSError:
            self.errors.append(name)
        finally:
            pipe.close()

    def finish(self):
        for thread in self.threads:
            thread.join(timeout=2)
        if self.errors or any(thread.is_alive() for thread in self.threads):
            raise OSError('diagnostic drain unconfirmed')


def execute(command_id, args, deadline, ledger):
    tool_started = time.monotonic()
    operation = str(uuid.uuid4())
    blocked = lambda reason: Receipt(operation, 'blocked', {'reason': reason})
    if command_id not in COMMANDS or not isinstance(args, dict):
        return blocked('unknown_command')
    if command_id in RESERVED:
        return blocked('prerequisite_not_implemented')
    if set(args) - {'state_dir', 'selection'}:
        return blocked('untyped_arguments')
    if (not isinstance(deadline, datetime) or deadline.tzinfo is None
            or deadline <= datetime.now(timezone.utc)):
        return blocked('deadline_expired')
    if sys.platform != 'win32' or ledger is None:
        return blocked('trusted_windows_controller_required')
    process = None
    diagnostics = None
    host_probe = None
    identity = None
    probes_started = False
    receipt = None
    def remaining(cap=None):
        budget = min(COMMANDS[command_id] - (time.monotonic() - tool_started),
                     (deadline - datetime.now(timezone.utc)).total_seconds())
        if budget <= 0:
            raise subprocess.TimeoutExpired(command_id, 0)
        return min(budget, cap) if cap is not None else budget
    def setup(mode, *args, cap):
        budget=remaining(cap)
        command=['wsl.exe','-d','MyinkPiLab','-u','root','--','timeout','--kill-after=1s',str(budget)+'s',
                 '/opt/myink-pi-lab/provision.sh',mode,*args]
        try:
            return subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=remaining(cap),check=True)
        except subprocess.CalledProcessError as error:
            if error.returncode==124: raise subprocess.TimeoutExpired(mode,budget) from error
            raise
    try:
        state = Path(args['state_dir'])
        if state.drive.lower() != 'e:' or not state.is_absolute() or '..' in state.parts:
            return blocked('invalid_state_path')
        identity = json.loads((state / 'lab-env.json').read_text(encoding='utf-8'))
        if identity['daemon_id'] != DAEMON_ID or identity['distribution'] != 'MyinkPiLab':
            return blocked('foreign_lab')
        preflight = setup('preflight', cap=120)
        fresh = json.loads(preflight.stdout)
        if fresh.get('lab_uuid') != identity['lab_uuid'] or fresh.get('daemon_id') != DAEMON_ID:
            return blocked('foreign_lab')
        if not verify_limits(fresh.get('kernel_proof', {}), 'heavy'):
            return blocked('missing_cgroup_proof')
        selection = args.get('selection', 'b7')
        if selection not in ('b7', 'provenance', 'bootstrap', 'watchdog', 'b8-red', 'b8-focused', 'b8-survival', 'b8'):
            return blocked('unknown_test_selection')
        if selection == 'b7' and command_id in ('test', 'probe'):
            remaining()
            probe_script = Path(__file__).parent / 'lab' / 'host-probe.py'
            host_probe = subprocess.Popen([sys.executable, str(probe_script), str(state)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            probe_file = state.parent / 'evidence' / 'b7-host-server.json'
            for _ in range(100):
                if probe_file.exists() and json.loads(probe_file.read_text()).get('pid') == host_probe.pid:
                    break
                if host_probe.poll() is not None:
                    receipt = blocked('host_probe_failed')
                    return receipt
                time.sleep(min(.05, remaining()))
            else:
                receipt = blocked('host_probe_failed')
                return receipt
            probes_started = True
            setup('prepare-probes', operation, identity['lab_uuid'], cap=30)
        run_budget = remaining()
        if run_budget < 1:
            receipt = blocked('deadline_expired')
            return receipt
        ledger.append_event('tool_intent', {'operation_id': operation, 'command_id': command_id, 'lab_uuid': identity['lab_uuid']})
        # Script is installed root-owned from reviewed source; all args are finite IDs.
        command = ['wsl.exe', '-d', 'MyinkPiLab', '-u', 'root', '--', '/opt/myink-pi-lab/provision.sh',
                   'execute', command_id, selection, str(int(run_budget)), operation]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        diagnostics = _Diagnostics(process, state, operation)
        watch, start = MemoryWatchdog(), time.monotonic()
        samples = []
        reason = None
        while process.poll() is None:
            available = host_available_memory()
            samples.append(available)
            if watch.observe(available, time.monotonic()):
                reason = 'host_low_memory'
            if time.monotonic() - start >= run_budget:
                reason = 'deadline_expired'
            if reason:
                termination = subprocess.run(['wsl.exe', '-d', 'MyinkPiLab', '-u', 'root', '--',
                                '/opt/myink-pi-lab/provision.sh', 'stop-heavy', operation, identity['lab_uuid']], timeout=30, check=True,
                               capture_output=True)
                termination_proof = json.loads(termination.stdout)
                process.kill()
                break
            time.sleep(.2)
        if diagnostics.threads:
            process.wait(timeout=30)
            diagnostics.finish()
            output = error = None
        else:
            output, error = process.communicate(timeout=30)
        evidence = {'command_id': command_id, 'lab_uuid': identity['lab_uuid'], 'host_min_available': min(samples) if samples else host_available_memory(),
                    'elapsed': time.monotonic() - start, 'returncode': process.returncode}
        # Persist diagnostic bytes in trusted state, never return candidate output to a model.
        if output is not None:
            (state / f'{operation}.stdout').write_bytes(output)
            (state / f'{operation}.stderr').write_bytes(error)
        evidence['diagnostics_truncated'] = diagnostics.truncated
        guest_file = state.parent / 'evidence' / f'{operation}.guest.json'
        if guest_file.exists():
            guest = json.loads(guest_file.read_text(encoding='utf-8'))
            if guest.get('operation_id') != operation or guest.get('lab_uuid') != identity['lab_uuid']:
                raise ValueError('foreign guest receipt')
            evidence['guest_watchdog'] = guest
            if guest['status'] != 'done' and reason is None:
                reason = guest['status']
        elif reason is None:
            reason = 'guest_sampler_receipt_missing'
        if reason:
            evidence['reason'] = reason
            evidence['termination_proof'] = locals().get('termination_proof')
        receipt = Receipt(operation, 'failed' if reason or process.returncode else 'done', evidence)
        return receipt
    except subprocess.TimeoutExpired:
        receipt = blocked('deadline_expired')
        return receipt
    except (KeyError, ValueError, OSError, subprocess.SubprocessError, RuntimeError):
        receipt = blocked('lab_preflight_failed')
        return receipt
    finally:
        cleanup_errors = []
        if probes_started:
            try:
                subprocess.run(['wsl.exe','-d','MyinkPiLab','-u','root','--','/opt/myink-pi-lab/provision.sh','stop-probes',operation,identity['lab_uuid']],timeout=10,capture_output=True,check=True)
            except (OSError, subprocess.SubprocessError) as error:
                cleanup_errors.append({'step': 'stop_probes', 'error': type(error).__name__})
        if host_probe is not None:
            try:
                if host_probe.poll() is None:
                    host_probe.terminate()
                    host_probe.wait(timeout=2)
            except (OSError, subprocess.SubprocessError) as error:
                cleanup_errors.append({'step': 'host_probe', 'error': type(error).__name__})
                try:
                    host_probe.kill()
                    host_probe.wait(timeout=2)
                except (OSError, subprocess.SubprocessError) as error:
                    cleanup_errors.append({'step': 'host_probe_kill', 'error': type(error).__name__})
        if process is not None:
            try:
                if process.poll() is None:
                    try:
                        subprocess.run(['wsl.exe', '-d', 'MyinkPiLab', '-u', 'root', '--', '/opt/myink-pi-lab/provision.sh', 'stop-heavy', operation, identity['lab_uuid']], timeout=30, capture_output=True, check=True)
                    finally:
                        try:
                            process.kill()
                        finally:
                            if diagnostics is not None and diagnostics.threads:
                                process.wait(timeout=30)
                                diagnostics.finish()
                            else:
                                process.communicate(timeout=30)
            except (OSError, subprocess.SubprocessError) as error:
                cleanup_errors.append({'step': 'owned_heavy', 'error': type(error).__name__})
        if receipt is not None and (process is not None or cleanup_errors):
            if cleanup_errors:
                evidence = {**receipt.evidence, 'cleanup_errors': cleanup_errors}
                evidence.setdefault('reason', 'cleanup_unconfirmed')
                receipt = Receipt(operation, 'failed' if receipt.status == 'done' else receipt.status, evidence)
            # File and ledger publication are independent; neither may mask cleanup.
            publication_errors = []
            publication = {'file': False, 'ledger': False}
            receipt_file = state.parent / 'evidence' / f'{operation}.receipt.json'
            try:
                receipt_file.write_text(json.dumps({'operation_id': operation, 'status': receipt.status, 'evidence': receipt.evidence}, indent=2), encoding='utf-8')
                publication['file'] = True
            except OSError as error:
                publication_errors.append({'step': 'receipt_file', 'error': type(error).__name__})
                evidence = {**receipt.evidence, 'publication_errors': list(publication_errors)}
                evidence.setdefault('reason', 'publication_unconfirmed')
                receipt = Receipt(operation, 'failed' if receipt.status == 'done' else receipt.status, evidence)
            try:
                ledger.append_event('tool_receipt', {'operation_id': operation, 'status': receipt.status, **receipt.evidence})
                publication['ledger'] = True
            except (OSError, RuntimeError, ValueError) as error:
                publication_errors.append({'step': 'receipt_ledger', 'error': type(error).__name__})
            if publication_errors:
                evidence = {**receipt.evidence, 'publication_errors': publication_errors, 'publication': dict(publication)}
                evidence.setdefault('reason', 'publication_unconfirmed')
                receipt = Receipt(operation, 'failed' if receipt.status == 'done' else receipt.status, evidence)
                # If ledger publication failed, correct an already-written file honestly.
                if publication['file'] and not publication['ledger']:
                    try:
                        receipt_file.write_text(json.dumps({'operation_id': operation, 'status': receipt.status, 'evidence': receipt.evidence}, indent=2), encoding='utf-8')
                    except OSError as error:
                        receipt.evidence['publication']['file'] = False
                        publication_errors.append({'step': 'receipt_file_correction', 'error': type(error).__name__})
            if cleanup_errors or publication_errors:
                return receipt
