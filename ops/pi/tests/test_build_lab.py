"""Only a current, fully enumerated B12 child group may be cancelled."""
import copy
import pytest

from ops.pi.lab.build_lab import validate_cancellation

OP = '11111111-1111-4111-8111-111111111111'
GROUP = 'myinkpi-heavy-b1211111111111141118111111111111111.slice'
ROOT = '/myinkpi.slice/myinkpi-heavy.slice/' + GROUP
ID = '1' * 64
IMAGE = 'sha256:' + '2' * 64


def proof():
    owner = {'operation_id': OP, 'lab_uuid': 'lab', 'unit': 'myinkpi-test-' + OP,
             'group': 'b12', 'status': 'active', 'child_group': GROUP}
    configuration = {'id': ID, 'image': IMAGE, 'user': '1000:1000', 'host': {}, 'mounts': [], 'networks': {}}
    manifest = {'operation_id': OP, 'lab_uuid': 'lab', 'daemon_id': '364e8400-3844-47e2-b86d-8b626332f61c',
                'unit': owner['unit'], 'child_group': GROUP, 'objects': [
                    {'kind': 'container', 'status': 'created', 'id': ID, 'frozen': configuration}],
                'protected': {'source': {'id': '3' * 64, 'image': IMAGE, 'user': '', 'host': {}, 'mounts': [], 'networks': {}}}}
    actual = {'unit_active': True, 'unit_cgroup': ROOT + '/' + owner['unit'] + '.service',
        'limits': {'memory.max': '1073741824', 'memory.swap.max': '268435456', 'cpu.max': '200000 100000'},
        'ancestor_verified': True, 'parent_limits_verified': True,
        'members': {101: ROOT + '/docker-' + ID + '.scope', 102: ROOT + '/' + owner['unit'] + '.service'},
        'containers': {ID: {'configuration': configuration, 'operation_id': OP, 'lab_uuid': 'lab', 'pid': 101, 'running': True}},
        'protected': {'source': {'configuration': manifest['protected']['source'], 'running': True, 'pid': 201}},
        'protected_members': {201: '/myinkpi.slice/myinkpi-heavy.slice/docker-source.scope'},
        'unknown_daemon_effects': False}
    return owner, manifest, actual


def test_owned_child_cancel_target_never_includes_protected_parent():
    owner, manifest, actual = proof()
    result = validate_cancellation(owner, manifest, actual)
    assert result == {'group_path': ROOT, 'container_ids': [ID], 'owned_pids': [101, 102]}
    assert 201 not in result['owned_pids']


@pytest.mark.parametrize('fault', ['stale', 'owner', 'lab', 'daemon', 'missing_manifest', 'foreign_group',
    'ancestor', 'parent_cap', 'child_cap', 'swap', 'cpu', 'pending_create', 'container_id', 'container_config',
    'container_lab', 'container_operation', 'escaped_pid', 'unknown_member', 'protected_adopted',
    'protected_stopped', 'protected_config', 'daemon_unknown'])
