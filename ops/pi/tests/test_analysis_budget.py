"""Host run limits over the canonical ledger; synthetic requests only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from http.server import ThreadingHTTPServer
from threading import Event, Thread
import importlib
import multiprocessing
import time

import httpx
import pytest

from ops.pi import budget
from ops.pi.analysis_run import AnalysisRun
from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger, OperationConflict
from ops.pi.model_gateway import forward_messages
from ops.pi.tests.test_analysis_execution import prepared
from ops.pi.tests.test_analysis_run import BINDING
from ops.pi.tests.test_budget import ledger, policy
from ops.pi.tests.test_budget_amendment import snapshot
from ops.pi.tests.test_fee_only_budget import seeded, upgrade, fee_policy
from ops.pi.tests.test_pi_gateway import PiStream


def bind(run, policy, cap=100000, deadline=None):
    api = getattr(run, 'bind_budget', None)
    assert callable(api), 'host run budget binding missing'
    return api(policy, cap_microyuan=cap, deadline=time.time() + 60 if deadline is None else deadline)


def context(run, index=0):
    return importlib.import_module('ops.pi.analysis_budget').AnalysisBudgetSlot(run, index)


@pytest.fixture
def setup_run(tmp_path, ledger, policy):
    slots, _, _ = prepared(tmp_path)
    seeded(ledger); upgrade(ledger)
    p = replace(fee_policy(policy), max_tokens=2048)
    run = AnalysisRun.create(ledger, 'bound-run', slots, **BINDING)
    return run, slots, p


def attempt(run, slots, policy, index=0):
    return budget.reserve(run.ledger, 'local-trial-1', slots[index]['request'], policy,
                          analysis_slot=context(run, index))


def known(ledger, permit):
    budget.settle(ledger, permit, dict(input_tokens=7, output_tokens=5,
        cache_read_input_tokens=0, cache_creation_input_tokens=0))


def test_binding_requires_original_approved_scope(tmp_path, ledger, policy):
    slots, _, _ = prepared(tmp_path)
    run = AnalysisRun.create(ledger, 'empty-scope', slots, **BINDING)
    before = snapshot(ledger)
    with pytest.raises(budget.BudgetDenied): bind(run, fee_policy(policy))
    assert snapshot(ledger) == before


def test_binding_requires_fee_only_amendment(tmp_path, ledger, policy):
    seeded(ledger)
    slots, _, _ = prepared(tmp_path)
    run = AnalysisRun.create(ledger, 'not-upgraded', slots, **BINDING)
    with pytest.raises(budget.BudgetDenied): bind(run, fee_policy(policy))


@pytest.mark.parametrize('cap,deadline', [(True, None), (0, None), (-1, None),
    (20000001, None), (1.0, None), (100000, True), (100000, float('nan')),
    (100000, float('inf')), (100000, 1)])
def test_invalid_limits_rejected_without_mutation(setup_run, cap, deadline):
    run, _, p = setup_run
    before = snapshot(run.ledger)
    with pytest.raises((ValueError, budget.BudgetDenied)): bind(run, p, cap, deadline)
    assert snapshot(run.ledger) == before


def test_reopen_preserves_limits_and_rejects_reset(setup_run):
    run, slots, p = setup_run
    deadline = time.time() + 60
    bind(run, p, 18384, deadline)
    before = snapshot(run.ledger)
    reopened = AnalysisRun.open(Ledger(run.ledger.path), 'bound-run', slots, **BINDING)
    bind(reopened, p, 18384, deadline)
    assert snapshot(run.ledger) == before
    for cap, end in [(18385, deadline), (18384, deadline + 1)]:
        with pytest.raises(OperationConflict): bind(reopened, p, cap, end)
    reopened.guard(0)(slots[0]['request'])
    permit = attempt(reopened, slots, p)
    assert permit.reserved_microyuan == 18384
    with pytest.raises(budget.BudgetDenied): attempt(reopened, slots, p)
    assert budget.totals(run.ledger, 'local-trial-1') == (1, 18384)


def test_cannot_bind_after_any_claim(setup_run):
    run, slots, p = setup_run
    run.guard(0)(slots[0]['request'])
    with pytest.raises(OperationConflict): bind(run, p)


def test_canonical_attempt_requires_claim_and_exact_body(setup_run):
    run, slots, p = setup_run
    bind(run, p)
    with pytest.raises(budget.BudgetDenied): attempt(run, slots, p)
    run.guard(0)(slots[0]['request'])
    with pytest.raises(budget.BudgetDenied):
        budget.reserve(run.ledger, 'local-trial-1', slots[0]['request'] | {'max_tokens': 10},
                       p, analysis_slot=context(run))
    assert budget.totals(run.ledger, 'local-trial-1') == (0, 0)


@pytest.mark.parametrize('change', [dict(prices={'input':'0','output':'0','cache_read':'0','cache_write':None}),
    dict(input_token_bound=1), dict(timeout_seconds=121), dict(base_url='https://other.example'),
    dict(live_enabled=True)])
def test_frozen_policy_drift_cannot_reserve(setup_run, change):
    run, slots, p = setup_run
    bind(run, p)
    run.guard(0)(slots[0]['request'])
    with pytest.raises(budget.BudgetDenied): attempt(run, slots, replace(p, **change))
    assert budget.totals(run.ledger, 'local-trial-1') == (0, 0)


def test_caller_mutation_of_nested_policy_does_not_change_frozen_policy(setup_run):
    run, slots, p = setup_run
    bind(run, p)
    run.guard(0)(slots[0]['request'])
    p.prices['output'] = '0'
    with pytest.raises(budget.BudgetDenied): attempt(run, slots, p)


def test_known_cost_releases_only_this_runs_unused_reserve(setup_run):
    run, slots, p = setup_run
    # 18,384 worst-case per slot; known first usage is 54.
    bind(run, p, 18437)
    run.guard(0)(slots[0]['request'])
    first = attempt(run, slots, p)
    known(run.ledger, first)
    run.finish(0, status='done')
    run.guard(1)(slots[1]['request'])
    with pytest.raises(budget.BudgetDenied): attempt(run, slots, p, 1)
    assert budget.totals(run.ledger, 'local-trial-1') == (1, 54)


def test_exact_run_cap_allows_boundary_after_known_usage(setup_run):
    run, slots, p = setup_run
    bind(run, p, 18438)
    run.guard(0)(slots[0]['request'])
    known(run.ledger, attempt(run, slots, p))
    run.finish(0, status='done'); run.guard(1)(slots[1]['request'])
    assert attempt(run, slots, p, 1).reserved_microyuan == 18384
    assert budget.totals(run.ledger, 'local-trial-1') == (2, 18438)


@pytest.mark.parametrize('settle_unknown', [False, True])
def test_unresolved_current_run_stops_next_slot_even_if_host_finishes(setup_run, settle_unknown):
    run, slots, p = setup_run
    bind(run, p)
    run.guard(0)(slots[0]['request'])
    permit = attempt(run, slots, p)
    if settle_unknown: budget.settle(run.ledger, permit, None)
    run.finish(0, status='done'); run.guard(1)(slots[1]['request'])
    with pytest.raises(budget.BudgetDenied): attempt(run, slots, p, 1)
    assert budget.totals(run.ledger, 'local-trial-1') == (1, 18384)


def historical(ledger, used):
    ledger.intent('historical', 'model-attempt', dict(scope_id='local-trial-1',
        reserved_microyuan=used))
    ledger.finish(Receipt('historical', 'uncertain', dict(charged_microyuan=used, usage_known=False)))


def test_history_is_never_reset_and_unknown_consumes_cumulative_budget(setup_run):
    run, slots, p = setup_run
    historical(run.ledger, 19981617)
    before = run.ledger.get('historical')
    bind(run, p)
    run.guard(0)(slots[0]['request'])
    with pytest.raises(budget.BudgetDenied): attempt(run, slots, p)
    assert run.ledger.get('historical') == before
    assert budget.totals(run.ledger, 'local-trial-1') == (1, 19981617)


def reserve_worker(path, slots, start, results):
    from ops.pi.policy import Policy
    run = AnalysisRun.open(Ledger(path), 'bound-run', slots, **BINDING)
    ctx = context(run)
    start.wait(10)
    try:
        budget.reserve(run.ledger, 'local-trial-1', slots[0]['request'],
                       Policy(**ctx.binding['policy']), analysis_slot=ctx)
        results.put(True)
    except budget.BudgetDenied:
        results.put(False)


def test_process_race_only_one_canonical_attempt(setup_run):
    run, slots, p = setup_run
    bind(run, p, 18384); run.guard(0)(slots[0]['request'])
    mp = multiprocessing.get_context('spawn')
    start, results = mp.Event(), mp.Queue()
    workers = [mp.Process(target=reserve_worker, args=(run.ledger.path, slots, start, results)) for _ in range(3)]
    for worker in workers: worker.start()
    start.set()
    try:
        outcomes = [results.get(timeout=20) for _ in workers]
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        assert sum(outcomes) == 1
    finally:
        for worker in workers:
            if worker.is_alive(): worker.terminate(); worker.join()
    assert budget.totals(run.ledger, 'local-trial-1') == (1, 18384)


def test_different_runs_race_for_same_cumulative_balance(setup_run):
    first, slots, p = setup_run
    historical(first.ledger, 19981616)
    second = AnalysisRun.create(first.ledger, 'second-run', slots, **BINDING)
    for run in (first, second):
        bind(run, p, 18384); run.guard(0)(slots[0]['request'])
    def reserve(run):
        try: return attempt(run, slots, p)
        except budget.BudgetDenied: return None
    with ThreadPoolExecutor(max_workers=2) as pool: outcomes = list(pool.map(reserve, [first, second]))
    assert sum(item is not None for item in outcomes) == 1
    assert budget.totals(first.ledger, 'local-trial-1') == (2, 20000000)


def test_deadline_rechecked_after_waiting_for_ledger_lock(setup_run, monkeypatch):
    run, slots, p = setup_run
    now = time.time()
    bind(run, p, deadline=now + 60); run.guard(0)(slots[0]['request'])
    ctx = context(run)
    clock = [now]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    started = Event()
    def reserve():
        started.set()
        with pytest.raises(budget.BudgetDenied):
            budget.reserve(run.ledger, 'local-trial-1', slots[0]['request'], p, analysis_slot=ctx)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with run.ledger.transaction():
            future = pool.submit(reserve)
            assert started.wait(5)
            clock[0] = now + 61
        future.result(timeout=10)
    assert budget.totals(run.ledger, 'local-trial-1') == (0, 0)


def test_expired_reopen_never_extends_deadline(setup_run, monkeypatch):
    run, slots, p = setup_run
    now = time.time(); bind(run, p, deadline=now + 60)
    monkeypatch.setattr(time, 'time', lambda: now + 61)
    reopened = AnalysisRun.open(Ledger(run.ledger.path), 'bound-run', slots, **BINDING)
    reopened.guard(0)(slots[0]['request'])
    with pytest.raises(budget.BudgetDenied): attempt(reopened, slots, p)
    assert budget.totals(run.ledger, 'local-trial-1') == (0, 0)


def test_whole_run_deadline_caps_permit_and_transport_acquisition(setup_run):
    run, slots, p = setup_run
    deadline = time.time() + 0.25
    bind(run, p, deadline=deadline); run.guard(0)(slots[0]['request'])
    timeouts, release = [], Event()
    def stalled(body, timeout):
        timeouts.append(timeout); release.wait(3)
        return httpx.Response(200)
    started = time.monotonic()
    try:
        result = forward_messages(slots[0]['request'], 'local-trial-1', ledger=run.ledger,
            policy=p, transport=stalled, analysis_slot=context(run))
        assert time.monotonic() - started < 1.5
        assert result.status_code == 502
        row = run.ledger.get(result.attempt_id)
        assert row['payload']['deadline'] == deadline
        assert row['status'] == 'uncertain'
        assert 0 < timeouts[0] <= 0.25
    finally: release.set()


def provider(body, timeout):
    return httpx.Response(200, headers={'content-type':'text/event-stream'},
        stream=PiStream(dict(input_tokens=7, output_tokens=0,
            cache_read_input_tokens=0, cache_creation_input_tokens=0)))


@contextmanager
def http_gateway(handler):
    with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            with httpx.Client(timeout=3, trust_env=False) as client:
                yield client, f'http://127.0.0.1:{server.server_port}/v1/messages'
        finally: server.shutdown(); worker.join(5)


def test_http_reopen_cannot_exceed_run_cap_or_accept_request_selected_limits(setup_run):
    run, slots, p = setup_run
    bind(run, p, 18437)
    headers = {'x-api-key':'x'*48, 'X-Pi-Scope':'local-trial-1'}
    handler = run.gateway_handler(0, p, provider, scope_token='x'*48)
    with http_gateway(handler) as (client, url):
        response = client.post(url, headers=headers, json=slots[0]['request'] | {'run_budget':20000000})
        assert response.status_code == 403
        assert budget.totals(run.ledger, 'local-trial-1') == (0, 0)
        assert client.post(url, headers=headers, json=slots[0]['request']).status_code == 200
    assert budget.totals(run.ledger, 'local-trial-1') == (1, 54)
    run.finish(0, status='done')
    reopened = AnalysisRun.open(Ledger(run.ledger.path), 'bound-run', slots, **BINDING)
    handler = reopened.gateway_handler(1, p, provider, scope_token='y'*48)
    with http_gateway(handler) as (client, url):
        assert client.post(url, headers=headers | {'x-api-key':'y'*48}, json=slots[1]['request']).status_code == 429
    assert budget.totals(run.ledger, 'local-trial-1') == (1, 54)


def test_handler_created_before_binding_cannot_bypass_new_constraints(setup_run):
    run, slots, p = setup_run
    handler = run.gateway_handler(0, p, provider, scope_token='x'*48)
    bind(run, p, 1)
    with http_gateway(handler) as (client, url):
        result = client.post(url, headers={'x-api-key':'x'*48,'X-Pi-Scope':'local-trial-1'}, json=slots[0]['request'])
        assert result.status_code != 200
    assert budget.totals(run.ledger, 'local-trial-1') == (0, 0)


def crash_after_reserve(path, slots):
    import os
    from ops.pi.policy import Policy
    run = AnalysisRun.open(Ledger(path), 'bound-run', slots, **BINDING)
    ctx = context(run)
    budget.reserve(run.ledger, 'local-trial-1', slots[0]['request'],
                   Policy(**ctx.binding['policy']), analysis_slot=ctx)
    os._exit(0)  # Simulate host death with no Python finalizers or receipt.


def test_crash_after_reserve_keeps_full_cost_and_blocks_replay_on_restart(setup_run):
    run, slots, p = setup_run
    bind(run, p); run.guard(0)(slots[0]['request'])
    worker = multiprocessing.get_context('spawn').Process(target=crash_after_reserve, args=(run.ledger.path, slots))
    worker.start(); worker.join(15)
    try:
        assert worker.exitcode == 0
    finally:
        if worker.is_alive(): worker.terminate(); worker.join()
    reopened = AnalysisRun.open(Ledger(run.ledger.path), 'bound-run', slots, **BINDING)
    assert reopened.snapshot()[0]['status'] == 'UNCERTAIN'
    with pytest.raises(OperationConflict): reopened.guard(0)(slots[0]['request'])
    with pytest.raises(budget.BudgetDenied): attempt(reopened, slots, p)
    reopened.finish(0, status='done'); reopened.guard(1)(slots[1]['request'])
    with pytest.raises(budget.BudgetDenied): attempt(reopened, slots, p, 1)
    assert budget.totals(reopened.ledger, 'local-trial-1') == (1, 18384)


def test_prior_global_refund_never_refills_this_runs_cap(setup_run):
    run, slots, p = setup_run
    old = budget.reserve(run.ledger, 'local-trial-1', slots[0]['request'], p)
    bind(run, p, 18437)
    run.guard(0)(slots[0]['request']); known(run.ledger, attempt(run, slots, p))
    budget.settle(run.ledger, old, dict(input_tokens=0, output_tokens=0,
        cache_read_input_tokens=0, cache_creation_input_tokens=0))
    run.finish(0, status='done'); run.guard(1)(slots[1]['request'])
    with pytest.raises(budget.BudgetDenied): attempt(run, slots, p, 1)
    assert budget.totals(run.ledger, 'local-trial-1') == (2, 54)


def test_changed_binding_receipt_does_not_fall_back_to_unbound(setup_run):
    run, slots, p = setup_run
    bind(run, p); ctx = context(run)
    run.guard(0)(slots[0]['request'])
    run.ledger.finish(Receipt('analysis:bound-run:budget', 'done', {'closed':True}))
    with pytest.raises(budget.BudgetDenied):
        budget.reserve(run.ledger, 'local-trial-1', slots[0]['request'], p, analysis_slot=ctx)
    assert budget.totals(run.ledger, 'local-trial-1') == (0, 0)


def test_context_cannot_bootstrap_replacement_ledger(setup_run, tmp_path):
    run, slots, p = setup_run
    bind(run, p); run.guard(0)(slots[0]['request'])
    replacement = Ledger(tmp_path / 'replacement.sqlite')
    before = snapshot(replacement)
    with pytest.raises(budget.BudgetDenied):
        budget.reserve(replacement, 'local-trial-1', slots[0]['request'], p, analysis_slot=context(run))
    assert snapshot(replacement) == before


def test_run_deadline_interrupts_stream_and_late_response_cannot_refund(setup_run):
    run, slots, p = setup_run
    deadline = time.time() + 0.3
    bind(run, p, deadline=deadline); run.guard(0)(slots[0]['request'])
    release, finished = Event(), Event()
    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            stream = iter(PiStream(dict(input_tokens=7, output_tokens=0,
                cache_read_input_tokens=0, cache_creation_input_tokens=0)))
            yield next(stream)
            release.wait(3)
            try: yield from stream
            finally: finished.set()
    result = forward_messages(slots[0]['request'], 'local-trial-1', ledger=run.ledger,
        policy=p, transport=lambda *_: httpx.Response(200, stream=SlowStream()), analysis_slot=context(run))
    started = time.monotonic()
    try:
        assert result.status_code == 200
        with pytest.raises(TimeoutError): b''.join(result.body)
        assert time.monotonic() - started < 1.5
        assert run.ledger.get(result.attempt_id)['status'] == 'uncertain'
    finally: release.set()
    assert finished.wait(3)
    assert run.ledger.get(result.attempt_id)['evidence']['charged_microyuan'] == 18384


def test_http_slow_body_cannot_outlive_whole_run_deadline(setup_run):
    import socket
    run, slots, p = setup_run
    bind(run, p, deadline=time.time() + 0.3)
    handler = run.gateway_handler(0, p, provider, scope_token='x'*48)
    with http_gateway(handler) as (_, url):
        from urllib.parse import urlsplit
        address = urlsplit(url)
        with socket.create_connection((address.hostname, address.port), timeout=2) as sock:
            sock.sendall(b'POST /v1/messages HTTP/1.0\r\nContent-Length: 100\r\nContent-Type: application/json\r\nx-api-key: ' + b'x'*48 + b'\r\nX-Pi-Scope: local-trial-1\r\n\r\n{')
            started = time.monotonic()
            assert sock.recv(4096) == b''
            assert time.monotonic() - started < 1.5
    assert budget.totals(run.ledger, 'local-trial-1') == (0, 0)
    assert run.snapshot()[0]['status'] == 'NOT_RUN'


@pytest.mark.parametrize('changed_input', ['policy', 'request'])
def test_policy_restored_during_lock_wait_cannot_underreserve(setup_run, monkeypatch, changed_input):
    run, slots, p = setup_run
    bind(run, p); run.guard(0)(slots[0]['request'])
    ctx = context(run)
    entered, release = Event(), Event()
    original_transaction = run.ledger.transaction
    @contextmanager
    def paused_transaction():
        entered.set()
        assert release.wait(5)
        with original_transaction() as db: yield db
    from copy import deepcopy
    body = deepcopy(slots[0]['request'])
    if changed_input == 'policy': p.prices['output'] = '0'
    else: body['max_tokens'] = 10
    monkeypatch.setattr(run.ledger, 'transaction', paused_transaction)
    def reserve():
        with pytest.raises(budget.BudgetDenied):
            budget.reserve(run.ledger, 'local-trial-1', body, p, analysis_slot=ctx)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(reserve)
        try:
            assert entered.wait(5)
            if changed_input == 'policy': p.prices['output'] = '8'
            else: body['max_tokens'] = 2048
        finally: release.set()
        future.result(timeout=10)
    monkeypatch.undo()
    assert budget.totals(run.ledger, 'local-trial-1') == (0, 0)


def test_forward_uses_private_request_matching_the_reserved_contract(setup_run):
    from copy import deepcopy
    run, slots, p = setup_run
    bind(run, p); run.guard(0)(slots[0]['request'])
    host_body = deepcopy(slots[0]['request'])
    sent_limits = []
    def send(body, timeout):
        host_body['max_tokens'] = 4096
        sent_limits.append(body['max_tokens'])
        return provider(body, timeout)
    result = forward_messages(host_body, 'local-trial-1', ledger=run.ledger,
        policy=p, transport=send, analysis_slot=context(run))
    assert result.status_code == 200
    assert b'Reviewed.' in b''.join(result.body)
    assert sent_limits == [2048]
    assert budget.totals(run.ledger, 'local-trial-1') == (1, 54)
