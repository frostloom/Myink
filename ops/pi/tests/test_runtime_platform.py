"""Host-pinned runtime architecture, not acceptance of either worker claim."""
from copy import deepcopy
import importlib
from pathlib import Path
import pytest
from ops.pi import container_runtime as runtime
from ops.pi.tests.test_container_runtime import source_fixture,valid_result
from ops.pi.tests.test_analysis_trial_result import case
from ops.pi import analysis_trial_result
from ops.pi import container_probe
from ops.pi.tests.test_container_probe import DAEMON,ENDPOINT,IMAGE


def platform_api():
    assert importlib.util.find_spec('ops.pi.runtime_platform'), 'runtime platform binding missing'
    return importlib.import_module('ops.pi.runtime_platform')

def elf(machine=62):
    raw=bytearray(64);raw[:7]=b'\x7fELF\x02\x01\x01'
    raw[16:18]=(2).to_bytes(2,'little');raw[18:20]=machine.to_bytes(2,'little')
    raw[20:24]=(1).to_bytes(4,'little');raw[52:54]=(64).to_bytes(2,'little')
    return raw

@pytest.mark.parametrize('machine,expected',[(62,'x86_64'),(183,'aarch64')])
def test_source_provenance_pins_real_shaped_node_architecture(tmp_path,monkeypatch,machine,expected):
    source,_=source_fixture(tmp_path,monkeypatch)
    (source/'node/bin/node').write_bytes(elf(machine))
    proof=runtime.verify_source(source,runtime.runtime_fingerprint(source))
    assert proof['machine']==expected

@pytest.mark.parametrize('offset,value',[(0,0),(4,1),(5,2),(6,0),(7,9),(16,1),(18,3),(20,0),(52,0)])
def test_malformed_or_unsupported_elf_is_not_accepted(tmp_path,monkeypatch,offset,value):
    source,_=source_fixture(tmp_path,monkeypatch);raw=elf(183);raw[offset]=value
    (source/'node/bin/node').write_bytes(raw)
    with pytest.raises(ValueError):runtime.verify_source(source,runtime.runtime_fingerprint(source))

@pytest.mark.parametrize('length',[0,4,19,20,63])
def test_truncated_elf_fails_closed(tmp_path,monkeypatch,length):
    source,_=source_fixture(tmp_path,monkeypatch);(source/'node/bin/node').write_bytes(elf(183)[:length])
    with pytest.raises(ValueError):runtime.verify_source(source,runtime.runtime_fingerprint(source))

@pytest.mark.parametrize('abi',[0,3])
@pytest.mark.parametrize('kind',[2,3])
def test_linux_supported_abi_and_exec_or_pie(tmp_path,abi,kind):
    raw=elf(62);raw[7]=abi;raw[16:18]=kind.to_bytes(2,'little');p=tmp_path/'node';p.write_bytes(raw)
    assert platform_api().node_machine(p)=='x86_64'

@pytest.mark.parametrize('value,expected',[('arm64','aarch64'),('aarch64','aarch64'),('amd64','x86_64'),('x86_64','x86_64')])
def test_daemon_machine_aliases_are_closed(value,expected):assert platform_api().canonical_machine(value)==expected

@pytest.mark.parametrize('value',['AMD64','x86','armv7l','',None,[],True])
def test_unknown_machine_is_not_an_implicit_native_alias(value):
    with pytest.raises(ValueError):platform_api().canonical_machine(value)

@pytest.mark.parametrize('machine',['aarch64','x86_64'])
def test_analysis_frame_requires_matching_explicit_machine(tmp_path,machine):
    frame,slot,view,report=valid_result(tmp_path);frame['runtime']['machine']=machine
    assert runtime.verify_result(frame,slot,view,report,expected_machine=machine)['contract_valid']
    other='x86_64' if machine=='aarch64' else 'aarch64'
    with pytest.raises(ValueError):runtime.verify_result(frame,slot,view,report,expected_machine=other)

def test_old_analysis_default_never_silently_accepts_x86_frame(tmp_path):
    frame,slot,view,report=valid_result(tmp_path);frame['runtime']['machine']='x86_64'
    with pytest.raises(ValueError):runtime.verify_result(frame,slot,view,report)

@pytest.mark.parametrize('machine',['aarch64','x86_64'])
def test_full_trial_frame_uses_same_host_pin(case,machine):
    frame,slot,view,report=case;frame['runtime']['machine']=machine
    assert analysis_trial_result.verify_trial_result(frame,slot,view,report,expected_machine=machine)['contract_valid']
    other='x86_64' if machine=='aarch64' else 'aarch64'
    with pytest.raises(ValueError):analysis_trial_result.verify_trial_result(frame,slot,view,report,expected_machine=other)

def test_full_trial_default_remains_arm(case):
    case[0]['runtime']['machine']='x86_64'
    with pytest.raises(ValueError):analysis_trial_result.verify_trial_result(*case)

@pytest.mark.parametrize('expected',['amd64','arm64','',None,[]])
def test_verifier_expected_pin_is_canonical_and_not_worker_selected(tmp_path,expected):
    frame,slot,view,report=valid_result(tmp_path)
    with pytest.raises(ValueError):runtime.verify_result(frame,slot,view,report,expected_machine=expected)

