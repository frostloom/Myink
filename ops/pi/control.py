import argparse
from datetime import datetime, timezone
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from hmac import compare_digest
import json
from pathlib import Path
import socket
import sys
from threading import Timer
import time

import httpx

from .ledger import Ledger, LedgerBlocked
from .model_gateway import forward_messages
from .policy import load_policy
from .provider_config import load_credentials


def live_ready(policy):
    return (policy.live_enabled and policy.input_bound_calibrated and bool(policy.input_bound_source.strip())
            and bool(policy.price_source.strip()) and all(v is not None for v in policy.prices.values()))


class _DeadlineIO:
    """Every socket operation shares the HTTP handler's absolute deadline."""
    def __init__(self, wrapped, handler):
        self.wrapped = wrapped
        self.handler = handler

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def _call(self, name, *args):
        self.handler.set_remaining_timeout()
        result = getattr(self.wrapped, name)(*args)
        self.handler.set_remaining_timeout()  # A late completion cannot resume settlement.
        return result

    def read(self, *args):
        return self._call('read', *args)

    def readline(self, *args):
        return self._call('readline', *args)

    def write(self, *args):
        return self._call('write', *args)

    def flush(self):
        return self._call('flush')


def make_gateway_handler(ledger, policy, transport, *, scope_token=None, usage_observer=None,
                         tool_broker=None, request_guard=None, analysis_slot=None):
    if scope_token is not None and (not isinstance(scope_token, str) or not 0 < len(scope_token) <= 4096
                                   or any(not 33 <= ord(char) <= 126 for char in scope_token)):
        raise ValueError('invalid scope token')
    if request_guard is not None and (not callable(request_guard) or scope_token is None):
        raise ValueError('request guard requires a callable and authenticated scope')
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'  # EOF framing supports streaming without buffering.

        def log_message(self, *args):
            pass  # Never log request data, credentials, or upstream exceptions.

        def setup(self):
            duration = policy.timeout_seconds
            if analysis_slot is not None and analysis_slot.deadline is not None:
                duration = min(duration, max(0.001, analysis_slot.deadline - time.time()))
            self.deadline = time.monotonic() + duration
            self.set_remaining_timeout()
            super().setup()
            self.rfile = _DeadlineIO(self.rfile, self)
            self.wfile = _DeadlineIO(self.wfile, self)
            # A deadline watchdog also interrupts a real socket trickling within
            # one buffered read, which could otherwise reset its per-recv timeout.
            self.watchdog = Timer(self.remaining(), self.expire_socket)
            self.watchdog.daemon = True
            self.watchdog.start()

        def remaining(self):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('HTTP request deadline exceeded')
            return remaining

        def set_remaining_timeout(self):
            self.request.settimeout(self.remaining())

        def expire_socket(self):
            self.close_connection = True
            try:
                self.request.shutdown(socket.SHUT_RDWR)
            except (OSError, AttributeError):
                pass

        def finish(self):
            self.watchdog.cancel()
            super().finish()

        def do_POST(self):
            iterator = None
            try:
                tool_path = self.path in ('/v1/tools', '/v1/tool-proof')
                request_token = tool_broker.token if tool_broker and tool_path else scope_token
                if request_token is not None:
                    keys = self.headers.get_all('x-api-key', [])
                    scopes = self.headers.get_all('X-Pi-Scope', [])
                    if (len(keys) != 1 or scopes != ['local-trial-1']
                            or not compare_digest(keys[0].encode('utf-8'), request_token.encode('utf-8'))):
                        self.send_error(403)
                        return
                lengths = self.headers.get_all('Content-Length', [])
                if (self.path not in (('/v1/messages', '/v1/messages?beta=true', '/v1/tools', '/v1/tool-proof') if tool_broker else ('/v1/messages', '/v1/messages?beta=true')) or len(lengths) != 1
                        or not lengths[0].isdigit() or self.headers.get('Transfer-Encoding')
                        or self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json'
                        or self.headers.get('X-Pi-Scope', 'local-trial-1') != 'local-trial-1'):
                    raise ValueError('invalid request envelope')
                length = int(lengths[0])
                if not 0 < length <= policy.max_body_bytes:
                    raise ValueError('invalid body size')
                if tool_path and length > 32768:
                    raise ValueError('invalid tool body size')
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError('incomplete request')
                from .tool_proof import strict_json, validate_proof
                body = strict_json(raw)
                if self.path == '/v1/tool-proof':
                    body = validate_proof(body)
                    verified = tool_broker.lookup(body['call_id'], body['name'], body['arguments'], body['receipt']) is True
                    result = json.dumps({'verified':verified}).encode('ascii')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(result)))
                    self.end_headers()
                    self.wfile.write(result)
                    return
                if self.path == '/v1/tools':
                    keys = self.headers.get_all('x-api-key', [])
                    scopes = self.headers.get_all('X-Pi-Scope', [])
                    if len(keys) != 1 or scopes != ['local-trial-1'] or length > 32768:
                        raise ValueError('invalid tool envelope')
                    from dataclasses import asdict
                    receipt = tool_broker.dispatch(keys[0], body)
                    raw_receipt = json.dumps(asdict(receipt), ensure_ascii=True, allow_nan=False).encode()
                    if len(raw_receipt) > 65536:
                        raise ValueError('bounded tool receipt required')
                    self.send_response(200); self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(raw_receipt))); self.end_headers()
                    self.wfile.write(raw_receipt)
                    return
                if request_guard is not None:
                    try:
                        admitted = request_guard(body) is True
                    except Exception:
                        admitted = False
                    if not admitted:
                        self.send_error(403)
                        return
                request_policy = replace(policy, timeout_seconds=self.remaining())
                result = forward_messages(body, 'local-trial-1', ledger=ledger, policy=request_policy,
                                          transport=transport, usage_observer=usage_observer,
                                          tool_allowlist=tool_broker.allowed_tools if tool_broker else (),
                                          analysis_slot=analysis_slot)
                if result.attempt_id:
                    permit_deadline = ledger.get(result.attempt_id)['payload']['deadline']
                    self.deadline = min(self.deadline, time.monotonic() + max(0, permit_deadline - time.time()))
                iterator = iter([result.body]) if isinstance(result.body, bytes) else iter(result.body)
                self.set_remaining_timeout()
                self.send_response(result.status_code)
                for key, value in result.headers.items():
                    # Only explicit safe response headers survive the model boundary.
                    if '\r' not in value and '\n' not in value:
                        self.send_header(key, value)
                self.send_header('Connection', 'close')
                self.end_headers()
                for chunk in iterator:
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (ValueError, TypeError):
                self.send_error(400)
            except Exception:
                # Socket/upstream failure closes the stream; reservation stays unknown.
                self.close_connection = True
            finally:
                if iterator is not None and hasattr(iterator, 'close'):
                    iterator.close()
    return Handler


