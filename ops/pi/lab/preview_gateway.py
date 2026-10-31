"""Trusted lab-root text gateway for the single bounded readonly Pi preview."""
import argparse
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from threading import Lock, Timer
import time

import httpx

from ..budget import _totals, totals
from ..control import live_ready, make_gateway_handler
from ..ledger import Ledger, LedgerBlocked, _json
from ..policy import load_policy


ROOT = Path('/Users/a1/项目/Myink/myink-pi')
POLICY_FILE = ROOT / 'evidence/c14/read-only-preview-policy.json'
CREDENTIAL_FILE = ROOT / 'state/credentials/platform-model.json'
LEDGER_FILE = ROOT / 'state/ledger.sqlite'
FENCE_ID = 'c14-readonly-preview-2026-10-11'
SCOPE = 'local-trial-1'


def ensure_preview_fence(ledger):
    # Baseline creation and the canonical count share one durable transaction.
    with ledger.transaction() as connection:
        count, _ = _totals(connection, SCOPE)
        row = connection.execute('SELECT * FROM operations WHERE operation_id=?', (FENCE_ID,)).fetchone()
        if row is not None:
            payload = Ledger._decode(row['payload'])
            if (row['kind'] != 'preview-fence' or row['status'] != 'pending'
                    or set(payload) != {'scope_id', 'baseline_attempts', 'max_preview_attempts'}
                    or payload['scope_id'] != SCOPE or type(payload['baseline_attempts']) is not int
                    or not 0 <= payload['baseline_attempts'] <= count <= 100
                    or type(payload['max_preview_attempts']) is not int or payload['max_preview_attempts'] != 6):
                raise LedgerBlocked('invalid preview fence')
            return payload
        if not 0 <= count <= 100:
            raise LedgerBlocked('invalid canonical attempt count')
        payload = dict(scope_id=SCOPE, baseline_attempts=count, max_preview_attempts=6)
        connection.execute("INSERT INTO operations VALUES (?,'preview-fence',?,'pending',NULL,1)", (FENCE_ID, _json(payload)))
        connection.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',
                           ('intent', _json(dict(operation_id=FENCE_ID, kind='preview-fence', payload=payload, schema_version=1))))
        return payload


def make_preview_transport(ledger, policy, client, credentials, *, deadline=None):
    fence = ensure_preview_fence(ledger)
    lock = Lock()

    def send(body, timeout):
        # forward_messages has already durably reserved this attempt. A denied
        # seventh reservation remains charged; it never reaches client.send.
        with lock:
            count, _ = totals(ledger, SCOPE)
            if count > fence['baseline_attempts'] + 6:
                raise LedgerBlocked('preview attempt cap exhausted')
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('preview deadline exceeded')
                timeout = min(timeout, remaining)
            request = client.build_request('POST', policy.base_url.rstrip('/') + '/v1/messages', json=body,
                                           headers={'x-api-key': credentials['PLATFORM_MODEL_API_KEY'],
                                                    'anthropic-version': '2023-06-01'}, timeout=timeout)
            return client.send(request, stream=True, follow_redirects=False)
    return send


def _private_path(path):
    if not path.is_absolute() or '..' in path.parts or not path.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('preview paths must remain in the private E lab root')
    return path


def make_usage_observer(path):
    """Opt-in private, exclusive diagnostic file; at most six bounded records."""
    path = _private_path(path)
    # Reserve the destination before any live request; never overwrite evidence.
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    lock = Lock()
    count = 0

    def observe(item):
        nonlocal count
        encoded = json.dumps(item, allow_nan=False, separators=(',', ':')) + '\n'
        if len(encoded.encode('utf-8')) > 8192:
            return
        with lock:
            if count >= 6:
                return
            count += 1
            with path.open('a', encoding='utf-8') as target:
                target.write(encoded)
                target.flush()
                os.fsync(target.fileno())
    return observe


