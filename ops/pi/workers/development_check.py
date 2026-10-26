"""Fixed isolated unittest runner. Only finite diagnostic metadata leaves the host."""
import os
import sys
os.environ.clear()
os.environ.update(HOME='/work', TMPDIR='/tmp', PYTHONDONTWRITEBYTECODE='1', EMBED_ENABLED='0', RANKINGS_ENABLED='0')
import site
site.main()
sys.path.insert(0, '/source/src')
import importlib.util
import json
import traceback
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import TextIOBase

feedback_spec=importlib.util.spec_from_file_location('fixed_feedback','/source/feedback.py')
feedback=importlib.util.module_from_spec(feedback_spec)
feedback_spec.loader.exec_module(feedback)


def inventory(group):
    result=[]
    for test in group:
        result.extend(inventory(test) if isinstance(test,unittest.TestSuite) else [test.id()])
    return result


class QuietOutput(TextIOBase):
    """Discard verbose test output; only fixed typed metadata is emitted."""
    def write(self, text):
        return len(text)


quiet = QuietOutput()
try:
    with redirect_stdout(quiet), redirect_stderr(quiet):
        spec=importlib.util.spec_from_file_location('fixed_development_tests','/source/test.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite=unittest.defaultTestLoader.loadTestsFromModule(module)
except BaseException as exc:
    detail=feedback.diagnostic(None,''.join(traceback.format_exception_only(type(exc),exc)))
    print(json.dumps(dict(tests=0,cases=[],failures=0,errors=1,skipped=0,passed=False,
        failed_cases=[],error_cases=[],diagnostics=[detail],load_error=True)))
    raise SystemExit(1)

cases=inventory(suite)
with redirect_stdout(quiet), redirect_stderr(quiet):
    result=unittest.TextTestRunner(stream=quiet,verbosity=1).run(suite)
passed=result.wasSuccessful() and result.testsRun==len(cases) and not result.skipped
print(json.dumps(dict(tests=result.testsRun,cases=cases,failures=len(result.failures),
    errors=len(result.errors),skipped=len(result.skipped),passed=passed,
    failed_cases=[test.id() for test,_ in result.failures],
    error_cases=[test.id() for test,_ in result.errors],
    diagnostics=[feedback.diagnostic(test.id(),trace) for test,trace in result.errors],load_error=False)))
raise SystemExit(0 if passed else 1)
