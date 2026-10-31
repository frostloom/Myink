"""C18 offline fault matrix: real SQLite/files; every external adapter SIMULATED.

These tests do not qualify pi_lab, queue consumers, checkpoints or watchdogs.
Breaks caught: replaying pending writes, recovering a human-owned candidate,
refunding unknown usage, bypassing PRE/POST debt, and incorrect cutoff/opening selection.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib

import httpx
import pytest

from ops.pi import backup, iteration
from ops.pi.budget import totals
from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger
from ops.pi.schedule import next_action, window_at
from ops.pi.tests.test_backup import case, artifacts, backup as collect, qualified_restore, CONTEXT, NOW
from ops.pi.tests.test_budget import policy, request
from ops.pi.tests.test_model_gateway import transport
from ops.pi.model_gateway import forward_messages


def simulated_services(tmp_path):
    candidate = tmp_path / 'candidate.bin'
    recovery = tmp_path / 'recovered.bin'
    identity = dict(main='a'*40, source='b'*64, config='c'*64,
                    owner='pi', generation=1, deployment_id='simulated-1')
    effects = []
    def stage(context):
        effects.append(context['stage'])
        if context['stage'] == 'develop':
            candidate.write_bytes(b'SIMULATED candidate\x00\xe4\xb8\xad')
        if context['stage'] == 'recover':
            recovery.write_bytes(candidate.read_bytes() if candidate.exists() else b'no-candidate')
        return Receipt(context['operation_id'], 'done', dict(
            verified=True, mode='SIMULATED', binding=context['input_hash']))
    services = dict(mode='SIMULATED', identity=lambda: deepcopy(identity),
        run_id='fault-day', slice_id='fault-slice', hypothesis='byte fidelity',
        evidence_hash='e'*64, stages={s:stage for s in iteration.STAGES}, recover=stage)
    return services, identity, candidate, recovery, effects


@pytest.mark.parametrize('failed_stage', ['pre', 'post'])
def test_pre_and_post_failures_recover(tmp_path, failed_stage):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    services, _, candidate, recovered, effects = simulated_services(tmp_path)
    services['stages'][failed_stage] = lambda c: Receipt(c['operation_id'], 'failed', {'reason':'injected'})
    result = iteration.run_iteration(ledger, 'faults', NOW, services)
    assert result.status == 'failed' and result.evidence['released'] is False
    assert recovered.read_bytes() == (b'no-candidate' if failed_stage == 'pre' else b'SIMULATED candidate\x00\xe4\xb8\xad')
    assert candidate.exists() is (failed_stage == 'post')
    assert effects.count('recover') == 1
    assert iteration.run_iteration(Ledger(ledger.path), 'faults', NOW, services) == result
    assert effects.count('recover') == 1


@pytest.mark.parametrize('failed_post', [False, True])
def test_post_debt_survives_reopen_and_corrupt_collection(case, failed_post):
    ledger, _, pair, _ = case
    qualified_restore(case)
    backup.mark_released(ledger, pair['release_pair_id'], pair['post_identity'], context=CONTEXT, now=NOW)
    def fail_post(action, context):
        if action == 'collect': raise OSError('SIMULATED storage failure')
        return artifacts(action, context)
    if failed_post:
        failure = collect(case, fail_post, 'POST')
        assert failure.status == 'failed'
    restarted = Ledger(ledger.path)
    assert backup.release_allowed(restarted, 'next-release', context=CONTEXT, now=NOW) is False
    assert backup.release_allowed(restarted, 'next-release', recovery=True) is True
    if failed_post:
        assert collect(case, phase='POST') == failure  # terminal attempts are never silently retried
        assert Ledger(ledger.path).get(failure.operation_id)['status'] == 'failed'
        return
    post = qualified_restore(case, 'POST')
    assert backup.release_allowed(restarted, 'next-release', context=CONTEXT, now=NOW) is True
    artifact = post.evidence['manifest_path']
    from pathlib import Path
    (Path(artifact).parent / 'attachment.bin').write_bytes(b'corrupt-after-restore')
    assert collect(case, phase='POST').status == 'blocked'
    assert backup.release_allowed(restarted, 'next-release', context=CONTEXT, now=NOW) is False


@pytest.mark.parametrize('response', ['402', 'empty', 'unknown_usage'])
def test_model_402_empty_unknown_usage_preserves_budget(tmp_path, policy, monkeypatch, response):
    import ops.pi.budget as budget
    clock = [1791734399.0]
    monkeypatch.setattr(budget.time, 'time', lambda:clock[0])
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    calls = []
    def external(_):
        calls.append(response)
        if response == '402': return httpx.Response(402, content=b'')
        if response == 'empty': return httpx.Response(200, content=b'')
        return httpx.Response(200, json={'id':'simulated-provider', 'usage':{'input_tokens':1}})
    result = forward_messages(request(), 'local-trial-1', ledger=ledger, policy=policy, transport=transport(external))
    assert result.status_code in (200, 402, 502)
    frozen = ledger.get(result.attempt_id)
    assert frozen['status'] == 'uncertain'
    assert frozen['evidence']['usage_known'] is False
    assert totals(ledger, 'local-trial-1') == (1, 10000)
    clock[0] += 86402
    reopened = Ledger(ledger.path)
    assert reopened.get(result.attempt_id) == frozen
    assert totals(reopened, 'local-trial-1') == (1, 10000)
    assert calls == [response]


@pytest.mark.parametrize('after_write', [False, True])
def test_crash_before_and_after_candidate_requires_reconciliation(tmp_path, after_write):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    services, _, candidate, recovered, effects = simulated_services(tmp_path)
    real_stage = services['stages']['develop']
    def crash(context):
        if after_write: real_stage(context)
        raise KeyboardInterrupt('SIMULATED process boundary')
    services['stages']['develop'] = crash
    with pytest.raises(KeyboardInterrupt): iteration.run_iteration(ledger, 'faults', NOW, services)
    before = candidate.read_bytes() if candidate.exists() else None
    services['stages']['develop'] = real_stage
    result = iteration.run_iteration(Ledger(ledger.path), 'faults', NOW, services)
    assert (candidate.read_bytes() if candidate.exists() else None) == before
    assert effects.count('develop') == int(after_write)
    assert not recovered.exists()
    assert result.status == 'uncertain' and result.evidence['next_action'] == 'reconcile'
    pending = result.evidence['stage_receipts'][-1]['operation_id']
    assert Ledger(ledger.path).get(pending)['status'] == 'pending'


def test_human_same_sha_takeover_preserves_new_candidate(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    services, identity, candidate, recovered, effects = simulated_services(tmp_path)
    def human_takeover(context):
        candidate.write_bytes(b'human-owned candidate')
        identity.update(owner='human', generation=2, deployment_id='human-2')
        return Receipt(context['operation_id'], 'failed', {'reason':'SIMULATED takeover'})
    services['stages']['develop'] = human_takeover
    result = iteration.run_iteration(ledger, 'faults', NOW, services)
    assert not recovered.exists() and 'recover' not in effects
    assert result.evidence['attribution'] == 'confounded'
    assert result.evidence['recovery']['status'] == 'blocked'
    assert candidate.read_bytes() == b'human-owned candidate'
    assert identity['main'] == 'a'*40


def test_0530_cutoff_0600_opening_is_selection_only(tmp_path, policy):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    local = timezone(timedelta(hours=8))
    before = datetime(2026, 10, 12, 5, 29, 59, tzinfo=local)
    assert window_at(before)['allow_new_candidate'] is True
    cutoff = before + timedelta(seconds=1)
    assert window_at(cutoff)['allow_new_candidate'] is False
    assert next_action(ledger, cutoff, {}, policy)['kind'] == 'close'
    assert next_action(ledger, cutoff.replace(hour=6, minute=0), {}, policy)['kind'] == 'open'
    with ledger.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM operations').fetchone()[0] == 0
    assert not (tmp_path / 'candidate.bin').exists()


def test_actual_mode_requires_gate_before_file_side_effect(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    services, _, candidate, recovered, effects = simulated_services(tmp_path)
    services['mode'] = 'ACTUAL'
    result = iteration.run_iteration(ledger, 'faults', NOW, services)
    assert result.status == 'blocked'
    assert result.evidence['reason'] == 'fresh_independent_runtime_acceptance_required'
    assert not candidate.exists() and not recovered.exists() and effects == []


def test_interrupted_analysis_keeps_source_ids_and_unknown_quality(tmp_path):
    from ops.pi.tests.test_writing_evidence import bundle, save, TASK
    from ops.pi.writing_evidence import load_writing_bundle, analyze_writing_bundle
    path, sha = save(tmp_path, bundle())
    report = analyze_writing_bundle(load_writing_bundle(path, sha, trusted_root=tmp_path))
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    ledger.intent('frozen-analysis', 'writing-analysis', report)
    services, _, _, _, _ = simulated_services(tmp_path)
    def crash(context): raise KeyboardInterrupt('SIMULATED analysis interruption')
    services['stages']['analysis'] = crash
    with pytest.raises(KeyboardInterrupt): iteration.run_iteration(ledger, 'faults', NOW, services)
    restarted = Ledger(ledger.path)
    assert iteration.run_iteration(restarted, 'faults', NOW, services).status == 'uncertain'
    saved = restarted.get('frozen-analysis')['payload']
    assert saved['dataset_sha256'] == sha == hashlib.sha256(path.read_bytes()).hexdigest()
    assert saved['sources']['tasks'][0]['id'] == TASK
    assert len(saved['quality_catalog']) == 45
    assert all(row['value'] is None and row['availability'] == 'unknown'
               for row in saved['quality_catalog'].values())
    assert saved == report
