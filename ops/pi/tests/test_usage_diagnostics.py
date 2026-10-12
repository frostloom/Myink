import json
from dataclasses import replace
from threading import Event, Thread

import httpx
import pytest

from ops.pi.budget import totals
from ops.pi.model_gateway import forward_messages
from ops.pi.tests.test_budget import ledger, policy, request
from ops.pi.tests.test_model_gateway import transport


class Evidence(list):
    def __init__(self):
        super().__init__()
        self.ready = Event()

    def append(self, item):
        super().append(item)
        self.ready.set()


class Events(httpx.SyncByteStream):
    def __init__(self, usage, delta):
        self.usage, self.delta = usage, delta

    def __iter__(self):
        for item in [dict(type='message_start', message=dict(usage=self.usage)),
                     dict(type='message_delta', usage=self.delta), dict(type='message_stop')]:
            yield b'data: ' + json.dumps(item).encode() + b'\n\n'


FULL = dict(input_tokens=1, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0)


@pytest.mark.parametrize('usage,status,charge', [
    (dict(input_tokens=1, output_tokens=0), 'uncertain', 10000),
    (FULL, 'done', 10),
])
def test_raw_usage_presence_does_not_default_missing_cache_to_zero(ledger, policy, usage, status, charge):
    evidence = Evidence()
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger,
                                policy=policy, transport=transport(lambda _: httpx.Response(200, stream=Events(usage, {'output_tokens': 1}))),
                                usage_observer=evidence.append)
    assert b'message_stop' in b''.join(response.body)
    assert ledger.get(response.attempt_id)['status'] == status
    assert totals(ledger, 'local-trial-1') == (1, charge)
    assert evidence.ready.wait(1)
    assert len(evidence) == 1
    item = evidence[0]
    assert item['attempt_id'] == response.attempt_id
    assert item['parser_reason'] == 'complete'
    assert item['stream_started'] and item['stream_stopped'] and item['final_output_usage'] and item['parser_valid']
    assert item['raw_usage']['message_delta']['dimensions']['output_tokens']['value'] == 1
    cache = item['raw_usage']['message_start']['dimensions']['cache_read_input_tokens']
    assert cache == ({'present': True, 'type': 'integer', 'value': 0} if usage == FULL
                     else {'present': False, 'type': 'missing', 'value': None})


def test_extra_delta_reports_only_finite_keys_and_preserves_uncertain_charge(ledger, policy):
    evidence = Evidence()
    delta = dict(output_tokens=1, service_tier='SECRET-TIER', **{'SECRET-KEY': 'SECRET-VALUE'})
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger,
                                policy=policy, transport=transport(lambda _: httpx.Response(200, stream=Events(FULL, delta))),
                                usage_observer=evidence.append)
    b''.join(response.body)
    assert evidence.ready.wait(1)
    item = evidence[0]
    assert item['parser_reason'] == 'invalid_usage_delta'
    assert item['parser_valid'] is False and item['final_output_usage'] is False
    raw = item['raw_usage']['message_delta']
    assert raw['recognized_extra_keys'] == ['service_tier']
    assert raw['extra_key_count'] == 2 and raw['unrecognized_extra_key_count'] == 1
    assert raw['dimensions']['output_tokens'] == {'present': True, 'type': 'integer', 'value': 1}
    assert 'SECRET' not in json.dumps(item)
    assert ledger.get(response.attempt_id)['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)


@pytest.mark.parametrize('delta,charge,status', [({'output_tokens': 1}, 10, 'done'),
                                                 ({'output_tokens': 1, 'service_tier': 'private'}, 10000, 'uncertain')])
def test_observer_failure_cannot_change_stream_or_settlement(ledger, policy, delta, charge, status):
    failed = Event()
    def fail(item):
        item.clear()
        failed.set()
        raise RuntimeError('secret observer failure')
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger,
                                policy=policy, transport=transport(lambda _: httpx.Response(200, stream=Events(FULL, delta))),
                                usage_observer=fail)
    assert b'message_stop' in b''.join(response.body)
    assert failed.wait(1)
    assert ledger.get(response.attempt_id)['status'] == status
    assert totals(ledger, 'local-trial-1') == (1, charge)


def test_nonstream_diagnostic_never_exports_invalid_numeric_values(ledger, policy):
    evidence = Evidence()
    usage = dict(input_tokens=True, output_tokens=-1, cache_read_input_tokens='SECRET', cache_creation_input_tokens=2**80)
    response = forward_messages(request(), 'local-trial-1', ledger=ledger, policy=policy,
                                transport=transport(lambda _: httpx.Response(200, json=dict(usage=usage, content='SECRET'))),
                                usage_observer=evidence.append)
    assert response.status_code == 200
    assert evidence.ready.wait(1)
    dimensions = evidence[0]['raw_usage']['response']['dimensions']
    assert [dimensions[k]['type'] for k in usage] == ['boolean', 'integer', 'string', 'integer']
    assert all(dimensions[k]['value'] is None for k in usage)
    assert 'SECRET' not in json.dumps(evidence)
    assert totals(ledger, 'local-trial-1') == (1, 10000)


def test_private_diagnostic_file_is_exclusive_and_capped(tmp_path, monkeypatch):
    from ops.pi.lab import preview_gateway
    monkeypatch.setattr(preview_gateway, 'ROOT', tmp_path)
    path = tmp_path / 'usage.jsonl'
    observe = preview_gateway.make_usage_observer(path)
    for _ in range(10):
        observe({'parser_reason': 'complete'})
    assert path.read_text().splitlines() == ['{"parser_reason":"complete"}'] * 6
    with pytest.raises(FileExistsError):
        preview_gateway.make_usage_observer(path)
    with pytest.raises(ValueError):
        preview_gateway.make_usage_observer(tmp_path.parent / 'outside.jsonl')


@pytest.mark.parametrize('streaming', [False, True])
def test_stalled_observer_does_not_block_paid_response_completion(ledger, policy, streaming):
    entered, release, observed, completed = Event(), Event(), Event(), Event()
    results, errors = [], []

    def stall(item):
        entered.set()
        release.wait(3)
        observed.set()

    def call():
        try:
            send = transport(lambda _: httpx.Response(200, stream=Events(FULL, {'output_tokens': 1})) if streaming
                             else httpx.Response(200, json={'usage': FULL | {'output_tokens': 1}}))
            response = forward_messages(request() | {'stream': streaming}, 'local-trial-1', ledger=ledger,
                                        policy=replace(policy, timeout_seconds=5), transport=send, usage_observer=stall)
            data = b''.join(response.body) if streaming else response.body
            results.append((response, data))
        except Exception as exc:
            errors.append(exc)
        finally:
            completed.set()

    caller = Thread(target=call, daemon=True)
    caller.start()
    try:
        assert entered.wait(1), 'the diagnostic callback must actually be stalled'
        assert completed.wait(1), 'model completion must not wait for diagnostic storage'
        assert not release.is_set() and not observed.is_set()
        assert errors == [] and len(results) == 1
        response, data = results[0]
        assert response.status_code == 200 and data
        assert ledger.get(response.attempt_id)['status'] == 'done'
        assert totals(ledger, 'local-trial-1') == (1, 10)
    finally:
        release.set()
        caller.join(1)
        assert observed.wait(1)
