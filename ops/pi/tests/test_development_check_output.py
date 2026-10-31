"""Synthetic checker subprocesses: raw candidate output never displaces the report."""
import json
from pathlib import Path
import subprocess
import sys
from ops.pi.unit_feedback import diagnostic,validate_report


def worker(tmp_path,source):
    base=Path(__file__).parents[1];(tmp_path/'test.py').write_text(source)
    (tmp_path/'feedback.py').write_text((base/'unit_feedback.py').read_text())
    code=(base/'workers/development_check.py').read_text()
    for name in ('test.py','feedback.py','src'):
        code=code.replace(repr('/source/'+name),repr(str(tmp_path/name)))
    result=subprocess.run([sys.executable,'-I','-c',code],capture_output=True,text=True,timeout=15)
    assert len(result.stdout.encode())+len(result.stderr.encode())<65536
    assert result.stderr=='' and 'PRIVATE-TRACE' not in result.stdout
    return result,json.loads(result.stdout)


def test_many_attribute_errors_remain_complete_typed_failures(tmp_path):
    source='import unittest\nclass Dense(unittest.TestCase):\n'
    for i in range(226):
        body='raise AttributeError("Object has no attribute \'status\'; PRIVATE-TRACE-"+"x"*2048)' if i<60 else 'pass'
        source+='    def test_'+str(i).zfill(3)+'(self): '+body+'\n'
    process,raw=worker(tmp_path,source)
    expected=['fixed_development_tests.Dense.test_'+str(i).zfill(3) for i in range(226)]
    validate_report(raw,process.returncode,expected)
    assert process.returncode==1 and raw['tests']==226 and raw['errors']==60 and raw['passed'] is False
    assert len(raw['diagnostics'])==60 and all(d['attribute']=='status' for d in raw['diagnostics'])


def test_import_error_only_emits_finite_load_error_metadata(tmp_path):
    process,raw=worker(tmp_path,'raise RuntimeError("PRIVATE-TRACE-"+"x"*70000)')
    validate_report(raw,process.returncode,['fixed_development_tests.Case.test_one'])
    assert process.returncode==1 and raw['load_error'] and raw['tests']==0 and raw['errors']==1 and not raw['passed']
    assert raw['diagnostics']==[dict(case=None,category='RuntimeError',attribute=None)]


def test_import_and_test_prints_do_not_pollute_success_report(tmp_path):
    source='import unittest,sys\nprint("PRIVATE-TRACE-import")\nclass Clean(unittest.TestCase):\n    def test_one(self):\n        print("PRIVATE-TRACE-test")\n        print("PRIVATE-TRACE-stderr",file=sys.stderr)\n'
    process,raw=worker(tmp_path,source);validate_report(raw,process.returncode,['fixed_development_tests.Clean.test_one'])
    assert raw['passed'] and raw['tests']==1


def test_only_approved_status_attribute_is_exposed():
    assert diagnostic(None,"AttributeError: 'Fact' object has no attribute 'status'")['attribute']=='status'
    assert diagnostic(None,"AttributeError: 'Fact' object has no attribute 'private_token'")['attribute']=='unknown_attribute'


import pytest


@pytest.mark.parametrize('statement',[
    'import sys; sys.exit("PRIVATE-TRACE-import-exit")',
    'raise KeyboardInterrupt("PRIVATE-TRACE-import-interrupt")',
])
def test_import_baseexception_is_a_typed_failure_not_raw_exit(tmp_path,statement):
    process,raw=worker(tmp_path,statement)
    validate_report(raw,process.returncode,['fixed_development_tests.Case.test_one'])
    assert process.returncode==1 and raw['load_error'] and raw['errors']==1 and not raw['passed']
    assert raw['diagnostics']==[dict(case=None,category='RuntimeError',attribute=None)]
