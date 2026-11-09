"""Idle manual releases append a baseline without rewriting completed cycles."""
from copy import deepcopy
from datetime import timedelta
import json
import uuid

import pytest

from ops.pi.audit import digest
from ops.pi.development_inputs import file_hash, ledger_snapshot
from ops.pi.tests.test_nightly_handoff import handoff_case, case


@pytest.fixture
def idle_case(handoff_case):
    g, cycle, _, _, old, driver, config, proof, _, execute = handoff_case
    execute()
    operation = str(uuid.uuid4())
    config['manual_baseline'] = operation
    driver.write_text(json.dumps(config))
    proof = deepcopy(proof)
    proof['identity'] = dict(proof['identity'], deployment_id='next-manual-main', generation=3)
    observer = driver.parent / 'next-observer.json'
    observer.write_text(json.dumps({'identity': proof['identity'], 'root': str(driver.parent / 'metrics')}))
    observer.chmod(0o600)
    proof['observer'] = {'path': str(observer), 'sha256': file_hash(observer)}
    with g._connection() as db:
        old_result = g._row(db, cycle)['result_sha256']
    value = dict(schema='pi-idle-main-baseline-v1', mode='SIMULATED', issuer='human_operator',
        action='adopt_idle_manual_main_release', operation_id=operation,
        previous_cycle_id=cycle, previous_result_sha256=old_result, previous_identity=old['new_identity'],
        new_identity=proof['identity'], new_package_sha256=proof['package_sha256'],
        driver_sha256=file_hash(driver), profile_sha256=proof['profile_sha256'],
        issued_at=g.clock().isoformat(), expires_at=(g.clock()+timedelta(hours=1)).isoformat())
    permission = handoff_case[2].parent / (operation + '.json')
    permission.write_text(json.dumps(value)); permission.chmod(0o600)
    return g, cycle, driver, permission, value, proof


def adopt(c, verify=None):
    from ops.pi.idle_baseline import adopt
    g, cycle, driver, permission, value, proof = c
    return adopt(g, permission, file_hash(permission), driver, file_hash(driver),
                 verify=verify or (lambda *args: deepcopy(proof)))


def test_idle_baseline_preserves_history_and_original_accounting(idle_case):
    g, cycle, *_ = idle_case
    before = ledger_snapshot(g.state), ledger_snapshot(g.billing)
    with g._connection() as db:
        history = [tuple(r) for r in db.execute('SELECT * FROM approval_cycles')]
    result = adopt(idle_case)
    assert result['status'] == 'baseline_adopted' and result['model_requests'] == 0
    assert g.status()['phase'] == 'idle'
    with g._connection() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM approval_cycles')] == history
    assert (ledger_snapshot(g.state), ledger_snapshot(g.billing)) == before
    assert adopt(idle_case, lambda *a: pytest.fail('verified adoption must not replay')) == result


def test_active_round_prevents_idle_baseline(idle_case):
    g = idle_case[0]
    cycle = str(uuid.uuid4()); g.begin(cycle, '2026-11-03')
    with pytest.raises(ValueError, match='idle'):
        adopt(idle_case)


@pytest.mark.parametrize('field', ['issuer', 'action', 'previous_result_sha256', 'driver_sha256'])
def test_wrong_operator_binding_is_rejected(idle_case, field):
    c = idle_case; value = c[4]; value[field] = 'wrong'
    c[3].write_text(json.dumps(value))
    with pytest.raises(ValueError):
        adopt(c)


def test_bad_physical_proof_cannot_publish_baseline(idle_case):
    def wrong(*args):
        result = deepcopy(idle_case[-1]); result['identity']['deployment_id'] = 'wrong'
        return result
    with pytest.raises(ValueError):
        adopt(idle_case, wrong)


def test_unfinished_adoption_is_not_replayed(idle_case):
    from ops.pi.idle_baseline import output_root
    g, cycle, driver, permission, value, proof = idle_case
    root = output_root(g, json.loads(driver.read_bytes()), value['operation_id'])
    root.parent.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    (root/'baseline-intent.json').write_text('{}')
    with pytest.raises(ValueError, match='unfinished'):
        adopt(idle_case)


