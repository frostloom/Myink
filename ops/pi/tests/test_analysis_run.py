"""Durable host admission over real SQLite and loopback HTTP; no paid calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from http.server import ThreadingHTTPServer
from threading import Thread
import importlib
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from ops.pi.budget import totals
from ops.pi.ledger import Ledger, LedgerBlocked, OperationConflict
from ops.pi.tests.test_analysis_execution import prepared
from ops.pi.tests.test_budget import ledger, policy
from ops.pi import control
from ops.pi.tests.test_gateway_admission import HEADERS, TOKEN
from ops.pi.tests.test_model_gateway import transport
from ops.pi.tests.test_pi_gateway import PiStream


BINDING = dict(source_sha256='a' * 64, config_sha256='b' * 64)


def module():
    assert importlib.util.find_spec('ops.pi.analysis_run'), 'durable analysis run missing'
    return importlib.import_module('ops.pi.analysis_run')


def create(ledger, slots):
    return module().AnalysisRun.create(ledger, 'synthetic-run', slots, **BINDING)


def reopen(ledger, slots, **changes):
    return module().AnalysisRun.open(ledger, 'synthetic-run', slots, **(BINDING | changes))


def race_worker(path, slots, start, results):
    run = reopen(Ledger(Path(path)), slots)
    start.wait(10)
    try:
        results.put(run.guard(0)(slots[0]['request']))
    except OperationConflict:
        results.put(False)


def test_all_thirty_slots_persist_without_private_prose(tmp_path, ledger):
    slots, _, _ = prepared(tmp_path)
    run = create(ledger, slots)
    snapshot = run.snapshot()
    assert len(snapshot) == 30
    assert [r['slot_id'] for r in snapshot] == [s['slot_id'] for s in slots]
    assert {r['status'] for r in snapshot} == {'NOT_RUN'}
    assert reopen(Ledger(ledger.path), slots).snapshot() == snapshot
    with ledger.transaction() as db:
        stored = '\n'.join(row[0] for row in db.execute('SELECT payload FROM operations'))
    assert slots[0]['request']['messages'][0]['content'][0]['text'] not in stored
    assert totals(ledger, 'local-trial-1') == (0, 0)


@pytest.mark.parametrize('change', ['source', 'config', 'body', 'order', 'run'])
def test_identity_drift_cannot_reopen_or_reset(tmp_path, ledger, change):
    slots, _, _ = prepared(tmp_path)
    create(ledger, slots)
    other, binding = deepcopy(slots), BINDING.copy()
    run_id = 'synthetic-run'
    if change == 'source': binding['source_sha256'] = 'c' * 64
    if change == 'config': binding['config_sha256'] = 'c' * 64
    if change == 'body': other[0]['request']['max_tokens'] += 1
    if change == 'order': other[0], other[1] = other[1], other[0]
    if change == 'run': run_id = 'missing-run'
    with pytest.raises((ValueError, OperationConflict, LedgerBlocked)):
        module().AnalysisRun.open(ledger, run_id, other, **binding)
    with pytest.raises(OperationConflict): create(ledger, slots)


def test_guard_checks_body_and_order_before_consuming(tmp_path, ledger):
    slots, _, _ = prepared(tmp_path)
    run = create(ledger, slots)
    with pytest.raises(ValueError): run.guard(0)(slots[0]['request'] | {'metadata': {}})
    with pytest.raises(OperationConflict): run.guard(1)(slots[1]['request'])
    assert {r['status'] for r in run.snapshot()} == {'NOT_RUN'}
    assert run.guard(0)(slots[0]['request']) is True
    with pytest.raises(OperationConflict): run.guard(0)(slots[0]['request'])
    with pytest.raises(OperationConflict): run.guard(1)(slots[1]['request'])
    run.finish(0, status='done')
    assert run.guard(1)(slots[1]['request']) is True


def test_stale_guard_cannot_consume_later_identical_baseline(tmp_path, ledger):
    slots, _, _ = prepared(tmp_path)
    run = create(ledger, slots)
    old = run.guard(0)
    assert slots[0]['request'] == slots[2]['request']
    for index in (0, 1):
        assert run.guard(index)(slots[index]['request']) is True
        run.finish(index, status='done')
    with pytest.raises(OperationConflict): old(slots[0]['request'])
    assert run.snapshot()[2]['status'] == 'NOT_RUN'
    assert run.guard(2)(slots[2]['request']) is True


def test_thread_race_has_one_winner(tmp_path, ledger):
    slots, _, _ = prepared(tmp_path)
    create(ledger, slots)
    def claim(_):
        try: return reopen(ledger, slots).guard(0)(slots[0]['request'])
        except OperationConflict: return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(16)))
    assert results.count(True) == 1


def test_process_race_has_one_winner(tmp_path, ledger):
    slots, _, _ = prepared(tmp_path)
    create(ledger, slots)
    context = multiprocessing.get_context('spawn')
    start, results = context.Event(), context.Queue()
    workers = [context.Process(target=race_worker, args=(str(ledger.path), slots, start, results)) for _ in range(3)]
    for worker in workers: worker.start()
    start.set()
    try:
        answers = [results.get(timeout=20) for _ in workers]
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        assert answers.count(True) == 1
    finally:
        for worker in workers:
            if worker.is_alive(): worker.terminate()
            worker.join(5)
        results.close()


def test_process_exit_after_claim_stays_uncertain_and_blocks_progress(tmp_path, ledger):
    slots, _, _ = prepared(tmp_path)
    create(ledger, slots)
    fixture = tmp_path / 'synthetic.json'
    fixture.write_text(json.dumps(slots))
    code = '''import json, os, sys
from pathlib import Path
from ops.pi.ledger import Ledger
from ops.pi.analysis_run import AnalysisRun
slots=json.loads(Path(sys.argv[2]).read_text())
run=AnalysisRun.open(Ledger(Path(sys.argv[1])), 'synthetic-run', slots, source_sha256='a'*64, config_sha256='b'*64)
assert run.guard(0)(slots[0]['request']) is True
os._exit(23)
'''
    result = subprocess.run([sys.executable, '-c', code, str(ledger.path), str(fixture)], timeout=15)
    assert result.returncode == 23
    run = reopen(Ledger(ledger.path), slots)
    assert [r['status'] for r in run.snapshot()] == ['UNCERTAIN'] + ['NOT_RUN'] * 29
    for index in (0, 1):
        with pytest.raises(OperationConflict): run.guard(index)(slots[index]['request'])


@pytest.mark.parametrize('status', ['done', 'failed', 'uncertain', 'blocked'])
def test_results_require_claim_and_keep_terminal_history(tmp_path, ledger, status):
    slots, _, _ = prepared(tmp_path)
    run = create(ledger, slots)
    with pytest.raises(OperationConflict): run.finish(0, status=status)
    assert run.guard(0)(slots[0]['request']) is True
    run.finish(0, status=status)
    run.finish(0, status=status)
    assert reopen(ledger, slots).snapshot()[0]['status'] == status.upper()
    with pytest.raises(OperationConflict): run.finish(0, status='failed' if status == 'done' else 'done')
    if status in ('done', 'failed'):
        assert run.guard(1)(slots[1]['request']) is True
    else:
        with pytest.raises(OperationConflict): run.guard(1)(slots[1]['request'])


@pytest.mark.parametrize('index', [-1, 30, True, '0'])
def test_invalid_index_never_claims(tmp_path, ledger, index):
    slots, _, _ = prepared(tmp_path)
    run = create(ledger, slots)
    with pytest.raises(ValueError): run.guard(index)
    with pytest.raises(ValueError): run.finish(index, status='done')
    assert {r['status'] for r in run.snapshot()} == {'NOT_RUN'}


def test_input_mutation_cannot_retarget_existing_guard(tmp_path, ledger):
    slots, _, _ = prepared(tmp_path)
    original = deepcopy(slots)
    run = create(ledger, slots)
    slots[0]['request']['max_tokens'] += 1
    with pytest.raises(ValueError): run.guard(0)(slots[0]['request'])
    assert run.guard(0)(original[0]['request']) is True


def test_unavailable_storage_fails_closed(tmp_path, ledger):
    slots, _, _ = prepared(tmp_path)
    run = create(ledger, slots)
    ledger.path.rename(tmp_path / 'moved.sqlite')
    with pytest.raises((LedgerBlocked, OperationConflict)): run.guard(0)(slots[0]['request'])


@contextmanager
def gateway(ledger, policy, guard, calls):
    def provider(request):
        calls.append(json.loads(request.content))
        assert totals(ledger, 'local-trial-1') == (1, 18384)
        return httpx.Response(200, stream=PiStream(dict(input_tokens=7, output_tokens=0,
            cache_read_input_tokens=0, cache_creation_input_tokens=0)))
    handler = control.make_gateway_handler(ledger, policy, transport(provider),
        scope_token=TOKEN, request_guard=guard)
    with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
        server.daemon_threads = True
        worker = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        worker.start()
        try:
            with httpx.Client(trust_env=False, timeout=3) as client:
                yield client, 'http://127.0.0.1:' + str(server.server_port)
        finally:
            server.shutdown()
            worker.join(3)


def test_http_replay_is_denied_before_second_reservation(tmp_path, ledger, policy):
    slots, _, _ = prepared(tmp_path)
    # Gateway fixture uses a smaller output ceiling than the real frozen slots.
    from dataclasses import replace
    policy = replace(policy, max_tokens=2048)
    run, calls = create(ledger, slots), []
    with gateway(ledger, policy, run.guard(0), calls) as (client, base):
        response = client.post(base + '/v1/messages', headers=HEADERS, json=slots[0]['request'])
        assert response.status_code == 200
        assert totals(ledger, 'local-trial-1') == (1, 54)
        run.finish(0, status='done')
        response = client.post(base + '/v1/messages', headers=HEADERS, json=slots[0]['request'])
        assert response.status_code == 403
    with gateway(ledger, policy, reopen(Ledger(ledger.path), slots).guard(0), calls) as (client, base):
        assert client.post(base + '/v1/messages', headers=HEADERS, json=slots[0]['request']).status_code == 403
    assert len(calls) == 1 and totals(ledger, 'local-trial-1') == (1, 54)


@pytest.mark.parametrize('same_run', [True, False])
def test_gateway_token_cannot_authorize_a_different_slot_or_run(tmp_path, ledger, policy, same_run):
    slots, _, _ = prepared(tmp_path)
    run = create(ledger, slots)
    token = 'synthetic-slot-token-' + 'a' * 32
    run.gateway_handler(0, policy, lambda *_: None, scope_token=token)
    if not same_run:
        run = module().AnalysisRun.create(ledger, 'second-run', slots, **BINDING)
    with pytest.raises(OperationConflict):
        run.gateway_handler(1 if same_run else 0, policy, lambda *_: None, scope_token=token)


@pytest.mark.parametrize('token', [None, '', 'short', 'x' * 4097, 'a' * 32 + '\n'])
def test_gateway_requires_bounded_private_slot_token(tmp_path, ledger, policy, token):
    slots, _, _ = prepared(tmp_path)
    run = create(ledger, slots)
    with pytest.raises(ValueError):
        run.gateway_handler(0, policy, lambda *_: None, scope_token=token)
    assert {r['status'] for r in run.snapshot()} == {'NOT_RUN'}


def test_http_old_packet_cannot_consume_identical_later_slot(tmp_path, ledger, policy):
    from dataclasses import replace
    slots, _, _ = prepared(tmp_path)
    run = create(ledger, slots)
    assert slots[0]['request'] == slots[2]['request']
    token0, token2 = 'synthetic-old-' + 'a' * 32, 'synthetic-new-' + 'b' * 32
    run.gateway_handler(0, policy, lambda *_: None, scope_token=token0)
    for index in (0, 1):
        run.guard(index)(slots[index]['request'])
        run.finish(index, status='done')
    calls = []
    def provider(request):
        calls.append(request)
        return httpx.Response(200, stream=PiStream(dict(input_tokens=7, output_tokens=0,
            cache_read_input_tokens=0, cache_creation_input_tokens=0)))
    handler = run.gateway_handler(2, replace(policy, max_tokens=2048),
        transport(provider), scope_token=token2)
    with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
        worker = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        worker.start()
        try:
            with httpx.Client(trust_env=False, timeout=3) as client:
                url = 'http://127.0.0.1:' + str(server.server_port) + '/v1/messages'
                for token, expected in [(token0, 403), (token2, 200), (token2, 403)]:
                    response = client.post(url, headers=HEADERS | {'x-api-key': token}, json=slots[0]['request'])
                    assert response.status_code == expected
        finally:
            server.shutdown()
            worker.join(3)
    assert len(calls) == 1 and totals(ledger, 'local-trial-1') == (1, 54)
    assert run.snapshot()[2]['status'] == 'UNCERTAIN'
