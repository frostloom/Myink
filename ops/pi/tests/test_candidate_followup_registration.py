"""Only fully reviewed original candidates enter the existing fixed registry."""
from copy import deepcopy
from pathlib import Path
import importlib
import pytest
from ops.pi.audit import AuditStore
from ops.pi.development_inputs import file_hash,read_json,ledger_snapshot
from ops.pi.tests.test_candidate_review_once import stage_case,finished,stopped,completed,config_file,write,NOW,proof,run


@pytest.fixture
def registry(stage_case):
    pp,p,claim,lp,finished=stage_case;dc=finished[5];root=pp.parent/'followup-runs';root.mkdir(mode=0o700)
    e=dict(test_id='original-fixed',run_id='old-original',scheduled_for=NOW.isoformat(),candidate_path=str(Path(dc['root'])/'candidate'),candidate_sha256=finished[6]['evidence']['result']['candidate_sha256'],source_path=dc['source_path'],source_sha256=dc['source_sha256'],test_path=dc['test_path'],test_sha256=dc['test_sha256'],test_cases=dc['test_cases'],review_path=str(Path(dc['root'])/'result.json'),review_sha256=file_hash(Path(dc['root'])/'result.json'),checker={k:dc[k] for k in ('docker','endpoint','daemon_id','checker_image_id')})
    c=dict(schema='pi-followup-registry-v1',mode=p['mode'],root=str(root),audit_path=p['audit_path'],export_root=p['export_root'],lock_path=str(lp),billing_path=p['host']['ledger_path'],manager_path=p['manager_state'],entries=[e]);rp=pp.parent/'followup-registry.json';write(rp,c)
    ep=pp.parent/'followup.env';ep.write_text('PI_OBSERVER_RUNTIME_SHA256='+'b'*64+'\nPI_FOLLOWUP_ENTRYPOINT=/closed/followup/entry.py\nPI_FOLLOWUP_REGISTRY_SHA256='+file_hash(rp)+'\n');ep.chmod(0o600)
    p['checker_image_id']=dc['checker_image_id'];write(pp,p)
    return rp,ep,c


def test_approved_completion_registers_exact_candidate_and_plan_once(stage_case,registry,proof,monkeypatch):
    pp,p,claim,lp,finished=stage_case;rp,ep,old=registry;r,calls=run(stage_case,proof,monkeypatch)
    assert r['status']=='review_approved' and r['followup_registered'] is True
    current=read_json(rp);assert current['entries'][:1]==old['entries'] and len(current['entries'])==2
    e=current['entries'][1];assert e['candidate_sha256']==r['candidate_sha256'] and e['run_id']==finished[2]
    assert 'PI_FOLLOWUP_REGISTRY_SHA256='+file_hash(rp) in ep.read_text()
    plan=AuditStore(p['audit_path']).events(run_id=finished[2])[-1];assert plan['status']=='planned' and plan['followups'][0]['status']=='planned'
    from myink.pi_audit import AuditReader
    assert AuditReader(p['export_root']).daily('2026-10-29')['next_tests'][0]['result'] is None
    before=rp.read_bytes(),ep.read_bytes(),ledger_snapshot(finished[1]);again,newcalls=run(stage_case,proof,monkeypatch)
    assert again['cached'] and newcalls==[] and (rp.read_bytes(),ep.read_bytes(),ledger_snapshot(finished[1]))==before


@pytest.mark.parametrize('scenario',['reject','invalid','unknown','cleanup'])
def test_unapproved_or_uncertain_review_never_modifies_registry(stage_case,registry,proof,monkeypatch,scenario):
    rp,ep,_=registry;before=rp.read_bytes(),ep.read_bytes();r,_=run(stage_case,proof,monkeypatch,scenario)
    assert r['followup_registered'] is False and (rp.read_bytes(),ep.read_bytes())==before


