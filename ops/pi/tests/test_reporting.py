import importlib.util
import json
import pytest
from ops.pi.control import main


def render(events, snapshots):
    if importlib.util.find_spec('ops.pi.reporting') is None:
        return ''
    from ops.pi.reporting import render_report
    return render_report(events, snapshots)


def test_report_keeps_failure_after_success():
    result = render([{'kind': 'receipt', 'payload': {'operation_id': 'build-1', 'status': 'failed'}}, {'kind': 'receipt', 'payload': {'operation_id': 'build-2', 'status': 'done'}}], [])
    assert 'build-1' in result and 'failed' in result and 'build-2' in result


def test_no_release_has_reason_and_next_action():
    result = render([], [])
    assert 'No release' in result and 'Reason:' in result and 'Next action:' in result
    assert 'A4 live database' in result and 'pending' in result


def test_unknown_cost_not_zero():
    result = render([], [{'cost_cny': None}])
    assert 'unknown' in result and '0 CNY' not in result


def test_report_redacts_raw_evidence_and_credentials():
    result = render([{'kind': 'fault', 'payload': {'status': 'failed', 'evidence': {'secret': 'RAW_SECRET'}, 'api_key': 'KEY_SECRET'}}], [])
    assert 'failed' in result
    assert 'RAW_SECRET' not in result and 'KEY_SECRET' not in result


def test_cli_writes_markdown_and_index(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr('ops.pi.control.state_path_allowed', lambda path: True)
    output = tmp_path / 'daily.md'
    try:
        code = main(['report', '--state-dir', str(tmp_path), '--output', str(output)])
    except SystemExit:
        code = 2
    assert code == 0
    assert 'Next action:' in output.read_text(encoding='utf-8')
    index = json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
    assert index['pending_acceptance'] and index['event_count'] == 0


def test_unknown_measurement_cannot_be_replaced_with_legacy_cost():
    result = render([], [{'measurements': {'cost': {'availability': 'unknown', 'value': None}}, 'cost_cny': 0}])
    assert 'cost=unknown' in result and '0 CNY' not in result


def test_legacy_zero_without_measurement_stays_unknown():
    result = render([], [{'cost_cny': 0}])
    assert 'cost=unknown' in result and '0 CNY' not in result


def test_valid_measured_zero_remains_known():
    result = render([], [{'measurements': {'cost': {'availability': 'measured', 'value': 0}}}])
    assert 'cost=0 CNY' in result


@pytest.mark.parametrize('suffix', ['.json', '.JSON'])
def test_cli_rejects_json_output_before_writing(tmp_path, monkeypatch, suffix):
    monkeypatch.setattr('ops.pi.control.state_path_allowed', lambda path: True)
    output = tmp_path / ('daily' + suffix)
    output.write_text('existing report', encoding='utf-8')
    assert main(['report', '--state-dir', str(tmp_path), '--output', str(output)]) == 1
    assert output.read_text(encoding='utf-8') == 'existing report'
