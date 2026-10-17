"""Finite frozen B12 installer; only the independently approved packet closure."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import time


def validate_lock(path, handle):
    value = os.fstat(handle.fileno())
    if path.is_symlink() or value.st_uid != 0 or value.st_nlink != 1 or value.st_mode & 0o022:
        raise ValueError('b12_install_lock_untrusted')


@contextmanager
def install_locks(base, deadline):
    import fcntl
    handles = []
    try:
        for name in ('heavy.lock', 'ownership.lock'):
            path = base / name
            handle = os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600), 'r+')
            try:
                validate_lock(path, handle)
                while True:
                    if datetime.now(timezone.utc) >= deadline: raise TimeoutError('b12_install_lock_deadline')
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        time.sleep(min(.02, max(0, (deadline-datetime.now(timezone.utc)).total_seconds())))
                handles.append(handle)
            except BaseException:
                handle.close()
                raise
        yield
    finally:
        for handle in reversed(handles):
            try: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally: handle.close()


def install_frozen(packet, expected, base=Path('/opt/myink-pi-lab')):
    """Packet path and expected hashes are literals in the frozen root entrypoint."""
    from ops.pi.lab.build_lab import _durable_json, _fsync_directory, digest, protected_protocol_health
    from ops.pi.lab.verify import verify_runtime
    if os.getuid() != 0: raise ValueError('b12_install_root_required')
    for name, value in expected.items():
        if name == 'launcher': continue
        if digest(packet/name) != value: raise ValueError('b12_install_packet_drift')
    spec=json.loads((packet/'spec.json').read_text())
    files=json.loads((packet/'source-manifest.json').read_text())
    previous=json.loads((packet/'native-before.json').read_text())
    if files!=spec['source_files'] or hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=spec['source_hash']:
        raise ValueError('b12_install_source_closure_drift')
    deadline=datetime.fromisoformat(spec['deadline'])
    deadline=min(deadline, datetime.now(timezone.utc) + __import__('datetime').timedelta(seconds=120))
    inventory_path=packet/'protocol-targets.json'
    if digest(inventory_path)!=spec['protocol_inventory_sha256']:
        raise ValueError('b12_install_protocol_inventory_hash_drift')
    inventory=json.loads(inventory_path.read_text())
    if (inventory['operation_id']!=spec['operation_id']
            or inventory['lab_uuid']!=spec['lab_uuid']
            or inventory['daemon_id']!=spec['daemon_id']):
        raise ValueError('b12_install_protocol_inventory_identity_drift')
    source=base/'trusted-source'
    changed=[]
    with install_locks(base, deadline):
        if (base/'heavy.lock.uncertain').exists() or (base/'installation.uncertain').exists():
            raise ValueError('b12_install_previous_uncertainty')
        if subprocess.check_output(['/usr/bin/systemctl','list-units','myinkpi-test-*','--state=running','--no-legend','--no-pager'],text=True,timeout=5).strip():
            raise ValueError('b12_install_active_unit')
        owner=base/'current-operation.json'
        if owner.exists() and json.loads(owner.read_text()).get('status') in ('active','uncertain'):
            raise ValueError('b12_install_owner_unresolved')
        runtime=verify_runtime()
        if runtime['lab_uuid']!=spec['lab_uuid'] or runtime['daemon_id']!=spec['daemon_id']:
            raise ValueError('b12_install_runtime_identity_drift')
        health_before=protected_protocol_health(runtime, deadline, inventory)
        if set(files)!=set(previous): raise ValueError('b12_install_exact_baseline_required')
        for name, value in files.items():
            relative=PurePosixPath(name)
            if relative.is_absolute() or '..' in relative.parts or not name.startswith('ops/'):
                raise ValueError('b12_install_path_invalid')
            copied=packet/'source'/name
            if copied.is_symlink() or copied.stat().st_nlink!=1 or digest(copied)!=value:
                raise ValueError('b12_install_source_drift')
            target=source/name
            for path in (target,*target.parents):
                if path==base: break
                if path.is_symlink(): raise ValueError('b12_install_native_link')
            old=previous[name]
            if old.get('absent'):
                if target.exists(): raise ValueError('b12_install_foreign_new_source')
            elif (not target.is_file() or target.stat().st_uid!=0 or target.stat().st_nlink!=1
                    or target.stat().st_mode & 0o022 or digest(target)!=old['sha256']):
                raise ValueError('b12_install_native_baseline_drift')
        launcher=base/'provision.sh'
        if launcher.is_symlink() or launcher.stat().st_uid!=0 or launcher.stat().st_nlink!=1 or digest(launcher)!=expected['launcher']:
            raise ValueError('b12_install_launcher_baseline_drift')
        # Persist original bytes before any source replacement. Existing backup forbids retries.
        backup=packet/'previous-native'; backup.mkdir(mode=0o700)
        _fsync_directory(packet)
        try:
            for name in files:
                target=source/name
                if target.exists():
                    archived=backup/name; archived.parent.mkdir(parents=True,exist_ok=True)
                    with archived.open('xb') as out:
                        out.write(target.read_bytes()); out.flush(); os.fsync(out.fileno())
                    for directory in (archived.parent,*archived.parent.parents):
                        _fsync_directory(directory)
                        if directory==backup: break
                temporary=target.with_name('.'+target.name+'.b12-'+spec['operation_id'])
                with temporary.open('xb') as out:
                    os.fchmod(out.fileno(),0o644); out.write((packet/'source'/name).read_bytes()); out.flush(); os.fsync(out.fileno())
                _fsync_directory(target.parent)
            with (backup/'installed-provision.sh').open('xb') as out:
                out.write(launcher.read_bytes()); out.flush(); os.fsync(out.fileno())
            _fsync_directory(backup)
            _durable_json(packet/'installation-intent.json', {'operation_id':spec['operation_id'], 'files':files,
                'source_hash':spec['source_hash'], 'backup':str(backup)}, exclusive=True)
            installation_fence={'operation_id':spec['operation_id'],'source_hash':spec['source_hash'],
                'kind':'trusted-source-installation','status':'uncertain','backup':str(backup)}
            for path in (base/'installation.uncertain',base/'heavy.lock.uncertain'):
                _durable_json(path,installation_fence,exclusive=True)
            for name in files:
                if datetime.now(timezone.utc)>=deadline: raise TimeoutError('b12_install_deadline')
                target=source/name
                target.with_name('.'+target.name+'.b12-'+spec['operation_id']).replace(target)
                changed.append(name); _fsync_directory(target.parent)
            temporary=base/('.provision.b12-'+spec['operation_id'])
            with temporary.open('xb') as out:
                os.fchmod(out.fileno(),0o700); out.write((packet/'source/ops/pi/lab/provision.sh').read_bytes()); out.flush(); os.fsync(out.fileno())
            temporary.replace(launcher); changed.append('installed-provision.sh'); _fsync_directory(base)
            admissions=base/'b12-probe'; admissions.mkdir(mode=0o700,exist_ok=True)
            if admissions.is_symlink() or admissions.stat().st_uid!=0 or admissions.stat().st_mode&0o077:
                raise ValueError('b12_install_admission_untrusted')
            health_path=admissions/(spec['operation_id']+'.health.json')
            with health_path.open('xb') as out:
                os.fchmod(out.fileno(),0o600); out.write(inventory_path.read_bytes()); out.flush(); os.fsync(out.fileno())
            _fsync_directory(admissions)
            if digest(health_path)!=spec['protocol_inventory_sha256']:
                raise ValueError('b12_install_native_inventory_hash_drift')
            _durable_json(admissions/(spec['operation_id']+'.json'),spec,exclusive=True)
            _fsync_directory(base)
            for name,value in files.items():
                if digest(source/name)!=value: raise ValueError('b12_install_final_source_drift')
            if digest(launcher)!=files['ops/pi/lab/provision.sh']: raise ValueError('b12_install_final_launcher_drift')
            final=verify_runtime()
            health_after=protected_protocol_health(final,deadline,inventory)
            _durable_json(packet/'installation-receipt.json', {'operation_id':spec['operation_id'], 'status':'installed',
                'source_hash':spec['source_hash'], 'files':files, 'changed':changed,
                'previous_native_inventory_sha256':digest(packet/'native-before.json'),
                'health_before':health_before, 'health_after':health_after,
                'protocol_inventory_sha256':spec['protocol_inventory_sha256']},exclusive=True)
            for path in (base/'installation.uncertain',base/'heavy.lock.uncertain'):
                if json.loads(path.read_text())!=installation_fence:
                    raise ValueError('b12_install_fence_owner_drift')
            if datetime.now(timezone.utc)>=deadline: raise TimeoutError('b12_install_final_deadline')
            for path in (base/'installation.uncertain',base/'heavy.lock.uncertain'):
                path.unlink(); _fsync_directory(base)
        except BaseException as error:
            record={'operation_id':spec['operation_id'],'status':'uncertain','reason':str(error),
                    'changed':changed,'backup':str(backup),'source_hash':spec['source_hash']}
            # Installation uncertainty fences every old/new heavy route; never automatic rollback.
            for path in (base/'heavy.lock.uncertain',base/'installation.uncertain'):
                if not path.exists(): _durable_json(path,record,exclusive=True)
            _durable_json(packet/'installation-failure.json',record,exclusive=True)
            raise
    return {'operation_id':spec['operation_id'],'status':'installed','source_hash':spec['source_hash']}
