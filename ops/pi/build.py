"""Trusted serial image export/load controller; daemon cost stays in host headroom."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from .contracts import Receipt

GIB = 1024**3
BUILD_LIMITS = {'memory_max_bytes': 1536 * 1024**2,
                'memory_plus_swap_bytes': 1792 * 1024**2,
                'cpu_max': '200000 100000', 'max_parallelism': 1}
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')


class HeavyAction:
    """One native heavy.lock shared with provision.sh; unknown work blocks reuse."""
    def __init__(self, path):
        self.path = Path(path)
        self.file = None
        self.marker = self.path.with_name(self.path.name + '.uncertain')

    def __enter__(self):
        if self.path.is_symlink() or self.marker.exists():
            raise ValueError('heavy ownership unresolved')
        self.file = self.path.open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0)
                if not self.file.read(1):
                    self.file.write(b'0')
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.marker.exists():
                raise ValueError('heavy ownership unresolved')
        except Exception:
            self.file.close()
            self.file = None
            raise
        return self

    def uncertain(self, operation, reason):
        with self.marker.open('x', encoding='utf-8') as output:
            json.dump({'operation_id': operation, 'reason': reason}, output)
            output.flush()
            os.fsync(output.fileno())

    def __exit__(self, *args):
        if self.file:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()


def admission(candidate_sha, lab):
    if (not isinstance(candidate_sha, str) or not re.fullmatch('[0-9a-f]{40}', candidate_sha)
            or candidate_sha != lab.get('candidate_sha')
            or not re.fullmatch('[0-9a-f]{64}', lab.get('source_hash', ''))):
        raise ValueError('candidate_source_mismatch')
    deadline = lab.get('deadline')
    if not isinstance(deadline, datetime) or deadline.tzinfo is None or deadline <= datetime.now(timezone.utc):
        raise ValueError('deadline_expired')
    peak = lab.get('planned_peak_bytes')
    if type(peak) is not int or peak < 0:
        raise ValueError('disk_estimate_missing')
    if any(type(lab.get(k)) is not int or lab[k] < peak + 5 * GIB
           for k in ('host_free_bytes', 'guest_free_bytes')):
        raise ValueError('disk_new_peak_plus_five_gib_required')
    root = Path(lab['artifact_dir'])
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError('owned_artifact_directory_required')
    return root


def outcome(operation, status, reason, candidate_sha, lab, **evidence):
    return Receipt(operation, status, {'status': {'done': 'PASS', 'failed': 'FAIL',
        'blocked': 'BLOCKED', 'uncertain': 'BLOCKED'}[status], 'reason': reason,
        'candidate_sha': candidate_sha, 'source_hash': lab.get('source_hash'), **evidence})


def bound(lab, seconds=2700):
    return min(lab['deadline'], datetime.now(timezone.utc) + timedelta(seconds=seconds))


def checked_call(executor, action, request):
    if datetime.now(timezone.utc) >= request['deadline']:
        raise TimeoutError('deadline_expired')
    receipt = executor(action, request)
    if not isinstance(receipt, Receipt):
        raise ValueError('canonical_receipt_missing')
    if datetime.now(timezone.utc) >= request['deadline']:
        raise TimeoutError('deadline_expired')
    return receipt


def same_source(receipt, candidate_sha, lab):
    return (receipt.evidence.get('candidate_sha') == candidate_sha
            and receipt.evidence.get('source_hash') == lab['source_hash'])


def _prepared(receipt, candidate_sha, lab):
    e = receipt.evidence
    return (receipt.status == 'done' and e.get('status') == 'PASS'
        and same_source(receipt, candidate_sha, lab)
        and all(e.get(k) is True for k in ('sandbox_verified', 'resource_limits_verified',
                                          'dependency_inventory_verified', 'process_sandbox'))
        and e.get('builder_driver') == 'remote'
        and re.fullmatch(r'moby/buildkit@sha256:[0-9a-f]{64}', e.get('builder_image', ''))
        and all(e.get(k) == v for k, v in BUILD_LIMITS.items()))


def build_images(candidate_sha, lab, ledger):
    """Only trusted executor actions: prepare, Python export/load, Caddy export/load, exit."""
    operation = str(uuid.uuid4())
    events, images = [], {}
    receipt = outcome(operation, 'blocked', 'build_facility_unavailable', candidate_sha, lab)
    prepared = False
    load_pending = False
    try:
        admission(candidate_sha, lab)
        if ledger is None or not callable(lab.get('executor')):
            raise ValueError('trusted_executor_required')
        executor = lab['executor']
        with HeavyAction(lab['lock_path']) as lease:
            protected = set(lab.get('protected_image_ids', []))
            if not protected:
                raise ValueError('stable_image_set_missing')
            verified = [s for s in lab.get('verified_image_sets', []) if s.get('verified') is True]
            for image_set in verified[-2:]:
                protected.update(image_set['image_ids'])
            common = {'operation_id': operation, 'candidate_sha': candidate_sha,
                      'source_hash': lab['source_hash'], 'deadline': lab['deadline']}
            ledger.append_event('b12_build_intent', {k: v for k, v in common.items() if k != 'deadline'})
            try:
                prepared = True  # Failed prepare may still own partial objects.
                preflight = checked_call(executor, 'build.prepare', {
                    **common, **BUILD_LIMITS, 'driver': 'remote', 'process_sandbox': True})
                events.append(asdict(preflight))
                if not _prepared(preflight, candidate_sha, lab):
                    receipt = outcome(operation, 'blocked', preflight.evidence.get('reason', 'build_sandbox_unverified'),
                                      candidate_sha, lab, actions=events)
                else:
                    for name, dockerfile in (('python', 'Dockerfile'), ('caddy', 'caddy/Dockerfile')):
                        image_deadline = bound(lab)
                        request = {**common, 'image': name, 'dockerfile': dockerfile,
                                   'deadline': image_deadline, 'network': 'none', 'push': False}
                        exported = checked_call(executor, 'build.export', request)
                        events.append(asdict(exported))
                        e = exported.evidence
                        if (exported.status != 'done' or not same_source(exported, candidate_sha, lab)
                                or e.get('returncode') != 0 or e.get('revision') != candidate_sha
                                or not DIGEST.fullmatch(e.get('image_id', ''))
                                or not DIGEST.fullmatch(e.get('digest', ''))
                                or not re.fullmatch('[0-9a-f]{64}', e.get('archive_hash', ''))
                                or not re.fullmatch('[0-9a-f]{64}', e.get('artifact_hash', ''))):
                            receipt = outcome(operation, 'failed', 'export_unverified', candidate_sha, lab, actions=events)
                            break
                        load_pending = True
                        loaded = checked_call(executor, 'build.load', {
                            **request, 'image_id': e['image_id'], 'archive_hash': e['archive_hash']})
                        events.append(asdict(loaded))
                        le = loaded.evidence
                        load_pending = not (le.get('owned_import_terminal') is True)
                        if (loaded.status != 'done' or not same_source(loaded, candidate_sha, lab)
                                or le.get('returncode') != 0 or le.get('image_id') != e['image_id']
                                or le.get('revision') != candidate_sha or le.get('archive_hash') != e['archive_hash']
                                or le.get('daemon_overhead_measured') is not True or load_pending):
                            receipt = outcome(operation, 'uncertain' if load_pending else 'failed',
                                              'load_unconfirmed', candidate_sha, lab, actions=events)
                            break
                        images[name] = {'image_id': e['image_id'], 'digest': e['digest'],
                                        'archive_hash': e['archive_hash'], 'revision': candidate_sha}
                    else:
                        receipt = outcome(operation, 'done', 'serial_images_verified', candidate_sha, lab,
                            images=images, api_image_id=images['python']['image_id'],
                            worker_image_ids=[images['python']['image_id']] * 2, actions=events)
            except (OSError, ValueError, RuntimeError, TimeoutError) as error:
                receipt = outcome(operation, 'uncertain' if load_pending else 'blocked',
                    'load_unconfirmed' if load_pending else str(error), candidate_sha, lab, actions=events)
            finally:
                if prepared:
                    try:
                        # No pruning: keep all failed artifacts and protect the sole stable + latest two verified sets.
                        cleanup = executor('build.cleanup', {**common, 'protected_image_ids': sorted(protected),
                            'delete_image_ids': [], 'load_pending': load_pending})
                        if isinstance(cleanup, Receipt):
                            events.append(asdict(cleanup))
                        if (not isinstance(cleanup, Receipt) or cleanup.status != 'done'
                                or cleanup.evidence.get('owned_exit_verified') is not True
                                or cleanup.evidence.get('protected_images_unchanged') is not True):
                            receipt = outcome(operation, 'uncertain', 'cleanup_unconfirmed', candidate_sha, lab, actions=events)
                    except (OSError, ValueError, RuntimeError, TimeoutError):
                        receipt = outcome(operation, 'uncertain', 'cleanup_unconfirmed', candidate_sha, lab, actions=events)
                if load_pending or receipt.status == 'uncertain':
                    lease.uncertain(operation, receipt.evidence['reason'])
                ledger.append_event('b12_build_receipt', asdict(receipt))
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        receipt = outcome(operation, 'blocked', str(error), candidate_sha, lab, actions=events)
    return receipt