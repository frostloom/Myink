from dataclasses import replace
import pytest
from importlib.util import find_spec
from ops.pi.tests.test_plans import candidate


def compare_windows(*args):
    assert find_spec('ops.pi.compare') is not None, 'comparison capability must exist'
    from ops.pi.compare import compare_windows as compare
    return compare(*args)


def evidence(**changes):
    s = dict(id='base-1', config_hash='config-1', prompt_hash='prompt-1', rubric_hash='rubric-1',
             data_hash='data-1', schema_id='schema-1', model_ids=['actual'], pricing_id='a' * 64, evidence_domain='online',
             identity=dict(deployment_id='deploy-1', generation=1, owner='human', image_ids={'api': 'old'}),
             complete_tasks=20, paired_group_ids=[], tail_samples=100, confounders=[], availability='measured',
             measurements=dict(latency=dict(value=100, availability='measured', samples=20, direction='lower'),
                               errors=dict(value=0, availability='measured', samples=20, direction='lower')))
    s.update(changes)
    return s


def test_nineteen_tasks_insufficient():
    assert compare_windows(evidence(), evidence(complete_tasks=19), candidate())['status'] == 'insufficient_evidence'


def test_p95_requires_one_hundred():
    b = evidence(tail_samples=99); b['measurements']['latency_p95'] = b['measurements']['latency']
    result = compare_windows(b, b, candidate(metric='latency_p95'))
    assert result['p95_conclusion'] is None and result['status'] == 'insufficient_evidence'


@pytest.mark.parametrize('change', [dict(model_ids=['different']), dict(config_hash='other'),
                                  dict(confounders=['manual_deployment']), dict(identity=dict(deployment_id='manual-new', generation=2, owner='human', image_ids={'api': 'old'}))])
def test_manual_or_model_change_confounds_window(change):
    assert compare_windows(evidence(), evidence(**change), candidate())['status'] == 'confounded'


def test_quality_is_not_inferred_from_cost():
    assert compare_windows(evidence(), evidence(), candidate(metric='quality', scope='writing_quality'))['status'] == 'insufficient_evidence'


def test_improvement_regression_and_frozen_binding():
    b = evidence(); c = evidence(id='candidate-1')
    c['measurements']['latency']['value'] = 80
    result = compare_windows(b, c, candidate())
    assert result['status'] == 'improved'
    assert result['plan_hash'] == candidate().plan_hash
    assert result['baseline'] == 'base-1' and result['config_hash'] == 'config-1'
    c['measurements']['errors']['value'] = .3
    assert compare_windows(b, c, candidate())['status'] == 'regressed'


def test_synthetic_requires_distinct_matched_pairs():
    plan = candidate(evidence_domain='synthetic', sample_floor=5)
    b = evidence(evidence_domain='synthetic', paired_group_ids=['a'] * 5)
    assert compare_windows(b, b, plan)['status'] == 'insufficient_evidence'
    b['paired_group_ids'] = list('abcde')
    assert compare_windows(b, b, plan)['status'] == 'not_improved'
    c = evidence(evidence_domain='synthetic', paired_group_ids=list('fghij'))
    assert compare_windows(b, c, plan)['status'] == 'insufficient_evidence'


def test_unknown_or_mixed_versions_cannot_authorize():
    assert compare_windows(evidence(), evidence(availability='unknown'), candidate())['status'] == 'insufficient_evidence'
    assert compare_windows(evidence(id='wrong'), evidence(), candidate())['status'] == 'confounded'


def test_expected_pi_candidate_deployment_is_not_manual_confound():
    c = evidence(identity=dict(deployment_id='pi-new', generation=2, owner='pi', image_ids={'api': 'new'}))
    assert compare_windows(evidence(), c, candidate())['status'] == 'not_improved'


def test_measurement_sample_floor_cannot_be_replaced_by_completed_count():
    b = evidence(); b['measurements']['latency']['samples'] = 1
    assert compare_windows(b, b, candidate())['status'] == 'insufficient_evidence'


def test_cost_metric_cannot_prove_writing_quality_scope():
    b = evidence(); b['measurements']['cost'] = b['measurements']['latency']
    assert compare_windows(b, b, candidate(scope='writing_quality', metric='cost'))['status'] == 'insufficient_evidence'


@pytest.mark.parametrize('guard', [False, True])
def test_cost_target_or_guard_requires_stable_confirmed_pricing(guard):
    b = evidence(); c = evidence()
    for s in (b, c):
        s['measurements']['cost'] = dict(value=1, availability='measured', samples=20, direction='lower')
    plan = candidate(metric='latency' if guard else 'cost', guard_metrics=('cost',) if guard else ('errors',))
    assert compare_windows(b, c, plan)['status'] == 'not_improved'
    c['pricing_id'] = 'b' * 64
    assert compare_windows(b, c, plan)['status'] == 'confounded'
    c['pricing_id'] = None
    assert compare_windows(b, c, plan)['status'] == 'insufficient_evidence'


def test_unknown_complete_configuration_cannot_claim_matching():
    assert compare_windows(evidence(config_hash=None), evidence(config_hash=None), candidate())['status'] == 'insufficient_evidence'