def test_cancellation_rejects_unconfirmed_or_foreign_authority(fault):
    owner, manifest, actual = proof()
    if fault == 'stale': owner['status'] = 'completed'
    if fault == 'owner': manifest['operation_id'] = '22222222-2222-4222-8222-222222222222'
    if fault == 'lab': manifest['lab_uuid'] = 'foreign'
    if fault == 'daemon': manifest['daemon_id'] = 'foreign'
    if fault == 'missing_manifest': manifest = {}
    if fault == 'foreign_group': actual['unit_cgroup'] = '/myinkpi.slice/myinkpi-heavy.slice/foreign.service'
    if fault == 'ancestor': actual['ancestor_verified'] = False
    if fault == 'parent_cap': actual['parent_limits_verified'] = False
    if fault == 'child_cap': actual['limits']['memory.max'] = '1610612736'
    if fault == 'swap': actual['limits']['memory.swap.max'] = '0'
    if fault == 'cpu': actual['limits']['cpu.max'] = 'max 100000'
    if fault == 'pending_create': manifest['objects'][0]['status'] = 'intent'
    if fault == 'container_id': manifest['objects'][0]['id'] = '4' * 64
    if fault == 'container_config':
        actual['containers'][ID]['configuration'] = {**actual['containers'][ID]['configuration'], 'user': '0'}
    if fault == 'container_lab': actual['containers'][ID]['lab_uuid'] = 'foreign'
    if fault == 'container_operation': actual['containers'][ID]['operation_id'] = 'foreign'
    if fault == 'escaped_pid': actual['members'][101] = '/foreign/docker.scope'
    if fault == 'unknown_member': actual['members'][103] = ROOT + '/docker-unknown.scope'
    if fault == 'protected_adopted': actual['protected_members'][201] = ROOT + '/docker-source.scope'
    if fault == 'protected_stopped': actual['protected']['source']['running'] = False
    if fault == 'protected_config': actual['protected']['source']['configuration'] = {}
    if fault == 'daemon_unknown': actual['unknown_daemon_effects'] = True
    with pytest.raises(ValueError):
        validate_cancellation(owner, manifest, actual)
def test_cancel_writes_only_owned_child_and_rechecks_owner(monkeypatch):
    from pathlib import Path
    from ops.pi.lab import build_lab, verify
    owner, manifest, actual = proof()
    actual['unknown_daemon_effects'] = False
    writes, updates = [], []
    def trusted(path):
        if path.name == 'current-operation.json': return dict(owner)
        if path.name == 'creation.json': return manifest
        if path.name == 'runtime-manifest.json': return {'lab_uuid': 'lab', 'containers': manifest['protected']}
        raise AssertionError(path)
    monkeypatch.setattr(build_lab, 'trusted_json', trusted)
    monkeypatch.setattr(build_lab, 'cancellation_state', lambda *args: actual)
    monkeypatch.setattr(Path, 'write_text', lambda path, value: writes.append((path.as_posix(), value)))
    monkeypatch.setattr(build_lab, '_group_members', lambda path: {})
    monkeypatch.setattr(build_lab, '_docker', lambda *args: [{'State': {'Running': False, 'Pid': 0}}])
    monkeypatch.setattr(build_lab, 'verify_runtime', lambda: {})
    monkeypatch.setattr(build_lab, '_write_b12_owner', lambda value: updates.append(value))
    result = build_lab.cancel_b12_owned(OP, 'lab')
    assert writes == [('/sys/fs/cgroup' + ROOT + '/cgroup.kill', '1')]
    assert result['owned_empty'] is True and result['protected_runtime_unchanged'] is True
    assert updates[0]['status'] == 'cancelled'


def test_owner_change_between_validation_and_kill_has_no_effect(monkeypatch):
    from pathlib import Path
    from ops.pi.lab import build_lab
    owner, manifest, actual = proof()
    reads, writes = [], []
    def trusted(path):
        if path.name == 'current-operation.json':
            reads.append(1)
            return owner if len(reads) == 1 else {**owner, 'operation_id': 'changed'}
        if path.name == 'creation.json': return manifest
        return {'lab_uuid': 'lab', 'containers': manifest['protected']}
    monkeypatch.setattr(build_lab, 'trusted_json', trusted)
    monkeypatch.setattr(build_lab, 'cancellation_state', lambda *args: actual)
    monkeypatch.setattr(Path, 'write_text', lambda *args: writes.append(args))
    with pytest.raises(ValueError):
        build_lab.cancel_b12_owned(OP, 'lab')
    assert writes == []


