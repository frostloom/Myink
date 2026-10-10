"""Explicit opt-in gates run after pytest marker deselection."""
import json
import os
from pathlib import Path
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
        path = os.environ.get('PI_LAB_ENV', '')
        try:
            receipt = json.loads(Path(path).read_text())
            if receipt['daemon_id'] != '364e8400-3844-47e2-b86d-8b626332f61c' or receipt['status'] != 'done':
                raise ValueError('unverified lab')
        except (OSError, ValueError, KeyError):
            raise pytest.UsageError('pi_lab blocked: successful private lab preflight required')


@pytest.fixture
def lab_identity():
    return json.loads(Path(os.environ['PI_LAB_ENV']).read_text())
