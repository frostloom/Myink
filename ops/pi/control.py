import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

import httpx

from .ledger import Ledger, LedgerBlocked
from .model_gateway import forward_messages
from .policy import load_policy


def live_ready(policy):
    return (policy.live_enabled and policy.input_bound_calibrated and bool(policy.input_bound_source.strip())
            and bool(policy.price_source.strip()) and all(v is not None for v in policy.prices.values()))


def make_gateway_handler(ledger, policy, transport):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'  # EOF framing supports streaming without buffering.

        def log_message(self, *args):
            pass  # Never log request data, credentials, or upstream exceptions.

        def setup(self):
            self.request.settimeout(policy.timeout_seconds)
            super().setup()

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
                result = forward_messages(body, 'local-trial-1', ledger=ledger, policy=policy, transport=transport)
                self.send_response(result.status_code)
                for key, value in result.headers.items():
                    # Only explicit safe response headers survive the model boundary.
                    if '\r' not in value and '\n' not in value:
                        self.send_header(key, value)
                self.send_header('Connection', 'close')
                self.end_headers()
                iterator = iter([result.body]) if isinstance(result.body, bytes) else iter(result.body)
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
    args = parser.parse_args(argv)
    try:
        state = args.state_dir
        if not state.is_absolute() or state.drive.lower() != 'e:':
            raise LedgerBlocked('state directory must be an explicit absolute E drive path')
        state.mkdir(parents=True, exist_ok=True)
        ledger = Ledger(state / 'ledger.sqlite')
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