def test_legacy_cancel_dispatches_b12_without_parent_kill(monkeypatch, tmp_path):
    from ops.pi.lab import build_lab, verify
    owner, manifest, actual = proof()
    (tmp_path / 'current-operation.json').write_text(__import__('json').dumps(owner))
    (tmp_path / 'lab-env.json').write_text('{"lab_uuid": "lab"}')
    monkeypatch.setattr(verify, 'BASE', tmp_path)
    called = []
    monkeypatch.setattr(verify, '_run', lambda *args: (_ for _ in ()).throw(AssertionError('legacy parent cancellation path invoked')))
    monkeypatch.setattr(__import__('pathlib').Path, 'write_text', lambda *args: None)
    monkeypatch.setattr(build_lab, 'cancel_b12_owned', lambda op, lab: called.append((op, lab)) or {'owned_empty': True})
    assert verify.cancel_owned(OP, 'lab') == {'owned_empty': True}
    assert called == [(OP, 'lab')]
def test_guest_b12_guard_dispatch_never_kills_heavy_parent(monkeypatch):
    from pathlib import Path
    from ops.pi import resources
    from ops.pi.lab import build_lab
    owner, _, _ = proof()
    calls, writes = [], []
    monkeypatch.setattr(build_lab, 'cancel_b12_watch', lambda value: calls.append(value) or {'owned_empty': True}, raising=False)
    monkeypatch.setattr(Path, 'write_text', lambda *args: writes.append(args))
    resources._cancel_watched(owner)
    assert calls == [owner] and writes == []

def unknown_pull():
    from ops.pi.lab.build_lab import BUILDKIT_IMAGE
    owner, manifest, actual = proof()
    intent = {'kind': 'image-pull', 'operation_id': OP, 'source_hash': 'a' * 64,
              'image': BUILDKIT_IMAGE, 'input': BUILDKIT_IMAGE, 'status': 'unknown'}
    owner['pending_image'] = intent
    manifest.update(source_hash='a' * 64, daemon_intents=[intent], unknown_daemon_effects=True)
    actual['unknown_daemon_effects'] = True
    return owner, manifest, actual


def test_unknown_fixed_pull_permits_only_owned_stop():
    owner, manifest, actual = unknown_pull()
    result = validate_cancellation(owner, manifest, actual)
    assert result['group_path'] == ROOT and result['daemon_terminal_verified'] is False
    assert result['owned_pids'] == [101, 102]


@pytest.mark.parametrize('fault', ['kind', 'image', 'input', 'operation', 'source', 'owner', 'multiple', 'status'])
def test_unknown_image_boolean_cannot_substitute_exact_durable_intent(fault):
    owner, manifest, actual = unknown_pull()
    intent = dict(manifest['daemon_intents'][0])
    if fault == 'kind': intent['kind'] = 'container-create'
    if fault == 'image': intent['image'] = 'arbitrary@sha256:' + 'b' * 64
    if fault == 'input': intent['input'] = 'candidate-selected'
    if fault == 'operation': intent['operation_id'] = 'changed'
    if fault == 'source': intent['source_hash'] = 'b' * 64
    if fault == 'owner': owner['pending_image'] = {}
    if fault == 'status': intent['status'] = 'done'
    manifest['daemon_intents'] = [intent, intent] if fault == 'multiple' else [intent]
    with pytest.raises(ValueError):
        validate_cancellation(owner, manifest, actual)


