"""Failure feedback is bounded fixed data, never model authority or raw trace text."""
from copy import deepcopy
from dataclasses import asdict
import pytest
from ops.pi.contracts import Receipt
from ops.pi.tools import _failed_check_feedback,digest,ToolDenied
from ops.pi.unit_feedback import validate_report

CASES=['fixed_development_tests.Case.test_bad','fixed_development_tests.Case.test_ok']
SHA='a'*64


def report():
    return dict(tests=2,cases=CASES,failures=1,errors=0,skipped=0,passed=False,
                failed_cases=[CASES[0]],error_cases=[],diagnostics=[],load_error=False)


def snapshot():
    return dict(candidate_hash='candidate',plan_hash='plan',base='base',candidate_id='id',generation=1,check_id='unit')


def test_fixed_failure_projects_only_typed_case_metadata():
    raw=report();validate_report(raw,1,CASES)
    s=snapshot();receipt=Receipt('development-check:'+digest(s),'blocked',dict(s,result='failed',verified=True,
        mode='ACTUAL',test_sha256=SHA,report=raw))
    out=_failed_check_feedback(receipt,s,unit_test_sha256=SHA,unit_case_ids=CASES)
    assert out['check_feedback']['failed_cases']==[CASES[0]]
    assert out['check_feedback']['result']=='failed'
    assert out['check_feedback']['remediation_codes']==['fixed_unittest_failed']
    assert 'report' not in out and 'reason' not in out['check_feedback']
    with pytest.raises(ToolDenied):_failed_check_feedback(receipt,s,unit_test_sha256='b'*64,unit_case_ids=CASES)
    with pytest.raises(ToolDenied):_failed_check_feedback(receipt,dict(s,candidate_hash='stale'),unit_test_sha256=SHA,unit_case_ids=CASES)


@pytest.mark.parametrize('change',[
    dict(passed=True),dict(failures=0),dict(cases=['foreign']),dict(failed_cases=['foreign']),
    dict(diagnostics=[dict(case=CASES[0],category='run_shell',attribute=None)]),dict(diagnostics=[dict(case=CASES[0],category='AttributeError',attribute='$(secret)')]),dict(skipped=1),
    dict(text='private source or arbitrary instruction'),dict(tests=True),dict(failed_cases=[CASES[0],CASES[0]])])
def test_invalid_fixed_failure_never_forwarded(change):
    value=dict(report(),**change)
    with pytest.raises(ValueError):validate_report(value,1,CASES)


def test_error_and_load_failure_are_explicitly_not_passes():
    raw=dict(report(),failures=0,errors=1,failed_cases=[],error_cases=[CASES[0]],diagnostics=[dict(case=CASES[0],category='AttributeError',attribute='statement')])
    validate_report(raw,1,CASES)
    raw=dict(raw,tests=0,cases=[],errors=1,error_cases=[],diagnostics=[dict(case=None,category='SyntaxError',attribute=None)],load_error=True)
    validate_report(raw,1,CASES)
    with pytest.raises(ValueError):validate_report(raw,0,CASES)


def test_unapproved_attribute_and_unsupported_duplicate_errors_fail_closed():
    raw=dict(report(),failures=0,errors=1,failed_cases=[],error_cases=[CASES[0]],
             diagnostics=[dict(case=CASES[0],category='AttributeError',attribute='secret_key')])
    with pytest.raises(ValueError):validate_report(raw,1,CASES)
    raw['diagnostics'][0]['attribute']='unknown_attribute';validate_report(raw,1,CASES)
    raw.update(errors=2,error_cases=[CASES[0],CASES[0]])
    with pytest.raises(ValueError):validate_report(raw,1,CASES)


def test_class_setup_and_subtest_ids_are_not_silently_counted_as_cases():
    for case in ('setUpClass (fixed_development_tests.Case)',CASES[0]+' (x=1)'):
        raw=dict(report(),failures=0,errors=1,failed_cases=[],error_cases=[case],
                 diagnostics=[dict(case=case,category='ValueError',attribute=None)])
        with pytest.raises(ValueError):validate_report(raw,1,CASES)


def test_projection_cannot_select_its_own_valid_looking_inventory():
    raw=report();raw['cases']=['fixed_development_tests.Other.test_one'];raw['tests']=1
    raw['failed_cases']=raw['cases'];s=snapshot()
    receipt=Receipt('development-check:'+digest(s),'blocked',dict(s,result='failed',verified=True,
        mode='ACTUAL',test_sha256=SHA,report=raw))
    with pytest.raises(ToolDenied):_failed_check_feedback(receipt,s,unit_test_sha256=SHA,unit_case_ids=CASES)


def test_diagnostic_maps_arbitrary_attribute_and_trace_text_to_closed_enum():
    from ops.pi.unit_feedback import diagnostic
    value=diagnostic(CASES[0],"sensitive raw source\nAttributeError: 'Object' object has no attribute 'private_token_123'")
    assert value==dict(case=CASES[0],category='AttributeError',attribute='unknown_attribute')
    assert 'private_token' not in str(value)
    assert diagnostic(None,'SyntaxError: arbitrary source')==dict(case=None,category='SyntaxError',attribute=None)


def test_import_error_keeps_expected_inventory_host_selected():
    raw=dict(report(),tests=0,cases=[],failures=0,errors=1,failed_cases=[],error_cases=[],
             diagnostics=[dict(case=None,category='SyntaxError',attribute=None)],load_error=True)
    s=snapshot();receipt=Receipt('development-check:'+digest(s),'blocked',dict(s,result='failed',verified=True,
        mode='ACTUAL',test_sha256=SHA,report=raw))
    out=_failed_check_feedback(receipt,s,unit_test_sha256=SHA,unit_case_ids=CASES)
    assert out['check_feedback']['load_error'] is True
    assert out['check_feedback']['diagnostics'][0]['category']=='SyntaxError'


def test_report_survives_docker_stdout_stderr_reordering():
    import json
    from ops.pi.development_launcher import parse_check_output
    raw=dict(report(),failures=0,failed_cases=[],passed=True)
    for output in (json.dumps(raw)+'\n\nRan 2 tests\n\nOK\n',
                   'Ran 2 tests\nOK\n'+json.dumps(raw)+'\n'):
        assert parse_check_output(output)==raw
    with pytest.raises(ValueError):parse_check_output(json.dumps(raw)+'\n'+json.dumps(raw))
    with pytest.raises(ValueError):parse_check_output('Ran 2 tests\nOK\n')
