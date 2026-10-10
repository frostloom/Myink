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
    tasks = [{**dict(created_at=NOW, updated_at=NOW + timedelta(minutes=5)), **t} for t in tasks]
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
               input_tokens=1, output_tokens=1, created_at=NOW + timedelta(minutes=1),
               provenance=PROVENANCE, measurement=dict(kind='model', cost=True, latency=True, pricing_id='a' * 64))
    row.update(changes)
    if isinstance(row.get('measurement'), dict) and row['measurement']:
        row['measurement'] = {'kind': 'model', **row['measurement']}
    return row


def test_post_end_completion_cannot_measure_partial_runs_or_past_status():
    tasks = [dict(id='t', status='done', created_at=NOW, updated_at=NOW + timedelta(hours=2))]
    s, _ = snapshot(tasks, [run(created_at=NOW + timedelta(minutes=1)),
                            run(created_at=NOW + timedelta(minutes=90), cost_est=100)])
    assert s['complete_tasks'] == 0
    assert s['status_unknown'] == 1
    assert s['measurements']['cost']['availability'] == 'unknown'
    assert s['measurements']['latency']['availability'] == 'unknown'
    assert s['measurements']['errors']['availability'] == 'unknown'


def test_cohort_query_includes_batch_children_and_runs_by_thread_not_independent_window():
    tasks = [dict(id='b', status='done', created_at=NOW, updated_at=NOW + timedelta(minutes=5)),
             dict(id='c', batch_task_id='b', chapter_seq=1, status='done',
                  created_at=NOW + timedelta(minutes=1), updated_at=NOW + timedelta(minutes=5))]
    s, requests = snapshot(tasks, [run('b:ch1', created_at=NOW + timedelta(minutes=2))])
    assert s['complete_tasks'] == 1
    query = next(r['sql'] for r in requests if r['source'] == 'tasks')
    assert 'batch_task_id IN' in query
    request = next(r for r in requests if r['source'] == 'agent_runs')
    assert 'task_id IN' in request['sql']
    assert 'b:ch1' in request['params'].values()


def test_cross_boundary_batch_and_exact_end_completion_are_incomplete():
    for tasks in ([dict(id='b', status='done', created_at=NOW - timedelta(minutes=1), updated_at=NOW),
                   dict(id='c', batch_task_id='b', chapter_seq=1, status='done', created_at=NOW, updated_at=NOW)],
                  [dict(id='b', status='done', created_at=NOW, updated_at=NOW + timedelta(hours=1)),
                   dict(id='c', batch_task_id='b', chapter_seq=1, status='done', created_at=NOW, updated_at=NOW + timedelta(minutes=5))]):
        s, _ = snapshot(tasks, [run('b:ch1', created_at=NOW)])
        assert s['complete_tasks'] == 0 and s['availability'] == 'unknown'


def test_mixed_model_and_deterministic_nodes_keep_cost_model_identity_and_rubric_score():
    tasks = [dict(id='t', status='done', created_at=NOW, updated_at=NOW + timedelta(minutes=5))]
    model = run(created_at=NOW + timedelta(minutes=1), cost_est=1,
                measurement=dict(kind='model', cost=True, latency=True, pricing_id='a' * 64,
                                 quality_score=.8, quality_rubric_id='rubric-1'))
    plain = run(created_at=NOW + timedelta(minutes=2), node='persist', model_id=None,
                input_tokens=0, output_tokens=0,
                measurement=dict(kind='deterministic', cost=True, latency=True, zero_cost=True))
    s, _ = snapshot(tasks, [model, plain])
    assert s['availability'] == 'measured' and s['model_ids'] == ['actual']
    assert s['measurements']['cost']['value'] == 1
    assert s['measurements']['node_time']['value'] == 20
    assert s['measurements']['quality']['value'] == .8
    legacy, _ = snapshot(tasks, [model, {**plain, 'provenance': {}, 'measurement': {}}])
    assert legacy['availability'] == 'unknown'
    assert legacy['measurements']['cost']['availability'] == 'unknown'


def test_post_end_run_cannot_leave_complete_group_measured():
    tasks = [dict(id='t', status='done', created_at=NOW, updated_at=NOW + timedelta(minutes=5))]
    s, _ = snapshot(tasks, [run(), run(created_at=NOW + timedelta(hours=1))])
    assert s['complete_tasks'] == 0 and s['availability'] == 'unknown'
    assert 'out_of_bounds_run' in s['confounders']


def test_sql_null_quality_leaves_do_not_require_unscored_nodes_to_have_scores():
    tasks = [dict(id='t', status='done')]
    scored = run(measurement=dict(kind='model', cost=True, latency=True, pricing_id='a' * 64,
                                 quality_score=.8, quality_rubric_id='rubric-1'))
    unscored = run(measurement=dict(kind='model', cost=True, latency=True, pricing_id='a' * 64,
                                   quality_score=None, quality_rubric_id=None))
    s, _ = snapshot(tasks, [scored, unscored])
    assert s['measurements']['quality']['value'] == .8


