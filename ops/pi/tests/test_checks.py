"""A skipped/missing case or helper DONE must never certify full CI."""
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path

import pytest
from ops.pi.checks import run_checks
from ops.pi.contracts import Receipt


SHA = 'a' * 40
CONTENT = 'b' * 64


def lab(tmp_path):
    return {'candidate_sha': SHA, 'source_hash': CONTENT,
            'artifact_dir': tmp_path, 'lock_path': tmp_path / 'heavy.lock',
            'deadline': datetime.now(timezone.utc) + timedelta(seconds=60),
            'planned_peak_bytes': 1, 'host_free_bytes': 6 * 1024**3,
            'guest_free_bytes': 6 * 1024**3,
            'required_cases': {'python-tests': ['suite.test_ok'], 'ops-tests': ['suite.test_ok'],
                               'frontend-tests': ['suite.test_ok']}}


class Runner:
    def __init__(self, root, fault=None):
        self.root, self.fault, self.calls = root, fault, []
    def __call__(self, action, request):
        self.calls.append((action, request))
        if action == 'checks.prepare':
            return Receipt('prepare', 'done', {'status': 'PASS', 'candidate_sha': SHA,
                'source_hash': CONTENT, 'sandbox_verified': True, 'dependency_inventory_verified': True,
                'resource_limits_verified': True, 'fixture_identity_verified': True})
        if action == 'checks.cleanup':
            return Receipt('cleanup', 'done', {'status': 'PASS', 'owned_exit_verified': True,
                                               'source_unchanged': True})
        if action == 'checks.run':
            check = request['check']
            if self.fault == 'missing' and check == 'python-tests':
                return Receipt('check', 'done', {})
            stdout = self.root / (check + '.stdout')
            stdout.write_bytes(b'captured raw child output')
            evidence = {'candidate_sha': SHA, 'source_hash': CONTENT,
                'command': request['command'], 'version': 'verified-tool-1',
                'returncode': 0, 'stdout': str(stdout), 'stderr': str(stdout)}
            if request['junit']:
                junit = self.root / (check + '.xml')
                skipped = '<skipped/>' if self.fault == 'skip' and check == 'python-tests' else ''
                name = 'other' if self.fault == 'missing_case' and check == 'python-tests' else 'test_ok'
                junit.write_text('<testsuites><testsuite><testcase classname="suite" name="' +
                                 name + '">' + skipped + '</testcase></testsuite></testsuites>')
                evidence['junit'] = str(junit)
            if self.fault == 'helper_done' and check == 'python-tests':
                evidence = {'selection': 'b8-ci-collection', 'returncode': 0}
            return Receipt('check', 'done', evidence)
        raise AssertionError(action)


@pytest.mark.parametrize('fault', ['skip', 'missing', 'missing_case', 'helper_done'])
def test_skip_or_missing_required_check_blocks(tmp_path, fault):
    runner = Runner(tmp_path, fault)
    receipts = run_checks(SHA, lab(tmp_path), runner)
    assert receipts and any(r.status != 'done' for r in receipts)
    assert not any(a == 'checks.run' and q['check'] == 'frontend-build' for a, q in runner.calls)


def test_complete_required_checks_have_structured_source_bound_receipts(tmp_path):
    runner = Runner(tmp_path)
    receipts = run_checks(SHA, lab(tmp_path), runner)
    assert len(receipts) == 12
    assert all(r.status == 'done' for r in receipts)
    for receipt in receipts:
        evidence = receipt.evidence
        assert evidence['required'] is True and evidence['status'] == 'PASS'
        assert evidence['pass'] is True and evidence['fail'] is False and evidence['skip'] is False
        assert evidence['candidate_sha'] == SHA and evidence['source_hash'] == CONTENT
        assert evidence['command'] and evidence['version'] and len(evidence['artifact_hash']) == 64
    frontend = [q for a, q in runner.calls if a == 'checks.run' and q['check'] == 'frontend-tests'][0]
    assert '--maxWorkers=1' in frontend['command'] and '--no-file-parallelism' in frontend['command']