def _credentials(policy):
    if CREDENTIAL_FILE.stat().st_size > 16384:
        raise ValueError('invalid trusted credentials')
    credentials = json.loads(CREDENTIAL_FILE.read_text(encoding='utf-8'))
    expected = {'PLATFORM_MODEL_API_KEY', 'PLATFORM_MODEL_BASE_URL', 'PLATFORM_MODEL_NAME', 'PLATFORM_MODEL_PROTOCOL'}
    if (not isinstance(credentials, dict) or set(credentials) != expected
            or not all(isinstance(value, str) and value.strip() for value in credentials.values())
            or credentials['PLATFORM_MODEL_BASE_URL'].rstrip('/') != policy.base_url.rstrip('/')
            or credentials['PLATFORM_MODEL_NAME'] != policy.model
            or credentials['PLATFORM_MODEL_PROTOCOL'] != policy.protocol):
        raise ValueError('invalid trusted credentials')
    return credentials


def _budget(ledger):
    count, charged = totals(ledger, SCOPE)
    return dict(scope_id=SCOPE, attempts=count, charged_or_reserved_microyuan=charged)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope-token-file', required=True, type=Path)
    parser.add_argument('--ready-file', required=True, type=Path)
    parser.add_argument('--usage-diagnostic-file', type=Path)
    parser.add_argument('--deadline-seconds', type=int, default=180)
    args = parser.parse_args(argv)
    if (not sys.platform.startswith('linux') or os.geteuid() != 0
            or not 3 <= args.deadline_seconds <= 180):
        print(json.dumps(dict(status='blocked')))
        return 1
    # The separately reviewed systemd RuntimeMaxSec is also mandatory at launch.
    # A blocked I/O/SQLite operation cannot extend this process deadline.
    deadline = time.monotonic() + args.deadline_seconds
    hard_stop = Timer(args.deadline_seconds, os._exit, args=(124,))
    hard_stop.daemon = True
    hard_stop.start()
    shutdown = None
    try:
        token_file, ready_file = _private_path(args.scope_token_file), _private_path(args.ready_file)
        if token_file.stat().st_size > 64:
            raise ValueError('invalid scope token file')
        token = token_file.read_text(encoding='ascii').strip()
        if len(token) != 32 or any(not 33 <= ord(char) <= 126 for char in token):
            raise ValueError('invalid scope token file')
        policy = load_policy(POLICY_FILE)
        if (not live_ready(policy) or policy.max_attempts != 100 or policy.budget_microyuan != 10000000
                or policy.max_tokens != 2048 or policy.input_token_bound != 1000000
                or policy.max_body_bytes != 65536):
            raise ValueError('preview policy does not match reviewed bounds')
        usage_observer = make_usage_observer(args.usage_diagnostic_file) if args.usage_diagnostic_file else None
        credentials = _credentials(policy)
        ledger = Ledger(LEDGER_FILE)
        before = _budget(ledger)
        with httpx.Client(transport=httpx.HTTPTransport(retries=0, trust_env=False), trust_env=False,
                          follow_redirects=False, timeout=policy.timeout_seconds) as client:
            send = make_preview_transport(ledger, policy, client, credentials, deadline=deadline)
            handler = make_gateway_handler(ledger, policy, send, scope_token=token, usage_observer=usage_observer)
            with ThreadingHTTPServer(('127.0.0.1', 8765), handler) as server:
                server.daemon_threads = True
                ready = dict(status='ready', pid=os.getpid(), host='127.0.0.1', port=8765,
                             policy_sha256=hashlib.sha256(POLICY_FILE.read_bytes()).hexdigest(),
                             budget_before=before, fence=ensure_preview_fence(ledger))
                with ready_file.open('x', encoding='utf-8') as target:
                    target.write(json.dumps(ready))
                    target.flush()
                    os.fsync(target.fileno())
                remaining = deadline - time.monotonic() - 1
                if remaining <= 0:
                    raise TimeoutError('preview setup exceeded deadline')
                shutdown = Timer(remaining, server.shutdown)
                shutdown.daemon = True
                shutdown.start()
                print(json.dumps(ready), flush=True)
                server.serve_forever(poll_interval=0.05)
        print(json.dumps(dict(status='stopped', budget_before=before, budget_after=_budget(ledger))), flush=True)
        return 0
    except Exception:
        # Credential values, request bodies and exception context never escape.
        print(json.dumps(dict(status='blocked')), flush=True)
        return 1
    finally:
        if shutdown is not None:
            shutdown.cancel()
        hard_stop.cancel()


if __name__ == '__main__':
    raise SystemExit(main())
