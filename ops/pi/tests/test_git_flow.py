"""Real local Git exercises: dropping frozen identities must break these gates."""
import importlib
from pathlib import Path
import subprocess

import pytest

from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger
from ops.pi.tests.test_budget import policy
from ops.pi.tests.test_plans import candidate


def test_control_exposes_trusted_git_boundary():
    from ops.pi import control
    assert callable(getattr(control, 'make_git_flow', None)), 'host controller must expose trusted Git setup'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, encoding='utf-8', timeout=120).strip()


def commit(repo, text='new', path='app/worker.py'):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')
    git(repo, 'add', '--', path)
    git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'change')
    return git(repo, 'rev-parse', 'HEAD')


def test_trusted_git_flow_capability_available():
    spec = importlib.util.find_spec('ops.pi.git_flow')
    assert spec is not None, 'trusted Git candidate flow capability must be available'


@pytest.fixture
def lab(tmp_path, policy):
    module = importlib.import_module('ops.pi.git_flow')
    source = tmp_path / '源 repo with spaces'
    source.mkdir()
    git(source, 'init', '-b', 'main')
    base = commit(source, 'old')
    remote = tmp_path / 'remote 仓库.git'
    subprocess.check_call(['git', 'init', '--bare', str(remote)], stdout=subprocess.DEVNULL)
    git(source, 'push', str(remote), 'HEAD:refs/heads/main')
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    flow = module.GitFlow(ledger, module.GitConfig(tmp_path / 'candidates', {'lab': remote}, ('unit',)), candidate(), policy)
    prepared = flow.prepare_slice(source, 'experiment', 'slice-1', base)
    repo = Path(prepared['repo'])
    head = commit(repo)
    return flow, ledger, source, repo, remote, prepared, base, head


def ready(lab, result='passed'):
    flow, _, _, repo, _, prepared, base, head = lab
    check = flow.record_check(repo, prepared['branch'], 'unit', result, expected_head=head, expected_base=base)
    return flow.freeze_candidate(repo, prepared['branch'], [check])


def test_wip_push_does_not_change_ready_slice(lab):
    flow, _, _, repo, remote, prepared, _, head = lab
    frozen = ready(lab)
    assert frozen['status'] == 'ready'
    receipt = flow.push_candidate(repo, frozen, 'lab')
    assert receipt.status == 'done'
    frozen_ready_ref = git(remote, 'rev-parse', 'refs/heads/' + prepared['branch'])
    git(repo, 'checkout', prepared['wip_branch'])
    wip = commit(repo, 'wip')
    assert flow.push_wip(repo, prepared, 'lab', expected_head=wip).status == 'done'
    assert git(remote, 'rev-parse', 'refs/heads/' + prepared['branch']) == frozen_ready_ref == head


def test_new_main_invalidates_checks(lab):
    flow, _, source, repo, remote, _, _, _ = lab
    frozen = ready(lab)
    human = commit(source, 'human')
    git(source, 'push', str(remote), 'HEAD:refs/heads/main')
    receipt = flow.merge_candidate(repo, frozen, 'lab')
    assert receipt.status == 'blocked'
    assert git(remote, 'rev-parse', 'refs/heads/main') == human
    assert flow.candidate_state(repo, frozen)['status'] == 'invalidated'


def test_new_candidate_commit_unfreezes(lab):
    flow, _, _, repo, remote, _, base, _ = lab
    frozen = ready(lab)
    commit(repo, 'changed again')
    assert flow.candidate_state(repo, frozen)['status'] == 'draft'
    assert flow.merge_candidate(repo, frozen, 'lab').status == 'blocked'
    assert git(remote, 'rev-parse', 'refs/heads/main') == base


def test_skipped_check_blocks_merge(lab):
    flow, _, _, repo, remote, _, base, _ = lab
    frozen = ready(lab, 'skipped')
    assert frozen['status'] == 'draft'
    assert flow.merge_candidate(repo, frozen, 'lab').status == 'blocked'
    assert git(remote, 'rev-parse', 'refs/heads/main') == base


