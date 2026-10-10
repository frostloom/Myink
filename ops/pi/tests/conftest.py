"""Explicit opt-in gates run after pytest marker deselection."""
import json
import subprocess
import pytest


def pytest_addoption(parser):
    parser.addoption('--pi-lab', action='store_true', help='Run verified private lab tests')
    parser.addoption('--pi-live', action='store_true', help='Request paid tests; all B/price/scope gates still required')


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    lab = [item for item in items if item.get_closest_marker('pi_lab')]
    live = [item for item in items if item.get_closest_marker('pi_live')]
    if lab and not config.getoption('--pi-lab'):
        raise pytest.UsageError('selected pi_lab tests require --pi-lab')
    if live:
        if not config.getoption('--pi-live'):
            raise pytest.UsageError('selected pi_live tests require --pi-live')
        # C14 has not accepted all B gates. Direct pytest cannot bypass it.
        raise pytest.UsageError('pi_live blocked: B acceptance and calibrated price/cumulative scope gates pending')
    if lab:
        try:
            from ops.pi.lab.verify import verify_test_environment
            if any(item.path.parent.name == 'integration' for item in lab):
                identity,_ = verify_test_environment()
            else:
                # Windows installer/watchdog tests contain no DB fixture; still require fresh runtime.
                result=subprocess.run(['wsl.exe','-d','MyinkPiLab','-u','root','--','/opt/myink-pi-lab/provision.sh','preflight'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120,check=True)
                identity=json.loads(result.stdout)
            config._pi_lab_identity=identity
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            reason=str(error) if isinstance(error,ValueError) else type(error).__name__
            raise pytest.UsageError('pi_lab blocked: fresh owned operation/runtime and fixture endpoint proof required: '+reason)



@pytest.fixture
def lab_identity(request):
    return request.config._pi_lab_identity
