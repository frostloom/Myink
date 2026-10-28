"""External host publication feeds unchanged FileReview, with no model request."""
from datetime import timedelta
from pathlib import Path
from threading import Event
import importlib,time
import pytest
from ops.pi.audit import digest
from ops.pi.development_inputs import authorization_hash,file_hash,ledger_snapshot,read_json,validate_review
from ops.pi.maintenance_adapters import FileReview
from ops.pi.tests.test_review_lease import completed,write,NOW
from ops.pi.tests.test_sdk_review_launcher import review_config
from ops.pi.tests.test_review_dossier import dossier_input,config_file
from ops.pi.tests.test_selection_launcher import proof


@pytest.fixture
def publication(completed):
    pp,p,cp,c,tc=completed;lease=importlib.import_module('ops.pi.review_lease').create(pp,file_hash(pp),cp,file_hash(cp),selection_operation_id='fixed-selection',clock=lambda:NOW)
    target=Path(p['prepared_parent'])/'value-fix';target.mkdir(mode=0o700)
    current=dict(tc,ledger_sha256=ledger_snapshot(c['ledger_path'])['sha256'],deadline_seconds=tc['deadline_seconds']-1,review_path=str(target/'review.json'),review_sha256='0'*64)
    config=target/'config.json';write(config,current);plan=read_json(tc['plan_path'])
    request=dict(authorization_sha256=authorization_hash(current),plan_hash=digest(plan),base=current['source_sha256'],candidate_id=current['run_id'],config_path=str(config),task_id='value-fix');write(target/'review-request.json',request)
    return pp,p,cp,c,lease,config,current


def api():return importlib.import_module('ops.pi.review_publisher')


def test_external_publication_satisfies_original_file_review_without_new_fees(publication):
    pp,p,cp,c,lease,config,current=publication;before=ledger_snapshot(c['ledger_path'])
    result=api().publish(lease['lease_path'],lease['lease_sha256'],config,clock=lambda:NOW)
    assert result['status']=='published' and result['model_requests']==0 and ledger_snapshot(c['ledger_path'])==before
    approval=FileReview(1)(config,dict(cancel=Event(),deadline=time.monotonic()+1));validate_review(approval,current,digest(read_json(current['plan_path'])),current['source_sha256'])
    assert not Path(current['root']).exists()
    with pytest.raises(ValueError):api().publish(lease['lease_path'],lease['lease_sha256'],config,clock=lambda:NOW)


@pytest.mark.parametrize('fault',['scope','request','policy_revoke','lease_pin','artifact','existing','source','expired','config_alias'])
def test_publisher_rejects_drift_before_any_approval(publication,fault):
    pp,p,cp,c,lease,config,current=publication;pin=lease['lease_sha256'];clock=lambda:NOW
    if fault=='scope':current['max_requests']+=1;write(config,current)
    elif fault=='request':write(config.parent/'review-request.json',{})
    elif fault=='policy_revoke':write(pp,{})
    elif fault=='lease_pin':pin='f'*64
    elif fault=='artifact':write(Path(c['root'])/'verification.json',{})
    elif fault=='existing':write(Path(current['review_path']),dict(existing=True))
    elif fault=='source':(Path(current['source_path'])/'src/a.py').write_text('changed')
    elif fault=='expired':clock=lambda:NOW+timedelta(hours=2)
    else:config=config.parent/'other.json';write(config,current)
    before=ledger_snapshot(c['ledger_path'])
    with pytest.raises((ValueError,OSError,KeyError)):api().publish(lease['lease_path'],pin,config,clock=clock)
    assert ledger_snapshot(c['ledger_path'])==before
    assert (not Path(current['review_path']).exists()) if fault!='existing' else read_json(current['review_path'])==dict(existing=True)


