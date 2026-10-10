import argparse
from datetime import datetime
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


def make_gateway_handler(ledger, policy, transport):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'  # EOF framing supports streaming without buffering.

        def log_message(self, *args):
            pass  # Never log request data, credentials, or upstream exceptions.

        def setup(self):
            self.deadline = time.monotonic() + policy.timeout_seconds
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
                lengths = self.headers.get_all('Content-Length', [])
                if (self.path != '/v1/messages' or len(lengths) != 1
                        or not lengths[0].isdigit() or self.headers.get('Transfer-Encoding')
                        or self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json'
                        or self.headers.get('X-Pi-Scope', 'local-trial-1') != 'local-trial-1'):
                    raise ValueError('invalid request envelope')
                length = int(lengths[0])
                if not 0 < length <= policy.max_body_bytes:
                    raise ValueError('invalid body size')
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError('incomplete request')
                body = json.loads(raw)
                request_policy = replace(policy, timeout_seconds=self.remaining())
                result = forward_messages(body, 'local-trial-1', ledger=ledger, policy=request_policy, transport=transport)
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


def serve_gateway(ledger, policy, credential_file, host='127.0.0.1', port=8765):
    if not live_ready(policy):
        raise ValueError('live configuration incomplete')
    credentials = json.loads(credential_file.read_text(encoding='utf-8'))
    expected = {'PLATFORM_MODEL_API_KEY', 'PLATFORM_MODEL_BASE_URL', 'PLATFORM_MODEL_NAME', 'PLATFORM_MODEL_PROTOCOL'}
    if (not isinstance(credentials, dict) or set(credentials) != expected
            or not all(isinstance(v, str) and v.strip() for v in credentials.values())
            or credentials['PLATFORM_MODEL_BASE_URL'].rstrip('/') != policy.base_url.rstrip('/')
            or credentials['PLATFORM_MODEL_NAME'] != policy.model
            or credentials['PLATFORM_MODEL_PROTOCOL'] != policy.protocol):
        raise ValueError('invalid trusted credentials')
    with httpx.Client(follow_redirects=False, trust_env=False, timeout=policy.timeout_seconds) as client:
        def transport(body, timeout):
            request = client.build_request('POST', policy.base_url.rstrip('/') + '/v1/messages', json=body,
                                           headers={'x-api-key': credentials['PLATFORM_MODEL_API_KEY'],
                                                    'anthropic-version': '2023-06-01'}, timeout=timeout)
            return client.send(request, stream=True, follow_redirects=False)
        with ThreadingHTTPServer((host, port), make_gateway_handler(ledger, policy, transport)) as server:
            server.daemon_threads = True
            server.serve_forever()


def state_path_allowed(path, *, platform=None):
    """Current lab state is E: on Windows, or its /mnt/e WSL mount."""
    platform = sys.platform if platform is None else platform
    if not path.is_absolute() or '..' in path.parts:
        return False
    if platform == 'win32':
        return path.drive.lower() == 'e:'
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
        if args.command == 'schedule':
            from .schedule import next_action
            result = next_action(None, datetime.fromisoformat(args.clock), {}, load_policy(args.policy))
            print(json.dumps(result))
            return 0
        state = args.state_dir
        if not state_path_allowed(state):
            raise LedgerBlocked('state directory must be an explicit absolute E drive path')
        state.mkdir(parents=True, exist_ok=True)
        ledger = Ledger(state / 'ledger.sqlite')
        if args.command == 'report':
            from .reporting import render_report, PENDING_ACCEPTANCE
            if not state_path_allowed(args.output):
                raise LedgerBlocked('report output must be an explicit absolute E drive path')
            with ledger.transaction() as connection:
                events = [dict(kind=row['kind'], payload=ledger._decode(row['payload']))
                          for row in connection.execute('SELECT kind,payload FROM events ORDER BY id')]
            snapshots = [event['payload'] for event in events if event['kind'] == 'snapshot']
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
