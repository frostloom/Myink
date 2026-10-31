import json
from pathlib import Path
import sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from ops.pi.lab import build_lab

OP = '11111111-1111-4111-8111-111111111111'


def runtime_targets():
    names = ['lab-postgres', 'lab-redis', 'lab-rabbitmq', 'lab-maintenance-postgres',
             'lab-maintenance-redis', 'lab-maintenance-rabbit', 'lab-maintenance-entry']
    ports = [5432, 6379, 5672, 5432, 6379, 5672, 8080]
    frozen = {name: {'id': str(index) * 64, 'host': {'PortBindings': {
        str(port) + '/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(20000 + index)}]}}}
        for index, (name, port) in enumerate(zip(names, ports), 1)}
    return {'lab_uuid': 'lab', 'daemon_id':build_lab.DAEMON_ID, 'test_containers': names[:3], 'maintenance_containers': names[3:]}, frozen


@pytest.mark.parametrize('fault', ['foreign_id', 'wildcard', 'wrong_port', 'missing', 'extra'])
def test_health_refuses_changed_identity_or_nonfixed_target(fault):
    runtime, frozen = runtime_targets()
    inventory={'operation_id':OP,'lab_uuid':'lab','daemon_id':build_lab.DAEMON_ID,'containers': {name:{'id':value['id'],'port_bindings':value['host']['PortBindings'],'actual_ports':value['host']['PortBindings']} for name,value in frozen.items()}}
    actual = {name:{'configuration':value,'actual_ports':value['host']['PortBindings']} for name,value in json.loads(json.dumps(frozen)).items()}
    if fault == 'foreign_id': actual['lab-postgres']['configuration']['id'] = 'f' * 64
    if fault == 'wildcard': actual['lab-postgres']['configuration']['host']['PortBindings']['5432/tcp'][0]['HostIp'] = '0.0.0.0'
    if fault == 'wrong_port': actual['lab-postgres']['configuration']['host']['PortBindings'] = {'15432/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '20001'}]}
    if fault == 'missing': runtime['maintenance_containers'].pop()
    if fault == 'extra': runtime['test_containers'].append('candidate')
    with pytest.raises(ValueError): build_lab.health_targets(runtime, frozen, actual, inventory)


def test_health_uses_exact_seven_frozen_ids_and_loopback_ports():
    runtime, frozen = runtime_targets()
    inventory={'operation_id':OP,'lab_uuid':'lab','daemon_id':build_lab.DAEMON_ID,'containers': {name:{'id':value['id'],'port_bindings':value['host']['PortBindings'],'actual_ports':value['host']['PortBindings']} for name,value in frozen.items()}}
    actual={name:{'configuration':value,'actual_ports':value['host']['PortBindings']} for name,value in frozen.items()}
    targets = build_lab.health_targets(runtime, frozen, actual, inventory)
    assert len(targets) == 7
    assert [target['protocol'] for target in targets] == ['postgres', 'redis', 'amqp', 'postgres', 'redis', 'amqp', 'http503']
    assert all(t['host'] == '127.0.0.1' and t['id'] == frozen[t['name']]['id'] for t in targets)


class Wire:
    def __init__(self, reply): self.reply, self.sent = reply, []
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def settimeout(self, value): assert 0 < value <= 2
    def sendall(self, value): self.sent.append(value)
    def recv(self, size):
        value, self.reply = self.reply[:size], self.reply[size:]
        return value


@pytest.mark.parametrize('protocol,reply', [('postgres', b'E\x00\x00\x00\x08bad!'), ('postgres', b''),
    ('redis', b'-ERR\r\n'), ('amqp', b'AMQPbad'), ('http503', b'HTTP/1.1 200 OK\r\n\r\n')])
def test_health_rejects_protocol_error_closed_connection_or_wrong_http(monkeypatch, protocol, reply):
    import socket
    wire = Wire(reply)
    monkeypatch.setattr(socket, 'create_connection', lambda *args, **kwargs: wire)
    with pytest.raises(ValueError): build_lab.protocol_health({'protocol': protocol, 'host': '127.0.0.1', 'port': 20001}, 2)


@pytest.mark.parametrize('protocol,reply', [('postgres', b'R\x00\x00\x00\x08\x00\x00\x00\x0a'),
    ('redis', b'+PONG\r\n'), ('amqp', b'\x01\x00\x00\x00\x00\x00\x04\x00\x0a\x00\x0a\xce'),
    ('http503', b'HTTP/1.1 503 Service Unavailable\r\n\r\n')])
def test_health_only_sends_fixed_protocol_requests_without_auth_or_data(monkeypatch, protocol, reply):
    import socket
    wire = Wire(reply)
    monkeypatch.setattr(socket, 'create_connection', lambda *args, **kwargs: wire)
    result = build_lab.protocol_health({'protocol': protocol, 'host': '127.0.0.1', 'port': 20001}, 2)
    assert result == 'available'
    assert len(wire.sent) == 1 and b'password' not in wire.sent[0] and b'SELECT' not in wire.sent[0]


def test_new_slice_is_journaled_and_configured_before_start(monkeypatch, tmp_path):
    monkeypatch.setattr(build_lab, '_fsync_directory', lambda path: None)
    original_chmod=build_lab.os.chmod
    monkeypatch.setattr(build_lab.os, 'chmod', lambda path, mode, **kw: original_chmod(path, 0o444 if str(path).endswith('.slice') else mode, **kw))
    monkeypatch.setattr(build_lab, 'SYSTEMD_RUNTIME', tmp_path)
    native_stat = Path.stat
    def root_unit_stat(path, **kwargs):
        value = native_stat(path, **kwargs)
        if path == tmp_path / build_lab.owned_group(OP):
            fields = list(value)
            fields[4] = 0
            return __import__('os').stat_result(fields)
        return value
    monkeypatch.setattr(Path, 'stat', root_unit_stat)
    monkeypatch.setattr(build_lab, '_probe_group', lambda op: tmp_path/'cgroup')
    events = []
    original = build_lab._durable_json
    monkeypatch.setattr(build_lab, '_durable_json', lambda path, value, **kw: events.append(('journal', json.loads(json.dumps(value)))) or original(path, value, **kw))
    def systemctl(*args):
        unit = tmp_path/build_lab.owned_group(OP)
        events.append(args)
        assert unit.read_text().find('MemoryMax=1073741824') >= 0
        if args[0] == 'start':
            group = tmp_path/'cgroup'; group.mkdir()
            for key, value in build_lab.CHILD_LIMITS.items(): (group/key).write_text(value)
        return ''
    monkeypatch.setattr(build_lab, '_systemctl', systemctl)
    manifest = {'operation_id': OP, 'child_group': build_lab.owned_group(OP)}
    build_lab.create_probe_slice(manifest, tmp_path/'creation.json')
    assert events[0][0] == 'journal' and events[0][1]['slice_unit']['status'] == 'intent'
    assert ('daemon-reload',) in events and ('start', build_lab.owned_group(OP)) in events
    assert not any('set-property' in str(event) for event in events)
    assert manifest['slice_unit']['status'] == 'created'


def test_slice_foreign_file_refuses_before_systemd_effect(monkeypatch, tmp_path):
    monkeypatch.setattr(build_lab, 'SYSTEMD_RUNTIME', tmp_path)
    unit = tmp_path/build_lab.owned_group(OP); unit.write_bytes(b'foreign')
    effects=[]; monkeypatch.setattr(build_lab, '_systemctl', lambda *a: effects.append(a))
    with pytest.raises(ValueError): build_lab.create_probe_slice({'operation_id': OP, 'child_group': unit.name}, tmp_path/'creation.json')
    assert effects == [] and unit.read_bytes() == b'foreign'


def test_controller_failure_persists_fence_and_owner_before_return(monkeypatch, tmp_path):
    monkeypatch.setattr(build_lab, 'BASE', tmp_path)
    monkeypatch.setattr(build_lab, 'trusted_json', lambda path: {'operation_id': OP, 'status': 'active', 'group': 'b12'})
    monkeypatch.setattr(build_lab, '_fsync_directory', lambda path: None)
    writes=[]; monkeypatch.setattr(build_lab, '_write_b12_owner', lambda value: writes.append(value))
    result=build_lab.probe_uncertain(OP, 'watcher_stop_failed')
    assert result['status']=='uncertain' and result['daemon_terminal_verified'] is False
    assert json.loads((tmp_path/'heavy.lock.uncertain').read_text())['operation_id']==OP
    assert writes[-1]['status']=='uncertain'


def test_install_lock_order_and_busy_second_lock_release(monkeypatch, tmp_path):
    from ops.pi.lab import install_probe
    events=[]
    first=[None]
    def flock(fd, flags):
        if flags & 2:
            events.append('acquire')
            if first[0] is None: first[0]=fd
            elif fd != first[0]: raise BlockingIOError('busy')
        else: events.append('release')
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(flock=flock,LOCK_EX=2,LOCK_NB=4,LOCK_UN=8))
    monkeypatch.setattr(install_probe.os,'getuid',lambda:0,raising=False)
    monkeypatch.setattr(install_probe,'validate_lock',lambda *a:None)
    with pytest.raises(TimeoutError):
        with install_probe.install_locks(tmp_path, datetime.now(timezone.utc)+timedelta(seconds=.01)): pytest.fail('busy admitted')
    assert events[:2]==['acquire','acquire'] and events[-1]=='release'
    assert (tmp_path/'heavy.lock').exists() and (tmp_path/'ownership.lock').exists()


@pytest.mark.parametrize('fault', ['watcher_start', 'watcher_stop', 'child_timeout', 'completion'])
def test_controller_actual_error_boundaries_keep_native_uncertain(monkeypatch, tmp_path, fault):
    import subprocess
    from ops.pi.tests.test_build_lab import runner_spec
    monkeypatch.setattr(build_lab, 'BASE', tmp_path)
    monkeypatch.setattr(build_lab, 'PRIVATE', tmp_path/'private')
    (tmp_path/'private/evidence').mkdir(parents=True)
    monkeypatch.setattr(build_lab.os, 'getuid', lambda:0, raising=False)
    monkeypatch.setattr(build_lab, '_fsync_directory', lambda path:None)
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(flock=lambda *a:None,LOCK_EX=2,LOCK_NB=4,LOCK_UN=8))
    spec=runner_spec(); runtime={'lab_uuid':'lab','daemon_id':build_lab.DAEMON_ID}
    monkeypatch.setattr(build_lab,'probe_admission',lambda op:(spec,runtime))
    monkeypatch.setattr(build_lab,'probe_health_inventory',lambda *a:{},raising=False)
    monkeypatch.setattr(build_lab,'_probe_filesystem',lambda:{'fs_type':'ext4'})
    monkeypatch.setattr(build_lab.shutil,'disk_usage',lambda path:SimpleNamespace(free=20*1024**3))
    monkeypatch.setattr(build_lab,'_docker',lambda *a:[{'Id':build_lab.RUNNER_IMAGE}])
    monkeypatch.setattr(build_lab,'sample_resources',lambda group:{'memory.current':'100'})
    monkeypatch.setattr(build_lab,'protected_protocol_health',lambda *a:{'services':['available']*7},raising=False)
    monkeypatch.setattr(build_lab,'verify_runtime',lambda:runtime)
    monkeypatch.setattr(build_lab,'verify_source',lambda *a:'a'*64)
    monkeypatch.setattr(build_lab,'_probe_group',lambda op:tmp_path/'cgroup')
    def trusted(path):
        if path.name=='runtime-manifest.json': return {'containers':{}}
        return json.loads(path.read_text())
    monkeypatch.setattr(build_lab,'trusted_json',trusted)
    def create_slice(manifest,path):
        group=tmp_path/'cgroup'; group.mkdir()
        for key in ('memory.current','memory.peak','memory.swap.current','memory.events','cpu.stat'): (group/key).write_text('0')
    monkeypatch.setattr(build_lab,'create_probe_slice',create_slice,raising=False)
    systemctl_calls=[]
    def systemctl(*args):
        systemctl_calls.append(args)
        if args[0]=='start':
            group=tmp_path/'cgroup'; group.mkdir()
            for key,value in build_lab.CHILD_LIMITS.items(): (group/key).write_text(value)
        if args[0]=='stop' and fault=='watcher_stop': raise ValueError('watcher_stop_failed')
        return ''
    monkeypatch.setattr(build_lab,'_systemctl',systemctl)
    def run(argv,**kw):
        if argv[0]=='/usr/bin/systemd-run' and fault=='watcher_start': raise subprocess.CalledProcessError(1,argv)
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(build_lab.subprocess,'run',run)
    class Child:
        def poll(self): return 78
        def wait(self,**kw):
            if fault=='child_timeout': raise subprocess.TimeoutExpired('owned-child',1)
            return 78
    monkeypatch.setattr(build_lab.subprocess,'Popen',lambda *a,**kw:Child())
    monkeypatch.setattr(build_lab,'_group_members',lambda path:[])
    def finish(*a):
        if fault=='completion': raise ValueError('terminal_unconfirmed')
        return {'status':'completed','daemon_terminal_verified':True}
    monkeypatch.setattr(build_lab,'finish_b12_owner',finish)
    assert build_lab.execute_probe_controller(OP,120)==78
    if fault=='watcher_start':
        assert not any(call==('stop','myinkpi-watch-'+OP) for call in systemctl_calls)
    receipt=json.loads((tmp_path/'private/evidence'/('b12-'+OP)/'native-receipt.json').read_text())
    assert receipt['status']=='uncertain' and receipt['evidence']['completion']['daemon_terminal_verified'] is False
    assert (tmp_path/'heavy.lock.uncertain').exists()
    assert json.loads((tmp_path/'current-operation.json').read_text())['status']=='uncertain'


@pytest.mark.parametrize('failure', ['replace', 'final_health', 'fence_mismatch', 'success'])
def test_partial_install_retains_original_bytes_and_durable_fence(monkeypatch,tmp_path,failure):
    from contextlib import contextmanager
    from ops.pi.lab import install_probe,verify
    import hashlib
    base=tmp_path/'base'; source=base/'trusted-source'; packet=tmp_path/'packet'
    (source/'ops/pi/lab').mkdir(parents=True); (packet/'source/ops/pi/lab').mkdir(parents=True)
    name='ops/pi/lab/provision.sh'
    (packet/'source'/name).write_bytes(b'new launcher')
    # Newly introduced source is absent; retained installed launcher supplies old-byte proof.
    previous={name:{'absent':True}}
    files={name:hashlib.sha256(b'new launcher').hexdigest()}
    launcher=base/'provision.sh'; launcher.write_bytes(b'old launcher')
    spec={'operation_id':OP,'lab_uuid':'lab','daemon_id':build_lab.DAEMON_ID,
        'source_hash':hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'source_files':files,'protocol_inventory_sha256':'a'*64,'deadline':'2099-01-01T00:00:00+00:00'}
    for file,value in [('spec.json',spec),('source-manifest.json',files),('native-before.json',previous),('protocol-targets.json',{'operation_id':OP,'lab_uuid':'lab','daemon_id':build_lab.DAEMON_ID,'containers':{}})]:
        (packet/file).write_text(json.dumps(value))
    expected={file:hashlib.sha256((packet/file).read_bytes()).hexdigest() for file in ('spec.json','source-manifest.json','native-before.json')}
    spec['protocol_inventory_sha256']=hashlib.sha256((packet/'protocol-targets.json').read_bytes()).hexdigest()
    (packet/'spec.json').write_text(json.dumps(spec)); expected['spec.json']=hashlib.sha256((packet/'spec.json').read_bytes()).hexdigest()
    expected['protocol-targets.json']=spec['protocol_inventory_sha256']
    expected['launcher']=hashlib.sha256(b'old launcher').hexdigest()
    held=[]
    @contextmanager
    def locks(*a):
        held.append(True)
        try: yield
        finally: held.pop()
    monkeypatch.setattr(install_probe,'install_locks',locks)
    monkeypatch.setattr(install_probe.os,'getuid',lambda:0,raising=False)
    monkeypatch.setattr(install_probe.os,'fchmod',lambda *a:None,raising=False)
    monkeypatch.setattr(build_lab,'_fsync_directory',lambda path:None)
    monkeypatch.setattr(install_probe.subprocess,'check_output',lambda *a,**kw:'')
    monkeypatch.setattr(verify,'verify_runtime',lambda:{'lab_uuid':'lab','daemon_id':build_lab.DAEMON_ID})
    calls=[]
    def health(*a):
        assert held
        calls.append('health')
        if len(calls)==2 and failure=='final_health': raise ValueError('health failed')
        if len(calls)==2 and failure=='fence_mismatch':
            (base/'heavy.lock.uncertain').write_text(json.dumps({'operation_id':'foreign','kind':'image-pull'}))
        return {'services':['available']*7}
    monkeypatch.setattr(build_lab,'protected_protocol_health',health)
    native_stat=Path.stat
    def stat(path,**kw):
        value=native_stat(path,**kw)
        if path.is_relative_to(base):
            fields=list(value)
            fields[4] = 0  # This fixture models the root-owned Linux native tree.
            if path.name=='b12-probe': fields[0] &= ~0o077
            return __import__('os').stat_result(fields)
        return value
    monkeypatch.setattr(Path,'stat',stat)
    original=Path.replace
    def replace(path,target):
        assert held
        if str(target).endswith(name.replace('/',__import__('os').sep)):
            assert (base/'heavy.lock.uncertain').exists() and (base/'installation.uncertain').exists()
        if str(target).endswith(name.replace('/',__import__('os').sep)) and failure=='replace':
            raise OSError('replacement failure')
        return original(path,target)
    monkeypatch.setattr(Path,'replace',replace)
    cleared=[]; native_unlink=Path.unlink
    def unlink(path,**kw):
        if path.name in ('installation.uncertain','heavy.lock.uncertain'):
            assert held and (packet/'installation-receipt.json').exists()
            cleared.append(path.name)
        return native_unlink(path,**kw)
    monkeypatch.setattr(Path,'unlink',unlink)
    if failure=='success':
        result=install_probe.install_frozen(packet,expected,base)
        assert result['status']=='installed' and cleared==['installation.uncertain','heavy.lock.uncertain']
        assert not (base/'heavy.lock.uncertain').exists() and not (base/'installation.uncertain').exists()
        assert (packet/'previous-native/installed-provision.sh').read_bytes()==b'old launcher'
        return
    with pytest.raises((ValueError,OSError)): install_probe.install_frozen(packet,expected,base)
    record=json.loads((base/'heavy.lock.uncertain').read_text())
    if failure=='fence_mismatch':
        assert record=={'operation_id':'foreign','kind':'image-pull'} and cleared==[]
    else:
        assert record['status']=='uncertain' and record['operation_id']==OP
    assert (base/'installation.uncertain').exists() and (packet/'installation-failure.json').exists()
    assert (packet/'previous-native/installed-provision.sh').read_bytes()==b'old launcher'
    assert held==[]
    with pytest.raises(ValueError,match='previous_uncertainty'): install_probe.install_frozen(packet,expected,base)


@pytest.mark.parametrize('fault',['none','changed_actual','changed_inventory','extra_published'])
def test_health_dynamic_requested_ports_use_only_bound_actual_inventory(fault):
    runtime,frozen=runtime_targets()
    inventory={'operation_id':OP,'lab_uuid':'lab','daemon_id':build_lab.DAEMON_ID,'containers':{}}
    actual={}
    for name,value in frozen.items():
        ports=json.loads(json.dumps(value['host']['PortBindings']))
        ports['9999/tcp']=None
        value['host']['PortBindings'][next(iter(value['host']['PortBindings']))][0]['HostPort']=''
        inventory['containers'][name]={'id':value['id'],'port_bindings':value['host']['PortBindings'],'actual_ports':json.loads(json.dumps(ports))}
        actual[name]={'configuration':value,'actual_ports':ports}
    if fault=='changed_actual': actual['lab-postgres']['actual_ports']['5432/tcp'][0]['HostPort']='30000'
    if fault=='changed_inventory': inventory['containers']['lab-postgres']['id']='f'*64
    if fault=='extra_published': actual['lab-postgres']['actual_ports']['9999/tcp']=[{'HostIp':'127.0.0.1','HostPort':'30000'}]
    if fault!='none':
        with pytest.raises(ValueError): build_lab.health_targets(runtime,frozen,actual,inventory)
    else:
        result=build_lab.health_targets(runtime,frozen,actual,inventory)
        assert [value['port'] for value in result]==list(range(20001,20008))