def test_partial_publication_claim_is_retained_and_never_replayed(publication,monkeypatch):
    pp,p,cp,c,lease,config,current=publication;module=api();original=module._new
    def write_fault(path,value):
        if path.name=='receipt.json':raise OSError('synthetic receipt sync failure')
        return original(path,value)
    monkeypatch.setattr(module,'_new',write_fault)
    with pytest.raises(OSError):module.publish(lease['lease_path'],lease['lease_sha256'],config,clock=lambda:NOW)
    assert Path(current['review_path']).exists() and (Path(lease['lease_path']).parent/'publication/intent.json').exists()
    with pytest.raises(ValueError):module.publish(lease['lease_path'],lease['lease_sha256'],config,clock=lambda:NOW)


def test_original_frozen_adapter_waits_for_external_host_publication_without_deadlock(completed,monkeypatch):
    from threading import Thread
    from ops.pi.maintenance_adapters import FrozenDevelopmentAdapter
    from ops.pi.maintenance_handoff import _catalog
    pp,p,cp,c,tc=completed
    monkeypatch.setattr('ops.pi.maintenance_adapters.verify_source',lambda *args:dict(machine='aarch64'))
    lease=importlib.import_module('ops.pi.review_lease').create(pp,file_hash(pp),cp,file_hash(cp),selection_operation_id='fixed-selection',clock=lambda:NOW)
    refreshed=dict(tc,ledger_sha256=ledger_snapshot(c['ledger_path'])['sha256']);template=cp.parent/'refreshed-template.json';write(template,refreshed)
    outcome=read_json(c['outcome_path']);task=_catalog(outcome['catalog'])[0];captured=[];failure=[]
    def publisher():
        try:
            target=Path(p['prepared_parent'])/task['task_id']/'config.json';until=time.monotonic()+8
            while not (target.parent/'review-request.json').exists():
                if time.monotonic()>=until:raise TimeoutError('adapter did not request review')
                time.sleep(.01)
            captured.append(api().publish(lease['lease_path'],lease['lease_sha256'],target,clock=lambda:NOW))
        except Exception as error:failure.append(error)
    thread=Thread(target=publisher);thread.start()
    adapter=FrozenDevelopmentAdapter({task['task_id']:dict(path=str(template),sha256=file_hash(template))},p['prepared_parent'],c['ledger_path'],FileReview(10))
    receipt=adapter(dict(cancel=Event(),deadline=time.monotonic()+1800,task=task,mode='SIMULATED',input_hash='b'*64,operation_id='freeze-one'))
    thread.join(timeout=10)
    assert not thread.is_alive() and not failure and receipt.status=='done' and captured[0]['status']=='published'
    from ops.pi.development_inputs import prepare
    assert prepare(receipt.evidence['config_path'])[0]['ledger_sha256']==ledger_snapshot(c['ledger_path'])['sha256']


def test_final_permission_does_not_race_development_for_fee_lock(publication,monkeypatch):
    import fcntl
    pp,p,cp,c,lease,config,current=publication;module=api();original=module._publish_new;checked=[]
    def final_publication(path,raw):
        with Path(c['ledger_path']).with_suffix('.tools.lock').open('rb') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);checked.append(True)
        return original(path,raw)
    monkeypatch.setattr(module,'_publish_new',final_publication)
    module.publish(lease['lease_path'],lease['lease_sha256'],config,clock=lambda:NOW)
    assert checked==[True]


def test_host_permission_has_distinct_admin_audit_without_overwriting_sdk_cost(publication):
    from ops.pi.audit import AuditStore
    pp,p,cp,c,lease,config,current=publication
    before=AuditStore(c['audit_path']).events(run_id=c['run_id'])
    api().publish(lease['lease_path'],lease['lease_sha256'],config,clock=lambda:NOW)
    events=AuditStore(c['audit_path']).events(run_id=current['run_id'])
    approval=next(e for e in events if e['details'].get('reference')=='host.file_review.v1')
    assert approval['kind']=='review' and approval['status']=='passed' and approval['details']['decision']=='issued'
    assert {p['kind'] for p in approval['evidence']}=={'independent_review_dossier','host_review_lease','exact_file_review'}
    assert 'known_cost_microyuan' not in approval['details'] and 'model_requests' not in approval['details']
    assert AuditStore(c['audit_path']).events(run_id=c['run_id'])==before
