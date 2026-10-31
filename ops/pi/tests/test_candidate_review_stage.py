"""Root-generated candidate review requires original admission and completion proof."""
from datetime import timedelta
from pathlib import Path
import fcntl,importlib
from threading import Event
import pytest
from ops.pi.audit import encoded
from ops.pi.development_inputs import file_hash,ledger_snapshot,read_json
from ops.pi.tests.test_manager_completion import finished,stopped,completed,config_file,write
from ops.pi.tests.test_candidate_review_launcher import NOW


def api():return importlib.import_module('ops.pi.candidate_review_stage')


@pytest.fixture
def stage_case(finished,monkeypatch):
    state,billing,taskid,qp,q,c,result=finished;parent=qp.parent;roots={}
    for key in ('root','review_root','permit_root','handoff_root'):
        d=parent/('stage-'+key);d.mkdir(mode=0o700);roots[key]=str(d)
    claim=Path(roots['root'])/('a'*64);claim.mkdir(mode=0o700);lock=parent/'maintenance.lock';lock.touch(mode=0o600)
    audit=parent/'audit';audit.mkdir(mode=0o700)
    from ops.pi.audit import AuditStore
    AuditStore(audit/'events.sqlite')
    host={k:c[k] for k in ('runtime_path','runtime_sha256','ledger_path','policy_path','policy_sha256','credential_path','credential_sha256','docker','endpoint','daemon_id','image_id')}
    p=dict(controller_sha256='d'*64,mode='SIMULATED',**roots,host=host,source=dict(source_sha256=c['source_sha256'],files=['src/a.py']),manager_state=str(state),lock_path=str(lock),audit_path=str(audit/'events.sqlite'),export_root=str(parent/'export'),budget_microyuan=10000000,legacy_unknown_ids=[],limits=dict(review_seconds=60,max_requests=30,max_tools=64,development_seconds=900),expires_at=(NOW+timedelta(hours=1)).isoformat())
    pp=parent/'stage-profile.json';write(pp,p)
    def load(path,pin,**kwargs):
        assert path==pp and pin==file_hash(pp);return p,NOW,ledger_snapshot(billing)
    module=api();monkeypatch.setattr(module.profile,'load',load);monkeypatch.setattr(module,'_admitted',lambda *a:dict(task_id=taskid))
    return pp,p,claim,lock,finished


def create(case,**kwargs):
    pp,p,claim,lp,_=case
    with lp.open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);return api().create(pp,file_hash(pp),claim,lock,clock=lambda:NOW,**kwargs)


def test_generated_permit_and_dossier_bind_original_completed_candidate_without_models(stage_case,monkeypatch):
    pp,p,claim,lp,finished=stage_case;before=ledger_snapshot(finished[1]);r=create(stage_case)
    assert r['status']=='prepared' and r['model_requests']==0 and r['candidate_sha256']==finished[6]['evidence']['result']['candidate_sha256']
    c=read_json(r['config_path']);permit=read_json(c['permit_path']);assert permit['authority']=='independent_candidate_recommendation_only' and permit['max_model_requests']==1
    assert permit['candidate_sha256']==r['candidate_sha256'] and permit['budget_microyuan']==p['budget_microyuan'] and c['ledger_sha256']==before['sha256']
    module=importlib.import_module('ops.pi.candidate_review_launcher');monkeypatch.setattr(module,'verify_source',lambda *a:dict(machine='aarch64'));module.prepare(r['config_path'],clock=lambda:NOW)
    again=create(stage_case);assert again['cached'] is True and again['config_sha256']==r['config_sha256'] and ledger_snapshot(finished[1])==before


@pytest.mark.parametrize('fault',['source','files','budget','holds','runtime','policy','credential','limits','lock','cancel','completion'])
def test_outside_profile_or_unverified_completion_cannot_issue_review_permit(stage_case,fault):
    pp,p,claim,lp,finished=stage_case;event=Event()
    if fault=='source':p['source']['source_sha256']='f'*64
    elif fault=='files':p['source']['files']=['src/other.py']
    elif fault=='budget':p['budget_microyuan']+=1
    elif fault=='holds':p['legacy_unknown_ids']=['new-unknown']
    elif fault in ('runtime','policy','credential'):p['host'][fault+'_sha256']='f'*64
    elif fault=='limits':p['limits']['max_requests']=1
    elif fault=='cancel':event.set()
    elif fault=='completion':(Path(finished[5]['root'])/'phase-verification.json').write_bytes(b'{}')
    if fault=='lock':
        other=lp.with_name('foreign.lock');other.touch(mode=0o600)
        with other.open('rb') as lock:
            with pytest.raises((ValueError,OSError)):api().create(pp,file_hash(pp),claim,lock,clock=lambda:NOW)
    else:
        with pytest.raises((ValueError,OSError)):create(stage_case,cancel=event)
    assert list(Path(p['permit_root']).iterdir())==[]


def test_partial_preparation_is_retained_and_cannot_be_replayed(stage_case,monkeypatch):
    pp,p,claim,lp,finished=stage_case;module=api();original=module.profile.write;seen=[]
    def fail(p,path,value,**kwargs):
        seen.append(path)
        if path.name=='candidate-dossier.json':raise OSError('synthetic storage failure')
        return original(p,path,value,**kwargs)
    monkeypatch.setattr(module.profile,'write',fail)
    with pytest.raises(OSError):create(stage_case)
    assert (claim/'completion-prepare/intent.json').exists() and not (claim/'completion-prepare/receipt.json').exists()
    monkeypatch.setattr(module.profile,'write',original);before=ledger_snapshot(finished[1]);r=create(stage_case);assert r['status']=='uncertain' and r['model_requests']==0 and ledger_snapshot(finished[1])==before