def test_complete_task_with_no_instrumented_runs_has_unknown_configuration():
    s, _ = snapshot([dict(id='t', status='done'), dict(id='other', status='done')], [run()])
    assert s['availability'] == 'unknown'


def test_plain_recorder_appends_metadata_without_services(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    import uuid
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'src'))
    from myink.workflow import nodes
    monkeypatch.setattr(nodes, 'settings', SimpleNamespace(observation_config_id='b' * 64))
    rows = []
    original = {'saved': True}
    uid = uuid.uuid4()
    nodes.record_plain(SimpleNamespace(add=rows.append), user_id=uid, task_id='t',
                       node='persist', detail=original, duration_ms=3)
    row = rows[0]
    assert row.user_id == uid and row.project_id is None and row.model_id is None
    assert row.cost_est == row.input_tokens == row.output_tokens == 0 and row.duration_ms == 3
    assert original == {'saved': True} and row.detail['saved'] is True
    assert row.detail['run_provenance']['config_id'] == 'b' * 64
    assert row.detail['measurement']['kind'] == 'deterministic' and row.detail['measurement']['zero_cost'] is True


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
    s, _ = snapshot([dict(id='t', status='done', updated_at=None)], [run()])
    assert s['measurements']['latency']['availability'] == 'unknown'
    assert s['measurements']['node_time']['availability'] == 'unknown'


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
    assert provenance.get('settings_id') and provenance['config_id'] is None and provenance['prompt_id'] == 'p'
    detail = capture_detail(dict(run_provenance=provenance, measurement=dict(cost=True)))
    assert capture_detail({**detail, 'audit_verdict': {'ok': True}})['run_provenance'] == provenance


def test_config_requires_trusted_complete_fingerprint(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'src'))
    from myink.observability import run_provenance
    for value in ('', 'not-a-digest', 'sk-not-a-valid-config-digest'):
        assert run_provenance(SimpleNamespace(observation_config_id=value))['config_id'] is None
    assert run_provenance(SimpleNamespace(observation_config_id='b' * 64))['config_id'] == 'b' * 64


def test_pricing_is_projected_and_missing_or_mixed_is_explicit():
    tasks = [dict(id='t', status='done')]
    known, _ = snapshot(tasks, [run()])
    assert known.get('pricing_id') == 'a' * 64
    missing, _ = snapshot(tasks, [run(measurement=dict(cost=True, latency=True))])
    assert missing['pricing_id'] is None
    assert missing['measurements']['cost']['availability'] == 'unknown'
    mixed, _ = snapshot(tasks, [run(), run(measurement=dict(cost=True, latency=True, pricing_id='b' * 64))])
    assert mixed['pricing_id'] is None and 'mixed_pricing' in mixed['confounders']


def test_incomplete_config_makes_snapshot_unknown():
    s, _ = snapshot([dict(id='t', status='done')], [run(provenance={**PROVENANCE, 'config_id': None})])
    assert s['config_hash'] is None and s['availability'] == 'unknown'


def test_error_or_unproven_zero_usage_is_not_measured_cost(monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'src'))
    from myink.observability import run_measurement
    from myink.providers.base import ModelResponse
    assert run_measurement(ModelResponse(content='text', model_id='deepseek-v4-flash'))['cost'] is False
    assert run_measurement(ModelResponse(content='', model_id='deepseek-v4-flash',
                                         error='provider error', input_tokens=1))['cost'] is False
    zero_prices = dict(input=0, input_cache_hit=0, output=0)
    assert run_measurement(ModelResponse(content='text', model_id='custom', input_tokens=1, output_tokens=1,
                                         prices=zero_prices))['cost'] is True


def test_partial_default_usage_is_unknown(monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'src'))
    from myink.observability import run_measurement
    from myink.providers.base import ModelResponse
    assert run_measurement(ModelResponse(content='text', model_id='deepseek-v4-flash', input_tokens=1))['cost'] is False
    assert run_measurement(ModelResponse(content='text', model_id='deepseek-v4-flash', output_tokens=1))['cost'] is False
    assert run_measurement(ModelResponse(content='', model_id='deepseek-v4-flash', input_tokens=1,
                                         tool_calls=[{'name': 'read'}]))['cost'] is False


@pytest.mark.parametrize('changes', [dict(end=NOW), dict(page_size=1001), dict(query_timeout_ms=5001), dict(evidence_domain='mixed')])
def test_invalid_reader_bounds_rejected(changes):
    with pytest.raises(ValueError):
        snapshot([], **changes)
