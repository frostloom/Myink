"""Explicit host-owned one- or two-slot pilot. Default check never authorizes spending.

A pinned evidence record is a host review declaration, not an online price,
credential, usage or billing certificate. This module is never a model tool.
"""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
from http.server import ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import stat
import subprocess
from threading import Thread
import time
import uuid

import httpx

from .analysis_execution import _hash, prepare_contract_slots
from .analysis_preflight import audit
from .analysis_run import AnalysisRun
from .analysis_trial import GROUPS
from .container_probe import ProbeHost, _path, _write, verify_inspect
from .container_runtime import exchange, strict_json, verify_result, verify_source, INITIAL_FRAME_LIMIT
from .control import live_ready
from .ledger import Ledger, LedgerBlocked
from .policy import load_policy
from .provider_config import DEFAULT_MODEL, DEEPSEEK_BASE_URL, load_credentials
from .usage_diagnostics import make_usage_observer


_FIELDS = set('schema ledger_path policy_path credential_path input_path evidence_path root source docker '
    'endpoint daemon_id image_id runtime_sha256 expected_code_sha256 expected_input_sha256 '
    'expected_evidence_sha256 expected_scope_sha256 expected_policy_sha256 run_id cap_microyuan deadline'.split())
_ERROR = 'analysis launch blocked'