def test_unknown_pull_stop_retains_owner_and_fence(monkeypatch, tmp_path):
    from pathlib import Path
    from ops.pi.lab import build_lab, verify
    owner, manifest, actual = unknown_pull()
    (tmp_path / 'heavy.lock').write_text('')
    monkeypatch.setattr(build_lab, 'BASE', tmp_path)
    def trusted(path):
        if path.name == 'current-operation.json': return dict(owner)
        if path.name == 'creation.json': return manifest
        return {'lab_uuid': 'lab', 'containers': manifest['protected']}
    monkeypatch.setattr(build_lab, 'trusted_json', trusted)
    monkeypatch.setattr(build_lab, 'cancellation_state', lambda *args: actual)
    original_write = Path.write_text
    effects, updates = [], []
    monkeypatch.setattr(build_lab, '_fsync_directory', lambda path: effects.append('directory-persisted'), raising=False)
    def write(path, text, *args, **kwargs):
        if path.name == 'cgroup.kill': effects.append(path.as_posix()); return
        return original_write(path, text, *args, **kwargs)
    monkeypatch.setattr(Path, 'write_text', write)
    monkeypatch.setattr(build_lab, '_group_members', lambda *args: {})
    monkeypatch.setattr(build_lab, '_docker', lambda *args: [{'State': {'Running': False, 'Pid': 0}}])
    monkeypatch.setattr(build_lab, 'verify_runtime', lambda: {})
    monkeypatch.setattr(build_lab, '_write_b12_owner', lambda value: updates.append(value))
    result = build_lab.cancel_b12_owned(OP, 'lab')
    assert result['status'] == 'uncertain' and result['owned_empty'] is True
    assert result['daemon_terminal_verified'] is False
    assert effects == ['directory-persisted', '/sys/fs/cgroup' + ROOT + '/cgroup.kill']
    assert updates[-1]['status'] == 'uncertain' and updates[-1]['pending_image'] == owner['pending_image']
    fence = __import__('json').loads((tmp_path / 'heavy.lock.uncertain').read_text())
    assert fence['operation_id'] == OP and fence['pending_image'] == owner['pending_image']
    assert (tmp_path / 'heavy.lock').exists()

def runner_spec():
    return {'operation_id': OP, 'lab_uuid': 'lab', 'daemon_id': '364e8400-3844-47e2-b86d-8b626332f61c',
        'kind': 'runner-userns', 'image': 'sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1',
        'source_hash': 'a' * 64, 'source_files': {'ops/pi/lab/build_lab.py': 'b' * 64},
        'deadline': '2099-01-01T00:00:00+00:00', 'planned_peak_bytes': 1024**3,
        'tool_seconds': 120, 'protocol_inventory_sha256':'d'*64}


@pytest.mark.parametrize('fault', ['operation', 'lab', 'daemon', 'kind', 'image', 'source', 'deadline', 'peak', 'budget', 'extra', 'inventory'])
def test_probe_rejects_changed_frozen_identity_or_authority(fault):
    from ops.pi.lab import build_lab
    spec = runner_spec()
    if fault == 'operation': spec['operation_id'] = '22222222-2222-4222-8222-222222222222'
    if fault == 'lab': spec['lab_uuid'] = 'foreign'
    if fault == 'daemon': spec['daemon_id'] = 'foreign'
    if fault == 'kind': spec['kind'] = 'shell'
    if fault == 'image': spec['image'] = 'python:latest'
    if fault == 'source': spec['source_hash'] = 'c' * 64
    if fault == 'deadline': spec['deadline'] = '2000-01-01T00:00:00+00:00'
    if fault == 'peak': spec['planned_peak_bytes'] = 0
    if fault == 'budget': spec['tool_seconds'] = 121
    if fault == 'inventory': spec['protocol_inventory_sha256']='not-a-hash'
    if fault == 'extra': spec['seccomp'] = 'unconfined'
    with pytest.raises(ValueError):
        build_lab.validate_probe(spec, OP, {'lab_uuid': 'lab', 'daemon_id': spec['daemon_id']}, 'a' * 64)


def test_probe_accepts_only_fixed_no_candidate_capability_route():
    from ops.pi.lab import build_lab
    admitted = build_lab.validate_probe(runner_spec(), OP,
        {'lab_uuid': 'lab', 'daemon_id': '364e8400-3844-47e2-b86d-8b626332f61c'}, 'a' * 64)
    assert admitted['kind'] == 'runner-userns' and admitted['tool_seconds'] == 120

