"""Actual installed Pi, two synthetic contract slots, loopback-only SSE.

No provider client, credential file, canonical ledger or paid-run grant is used.
This probe proves process/wire compatibility, not production containment.
"""
import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

from ops.pi.analysis_execution import (
    MODEL, prepare_contract_slots, run_contract_slot, verify_contract_request,
)
from ops.pi.analysis_trial import GROUPS
from ops.pi.engine import EngineSession
from ops.pi.pi_config import make_pi_config
from ops.pi.pi_rpc import PiAdapter
from ops.pi.writing_analysis import DOMAINS, SYSTEM_PROMPT, _json
from ops.pi.writing_evidence import _quality_catalog, _unique_pairs


MOCK_TOKEN = 'local-contract-probe-only'


def synthetic_inputs():
    source = dict(table='agent_runs', id=1, fingerprint='c'*64, node='write', path='trace.response.content')
    view = dict(schema_version=1, dataset_id='a'*64, dataset_sha256='b'*64,
        untrusted_body_text=True, window=dict(start='synthetic-start', end='synthetic-end'),
        evidence=[dict(category='write', source=source, excerpts=[dict(start_byte=0, end_byte=5, text='start')])],
        limits=dict(omitted_evidence=0), limitations=['synthetic; not real writing quality'],
        table_coverage={}, tasks=[], short_sessions=[], source_provenance='synthetic')
    report = dict(dataset_id=view['dataset_id'], dataset_sha256=view['dataset_sha256'],
        window=view['window'], sources=dict(agent_runs=[dict(id=1, fingerprint='c'*64)]),
        quality_catalog=_quality_catalog(), operations={})
    return view, report


def synthetic_answer():
    return dict(domains=[dict(domain=d, availability='unknown', observation='Synthetic probe only', refs=[])
                         for d in DOMAINS],
        hypothesis=dict(change='Verify existing output validation',
            refs=[dict(evidence_index=0, excerpt_index=0, quote='start')],
            baseline=dict(availability='unknown', reason='Synthetic protocol probe'),
            metrics=['Invalid output ratio'], tests=['Boundary regression'],
            rollback='Restore previous validation', risks=['False rejection']),
        owner_decision=dict(new_features_require_owner=True))


def accept_probe_request(bind, path, headers, body, state):
    state['attempts'] += 1
    headers = {k.lower(): v for k, v in headers.items()}
    if (bind != '127.0.0.1' or path != '/v1/messages?beta=true'
            or headers.get('x-api-key') != MOCK_TOKEN
            or headers.get('x-pi-scope') != 'local-trial-1'
            or state['attempts'] != 1):
        raise ValueError('single loopback mock request required')
    digest = verify_contract_request(body, state['slot'])
    state['accepted'] += 1
    return digest


def _write(path, value):
    # Private evidence may contain Unicode; ASCII serialization retains surrogates.
    with path.open('x', encoding='utf-8') as output:
        output.write(json.dumps(value, ensure_ascii=True, indent=2) + '\n')