def serve_gateway(ledger, policy, credential_file, host='127.0.0.1', port=8765, *, scope_token=None,
                  tool_broker=None, request_guard=None):
    if not live_ready(policy):
        raise ValueError('live configuration incomplete')
    credentials = load_credentials(credential_file, policy)
    with httpx.Client(follow_redirects=False, trust_env=False, timeout=policy.timeout_seconds) as client:
        def transport(body, timeout):
            request = client.build_request('POST', policy.base_url.rstrip('/') + '/v1/messages', json=body,
                                           headers={'x-api-key': credentials['PLATFORM_MODEL_API_KEY'],
                                                    'anthropic-version': '2023-06-01'}, timeout=timeout)
            return client.send(request, stream=True, follow_redirects=False)
        with ThreadingHTTPServer((host, port), make_gateway_handler(ledger, policy, transport,
                scope_token=scope_token, tool_broker=tool_broker, request_guard=request_guard)) as server:
            server.daemon_threads = True
            server.serve_forever()


_MAC_LAB = '/Users/a1/项目/Myink/myink-pi'


def state_path_allowed(path, *, platform=None):
    """Lab state stays on E: for Windows, /mnt/e for WSL, or the Mac project folder."""
    platform = sys.platform if platform is None else platform
    if not path.is_absolute() or '..' in path.parts:
        return False
    if platform == 'win32':
        return path.drive.lower() == 'e:'
    if platform == 'darwin':
        try:
            path.relative_to(_MAC_LAB)
        except ValueError:
            return False
        return True
    if platform.startswith('linux'):
        return path.parts[:3] == ('/', 'mnt', 'e')
    return False


