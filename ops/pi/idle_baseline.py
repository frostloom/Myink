"""Root adoption of a verified manual release while the original Gate is idle."""
from datetime import timedelta
import fcntl
import os
from pathlib import Path
import stat

from .audit import AuditStore, _path, _plain, digest, hash_value, require, strict_json, utc
from .development_inputs import file_hash, ledger_snapshot
from .nightly_gate import BASE, ApprovalGate, _uuid
from .nightly_driver import _load
from .nightly_handoff import _native, PROOF_FIELDS
from .product_commands import _write

FIELDS = set('schema mode issuer action operation_id previous_cycle_id previous_result_sha256 previous_identity new_identity new_package_sha256 driver_sha256 profile_sha256 issued_at expires_at'.split())


def _permission(gate, path, pin, *, current):
    value = gate._trusted(path, pin, 'handoff')
    require(set(value) == FIELDS and value['schema'] == 'pi-idle-main-baseline-v1'
            and value['mode'] == gate.mode and value['issuer'] == 'human_operator'
            and value['action'] == 'adopt_idle_manual_main_release', 'exact idle operator permission required')
    _uuid(value['operation_id']); _uuid(value['previous_cycle_id'])
    require(all(hash_value(value[k]) for k in ('previous_result_sha256', 'new_package_sha256', 'driver_sha256', 'profile_sha256')), 'exact idle baseline pins required')
    from .live_observer import _identity
    for key in ('previous_identity', 'new_identity'):
        _identity(value[key])
        require(set(value[key]) == set('deployment_id generation owner image_ids commit_sha schema_id config_hash'.split())
                and all(v is not None for v in value[key].values()) and 'python' in value[key]['image_ids'], 'complete manual deployment identity required')
    old, new = value['previous_identity'], value['new_identity']
    require(new['generation'] == old['generation'] + 1 and new['deployment_id'] != old['deployment_id'], 'new manual deployment generation required')
    issued, expires, now = utc(value['issued_at']), utc(value['expires_at']), utc(gate.clock())
    require(issued <= now and issued < expires and expires-issued <= timedelta(hours=1), 'bounded idle permission lifetime required')
    if current:
        require(now < expires, 'idle permission expired')
    return value


def output_root(gate, driver, operation):
    _uuid(operation)
    parent = BASE/'control/manual-baselines' if gate.mode == 'ACTUAL' else _path(driver['root']).parent/'manual-baselines'
    return _path(parent/operation)


def _anchor(gate):
    with gate._connection() as db:
        row = db.execute("SELECT cycle_id,result_sha256 FROM approval_cycles WHERE phase='completed' AND package IS NOT NULL AND deployment IS NOT NULL ORDER BY rowid DESC LIMIT 1").fetchone()
        require(row is not None and hash_value(row['result_sha256']), 'verified deployed predecessor required')
        return row['cycle_id'], row['result_sha256']


def _proof(permission, proof):
    require(isinstance(proof, dict) and set(proof) == PROOF_FIELDS
            and proof['identity'] == permission['new_identity']
            and proof['package_sha256'] == permission['new_package_sha256']
            and proof['profile_sha256'] == permission['profile_sha256']
            and all(hash_value(proof[k]) for k in ('source_sha256', 'cohort_sha256', 'metrics_source_sha256')), 'verified idle deployment proof required')


def _result(receipt):
    return dict(status='baseline_adopted', operation_id=receipt['operation_id'],
                result_sha256=digest(receipt), model_requests=0, known_cost_microyuan=0)