def _handler(state, root):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            self.connection.settimeout(5)
            state['http_attempts'] += 1
            if state['current'] is not None:
                current = state['current']
                current['http_attempts'] = current.get('http_attempts', 0) + 1
            try:
                length = self.headers.get('Content-Length', '')
                if (not length.isascii() or not length.isdigit() or not 0 < int(length) <= 65536
                        or self.headers.get('Transfer-Encoding')):
                    raise ValueError('bounded content length required')
                body = json.loads(self.rfile.read(int(length)), object_pairs_hook=_unique_pairs)
                current = state['current']
                accept_probe_request(self.server.server_address[0], self.path, self.headers, body, current)
                _write(root / (current['slot']['slot_id'].replace(':', '-') + '-wire.json'), body)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Connection', 'close')
                self.end_headers()
                text = json.dumps(synthetic_answer(), ensure_ascii=False)
                events = [dict(type='message_start', message=dict(id='msg_contract_probe',
                    type='message', role='assistant', model=MODEL, content=[], stop_reason=None,
                    stop_sequence=None, usage=dict(input_tokens=17, output_tokens=0,
                        cache_read_input_tokens=0, cache_creation_input_tokens=0))),
                    dict(type='content_block_start', index=0, content_block=dict(type='text', text='')),
                    dict(type='content_block_delta', index=0, delta=dict(type='text_delta', text=text)),
                    dict(type='content_block_stop', index=0),
                    dict(type='message_delta', delta=dict(stop_reason='end_turn', stop_sequence=None),
                         usage=dict(output_tokens=100)), dict(type='message_stop')]
                for event in events:
                    self.wfile.write(('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode())
                    self.wfile.flush()
            except (ValueError, OSError, KeyError, TypeError):
                state['rejected'] += 1
                self.send_error(400)
            finally:
                self.close_connection = True
    return Handler


def _check_probe_paths(root, node, cli):
    if os.name != 'posix' or os.getuid() == 0:
        raise ValueError('nonroot Linux probe required')
    paths = (root, node, cli)
    if any(not p.is_absolute() or '..' in p.parts or
           any(x.is_symlink() for x in (p, *p.parents)) for p in paths):
        raise ValueError('absolute unlinked host-selected probe paths required')
    # The host must verify the named WSL distro is stored on E: before native use.
    allowed_root = root.is_relative_to('/mnt/e') or root.is_relative_to(
        '/opt/myink-pi-lab/analysis-contract-probes')
    if (not allowed_root or root.exists() or not node.is_file()
            or not cli.is_file() or json.loads((cli.parents[2] / 'package.json').read_bytes())['version'] != '1.1.0'):
        raise ValueError('fresh E-drive root and installed Pi1.1.0 required')


def run_probe(root, node, cli):
    _check_probe_paths(root, node, cli)
    root.mkdir(parents=True, mode=0o700)
    cwd = root / 'candidate'
    cwd.mkdir()
    view, report = synthetic_inputs()
    slots = prepare_contract_slots({d: view for d in GROUPS}, report, model=MODEL, cwd=cwd)
    _write(root / 'private-slots.json', slots)
    state = dict(current=None, rejected=0, http_attempts=0)
    server = HTTPServer(('127.0.0.1', 0), _handler(state, root))
    thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
    thread.start()
    results = []
    public = dict(mode='ACTUAL_PI_LOCAL_MOCK', planned_slots=30,
        selected_probe_slots=2, paid_http_requests=0, canonical_ledger_modified=False,
        semantic_metrics='unknown', automatic_execution=False, release_allowed=False,
        production_containment_verified=False, uid=os.getuid(), gid=os.getgid(),
        node_sha256=sha256(node.read_bytes()).hexdigest(), cli_sha256=sha256(cli.read_bytes()).hexdigest())
    try:
        config = make_pi_config(root, dict(base_url=f'http://127.0.0.1:{server.server_port}',
            scope_token=MOCK_TOKEN), SimpleNamespace(model=MODEL, max_tokens=2048))
        config['args'] += ['--system-prompt', SYSTEM_PROMPT]
        for name, value in config['env'].items():
            if name not in ('PI_TELEMETRY', 'PI_OFFLINE', 'SCOPED_GATEWAY_TOKEN'):
                Path(value).mkdir(parents=True, exist_ok=True)
        agent = Path(config['env']['PI_CODING_AGENT_DIR'])
        _write(agent / 'settings.json', config['settings'])
        _write(agent / 'models.json', config['models'])
        guard = Path(__file__).with_name('pi-wire-guard.mjs')
        config_hash = sha256(_json({k: v for k, v in config.items() if k != 'env'}).encode()
                             + guard.read_bytes()).hexdigest()
        env = {**config['env'], 'PATH': str(node.parent) + ':/usr/bin:/bin', 'LANG': 'C.UTF-8'}
        command = [str(node), str(cli), *config['args']]
        for slot_index, slot in enumerate(slots[:2]):
            state['current'] = dict(slot=slot, attempts=0, accepted=0, http_attempts=0)
            row = dict(slot_id=slot['slot_id'], execution_state='started', engine_status=None,
                contract_valid=False, failure_class=None, mock_attempts=0, mock_accepted=0,
                request_sha256=slot['request_sha256'], system_sha256=slot['system_sha256'])
            results.append(row)
            try:
                path = root / 'sessions' / (slot['slot_id'].replace(':', '-') + '.jsonl')
                engine = PiAdapter(command, cwd=cwd, env=env, config_hash=config_hash)
                result = run_contract_slot(slot_index=slot_index, slot=slot, view=view, report=report, engine=engine,
                    session=EngineSession('pi', config_hash, 'analysis', path), model=MODEL, cwd=cwd,
                    deadline=datetime.now(timezone.utc) + timedelta(seconds=60))
                receipt_path = root / (slot['slot_id'].replace(':', '-') + '-receipt.json')
                _write(receipt_path, result)
                e = result['evidence']
                row.update(execution_state='returned', engine_status=result['engine_status'],
                    contract_valid=result['contract_valid'], session_sha256=e.get('session_sha256'),
                    process_exited=e.get('process_exited'), returncode=e.get('returncode'),
                    clear_abort_acknowledged=e.get('clear_abort_acknowledged'),
                    owned_pid=e.get('owned_pid'), receipt_sha256=sha256(receipt_path.read_bytes()).hexdigest())
            except Exception as exc:
                # No exception message or source text enters the public summary.
                known = ('ValueError', 'TypeError', 'KeyError', 'OSError', 'RuntimeError',
                         'PermissionError', 'FileExistsError', 'TimeoutError')
                row.update(execution_state='failed', failure_class=(
                    type(exc).__name__ if type(exc).__name__ in known else 'Exception'))
            finally:
                row.update(mock_attempts=state['current']['http_attempts'],
                           mock_accepted=state['current']['accepted'])
            if not row['contract_valid'] or row['mock_attempts'] != 1 or row['mock_accepted'] != 1:
                break
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        public.update(results=results, rejected_mock_requests=state['rejected'],
            not_run_slots=30-len(results), started_probe_slots=len(results),
            completed_probe_slots=sum(r['execution_state'] == 'returned' for r in results),
            actual_mock_http_requests=state['http_attempts'],
            passed=len(results) == 2 and state['rejected'] == 0 and all(
                r['contract_valid'] and r['mock_attempts'] == r['mock_accepted'] == 1
                for r in results))
        public['stop_reason'] = (None if public['passed'] else 'slot_exception'
            if any(r['failure_class'] for r in results) else 'slot_not_valid'
            if results else 'setup_incomplete')
        _write(root / 'probe-summary.json', public)
    return public


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'node', 'pi-cli'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = run_probe(args.root, args.node, args.pi_cli)
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