def make_git_flow(ledger, config, plan, policy):
    """Host-only setup; Git authority is never accepted by the model HTTP handler."""
    from .git_flow import GitFlow
    if not state_path_allowed(config.workspace_root):
        raise LedgerBlocked('Git workspace must be an explicit absolute E drive path')
    return GitFlow(ledger, config, plan, policy)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    trial = commands.add_parser('trial')
    trial_commands = trial.add_subparsers(dest='trial_command', required=True)
    trial_run = trial_commands.add_parser('run')
    trial_run.add_argument('--state-dir', required=True, type=Path)
    trial_run.add_argument('--policy', required=True, type=Path)
    trial_run.add_argument('--scenario', required=True)
    trial_run.add_argument('--experiment', default='local-trial-1')
    trial_run.add_argument('--live', action='store_true')
    trial_resume = trial_commands.add_parser('resume')
    trial_resume.add_argument('--state-dir', required=True, type=Path)
    trial_resume.add_argument('--experiment', required=True)
    lab = commands.add_parser('lab')
    lab_commands = lab.add_subparsers(dest='lab_command', required=True)
    lab_preflight = lab_commands.add_parser('preflight')
    lab_preflight.add_argument('--root', required=True, type=Path)
    lab_up = lab_commands.add_parser('up')
    lab_up.add_argument('--state-dir', required=True, type=Path)
    lab_maintenance = lab_commands.add_parser('maintenance-up')
    lab_maintenance.add_argument('--state-dir', required=True, type=Path)
    recovery = commands.add_parser('backup-lab')
    recovery.add_argument('--state-dir', required=True, type=Path)
    recovery.add_argument('--phase', required=True, choices=('source','restore','verify','fresh','gate'))
    recovery.add_argument('--deadline', required=True)
    check = commands.add_parser('ledger-check')
    check.add_argument('--state-dir', required=True, type=Path)
    gateway = commands.add_parser('model-gateway')
    gateway.add_argument('--state-dir', required=True, type=Path)
    gateway.add_argument('--policy', required=True, type=Path)
    gateway.add_argument('--credential-file', required=True, type=Path)
    gateway.add_argument('--host', default='127.0.0.1')
    gateway.add_argument('--port', type=int, default=8765)
    schedule = commands.add_parser('schedule')
    schedule.add_argument('--clock', required=True)
    schedule.add_argument('--simulate', required=True, action='store_true')
    schedule.add_argument('--policy', type=Path, default=Path(__file__).with_name('policy.example.json'))
    report = commands.add_parser('report')
    report.add_argument('--state-dir', required=True, type=Path)
    report.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'lab':
            from dataclasses import asdict
            from .resources import probe_environment
            root = args.root if args.lab_command == 'preflight' else args.state_dir.parent
            receipt = probe_environment(root)
            if args.lab_command in ('up', 'maintenance-up') and receipt.status == 'done':
                import subprocess
                completed = subprocess.run(['wsl.exe', '-d', 'MyinkPiLab', '-u', 'root', '--', '/opt/myink-pi-lab/provision.sh', 'maintenance-up' if args.lab_command == 'maintenance-up' else 'preflight'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
                if completed.returncode:
                    raise LedgerBlocked('lab resource preflight failed')
                receipt = replace(receipt, evidence={**receipt.evidence, **json.loads(completed.stdout)})
            print(json.dumps(asdict(receipt)))
            return 0 if receipt.status == 'done' else 1
        if args.command == 'schedule':
            from .schedule import next_action
            result = next_action(None, datetime.fromisoformat(args.clock), {}, load_policy(args.policy))
            print(json.dumps(result))
            return 0
        state = args.state_dir
        if not state_path_allowed(state):
            raise LedgerBlocked('state directory must be an explicit absolute E drive path')
        state.mkdir(parents=True, exist_ok=True)
        ledger = Ledger(state / ('b11-executor-ledger.sqlite' if args.command=='backup-lab' else 'ledger.sqlite'))
        if args.command == 'trial':
            from dataclasses import asdict
            from .iteration import simulate_trial, resume_simulated_trial
            if args.trial_command == 'run':
                load_policy(args.policy)
                if args.live:
                    print(json.dumps(dict(status='blocked', released=False,
                        reason='live requires fresh host-composed runtime and downstream acceptance')))
                    return 1
                receipt = simulate_trial(ledger,args.scenario,args.experiment,datetime.now(timezone.utc))
            else:
                receipt = resume_simulated_trial(ledger,args.experiment)
            print(json.dumps(asdict(receipt)))
            return 0 if receipt.status=='done' else 1
        if args.command == 'backup-lab':
            from dataclasses import asdict
            from .executor import execute
            receipt=execute('backup' if args.phase in ('source','fresh') else 'restore', {'state_dir':str(state),'selection':'b11-'+args.phase},datetime.fromisoformat(args.deadline),ledger)
            print(json.dumps(asdict(receipt)))
            return 0 if receipt.status=='done' else 1
        if args.command == 'report':
            from .reporting import render_report, PENDING_ACCEPTANCE
            if not state_path_allowed(args.output):
                raise LedgerBlocked('report output must be an explicit absolute E drive path')
            with ledger.transaction() as connection:
                events = [dict(kind=row['kind'], payload=ledger._decode(row['payload']))
                          for row in connection.execute('SELECT kind,payload FROM events ORDER BY id')]
            snapshots = [event['payload'] for event in events if event['kind'] == 'snapshot']
            if args.output.suffix.lower() == '.json':
                raise ValueError('report output must not use the JSON index extension')
            args.output.write_text(render_report(events, snapshots), encoding='utf-8')
            index = dict(schema_version=1, event_count=len(events), snapshot_count=len(snapshots),
                         pending_acceptance=PENDING_ACCEPTANCE, next_action='review blockers and gather pending acceptance evidence')
            args.output.with_suffix('.json').write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(index, ensure_ascii=False))
            return 0
        if args.command == 'model-gateway':
            policy = load_policy(args.policy)
            if not live_ready(policy) or not args.credential_file.is_absolute() or not 1 <= args.port <= 65535:
                raise ValueError('live configuration incomplete')
            serve_gateway(ledger, policy, args.credential_file, args.host, args.port)
    except (LedgerBlocked, OSError, ValueError, TypeError):
        print(json.dumps({'schema_version': 1, 'status': 'blocked'}))
        return 1
    print(json.dumps({'schema_version': 1, 'status': 'done'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