def test_unrelated_local_changes_untouched(lab):
    flow, _, source, repo, remote, prepared, _, head = lab
    dirty = source / 'app/worker.py'
    dirty.write_text('human unsaved', encoding='utf-8')
    (source / 'untracked.txt').write_text('keep')
    before = git(source, 'status', '--porcelain')
    original = git(source, 'rev-parse', 'HEAD')
    frozen = ready(lab)
    assert flow.merge_candidate(repo, frozen, 'lab').status == 'done'
    assert git(remote, 'rev-parse', 'refs/heads/main') == head
    assert git(source, 'status', '--porcelain') == before
    assert git(source, 'rev-parse', 'HEAD') == original
    assert dirty.read_text() == 'human unsaved'
    assert prepared['branch'] == 'codex/pi/experiment/slice-1'
    assert prepared['wip_branch'] == 'codex/pi/experiment/wip'


def test_remote_success_without_receipt_reconciles(lab, monkeypatch):
    flow, ledger, _, repo, remote, _, _, head = lab
    frozen = ready(lab)
    original = ledger.finish
    def disconnect(receipt):
        if receipt.operation_id.startswith('git_push:'):
            raise ConnectionError('lost receipt')
        return original(receipt)
    monkeypatch.setattr(ledger, 'finish', disconnect)
    with pytest.raises(ConnectionError):
        flow.push_candidate(repo, frozen, 'lab')
    assert git(remote, 'rev-parse', 'refs/heads/' + frozen['branch']) == head
    monkeypatch.setattr(ledger, 'finish', original)
    recovered = flow.push_candidate(repo, frozen, 'lab')
    assert recovered.status == 'done'
    assert recovered.evidence['reconciled'] is True


def test_merge_is_not_deployment_and_revert_uses_new_branch(lab):
    flow, _, _, repo, remote, _, base, head = lab
    frozen = ready(lab)
    receipt = flow.merge_candidate(repo, frozen, 'lab')
    assert receipt.status == 'done'
    assert receipt.evidence['head'] == head
    assert 'deployment_id' not in receipt.evidence
    revert = flow.prepare_revert(repo, frozen, expected_head=head)
    assert revert['branch'].startswith('codex/pi/revert/')
    assert git(Path(revert['repo']), 'show', 'HEAD:app/worker.py') == 'old'
    assert git(remote, 'rev-parse', 'refs/heads/main') == head


def test_forged_ci_and_candidate_do_not_authorize_merge(lab):
    flow, _, _, repo, _, prepared, base, head = lab
    fake = Receipt('untrusted', 'done', dict(name='unit', result='passed', head=head, base=base))
    frozen = flow.freeze_candidate(repo, prepared['branch'], [fake])
    assert frozen['status'] == 'draft'
    frozen['status'] = 'ready'
    assert flow.merge_candidate(repo, frozen, 'lab').status == 'blocked'


def test_protected_or_undeclared_diff_blocks(lab):
    flow, _, _, repo, _, prepared, base, _ = lab
    head = commit(repo, 'quota override', 'ops/pi/policy.json')
    check = flow.record_check(repo, prepared['branch'], 'unit', 'passed', expected_head=head, expected_base=base)
    assert check.status == 'done'
    assert flow.freeze_candidate(repo, prepared['branch'], [check])['status'] == 'draft'


def test_unapproved_remote_is_rejected(lab):
    flow, _, _, repo, _, _, _, _ = lab
    with pytest.raises(ValueError, match='remote'):
        flow.merge_candidate(repo, ready(lab), 'origin')


def test_new_required_context_invalidates_frozen_candidate(lab):
    flow, ledger, _, repo, remote, _, base, _ = lab
    frozen = ready(lab)
    module = importlib.import_module('ops.pi.git_flow')
    changed = module.GitFlow(ledger, module.GitConfig(flow.root, {'lab': remote}, ('unit', 'integration')), flow.plan, flow.policy)
    assert changed.merge_candidate(repo, frozen, 'lab').status == 'blocked'
    assert git(remote, 'rev-parse', 'refs/heads/main') == base