def adopt(gate, permission_path, permission_pin, driver_path, driver_pin, *, verify=None):
    require((gate.mode == 'ACTUAL' and os.geteuid() == 0 and verify is None)
            or (gate.mode == 'SIMULATED' and callable(verify)), 'root native or isolated baseline verifier required')
    permission_path, driver_path = _path(permission_path), _path(driver_path)
    permission = _permission(gate, permission_path, permission_pin, current=False)
    driver = _load(driver_path, driver_pin, (), None if gate.mode == 'ACTUAL' else gate.clock)
    require(driver['inherit_task_id'] is None and driver['manual_baseline'] == permission['operation_id'] and driver_pin == permission['driver_sha256']
            and driver['base_image_id'] == permission['new_identity']['image_ids']['python']
            and driver['autonomy_profile']['sha256'] == permission['profile_sha256']
            and all(_path(driver[k]) == v for k, v in [('state_path', gate.state), ('billing_path', gate.billing), ('gate_path', gate.path)]), 'idle driver binding changed')
    profile = _path(driver['autonomy_profile']['path'])
    template = _path(driver['source_template']['path'])
    require(file_hash(profile) == permission['profile_sha256'] and file_hash(template) == driver['source_template']['sha256'], 'idle source inputs changed')
    root = output_root(gate, driver, permission['operation_id'])
    maintenance = BASE/'control/maintenance.lock' if gate.mode == 'ACTUAL' else _path(driver['lock_path']).with_name('maintenance.lock')
    _plain(maintenance)
    with _path(driver['lock_path']).open('rb') as night_lock, maintenance.open('rb') as maintenance_lock:
        fcntl.flock(night_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(maintenance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(gate.status()['phase'] == 'idle', 'idle Gate required for manual baseline')
        require(_anchor(gate) == (permission['previous_cycle_id'], permission['previous_result_sha256']), 'idle predecessor changed')
        if (root/'verified.json').exists():
            receipt = _read(root/'verified.json', gate.mode)
            require(receipt['permission_sha256'] == permission_pin and receipt['driver_sha256'] == driver_pin, 'idle baseline receipt changed')
            return _result(receipt)
        _permission(gate, permission_path, permission_pin, current=True)
        if not root.parent.exists():
            root.parent.mkdir(mode=0o700)
        require(root.parent.is_dir() and stat.S_IMODE(root.parent.stat().st_mode) == 0o700, 'private idle baseline root required')
        siblings = list(root.parent.iterdir())
        require(len(siblings) <= 4096 and not any(p != root and p.is_dir() and not (p/'verified.json').is_file() for p in siblings), 'unfinished sibling idle baseline retained; inspect original operation')
        root.mkdir(mode=0o700, exist_ok=True)
        require(not (root/'baseline-intent.json').exists(), 'unfinished idle baseline retained; inspect original operation')
        (root/'commands').mkdir(mode=0o700)
        accounting = ledger_snapshot(gate.state), ledger_snapshot(gate.billing)
        _write(root/'baseline-intent.json', dict(permission_sha256=permission_pin, driver_sha256=driver_pin, accounting_sha256=digest(accounting)))
        proof = (verify or _native)(gate, permission, driver, root)
        _proof(permission, proof)
        require((ledger_snapshot(gate.state), ledger_snapshot(gate.billing)) == accounting, 'idle accounting changed')
        audit, export = _path(proof['audit_path']), _path(proof['export_root'])
        from .local_cycle import _disjoint
        for output in (audit, export):
            for protected in (gate.path, gate.state, gate.billing, permission_path, driver_path, profile, root):
                _disjoint(output, protected)
        _disjoint(audit, export)
        if gate.mode == 'ACTUAL':
            require(audit == BASE/'audit/state/events.sqlite' and export == BASE/'audit/export', 'original idle audit required')
        identity = permission['new_identity']
        domain = 'online_business' if gate.mode == 'ACTUAL' else 'synthetic'
        event = dict(kind='version', status='insufficient_evidence', run_id=permission['operation_id'], occurred_at=utc(gate.clock()).isoformat(),
            summary='Human main deployment verified while idle; future research uses this version. No comparison or quality improvement is claimed.',
            details=dict(reference='nightly.idle_baseline.v1', operation_id=permission['operation_id'], decision='baseline_adopted', reason='manual_main_release', next_action='fresh_daily_source', model_requests=0, known_cost_microyuan=0),
            version=dict(source_commit=identity['commit_sha'], deployment_id=identity['deployment_id'], generation=identity['generation'], owner=identity['owner'], image_ids=identity['image_ids']),
            changes=[], evidence=[dict(kind='verified_idle_main', sha256=digest(proof), verified=True, evidence_domain=domain)], followups=[], mode=gate.mode, evidence_domain=domain)
        store = AuditStore(audit); store.append('idle-main-baseline:'+permission['operation_id'], event); store.export(export)
        if gate.mode == 'ACTUAL':
            from .nightly_binding import _audit_outputs, _ordinary
            for path in _audit_outputs(proof):
                _ordinary(path, gate.mode)
        require(file_hash(driver_path) == driver_pin and file_hash(profile) == permission['profile_sha256']
                and file_hash(template) == driver['source_template']['sha256'] and file_hash(permission_path) == permission_pin
                and (ledger_snapshot(gate.state), ledger_snapshot(gate.billing)) == accounting
                and gate.status()['phase'] == 'idle' and _anchor(gate) == (permission['previous_cycle_id'], permission['previous_result_sha256']), 'idle handoff inputs changed')
        require((verify or _native)(gate, permission, driver, root) == proof, 'idle physical deployment changed')
        receipt = dict(schema='pi-idle-main-baseline-result-v1', mode=gate.mode, operation_id=permission['operation_id'], permission_path=str(permission_path), permission_sha256=permission_pin,
            driver_sha256=driver_pin, previous_cycle_id=permission['previous_cycle_id'], previous_result_sha256=permission['previous_result_sha256'],
            source_template_sha256=driver['source_template']['sha256'], proof=proof, accounting_sha256=digest(accounting), model_requests=0, known_cost_microyuan=0)
        _write(root/'verified.json', receipt)
        return _result(receipt)


def _read(path, mode):
    path = _path(path); _plain(path)
    require(path.stat().st_size <= 1048576 and stat.S_IMODE(path.stat().st_mode) == 0o600
            and (mode != 'ACTUAL' or path.stat().st_uid == 0), 'private idle baseline receipt required')
    return strict_json(path.read_bytes())


def load(gate, previous, result_pin, binding, template_pin):
    driver = _load(_path(binding['path']), binding['sha256'], (), None if gate.mode == 'ACTUAL' else gate.clock)
    operation = driver['manual_baseline']
    root = output_root(gate, driver, operation)
    receipt = _read(root/'verified.json', gate.mode)
    permission = _permission(gate, _path(receipt['permission_path']), receipt['permission_sha256'], current=False)
    require(receipt['schema'] == 'pi-idle-main-baseline-result-v1' and receipt['mode'] == gate.mode
            and receipt['operation_id'] == operation == permission['operation_id']
            and receipt['driver_sha256'] == binding['sha256'] == permission['driver_sha256']
            and receipt['source_template_sha256'] == template_pin == driver['source_template']['sha256']
            and (receipt['previous_cycle_id'], receipt['previous_result_sha256']) == (permission['previous_cycle_id'], permission['previous_result_sha256']), 'idle baseline binding drift')
    _proof(permission, receipt['proof'])
    # A later verified Pi deployment supersedes this manual baseline naturally.
    if (previous, result_pin) != (permission['previous_cycle_id'], permission['previous_result_sha256']):
        return None
    proof = receipt['proof']
    observer_binding = proof['observer']; observer = _read(observer_binding['path'], gate.mode)
    require(file_hash(observer_binding['path']) == observer_binding['sha256'] and observer['identity'] == proof['identity'], 'idle observer changed')
    packet = dict(schema='pi-human-main-baseline-v1', manifest=dict(image_id=proof['identity']['image_ids']['python']), image=dict(package_sha256=proof['package_sha256']))
    return packet, dict(packet=dict(deployed_at=proof['deployed_at'])), dict(containers=[dict(identity=proof['identity'])]), root/'verified.json', observer_binding, observer


def window_ready(gate, binding):
    previous, result_pin = _anchor(gate)
    driver = _load(_path(binding['path']), binding['sha256'], (), None if gate.mode == 'ACTUAL' else gate.clock)
    baseline = load(gate, previous, result_pin, binding, driver['source_template']['sha256'])
    if baseline is None:
        return True
    from .live_observer import observation_window
    observer = dict(baseline[5], window_policy='previous_day_shanghai', lookback_hours=24)
    start, _ = observation_window(observer, utc(gate.clock()))
    return utc(baseline[1]['packet']['deployed_at']) <= start


def run(config_path, pin):
    gate = ApprovalGate(BASE/'state/nightly-approval.sqlite', BASE/'state/actual-manager.sqlite', BASE/'state/ledger.sqlite', mode='ACTUAL')
    permission = _permission(gate, _path(config_path), pin, current=False)
    return adopt(gate, config_path, pin, BASE/'config/nightly-driver.json', permission['driver_sha256'])