@pytest.mark.parametrize('native',['x86_64','amd64'])
def test_model_host_checks_native_architecture_before_container_side_effects(monkeypatch,native):
    h=container_probe.ProbeHost(docker=Path('/synthetic/docker'),endpoint=ENDPOINT,daemon_id=DAEMON,image_id=IMAGE,operation_id='00000000-0000-4000-8000-000000000001',expected_machine='x86_64')
    calls=[]
    def call(*args,**kw):
        calls.append(args);return type('Reply',(),dict(stdout=DAEMON if args[-1]=='{{.ID}}' else native))()
    monkeypatch.setattr(h,'_call',call);h._daemon()
    assert calls==[('info','--format','{{.ID}}'),('info','--format','{{.Architecture}}')]

@pytest.mark.parametrize('native',['aarch64','arm64','unknown'])
def test_wrong_native_arch_stops_before_create(monkeypatch,tmp_path,native):
    h=container_probe.ProbeHost(docker=Path('/synthetic/docker'),endpoint=ENDPOINT,daemon_id=DAEMON,image_id=IMAGE,operation_id='00000000-0000-4000-8000-000000000002',expected_machine='x86_64')
    calls=[]
    def call(*args,**kw):
        calls.append(args);assert args[0]=='info'
        return type('Reply',(),dict(stdout=DAEMON if args[-1]=='{{.ID}}' else native))()
    monkeypatch.setattr(h,'_call',call);worker=tmp_path/'worker.py';worker.write_text('trusted')
    with pytest.raises(RuntimeError,match='architecture'):h.create('isolation',worker=worker,source=tmp_path,foreign=tmp_path/'absent')
    assert not h.owned and not h.pending and all(c[0]=='info' for c in calls)

def test_generic_checker_host_keeps_old_id_only_semantics(monkeypatch):
    h=container_probe.ProbeHost(docker=Path('/synthetic/docker'),endpoint=ENDPOINT,daemon_id=DAEMON,image_id=IMAGE,operation_id='00000000-0000-4000-8000-000000000003')
    calls=[]
    def call(*args,**kw):calls.append(args);return type('Reply',(),dict(stdout=DAEMON))()
    monkeypatch.setattr(h,'_call',call);h._daemon();assert len(calls)==1


from ops.pi.tests.test_development_inputs import config_file
from ops.pi.tests.test_selection_launcher import selection_config
from ops.pi.tests.test_analysis_launcher import setup as analysis_setup

class EmptyHost:
    owned={};pending={};operation_id='synthetic'
    def reconcile(self): pass
    def _daemon(self): pass
    def _call(self,*a): return type('Output',(),{'stdout':''})()

def test_development_model_host_receives_source_machine(config_file,monkeypatch):
    from ops.pi import development_launcher as dev,development_inputs
    cp,c=config_file;seen=[]
    monkeypatch.setattr(development_inputs,'verify_source',lambda *a:{'machine':'x86_64'})
    def host(config,image,machine=None):seen.append((image,machine));return EmptyHost()
    monkeypatch.setattr(dev,'_host',host)
    def stop(*a,**k):raise RuntimeError('synthetic before provider')
    monkeypatch.setattr(dev,'_exchange',stop)
    result=dev.execute(cp,transport=lambda *a:None)
    assert seen==[('image_id','x86_64')] and result['new_attempts']==0 and result['policy_restored']

def test_selection_model_host_receives_source_machine(selection_config,monkeypatch):
    import time
    from ops.pi import selection_launcher as selection
    cp,c,catalog=selection_config;seen=[]
    monkeypatch.setattr(selection,'verify_source',lambda *a:{'machine':'x86_64'})
    def host(config,image,machine=None):
        if machine is not None:seen.append((image,machine))
        return EmptyHost()
    monkeypatch.setattr(selection,'_host',host)
    def stop(*a,**k):raise RuntimeError('synthetic before provider')
    monkeypatch.setattr(selection,'_exchange',stop)
    context=dict(mode='SIMULATED',source_sha256=c['source_sha256'],tasks=catalog,input_hash='c'*64,deadline=time.monotonic()+90)
    result=selection.execute(cp,context,transport=lambda *a:None)
    assert seen==[('image_id','x86_64')] and result['new_attempts']==0 and result['policy_restored']

@pytest.mark.parametrize('trial',[False,True])
def test_analysis_launcher_really_propagates_native_x86_frame_pin(analysis_setup,monkeypatch,trial):
    from ops.pi.tests import test_analysis_launcher as pilot,test_analysis_full_trial as full
    config,ledger,_,_,_=analysis_setup
    (Path(config['source'])/'node/bin/node').write_bytes(elf(62))
    config['runtime_sha256']=runtime.runtime_fingerprint(Path(config['source']))
    monkeypatch.setattr(pilot,'CHILD',pilot.CHILD.replace("machine='aarch64'","machine='x86_64'"))
    if trial:
        processes,calls,daemon=full.install(monkeypatch);config=full.trial_config(config);expected=30
    else:
        processes,calls,daemon=pilot.install_external_boundaries(monkeypatch);expected=2
    daemon.machine='x86_64'
    result=pilot.api().launch(config,execute=True)
    assert result['status']=='completed' and len(calls)==len(processes)==expected
    assert not daemon.objects and all(p.poll()==0 for p in processes)
    assert all(row['runtime']['machine']=='x86_64' for row in result['cases'])
