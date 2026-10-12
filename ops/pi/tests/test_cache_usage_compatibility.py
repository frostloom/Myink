"""Prospective strict cache metadata compatibility; no historical repair."""
from dataclasses import replace
from threading import Event, Thread

import httpx
import pytest

from ops.pi.budget import reserve, settle, totals
from ops.pi.model_gateway import _UsageCollector, forward_messages
from ops.pi.tests.test_budget import ledger, policy, request
from ops.pi.tests.test_cumulative_usage import FULL, FINAL, CumulativeEvents, event, forward
from ops.pi.tests.test_model_gateway import transport


def duplicate(usage):
    return usage | {'prompt_tokens_details': {'cached_tokens': usage['cache_read_input_tokens']}}


def test_future_live_shaped_cache_equality_charges_disjoint_final_counters_once(ledger, policy):
    configured = replace(policy, input_token_bound=4000)
    final = dict(input_tokens=852, output_tokens=103, cache_read_input_tokens=2688, cache_creation_input_tokens=0)
    record, evidence = forward(ledger, configured, dict(input_tokens=1955, output_tokens=0), [duplicate(final)])
    # Independently: 852*2 + 2688*0.2 + 103*8 = 3065.6, ceiling 3066.
    assert record['status'] == 'done' and record['evidence']['usage_known'] is True
    assert record['payload']['prices'] == {'input': '2', 'output': '8', 'cache_read': '0.2', 'cache_write': None}
    assert totals(ledger, 'local-trial-1') == (1, 3066)
    assert evidence['parser_reason'] == 'complete' and evidence['stream_stopped']
    assert evidence['raw_usage']['message_delta']['prompt_tokens_details'] == dict(
        present=True, exact_shape_valid=True, cached_tokens_valid=True,
        cached_tokens=2688, cache_read_equal=True)
    collector = _UsageCollector()
    for chunk in CumulativeEvents(dict(input_tokens=1955, output_tokens=0), [duplicate(final)]):
        collector.feed(chunk)
    assert collector.complete() and collector.usage == final


@pytest.mark.parametrize('location', ['start', 'delta', 'both'])
def test_positive_equal_details_preserve_cumulative_overwrite_and_output_monotonicity(ledger, policy, location):
    start = FULL | dict(input_tokens=8, cache_read_input_tokens=9)
    first = FINAL | dict(input_tokens=7, output_tokens=1, cache_read_input_tokens=6)
    final = FINAL | dict(input_tokens=4, cache_read_input_tokens=3)
    start = duplicate(start) if location in ('start', 'both') else start
    deltas = [duplicate(first), duplicate(final), duplicate(final)] if location in ('delta', 'both') else [first, final, final]
    record, _ = forward(ledger, policy, start, deltas)
    assert record['status'] == 'done' and totals(ledger, 'local-trial-1') == (1, 25)
    collector = _UsageCollector()
    for chunk in CumulativeEvents(start, deltas):
        collector.feed(chunk)
    assert collector.complete() and collector.usage == final


@pytest.mark.parametrize('cached', [0, 2, None, True, 1.0, '1', -1, 2**63])
@pytest.mark.parametrize('location', ['start', 'delta'])
def test_invalid_cache_duplicate_is_terminal_and_atomic(ledger, policy, location, cached):
    bad = (FULL if location == 'start' else FINAL) | dict(cache_read_input_tokens=1, prompt_tokens_details={'cached_tokens': cached})
    start = bad if location == 'start' else FULL
    deltas = [FINAL] if location == 'start' else [bad, FINAL]
    record, evidence = forward(ledger, policy, start, deltas)
    assert record['status'] == 'uncertain' and totals(ledger, 'local-trial-1') == (1, 10000)
    assert evidence['parser_reason'] == ('invalid_start_usage' if location == 'start' else 'invalid_usage_delta')
    collector = _UsageCollector()
    for chunk in CumulativeEvents(start, deltas):
        collector.feed(chunk)
    assert not collector.complete() and not collector.final_output_usage
    assert collector.usage == ({} if location == 'start' else FULL)


@pytest.mark.parametrize('invalid', [True, 1.0, '1', -1, 2**63])
def test_equal_non_integer_or_out_of_range_duplicates_are_rejected(invalid):
    collector = _UsageCollector()
    collector.feed(event('message_start', FULL))
    collector.feed(event('message_delta', FINAL | dict(cache_read_input_tokens=invalid, prompt_tokens_details={'cached_tokens': invalid})))
    assert not collector.valid and collector.usage == FULL


