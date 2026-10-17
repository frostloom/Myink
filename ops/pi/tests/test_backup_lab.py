"""Finite handler lifecycle regression; SQLite/artifacts real, source boundary doubled."""
from types import SimpleNamespace
from ops.pi.tests.test_backup import case,artifacts


def test_fresh_creator_verification_then_first_pre_before_restore(case,monkeypatch):
    from ops.pi.lab import backup_lab as lab
    ledger,identity,pair,root=case;trace=[]
    monkeypatch.setattr(lab,'verify_test_environment',lambda:({},{}))
    monkeypatch.setattr(lab,'initialize_source',lambda:trace.append('initialize'))
    def historical():raise AssertionError('fresh current creator routed to historical failed/PRE observer')
    monkeypatch.setattr(lab,'observe_source',historical)
    monkeypatch.setattr(lab,'observe_created_source',lambda **kw:trace.append('current_creator_verified'),raising=False)
    monkeypatch.setattr(lab,'identities',lambda:(identity,None,pair))
    monkeypatch.setattr(lab,'COLLECTIONS',root)
    class Boundary:
        def __init__(self):self.ledger=ledger
        def __call__(self,action,context):return artifacts(action,context)
    monkeypatch.setattr(lab,'get_boundary',lambda **kw:Boundary())
    def restore_run(*args,**kwargs):
        assert ledger.get('backup:release-1:PRE')['status']=='done'
        trace.append('first_pre_then_restore');return SimpleNamespace(returncode=0)
    monkeypatch.setattr(lab.subprocess,'run',restore_run)
    lab.prepare('b11-source')
    assert trace==['initialize','current_creator_verified','first_pre_then_restore']


def test_corruption_probe_uses_matching_canonical_candidate(case,monkeypatch):
    from ops.pi.lab import backup_fresh as fresh
    from ops.pi.tests.test_backup import backup,CONTEXT,NOW
    ledger,identity,pair,_=case;backup(case)
    monkeypatch.setattr(fresh.lab,'identities',lambda:(None,identity,None))
    def mark(ledger,pair_id,candidate,**kwargs):
        assert candidate==pair['post_identity'],'probe rejected wrong candidate before testing collection corruption'
        raise ValueError('actual collection corruption blocks gate')
    monkeypatch.setattr(fresh,'mark_released',mark)
    assert fresh.assert_corrupt_pre_refuses_release(ledger,pair['release_pair_id'],CONTEXT,NOW)


def test_preparation_failure_closes_prior_current_rehearsal(case,monkeypatch):
    import pytest
    from ops.pi.lab import backup_lab as lab
    from ops.pi.tests.test_backup import qualified_restore,CONTEXT,api
    ledger,pre,pair,root=case;qualified_restore(case);trace=[]
    assert api().release_allowed(ledger,pair['release_pair_id'],context=CONTEXT)
    class Boundary:
        def __init__(self):self.ledger=ledger
        def __call__(self,action,context):return artifacts(action,context)
        def new_target(self,*args):trace.append('preparation_failed');raise ValueError('fixed readiness failure before actual target identity')
        def stop_owned_target(self,status):trace.append('cleanup:'+status)
    monkeypatch.setattr(lab,'get_boundary',lambda:Boundary())
    monkeypatch.setattr(lab,'identities',lambda:(pre,None,pair))
    monkeypatch.setattr(lab,'rehearsal_context',lambda:CONTEXT)
    monkeypatch.setattr(lab,'COLLECTIONS',root)
    monkeypatch.setattr(lab,'current_operation',lambda:'ef92d9a8-dc88-48d1-bd33-bc3a158a2c31')
    with pytest.raises(ValueError,match='fixed readiness'):lab.run_actual_pair()
    assert trace==['preparation_failed','cleanup:failed']
    assert not api().release_allowed(ledger,pair['release_pair_id'],context=CONTEXT),'prior success remained qualified after real handler preparation failure'
    with pytest.raises(ValueError):api().mark_released(ledger,pair['release_pair_id'],pair['post_identity'],context=CONTEXT)
    assert api().release_allowed(ledger,pair['release_pair_id'],recovery=True)