def test_merge_success_without_receipt_reconciles(lab, monkeypatch):
    flow, ledger, _, repo, remote, _, _, head = lab
    frozen = ready(lab)
    original = ledger.finish
    def disconnect(receipt):
        if receipt.operation_id.startswith('git_merge:'):
            raise ConnectionError('lost merge receipt')
        return original(receipt)
    monkeypatch.setattr(ledger, 'finish', disconnect)
    with pytest.raises(ConnectionError):
        flow.merge_candidate(repo, frozen, 'lab')
    assert git(remote, 'rev-parse', 'refs/heads/main') == head
    monkeypatch.setattr(ledger, 'finish', original)
    receipt = flow.merge_candidate(repo, frozen, 'lab')
    assert receipt.status == 'done' and receipt.evidence['reconciled'] is True


def test_prepare_excludes_private_dirty_and_ignored_files(lab):
    flow, _, source, _, _, _, base, _ = lab
    (source / '.gitignore').write_text('private/\n')
    (source / 'private').mkdir()
    (source / 'private/key.txt').write_text('private fixture')
    (source / 'untracked.txt').write_text('keep')
    (source / 'app/worker.py').write_text('uncommitted')
    before = git(source, 'status', '--porcelain')
    second = flow.prepare_slice(source, 'second', 'slice-1', base)
    clone = Path(second['repo'])
    assert not (clone / 'private').exists()
    assert not (clone / 'untracked.txt').exists()
    assert (clone / 'app/worker.py').read_text() == 'old'
    assert git(source, 'status', '--porcelain') == before


def test_required_check_missing_and_failed_are_not_ready(lab):
    flow, _, _, repo, _, prepared, base, head = lab
    assert flow.freeze_candidate(repo, prepared['branch'], [])['status'] == 'draft'
    failed = flow.record_check(repo, prepared['branch'], 'unit', 'failed', expected_head=head, expected_base=base)
    assert flow.freeze_candidate(repo, prepared['branch'], [failed])['status'] == 'draft'


def test_pr_success_without_receipt_reuses_identity(lab, monkeypatch):
    flow, ledger, _, repo, _, _, _, _ = lab
    original = ledger.finish
    def disconnect(receipt):
        if receipt.operation_id.startswith('git_pr:'):
            raise ConnectionError('lost PR receipt')
        return original(receipt)
    monkeypatch.setattr(ledger, 'finish', disconnect)
    with pytest.raises(ConnectionError):
        ready(lab)
    with ledger.transaction() as connection:
        pending = connection.execute("SELECT operation_id FROM operations WHERE kind='git_pr'").fetchall()
    monkeypatch.setattr(ledger, 'finish', original)
    frozen = ready(lab)
    assert len(pending) == 1 and frozen['pr_id'] == pending[0][0]
    assert flow.candidate_state(repo, frozen)['status'] == 'ready'


@pytest.mark.parametrize('experiment,slice_id', [('bad;command', 'slice-1'), ('experiment', 'wip'), ('experiment', '../main')])
def test_invalid_or_reserved_branch_identity_rejected(lab, experiment, slice_id):
    flow, _, source, _, _, _, base, _ = lab
    before = git(source, 'for-each-ref', '--format=%(refname) %(objectname)')
    with pytest.raises(ValueError):
        flow.prepare_slice(source, experiment, slice_id, base)
    assert git(source, 'for-each-ref', '--format=%(refname) %(objectname)') == before


def test_controller_rejects_workspace_outside_lab(lab):
    from ops.pi.control import make_git_flow
    from ops.pi.git_flow import GitConfig
    from ops.pi.ledger import LedgerBlocked
    flow, ledger, _, _, remote, _, _, _ = lab
    with pytest.raises(LedgerBlocked):
        make_git_flow(ledger, GitConfig(Path('relative-workspace'), {'lab': remote}, ('unit',)), flow.plan, flow.policy)