def test_source_loader_uses_verified_baseline_and_detects_drift(idle_case):
    from ops.pi.idle_baseline import load
    g, cycle, driver, permission, value, proof = idle_case
    adopt(idle_case)
    binding = dict(path=str(driver), sha256=file_hash(driver))
    result = load(g, cycle, value['previous_result_sha256'], binding,
                  json.loads(driver.read_bytes())['source_template']['sha256'])
    assert result[0]['manifest']['image_id'] == proof['identity']['image_ids']['python']
    assert result[2]['containers'][0]['identity'] == proof['identity']
    value['new_identity']['deployment_id'] = 'tampered'
    permission.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load(g, cycle, value['previous_result_sha256'], binding,
             json.loads(driver.read_bytes())['source_template']['sha256'])


def test_expired_permission_cannot_adopt(idle_case):
    idle_case[4]['expires_at'] = idle_case[4]['issued_at']
    idle_case[3].write_text(json.dumps(idle_case[4]))
    with pytest.raises(ValueError):
        adopt(idle_case)


def test_actual_component_rejects_simulated_verifier(idle_case):
    idle_case[0].mode = 'ACTUAL'
    with pytest.raises(ValueError, match='root native'):
        adopt(idle_case)


def test_accounting_drift_cannot_publish_idle_receipt(idle_case):
    def changed(*args):
        from ops.pi.ledger import Ledger
        Ledger(idle_case[0].billing, existing=True).intent('new-unknown', 'model_attempt', {'held_microyuan': 1})
        return deepcopy(idle_case[-1])
    with pytest.raises(ValueError, match='accounting'):
        adopt(idle_case, changed)


def test_nightly_lock_serializes_idle_adoption(idle_case):
    import fcntl
    config = json.loads(idle_case[2].read_bytes())
    with open(config['lock_path'], 'rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            adopt(idle_case)


def test_later_pi_comparison_supersedes_manual_baseline(idle_case):
    from ops.pi.idle_baseline import load
    adopt(idle_case)
    g, cycle, driver, permission, value, proof = idle_case
    assert load(g, str(uuid.uuid4()), 'f'*64, {'path': str(driver), 'sha256': file_hash(driver)},
                json.loads(driver.read_bytes())['source_template']['sha256']) is None


def test_unfinished_sibling_cannot_be_bypassed_with_new_operation(idle_case):
    from ops.pi.idle_baseline import output_root
    g, cycle, driver, permission, value, proof = idle_case
    root = output_root(g, json.loads(driver.read_bytes()), value['operation_id'])
    root.parent.mkdir(mode=0o700); root.mkdir(mode=0o700)
    (root/'baseline-intent.json').write_text('{}')
    operation = str(uuid.uuid4())
    config = json.loads(driver.read_bytes()); config['manual_baseline'] = operation
    driver.write_text(json.dumps(config))
    value['operation_id'] = operation; value['driver_sha256'] = file_hash(driver)
    next_permission = permission.parent/(operation+'.json')
    next_permission.write_text(json.dumps(value)); next_permission.chmod(0o600)
    next_case = (g, cycle, driver, next_permission, value, proof)
    with pytest.raises(ValueError, match='unfinished'):
        adopt(next_case)


def test_inherited_candidate_cannot_bypass_fresh_manual_baseline(idle_case):
    g, cycle, driver, permission, value, proof = idle_case
    config = json.loads(driver.read_bytes()); config['inherit_task_id'] = str(uuid.uuid4())
    driver.write_text(json.dumps(config))
    value['driver_sha256'] = file_hash(driver); permission.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='driver'):
        adopt(idle_case)


from ops.pi.tests.test_nightly_source import source_case, binding_case, deployed_case, bundle_case, finished, stopped, completed, config_file