def test_directory_persistence_failure_prevents_kernel_stop(monkeypatch, tmp_path):
    from pathlib import Path
    from ops.pi.lab import build_lab
    owner, manifest, actual = unknown_pull()
    monkeypatch.setattr(build_lab, 'BASE', tmp_path)
    monkeypatch.setattr(build_lab, 'trusted_json', lambda path: owner if path.name == 'current-operation.json' else manifest if path.name == 'creation.json' else {'lab_uuid': 'lab', 'containers': manifest['protected']})
    monkeypatch.setattr(build_lab, 'cancellation_state', lambda *args: actual)
    def failed_directory(path): raise OSError('directory persistence failed')
    monkeypatch.setattr(build_lab, '_fsync_directory', failed_directory, raising=False)
    effects = []
    monkeypatch.setattr(Path, 'write_text', lambda *args: effects.append(args))
    with pytest.raises(OSError): build_lab.cancel_b12_owned(OP, 'lab')
    assert effects == []


def test_completion_never_overwrites_uncertain_owner_or_releases_fence(monkeypatch, tmp_path):
    from ops.pi.lab import build_lab, verify
    owner, _, _ = unknown_pull()
    owner['status'] = 'uncertain'
    fence = tmp_path / 'heavy.lock.uncertain'
    fence.write_text('persistent unknown')
    monkeypatch.setattr(build_lab, 'BASE', tmp_path)
    monkeypatch.setattr(build_lab, 'trusted_json', lambda path: dict(owner))
    updates = []
    monkeypatch.setattr(build_lab, '_write_b12_owner', lambda value: updates.append(value))
    result = build_lab.finish_b12_owner(OP, True)
    assert result['status'] == 'uncertain' and result['daemon_terminal_verified'] is False
    assert updates == [] and fence.read_text() == 'persistent unknown'

def namespace_proof():
    host = {key: 'host-' + key for key in ('mnt', 'pid', 'net', 'user')}
    parent = {'pid': 101, 'children': [103], 'start': '100', 'program_hash': 'a' * 64}
    child = {'pid': 103, 'parent': 101, 'start': '101', 'cgroup': ROOT + '/docker-' + ID + '.scope',
        'namespaces': {key: 'isolated-' + key for key in host},
        'uid_map': '0 65534 1', 'gid_map': '0 65534 1', 'uid': [65534] * 4,
        'no_new_privileges': '1', 'cap_eff': '0000000000000000', 'program_hash': 'a' * 64}
    return host, parent, child


@pytest.mark.parametrize('fault', ['missing_child', 'parent', 'program', 'cgroup', 'userns', 'mount', 'pid', 'net', 'uid_map', 'gid_map', 'uid', 'nnp', 'caps'])
def test_runner_actual_child_namespace_and_authority_are_required(fault):
    from ops.pi.lab import build_lab
    host, parent, child = namespace_proof()
    if fault == 'missing_child': parent['children'] = []
    if fault == 'parent': child['parent'] = 999
    if fault == 'program': child['program_hash'] = 'b' * 64
    if fault == 'cgroup': child['cgroup'] = '/host'
    if fault == 'userns': child['namespaces']['user'] = host['user']
    if fault in ('mount', 'pid', 'net'):
        key = 'mnt' if fault == 'mount' else fault
        child['namespaces'][key] = host[key]
    if fault == 'uid_map': child['uid_map'] = '0 0 4294967295'
    if fault == 'gid_map': child['gid_map'] = '0 0 4294967295'
    if fault == 'uid': child['uid'] = [0] * 4
    if fault == 'nnp': child['no_new_privileges'] = '0'
    if fault == 'caps': child['cap_eff'] = '00000000ffffffff'
    with pytest.raises(ValueError):
        build_lab.validate_runner_process(parent, child, host, ROOT + '/docker-' + ID + '.scope', 'a' * 64)


def test_runner_qualifies_actual_namespace_child_not_entrypoint_only():
    from ops.pi.lab import build_lab
    host, parent, child = namespace_proof()
    result = build_lab.validate_runner_process(parent, child, host, ROOT + '/docker-' + ID + '.scope', 'a' * 64)
    assert result['candidate_pid'] == 103 and result['candidate_start'] == '101'
    assert result['uid_map'] == '0 65534 1'