def _read(path, limit=1048576):
    path = _path(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(_ERROR)
    with path.open('rb') as file:
        raw = file.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(_ERROR)
    return raw


def _evidence(config):
    value = strict_json(_read(config['evidence_path']))
    if (not isinstance(value, dict) or set(value) != {
            'schema', 'policy_sha256', 'review_reference', 'valid_until', 'price', 'input_bound'}
            or value['schema'] != 'pi-provider-evidence-v1'
            or _hash(value) != config['expected_evidence_sha256']
            or value['policy_sha256'] != config['expected_policy_sha256']
            or not isinstance(value['review_reference'], str)
            or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', value['review_reference'])
            or type(value['valid_until']) not in (int, float) or not math.isfinite(value['valid_until'])
            or config['deadline'] > value['valid_until']):
        raise ValueError(_ERROR)
    for kind in ('price', 'input_bound'):
        source = value[kind]
        if (not isinstance(source, dict) or set(source) != {'path', 'sha256'}
                or sha256(_read(source['path'])).hexdigest() != source['sha256']):
            raise ValueError(_ERROR)


def _initial(config, inputs, slot, index, token):
    return dict(slot_index=index, token=token, slot=slot, view=inputs['views'][slot['domain']],
                report=inputs['report'], deadline=min(config['deadline'], time.time() + 45))


def _selected_count(config):
    return 2 if config['schema'] == 'pi-analysis-launch-v1' else config['selected_slots']


def _prepare(config):
    config = strict_json(json.dumps(config, allow_nan=False))  # Caller cannot mutate this run.
    if (not isinstance(config, dict) or config.get('schema') not in ('pi-analysis-launch-v1', 'pi-analysis-launch-v2')
            or set(config) != (_FIELDS | {'selected_slots'} if config['schema'] == 'pi-analysis-launch-v2' else _FIELDS)
            or (config['schema'] == 'pi-analysis-launch-v2' and (type(config['selected_slots']) is not int
                or config['selected_slots'] not in (1, 2)))
            or type(config['cap_microyuan']) is not int or not 0 < config['cap_microyuan'] <= 20000000
            or type(config['deadline']) not in (int, float) or not math.isfinite(config['deadline'])
            or not 0 < config['deadline'] - time.time() <= 600
            or not isinstance(config['run_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', config['run_id'])):
        raise ValueError(_ERROR)
    for key in _FIELDS:
        if key.endswith('sha256') and (not isinstance(config[key], str) or not re.fullmatch('[0-9a-f]{64}', config[key])):
            raise ValueError(_ERROR)
    for key in ('root', 'source', 'ledger_path', 'policy_path', 'credential_path', 'input_path', 'evidence_path', 'docker'):
        _path(config[key])
    root = Path(config['root'])
    if root.exists() or not root.parent.is_dir():
        raise ValueError(_ERROR)
    credential = Path(config['credential_path'])
    if (stat.S_IMODE(credential.stat().st_mode) != 0o600
            or stat.S_IMODE(credential.parent.stat().st_mode) != 0o700):
        raise ValueError(_ERROR)
    _read(config['policy_path']); _read(credential)
    policy = load_policy(Path(config['policy_path']))
    if (_hash(asdict(policy)) != config['expected_policy_sha256']
            or policy.model != DEFAULT_MODEL or policy.base_url != DEEPSEEK_BASE_URL or policy.protocol != 'anthropic'):
        raise ValueError(_ERROR)
    credentials = load_credentials(credential, policy)
    _evidence(config)
    inputs = strict_json(_read(config['input_path']))
    if not isinstance(inputs, dict) or set(inputs) != {'views', 'report'} or _hash(inputs) != config['expected_input_sha256']:
        raise ValueError(_ERROR)
    slots = prepare_contract_slots(inputs['views'], inputs['report'], model=DEFAULT_MODEL, cwd=Path('/work/candidate'))
    for index, slot in enumerate(slots[:_selected_count(config)]):
        if len(json.dumps(_initial(config, inputs, slot, index, 'a'*64), ensure_ascii=True).encode()) + 1 > INITIAL_FRAME_LIMIT:
            raise ValueError(_ERROR)
    provenance = verify_source(Path(config['source']), config['runtime_sha256'])
    if provenance['code_sha256'] != config['expected_code_sha256']:
        raise ValueError(_ERROR)
    diagnostic = audit(Path(config['ledger_path']), Path(config['policy_path']),
        credential_path=credential, expected_scope_sha256=config['expected_scope_sha256'],
        expected_policy_sha256=config['expected_policy_sha256'])
    reserve = diagnostic['policy']['max_request_reserved_microyuan']
    if (reserve is None or config['cap_microyuan'] < reserve
            or config['cap_microyuan'] > diagnostic['accounting']['conservative_remaining_microyuan']
            or diagnostic['accounting']['pending_attempts']):
        raise ValueError(_ERROR)
    host = ProbeHost(docker=Path(config['docker']), endpoint=config['endpoint'],
        daemon_id=config['daemon_id'], image_id=config['image_id'], operation_id=str(uuid.uuid4()))
    return config, policy, credentials, inputs, slots, provenance, diagnostic, host


@contextmanager
def _provider(policy, credentials):
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=policy.timeout_seconds) as client:
        def send(body, timeout):
            request = client.build_request('POST', policy.base_url + '/v1/messages', json=body,
                headers={'x-api-key': credentials['PLATFORM_MODEL_API_KEY'], 'anthropic-version': '2023-06-01', 'accept-encoding': 'identity'}, timeout=timeout)
            return client.send(request, stream=True, follow_redirects=False)
        yield send


def _known_attempt(run, index):
    with run.ledger.transaction() as db:
        rows = [row for row in db.execute("SELECT * FROM operations WHERE kind='model-attempt'")
                if Ledger._decode(row['payload']).get('analysis_run_id') == run._identity['run_id']
                and Ledger._decode(row['payload']).get('analysis_slot_index') == index]
        if (len(rows) != 1 or rows[0]['status'] != 'done'
                or Ledger._decode(rows[0]['evidence']).get('usage_known') is not True):
            raise LedgerBlocked(_ERROR)


def _slot(run, policy, config, inputs, slot, index, host, transport, root, provenance, progress):
    token = uuid.uuid4().hex + uuid.uuid4().hex
    remaining = lambda: config['deadline'] - time.time()
    if remaining() <= 0 or _hash(verify_source(Path(config['source']), config['runtime_sha256'])) != _hash(provenance):
        raise ValueError(_ERROR)
    row = dict(slot_index=index, slot_id=slot['slot_id'], http_statuses=[])
    observer = make_usage_observer(root/f'slot-{index}-usage-private.jsonl', slot_index=index)
    handler = run.gateway_handler(index, policy, transport, scope_token=token, usage_observer=observer)
    with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
        server.daemon_threads = True
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True); thread.start()
        process = None
        slot_failed = False
        try:
            progress['stage'] = 'container_create'
            cid = host.create('isolation', worker=Path(__file__).parent/'lab/container_runtime_worker.py',
                source=Path(config['source']), foreign=root/'not-mounted', interactive=True)
            progress['stage'] = 'container_inspect'
            if not verify_inspect(host.inspect(cid)) or remaining() <= 0:
                raise ValueError(_ERROR)
            progress['stage'] = 'container_attach'
            process = subprocess.Popen(host.command + ['start', '-a', '-i', cid], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            with httpx.Client(trust_env=False, follow_redirects=False) as client:
                def route(frame, seconds):
                    from .relay_stream import ReplyStream, response_frames, CHUNK_LIMIT
                    def frames():
                        progress.update(stage='relay', reason='stage_failed', response_bytes=0, http_status=None)
                        timeout = min(seconds, remaining())
                        if timeout <= 0:
                            progress['reason'] = 'deadline_exceeded'
                            raise TimeoutError(_ERROR)
                        with client.stream('POST', f'http://127.0.0.1:{server.server_port}' + frame['path'],
                                headers=frame['headers'], content=frame['body'].encode(), timeout=timeout) as reply:
                            progress['http_status'] = reply.status_code
                            yield from response_frames(reply.status_code, reply.iter_bytes(chunk_size=CHUNK_LIMIT), remaining, progress)
                            row['http_statuses'].append(reply.status_code)
                            progress.update(stage='exchange', reason='stage_failed')
                    return ReplyStream(frames())
                progress['stage'] = 'exchange'
                with (root/f'slot-{index}-attach-private.log').open('xb') as evidence:
                    frame = exchange(process, _initial(config, inputs, slot, index, token), route,
                        seconds=min(60, remaining()), evidence=evidence)
            progress['stage'] = 'result_write'
            _write(root/f'slot-{index}-private.json', frame)
            progress['stage'] = 'result_verify'
            row.update(verify_result(frame, slot, inputs['views'][slot['domain']], inputs['report']))
            progress['stage'] = 'http_sequence'
            if row['http_statuses'] != [403, 403, 200, 403] or remaining() <= 0:
                raise ValueError(_ERROR)
            progress['stage'] = 'usage_check'
            _known_attempt(run, index)
            return row, cid
        except Exception:
            slot_failed = True
            raise
        finally:
            try:
                try:
                    if process is not None:
                        try:
                            if process.poll() is None:
                                host.stop(cid)
                        finally:
                            if process.poll() is None:
                                process.kill()
                            process.wait(timeout=3)
                            process.stdin.close(); process.stdout.close()
                finally:
                    server.shutdown(); thread.join(2)
            except Exception:
                if not slot_failed:
                    progress.update(stage='slot_cleanup', reason='stage_failed')
                    raise  # Preserve an active primary failure and its bounded detail.


def launch(config, *, execute=False):
    """Check by default. Only explicit trusted-host execution can mutate state.

    All thirty slots are registered; the manifest selects the first one or pair.
    A failed invocation is never resumed or retried by this entry point.
    """
    try:
        if type(execute) is not bool:
            raise ValueError(_ERROR)
        config, policy, credentials, inputs, slots, provenance, diagnostic, host = _prepare(config)
        result = dict(status='checked', execution_requested=execute, launch_ready=live_ready(policy),
            planned_slots=30, selected_slots=_selected_count(config), production_ready=False, automatic_execution=False,
            billing_verified=False, usage_diagnostics='best_effort_private',
            config_sha256=_hash(config), provenance=provenance, failure_detail=None,
            preflight=diagnostic, cases=[], cleanup=[])
        if not execute:
            return result
        if not live_ready(policy):
            raise LedgerBlocked(_ERROR)
        ledger = Ledger(Path(config['ledger_path']), existing=True)
        run = AnalysisRun.create(ledger, config['run_id'], slots,
            source_sha256=_hash(provenance), config_sha256=_hash(config))
        run.bind_budget(policy, cap_microyuan=config['cap_microyuan'], deadline=config['deadline'])
        root = Path(config['root']); root.mkdir(mode=0o700)
    except Exception:
        raise LedgerBlocked(_ERROR) from None
    result.update(status='blocked', operation_id=host.operation_id, failure_class=None)
    index = 0
    progress = dict(slot_index=0, stage='provider_setup', reason='stage_failed', response_bytes=0, http_status=None)
    try:
        with _provider(policy, credentials) as transport:
            for index, slot in enumerate(slots[:_selected_count(config)]):
                progress = dict(slot_index=index, stage='source_check', reason='stage_failed', response_bytes=0, http_status=None)
                row, cid = _slot(run, policy, config, inputs, slot, index, host, transport, root, provenance, progress)
                progress['stage'] = 'session_unique'
                if any(previous['session_id'] == row['session_id'] for previous in result['cases']):
                    raise ValueError(_ERROR)
                result['cases'].append(row)
                progress['stage'] = 'container_cleanup'
                cleaned = host.cleanup(cid); result['cleanup'].append(cleaned)
                if cleaned['exit_code'] != 0:
                    raise ValueError(_ERROR)
                progress['stage'] = 'slot_finish'
                run.finish(index, status='done')
            result['status'] = 'completed'
    except Exception as exc:
        result['failure_class'] = type(exc).__name__
        result['failure_detail'] = dict(progress)
        try:
            if run.snapshot()[index]['status'] == 'UNCERTAIN':
                run.finish(index, status='uncertain')
        except Exception:
            pass  # Preserve the durable claim rather than inventing an outcome.
    finally:
        try:
            host.reconcile()
        except Exception as exc:
            result['status'] = 'blocked'
            if result['failure_detail'] is None:
                result['failure_class'] = type(exc).__name__
                result['failure_detail'] = dict(progress, stage='container_reconcile', reason='stage_failed')
        for name, mode in host.pending.items():
            result['cleanup'].append(dict(name=name, mode=mode, removed=False, operation_id=host.operation_id))
        for cid in list(host.owned):
            try:
                result['cleanup'].append(host.cleanup(cid))
            except Exception as exc:
                result['cleanup'].append(dict(container_id=cid, removed=False, failure_class=type(exc).__name__))
        if any(not row.get('removed') for row in result['cleanup']):
            result['status'] = 'blocked'
            if result['failure_detail'] is None:
                result['failure_detail'] = dict(progress, stage='container_cleanup', reason='stage_failed')
        try:
            result['slots'] = run.snapshot()
            _write(root/'receipt.json', result)
        except Exception:
            raise LedgerBlocked(_ERROR) from None
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = launch(strict_json(_read(args.config, 65536)), execute=args.execute)
    except Exception:
        print(json.dumps(dict(status='blocked', error=_ERROR)))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] in ('checked', 'completed') else 2


if __name__ == '__main__':
    raise SystemExit(main())
