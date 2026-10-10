"""Trusted host-only Git executor. Local bare PR/CI simulation, never deployment."""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess

from .contracts import Receipt, Record
from .plans import Plan, check_diff


def _identity(kind, payload):
    return kind + ':' + sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise ValueError('full expected SHA required')
    return value


@dataclass(frozen=True)
class GitConfig:
    """Supplied by the trusted host, separate from strict model policy JSON."""
    workspace_root: Path
    remotes: dict[str, Path]
    required_checks: tuple[str, ...]


class GitFlow:
    def __init__(self, ledger, config: GitConfig, plan: Plan, policy):
        self.ledger, self.plan, self.policy = ledger, plan, policy
        self.root = Path(config.workspace_root).resolve()
        self.remotes = {name: Path(path).resolve() for name, path in config.remotes.items()}
        self.required_checks = tuple(config.required_checks)
        if (not self.remotes or not self.required_checks or len(set(self.required_checks)) != len(self.required_checks)
                or any(not isinstance(name, str) or not name.strip() for name in self.required_checks)):
            raise ValueError('explicit remotes and required checks required')
        self.root.mkdir(parents=True, exist_ok=True)
        self.hooks = self.root / 'disabled-hooks'
        self.hooks.mkdir(exist_ok=True)
        for path in self.remotes.values():
            if self._git(path, 'rev-parse', '--is-bare-repository') != 'true':
                raise ValueError('only local bare remotes enabled')

    def _git(self, repo, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        env.update(GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        command = ['git', '-c', 'core.hooksPath=' + str(self.hooks), '-c', 'protocol.allow=never',
                   '-c', 'protocol.file.allow=always', '-c', 'credential.helper=',
                   '-c', 'core.quotePath=false', '-c', 'uploadpack.packObjectsHook=',
                   '-C', str(repo), *map(str, args)]
        result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8',
                                timeout=120, check=True)
        return result.stdout.strip()

    def _remote(self, name):
        if name not in self.remotes:
            raise ValueError('remote not allowed')
        return self.remotes[name]

    def _repo(self, repo):
        repo = Path(repo).resolve()
        if repo == self.root or self.root not in repo.parents:
            raise ValueError('candidate repo outside trusted workspace')
        return repo

    def _slice(self, repo, branch):
        key = _identity('git_slice', dict(repo=str(self._repo(repo)), branch=branch))
        record = self.ledger.get(key)
        if record is None or record['status'] != 'done':
            raise ValueError('prepared slice required')
        return record['evidence']

    def _finish(self, operation_id, status, evidence):
        receipt = Receipt(operation_id, status, evidence)
        self.ledger.finish(receipt)
        return receipt

    @staticmethod
    def _receipt(record):
        return Receipt(record['operation_id'], record['status'], record['evidence'])

    def prepare_slice(self, repo: Path, experiment_id: str, slice_id: str, base_sha: str) -> Record:
        _sha(base_sha)
        for value in (experiment_id, slice_id):
            if not isinstance(value, str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', value):
                raise ValueError('safe experiment and slice identities required')
        if slice_id == 'wip' or slice_id not in self.plan.slice_ids:
            raise ValueError('slice outside trusted plan')
        source = Path(repo).resolve()
        branch, wip = f'codex/pi/{experiment_id}/{slice_id}', f'codex/pi/{experiment_id}/wip'
        destination = self.root / _identity('slice', dict(source=str(source), branch=branch)).split(':')[1]
        payload = dict(repo=str(destination), source=str(source), branch=branch, wip_branch=wip,
                       expected_base=base_sha, plan_hash=self.plan.plan_hash)
        operation_id = _identity('git_slice', dict(repo=str(destination), branch=branch))
        intent = self.ledger.intent(operation_id, 'git_prepare', payload)
        if intent['status'] != 'pending':
            return intent['evidence']
        if self._git(source, 'rev-parse', base_sha + '^{commit}') != base_sha:
            raise ValueError('base commit missing')
        if not destination.exists():
            self._git(self.root, 'clone', '--no-local', '--no-checkout', '--', source, destination)
        # Origin refers to source only during object copy; never use repository config as remote authority.
        if self._git(destination, 'remote'):
            self._git(destination, 'remote', 'remove', 'origin')
        refs = self._git(destination, 'for-each-ref', '--format=%(refname)', 'refs/heads/')
        if 'refs/heads/' + branch not in refs.splitlines():
            self._git(destination, 'branch', wip, base_sha)
            self._git(destination, 'checkout', '-b', branch, base_sha)
        elif self._git(destination, 'rev-parse', 'refs/heads/' + branch) != base_sha:
            raise ValueError('pending preparation needs reconciliation')
        result = dict(payload, status='draft', operation_id=operation_id)
        self._finish(operation_id, 'done', result)
        return result

    def record_check(self, repo, branch, name, result, *, expected_head, expected_base) -> Receipt:
        """Only trusted local CI adapter calls this; model/tool HTTP routes cannot."""
        prepared = self._slice(repo, branch)
        _sha(expected_head); _sha(expected_base)
        if name not in self.required_checks or result not in ('passed', 'failed', 'skipped'):
            raise ValueError('invalid CI context or result')
        payload = dict(repo=str(self._repo(repo)), branch=branch, name=name, result=result,
                       head=expected_head, base=expected_base, plan_hash=self.plan.plan_hash)
        operation_id = _identity('git_ci', payload)
        intent = self.ledger.intent(operation_id, 'git_ci', payload)
        if intent['status'] != 'pending':
            return self._receipt(intent)
        valid = (self._git(repo, 'rev-parse', 'refs/heads/' + branch) == expected_head
                 and prepared['expected_base'] == expected_base and result == 'passed')
        return self._finish(operation_id, 'done' if valid else 'blocked', payload)

    def _diff_gate(self, repo, head, base):
        # Numstat -z handles spaces, tabs, Unicode, renames, and binary content without shell quoting.
        raw = self._git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--numstat', '-z', base, head, '--')
        files, added, deleted = [], 0, 0
        for row in raw.split('\0'):
            if not row:
                continue
            plus, minus, path = row.split('\t', 2)
            if not plus.isdigit() or not minus.isdigit():
                return False
            files.append(path)
            # Counting all files is conservative; never hides production changes as tests.
            added += int(plus); deleted += int(minus)
        return check_diff(self.plan, dict(plan_hash=self.plan.plan_hash, files=files,
                          tracked_files=len(files), production_added=added, production_deleted=deleted), self.policy).status == 'done'

    def freeze_candidate(self, repo: Path, branch: str, check_receipts: list[Receipt]) -> Record:
        repo = self._repo(repo)
        prepared = self._slice(repo, branch)
        head, base = self._git(repo, 'rev-parse', 'refs/heads/' + branch), prepared['expected_base']
        checks, valid = {}, True
        for receipt in check_receipts:
            record = self.ledger.get(receipt.operation_id)
            if (record is None or record['kind'] != 'git_ci' or record['status'] != 'done'
                    or receipt != self._receipt(record)):
                valid = False
                continue
            evidence = record['evidence']
            name = evidence.get('name')
            if (name in checks or evidence.get('repo') != str(repo) or evidence.get('branch') != branch
                    or evidence.get('head') != head or evidence.get('base') != base
                    or evidence.get('plan_hash') != self.plan.plan_hash or evidence.get('result') != 'passed'):
                valid = False
            checks[name] = receipt.operation_id
        valid = (valid and set(checks) == set(self.required_checks) and self._diff_gate(repo, head, base)
                 and not self._git(repo, 'status', '--porcelain')
                 and prepared['plan_hash'] == self.plan.plan_hash)
        payload = dict(repo=str(repo), branch=branch, expected_head=head, expected_base=base,
                       plan_hash=self.plan.plan_hash, checks=checks, status='ready' if valid else 'draft',
                       adapter='local_mock_pr')
        operation_id = _identity('git_pr', payload)
        intent = self.ledger.intent(operation_id, 'git_pr', payload)
        candidate = dict(payload, operation_id=operation_id, pr_id=operation_id)
        if intent['status'] == 'pending':
            self._finish(operation_id, 'done', candidate)
        return candidate

    def candidate_state(self, repo, candidate) -> Record:
        repo = self._repo(repo)
        stored = self.ledger.get(candidate.get('operation_id', ''))
        if (stored is None or stored['kind'] != 'git_pr' or stored['status'] != 'done'
                or stored['evidence'] != candidate or candidate.get('repo') != str(repo)):
            return dict(status='draft', reason='untrusted_candidate')
        if self._git(repo, 'rev-parse', 'refs/heads/' + candidate['branch']) != candidate['expected_head']:
            return dict(status='draft', reason='head_changed')
        with self.ledger.transaction() as connection:
            invalidated = connection.execute("SELECT 1 FROM events WHERE kind='git_invalidation' AND payload=?",
                                            (json.dumps(dict(pr_id=candidate['pr_id']), sort_keys=True, separators=(',', ':')),)).fetchone()
        if invalidated:
            return dict(status='invalidated', reason='base_changed')
        if (set(candidate['checks']) != set(self.required_checks)
                or candidate['plan_hash'] != self.plan.plan_hash or not self._diff_gate(repo, candidate['expected_head'], candidate['expected_base'])
                or self._git(repo, 'status', '--porcelain')):
            return dict(status='draft', reason='scope_or_workspace_changed')
        return dict(status=candidate['status'])

    def _push(self, repo, branch, head, base, remote, *, kind):
        destination = self._remote(remote)
        payload = dict(repo=str(self._repo(repo)), branch=branch, expected_head=_sha(head), expected_base=_sha(base),
                       remote=str(destination))
        operation_id = _identity(kind, payload)
        intent = self.ledger.intent(operation_id, kind, payload)
        if intent['status'] != 'pending':
            return self._receipt(intent)
        ref = 'refs/heads/' + branch
        existing = self._git(destination, 'for-each-ref', '--format=%(objectname)', ref)
        if existing == head:
            return self._finish(operation_id, 'done', dict(payload, reconciled=True))
        if self._git(repo, 'rev-parse', ref) != head:
            return self._finish(operation_id, 'blocked', dict(payload, reason='head_changed'))
        try:
            self._git(repo, 'push', '--', destination, head + ':' + ref)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            # Keep durable pending intent: next call inspects ref rather than blindly retrying.
            raise
        return self._finish(operation_id, 'done', dict(payload, reconciled=False))

    def push_candidate(self, repo, candidate, remote) -> Receipt:
        self._remote(remote)
        if self.candidate_state(repo, candidate)['status'] != 'ready':
            raise ValueError('ready frozen candidate required')
        return self._push(repo, candidate['branch'], candidate['expected_head'], candidate['expected_base'], remote, kind='git_push')

    def push_wip(self, repo, prepared, remote, *, expected_head) -> Receipt:
        trusted = self._slice(repo, prepared['branch'])
        if trusted != prepared:
            raise ValueError('trusted preparation required')
        return self._push(repo, prepared['wip_branch'], expected_head, prepared['expected_base'], remote, kind='git_wip_push')

    def merge_candidate(self, repo: Path, candidate: Record, remote: str) -> Receipt:
        destination = self._remote(remote)
        payload = dict(repo=str(self._repo(repo)), candidate=candidate, remote=str(destination))
        operation_id = _identity('git_merge', payload)
        intent = self.ledger.intent(operation_id, 'git_merge', payload)
        if intent['status'] != 'pending':
            return self._receipt(intent)
        stored = self.ledger.get(candidate.get('operation_id', ''))
        if stored is None or stored['evidence'] != candidate or candidate.get('status') != 'ready':
            return self._finish(operation_id, 'blocked', dict(reason='untrusted_or_draft_candidate'))
        head, base = candidate['expected_head'], candidate['expected_base']
        current = self._git(destination, 'rev-parse', 'refs/heads/main')
        # Recover only our own already-authorized remote merge, never infer a deployment.
        push = self.ledger.get(_identity('git_push', dict(repo=str(self._repo(repo)), branch=candidate['branch'],
                       expected_head=head, expected_base=base, remote=str(destination))))
        if current == head and push is not None and push['status'] == 'done':
            return self._finish(operation_id, 'done', dict(head=head, base=base, reconciled=True, adapter='local_mock_merge'))
        if current != base:
            self.ledger.append_event('git_invalidation', dict(pr_id=candidate['pr_id']))
            return self._finish(operation_id, 'blocked', dict(reason='base_changed', observed_base=current, head=head, base=base))
        if self.candidate_state(repo, candidate)['status'] != 'ready':
            return self._finish(operation_id, 'blocked', dict(reason='candidate_changed', head=head, base=base))
        self.push_candidate(repo, candidate, remote)
        try:
            # Local mock PR merge uses an atomic expected-old ref update. No force push or history overwrite.
            self._git(destination, 'merge-base', '--is-ancestor', base, head)
            self._git(destination, 'update-ref', 'refs/heads/main', head, base)
        except subprocess.CalledProcessError:
            self.ledger.append_event('git_invalidation', dict(pr_id=candidate['pr_id']))
            return self._finish(operation_id, 'blocked', dict(reason='base_conflict', head=head, base=base))
        return self._finish(operation_id, 'done', dict(head=head, base=base, reconciled=False, adapter='local_mock_merge'))

    def prepare_revert(self, repo, candidate, *, expected_head) -> Record:
        repo = self._repo(repo)
        _sha(expected_head)
        stored = self.ledger.get(candidate.get('operation_id', ''))
        if stored is None or stored['evidence'] != candidate or expected_head != candidate['expected_head']:
            raise ValueError('trusted exact candidate required')
        branch = 'codex/pi/revert/' + expected_head[:12]
        destination = self.root / ('revert-' + expected_head)
        payload = dict(source=str(repo), repo=str(destination), branch=branch, expected_head=expected_head,
                       expected_base=candidate['expected_base'])
        operation_id = _identity('git_revert', payload)
        intent = self.ledger.intent(operation_id, 'git_revert', payload)
        if intent['status'] != 'pending':
            return intent['evidence']
        if destination.exists():
            raise ValueError('pending revert requires manual reconciliation')
        self._git(self.root, 'clone', '--no-local', '--no-checkout', '--', repo, destination)
        self._git(destination, 'remote', 'remove', 'origin')
        self._git(destination, 'checkout', '-b', branch, expected_head)
        self._git(destination, 'restore', '--source=' + candidate['expected_base'], '--staged', '--worktree', '--', '.')
        self._git(destination, '-c', 'user.name=Pi local executor', '-c', 'user.email=pi@example.invalid',
                  'commit', '-m', 'Revert frozen Pi candidate ' + expected_head)
        result = dict(payload, status='draft', revert_head=self._git(destination, 'rev-parse', 'HEAD'))
        self._finish(operation_id, 'done', result)
        return result
