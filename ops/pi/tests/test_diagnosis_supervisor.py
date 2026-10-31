"""Evidence-key claims are durable; audit plans never authorize paid execution."""
from pathlib import Path
from datetime import timedelta
from hashlib import sha256
import fcntl,importlib,json,subprocess,sys
import pytest
from ops.pi.audit import AuditStore,encoded,digest
from ops.pi.tests.test_diagnosis_launcher import diagnosis_config,write
from ops.pi.tests.test_development_inputs import config_file
from ops.pi.tests.test_live_observer import configured,NOW,Rows,run as observe
from ops.pi.development_inputs import file_hash


def api():return importlib.import_module('ops.pi.diagnosis_supervisor')


@pytest.fixture
def registry(diagnosis_config):
    cp,c,e,m,p=diagnosis_config;root=cp.parent/'supervisor';root.mkdir(mode=0o700)
    lock=cp.parent/'maintenance.lock';lock.touch(mode=0o600)
    value=dict(schema='pi-diagnosis-registry-v1',mode='SIMULATED',root=str(root),lock_path=str(lock),
        ledger_path=c['ledger_path'],legacy_unknown_ids=[],observer_config_path=c['observer_config_path'],observer_config_sha256=c['observer_config_sha256'],observer_controller_sha256=c['observer_controller_sha256'],
        audit_path=c['audit_path'],export_root=c['export_root'],entries=[dict(config_path=str(cp),config_sha256=file_hash(cp),evidence_fingerprint=e['evidence_fingerprint'])])
    rp=cp.parent/'diagnosis-registry.json';write(rp,value);return rp,value,diagnosis_config


def launch_result(c,**changes):
    value=dict(schema='pi-diagnosis-result-v1',mode='SIMULATED',run_id=c['run_id'],evidence_fingerprint=json.loads(Path(c['evidence_path']).read_bytes())['evidence_fingerprint'],verified=True,closed_verified=True,new_unknown=0,new_attempts=1,known_cost_microyuan=3)
    value.update(changes);return value


def tick(registry,runner):return api().run(registry[0],file_hash(registry[0]),runner=runner,clock=lambda:NOW)


def test_one_paid_admission_then_cached_across_audit_updates(registry):
    rp,c,(_,launch,*_)=registry;calls=[]
    def runner(cp,pin):calls.append((cp,pin));return launch_result(launch)
    first=tick(registry,runner);assert first['status']=='passed' and len(calls)==1
    for _ in range(2):assert tick(registry,runner)['status']=='cached'
    assert len(calls)==1 and AuditStore(c['audit_path']).events()


@pytest.mark.parametrize('fault',['pending','empty','tampered','new_unknown','bad_config','no_permit','lock','overlap','actual_injection','source_overlap','launch_overlap'])
def test_fail_closed_before_model(registry,fault):
    rp,c,(_,launch,e,*_)=registry;module=api();root=Path(c['root']);claim=root/e['evidence_fingerprint']
    if fault in ('pending','empty','tampered'):
        if fault=='tampered':
            tick(registry,lambda *a:launch_result(launch));next(root.glob('*/receipt.json')).write_text('{}')
        else:
            claim.mkdir(mode=0o700)
            if fault=='pending':write(claim/'intent.json',dict(fingerprint=e['evidence_fingerprint']))
    elif fault=='new_unknown':c['legacy_unknown_ids']=['unrecognized'];write(rp,c)
    elif fault=='bad_config':c['entries'][0]['config_sha256']='f'*64;write(rp,c)
    elif fault=='no_permit':c['entries']=[];write(rp,c)
    elif fault=='overlap':c['export_root']=str(Path(c['ledger_path']).parent);write(rp,c)
    elif fault=='actual_injection':c['mode']='ACTUAL';write(rp,c)
    elif fault=='source_overlap':c['root']=str(Path(launch['observation_receipt_path']).parent.parent);write(rp,c)
    elif fault=='launch_overlap':launch['root']=str(root/'paid-output');write(Path(c['entries'][0]['config_path']),launch);c['entries'][0]['config_sha256']=file_hash(c['entries'][0]['config_path']);write(rp,c)
    lock=None
    if fault=='lock':lock=Path(c['lock_path']).open('a+b');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    calls=[]
    try:
        try:result=tick(registry,lambda *a:calls.append(1) or launch_result(launch))
        except ValueError:result=dict(status='blocked')
    finally:
        if lock:lock.close()
    assert not calls and result['status'] in ('uncertain','blocked','no_permit','lock_busy')


