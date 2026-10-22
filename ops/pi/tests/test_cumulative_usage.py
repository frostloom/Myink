import hashlib
import json
from dataclasses import replace

import httpx
import pytest

from ops.pi.budget import totals
from ops.pi.model_gateway import _UsageCollector, _usage_snapshot, forward_messages
from ops.pi.tests.test_budget import ledger, policy, request
from ops.pi.tests.test_model_gateway import transport
from ops.pi.tests.test_usage_diagnostics import Evidence


FULL = dict(input_tokens=5, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0)
FINAL = FULL | dict(input_tokens=9, output_tokens=2)
DIMENSIONS = tuple(FULL)


def event(kind, usage=None):
    item = dict(type=kind)
    if kind == 'message_start':
        item['message'] = dict(usage=usage)
    elif usage is not None:
        item['usage'] = usage
    return b'data: ' + json.dumps(item).encode() + b'\n\n'


class CumulativeEvents(httpx.SyncByteStream):
    def __init__(self, start, deltas):
        self.start, self.deltas = start, deltas

    def __iter__(self):
        yield event('message_start', self.start)
        for delta in self.deltas:
            yield event('message_delta', delta)
        yield event('message_stop')


def forward(ledger, policy, start, deltas):
    evidence = Evidence()
    stream = CumulativeEvents(start, deltas)
    response = forward_messages(request() | dict(stream=True), 'local-trial-1', ledger=ledger,
                                policy=policy, transport=transport(lambda _: httpx.Response(200, stream=stream)),
                                usage_observer=evidence.append)
    assert b'message_stop' in b''.join(response.body)
    assert evidence.ready.wait(1)
    return ledger.get(response.attempt_id), evidence[0]


@pytest.mark.parametrize('deltas', [[FINAL], [FINAL | dict(input_tokens=7, output_tokens=1), FINAL, FINAL]])
def test_four_final_counters_replace_cumulative_totals_without_addition(ledger, policy, deltas):
    record, evidence = forward(ledger, policy, dict(input_tokens=5, output_tokens=0), deltas)
    assert record['status'] == 'done' and record['evidence']['usage_known'] is True
    assert totals(ledger, 'local-trial-1') == (1, 34)
    assert evidence['parser_reason'] == 'complete'
    assert evidence['parser_valid'] and evidence['final_output_usage'] and evidence['stream_stopped']
    collector = _UsageCollector()
    for chunk in CumulativeEvents(dict(input_tokens=5, output_tokens=0), deltas):
        collector.feed(chunk)
    assert collector.complete() and collector.usage == FINAL


@pytest.mark.parametrize('start,delta,status,charge', [
    (FULL, dict(input_tokens=None, output_tokens=2, cache_read_input_tokens=None, cache_creation_input_tokens=None), 'done', 26),
    (FULL, dict(output_tokens=2), 'done', 26),
    (dict(input_tokens=5, output_tokens=0), dict(output_tokens=2), 'uncertain', 10000),
    (dict(input_tokens=5, output_tokens=0, cache_read_input_tokens=None, cache_creation_input_tokens=None),
     dict(input_tokens=None, output_tokens=2, cache_read_input_tokens=None, cache_creation_input_tokens=None), 'uncertain', 10000),
])
def test_optional_null_or_absence_preserves_only_previously_known_values(ledger, policy, start, delta, status, charge):
    record, evidence = forward(ledger, policy, start, [delta])
    assert record['status'] == status
    assert totals(ledger, 'local-trial-1') == (1, charge)
    assert evidence['parser_valid'] and evidence['parser_reason'] == 'complete'
    collector = _UsageCollector()
    for chunk in CumulativeEvents(start, [delta]):
        collector.feed(chunk)
    expected = dict(input_tokens=5, output_tokens=2)
    if start == FULL:
        expected |= dict(cache_read_input_tokens=0, cache_creation_input_tokens=0)
    assert collector.usage == expected


