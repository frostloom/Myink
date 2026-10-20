"""Finite native B12 infrastructure, independently trusted from candidate source.

Admission is root-owned and SHA-bound. Docker/test/build instructions are fixed
here; no shell, SQL, URL, image or path arrives from the candidate interpreter.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
import uuid

from ops.pi.build import BUILD_LIMITS, DIGEST, admission
from ops.pi.checks import CHECKS, run_checks
from ops.pi.contracts import Receipt
from ops.pi.executor import DAEMON_ID, EXCLUDED, safe_source
from ops.pi.ledger import Ledger
from ops.pi.resources import sample_resources, verify_limits
from ops.pi.lab.verify import BASE, _configuration, _docker, verify_runtime

BUILDKIT_IMAGE = 'moby/buildkit@sha256:d947144c3dc4f827f8dacaaf98d622f0143465740075fa9790991bc381761dc9'
DEPENDENCY_FILES = ('Dockerfile', 'caddy/Dockerfile', 'pyproject.toml', 'docker/constraints.txt',
                    'web/package.json', 'web/package-lock.json', '.dockerignore')
PRIVATE = Path('/mnt/e/tools/myink-pi')
FORBIDDEN_ENV = {'PI_LAB_ENV', 'DOCKER_HOST', 'DOCKER_CONFIG', 'PLATFORM_MODEL_API_KEY',
                 'PLATFORM_MODEL_BASE_URL', 'PLATFORM_MODEL_NAME', 'PLATFORM_MODEL_PROTOCOL'}
ROLE_SQL = """
CREATE ROLE myink_app LOGIN PASSWORD 'synthetic-b12-only' NOSUPERUSER NOBYPASSRLS;
GRANT CONNECT ON DATABASE myink TO myink_app;
GRANT CREATE ON SCHEMA public TO myink_app;
ALTER DEFAULT PRIVILEGES FOR ROLE myink IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO myink_app;
ALTER DEFAULT PRIVILEGES FOR ROLE myink IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO myink_app;
CREATE ROLE myink_report LOGIN PASSWORD 'synthetic-b12-only' NOSUPERUSER BYPASSRLS;
GRANT CONNECT ON DATABASE myink TO myink_report;
GRANT USAGE ON SCHEMA public TO myink_report;
ALTER DEFAULT PRIVILEGES FOR ROLE myink IN SCHEMA public GRANT SELECT ON TABLES TO myink_report;
ALTER ROLE myink_report SET default_transaction_read_only = on;
"""


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_source(root, files):
    """Exactly ordinary frozen files; private material cannot enter a build context."""
    root = Path(root)
    if root.is_symlink() or not files:
        raise ValueError('source_manifest_missing')
    for name, expected in files.items():
        parts = Path(name).parts
        if (not parts or any(p in EXCLUDED or p.startswith('.env') for p in parts)
                or name.endswith(('.key', '.pem', '.sqlite', '.sqlite-wal', '.sqlite-shm'))
                or not re.fullmatch('[0-9a-f]{64}', expected)):
            raise ValueError('private_or_unhashed_source')
        path = safe_source(root, name)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or digest(path) != expected:
            raise ValueError('frozen_source_drift')
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def trusted_json(path):
    info = path.lstat()
    if (path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != 0 or info.st_mode & 0o022):
        raise ValueError('untrusted_admission')
    return json.loads(path.read_text())


def owned_group(operation):
    return 'myinkpi-heavy-b12' + uuid.UUID(operation).hex + '.slice'


def verify_candidate_container(info, expected, operation, lab_uuid, group):
    config = info['HostConfig']
    env = dict(v.split('=', 1) for v in info['Config']['Env'])
    if (_configuration(info) != expected or info['Config']['User'] != '65534:65534'
            or info['Config']['Labels'].get('myink.pi.operation') != operation
            or info['Config']['Labels'].get('myink.pi.lab') != lab_uuid
            or not info['State']['Running'] or info['State']['Pid'] <= 0
            or config.get('Privileged') or config.get('PidMode') or config.get('IpcMode') == 'host'
            or config.get('Devices') or config.get('DeviceRequests')
            or config.get('CgroupParent') != group or config.get('CapDrop') != ['ALL']
            or not config.get('ReadonlyRootfs') or 'no-new-privileges' not in config.get('SecurityOpt', [])
            or set(env) & FORBIDDEN_ENV
            or any(m['Destination'] not in ('/work', '/artifacts') for m in info['Mounts'])):
        raise ValueError('candidate_sandbox_drift')
    pid = info['State']['Pid']
    membership = Path('/proc/' + str(pid) + '/cgroup').read_text()
    if ('/' + group + '/') not in membership:
        raise ValueError('candidate_outside_owned_cgroup')
    for namespace in ('mnt', 'pid', 'net', 'user'):

        if os.readlink('/proc/' + str(pid) + '/ns/' + namespace) == os.readlink('/proc/1/ns/' + namespace):
            raise ValueError('candidate_host_namespace')
    status = Path('/proc/' + str(pid) + '/status').read_text()
    uid = next(line for line in status.splitlines() if line.startswith('Uid:')).split()[1:]
    if any(value == '0' for value in uid):
        raise ValueError('candidate_host_root')


class NativeFacility:
    """An operation-only registry preserves authority even if a Docker call times out."""
    def __init__(self, spec, operation, phase, runtime, deadline):
        self.spec, self.operation, self.phase = spec, operation, phase
        self.runtime, self.deadline = runtime, deadline
        self.group = owned_group(operation)
        self.root = BASE / 'b12' / operation
        self.root.mkdir(mode=0o700)
        self.artifacts = self.root / 'artifacts'
        self.artifacts.mkdir(mode=0o700)
        self.work = self.root / 'work'
        self.work.mkdir(mode=0o700)
        self.created = []
        self.sequence = 0
        self.environment = {}
        self.before = verify_runtime()
        self.source = Path(spec['source_path'])
        self.source_hash = verify_source(self.source, spec['source_files'])
        if self.source_hash != spec['source_hash']:
            raise ValueError('source_hash_mismatch')
        self.registry_path = self.root / 'creation.json'
        self.save_registry()

    def save_registry(self):
        value = {'operation_id': self.operation, 'lab_uuid': self.runtime['lab_uuid'],
                 'daemon_id': DAEMON_ID, 'source_hash': self.source_hash, 'objects': self.created}
        temporary = self.root / '.creation.tmp'
        with temporary.open('w') as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o600)
        temporary.replace(self.registry_path)

    def remaining(self):
        budget = (self.deadline - datetime.now(timezone.utc)).total_seconds()
        if budget <= 0:
            raise TimeoutError('b12_deadline_expired')
        return budget

    def run(self, argv, name, input_data=None, cap=None, env=None):
        self.sequence += 1
        prefix = self.root / (str(self.sequence) + '-' + name)
        with prefix.with_suffix('.stdout').open('xb', buffering=0) as out, prefix.with_suffix('.stderr').open('xb', buffering=0) as err:
            result = subprocess.run(argv, input=input_data, stdout=out, stderr=err,
                timeout=min(self.remaining(), cap or self.remaining()), env=env, check=False)
        return result.returncode, prefix.with_suffix('.stdout'), prefix.with_suffix('.stderr')

    def docker(self, args, name, input_data=None, cap=120):
        rc, out, err = self.run(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', *args],
                                 name, input_data, cap)
        if rc:
            raise ValueError(name + '_failed')
        return out.read_text().strip()

    def create(self, kind, name, args):
        intent = {'kind': kind, 'name': name, 'args': args, 'status': 'intent',
                  'requested_at': datetime.now(timezone.utc).isoformat()}
        self.created.append(intent)
        self.save_registry()
        obj = self.docker(args, 'create-' + kind)
        info = _docker(kind, 'inspect', obj)[0]
        labels = info['Config']['Labels'] if kind == 'container' else info['Labels']
        if labels.get('myink.pi.operation') != self.operation or labels.get('myink.pi.lab') != self.runtime['lab_uuid']:
            raise ValueError('created_identity_mismatch')
        intent.update(id=info['Id'], status='created', frozen=_configuration(info) if kind == 'container' else info)
        self.save_registry()
        return info['Id']

    def labels(self):
        return ['--label', 'myink.pi.operation=' + self.operation,
                '--label', 'myink.pi.lab=' + self.runtime['lab_uuid']]

    def container(self, suffix, image, args, command):
        if not DIGEST.fullmatch(image) and image != BUILDKIT_IMAGE:
            raise ValueError('unpinned_image')
        name = 'myinkpi-b12-' + uuid.UUID(self.operation).hex + '-' + suffix
        container = self.create('container', name, ['create', '--name', name, *self.labels(),
            '--cgroup-parent', self.group, '--memory', '1536m', '--memory-swap', '1792m',
            '--cpus', '2', '--pids-limit', '512', '--restart', 'no', *args, image, *command])
        self.docker(['start', container], 'start-' + suffix)
        return container

    def receipt(self, status, **evidence):
        return Receipt(self.operation, status, {'candidate_sha': self.spec['candidate_sha'],
            'source_hash': self.source_hash, 'status': 'PASS' if status == 'done' else 'BLOCKED', **evidence})

    def verify(self):
        runtime = verify_runtime()
        if runtime['lab_uuid'] != self.runtime['lab_uuid']:
            raise ValueError('lab_identity_drift')
        proof = sample_resources('heavy')
        if not verify_limits(proof, 'heavy'):
            raise ValueError('heavy_limits_drift')
        for item in self.created:
            if item['status'] != 'created':
                raise ValueError('unknown_creation_outcome')
            current = _docker(item['kind'], 'inspect', item['id'])[0]
            frozen = _configuration(current) if item['kind'] == 'container' else current
            if frozen != item['frozen']:
                raise ValueError('owned_configuration_drift')
            if item['kind'] == 'container' and current['State']['Running']:
                cgroup = Path('/proc/' + str(current['State']['Pid']) + '/cgroup').read_text()
                if '/' + self.group + '/' not in cgroup:
                    raise ValueError('owned_process_outside_group')
        capacity = {key: shutil.disk_usage(path).free for key, path in [('host_free_bytes', '/mnt/e'), ('guest_free_bytes', '/')] }
        admission(self.spec['candidate_sha'], {**self.spec, **capacity, 'deadline': self.deadline,
                                             'artifact_dir': self.artifacts})
        verify_source(self.source, self.spec['source_files'])
        return proof

    def prepare_checks(self):
        runner_image = self.spec.get('runner_image')
        if not runner_image or not DIGEST.fullmatch(runner_image):
            return self.receipt('blocked', reason='checks_runner_image_unprepared')
        try:
            image = _docker('image', 'inspect', runner_image)[0]
        except subprocess.SubprocessError:
            return self.receipt('blocked', reason='checks_runner_image_missing')
        if image['Config'].get('Labels', {}).get('myink.b12.dependencies') != self.spec['dependency_hash']:
            return self.receipt('blocked', reason='checks_dependency_inventory_unverified')
        # All trusted dependency material is prepared before this candidate code runs.
        for name, sha in self.spec['source_files'].items():
            target = self.work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.source / name, target)
        for path in [self.work, self.artifacts, *self.work.rglob('*')]:
            os.chown(path, 65534, 65534)
        network = self.spec.get('fixture_network')
        # A precreated network is acceptable only with full current operation creation authority.
        if not network:
            return self.receipt('blocked', reason='checks_isolated_network_unprepared')
        return self.receipt('blocked', reason='checks_fresh_fixture_creation_required')

    def prepare_build(self):
        # No security exceptions or arbitrary dependency egress are implicit.
        if self.spec.get('builder_image') != BUILDKIT_IMAGE:
            return self.receipt('blocked', reason='buildkit_pinned_image_unprepared')
        try:
            _docker('image', 'inspect', BUILDKIT_IMAGE)
        except subprocess.SubprocessError:
            return self.receipt('blocked', reason='buildkit_pinned_image_missing')
        return self.receipt('blocked', reason='buildkit_process_sandbox_not_qualified')

    def cleanup(self):
        pending = [v for v in self.created if v['status'] != 'created']
        if pending:
            return self.receipt('uncertain', reason='creation_outcome_unconfirmed', objects=pending)
        # Retain failure objects/artifacts. Stop only exact fresh created IDs after full frozen comparison.
        for item in reversed(self.created):
            current = _docker(item['kind'], 'inspect', item['id'])[0]
            if (_configuration(current) if item['kind'] == 'container' else current) != item['frozen']:
                return self.receipt('uncertain', reason='cleanup_identity_drift')
            if item['kind'] == 'container':
                self.docker(['stop', '--time', '5', item['id']], 'stop-owned')
                stopped = _docker('inspect', item['id'])[0]
                if stopped['State']['Running'] or stopped['State']['Pid'] != 0:
                    return self.receipt('uncertain', reason='owned_exit_unconfirmed')
        self.verify()
        return self.receipt('done', owned_exit_verified=True, source_unchanged=True,
                            protected_images_unchanged=True)

    def __call__(self, action, request):
        if request['operation_id'] != self.operation or request['candidate_sha'] != self.spec['candidate_sha'] or request['source_hash'] != self.source_hash:
            raise ValueError('operation_binding_mismatch')
        if action == 'checks.prepare':
            return self.prepare_checks()
        if action == 'build.prepare':
            return self.prepare_build()
        if action in ('checks.cleanup', 'build.cleanup'):
            return self.cleanup()
        raise ValueError('b12_facility_not_prepared')


def run_native(phase):
    """Fixed initializer entry, never accepts a candidate command or initializer selection."""
    if phase not in ('checks', 'build') or os.getuid() != 0:
        raise ValueError('trusted_b12_entry_required')
    owner = trusted_json(BASE / 'current-operation.json')
    operation = str(uuid.UUID(owner['operation_id']))
    if owner['unit'] != 'myinkpi-test-' + operation or owner['status'] != 'active':
        raise ValueError('active_b12_owner_required')
    evidence = PRIVATE / 'evidence' / ('b12-' + operation)
    evidence.mkdir(mode=0o700)
    admission_path = BASE / 'b12-admission.json'
    if not admission_path.exists():
        result = Receipt(operation, 'blocked', {'status': 'BLOCKED', 'scope': 'b12_full_' + phase,
            'reason': 'b12_frozen_admission_unprepared', 'required': True, 'pass': False,
            'fail': False, 'skip': False, 'source_qualified': False, 'executed_checks': 0,
            'executed_images': 0, 'helper_completion_is_ci_pass': False})
    else:
        spec = trusted_json(admission_path)
        runtime = verify_runtime()
        if (spec['lab_uuid'] != runtime['lab_uuid'] or spec['daemon_id'] != DAEMON_ID
                or spec['distribution'] != 'MyinkPiLab'
                or set(DEPENDENCY_FILES) - set(spec['dependency_files'])
                or any(spec['source_files'].get(k) != v for k, v in spec['dependency_files'].items())):
            raise ValueError('b12_admission_identity_or_dependencies_invalid')
        source = Path(spec['source_path'])
        if source.parent != BASE / 'b12-source' or source.name != spec['candidate_sha']:
            raise ValueError('b12_source_path_invalid')
        deadline = datetime.fromisoformat(spec['deadline'])
        if not deadline.tzinfo:
            raise ValueError('b12_deadline_invalid')
        handler = NativeFacility(spec, operation, phase, runtime, deadline)
        lab = {**spec, 'deadline': deadline, 'artifact_dir': handler.artifacts,
               'lock_path': handler.root / 'workflow.lock', 'executor': handler}
        if phase == 'checks':
            receipts = run_checks(spec['candidate_sha'], lab, handler)
            result = Receipt(operation, 'done' if len(receipts) == len(CHECKS) and all(r.status == 'done' for r in receipts) else 'blocked',
                {'scope': 'b12_full_checks', 'checks': [asdict(r) for r in receipts],
                 'candidate_sha': spec['candidate_sha'], 'source_hash': spec['source_hash']})
        else:
            from ops.pi.build import build_images
            result = build_images(spec['candidate_sha'], lab, Ledger(handler.root / 'ledger.sqlite'))
    payload = asdict(result)
    with (evidence / 'native-receipt.json').open('x') as output:
        json.dump(payload, output, indent=2)
        output.flush()
        os.fsync(output.fileno())
    print(json.dumps({'operation_id': operation, 'status': result.status,
                      'receipt_path': str(evidence / 'native-receipt.json')}))
    return 0 if result.status == 'done' else 1
CHILD_LIMITS = {'memory.max': str(1024**3), 'memory.swap.max': str(256 * 1024**2),
                'cpu.max': '200000 100000'}


def validate_cancellation(owner, manifest, actual):
    """Pure authorization: reject every uncertainty before selecting a kill target."""
    try:
        operation = str(uuid.UUID(owner['operation_id']))
        group = owned_group(operation)
        unit = 'myinkpi-test-' + operation
        path = '/myinkpi.slice/myinkpi-heavy.slice/' + group
        if (owner['status'] != 'active' or owner['group'] != 'b12'
                or owner['child_group'] != group or owner['unit'] != unit
                or manifest['operation_id'] != operation or manifest['lab_uuid'] != owner['lab_uuid']
                or manifest['daemon_id'] != DAEMON_ID or manifest['unit'] != unit
                or manifest['child_group'] != group
                or actual['unit_active'] is not True or actual['unit_cgroup'] != path + '/' + unit + '.service'
                or actual['limits'] != CHILD_LIMITS or actual['ancestor_verified'] is not True
                or actual['parent_limits_verified'] is not True):
            raise ValueError('b12_cancel_authority_invalid')
        unknown = actual['unknown_daemon_effects']
        if unknown is not False:
            intents = manifest.get('daemon_intents', [])
            if unknown is not True or manifest.get('unknown_daemon_effects') is not True or len(intents) != 1:
                raise ValueError('b12_unknown_image_intent_missing')
            intent = intents[0]
            if (intent != owner.get('pending_image') or intent.get('operation_id') != operation
                    or intent.get('source_hash') != manifest.get('source_hash')
                    or not re.fullmatch('[0-9a-f]{64}', intent.get('source_hash', ''))
                    or intent.get('status') != 'unknown'):
                raise ValueError('b12_unknown_image_intent_unbound')
            if intent.get('kind') != 'image-pull' or intent.get('image') != BUILDKIT_IMAGE or intent.get('input') != BUILDKIT_IMAGE:
                raise ValueError('b12_unknown_image_operation_unapproved')
        if not manifest['protected'] or set(actual['protected']) != set(manifest['protected']):
            raise ValueError('b12_protected_inventory_invalid')
        for name, expected in manifest['protected'].items():
            protected = actual['protected'][name]
            if (protected['configuration'] != expected or protected['running'] is not True
                    or protected['pid'] <= 0
                    or actual['protected_members'][protected['pid']].startswith(path)):
                raise ValueError('b12_protected_identity_or_state_drift')
        containers = []
        allowed = [path + '/' + unit + '.service']
        for item in manifest['objects']:
            if item['status'] != 'created':
                raise ValueError('b12_unknown_creation')
            if item['kind'] != 'container':
                if actual['objects'].get(item['id']) != item['frozen']:
                    raise ValueError('b12_owned_object_drift')
                continue
            identifier = item['id']
            if not re.fullmatch('[0-9a-f]{64}', identifier):
                raise ValueError('b12_container_identity_invalid')
            container = actual['containers'][identifier]
            if (container['configuration'] != item['frozen'] or container['operation_id'] != operation
                    or container['lab_uuid'] != owner['lab_uuid']):
                raise ValueError('b12_owned_container_drift')
            branch = path + '/docker-' + identifier + '.scope'
            if container['running'] and (container['pid'] <= 0 or actual['members'].get(container['pid']) != branch):
                raise ValueError('b12_container_outside_owned_group')
            allowed.append(branch)
            containers.append(identifier)
        for pid, member in actual['members'].items():
            if pid <= 0 or not any(member == branch or member.startswith(branch + '/') for branch in allowed):
                raise ValueError('b12_foreign_or_escaped_member')
        result = {'group_path': path, 'container_ids': containers, 'owned_pids': sorted(actual['members'])}
        if unknown:
            result['daemon_terminal_verified'] = False
        return result
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('b12_cancel_proof_missing') from error


def _group_members(root):
    members = {}
    for file in root.rglob('cgroup.procs'):
        for value in file.read_text().split():
            pid = int(value)
            membership = Path('/proc/' + value + '/cgroup').read_text().strip()
            if not membership.startswith('0::'):
                raise ValueError('non_v2_member')
            members[pid] = membership.removeprefix('0::')
    return members


def object_configuration(kind, info):
    if kind == 'container':
        return {'runtime': _configuration(info), 'config': info['Config'], 'host_config': info['HostConfig']}
    if kind == 'network':
        return {key: info.get(key) for key in ('Id', 'Name', 'Driver', 'Scope', 'Internal',
            'Attachable', 'EnableIPv6', 'IPAM', 'Options', 'Labels')}
    raise ValueError('unknown_b12_object_kind')


def _systemctl(*args):
    return subprocess.check_output(['/usr/bin/systemctl', *args], text=True, timeout=10).strip()


def cancellation_state(owner, manifest):
    group = owned_group(owner['operation_id'])
    root = Path('/sys/fs/cgroup/myinkpi.slice/myinkpi-heavy.slice') / group
    parent = sample_resources('heavy')
    actual = {'unit_active': _systemctl('is-active', owner['unit']) == 'active',
        'unit_cgroup': _systemctl('show', owner['unit'], '--property=ControlGroup', '--value'),
        'limits': {key: (root / key).read_text().strip() for key in CHILD_LIMITS},
        'ancestor_verified': root.parent.name == 'myinkpi-heavy.slice' and root.parent.parent.name == 'myinkpi.slice',
        'parent_limits_verified': verify_limits(parent, 'heavy'), 'members': _group_members(root),
        'containers': {}, 'objects': {}, 'protected': {}, 'protected_members': {},
        'unknown_daemon_effects': manifest.get('unknown_daemon_effects', True)}
    for item in manifest['objects']:
        if item['status'] != 'created':
            continue
        current = _docker(item['kind'], 'inspect', item['id'])[0]
        if item['kind'] == 'container':
            actual['containers'][item['id']] = {'configuration': object_configuration('container', current),
                'operation_id': current['Config']['Labels'].get('myink.pi.operation'),
                'lab_uuid': current['Config']['Labels'].get('myink.pi.lab'),
                'pid': current['State']['Pid'], 'running': current['State']['Running']}
        else:
            actual['objects'][item['id']] = object_configuration(item['kind'], current)
    for name in manifest['protected']:
        current = _docker('inspect', name)[0]
        pid = current['State']['Pid']
        actual['protected'][name] = {'configuration': _configuration(current), 'running': current['State']['Running'], 'pid': pid}
        if pid:
            actual['protected_members'][pid] = Path('/proc/' + str(pid) + '/cgroup').read_text().strip().removeprefix('0::')
    return actual


def cancel_b12_owned(operation, lab_uuid):
    """Caller holds ownership.lock; never kill the protected heavy ancestor."""
    owner = trusted_json(BASE / 'current-operation.json')
    if owner.get('operation_id') != operation or owner.get('lab_uuid') != lab_uuid:
        raise ValueError('b12_stale_cancel')
    manifest = trusted_json(BASE / 'b12' / operation / 'creation.json')
    frozen = trusted_json(BASE / 'runtime-manifest.json')
    if frozen['lab_uuid'] != lab_uuid or manifest['protected'] != frozen['containers']:
        raise ValueError('b12_protected_manifest_drift')
    actual = cancellation_state(owner, manifest)
    target = validate_cancellation(owner, manifest, actual)
    unknown = target.get('daemon_terminal_verified') is False
    if unknown:
        fence = BASE / 'heavy.lock.uncertain'
        payload = {'operation_id': operation, 'lab_uuid': lab_uuid, 'reason': 'image_daemon_terminal_unconfirmed',
                   'pending_image': owner['pending_image']}
        if fence.exists():
            if trusted_json(fence) != payload:
                raise ValueError('b12_foreign_uncertainty_fence')
        else:
            with fence.open('x') as output:
                fence.chmod(0o600)
                json.dump(payload, output)
                output.flush()
                os.fsync(output.fileno())
            _fsync_directory(BASE)
    # Re-read owner under caller's lock immediately before the sole kernel effect.
    if trusted_json(BASE / 'current-operation.json') != owner:
        raise ValueError('b12_owner_changed')
    root = Path('/sys/fs/cgroup') / target['group_path'].lstrip('/')
    (root / 'cgroup.kill').write_text('1')
    for _ in range(30):
        if not _group_members(root):
            break
        time.sleep(.1)
    if _group_members(root):
        raise ValueError('b12_owned_descendants_remain')
    for identifier in target['container_ids']:
        info = _docker('inspect', identifier)[0]
        if info['State']['Running'] or info['State']['Pid'] != 0:
            raise ValueError('b12_docker_terminal_unconfirmed')
    verify_runtime()
    _write_b12_owner({**owner, 'status': 'uncertain' if unknown else 'cancelled'})
    return {'status': 'uncertain' if unknown else 'done', 'operation_id': operation, 'lab_uuid': lab_uuid,
            'owned_empty': True, 'protected_runtime_unchanged': True,
            'group_path': target['group_path'], 'daemon_terminal_verified': not unknown}
def cancel_b12_watch(ownership):
    """Watcher takes the same ownership lock as host cancellation/start/completion."""
    import fcntl
    lock = BASE / 'ownership.lock'
    if lock.is_symlink():
        raise ValueError('b12_ownership_lock_link')
    with lock.open('a') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        if trusted_json(BASE / 'current-operation.json') != ownership:
            raise ValueError('b12_watch_owner_changed')
        return cancel_b12_owned(ownership['operation_id'], ownership['lab_uuid'])
RUNNER_IMAGE = 'sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1'
PROBE_FIELDS = {'operation_id', 'lab_uuid', 'daemon_id', 'kind', 'image', 'source_hash',
                'source_files', 'deadline', 'planned_peak_bytes', 'tool_seconds', 'protocol_inventory_sha256'}


def validate_probe(spec, operation, runtime, source_hash):
    if (set(spec) != PROBE_FIELDS or spec['operation_id'] != str(uuid.UUID(operation))
            or spec['lab_uuid'] != runtime['lab_uuid'] or spec['daemon_id'] != DAEMON_ID
            or runtime['daemon_id'] != DAEMON_ID or spec['kind'] != 'runner-userns'
            or spec['image'] != RUNNER_IMAGE or spec['source_hash'] != source_hash
            or not re.fullmatch('[0-9a-f]{64}', source_hash)
            or not isinstance(spec['protocol_inventory_sha256'],str)
            or not re.fullmatch('[0-9a-f]{64}', spec['protocol_inventory_sha256'])
            or type(spec['planned_peak_bytes']) is not int or spec['planned_peak_bytes'] != 1024**3
            or type(spec['tool_seconds']) is not int or spec['tool_seconds'] != 120):
        raise ValueError('b12_probe_spec_unapproved')
    deadline = datetime.fromisoformat(spec['deadline'])
    if deadline.tzinfo is None or deadline <= datetime.now(timezone.utc):
        raise ValueError('b12_probe_deadline_expired')
    return spec

def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def finish_b12_owner(operation, owned_empty):
    """Caller holds ownership.lock; unit exit never resolves daemon uncertainty."""
    owner = trusted_json(BASE / 'current-operation.json')
    if owner.get('operation_id') != operation or owner.get('group') != 'b12':
        raise ValueError('b12_completion_owner_changed')
    if owner.get('status') == 'uncertain' or (BASE / 'heavy.lock.uncertain').exists():
        return {'status': 'uncertain', 'daemon_terminal_verified': False}
    if owned_empty is not True:
        raise ValueError('b12_completion_descendants_remain')
    manifest = trusted_json(BASE / 'b12' / operation / 'creation.json')
    if (manifest['operation_id'] != operation or manifest['lab_uuid'] != owner['lab_uuid']
            or manifest['daemon_id'] != DAEMON_ID or manifest['child_group'] != owner['child_group']
            or manifest['unit'] != owner['unit']):
        raise ValueError('b12_completion_manifest_changed')
    if manifest.get('unknown_daemon_effects', False) or any(item['status'] != 'created' for item in manifest['objects']):
        _durable_json(BASE / 'heavy.lock.uncertain', {'operation_id': operation, 'reason': 'creation_terminal_unconfirmed'}, exclusive=True)
        _write_b12_owner({**owner, 'status': 'uncertain'})
        return {'status': 'uncertain', 'daemon_terminal_verified': False}
    for item in manifest['objects']:
        current = _docker(item['kind'], 'inspect', item['id'])[0]
        if item['kind'] == 'container' and (current['State']['Running'] or current['State']['Pid'] != 0):
            raise ValueError('b12_completion_docker_terminal_unconfirmed')
        if object_configuration(item['kind'], current) != item['frozen']:
            raise ValueError('b12_completion_object_drift')
    if owner['status'] == 'active':
        _write_b12_owner({**owner, 'status': 'completed'})
    return {'status': 'done', 'owned_empty': True, 'daemon_terminal_verified': True}


RUNNER_PROGRAM = """import ctypes,json,os,pathlib,time
libc=ctypes.CDLL(None,use_errno=True)
if libc.unshare(0x10000000):
    print(json.dumps({'status':'BLOCKED','reason':'runner_default_userns_denied','errno':ctypes.get_errno()}),flush=True)
    raise SystemExit(78)
