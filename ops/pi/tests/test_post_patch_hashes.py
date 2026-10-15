"""Offline post-patch receipts; real temporary candidates and durable ledgers only."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json

import pytest

from ops.pi.ledger import Ledger
from ops.pi.tests.test_budget import policy
from ops.pi.tests.test_plans import candidate
from ops.pi.tests.test_tools import approve, call, setup


def test_receipt_hash_drives_next_patch_without_source_reread(tmp_path, policy):
    broker, cap, root, _ = setup(tmp_path, policy)
    approve(broker, cap)
    initial = call(broker, cap, 'read_source', dict(path='app/worker.py', start_line=1, end_line=1), 'read')
    args = dict(plan_hash=cap.plan.plan_hash, base=cap.base, candidate_hash=broker.candidate_hash(),
        edits=[dict(path='app/worker.py', source_hash=initial.evidence['source_hash'], old='value = 1', new='value = 2')])
    first = call(broker, cap, 'apply_patch', args, 'first')
    assert first.status == 'done'
    assert 'source_hashes' in first.evidence, 'successful patch must supply next-edit source hashes'
    assert (root/'app/worker.py').read_bytes() == b'value = 2\n'
    assert first.evidence['source_hashes'] == {'app/worker.py':hashlib.sha256(b'value = 2\n').hexdigest()}
    second_args = dict(plan_hash=cap.plan.plan_hash, base=cap.base, candidate_hash=first.evidence['candidate_hash'],
        edits=[dict(path='app/worker.py', source_hash=first.evidence['source_hashes']['app/worker.py'],
                    old='value = 2', new='value = 3')])
    second = call(broker, cap, 'apply_patch', second_args, 'second')
    assert second.status == 'done'
    assert (root/'app/worker.py').read_bytes() == b'value = 3\n'
    assert second.evidence['source_hashes'] == {'app/worker.py':hashlib.sha256(b'value = 3\n').hexdigest()}
    snapshot = {'app/worker.py':hashlib.sha256(b'value = 3\n').hexdigest(),
                'app/other.py':hashlib.sha256(b'other = 1\n').hexdigest()}
    expected_candidate = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert second.evidence['candidate_hash'] == expected_candidate == broker.candidate_hash()
    assert broker.lookup('second', 'apply_patch', second_args, asdict(second))
    status = call(broker, cap, 'candidate_status', call_id='status')
    assert [r['tool'] for r in status.evidence['receipts']].count('read_source') == 1


def test_hashes_cover_only_this_calls_edits_while_files_stay_cumulative(tmp_path, policy):
    plan = candidate(files=('app/worker.py', 'app/other.py'))
    broker, cap, root, _ = setup(tmp_path, policy, plan=plan)
    approve(broker, cap)
    args = dict(plan_hash=plan.plan_hash, base=cap.base, candidate_hash=broker.candidate_hash(), edits=[
        dict(path='app/worker.py', source_hash=hashlib.sha256(b'value = 1\n').hexdigest(), old='value = 1', new='value = 2'),
        dict(path='app/other.py', source_hash=hashlib.sha256(b'other = 1\n').hexdigest(), old='other = 1', new='other = 2')])
    first = call(broker, cap, 'apply_patch', args, 'multi')
    assert first.status == 'done'
    assert 'source_hashes' in first.evidence, 'multi-file patch must supply bounded source hashes'
    expected = {'app/worker.py':hashlib.sha256(b'value = 2\n').hexdigest(),
                'app/other.py':hashlib.sha256(b'other = 2\n').hexdigest()}
    assert first.evidence['source_hashes'] == expected
    for path in plan.files:
        assert hashlib.sha256((root/path).read_bytes()).hexdigest() == expected[path]
    args['candidate_hash'] = first.evidence['candidate_hash']
    args['edits'] = [dict(path='app/worker.py', source_hash=expected['app/worker.py'], old='value = 2', new='value = 3')]
    second = call(broker, cap, 'apply_patch', args, 'single')
    assert second.status == 'done'
    assert second.evidence['source_hashes'] == {'app/worker.py':hashlib.sha256(b'value = 3\n').hexdigest()}
    assert set(second.evidence['files']) == set(plan.files)
    assert set(second.evidence) == {'tool', 'input_hash', 'binding', 'candidate_hash', 'files', 'scope', 'source_hashes'}


@pytest.mark.parametrize('fault', ['source_hash', 'candidate_hash', 'generation', 'unapproved', 'too_many_edits'])
def test_denied_patch_has_no_postwrite_hash_metadata_or_file_side_effect(tmp_path, policy, fault):
    broker, cap, root, identity = setup(tmp_path, policy)
    if fault != 'unapproved':
        approve(broker, cap)
    args = dict(plan_hash=cap.plan.plan_hash, base=cap.base, candidate_hash=broker.candidate_hash(),
        edits=[dict(path='app/worker.py', source_hash=hashlib.sha256(b'value = 1\n').hexdigest(), old='value = 1', new='value = 2')])
    if fault == 'source_hash':
        args['edits'][0]['source_hash'] = '0'*64
    elif fault == 'candidate_hash':
        args['candidate_hash'] = '0'*64
    elif fault == 'generation':
        identity['generation'] = 2
    elif fault == 'too_many_edits':
        args['edits'] *= policy.hard_tracked_files + 1
    result = call(broker, cap, 'apply_patch', args)
    assert result.status == 'blocked'
    assert 'source_hashes' not in result.evidence and 'candidate_hash' not in result.evidence
    assert (root/'app/worker.py').read_bytes() == b'value = 1\n'
    assert (root/'app/other.py').read_bytes() == b'other = 1\n'
    assert not list(root.rglob('.controlled-*'))


def test_replay_keeps_original_postwrite_hash_after_later_patch(tmp_path, policy):
    broker, cap, root, _ = setup(tmp_path, policy)
    approve(broker, cap)
    args = dict(plan_hash=cap.plan.plan_hash, base=cap.base, candidate_hash=broker.candidate_hash(),
        edits=[dict(path='app/worker.py', source_hash=hashlib.sha256(b'value = 1\n').hexdigest(), old='value = 1', new='value = 2')])
    first = call(broker, cap, 'apply_patch', args, 'first')
    assert first.status == 'done'
    assert 'source_hashes' in first.evidence, 'replay must persist the original postwrite hashes'
    next_args = deepcopy(args)
    next_args['candidate_hash'] = first.evidence['candidate_hash']
    next_args['edits'][0].update(source_hash=first.evidence['source_hashes']['app/worker.py'], old='value = 2', new='value = 3')
    assert call(broker, cap, 'apply_patch', next_args, 'later').status == 'done'
    replay = call(broker, cap, 'apply_patch', args, 'first')
    assert replay == first
    assert replay.evidence['source_hashes'] == {'app/worker.py':hashlib.sha256(b'value = 2\n').hexdigest()}
    assert (root/'app/worker.py').read_bytes() == b'value = 3\n'
    row = Ledger(broker.ledger.path).get(first.operation_id)
    assert row['status'] == 'done' and row['evidence'] == first.evidence
    collision = deepcopy(args)
    collision['edits'][0]['new'] = 'value = 4'
    denied = call(broker, cap, 'apply_patch', collision, 'first')
    assert denied.status == 'blocked' and 'source_hashes' not in denied.evidence
    assert (root/'app/worker.py').read_bytes() == b'value = 3\n'
