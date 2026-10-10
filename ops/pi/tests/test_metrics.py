from datetime import datetime, timedelta, timezone
import pytest
from importlib.util import find_spec
from ops.pi.contracts import Identity

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)
IDENTITY = Identity('deploy-1', 1, 'human', {'api': 'image-1'}, schema_id='schema-1', config_hash='config-1')
PROVENANCE = dict(deployment_id='deploy-1', generation=1, owner='human', schema_id='schema-1',
                  config_id='config-1', prompt_id='prompt-1', rubric_id='rubric-1', data_id='data-1',
                  image_ids={'api': 'image-1'})


def snapshot(tasks, runs=(), **changes):
    assert find_spec('ops.pi.metrics') is not None, 'snapshot capability must exist'
    from ops.pi.metrics import collect_snapshot
    requests = []
    def reader(request):
        requests.append(request)
        rows = tasks if request['source'] == 'tasks' else runs
        offset = request['params']['offset']
        return rows[offset:offset + request['params']['limit']]
    window = dict(id='base-1', start=NOW, end=NOW + timedelta(hours=1), metric='cost', evidence_domain='online')
    window.update(changes)
    return collect_snapshot(reader, window, IDENTITY), requests


def run(task='t', **changes):
    row = dict(task_id=task, node='write', model_id='actual', cost_est=0, duration_ms=10,
               provenance=PROVENANCE, measurement=dict(cost=True, latency=True))
    row.update(changes)
    return row


def test_failed_planned_tasks_remain_in_denominator():
    s, _ = snapshot([dict(id='t', status='done'), dict(id='f', status='failed')], [run()])
    assert (s['planned'], s['completed'], s['failed']) == (2, 1, 1)
    assert s['measurements']['errors']['value'] == .5


def test_zero_and_missing_are_distinct():
    zero, _ = snapshot([dict(id='t', status='done')], [run()])
    missing, _ = snapshot([dict(id='t', status='done')], [run(measurement={})])
    assert zero['measurements']['cost'] == dict(value=0.0, availability='measured', samples=1, direction='lower')
    assert missing['measurements']['cost']['availability'] == 'unknown'
    assert missing['measurements']['cost']['value'] is None


def test_bounded_select_projection_and_pagination():
    s, requests = snapshot([dict(id=str(i), status='queued') for i in range(3)], page_size=2)
    assert s['planned'] == 3
    assert len([r for r in requests if r['source'] == 'tasks']) == 2
    for r in requests:
        assert r['sql'].startswith('SELECT ')
        assert r['read_only'] and r['timeout_ms'] <= 5000
        assert r['params']['start'] == NOW
        assert 'users' not in r['sql'] and 'payload' not in r['sql']
        assert 'detail,' not in r['sql']


def test_parent_batch_merges_threads_and_keeps_wait_separate():
    tasks = [dict(id='b', status='done'), dict(id='child', batch_task_id='b', chapter_seq=1, status='done')]
    s, _ = snapshot(tasks, [run('b:ch1'), run('child')])
    assert s['planned'] == s['completed'] == 1
    assert s['measurements']['node_time']['value'] == 20
    assert s['measurements']['queue_time']['availability'] == 'unknown'
    assert s['measurements']['human_wait']['availability'] == 'unknown'


def test_legacy_versions_are_unknown_not_current_config():
    s, _ = snapshot([dict(id='t', status='done')], [run(provenance={})])
    assert s['config_hash'] is None and s['availability'] == 'unknown'


def test_observed_deployment_must_match_collector_identity():
    s, _ = snapshot([dict(id='t', status='done')], [run(provenance={**PROVENANCE, 'deployment_id': 'old'})])
    assert 'identity_mismatch' in s['confounders']


def test_node_duration_does_not_claim_end_to_end_latency():
    s, _ = snapshot([dict(id='t', status='done')], [run()])
    assert s['measurements']['latency']['availability'] == 'unknown'
    assert s['measurements']['node_time']['value'] == 10


def test_json_projection_does_not_return_arbitrary_nested_detail():
    _, requests = snapshot([])
    query = next(r['sql'] for r in requests if r['source'] == 'agent_runs')
    assert "detail->'run_provenance' AS" not in query
    assert "detail->'measurement' AS" not in query


def test_business_provenance_is_safe_and_survives_detail_capture(monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'src'))
    assert find_spec('myink.observability') is not None, 'business provenance capability must exist'
    from types import SimpleNamespace
    from myink.observability import run_provenance
    from myink.admin_observability import capture_detail
    settings = SimpleNamespace(deployment_id='d', deployment_generation=1, deployment_owner='pi',
                               observation_schema_id='s', observation_prompt_id='p',
                               observation_rubric_id='r', observation_data_id='data',
                               platform_model_api_key='never-copy', database_url='never-copy',
                               request_token_budget=100)
    provenance = run_provenance(settings)
    assert 'never-copy' not in str(provenance)
    assert provenance['config_id'] and provenance['prompt_id'] == 'p'
    detail = capture_detail(dict(run_provenance=provenance, measurement=dict(cost=True)))
    assert capture_detail({**detail, 'audit_verdict': {'ok': True}})['run_provenance'] == provenance


@pytest.mark.parametrize('changes', [dict(end=NOW), dict(page_size=1001), dict(query_timeout_ms=5001), dict(evidence_domain='mixed')])
def test_invalid_reader_bounds_rejected(changes):
    with pytest.raises(ValueError):
        snapshot([], **changes)