@pytest.mark.parametrize('dimension', DIMENSIONS)
@pytest.mark.parametrize('invalid', [True, -1, '1', 1.0, {}, 2**63])
def test_malformed_start_dimension_cannot_be_rescued_by_valid_final_delta(ledger, policy, dimension, invalid):
    record, evidence = forward(ledger, policy, FULL | {dimension: invalid}, [FINAL])
    assert record['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)
    assert not evidence['parser_valid'] and not evidence['final_output_usage']
    assert evidence['parser_reason'] == 'invalid_start_usage'


@pytest.mark.parametrize('missing', ['input_tokens', 'output_tokens'])
def test_start_requires_explicit_integer_input_and_output(ledger, policy, missing):
    start = dict(FULL)
    del start[missing]
    record, evidence = forward(ledger, policy, start, [FINAL])
    assert record['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)
    assert evidence['parser_reason'] == 'invalid_start_usage'


@pytest.mark.parametrize('dimension', DIMENSIONS)
@pytest.mark.parametrize('invalid', [True, -1, '1', 1.0, {}, 2**63])
def test_malformed_delta_is_rejected_without_partial_usage_mutation(dimension, invalid):
    collector = _UsageCollector(capture=True)
    collector.feed(event('message_start', FULL))
    collector.feed(event('message_delta', FINAL | {dimension: invalid}))
    assert not collector.valid and not collector.final_output_usage
    assert collector.reason() == 'invalid_usage_delta'
    assert collector.usage == FULL
    assert 'message_delta' in collector.raw_usage


@pytest.mark.parametrize('dimension', ['output_tokens'])
def test_decreasing_output_counter_preserves_full_reservation(ledger, policy, dimension):
    start = dict.fromkeys(DIMENSIONS, 5)
    record, evidence = forward(ledger, replace(policy, prices=policy.prices | dict(cache_write='2')),
                               start, [dict.fromkeys(DIMENSIONS, 6) | {dimension: 4}])
    assert record['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)
    assert evidence['parser_reason'] == 'invalid_usage_delta'


@pytest.mark.parametrize('delta', [dict(input_tokens=9), FINAL | dict(output_tokens=None)])
def test_final_delta_requires_integer_output(ledger, policy, delta):
    record, evidence = forward(ledger, policy, FULL, [delta])
    assert record['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)
    assert not evidence['final_output_usage'] and evidence['parser_reason'] == 'invalid_usage_delta'


@pytest.mark.parametrize('location', ['start', 'delta'])
@pytest.mark.parametrize('extra', [{'service_tier': 'priority'}, {'output_tokens_details': {}}, {'synthetic_extra': 0}])
def test_unsupported_extra_metadata_remains_uncertain(ledger, policy, location, extra):
    start = FULL | extra if location == 'start' else FULL
    delta = FINAL | extra if location == 'delta' else FINAL
    record, evidence = forward(ledger, policy, start, [delta])
    assert record['status'] == 'uncertain'
    assert totals(ledger, 'local-trial-1') == (1, 10000)
    assert not evidence['parser_valid']
    assert evidence['parser_reason'] == ('invalid_start_usage' if location == 'start' else 'invalid_usage_delta')


def test_unknown_key_fingerprints_use_exact_domain_separated_names_and_no_values():
    usage = FULL | {'service_tier': 'PRIVATE-TIER', 'Secret-Key': 'PRIVATE-VALUE', 'secret-key': {'PRIVATE': 1}, '\u00e9': 1, 'e\u0301': 2}
    snapshot = _usage_snapshot(usage)
    expected = sorted(hashlib.sha256(b'myink-pi-usage-key-v1\0' + key.encode('utf-8')).hexdigest()
                      for key in ['Secret-Key', 'secret-key', '\u00e9', 'e\u0301'])
    assert snapshot['unrecognized_extra_key_sha256'] == expected
    assert len(set(expected)) == 4
    assert snapshot['unrecognized_extra_keys_unfingerprinted'] == 0
    assert snapshot['recognized_extra_keys'] == ['service_tier']
    assert snapshot['unrecognized_extra_key_count'] == 4
    assert all(value not in json.dumps(snapshot) for value in ['Secret-Key', 'secret-key', 'PRIVATE'])
    assert _usage_snapshot({key: None for key in usage})['unrecognized_extra_key_sha256'] == expected


def test_unknown_key_fingerprints_are_bounded_and_count_overflow():
    names = [f'unknown-{number}' for number in range(12)]
    snapshot = _usage_snapshot(dict.fromkeys(names, 'PRIVATE'))
    assert snapshot['unrecognized_extra_key_sha256'] == sorted(
        hashlib.sha256(b'myink-pi-usage-key-v1\0' + key.encode()).hexdigest() for key in names[:8])
    assert snapshot['unrecognized_extra_keys_unfingerprinted'] == 4
    assert snapshot['unrecognized_extra_key_count'] == 12
    assert len(json.dumps(snapshot).encode()) < 8192


def test_unknown_key_fingerprints_skip_oversized_and_unencodable_without_truncation():
    usage = {'a' * 256: 1, 'b' * 257: 1, '\u00e9' * 129: 1, '\ud800': 1}
    snapshot = _usage_snapshot(usage)
    assert snapshot['unrecognized_extra_key_sha256'] == [
        hashlib.sha256(b'myink-pi-usage-key-v1\0' + b'a' * 256).hexdigest()]
    assert snapshot['unrecognized_extra_keys_unfingerprinted'] == 3
    assert snapshot['unrecognized_extra_key_count'] == 4


def test_unknown_key_fingerprints_reach_only_opt_in_private_evidence(ledger, policy):
    record, evidence = forward(ledger, policy, FULL, [FINAL | {'synthetic_extra': 'PRIVATE'}])
    raw = evidence['raw_usage']['message_delta']
    assert len(raw['unrecognized_extra_key_sha256']) == 1
    assert raw['unrecognized_extra_keys_unfingerprinted'] == 0
    assert record['status'] == 'uncertain'
    assert 'sha256' not in json.dumps(record) and 'synthetic_extra' not in json.dumps(evidence)
    collector = _UsageCollector()
    collector.feed(event('message_start', FULL | {'synthetic_extra': 'PRIVATE'}))
    assert collector.raw_usage == {}


@pytest.mark.parametrize('dimension',['input_tokens','cache_read_input_tokens','cache_creation_input_tokens'])
def test_final_input_and_cache_replace_lower_start_totals(ledger,policy,dimension):
    start=dict.fromkeys(DIMENSIONS,5); final=dict.fromkeys(DIMENSIONS,6)|{dimension:4}
    configured=replace(policy,prices=policy.prices|dict(cache_write='2'))
    record,evidence=forward(ledger,configured,start,[final])
    assert record['status']=='done' and record['evidence']['usage_known'] is True
    collector=_UsageCollector()
    for chunk in CumulativeEvents(start,[final]):collector.feed(chunk)
    assert collector.usage==final and evidence['parser_reason']=='complete'


@pytest.mark.parametrize('location',['start','delta'])
def test_explicit_redundant_zero_cache_details_settle_only_priced_counters(ledger,policy,location):
    extra={'prompt_tokens_details':{'cached_tokens':0}}
    start=FULL|extra if location=='start' else FULL
    final=FINAL|extra if location=='delta' else FINAL
    record,evidence=forward(ledger,policy,start,[final])
    assert record['status']=='done' and totals(ledger,'local-trial-1')==(1,34)
    assert evidence['parser_valid']
    collector=_UsageCollector()
    for chunk in CumulativeEvents(start,[final]):collector.feed(chunk)
    assert collector.usage==FINAL and set(collector.usage)==set(DIMENSIONS)


@pytest.mark.parametrize('details',[None,0,[],{}, {'cached_tokens':None},{'cached_tokens':True},
    {'cached_tokens':0.0},{'cached_tokens':-1},{'cached_tokens':1},{'cached_tokens':0,'extra':0}])
def test_malformed_or_mismatched_cache_details_keep_full_reservation(ledger,policy,details):
    record,evidence=forward(ledger,policy,FULL,[FINAL|{'prompt_tokens_details':details}])
    assert record['status']=='uncertain' and totals(ledger,'local-trial-1')==(1,10000)
    assert evidence['parser_reason']=='invalid_usage_delta'


@pytest.mark.parametrize('cache',[None,True,0.0,1,'missing'])
def test_zero_details_reject_missing_invalid_or_mismatched_same_event_cache_read(ledger,policy,cache):
    final=FINAL|{'prompt_tokens_details':{'cached_tokens':0},'cache_read_input_tokens':cache}
    if cache=='missing':del final['cache_read_input_tokens']
    record,_=forward(ledger,policy,FULL,[final])
    assert record['status']=='uncertain' and totals(ledger,'local-trial-1')==(1,10000)


def test_zero_details_cannot_replace_unknown_priced_cache_write(ledger,policy):
    final=FINAL|{'prompt_tokens_details':{'cached_tokens':0}}
    del final['cache_creation_input_tokens']
    record,evidence=forward(ledger,policy,dict(input_tokens=5,output_tokens=0),[final])
    assert record['status']=='uncertain' and totals(ledger,'local-trial-1')==(1,10000)
    assert evidence['parser_valid'] and evidence['parser_reason']=='complete'