@pytest.mark.parametrize('outcome',['exception','unknown','cleanup','contract'])
def test_attempt_is_never_replayed_and_uncertain_execution_freezes_new_work(registry,outcome):
    _,c,(_,launch,*_)=registry;calls=[]
    def runner(*args):
        calls.append(1)
        if outcome=='exception':raise RuntimeError('interrupted SDK')
        return launch_result(launch,verified=False,closed_verified=outcome=='contract',new_unknown=int(outcome=='unknown'))
    result=tick(registry,runner);assert result['status'] in ('failed','uncertain','blocked') and len(calls)==1
    next_result=tick(registry,runner);assert len(calls)==1 and next_result['status'] in ('cached','blocked','uncertain')
    assert (Path(c['root'])/'freeze.json').exists()==(outcome!='contract')


def test_supervisor_import_is_standard_library_only():
    code="import sys;sys.path.insert(0,sys.argv[1]);import ops.pi.diagnosis_supervisor;assert 'httpx' not in sys.modules;assert 'ops.pi.diagnosis_launcher' not in sys.modules;assert 'ops.pi.development_launcher' not in sys.modules"
    subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(Path(__file__).parents[3])],check=True,capture_output=True)


def test_inconsistent_success_receipt_is_not_trusted(registry):
    _,c,(_,launch,*_)=registry
    result=tick(registry,lambda *a:launch_result(launch,verified=True,closed_verified=False))
    assert result['status']=='uncertain' and (Path(c['root'])/'freeze.json').exists()


def test_window_refresh_and_changed_cohort_do_not_mint_permits(registry,configured):
    rp,c,(_,launch,*_)=registry;calls=[]
    def runner(*args):calls.append(1);return launch_result(launch)
    assert tick(registry,runner)['status']=='passed'
    later=NOW+timedelta(minutes=15);observe(configured,Rows(1),clock=lambda:later)
    assert api().run(rp,file_hash(rp),runner=runner,clock=lambda:later)['status']=='cached'
    later=NOW+timedelta(minutes=30);observe(configured,Rows(2),clock=lambda:later)
    result=api().run(rp,file_hash(rp),runner=runner,clock=lambda:later)
    assert result['status']=='no_permit' and result['development_dispatches']==0 and len(calls)==1


def test_claim_parent_is_synced_before_intent_and_execution(registry,monkeypatch):
    _,c,(_,launch,*_)=registry;module=api();calls=[];publish=module._publish;sync=module.os.fsync
    def fsync(fd):calls.append('sync');return sync(fd)
    def write_receipt(path,data,**kwargs):
        if path.name=='intent.json':assert 'sync' in calls;calls.append('intent')
        return publish(path,data,**kwargs)
    monkeypatch.setattr(module.os,'fsync',fsync);monkeypatch.setattr(module,'_publish',write_receipt)
    def runner(*args):assert 'intent' in calls;return launch_result(launch)
    assert tick(registry,runner)['status']=='passed'


@pytest.mark.parametrize('sidecar',['-journal','-wal','-shm'])
def test_audit_sidecar_cannot_alias_supervisor_registry(registry,sidecar):
    rp,c,*_=registry;alias=Path(c['audit_path']+sidecar);original=rp.read_bytes();alias.write_bytes(original);alias.chmod(0o600)
    with pytest.raises(ValueError,match='overlap'):api().run(alias,file_hash(alias),runner=lambda *a:pytest.fail('dispatched'),clock=lambda:NOW)
    assert alias.read_bytes()==original