@pytest.mark.parametrize('details', [None, 1, [], {}, {'other': 1}, {'cached_tokens': 1, 'private-name': 'PRIVATE'}])
def test_cache_details_require_exact_known_single_member_shape(details):
    collector = _UsageCollector()
    collector.feed(event('message_start', FULL))
    collector.feed(event('message_delta', FINAL | dict(cache_read_input_tokens=1, prompt_tokens_details=details)))
    assert not collector.valid and collector.usage == FULL


@pytest.mark.parametrize('read', [None, True, 1.0, '1', -1, 2**63, 'missing'])
def test_duplicate_requires_same_event_valid_read_even_when_previous_read_matches(read):
    collector = _UsageCollector()
    start = FULL | dict(cache_read_input_tokens=1)
    collector.feed(event('message_start', start))
    final = FINAL | dict(cache_read_input_tokens=read, prompt_tokens_details={'cached_tokens': 1})
    if read == 'missing':
        del final['cache_read_input_tokens']
    collector.feed(event('message_delta', final))
    assert not collector.valid and collector.usage == start


def test_maximum_bounded_integer_duplicate_parses_but_cannot_evade_budget_bound(ledger, policy):
    final = FINAL | dict(cache_read_input_tokens=2**63 - 1)
    record, evidence = forward(ledger, policy, FULL, [duplicate(final)])
    assert evidence['parser_valid'] and evidence['parser_reason'] == 'complete'
    assert record['status'] == 'uncertain' and totals(ledger, 'local-trial-1') == (1, 10000)


@pytest.mark.parametrize('missing', ['input_tokens', 'cache_creation_input_tokens'])
def test_duplicate_metadata_cannot_supply_never_known_priced_dimensions(ledger, policy, missing):
    start = dict(input_tokens=5, output_tokens=0)
    final = duplicate(FINAL | dict(cache_read_input_tokens=1))
    del final[missing]
    if missing in start:
        del start[missing]
        # A start must know input. Test a never-known optional creation separately;
        # absent input at start itself remains a terminal error.
    record, _ = forward(ledger, policy, start, [final])
    assert record['status'] == 'uncertain' and totals(ledger, 'local-trial-1') == (1, 10000)