def test_planned_attempt_precedes_verified_target_and_terminal_receipt(case,monkeypatch):
    import json
    from pathlib import Path
    from ops.pi.lab import backup_lab as lab
    from ops.pi.tests.test_backup import qualified_restore,CONTEXT,api
    from ops.pi.contracts import Receipt
    ledger,_,pair,_=case;receipt=qualified_restore(case)
    previous=ledger.get('restore-check:restore:'+receipt.evidence['backup_id']+':target-PRE')
    monkeypatch.setattr(lab,'current_operation',lambda:'ef92d9a8-dc88-48d1-bd33-bc3a158a2c31')
    class Boundary:
        def __init__(self):self.ledger=ledger
        def new_target(self,collection,fault):
            with ledger.transaction() as db:attempt=ledger._record(db.execute("SELECT * FROM operations WHERE kind='restore_check' ORDER BY rowid DESC LIMIT 1").fetchone())
            assert attempt['status']=='pending' and 'planned_target' in attempt['payload'] and 'system_identifier' not in attempt['payload']['planned_target']
            assert not api().release_allowed(ledger,pair['release_pair_id'],context=CONTEXT)
            planned=attempt['payload']['planned_target'];target_operation='restore-target:'+planned['case_uuid']
            ledger.intent(target_operation,'restore_target',planned)
            ledger.append_event('restore_target_created',{'target_operation':target_operation,'container_id':'synthetic-boundary-container','registry_sha256':'synthetic-registry'})
            self.target_operation=target_operation
            return {'clean':True,'system_identifier':'verified-target','source_system_identifier':'source','target_operation':target_operation,'container_id':'synthetic-boundary-container','collection_directory':str(collection)}
        def __call__(self,action,context):return {'verified':True,'target_system_identifier':context['target']['system_identifier'],'assertions':['protocol-double']}
        def stop_owned_target(self,status):ledger.finish(Receipt(self.target_operation,status,{'scope':'protocol-double'}))
    path=Path(receipt.evidence['manifest_path']);result=lab.rehearse_collection(Boundary(),receipt,path.parent,json.loads(path.read_text()),CONTEXT)
    assert result.status=='done' and api().release_allowed(ledger,pair['release_pair_id'],context=CONTEXT)
    assert ledger.get(previous['operation_id'])==previous
    with ledger.transaction() as db:
        events=[(row['kind'],json.loads(row['payload'])) for row in db.execute('SELECT * FROM events ORDER BY id')]
    planned=next(n for n,(kind,payload) in enumerate(events) if kind=='intent' and 'planned_target' in payload.get('payload',{}))
    verified=next(n for n,(kind,_) in enumerate(events) if kind=='rehearsal_target_verified')
    completed=next(n for n,(kind,payload) in enumerate(events) if kind=='receipt' and payload['operation_id'].startswith('restore-check:attempt:'))
    assert planned<verified<completed


def test_cleanup_unknown_closes_verified_import_attempt(case,monkeypatch):
    import json,pytest
    from pathlib import Path
    from ops.pi.lab import backup_lab as lab
    from ops.pi.tests.test_backup import qualified_restore,CONTEXT,api
    ledger,_,pair,_=case;receipt=qualified_restore(case)
    monkeypatch.setattr(lab,'current_operation',lambda:'ef92d9a8-dc88-48d1-bd33-bc3a158a2c31')
    class Boundary:
        def __init__(self):self.ledger=ledger
        def new_target(self,collection,fault):
            with ledger.transaction() as db:attempt=ledger._record(db.execute("SELECT * FROM operations WHERE kind='restore_check' ORDER BY rowid DESC LIMIT 1").fetchone())
            planned=attempt['payload']['planned_target'];operation='restore-target:'+planned['case_uuid'];ledger.intent(operation,'restore_target',planned)
            ledger.append_event('restore_target_created',{'target_operation':operation,'container_id':'protocol-container','registry_sha256':'protocol-registry'})
            return {'clean':True,'system_identifier':'target','source_system_identifier':'source','target_operation':operation,'container_id':'protocol-container','collection_directory':str(collection)}
        def __call__(self,action,context):return {'verified':True,'target_system_identifier':'target'}
        def stop_owned_target(self,status):raise OSError('cleanup cannot prove terminal ownership')
    path=Path(receipt.evidence['manifest_path'])
    with pytest.raises(OSError):lab.rehearse_collection(Boundary(),receipt,path.parent,json.loads(path.read_text()),CONTEXT)
    with ledger.transaction() as db:attempt=ledger._record(db.execute("SELECT * FROM operations WHERE kind='restore_check' ORDER BY rowid DESC LIMIT 1").fetchone())
    assert attempt['status']=='uncertain' and not api().release_allowed(ledger,pair['release_pair_id'],context=CONTEXT)
    assert api().release_allowed(ledger,pair['release_pair_id'],recovery=True)