def test_cleanup_failure_revokes_completed_checks(tmp_path):
    runner = Runner(tmp_path)
    def execute(action, request):
        if action == 'checks.cleanup':
            return Receipt('cleanup', 'uncertain', {'owned_exit_verified': False})
        return runner(action, request)
    receipts = run_checks(SHA, lab(tmp_path), execute)
    assert receipts and receipts[-1].status != 'done'
    assert receipts[-1].evidence['reason'] == 'cleanup_unconfirmed'


def test_candidate_source_mismatch_never_launches(tmp_path):
    runner = Runner(tmp_path)
    receipts = run_checks('c' * 40, lab(tmp_path), runner)
    assert receipts and receipts[0].status == 'blocked'
    assert not runner.calls


def test_disk_new_peak_plus_five_gib_required(tmp_path):
    state = lab(tmp_path)
    state['guest_free_bytes'] = 5 * 1024**3
    runner = Runner(tmp_path)
    receipts = run_checks(SHA, state, runner)
    assert receipts and receipts[0].status == 'blocked' and not runner.calls


def test_junit_external_or_duplicate_case_is_rejected(tmp_path):
    from ops.pi.checks import parse_junit
    path = tmp_path / 'cases.xml'
    path.write_text('<testsuite><testcase classname="s" name="t"/><testcase classname="s" name="t"/></testsuite>')
    with pytest.raises(ValueError):
        parse_junit(path, ['s.t'])
@pytest.mark.parametrize('fault', ['returncode', 'command', 'version', 'source', 'artifact_escape'])
def test_check_evidence_cannot_claim_unbound_success(tmp_path, fault):
    runner = Runner(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + '-foreign.stdout')
    outside.write_bytes(b'foreign')
    def execute(action, request):
        result = runner(action, request)
        if action == 'checks.run' and request['check'] == 'python-tests':
            if fault == 'returncode': result.evidence['returncode'] = 1
            if fault == 'command': result.evidence['command'] = ['false']
            if fault == 'version': result.evidence['version'] = ''
            if fault == 'source': result.evidence['source_hash'] = 'c' * 64
            if fault == 'artifact_escape': result.evidence['stdout'] = str(outside)
        return result
    receipts = run_checks(SHA, lab(tmp_path), execute)
    assert any(r.status != 'done' for r in receipts)
    assert not any(a == 'checks.run' and q['check'] == 'frontend-build' for a, q in runner.calls)


def test_unknown_cleanup_blocks_next_heavy_session(tmp_path):
    from ops.pi.build import HeavyAction
    runner = Runner(tmp_path)
    def execute(action, request):
        if action == 'checks.cleanup':
            raise OSError('owned descendants unresolved')
        return runner(action, request)
    run_checks(SHA, lab(tmp_path), execute)
    with pytest.raises(ValueError):
        with HeavyAction(tmp_path / 'heavy.lock'):
            raise AssertionError('unresolved cleanup released the next candidate')


def test_frozen_source_changed_or_linked_input_is_rejected(tmp_path):
    from ops.pi.lab.build_lab import verify_source
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'a.py').write_bytes(b'approved')
    manifest = {'a.py': hashlib.sha256(b'approved').hexdigest()}
    assert verify_source(source, manifest)
    (source / 'a.py').write_bytes(b'changed')
    with pytest.raises(ValueError):
        verify_source(source, manifest)


def test_frozen_source_manifest_never_includes_env_or_private_state(tmp_path):
    from ops.pi.lab.build_lab import verify_source
    source = tmp_path / 'source'
    source.mkdir()
    (source / '.env').write_bytes(b'not a real secret')
    with pytest.raises(ValueError):
        verify_source(source, {'.env': hashlib.sha256(b'not a real secret').hexdigest()})