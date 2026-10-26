"""Containment host control and bounded I/O; actual Docker acceptance is separate."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

import pytest


IMAGE = 'sha256:' + 'a'*64
DAEMON = 'synthetic-daemon'
ENDPOINT = 'unix:///tmp/synthetic-docker.sock'
CID = 'b'*64


def module():
    assert importlib.util.find_spec('ops.pi.container_probe'), 'container containment probe missing'
    return importlib.import_module('ops.pi.container_probe')


class Daemon:
    def __init__(self):
        self.daemon_id = DAEMON
        self.objects = {}
        self.commands = []

    def run(self, args, **kwargs):
        command = args[3:]  # executable, --host, explicit socket
        self.commands.append(command)
        output, code = '', 0
        if command[:1] == ['info']:
            output = self.daemon_id
        elif command[:2] == ['image','inspect']:
            output = IMAGE
        elif command[:1] == ['create']:
            option = lambda flag: command[command.index(flag)+1]
            labels = dict(command[i+1].split('=',1) for i,x in enumerate(command) if x == '--label')
            self.objects[CID] = dict(Id=CID, Name='/' + option('--name'), Image=IMAGE,
                Config={'Labels':labels}, State={'Running':True,'Pid':123,'ExitCode':0},
                HostConfig=inspect_proof()['HostConfig'])
            self.objects[CID]['Config']['User']='65534:65534'
            output = CID
        elif command[:1] == ['inspect']:
            value = self.objects.get(command[-1]) or next((v for v in self.objects.values() if v.get('Name')=='/'+command[-1]),None)
            if value is None: code = 1
            else: output = json.dumps([value])
        elif command[:1] == ['kill']:
            self.objects[command[-1]]['State'].update(Running=False, Pid=0, ExitCode=137)
        elif command[:1] == ['rm']:
            del self.objects[command[-1]]
        elif command[:1] == ['ps']:
            if not command[command.index('--filter')+1].startswith('label='):
                code=1
            else: output = '\n'.join(self.objects)
        elif command[:1] == ['top']:
            output = 'PID PPID\n123 0\n124 123\n125 124\n'
        else: raise AssertionError('unexpected docker command ' + repr(command))
        return subprocess.CompletedProcess(args, code, output, '')


@pytest.fixture
def host(tmp_path, monkeypatch):
    api = module()
    daemon = Daemon()
    monkeypatch.setattr(api.subprocess, 'run', daemon.run)
    worker = tmp_path / 'worker.py'; worker.write_text('print("synthetic")\n')
    source = tmp_path / 'source'; source.mkdir()
    foreign = tmp_path / 'private' / 'canary'
    value = api.ProbeHost(docker=Path('/synthetic/docker'), endpoint=ENDPOINT,
        daemon_id=DAEMON, image_id=IMAGE, operation_id=str(uuid.uuid4()))
    return value, daemon, worker, source, foreign


def create(host, mode='isolation'):
    value, _, worker, source, foreign = host
    return value.create(mode, worker=worker, source=source, foreign=foreign)


@pytest.mark.parametrize('change', [dict(endpoint='tcp://127.0.0.1:2375'),dict(endpoint='unix://relative'),
    dict(endpoint='unix:///tmp/a\nb'),dict(image_id='python:latest'),dict(image_id='sha256:'+'z'*64),
    dict(operation_id='shared'),dict(docker=Path('docker'))])
def test_invalid_host_identity_never_reaches_daemon(change, monkeypatch):
    api = module()
    args = dict(docker=Path('/synthetic/docker'), endpoint=ENDPOINT, daemon_id=DAEMON,
        image_id=IMAGE, operation_id=str(uuid.uuid4())) | change
    monkeypatch.setattr(api.subprocess, 'run', lambda *a,**k: pytest.fail('invalid input contacted daemon'))
    with pytest.raises(ValueError): api.ProbeHost(**args)


def test_create_uses_fixed_limits_and_no_host_credentials_or_socket_mount(host, monkeypatch):
    monkeypatch.setenv('PLATFORM_MODEL_API_KEY', 'synthetic-do-not-inherit')
    cid = create(host)
    assert cid == CID
    command = next(c for c in host[1].commands if c[0]=='create')
    option = lambda flag: command[command.index(flag)+1]
    for flag, expected in {'--network':'none','--user':'65534:65534','--cap-drop':'ALL',
        '--memory':'384m','--memory-swap':'384m','--cpus':'0.5','--pids-limit':'64',
        '--security-opt':'no-new-privileges=true','--cgroupns':'private','--pull':'never'}.items():
        assert option(flag) == expected
    assert '--read-only' in command and '--privileged' not in command
    assert 'synthetic-do-not-inherit' not in ' '.join(command)
    mounts = [command[i+1] for i,v in enumerate(command) if v=='--mount']
    assert len(mounts)==2 and all('readonly' in m for m in mounts)
    assert not any('docker.sock' in m or 'myink-pi/state' in m for m in mounts)


@pytest.mark.parametrize('part', ['worker','source'])
def test_symlink_mount_rejected_before_container_creation(host, tmp_path, part):
    value, daemon, worker, source, foreign = host
    alias=tmp_path/'alias'; alias.symlink_to(worker if part=='worker' else source)
    with pytest.raises(ValueError):
        value.create('isolation',worker=alias if part=='worker' else worker,
                     source=alias if part=='source' else source,foreign=foreign)
    assert not daemon.objects


def test_normal_cleanup_stops_then_removes_only_owned_container(host):
    cid=create(host)
    host[1].objects['foreign']={'State':{'Running':True}}
    result=host[0].cleanup(cid)
    assert result['stopped'] and result['removed']
    assert host[1].objects == {'foreign':{'State':{'Running':True}}}


@pytest.mark.parametrize('drift', ['daemon','label','image','id'])
def test_foreign_or_drifted_identity_is_never_killed_or_removed(host, drift):
    cid=create(host); daemon=host[1]
    before=deepcopy(daemon.objects)
    if drift=='daemon': daemon.daemon_id='foreign'
    elif drift=='label': daemon.objects[cid]['Config']['Labels']['myink.pi.operation']='foreign'
    elif drift=='image': daemon.objects[cid]['Image']='sha256:'+'c'*64
    else: daemon.objects[cid]['Id']='c'*64
    with pytest.raises((ValueError, RuntimeError)): host[0].cleanup(cid)
    assert not any(c[0] in ('kill','rm') for c in daemon.commands)
    assert before[cid]['State'] == daemon.objects[cid]['State']


def test_arbitrary_container_reference_is_never_inspected_or_removed(host):
    with pytest.raises(ValueError): host[0].cleanup('foreign')
    assert not any(c[0] in ('inspect','kill','rm') for c in host[1].commands)


@pytest.mark.parametrize('kind, script, expected', [
    ('overflow','import sys,time;print("x"*8192,flush=True);time.sleep(3)','output_overflow'),
    ('timeout','import time;time.sleep(3)','timeout'),
    ('exit','import sys;sys.exit(2)','process_failed'),
    ('done','print("ok",flush=True)','completed')])
def test_capture_bounds_real_child_io_and_time(host, monkeypatch, kind, script, expected):
    api=module(); cid=create(host)
    real_popen=subprocess.Popen
    monkeypatch.setattr(api.subprocess,'Popen',lambda *a,**kw: real_popen([sys.executable,'-I','-S','-c',script],
        stdout=kw['stdout'],stderr=kw['stderr']))
    result=host[0].capture(cid,seconds=0.4,output_limit=1024)
    assert result['reason']==expected
    assert len(result['output'])<=1024
    assert result['elapsed']<2
    # Container cleanup must also work when the Docker attach client fails/ends.
    assert host[0].cleanup(cid)['removed']


def isolation_proof():
    return dict(uid=65534,gid=65534,no_new_privileges=True,no_capabilities=True,
        positive_source_read=True,positive_tmp_write=True,authenticated_mock=200,wrong_token=403,
        source_write_denied=True,harness_write_denied=True,foreign_files_denied=True,
        foreign_native_aliases_denied=True,ledger_credentials_sessions_denied=True,
        host_sockets_denied=True,network_denied=True,nested_network_denied=True)


def resources_proof():
    return dict(memory_max=402653184,swap_max=0,cpu_max='50000 100000',pids_max=64,
        memory_peak=400000000,oom_kills_delta=1,memory_child_returncode=-9,
        throttled_delta=1,pids_denied=True,pids_peak=64,guest_available_before=1024**3)


@pytest.mark.parametrize('kind', ['isolation','resources'])
def test_proof_requires_each_independent_measurement(kind):
    api=module()
    proof=isolation_proof() if kind=='isolation' else resources_proof()
    verify=getattr(api,'verify_'+kind)
    assert verify(proof)
    for key in proof:
        bad=dict(proof); del bad[key]
        assert not verify(bad), key


@pytest.mark.parametrize('change', [dict(memory_peak=402653185),dict(throttled_delta=0),dict(oom_kills_delta=0),
    dict(pids_denied=1),dict(swap_max=1),dict(memory_child_returncode=0),dict(guest_available_before=1)])
def test_claimed_limits_without_actual_behavior_do_not_pass(change):
    assert not module().verify_resources(resources_proof() | change)


def test_run_refuses_existing_or_symlink_evidence_root(tmp_path):
    api=module()
    args=dict(docker=Path('/synthetic/docker'),endpoint=ENDPOINT,daemon_id=DAEMON,image_id=IMAGE)
    with pytest.raises(ValueError): api.run_probe(tmp_path,**args)
    alias=tmp_path/'alias'; alias.symlink_to(tmp_path)
    with pytest.raises(ValueError): api.run_probe(alias,**args)


def inspect_proof():
    return dict(Config={'User':'65534:65534'}, HostConfig=dict(ReadonlyRootfs=True,
        NetworkMode='none',Privileged=False,CapDrop=['ALL'],CapAdd=None,SecurityOpt=['no-new-privileges=true'],
        PidMode='',CgroupnsMode='private',Memory=402653184,MemorySwap=402653184,
        NanoCpus=500000000,PidsLimit=64,Binds=None,Devices=[],VolumesFrom=None,Links=None,
        LogConfig={'Type':'none'},Mounts=[{'Type':'bind','ReadOnly':True},{'Type':'bind','ReadOnly':True}]))


def test_container_settings_require_all_hardening_not_just_resource_flags():
    verify=module().verify_inspect
    assert verify(inspect_proof())
    for key in inspect_proof()['HostConfig']:
        bad=inspect_proof(); del bad['HostConfig'][key]
        assert not verify(bad),key
    for change in (dict(Privileged=True),dict(PidMode='host'),dict(NetworkMode='bridge'),
                   dict(MemorySwap=805306368),dict(CapAdd=['SYS_ADMIN']),dict(Binds=['/var/run/docker.sock:/docker.sock'])):
        bad=inspect_proof(); bad['HostConfig'].update(change)
        assert not verify(bad)


def test_completed_probe_evidence_survives_cleanup_failure(host, tmp_path, monkeypatch):
    api=module(); value=host[0]
    monkeypatch.setattr(api,'ProbeHost',lambda **kw: value)
    monkeypatch.setattr(value,'capture',lambda *a,**kw: dict(reason='completed',output=json.dumps(isolation_proof()).encode(),observed_pids=0,elapsed=.1))
    monkeypatch.setattr(value,'cleanup',lambda *a: (_ for _ in ()).throw(RuntimeError('synthetic cleanup failure')))
    result=api.run_probe(tmp_path/'new-run',docker=Path('/synthetic/docker'),endpoint=ENDPOINT,daemon_id=DAEMON,image_id=IMAGE)
    assert result['status']=='blocked'
    assert len(result['cases'])==1
    assert result['cases'][0]['mode']=='isolation'
    assert result['cases'][0]['proof']['authenticated_mock']==200
    assert result['cleanup'][0]['removed'] is False


@pytest.mark.parametrize('failure', [subprocess.TimeoutExpired('synthetic-create',1), KeyboardInterrupt()])
def test_uncertain_create_recovers_owned_object_before_caller_cleanup(host, monkeypatch, failure):
    value,daemon,*_=host
    real=daemon.run
    def create_then_fail(args,**kw):
        result=real(args,**kw)
        if args[3]=='create': raise failure
        return result
    monkeypatch.setattr(module().subprocess,'run',create_then_fail)
    with pytest.raises(type(failure)): create(host)
    assert CID in value.owned
    assert value.cleanup(CID)['removed']
    assert not daemon.objects


def test_uncertain_create_never_adopts_foreign_name(host, monkeypatch):
    value,daemon,*_=host
    real=daemon.run
    def create_foreign(args,**kw):
        result=real(args,**kw)
        if args[3]=='create':
            daemon.objects[CID]['Config']['Labels']['myink.pi.operation']='foreign'
            raise subprocess.TimeoutExpired('synthetic-create',1)
        return result
    monkeypatch.setattr(module().subprocess,'run',create_foreign)
    with pytest.raises(RuntimeError): create(host)
    assert not value.owned
    assert daemon.objects[CID]['State']['Running']
    assert not any(c[0] in ('kill','rm') for c in daemon.commands)


def test_attach_start_error_cleans_created_object_and_records_failure(host,tmp_path,monkeypatch):
    api=module(); value=host[0]
    monkeypatch.setattr(api,'ProbeHost',lambda **kw:value)
    def fail_start(*a,**kw): raise OSError('synthetic failed attach')
    monkeypatch.setattr(api.subprocess,'Popen',fail_start)
    result=api.run_probe(tmp_path/'new-run',docker=Path('/synthetic/docker'),endpoint=ENDPOINT,daemon_id=DAEMON,image_id=IMAGE)
    assert result['status']=='blocked' and result['failure_class']=='OSError'
    assert len(result['cases'])==1 and result['cases'][0]['mode']=='isolation'
    assert result['cleanup'][0]['removed'] and not host[1].objects


def test_invalid_worker_json_keeps_bounded_raw_evidence_and_cleans(host,tmp_path,monkeypatch):
    api=module(); value=host[0]
    monkeypatch.setattr(api,'ProbeHost',lambda **kw:value)
    monkeypatch.setattr(value,'capture',lambda *a,**kw:dict(reason='completed',output=b'invalid-json',observed_pids=0,elapsed=.1))
    root=tmp_path/'new-run'
    result=api.run_probe(root,docker=Path('/synthetic/docker'),endpoint=ENDPOINT,daemon_id=DAEMON,image_id=IMAGE)
    assert result['status']=='blocked' and result['failure_class']=='JSONDecodeError'
    assert len(result['cases'])==1 and result['cases'][0]['passed'] is False
    assert (root/'isolation.stdout').read_bytes()==b'invalid-json'
    assert result['cleanup'][0]['removed'] and not host[1].objects


def test_low_guest_headroom_stops_before_any_pressure_subprocess(monkeypatch):
    import importlib.util
    path=Path(__file__).parents[1]/'lab/container_probe_worker.py'
    spec=importlib.util.spec_from_file_location('containment_worker',path)
    worker=importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
    real=Path.read_text
    def read(path,*a,**kw):
        return 'MemAvailable: 1024 kB\n' if str(path)=='/proc/meminfo' else real(path,*a,**kw)
    monkeypatch.setattr(Path,'read_text',read)
    monkeypatch.setattr(worker.subprocess,'Popen',lambda *a,**kw:pytest.fail('low memory still started pressure'))
    with pytest.raises(RuntimeError,match='headroom'): worker.resources()


def test_delayed_create_is_reconciled_and_cleaned(host, monkeypatch):
    value,daemon,*_=host
    real=daemon.run
    delayed={}
    def run(args,**kw):
        if args[3]=='inspect' and delayed:
            result=real(args,**kw)
            daemon.objects.update(delayed); delayed.clear()
            return result
        result=real(args,**kw)
        if args[3]=='create':
            delayed.update(daemon.objects); daemon.objects.clear()
            raise subprocess.TimeoutExpired('create',1)
        return result
    monkeypatch.setattr(module().subprocess,'run',run)
    with pytest.raises(subprocess.TimeoutExpired): create(host)
    assert value.pending
    value.reconcile()
    assert not value.pending and CID in value.owned
    assert value.cleanup(CID)['removed'] and not daemon.objects


def test_unknown_create_keeps_recoverable_identity_in_receipt(host,tmp_path,monkeypatch):
    api=module(); value,daemon,*_=host
    real=daemon.run
    def run(args,**kw):
        if args[3]=='create': raise subprocess.TimeoutExpired('create',1)
        return real(args,**kw)
    monkeypatch.setattr(api.subprocess,'run',run)
    monkeypatch.setattr(api,'ProbeHost',lambda **kw:value)
    result=api.run_probe(tmp_path/'uncertain',docker=Path('/synthetic/docker'),endpoint=ENDPOINT,daemon_id=DAEMON,image_id=IMAGE)
    assert result['status']=='blocked'
    unresolved=result['cleanup'][0]
    assert unresolved['removed'] is False and unresolved['name'].startswith('myink-pi-probe-')
    assert unresolved['operation_id']==value.operation_id and value.pending


def test_top_uses_remaining_capture_deadline(host,monkeypatch):
    import time
    api=module(); cid=create(host,'timeout'); real=host[1].run
    def run(args,**kw):
        if args[3]=='top':
            time.sleep(kw['timeout'])
            raise subprocess.TimeoutExpired('top',kw['timeout'])
        return real(args,**kw)
    monkeypatch.setattr(api.subprocess,'run',run)
    real_popen=subprocess.Popen
    monkeypatch.setattr(api.subprocess,'Popen',lambda *a,**kw:real_popen(
        [sys.executable,'-I','-S','-c','import time;print("ready",flush=True);time.sleep(3)'],**kw))
    result=host[0].capture(cid,seconds=.15,output_limit=1024)
    assert result['reason']=='timeout' and result['elapsed']<.8
    assert host[1].objects[cid]['State']['Running'] is False


def test_stop_accepts_exit_between_inspect_and_kill_only_after_reinspect(host,monkeypatch):
    value,daemon,*_=host
    cid=create(host)
    original=daemon.run
    def racing(args,**kwargs):
        if args[3:4]==['kill']:
            daemon.objects[cid]['State'].update(Running=False,Pid=0,ExitCode=0)
            return subprocess.CompletedProcess(args,1,'','already stopped')
        return original(args,**kwargs)
    monkeypatch.setattr(module().subprocess,'run',racing)
    assert value.cleanup(cid)['removed']
    assert not daemon.objects


def test_stop_still_rejects_failed_kill_with_running_namespace(host,monkeypatch):
    value,daemon,*_=host
    cid=create(host);original=daemon.run
    def denied(args,**kwargs):
        if args[3:4]==['kill']:return subprocess.CompletedProcess(args,1,'','denied')
        return original(args,**kwargs)
    monkeypatch.setattr(module().subprocess,'run',denied)
    with pytest.raises(RuntimeError):value.stop(cid)
    assert cid in value.owned
