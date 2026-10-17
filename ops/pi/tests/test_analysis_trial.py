"""Preregistered contract comparison. No model, network or private prose."""
from copy import deepcopy
import importlib
import importlib.util
import inspect
import json

import pytest

from ops.pi.tests.test_writing_analysis import DOMAINS, fixture, plan


def trial():
    assert importlib.util.find_spec('ops.pi.analysis_trial') is not None
    return importlib.import_module('ops.pi.analysis_trial')


def test_freeze_locks_prompt_factor_and_refuses_execution():
    view, report = fixture()
    mod = trial()
    frozen = mod.freeze_contract_trial(view, report)
    assert frozen['changed_factor'] == 'prompt'
    assert frozen['groups'] == ['recall.events', 'recall.plot', 'recall.characters', 'extract', 'operations']
    assert frozen['automatic_execution'] is False
    assert frozen['release_allowed'] is False
    assert frozen['adopt_rule'] == 'candidate_valid_count > baseline_valid_count'
    assert frozen['semantic_metrics'] == 'unknown'
    assert 'executor' not in inspect.signature(mod.freeze_contract_trial).parameters
    again = mod.freeze_contract_trial(view, report)
    assert again['freeze_sha256'] == frozen['freeze_sha256']
    changed = deepcopy(report)
    changed['operations']['write']['success']['value'] = 0.25
    assert mod.freeze_contract_trial(view, changed)['freeze_sha256'] != frozen['freeze_sha256']
    prompts = frozen['prompts']
    shared = {item['baseline_prompt_sha256'] for item in prompts}
    assert len(shared) == 1
    assert len({item['candidate_prompt_sha256'] for item in prompts}) == 5
    recall = next(item for item in prompts if item['group'] == 'recall.events')
    operations = next(item for item in prompts if item['group'] == 'operations')
    assert 'operations may cite the body-free report in prose' in recall['baseline_prompt']
    assert 'operations may cite the body-free report in prose' not in recall['candidate_prompt']
    assert 'only recall.events may be trace_observation' in recall['candidate_prompt']
    assert 'only operations may be trace_observation' in operations['candidate_prompt']
    assert 'operations may cite the body-free report in prose' in operations['candidate_prompt']


def test_scorer_adds_target_rule_without_loosening_validator():
    view, _ = fixture()
    mod = trial()
    quiet = plan()
    assert mod.score_contract_output(quiet, view, 'recall.events')['valid'] is True
    operations_trace = plan()
    operations_trace['domains'][DOMAINS.index('operations')]['availability'] = 'trace_observation'
    from ops.pi.writing_analysis import validate_writing_analysis
    assert validate_writing_analysis(operations_trace, view) == operations_trace
    with pytest.raises(ValueError, match='non-target'):
        mod.score_contract_output(operations_trace, view, 'recall.events')
    assert mod.score_contract_output(operations_trace, view, 'operations')['valid'] is True
    array_rollback = plan()
    array_rollback['hypothesis']['rollback'] = ['恢复旧提示']
    with pytest.raises(ValueError):
        mod.score_contract_output(array_rollback, view, 'extract')


@pytest.mark.parametrize('target_domain', DOMAINS)
def test_target_scope_accepts_only_selected_domain(target_domain):
    from ops.pi.writing_analysis import parse_writing_analysis
    view, _ = fixture()
    original = deepcopy(view)
    result = plan()
    selected = result['domains'][DOMAINS.index(target_domain)]
    selected.update(availability='trace_observation', refs=[
        {'evidence_index': 0, 'excerpt_index': 0, 'quote': 'start'}])
    parsed = parse_writing_analysis(json.dumps(result, ensure_ascii=False), view)
    assert trial().score_contract_output(parsed, view, target_domain) == {
        'valid': True, 'target_domain': target_domain}
    assert view == original


@pytest.mark.parametrize('target_domain,other_domain', [
    (target, other) for target in DOMAINS for other in DOMAINS if target != other])
@pytest.mark.parametrize('availability', ['trace_observation', 'unknown'])
def test_target_scope_rejects_every_non_target_observation_or_reference(
        target_domain, other_domain, availability):
    from ops.pi.writing_analysis import parse_writing_analysis
    view, _ = fixture()
    result = plan()
    other = result['domains'][DOMAINS.index(other_domain)]
    other.update(availability=availability, refs=[
        {'evidence_index': 0, 'excerpt_index': 0, 'quote': 'start'}])
    # The base contract accepts these grounded fields; rejection must come from scope.
    parsed = parse_writing_analysis(json.dumps(result, ensure_ascii=False), view)
    with pytest.raises(ValueError, match='non-target domain must stay unknown'):
        trial().score_contract_output(parsed, view, target_domain)


@pytest.mark.parametrize('target_domain', DOMAINS)
def test_only_operations_target_can_observe_without_references(target_domain):
    view, _ = fixture()
    result = plan()
    result['domains'][DOMAINS.index(target_domain)]['availability'] = 'trace_observation'
    if target_domain == 'operations':
        assert trial().score_contract_output(result, view, target_domain) == {
            'valid': True, 'target_domain': 'operations'}
    else:
        with pytest.raises(ValueError, match='finite grounded references required'):
            trial().score_contract_output(result, view, target_domain)