def test_protocol_probe_retains_partial_output_on_child_timeout(tmp_path,monkeypatch):
    import hashlib,json,subprocess,pytest
    from collections import namedtuple
    from ops.pi.lab import backup_probe as probe
    native=tmp_path/'native';private=tmp_path/'private';(private/'evidence').mkdir(parents=True);(private/'state').mkdir()
    source=native/'trusted-source';frozen={}
    for name in probe.SOURCE_FILES:
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixed synthetic unit bytes');frozen[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (private/'evidence/b11-fix2-source.json').write_bytes(probe.encoded(frozen))
    spec={'scope':'synthetic_protocol_fixture','new_peak_bytes':64*1024**2,'reserve_bytes':5*1024**3,'tests':['fixed-protocol-unit']}
    raw=probe.encoded(spec);(private/'evidence'/probe.SPEC_NAME).write_bytes(raw)
    operation='91b985ca-62df-4233-bdf9-7ec18c001dd0'
    monkeypatch.setattr(probe,'PRIVATE',private);monkeypatch.setattr(probe,'BASE',native);monkeypatch.setattr(probe,'SPEC_SHA256',hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(probe,'current_operation',lambda:operation)
    monkeypatch.setattr(probe,'verify_test_environment',lambda:({},{}));monkeypatch.setattr(probe,'historical_binding',lambda spec:{'scope':'historical-source-double','new_actual_restores':0})
    monkeypatch.setattr(probe,'native_filesystem',lambda spec:{'scope':'filesystem-boundary-double'})
    monkeypatch.setattr(probe,'sample_resources',lambda group:{'scope':'kernel-boundary-double'})
    Disk=namedtuple('Disk','total used free');monkeypatch.setattr(probe.shutil,'disk_usage',lambda path:Disk(100*1024**3,0,100*1024**3))
    def timeout(command,**kwargs):
        if hasattr(kwargs['stdout'],'write'):kwargs['stdout'].write(b'fixed partial protocol output');kwargs['stdout'].flush()
        raise subprocess.TimeoutExpired(command,1,output=b'fixed partial protocol output')
    monkeypatch.setattr(probe.subprocess,'run',timeout)
    with pytest.raises(subprocess.TimeoutExpired):probe.run_protocol_probe()
    root=private/'evidence'/('b11-fix2-'+operation)
    assert (root/'stdout.txt').read_bytes()==b'fixed partial protocol output','timeout lost already emitted diagnostics'
    assert json.loads((root/'receipt.json').read_text())['status']=='failed'



def test_protocol_workspace_is_fixed_native_and_refuses_preexisting(tmp_path,monkeypatch):
    import pytest
    from ops.pi.lab import backup_probe as probe
    monkeypatch.setattr(probe,'BASE',tmp_path)
    operation='91b985ca-62df-4233-bdf9-7ec18c001dd0';root=probe.protocol_workspace(operation)
    assert root==tmp_path/('b11-protocol-'+operation)
    with pytest.raises(FileExistsError):probe.protocol_workspace(operation)
    with pytest.raises(ValueError):probe.protocol_workspace('../foreign')



def test_native_filesystem_refuses_foreign_distribution(tmp_path,monkeypatch):
    import hashlib,json,pytest
    from types import SimpleNamespace
    from ops.pi.lab import backup_probe as probe
    private=tmp_path/'private';(private/'evidence').mkdir(parents=True)
    proof={'distribution':'foreign','base_path':'/Users/a1/项目/Myink/myink-pi/runtime/wsl','root_filesystem':{'major_minor':'8:80','fs_type':'ext4','source':'/dev/sdf'}}
    path=private/'evidence/b11-fix2-filesystem.json';raw=probe.encoded(proof);path.write_bytes(raw)
    RealPath=probe.Path
    monkeypatch.setattr(probe,'PRIVATE',private)
    monkeypatch.setattr(probe,'Path',lambda value:SimpleNamespace(read_text=lambda:'80 1 8:80 / / rw - ext4 /dev/sdf rw') if value=='/proc/self/mountinfo' else RealPath(value))
    with pytest.raises(ValueError,match='foreign native filesystem'):probe.native_filesystem({'filesystem_proof_sha256':hashlib.sha256(raw).hexdigest()})
    with pytest.raises(ValueError,match='proof drift'):probe.native_filesystem({'filesystem_proof_sha256':'0'*64})


def test_protocol_archive_verifies_members_and_preserves_native(tmp_path):
    import json,tarfile
    from ops.pi.lab import backup_probe as probe
    work=tmp_path/'native';work.mkdir();(work/'data').mkdir();path=work/'data/artifact.bin';path.write_bytes(b'fixed protocol bytes')
    root=tmp_path/'evidence';root.mkdir()
    result=probe.retain_protocol_files(work,root,64*1024**2)
    inventory=json.loads((root/'native-copy-manifest.json').read_text())
    assert inventory['data/artifact.bin']['sha256']==probe.digest(path)
    archive=root/'native-fixture.tar'
    assert result['archive_sha256']==probe.digest(archive) and path.read_bytes()==b'fixed protocol bytes'
    with tarfile.open(archive) as retained:
        assert sorted(m.name for m in retained)==['data','data/artifact.bin']
        assert retained.extractfile('data/artifact.bin').read()==path.read_bytes()
    assert not (root/'native-copy').exists()


def test_protocol_archive_refuses_hardlink_or_budget(tmp_path):
    import os,pytest
    from ops.pi.lab import backup_probe as probe
    work=tmp_path/'native';work.mkdir();path=work/'artifact.bin';path.write_bytes(b'fixed')
    root=tmp_path/'evidence';root.mkdir();os.link(path,work/'alias')
    with pytest.raises(ValueError,match='unsafe protocol entry'):probe.retain_protocol_files(work,root,64*1024**2)
    assert not (root/'native-fixture.tar').exists()
    (work/'alias').unlink()
    with pytest.raises(ValueError,match='footprint'):probe.retain_protocol_files(work,root,1)
    assert not (root/'native-fixture.tar').exists()


def test_protocol_tmp_fixture_has_no_alias_and_refuses_unknown_or_duplicate(tmp_path,monkeypatch):
    import hashlib,pytest
    from ops.pi.lab import backup_probe as probe
    private=tmp_path/'private';(private/'evidence').mkdir(parents=True)
    nodeid='fixed.py::test_fixed';spec={'tests':[nodeid]};raw=probe.encoded(spec)
    (private/'evidence'/probe.SPEC_NAME).write_bytes(raw)
    monkeypatch.setattr(probe,'PRIVATE',private);monkeypatch.setattr(probe,'BASE',tmp_path)
    monkeypatch.setattr(probe,'SPEC_SHA256',hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(probe,'verify_test_environment',lambda:({},{}));monkeypatch.setattr(probe,'native_filesystem',lambda spec:{})
    operation='91b985ca-62df-4233-bdf9-7ec18c001dd0';monkeypatch.setattr(probe,'current_operation',lambda:operation)
    work=probe.protocol_workspace(operation)
    directory=probe.protocol_temporary_directory(nodeid)
    assert directory.parent==work/'fixtures' and directory.is_dir()
    assert all(not path.is_symlink() for path in work.rglob('*'))
    with pytest.raises(FileExistsError):probe.protocol_temporary_directory(nodeid)
    with pytest.raises(ValueError,match='unknown protocol node'):probe.protocol_temporary_directory(nodeid+'[foreign]')
    monkeypatch.setattr(probe,'SPEC_SHA256','0'*64)
    with pytest.raises(ValueError,match='spec drift'):probe.protocol_temporary_directory(nodeid)


def test_protocol_tmp_fixture_refuses_changed_operation_and_foreign_root(tmp_path,monkeypatch):
    import hashlib,pytest
    from ops.pi.lab import backup_probe as probe
    private=tmp_path/'private';(private/'evidence').mkdir(parents=True)
    nodeid='fixed.py::test_fixed';raw=probe.encoded({'tests':[nodeid]})
    (private/'evidence'/probe.SPEC_NAME).write_bytes(raw)
    monkeypatch.setattr(probe,'PRIVATE',private);monkeypatch.setattr(probe,'BASE',tmp_path)
    monkeypatch.setattr(probe,'SPEC_SHA256',hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(probe,'verify_test_environment',lambda:({},{}));monkeypatch.setattr(probe,'native_filesystem',lambda spec:{})
    operation='91b985ca-62df-4233-bdf9-7ec18c001dd0';monkeypatch.setattr(probe,'current_operation',lambda:operation)
    work=probe.protocol_workspace(operation)
    monkeypatch.setattr(probe,'current_operation',lambda:'4b54b4a9-7207-4b49-830f-08306b33b1b0')
    with pytest.raises(FileNotFoundError):probe.protocol_temporary_directory(nodeid)
    monkeypatch.setattr(probe,'current_operation',lambda:operation)
    monkeypatch.setattr(probe,'native_filesystem',lambda spec:(_ for _ in ()).throw(ValueError('foreign native filesystem')))
    with pytest.raises(ValueError,match='foreign'):probe.protocol_temporary_directory(nodeid)
    assert not (work/'fixtures').exists()


def protocol_harness(tmp_path,monkeypatch,after):
    import copy,hashlib,subprocess
    from collections import namedtuple
    from ops.pi.lab import backup_probe as probe
    native=tmp_path/'native';private=tmp_path/'private';(private/'evidence').mkdir(parents=True);(private/'state').mkdir()
    source=native/'trusted-source';frozen={}
    for name in probe.SOURCE_FILES:
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixed synthetic unit bytes');frozen[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (private/'evidence/b11-fix2-source.json').write_bytes(probe.encoded(frozen))
    raw=probe.encoded({'scope':'synthetic_protocol_fixture','new_peak_bytes':64*1024**2,'reserve_bytes':5*1024**3,'tests':['fixed-protocol-unit']})
    (private/'evidence'/probe.SPEC_NAME).write_bytes(raw)
    operation='91b985ca-62df-4233-bdf9-7ec18c001dd0'
    monkeypatch.setattr(probe,'PRIVATE',private);monkeypatch.setattr(probe,'BASE',native);monkeypatch.setattr(probe,'SPEC_SHA256',hashlib.sha256(raw).hexdigest());monkeypatch.setattr(probe,'current_operation',lambda:operation)
    before={'lab_uuid':'fixed-lab','containers':['fixed-container'],'configuration':{'fixed':'config'}}
    for group in ('heavy_proof','infra_proof','agent_proof','kernel_proof'):
        before[group]={'cpu.max':'200000 100000','memory.max':'1610612736','memory.swap.max':'268435456','path':'fixed-cgroup','target_id':'fixed-target','membership_verified':True,'ancestor_verified':True,'cpu.stat':'usage_usec 1','memory.current':'100','pids':[1],'sample_attempts':1,'vanished_pids':[],'memory.events':'oom 0','memory.peak':'100'}
    final=copy.deepcopy(before)
    for group in ('heavy_proof','infra_proof','agent_proof','kernel_proof'):
        final[group].update({'cpu.stat':'usage_usec 2','memory.current':'110','pids':[1,2],'sample_attempts':2,'vanished_pids':[3],'memory.events':'oom 0','memory.peak':'120'})
    after(final)
    snapshots=iter([before,final]);monkeypatch.setattr(probe,'verify_test_environment',lambda:(next(snapshots),{}))
    monkeypatch.setattr(probe,'historical_binding',lambda spec:{'scope':'historical-source-double','new_actual_restores':0});monkeypatch.setattr(probe,'native_filesystem',lambda spec:{'scope':'filesystem-boundary-double'})
    monkeypatch.setattr(probe,'sample_resources',lambda group:{'scope':'kernel-boundary-double'})
    Disk=namedtuple('Disk','total used free');monkeypatch.setattr(probe.shutil,'disk_usage',lambda path:Disk(100*1024**3,0,100*1024**3))
    def successful(command,**kwargs):kwargs['stdout'].write(b'fixed successful protocol output');return subprocess.CompletedProcess(command,0)
    monkeypatch.setattr(probe.subprocess,'run',successful)
    return probe,private/'evidence'/('b11-fix2-'+operation)


def test_protocol_final_guard_allows_observation_change(tmp_path,monkeypatch):
    import json
    probe,root=protocol_harness(tmp_path,monkeypatch,lambda value:None)
    result=probe.run_protocol_probe()
    assert json.loads((root/'receipt.json').read_text())['status']=='done'
    assert result['runtime_before']['heavy_proof']['cpu.stat']!=result['runtime_after']['heavy_proof']['cpu.stat']


import pytest
@pytest.mark.parametrize('drift',['identity','cap','config','unknown_outer','unknown_proof','memory_events','path','membership'])
def test_protocol_final_guard_refuses_safety_or_unknown_drift(tmp_path,monkeypatch,drift):
    import json
    def mutate(value):
        if drift=='identity':value['lab_uuid']='foreign-lab'
        elif drift=='cap':value['heavy_proof']['memory.max']='3221225472'
        elif drift=='config':value['configuration']['fixed']='changed'
        elif drift=='unknown_outer':value['future_authority']='changed'
        elif drift=='memory_events':value['heavy_proof']['memory.events']='oom 1'
        elif drift=='path':value['heavy_proof']['path']='foreign-cgroup'
        elif drift=='membership':value['heavy_proof']['membership_verified']=False
        else:value['heavy_proof']['future_safety_field']='changed'
    probe,root=protocol_harness(tmp_path,monkeypatch,mutate)
    with pytest.raises(ValueError,match='source or historical proof changed'):probe.run_protocol_probe()
    assert json.loads((root/'receipt.json').read_text())['status']=='failed'