@pytest.mark.parametrize('fault',['env_pin','manager','audit','capacity'])
def test_wrong_original_registry_is_blocked_without_replaying_review(stage_case,registry,proof,monkeypatch,fault):
    pp,p,claim,lp,finished=stage_case;rp,ep,c=registry
    if fault=='env_pin':ep.write_text(ep.read_text().replace(file_hash(rp),'f'*64))
    else:
        if fault=='manager':c['manager_path']=c['billing_path']
        elif fault=='audit':c['audit_path']=c['billing_path']
        else:c['entries']=[dict(c['entries'][0],test_id='prior-'+str(n)) for n in range(32)]
        old=file_hash(rp);write(rp,c);ep.write_text(ep.read_text().replace(old,file_hash(rp)))
    before=rp.read_bytes(),ep.read_bytes();r,calls=run(stage_case,proof,monkeypatch)
    assert r['followup_registered'] is False and calls==['candidate_review'] and (rp.read_bytes(),ep.read_bytes())==before
    again,newcalls=run(stage_case,proof,monkeypatch);assert again['cached'] and newcalls==[]


def test_registry_pair_partial_update_is_retained_never_replayed(stage_case,registry,proof,monkeypatch):
    rp,ep,c=registry;module=importlib.import_module('ops.pi.candidate_followup');original=module._replace
    def fail(path,raw,p):
        if path==ep:raise OSError('synthetic env failure')
        return original(path,raw,p)
    monkeypatch.setattr(module,'_replace',fail);r,calls=run(stage_case,proof,monkeypatch)
    assert r['followup_registered'] is False and (stage_case[2]/'followup-registration/intent.json').exists()
    before=rp.read_bytes(),ep.read_bytes();again,newcalls=run(stage_case,proof,monkeypatch)
    assert newcalls==[] and again['cached'] and (rp.read_bytes(),ep.read_bytes())==before


def test_registered_plan_runs_only_when_due_without_certifying_actual_execution(stage_case,registry,proof,monkeypatch):
    from datetime import timedelta
    from ops.pi.followup import run_due
    from ops.pi.audit import utc
    from myink.pi_audit import AuditReader
    pp,p,claim,lp,finished=stage_case;rp,ep,c=registry
    old=file_hash(rp);c['entries'][0]['scheduled_for']=(NOW+timedelta(days=10)).isoformat();write(rp,c);ep.write_text(ep.read_text().replace(old,file_hash(rp)))
    r,_=run(stage_case,proof,monkeypatch);assert r['followup_registered']
    entry=read_json(rp)['entries'][-1];due=utc(entry['scheduled_for']);called=[]
    def checker(e,root,write):
        called.append(e['test_id']);return dict(tests=len(e['test_cases']),cases=e['test_cases'],failures=0,errors=0,skipped=0,passed=True,failed_cases=[],error_cases=[],diagnostics=[],load_error=False,attach_returncode=0,container_id='owned',cleanup=[dict(container_id='owned',removed=True,exit_code=0)])
    before=ledger_snapshot(finished[0]),ledger_snapshot(finished[1]);assert run_due(rp,file_hash(rp),clock=lambda:due-timedelta(seconds=1),runner=checker)['results']==[] and called==[]
    result=run_due(rp,file_hash(rp),clock=lambda:due,runner=checker);assert result['results'][0]['status']=='passed' and called==[entry['test_id']] and result['model_requests']==0
    again=run_due(rp,file_hash(rp),clock=lambda:due,runner=checker);assert again['results']==result['results'] and len(called)==1
    assert (ledger_snapshot(finished[0]),ledger_snapshot(finished[1]))==before
    reader=AuditReader(p['export_root']);assert reader.daily('2026-10-29')['next_tests'][0]['result'] is None
    event=reader.events(finished[2],kind='test')['items'][-1];assert event['status']=='passed' and event['mode']=='SIMULATED' and event['occurred_at']==due.isoformat()