def test_fixed_runner_argv_never_adds_privilege_source_or_host_socket():
    from ops.pi.lab import build_lab
    argv = build_lab.runner_probe_arguments(OP, 'lab')
    assert '--pull' in argv and argv[argv.index('--pull')+1]=='never'
    assert argv[argv.index('--user') + 1] == '65534:65534'
    assert argv[argv.index('--network') + 1] == 'none'
    assert argv[argv.index('--security-opt') + 1] == 'no-new-privileges'
    assert '--read-only' in argv and '--privileged' not in argv
    assert '--mount' not in argv and '--volume' not in argv and '-v' not in argv
    assert '--cap-add' not in argv and 'seccomp=unconfined' not in argv
    assert argv[-4] == build_lab.RUNNER_IMAGE and argv[-3:-1] == ['python', '-c']
    assert 'unshare(0x10000000)' in argv[-1]
    assert 'PI_LAB_ENV' not in argv and 'DOCKER_HOST' not in argv

def test_probe_source_drift_refuses_before_creation_or_systemd_effects(monkeypatch, tmp_path):
    import hashlib, json
    from ops.pi.lab import build_lab
    source = tmp_path / 'trusted-source'
    (source / 'ops/pi/lab').mkdir(parents=True)
    file = source / 'ops/pi/lab/build_lab.py'
    file.write_bytes(b'new bytes')
    spec = runner_spec()
    spec['source_files'] = {'ops/pi/lab/build_lab.py': hashlib.sha256(b'old bytes').hexdigest()}
    spec['source_hash'] = hashlib.sha256(json.dumps(spec['source_files'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    monkeypatch.setattr(build_lab, 'BASE', tmp_path)
    monkeypatch.setattr(build_lab, 'trusted_json', lambda path: spec)
    monkeypatch.setattr(build_lab, 'verify_runtime', lambda: {'lab_uuid': 'lab', 'daemon_id': build_lab.DAEMON_ID})
    effects = []
    monkeypatch.setattr(build_lab, '_systemctl', lambda *args: effects.append(args))
    monkeypatch.setattr(build_lab, '_docker', lambda *args: effects.append(args))
    with pytest.raises(ValueError, match='frozen_source_drift'):
        build_lab.probe_admission(OP)
    assert effects == [] and not (tmp_path / 'b12' / OP).exists()

def test_completion_with_pending_container_persists_uncertainty(monkeypatch, tmp_path):
    from ops.pi.lab import build_lab, verify
    owner, manifest, _ = proof()
    manifest['objects'][0]['status'] = 'intent'
    monkeypatch.setattr(build_lab, 'BASE', tmp_path)
    monkeypatch.setattr(build_lab, 'trusted_json', lambda path: owner if path.name == 'current-operation.json' else manifest)
    writes, updates = [], []
    monkeypatch.setattr(build_lab, '_durable_json', lambda path, value, **kwargs: writes.append((path.name, value)))
    monkeypatch.setattr(build_lab, '_write_b12_owner', lambda value: updates.append(value))
    result = build_lab.finish_b12_owner(OP, True)
    assert result['status'] == 'uncertain' and result['daemon_terminal_verified'] is False
    assert writes[0][0] == 'heavy.lock.uncertain' and updates[-1]['status'] == 'uncertain'


def test_completion_empty_group_does_not_substitute_owned_docker_terminal(monkeypatch, tmp_path):
    from ops.pi.lab import build_lab, verify
    owner, manifest, _ = proof()
    monkeypatch.setattr(build_lab, 'BASE', tmp_path)
    monkeypatch.setattr(build_lab, 'trusted_json', lambda path: owner if path.name == 'current-operation.json' else manifest)
    monkeypatch.setattr(build_lab, '_docker', lambda *args: [{'State': {'Running': True, 'Pid': 123}}])
    updates = []
    monkeypatch.setattr(build_lab, '_write_b12_owner', lambda value: updates.append(value))
    with pytest.raises(ValueError): build_lab.finish_b12_owner(OP, True)
    assert updates == []