def test_normal_source_preparation_uses_the_new_idle_deployment(source_case):
    from pathlib import Path
    from ops.pi.idle_baseline import adopt as perform_adoption
    from ops.pi.nightly_source import prepare
    prior, empty_cycle, empty_out, template, binding, collect, old_rows = source_case
    g, previous, old_out, task, finish, now = prior
    g.no_release(empty_cycle, 'no_evidence', 'f'*64)
    operation = str(uuid.uuid4())
    old_identity = old_rows[0]['identity']
    identity = dict(old_identity, deployment_id='idle-main-current', generation=old_identity['generation']+1,
                    commit_sha='9'*40, image_ids={'python':'sha256:'+'8'*64})
    old_observer = json.loads(Path(binding['path']).read_bytes())
    observer_path = old_out.parent/'idle-observer.json'
    observer_path.write_text(json.dumps(dict(old_observer, identity=identity))); observer_path.chmod(0o600)
    profile = old_out.parent/'idle-profile.json'; profile.write_text('{}'); profile.chmod(0o600)
    lock = old_out.parent/'idle-nightly.lock'; lock.touch(mode=0o600)
    with g._connection() as db:
        result_pin = g._row(db, previous)['result_sha256']
    config = dict(schema='pi-nightly-driver-v1', mode='SIMULATED', state_path=str(g.state), billing_path=str(g.billing), gate_path=str(g.path),
        root=str(old_out.parent), lock_path=str(lock), inherit_task_id=None, base_image_id=identity['image_ids']['python'], docker='/bin/echo', endpoint='unix:///test.sock', daemon_id='test',
        autonomy_profile={'path':str(profile),'sha256':file_hash(profile)}, source_template={'path':str(template),'sha256':file_hash(template)}, manual_baseline=operation)
    driver = old_out.parent/'idle-driver.json'; driver.write_text(json.dumps(config)); driver.chmod(0o600)
    permission = dict(schema='pi-idle-main-baseline-v1', mode='SIMULATED', issuer='human_operator', action='adopt_idle_manual_main_release', operation_id=operation,
        previous_cycle_id=previous, previous_result_sha256=result_pin, previous_identity=old_identity, new_identity=identity, new_package_sha256='a'*64,
        driver_sha256=file_hash(driver), profile_sha256=file_hash(profile), issued_at=g.clock().isoformat(), expires_at=(g.clock()+timedelta(hours=1)).isoformat())
    permission_path = old_out.parent/'idle-permission.json'; permission_path.write_text(json.dumps(permission)); permission_path.chmod(0o600)
    proof = dict(identity=identity, package_sha256=permission['new_package_sha256'], source_sha256='b'*64, profile_sha256=file_hash(profile), cohort_sha256='c'*64,
        audit_path=old_observer['audit_path'], export_root=str(old_out/'export'), observer={'path':str(observer_path),'sha256':file_hash(observer_path)}, deployed_at=g.clock().isoformat(), metrics_source_sha256='d'*64)
    adopted = perform_adoption(g, permission_path, file_hash(permission_path), driver, file_hash(driver), verify=lambda *a:deepcopy(proof))
    now[0] += timedelta(days=2)
    cycle = str(uuid.uuid4()); assert g.begin(cycle,'2026-11-04')['claimed']
    out = old_out.parent/cycle; out.mkdir(mode=0o700)
    rows = [dict(r, identity=identity, image_id=identity['image_ids']['python']) for r in old_rows]
    result = prepare(g, cycle, out, template, file_hash(template), baseline={'path':str(driver),'sha256':file_hash(driver)},
        collect=collect, inspect_cohort=lambda *a:deepcopy(rows),
        read_source=lambda *a:{'src/a.py':(old_out/'bundle/candidate/src/a.py').read_text()})
    assert result['base_image_id'] == identity['image_ids']['python']
    assert result['comparison_sha256'] is None
    assert result['baseline_receipt_sha256'] == adopted['result_sha256']
    assert json.loads(Path(result['profile']['path']).read_bytes())['source']['reference_commit'] == identity['commit_sha']


def test_first_partial_day_waits_without_claiming_or_calling_models(idle_case):
    from ops.pi.nightly_driver import run
    from ops.pi.idle_baseline import window_ready
    adopt(idle_case)
    g, cycle, driver, permission, value, proof = idle_case
    binding = {'path':str(driver), 'sha256':file_hash(driver)}
    assert not window_ready(g, binding)
    before = ledger_snapshot(g.state), ledger_snapshot(g.billing)
    result = run(driver, file_hash(driver), clock=g.clock,
                 source_prepare=lambda *a, **k:pytest.fail('partial day must not collect or analyze'))
    assert result['status'] == 'baseline_window_not_ready' and g.status()['phase'] == 'idle'
    assert (ledger_snapshot(g.state), ledger_snapshot(g.billing)) == before
    now = g.clock(); g.clock = lambda:now+timedelta(days=2)
    assert window_ready(g, binding)