pathlib.Path('/proc/self/uid_map').write_text('0 65534 1')
pathlib.Path('/proc/self/setgroups').write_text('deny')
pathlib.Path('/proc/self/gid_map').write_text('0 65534 1')
class Header(ctypes.Structure): _fields_=[('version',ctypes.c_uint32),('pid',ctypes.c_int)]
class Data(ctypes.Structure): _fields_=[('effective',ctypes.c_uint32),('permitted',ctypes.c_uint32),('inheritable',ctypes.c_uint32)]
header=Header(0x20080522,0); data=(Data*2)()
if libc.capset(ctypes.byref(header),ctypes.byref(data)): raise OSError(ctypes.get_errno(),'capset')
child=os.fork()
if child==0:
    print(json.dumps({'status':'CAPABILITY_CHILD','pid':os.getpid()}),flush=True)
    time.sleep(60)
    os._exit(0)
os.waitpid(child,0)
"""


def validate_runner_process(parent, child, host, group_path, program_hash):
    try:
        if (parent['children'] != [child['pid']] or child['parent'] != parent['pid']
                or not parent['start'] or not child['start'] or child['cgroup'] != group_path
                or parent['program_hash'] != program_hash or child['program_hash'] != program_hash
                or child['uid_map'] != '0 65534 1' or child['gid_map'] != '0 65534 1'
                or child['uid'] != [65534] * 4 or child['no_new_privileges'] != '1'
                or child['cap_eff'] != '0000000000000000'
                or any(child['namespaces'][key] == host[key] for key in ('mnt', 'pid', 'net', 'user'))):
            raise ValueError('b12_runner_child_authority_invalid')
    except (KeyError, TypeError) as error:
        raise ValueError('b12_runner_child_proof_missing') from error
    return {'candidate_pid': child['pid'], 'candidate_start': child['start'],
            'uid_map': child['uid_map'], 'gid_map': child['gid_map'], 'namespaces': child['namespaces']}


def runner_probe_arguments(operation, lab_uuid):
    return ['create', '--pull', 'never', '--name', 'myinkpi-b12-' + uuid.UUID(operation).hex + '-userns',
        '--label', 'myink.pi.operation=' + operation, '--label', 'myink.pi.lab=' + lab_uuid,
        '--user', '65534:65534', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--read-only', '--network', 'none', '--cgroup-parent', owned_group(operation),
        '--memory', '1536m', '--memory-swap', '1792m', '--cpus', '2', '--pids-limit', '32',
        '--restart', 'no', '--entrypoint', '', RUNNER_IMAGE, 'python', '-c', RUNNER_PROGRAM]
def probe_admission(operation):
    operation = str(uuid.UUID(operation))
    spec = trusted_json(BASE / 'b12-probe' / (operation + '.json'))
    runtime = verify_runtime()
    source = BASE / 'trusted-source'
    source_hash = verify_source(source, spec['source_files'])
    validate_probe(spec, operation, runtime, source_hash)
    for name in spec['source_files']:
        info = (source / name).stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('untrusted_probe_source')
    probe_health_inventory(operation, spec)
    return spec, runtime

def probe_health_inventory(operation, spec):
    path=BASE/'b12-probe'/(operation+'.health.json')
    if digest(path)!=spec['protocol_inventory_sha256']:
        raise ValueError('b12_protocol_inventory_hash_drift')
    inventory=trusted_json(path)
    if (inventory['operation_id']!=operation or inventory['lab_uuid']!=spec['lab_uuid']
            or inventory['daemon_id']!=spec['daemon_id']):
        raise ValueError('b12_protocol_inventory_identity_drift')
    return inventory

def _durable_json(path, value, exclusive=False):
    temporary = path if exclusive else path.with_name('.' + path.name + '.tmp')
    with temporary.open('x' if exclusive else 'w') as output:
        temporary.chmod(0o600)
        json.dump(value, output, indent=2)
        output.flush()
        os.fsync(output.fileno())
    if not exclusive:
        temporary.replace(path)
    _fsync_directory(path.parent)


def _probe_filesystem():
    path = PRIVATE / 'evidence/b11-fix2-filesystem.json'
    if digest(path) != 'c6492fd2588f08556041deb7f49aa9bf65fc2cad4fa0d6b7059bf3e8ff87352a':
        raise ValueError('b12_native_filesystem_proof_drift')
    proof = json.loads(path.read_text())
    line = next(row for row in Path('/proc/self/mountinfo').read_text().splitlines() if row.split()[4] == '/')
    left, right = line.split(' - ', 1)
    fields = right.split()
    actual = {'major_minor': left.split()[2], 'fs_type': fields[0], 'source': fields[1]}
    if proof['distribution'] != 'MyinkPiLab' or not proof['base_path'].lower().startswith('e:') or actual != proof['root_filesystem']:
        raise ValueError('b12_native_filesystem_unowned')
    return proof


def _probe_group(operation):
    return Path('/sys/fs/cgroup/myinkpi.slice/myinkpi-heavy.slice') / owned_group(operation)


def _process_proof(pid):
    root = Path('/proc/' + str(pid))
    status = dict(line.split(':', 1) for line in (root / 'status').read_text().splitlines() if ':' in line)
    command = (root / 'cmdline').read_bytes().split(b'\0')
    if command[:2] != [b'python', b'-c'] or command[2].decode() != RUNNER_PROGRAM:
        raise ValueError('b12_probe_process_program_drift')
    result = {'pid': pid, 'parent': int(status['PPid']),
        'start': (root / 'stat').read_text().rsplit(')', 1)[1].split()[19],
        'children': [int(value) for value in (root / 'task' / str(pid) / 'children').read_text().split()],
        'cgroup': (root / 'cgroup').read_text().strip().removeprefix('0::'),
        'namespaces': {key: os.readlink(root / 'ns' / key) for key in ('mnt', 'pid', 'net', 'user')},
        'uid_map': ' '.join((root / 'uid_map').read_text().split()),
        'gid_map': ' '.join((root / 'gid_map').read_text().split()),
        'uid': [int(value) for value in status['Uid'].split()], 'no_new_privileges': status['NoNewPrivs'].strip(),
        'cap_eff': status['CapEff'].strip(), 'program_hash': hashlib.sha256(command[2]).hexdigest()}
    return result


def _runner_configuration(info, operation, lab_uuid):
    host = info['HostConfig']
    if (info['Image'] != RUNNER_IMAGE or info['Config']['User'] != '65534:65534'
            or info['Config']['Cmd'] != ['python', '-c', RUNNER_PROGRAM]
            or info['Config']['Entrypoint'] not in ([], None)
            or info['Config']['Labels'].get('myink.pi.operation') != operation
            or info['Config']['Labels'].get('myink.pi.lab') != lab_uuid
            or info['Mounts'] or host['NetworkMode'] != 'none' or host['Privileged']
            or host.get('CapAdd') or host['CapDrop'] != ['ALL']
            or host['SecurityOpt'] != ['no-new-privileges'] or not host['ReadonlyRootfs']
            or host['PidMode'] or host['IpcMode'] == 'host' or host.get('Devices') or host.get('DeviceRequests')
            or host['CgroupParent'] != owned_group(operation) or host['Memory'] != 1536 * 1024**2
            or host['MemorySwap'] != 1792 * 1024**2 or host['NanoCpus'] != 2000000000
            or host['PidsLimit'] != 32 or host['RestartPolicy']['Name'] != 'no'):
        raise ValueError('b12_runner_configuration_invalid')
    return object_configuration('container', info)


def run_runner_probe(operation):
    """Inside the new child unit; executes fixed capability code, no candidate code."""
    spec, runtime = probe_admission(operation)
    owner = trusted_json(BASE / 'current-operation.json')
    manifest_path = BASE / 'b12' / operation / 'creation.json'
    manifest = trusted_json(manifest_path)
    root = manifest_path.parent
    unit_path = '/myinkpi.slice/myinkpi-heavy.slice/' + owned_group(operation) + '/myinkpi-test-' + operation + '.service'
    if (owner['operation_id'] != operation or owner['status'] != 'active' or owner['group'] != 'b12'
            or Path('/proc/self/cgroup').read_text().strip() != '0::' + unit_path
            or manifest['source_hash'] != spec['source_hash']
            or {key: (_probe_group(operation) / key).read_text().strip() for key in CHILD_LIMITS} != CHILD_LIMITS):
        raise ValueError('b12_probe_current_unit_invalid')
    deadline = datetime.fromisoformat(manifest['execution_deadline'])
    sequence = 0
    def docker(args, name, cleanup=False):
        nonlocal sequence
        sequence += 1
        cap = min(120, (deadline - datetime.now(timezone.utc)).total_seconds())
        if cleanup:
            cap = 15
        if cap <= 0:
            raise TimeoutError('b12_probe_deadline_expired')
        prefix = root / (str(sequence) + '-' + name)
        with prefix.with_suffix('.stdout').open('xb', buffering=0) as out, prefix.with_suffix('.stderr').open('xb', buffering=0) as err:
            result = subprocess.run(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', *args],
                stdout=out, stderr=err, timeout=cap, check=False)
        if result.returncode:
            raise ValueError(name + '_failed')
        return prefix.with_suffix('.stdout').read_text().strip()
    receipt = {'operation_id': operation, 'status': 'blocked', 'evidence': {
        'scope': 'b12_runner_userns_capability', 'status': 'BLOCKED', 'lab_uuid': runtime['lab_uuid'],
        'daemon_id': DAEMON_ID, 'source_hash': spec['source_hash'], 'candidate_execution': False,
        'executed_checks': 0, 'executed_images': 0, 'helper_completion_is_ci_pass': False,
        'configured_container_limits': BUILD_LIMITS, 'effective_child_limits': CHILD_LIMITS}}
    item = {'kind': 'container', 'status': 'intent', 'operation_id': operation,
        'name': 'myinkpi-b12-' + uuid.UUID(operation).hex + '-userns'}
    manifest['objects'].append(item)
    _durable_json(manifest_path, manifest)
    try:
        identifier = docker(runner_probe_arguments(operation, runtime['lab_uuid']), 'create-runner')
        info = _docker('inspect', identifier)[0]
        configuration = _runner_configuration(info, operation, runtime['lab_uuid'])
        item.update(id=info['Id'], frozen=configuration, status='created')
        _durable_json(manifest_path, manifest)
        docker(['start', identifier], 'start-runner')
        until = min(time.monotonic() + 5, time.monotonic() + (deadline - datetime.now(timezone.utc)).total_seconds())
        while time.monotonic() < until:
            info = _docker('inspect', identifier)[0]
            if _runner_configuration(info, operation, runtime['lab_uuid']) != configuration:
                raise ValueError('b12_runner_start_drift')
            if not info['State']['Running']:
                logs = docker(['logs', identifier], 'runner-logs')
                receipt['evidence'].update(reason='runner_default_userns_denied' if 'runner_default_userns_denied' in logs else 'runner_capability_process_failed',
                    container_exitcode=info['State']['ExitCode'], logs_sha256=hashlib.sha256(logs.encode()).hexdigest())
                break
            parent = _process_proof(info['State']['Pid'])
            if len(parent['children']) == 1:
                child = _process_proof(parent['children'][0])
                host = {key: os.readlink('/proc/1/ns/' + key) for key in ('mnt', 'pid', 'net', 'user')}
                mapping = validate_runner_process(parent, child, host, unit_path.rsplit('/', 1)[0] + '/docker-' + identifier + '.scope', hashlib.sha256(RUNNER_PROGRAM.encode()).hexdigest())
                if _process_proof(child['pid']) != child or _process_proof(parent['pid']) != parent:
                    raise ValueError('b12_probe_process_race')
                receipt['status'] = 'done'
                receipt['evidence'].update(status='PASS', namespace_proof=mapping, reason='runner_default_userns_qualified')
                break
            time.sleep(.1)
        else:
            receipt['evidence']['reason'] = 'runner_capability_child_missing'
    except (ValueError, OSError, TimeoutError, subprocess.SubprocessError) as error:
        receipt['evidence'].update(reason=str(error), error_type=type(error).__name__)
    finally:
        if item['status'] == 'created':
            current = _docker('inspect', item['id'])[0]
            if _runner_configuration(current, operation, runtime['lab_uuid']) != item['frozen']:
                raise ValueError('b12_probe_cleanup_configuration_drift')
            docker(['stop', '--time', '2', item['id']], 'stop-owned-runner', cleanup=True)
            stopped = _docker('inspect', item['id'])[0]
            if stopped['State']['Running'] or stopped['State']['Pid'] != 0:
                raise ValueError('b12_probe_runner_terminal_unconfirmed')
            receipt['evidence']['owned_objects_terminal'] = True
        else:
            receipt['status'] = 'uncertain'
            receipt['evidence'].update(status='BLOCKED', reason='runner_creation_terminal_unconfirmed')
            _durable_json(BASE / 'heavy.lock.uncertain', {'operation_id': operation, 'reason': receipt['evidence']['reason']}, exclusive=True)
        verify_runtime()
        verify_source(BASE / 'trusted-source', spec['source_files'])
        receipt['evidence']['protected_runtime_unchanged'] = True
        _durable_json(root / 'native-attempt.json', receipt, exclusive=True)
    return 0 if receipt['status'] == 'done' else 78


SYSTEMD_RUNTIME = Path('/run/systemd/system')


def health_targets(runtime, frozen, actual, inventory):
    """Only the hash-bound root-approved actual ports grant protocol authority."""
    names = runtime['test_containers'] + runtime['maintenance_containers']
    protocols = [('postgres', '5432/tcp'), ('redis', '6379/tcp'), ('amqp', '5672/tcp')]
    if (set(inventory)!={'operation_id','lab_uuid','daemon_id','containers'}
            or inventory['lab_uuid']!=runtime['lab_uuid'] or inventory['daemon_id']!=runtime['daemon_id']
            or len(runtime['test_containers']) != 3 or len(runtime['maintenance_containers']) != 4
            or len(set(names)) != 7 or set(inventory['containers'])!=set(names) or set(actual)!=set(names)):
        raise ValueError('b12_health_exact_bound_seven_services_required')
    result = []
    for index, name in enumerate(names):
        protocol, port = protocols[index % 3] if index < 6 else ('http503', '8080/tcp')
        expected = frozen[name]
        bound=inventory['containers'][name]
        observed=actual[name]
        if (set(bound)!={'id','port_bindings','actual_ports'} or observed['configuration']!=expected
                or bound['id']!=expected['id'] or not re.fullmatch('[0-9a-f]{64}', expected['id'])
                or expected['host']['PortBindings']!=bound['port_bindings']
                or observed['actual_ports']!=bound['actual_ports']):
            raise ValueError('b12_health_frozen_identity_or_port_drift')
        requested=bound['port_bindings']
        if set(requested)!={port} or len(requested[port])!=1 or requested[port][0]['HostIp']!='127.0.0.1':
            raise ValueError('b12_health_fixed_requested_port_required')
        bindings=bound['actual_ports']
        if {key for key,value in bindings.items() if value is not None}!={port} or len(bindings[port])!=1:
            raise ValueError('b12_health_fixed_actual_port_required')
        address = bindings[port][0]
        if address['HostIp'] != '127.0.0.1' or not address['HostPort'].isdigit() or not 1 <= int(address['HostPort']) <= 65535:
            raise ValueError('b12_health_loopback_required')
        result.append({'name': name, 'id': expected['id'], 'protocol': protocol,
                       'host': '127.0.0.1', 'port': int(address['HostPort'])})
    return result


def protocol_health(target, seconds):
    """Unauthenticated server protocol availability; no business data assertion."""
    import socket
    import struct
    deadline = time.monotonic() + min(2, seconds)
    if seconds <= 0 or target['host'] != '127.0.0.1':
        raise ValueError('b12_health_budget_or_target_invalid')
    with socket.create_connection((target['host'], target['port']), timeout=min(2, seconds)) as wire:
        def receive(size):
            data = b''
            while len(data) < size:
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise TimeoutError('b12_health_protocol_deadline')
                wire.settimeout(remaining)
                part = wire.recv(size - len(data))
                if not part: raise ValueError('b12_health_protocol_closed')
                data += part
            return data
        protocol = target['protocol']
        if protocol == 'postgres':
            # Startup only: authentication challenge proves readiness; no password follows.
            payload = struct.pack('!I', 196608) + b'user\x00postgres\x00database\x00myink\x00\x00'
            wire.sendall(struct.pack('!I', len(payload) + 4) + payload)
            header = receive(5)
            size = struct.unpack('!I', header[1:])[0]
            if header[:1] != b'R' or not 8 <= size <= 4096:
                raise ValueError('b12_health_postgres_not_ready')
            auth = struct.unpack('!I', receive(size - 4)[:4])[0]
            if auth not in (0, 3, 5, 10): raise ValueError('b12_health_postgres_auth_protocol_invalid')
        elif protocol == 'redis':
            wire.sendall(b'*1\r\n$4\r\nPING\r\n')
            if receive(7) != b'+PONG\r\n': raise ValueError('b12_health_redis_not_ready')
        elif protocol == 'amqp':
            wire.sendall(b'AMQP\x00\x00\x09\x01')
            header = receive(7)
            size = struct.unpack('!I', header[3:])[0]
            if header[:3] != b'\x01\x00\x00' or not 4 <= size <= 65536:
                raise ValueError('b12_health_amqp_protocol_invalid')
            body = receive(size + 1)
            if body[:4] != b'\x00\x0a\x00\x0a' or body[-1:] != b'\xce':
                raise ValueError('b12_health_amqp_not_ready')
        elif protocol == 'http503':
            wire.sendall(b'GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
            line = b''
            while not line.endswith(b'\r\n') and len(line) < 256: line += receive(1)
            if not re.fullmatch(rb'HTTP/1\.[01] 503 [^\r\n]*\r\n', line):
                raise ValueError('b12_health_maintenance_not_503')
        else:
            raise ValueError('b12_health_unknown_protocol')
    return 'available'


def protected_protocol_health(runtime, deadline, inventory):
    frozen = trusted_json(BASE / 'runtime-manifest.json')['containers']
    names = runtime['test_containers'] + runtime['maintenance_containers']
    actual={}
    for name in names:
        info=_docker('inspect',frozen[name]['id'])[0]
        actual[name]={'configuration':_configuration(info),'actual_ports':info['NetworkSettings']['Ports']}
    targets = health_targets(runtime, frozen, actual, inventory)
    result = []
    for target in targets:
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
        result.append({**target, 'status': protocol_health(target, min(2, remaining))})
    return {'scope': 'unauthenticated_server_protocol_availability_only', 'services': result,
        'inventory_sha256':hashlib.sha256(json.dumps(inventory,indent=2,sort_keys=True).encode()).hexdigest()}


def create_probe_slice(manifest, manifest_path):
    operation = manifest['operation_id']
    group = owned_group(operation)
    if manifest['child_group'] != group:
        raise ValueError('b12_slice_canonical_identity_required')
    unit = SYSTEMD_RUNTIME / (group)
    if unit.exists() or unit.is_symlink():
        raise ValueError('b12_slice_unit_already_claimed')
    content = ('[Unit]\nDescription=Owned Myink B12 operation ' + operation + '\n'
               '[Slice]\nMemoryAccounting=yes\nCPUAccounting=yes\n'
               'MemoryMax=1073741824\nMemorySwapMax=268435456\n'
               'CPUQuota=200%\nCPUQuotaPeriodSec=100ms\n').encode()
    manifest['slice_unit'] = {'path': str(unit), 'sha256': hashlib.sha256(content).hexdigest(), 'status': 'intent'}
    _durable_json(manifest_path, manifest)
    with unit.open('xb') as out:
        os.chmod(unit, 0o644)
        out.write(content); out.flush(); os.fsync(out.fileno())
    _fsync_directory(SYSTEMD_RUNTIME)
    info = unit.stat()
    if unit.is_symlink() or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022 or digest(unit) != manifest['slice_unit']['sha256']:
        raise ValueError('b12_slice_unit_ownership_unconfirmed')
    manifest['slice_unit']['status'] = 'written'
    _durable_json(manifest_path, manifest)
    _systemctl('daemon-reload')
    _systemctl('start', group)
    if {key: (_probe_group(operation) / key).read_text().strip() for key in CHILD_LIMITS} != CHILD_LIMITS:
        raise ValueError('b12_probe_child_limits_unconfirmed')
    manifest['slice_unit']['status'] = 'created'
    manifest['child_status'] = 'created'
    _durable_json(manifest_path, manifest)


def probe_uncertain(operation, reason):
    fence = BASE / 'heavy.lock.uncertain'
    if not fence.exists():
        _durable_json(fence, {'operation_id': operation, 'reason': reason}, exclusive=True)
    owner_path = BASE / 'current-operation.json'
    try:
        owner = trusted_json(owner_path)
    except FileNotFoundError:
        owner = None
    if owner and owner.get('operation_id') == operation:
        _write_b12_owner({**owner, 'status': 'uncertain'})
    return {'status': 'uncertain', 'daemon_terminal_verified': False, 'reason': reason}


def execute_probe_controller(operation, seconds):
    """Trusted controller; every journaled incomplete transition retains its fence."""
    from ops.pi.build import HeavyAction
    from datetime import timedelta
    import fcntl
    if os.getuid() != 0 or not 1 <= seconds <= 120:
        raise ValueError('b12_probe_trusted_controller_required')
    spec, runtime = probe_admission(operation)
    filesystem = _probe_filesystem()
    capacity = {key: shutil.disk_usage(path).free for key, path in [('host_free_bytes', '/mnt/e'), ('guest_free_bytes', '/')]}
    if min(capacity.values()) < spec['planned_peak_bytes'] + 5 * 1024**3:
        raise ValueError('b12_probe_disk_peak_plus_reserve_required')
    root = BASE / 'b12' / operation
    group, unit = owned_group(operation), 'myinkpi-test-' + operation
    watcher = 'myinkpi-watch-' + operation
    execution_deadline = min(datetime.fromisoformat(spec['deadline']), datetime.now(timezone.utc) + timedelta(seconds=seconds))
    with HeavyAction(BASE / 'heavy.lock'):
        # All admission/ownership checks are repeated under the shared heavy mutex.
        spec, runtime = probe_admission(operation)
        if root.exists() or root.is_symlink() or _probe_group(operation).exists():
            raise ValueError('b12_probe_namespace_already_claimed')
        if _systemctl('list-units', 'myinkpi-test-*', '--state=running', '--no-legend', '--no-pager'):
            raise ValueError('b12_probe_other_unit_active')
        if _docker('image', 'inspect', RUNNER_IMAGE)[0]['Id'] != RUNNER_IMAGE:
            raise ValueError('b12_probe_existing_image_drift')
        before = sample_resources('heavy')
        inventory=probe_health_inventory(operation,spec)
        health_before = protected_protocol_health(runtime, execution_deadline, inventory)
        root.parent.mkdir(mode=0o700, exist_ok=True)
        root.mkdir(mode=0o700)
        manifest = {'operation_id': operation, 'lab_uuid': runtime['lab_uuid'], 'daemon_id': DAEMON_ID,
            'unit': unit, 'child_group': group, 'source_hash': spec['source_hash'], 'objects': [],
            'unknown_daemon_effects': False, 'daemon_intents': [],
            'protected': trusted_json(BASE / 'runtime-manifest.json')['containers'],
            'execution_deadline': execution_deadline.isoformat(), 'child_status': 'intent',
            'capacity_before': capacity, 'filesystem': filesystem, 'resources_before': before,
            'protocol_health_before': health_before}
        _durable_json(root / 'creation.json', manifest, exclusive=True)
        completion = {'status': 'uncertain', 'daemon_terminal_verified': False}
        errors, unit_returncode, health_after = [], None, None
        ownership_locked = False
        def acquire_ownership(ownership, deadline):
            nonlocal ownership_locked
            while datetime.now(timezone.utc) < deadline:
                try:
                    fcntl.flock(ownership.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    ownership_locked = True
                    return
                except BlockingIOError: time.sleep(.02)
            raise TimeoutError('b12_ownership_lock_deadline')
        with (BASE / 'ownership.lock').open('a') as ownership:
            try:
                acquire_ownership(ownership, execution_deadline)
                current_path = BASE / 'current-operation.json'
                if current_path.exists() and trusted_json(current_path).get('status') in ('active', 'uncertain'):
                    raise ValueError('b12_probe_owner_unresolved')
                _write_b12_owner({'operation_id': operation, 'lab_uuid': runtime['lab_uuid'], 'unit': unit,
                    'group': 'b12', 'child_group': group, 'status': 'active'})
                create_probe_slice(manifest, root / 'creation.json')
                unit_budget = int((execution_deadline - datetime.now(timezone.utc)).total_seconds())
                if unit_budget < 1: raise ValueError('b12_probe_deadline_before_start')
                env = ['/usr/bin/env', '-i', 'PATH=/opt/myink-pi-venv/bin:/usr/bin:/bin',
                    'HOME=' + str(root), 'TMPDIR=' + str(root), 'PYTHONDONTWRITEBYTECODE=1',
                    'PYTHONPATH=' + str(BASE / 'trusted-source/src') + ':' + str(BASE / 'trusted-source')]
                manifest['watcher_status'] = 'intent'
                _durable_json(root / 'creation.json', manifest)
                subprocess.run(['/usr/bin/systemd-run', '--quiet', '--unit=' + watcher, '--slice=myinkpi-infra.slice',
                    '-p', 'RuntimeMaxSec=' + str(unit_budget + 15), '--working-directory=' + str(BASE / 'trusted-source'),
                    *env, '/opt/myink-pi-venv/bin/python', '-B', '-m', 'ops.pi.resources', 'watch-guest', unit, str(unit_budget)], check=True, timeout=min(10,unit_budget))
                manifest['watcher_status'] = 'created'
                _durable_json(root / 'creation.json', manifest)
                with (root / 'unit.stdout').open('xb', buffering=0) as out, (root / 'unit.stderr').open('xb', buffering=0) as err:
                    child = subprocess.Popen(['/usr/bin/systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                        '--unit=' + unit, '--slice=' + group, '-p', 'RuntimeMaxSec=' + str(unit_budget),
                        '--working-directory=' + str(BASE / 'trusted-source'), *env,
                        '/opt/myink-pi-venv/bin/python', '-u', '-B', '-c',
                        "from ops.pi.lab.build_lab import run_runner_probe; raise SystemExit(run_runner_probe('" + operation + "'))"],
                        stdout=out, stderr=err)
                    for _ in range(50):
                        if subprocess.run(['/usr/bin/systemctl', 'is-active', '--quiet', unit], timeout=2).returncode == 0 or child.poll() is not None:
                            break
                        time.sleep(.1)
                    fcntl.flock(ownership.fileno(), fcntl.LOCK_UN)
                    ownership_locked = False
                    remaining = max(.01,(execution_deadline-datetime.now(timezone.utc)).total_seconds())
                    unit_returncode = child.wait(timeout=remaining + 5)
                until = time.monotonic() + 3
                while time.monotonic() < until:
                    if subprocess.run(['/usr/bin/systemctl', 'is-active', '--quiet', watcher], timeout=2).returncode != 0: break
                    time.sleep(.1)
            except (ValueError, OSError, subprocess.SubprocessError, RuntimeError) as error:
                errors.append(str(error))
                # Fence immediately, before releasing any remaining mutex authority.
                if not (BASE / 'heavy.lock.uncertain').exists():
                    _durable_json(BASE / 'heavy.lock.uncertain', {'operation_id': operation, 'reason': str(error)}, exclusive=True)
            finally:
                try:
                    if not ownership_locked:
                        acquire_ownership(ownership, datetime.now(timezone.utc) + timedelta(seconds=5))
                    if manifest.get('watcher_status') == 'created':
                        _systemctl('stop', watcher)
                    health_after = protected_protocol_health(verify_runtime(), datetime.now(timezone.utc) + timedelta(seconds=15), probe_health_inventory(operation,spec))
                    verify_source(BASE / 'trusted-source', spec['source_files'])
                    if errors:
                        completion = probe_uncertain(operation, errors[-1])
                    else:
                        completion = finish_b12_owner(operation, not _group_members(_probe_group(operation)))
                except (ValueError, OSError, subprocess.SubprocessError, RuntimeError) as error:
                    errors.append(str(error))
                    # No stop, timeout, health or finish error can bypass the durable fence.
                    if ownership_locked:
                        completion = probe_uncertain(operation, str(error))
                    else:
                        if not (BASE / 'heavy.lock.uncertain').exists():
                            _durable_json(BASE / 'heavy.lock.uncertain', {'operation_id':operation,'reason':str(error)}, exclusive=True)
                        completion = {'status':'uncertain','daemon_terminal_verified':False,'reason':str(error)}
                finally:
                    if ownership_locked: fcntl.flock(ownership.fileno(), fcntl.LOCK_UN)
        try:
            after = sample_resources('heavy')
            measurements = {key: (_probe_group(operation) / key).read_text().strip() for key in
                ('memory.current', 'memory.peak', 'memory.swap.current', 'memory.events', 'cpu.stat')}
            attempt = trusted_json(root / 'native-attempt.json') if (root / 'native-attempt.json').exists() else None
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            errors.append(str(error))
            with (BASE / 'ownership.lock').open('a') as final_ownership:
                try:
                    acquire_ownership(final_ownership, datetime.now(timezone.utc) + timedelta(seconds=5))
                    completion = probe_uncertain(operation,str(error))
                finally:
                    if ownership_locked: fcntl.flock(final_ownership.fileno(), fcntl.LOCK_UN)
            after, measurements, attempt = None, None, None
        if attempt is None:
            attempt = {'operation_id': operation, 'status': 'uncertain' if completion['status'] == 'uncertain' else 'blocked',
                'evidence': {'scope': 'b12_runner_userns_capability', 'status': 'BLOCKED',
                    'reason': 'runner_native_attempt_unfinished', 'lab_uuid': runtime['lab_uuid'], 'daemon_id': DAEMON_ID,
                    'source_hash': spec['source_hash'], 'candidate_execution': False, 'executed_checks': 0,
                    'executed_images': 0, 'helper_completion_is_ci_pass': False}}
        attempt['evidence'].update(completion=completion, resources_before=before, resources_after=after,
            child_measurements=measurements, protocol_health_before=health_before, protocol_health_after=health_after,
            errors=errors, native_root=str(root), unit_returncode=unit_returncode,
            raw_unit_stdout_sha256=digest(root/'unit.stdout') if (root/'unit.stdout').exists() else None,
            raw_unit_stderr_sha256=digest(root/'unit.stderr') if (root/'unit.stderr').exists() else None)
        if completion['status'] == 'uncertain': attempt['status'] = 'uncertain'
        output = PRIVATE / 'evidence' / ('b12-' + operation)
        output.mkdir(mode=0o700)
        _durable_json(output / 'native-receipt.json', attempt, exclusive=True)
        print(json.dumps({'operation_id': operation, 'status': attempt['status'], 'receipt_path': str(output / 'native-receipt.json')}))
        return 0 if attempt['status'] == 'done' else 78


def _write_b12_owner(owner):
    _durable_json(BASE / 'current-operation.json', owner)