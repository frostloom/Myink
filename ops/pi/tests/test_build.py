"""Exercise serialization, load deadlines and protected image ownership."""
from datetime import datetime, timedelta, timezone
import threading

import pytest
from ops.pi.build import HeavyAction, build_images
from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger


SHA = 'a' * 40
HASH = 'b' * 64
API = 'sha256:' + '1' * 64
CADDY = 'sha256:' + '2' * 64


def state(tmp_path, execute):
    return {'candidate_sha': SHA, 'source_hash': HASH, 'artifact_dir': tmp_path,
            'lock_path': tmp_path / 'heavy.lock', 'executor': execute,
            'deadline': datetime.now(timezone.utc) + timedelta(seconds=120),
            'planned_peak_bytes': 1024, 'host_free_bytes': 6 * 1024**3,
            'guest_free_bytes': 6 * 1024**3,
            'protected_image_ids': [API], 'verified_image_sets': []}


class Builder:
    def __init__(self, fault=None):
        self.calls, self.fault = [], fault
    def __call__(self, action, request):
        self.calls.append((action, request))
        evidence = {'status': 'PASS', 'candidate_sha': SHA, 'source_hash': HASH}
        if action == 'build.prepare':
            evidence.update(sandbox_verified=True, resource_limits_verified=True,
                dependency_inventory_verified=True, builder_driver='remote', process_sandbox=True,
                builder_image='moby/buildkit@sha256:' + '3' * 64,
                memory_max_bytes=1610612736, memory_plus_swap_bytes=1879048192,
                cpu_max='200000 100000', max_parallelism=1)
        elif action == 'build.export':
            evidence.update(image_id=API if request['image'] == 'python' else CADDY,
                digest='sha256:' + '4' * 64, archive_hash='5' * 64,
                artifact_hash='6' * 64, revision=SHA, returncode=0)
        elif action == 'build.load':
            if self.fault == 'load_timeout':
                return Receipt('load', 'uncertain', {'reason': 'load_deadline_expired'})
            evidence.update(image_id=request['image_id'], revision=SHA,
                archive_hash=request['archive_hash'], returncode=0,
                daemon_overhead_measured=True, owned_import_terminal=True)
        elif action == 'build.cleanup':
            evidence.update(owned_exit_verified=self.fault != 'cleanup',
                            protected_images_unchanged=True)
        else:
            raise AssertionError(action)
        return Receipt('build', 'done', evidence)


def test_only_one_heavy_action_runs(tmp_path):
    path = tmp_path / 'heavy.lock'
    entered = threading.Event()
    errors = []
    with HeavyAction(path):
        def other():
            try:
                with HeavyAction(path):
                    entered.set()
            except (RuntimeError, OSError):
                errors.append('busy')
        thread = threading.Thread(target=other)
        thread.start()
        thread.join(timeout=2)
    assert not entered.is_set() and errors == ['busy']


def test_python_build_precedes_caddy(tmp_path):
    builder = Builder()
    receipt = build_images(SHA, state(tmp_path, builder), Ledger(tmp_path / 'ledger.sqlite'))
    assert receipt.status == 'done', receipt
    assert [(a, q['image']) for a, q in builder.calls if a in ('build.export', 'build.load')] == [
        ('build.export', 'python'), ('build.load', 'python'),
        ('build.export', 'caddy'), ('build.load', 'caddy')]
    prepare = builder.calls[0][1]
    assert prepare['memory_max_bytes'] == 1610612736
    assert prepare['memory_plus_swap_bytes'] == 1879048192


def test_workers_reuse_python_image(tmp_path):
    builder = Builder()
    receipt = build_images(SHA, state(tmp_path, builder), Ledger(tmp_path / 'ledger.sqlite'))
    assert receipt.evidence.get('worker_image_ids') == [API, API]
    assert receipt.evidence.get('api_image_id') == API


def test_loading_cost_is_in_deadline(tmp_path):
    builder = Builder('load_timeout')
    receipt = build_images(SHA, state(tmp_path, builder), Ledger(tmp_path / 'ledger.sqlite'))
    assert receipt.status != 'done' and receipt.evidence.get('status') != 'PASS'
    assert not any(a == 'build.export' and q['image'] == 'caddy' for a, q in builder.calls)
    export, load = [q for a, q in builder.calls if a in ('build.export', 'build.load')]
    assert load['deadline'] == export['deadline']
    assert receipt.evidence['reason'] == 'load_unconfirmed'


def test_cleanup_preserves_sole_stable_and_recent_two_sets(tmp_path):
    builder = Builder()
    lab = state(tmp_path, builder)
    lab['verified_image_sets'] = [
        {'verified': True, 'image_ids': ['old']},
        {'verified': True, 'image_ids': ['recent1']},
        {'verified': False, 'image_ids': ['unverified']},
        {'verified': True, 'image_ids': ['recent2']}]
    receipt = build_images(SHA, lab, Ledger(tmp_path / 'ledger.sqlite'))
    assert receipt.status == 'done'
    cleanup = builder.calls[-1][1]
    assert set(cleanup['protected_image_ids']) == {API, 'recent1', 'recent2'}
    assert cleanup['delete_image_ids'] == []


def test_resource_claim_without_process_sandbox_blocks(tmp_path):
    builder = Builder()
    def run(action, request):
        receipt = builder(action, request)
        if action == 'build.prepare':
            receipt.evidence['process_sandbox'] = False
        return receipt
    receipt = build_images(SHA, state(tmp_path, run), Ledger(tmp_path / 'ledger.sqlite'))
    assert receipt.status == 'blocked'
    assert not any(a == 'build.export' for a, q in builder.calls)
@pytest.mark.parametrize('fault', ['driver', 'image', 'limits', 'identity', 'load_id', 'load_revision', 'daemon_metrics'])
def test_build_requires_exact_runtime_and_loaded_identity(tmp_path, fault):
    builder = Builder()
    def run(action, request):
        receipt = builder(action, request)
        if action == 'build.prepare':
            if fault == 'driver': receipt.evidence['builder_driver'] = 'docker-container'
            if fault == 'image': receipt.evidence['builder_image'] = 'moby/buildkit:rootless'
            if fault == 'limits': receipt.evidence['memory_plus_swap_bytes'] = 0
            if fault == 'identity': receipt.evidence['source_hash'] = 'c' * 64
        if action == 'build.load':
            if fault == 'load_id': receipt.evidence['image_id'] = CADDY
            if fault == 'load_revision': receipt.evidence['revision'] = 'c' * 40
            if fault == 'daemon_metrics': receipt.evidence['daemon_overhead_measured'] = False
        return receipt
    receipt = build_images(SHA, state(tmp_path, run), Ledger(tmp_path / 'ledger.sqlite'))
    assert receipt.status != 'done'
    assert not any(a == 'build.export' and q['image'] == 'caddy' for a, q in builder.calls)


def test_nonreceipt_cleanup_fails_closed(tmp_path):
    builder = Builder()
    def run(action, request):
        return None if action == 'build.cleanup' else builder(action, request)
    receipt = build_images(SHA, state(tmp_path, run), Ledger(tmp_path / 'ledger.sqlite'))
    assert receipt.status == 'uncertain' and receipt.evidence['reason'] == 'cleanup_unconfirmed'