@pytest.mark.parametrize('change', [dict(cache_creation_input_tokens=1), dict(input_tokens=1000), dict(output_tokens=1001)])
def test_valid_duplicate_does_not_bypass_prices_or_reservation_bounds(ledger, policy, change):
    final = duplicate(FINAL | dict(cache_read_input_tokens=1) | change)
    record, evidence = forward(ledger, policy, FULL, [final])
    assert evidence['parser_valid'] and record['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)


@pytest.mark.parametrize('chunks', [
    [event('message_start', FULL), event('message_delta', duplicate(FINAL | dict(cache_read_input_tokens=1)))],
    [event('message_start', FULL), event('message_stop')],
    [event('message_start', FULL), event('message_delta', duplicate(FINAL | dict(cache_read_input_tokens=1))), event('message_stop'), b'partial'],
    [event('message_delta', duplicate(FINAL | dict(cache_read_input_tokens=1))), event('message_stop')],
    [event('message_start', FULL | dict(output_tokens=3)), event('message_delta', duplicate(FINAL | dict(cache_read_input_tokens=1))), event('message_stop')],
    [event('message_start', FULL), event('message_delta', duplicate(FINAL | dict(cache_read_input_tokens=1))), event('message_stop'), event('message_delta', FINAL)],
])
def test_duplicate_cannot_rescue_incomplete_or_invalid_stream(chunks):
    collector = _UsageCollector()
    for chunk in chunks:
        collector.feed(chunk)
    assert not collector.complete()


def test_unknown_historical_attempt_is_immutable_when_future_duplicate_succeeds(ledger, policy):
    permit = reserve(ledger, 'local-trial-1', request(), policy)
    settle(ledger, permit, None)
    before = ledger.get(permit.attempt_id)
    record, _ = forward(ledger, policy, FULL, [duplicate(FINAL | dict(cache_read_input_tokens=1))])
    settle(ledger, permit, FINAL)
    assert ledger.get(permit.attempt_id) == before
    assert record['status'] == 'done' and totals(ledger, 'local-trial-1') == (2, 10035)


def test_nonstream_matching_duplicate_retains_conservative_unknown_settlement(ledger, policy):
    usage = duplicate(FINAL | dict(cache_read_input_tokens=1))
    response = forward_messages(request(), 'local-trial-1', ledger=ledger, policy=policy,
                                transport=transport(lambda _: httpx.Response(200, json={'usage': usage})))
    assert response.status_code == 200
    assert ledger.get(response.attempt_id)['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)


def test_duplicate_observer_exception_preserves_bytes_and_settlement(ledger, policy):
    failed = Event()
    def fail(item):
        item.clear()
        failed.set()
        raise RuntimeError('PRIVATE')
    stream = CumulativeEvents(FULL, [duplicate(FINAL | dict(cache_read_input_tokens=1))])
    expected = b''.join(CumulativeEvents(FULL, [duplicate(FINAL | dict(cache_read_input_tokens=1))]))
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger, policy=policy,
                                transport=transport(lambda _: httpx.Response(200, stream=stream)), usage_observer=fail)
    assert b''.join(response.body) == expected and failed.wait(1)
    assert ledger.get(response.attempt_id)['status'] == 'done' and totals(ledger, 'local-trial-1') == (1, 35)


@pytest.mark.parametrize('failure', ['timeout', 'disconnect'])
def test_complete_duplicate_counters_cannot_refund_failed_transport(ledger, policy, monkeypatch, failure):
    import time
    wall = time.time()
    elapsed = [0]
    monkeypatch.setattr(time, 'time', lambda: wall + elapsed[0])
    class FailedAfterUsage(httpx.SyncByteStream):
        def __iter__(self):
            yield event('message_start', FULL)
            yield event('message_delta', duplicate(FINAL | dict(cache_read_input_tokens=1)))
            if failure == 'disconnect':
                raise httpx.ReadError('offline disconnect')
            elapsed[0] = 121
            yield event('message_stop')
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger, policy=policy,
                                transport=transport(lambda _: httpx.Response(200, stream=FailedAfterUsage())))
    with pytest.raises((TimeoutError, httpx.ReadError)):
        b''.join(response.body)
    assert ledger.get(response.attempt_id)['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)


def test_positive_duplicate_stalled_observer_does_not_delay_settlement(ledger, policy):
    entered, release, observed, completed = Event(), Event(), Event(), Event()
    results, errors = [], []
    final = duplicate(FINAL | dict(cache_read_input_tokens=1))
    expected = b''.join(CumulativeEvents(FULL, [final]))
    def stall(item):
        entered.set()
        release.wait(3)
        observed.set()
    def call():
        try:
            response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger, policy=policy,
                                        transport=transport(lambda _: httpx.Response(200, stream=CumulativeEvents(FULL, [final]))),
                                        usage_observer=stall)
            results.append((response, b''.join(response.body)))
        except Exception as exc:
            errors.append(exc)
        finally:
            completed.set()
    caller = Thread(target=call, daemon=True)
    caller.start()
    try:
        assert entered.wait(1) and completed.wait(1)
        assert not release.is_set() and not observed.is_set()
        assert errors == [] and len(results) == 1
        response, forwarded = results[0]
        assert forwarded == expected and ledger.get(response.attempt_id)['status'] == 'done'
        assert totals(ledger, 'local-trial-1') == (1, 35)
    finally:
        release.set()
        caller.join(1)
        assert observed.wait(1)


def test_positive_duplicate_saturated_observer_queue_cannot_change_settlement(ledger, policy, monkeypatch):
    from queue import Queue
    import ops.pi.model_gateway as gateway
    entered, release, finished = Event(), Event(), Event()
    def stall(item):
        entered.set()
        release.wait(3)
        finished.set()
    gateway._dispatch_usage_observer(stall, {})
    assert entered.wait(1), 'the real observer worker must be blocked before queue replacement'
    saturated = Queue(maxsize=1)
    saturated.put_nowait((lambda _: None, {}))
    observed = Event()
    final = duplicate(FINAL | dict(cache_read_input_tokens=1))
    expected = b''.join(CumulativeEvents(FULL, [final]))
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(gateway, '_USAGE_OBSERVER_QUEUE', saturated)
            response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger, policy=policy,
                                        transport=transport(lambda _: httpx.Response(200, stream=CumulativeEvents(FULL, [final]))),
                                        usage_observer=lambda _: observed.set())
            assert b''.join(response.body) == expected and not observed.is_set()
            assert ledger.get(response.attempt_id)['status'] == 'done' and totals(ledger, 'local-trial-1') == (1, 35)
    finally:
        # Restore the original queue before the real worker calls task_done.
        release.set()
        assert finished.wait(1)
