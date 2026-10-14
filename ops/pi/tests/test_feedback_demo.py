"""Synthetic end-to-end contract; no DB, model or actual user submission."""
from copy import deepcopy
import json
import pytest


def api():
    from ops.pi import feedback_demo
    return feedback_demo


def test_all_existing_thirty_cases_flow_through_the_existing_pipeline():
    result = api().run_demo()
    assert result['synthetic'] is True
    assert result['database_execution'] == result['model_execution'] == 'MOCK'
    assert result['automatic_execution'] is result['candidate_allowed'] is False
    assert result['case_count'] == 30 and result['route_agreement_count'] == 30
    assert result['semantic_quality'] == 'unknown'
    assert len({c['case_id'] for c in result['cases']}) == 30
    assert all(c['status'] == 'valid' and c['host_reason'] for c in result['cases'])
    assert all(c['automatic_execution'] is c['candidate_allowed'] is False for c in result['cases'])


@pytest.mark.parametrize('case_id,route', [
    ('save_error', 'investigate'), ('feature', 'owner_decision'),
    ('system', 'deny'), ('database', 'deny'), ('auth', 'deny'),
    ('quoted', 'security_review'), ('encoded', 'security_review'),
    ('fake_system', 'security_review'), ('quoted_ui_error', 'investigate'),
])
def test_fixed_case_routes_and_explicit_reasons(case_id, route):
    case = api().run_demo([case_id])['cases'][0]
    assert case['case_id'] == case_id and case['host_route'] == route
    assert case['expected_host_route'] == route and case['host_reason']
    if route in ('deny', 'security_review'):
        assert case['risk_flags']


def test_projection_and_pi_prompt_omit_private_fields_and_reference_labels():
    prepared = api().prepare_demo(['system', 'feature'])
    assert prepared['synthetic'] is True
    for batch in prepared['batches']:
        assert batch['read_request']['read_only'] is True
        assert batch['read_request']['limit'] == 51
        assert batch['read_request']['timeout_ms'] == 5000
        assert batch['tools'] == [] and 'schema_version:2' in batch['prompt']
        assert 'expected_classification' not in batch['prompt'] and 'expected_host_route' not in batch['prompt']
        for marker in ('synthetic-contact@example.invalid', 'synthetic-user-private', 'synthetic-browser-private'):
            assert marker not in batch['prompt']
        assert all(row['untrusted_body_text'] is True for row in batch['snapshot']['rows'])
        assert all(set(row) == set(__import__('ops.pi.feedback', fromlist=['_ROW_FIELDS'])._ROW_FIELDS)
                   for row in batch['snapshot']['rows'])


def test_bad_model_output_is_unknown_and_never_repaired():
    batch = api().prepare_demo(['save_error'])['batches'][0]
    checked = api().evaluate_demo_response(batch, b'not json')
    assert checked['status'] == 'schema_failed'
    assert checked['cases'][0]['status'] == 'unknown'
    assert checked['cases'][0]['host_route'] is None
    assert checked['automatic_execution'] is False


def test_model_cannot_add_authority_or_forge_quote():
    batch = api().prepare_demo(['save_error'])['batches'][0]
    raw = json.loads(api().mock_response(batch))
    for change in ('authority', 'quote'):
        bad = deepcopy(raw)
        if change == 'authority':
            bad['items'][0]['candidate_allowed'] = True
        else:
            bad['items'][0]['refs'][0]['quote'] = 'not present'
        checked = api().evaluate_demo_response(batch, json.dumps(bad))
        assert checked['status'] == 'schema_failed'
        assert checked['cases'][0]['status'] == 'unknown'
        assert checked['candidate_allowed'] is False


@pytest.mark.parametrize('case_ids', [[], ['foreign'], ['save_error', 'save_error'], 'save_error'])
def test_selection_rejects_empty_foreign_duplicate_or_wrong_type(case_ids):
    with pytest.raises(ValueError):
        api().prepare_demo(case_ids)


def test_fixture_pin_tampering_fails_before_projection(monkeypatch):
    monkeypatch.setattr(api(), 'CORPUS_SHA256', '0' * 64)
    with pytest.raises(ValueError):
        api().prepare_demo()


def test_cli_default_is_mock_and_errors_never_echo_arguments(capsys):
    assert api().main(['--case', 'save_error']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['model_execution'] == 'MOCK' and result['cases'][0]['host_route'] == 'investigate'
    assert api().main(['--secret-token-never-echo']) == 2
    error = capsys.readouterr()
    assert 'secret-token' not in error.err and error.out == ''


def test_actual_isolated_cli_stdout_is_utf8_json():
    from pathlib import Path
    import subprocess, sys
    script = Path(__file__).resolve().parents[3] / 'scripts/pi-feedback-demo.py'
    run = subprocess.run([sys.executable, '-I', '-B', str(script), '--case', 'save_error'],
                         capture_output=True, timeout=30)
    assert run.returncode == 0 and run.stderr == b''
    result = json.loads(run.stdout.decode('utf-8'))
    assert result['synthetic'] is True and result['model_execution'] == 'MOCK'
    assert result['cases'][0]['submission']['description'] == '保存按钮失灵'


def test_host_reference_mutation_cannot_change_submission_or_pi_prompt(monkeypatch):
    from datetime import datetime, timezone
    from ops.pi import feedback, db_reader
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2020, 1, 2, tzinfo=timezone.utc)
    monkeypatch.setattr(feedback, 'datetime', FixedClock)
    monkeypatch.setattr(db_reader, 'datetime', FixedClock)
    corpus = api()._corpus()
    before = api().prepare_demo(['save_error'])['batches'][0]
    changed = deepcopy(corpus)
    next(c for c in changed if c['case_id'] == 'save_error')['expected_classification'] = 'new_feature'
    monkeypatch.setattr(api(), '_corpus', lambda: changed)
    after = api().prepare_demo(['save_error'])['batches'][0]
    assert before['references'] != after['references']
    assert before['submissions'] == after['submissions']
    assert before['snapshot'] == after['snapshot']
    assert before['prompt'] == after['prompt']
    assert before['prompt_sha256'] == after['prompt_sha256']
    assert before['submissions'][0]['submission']['category'] == 'other'
