"""A fresh post-development recommendation has no adoption authority."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import importlib,json
import httpx,pytest
from ops.pi.audit import encoded,AuditStore
from ops.pi.development_inputs import file_hash,ledger_snapshot
from ops.pi.candidate_dossier import compile_dossier
from ops.pi.tests.test_candidate_dossier import completed,config_file,write
from ops.pi.tests.test_selection_launcher import proof
from ops.pi.tests.test_diagnosis_launcher import fake_frame

NOW=datetime(2026,10,29,1,0,tzinfo=timezone.utc)
def api():return importlib.import_module('ops.pi.candidate_review_launcher')


@pytest.fixture
def candidate_review(completed):
    qp,q,dc,r,check=completed;parent=qp.parent;write(parent/'candidate-parent-profile.json',dict(mode='SIMULATED',expires_at=(NOW+timedelta(hours=1)).isoformat()));dp=parent/'candidate-dossier.json';d=compile_dossier(qp,file_hash(qp));write(dp,d)
    claims=parent/'candidate-reviews';claims.mkdir(mode=0o700)
    audit=parent/'audit';audit.mkdir(mode=0o700);AuditStore(audit/'events.sqlite')
    c={k:dc[k] for k in ('runtime_path','runtime_sha256','ledger_path','policy_path','policy_sha256','credential_path','credential_sha256','docker','endpoint','daemon_id','image_id')}
    c.update(schema='pi-candidate-review-v1',role='candidate_review',mode='SIMULATED',run_id='candidate-review-one',root=str(claims/('candidate-'+r['candidate_sha256'])),ledger_sha256=ledger_snapshot(dc['ledger_path'])['sha256'],deadline_seconds=60,request_path=str(qp),request_sha256=file_hash(qp),dossier_path=str(dp),dossier_sha256=file_hash(dp),permit_path=str(parent/'candidate-permit.json'),permit_sha256='0'*64,audit_path=str(audit/'events.sqlite'),export_root=str(parent/'export'))
    p={k:c[k] for k in ('mode','role','run_id','request_sha256','dossier_sha256','runtime_sha256','policy_sha256','credential_sha256','ledger_path','deadline_seconds')};p.update(schema='pi-candidate-review-permit-v1',authority='independent_candidate_recommendation_only',profile_path=str(parent/'candidate-parent-profile.json'),profile_sha256=file_hash(parent/'candidate-parent-profile.json'),claim_root=str(claims),candidate_sha256=r['candidate_sha256'],budget_scope='local-trial-1',budget_microyuan=10000000,max_model_requests=1,legacy_unknown_ids=[],issued_at=(NOW-timedelta(minutes=1)).isoformat(),expires_at=(NOW+timedelta(minutes=10)).isoformat())
    write(Path(c['permit_path']),p);c['permit_sha256']=file_hash(c['permit_path']);cp=parent/'candidate-review-config.json';write(cp,c);return cp,c,d,p,dc


def report(c,d,**changes):
    r=dict(schema='pi-candidate-review-recommendation-v1',candidate_sha256=d['candidate_sha256'],dossier_sha256=c['dossier_sha256'],recommendation='approve',reason_code='validated_repair',summary='Private reviewer commentary.');r.update(changes);return r


def test_preflight_is_readonly_and_report_is_not_permission(candidate_review,monkeypatch):
    cp,c,d,p,dc=candidate_review;module=api();monkeypatch.setattr(module,'verify_source',lambda *a:dict(machine='aarch64'));before={p:p.read_bytes() for p in cp.parent.rglob('*') if p.is_file()}
    module.prepare(cp,clock=lambda:NOW);assert before=={p:p.read_bytes() for p in cp.parent.rglob('*') if p.is_file()}
    for change in (dict(candidate_sha256='f'*64),dict(recommendation='deploy'),dict(approved=True),dict(reason_code='self_approved')):
        with pytest.raises(ValueError):module.validate_output(report(c,d,**change),c,dict(dossier=d))


@pytest.mark.parametrize('fault',['authority','expiry','cap','role','candidate','dossier','actual_shadow','canonical_sim','root_overlap','extra'])
def test_invalid_authority_never_claims_or_charges(candidate_review,monkeypatch,fault):
    cp,c,d,p,dc=candidate_review;module=api();monkeypatch.setattr(module,'verify_source',lambda *a:dict(machine='aarch64'))
    if fault=='authority':p['authority']='product_release'
    elif fault=='expiry':p['expires_at']=NOW.isoformat()
    elif fault=='cap':p['max_model_requests']=2
    elif fault=='role':c['role']='developer'
    elif fault=='candidate':p['candidate_sha256']='f'*64
    elif fault=='dossier':c['dossier_sha256']='f'*64
    elif fault=='actual_shadow':c['mode']='ACTUAL'
    elif fault=='canonical_sim':monkeypatch.setattr(module,'CANONICAL',Path(c['ledger_path']))
    elif fault=='root_overlap':c['root']=str(Path(dc['root'])/'inside')
    else:c['approve']=True
    if fault in ('authority','expiry','cap','candidate'):write(Path(c['permit_path']),p);c['permit_sha256']=file_hash(c['permit_path'])
    write(cp,c);before=ledger_snapshot(c['ledger_path'])
    with pytest.raises((ValueError,OSError)):module.prepare(cp,clock=lambda:NOW)
    assert not Path(c['root']).exists() and ledger_snapshot(c['ledger_path'])==before


def run_review(case,proof,monkeypatch,scenario='approve'):
    cp,c,d,p,dc=case;module=api();host=importlib.import_module('ops.pi.no_tool_host');monkeypatch.setattr(module,'verify_source',lambda *a:dict(machine='aarch64'))
    class H:operation_id='candidate-review-owned';owned={};pending={}
    class Owners:
        failed=False
        def __init__(self,*a):pass
        def add(self,h):return h
        def finish(self):return [dict(container_id='b'*64,removed=scenario!='cleanup')]
    monkeypatch.setattr(host,'_host',lambda *a:H());monkeypatch.setattr(host,'OwnedHosts',Owners)
    value=report(c,d,**(dict(recommendation='reject',reason_code='regression_risk') if scenario=='reject' else dict(approved=True) if scenario=='invalid' else {}));text=json.dumps(value)
    def exchange(h,config,initial,bridge,transport,limits,save,**kwargs):
        assert kwargs['worker']=='selection.py' and initial['system']==module.SYSTEM and str(cp.parent) not in initial['prompt']
        if scenario=='revoke':write(Path(c['permit_path']),{})
        if scenario=='parent_revoke':write(cp.parent/'candidate-parent-profile.json',{})
        if scenario=='candidate_drift':(Path(dc['root'])/'candidate/src/a.py').write_text('changed')
        if scenario=='expiry':monkeypatch.setattr(module,'_time',lambda *a:(_ for _ in ()).throw(ValueError('expired')))
        body=dict(model=initial['model'],max_tokens=initial['max_tokens'],system=[dict(type='text',text=module.wire_system(initial['system']))],messages=[dict(role='user',content=[dict(type='text',text=initial['prompt'])])],stream=True)
        bridge.route(dict(type='request',path='/v1/messages',headers=[['x-api-key',initial['model_token']],['x-pi-scope','local-trial-1']],body=json.dumps(body)),transport)
        frame=fake_frame(proof[0],initial,text);save('worker-frame-private.json',frame);return frame
    monkeypatch.setattr(host,'_exchange',exchange)
    def send(body,timeout):
        usage={} if scenario=='unknown' else dict(input_tokens=1,output_tokens=1,cache_read_input_tokens=0,cache_creation_input_tokens=0)
        rows=[dict(type='message_start',message=dict(usage=usage)),dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text=text)),dict(type='message_delta',usage=dict(output_tokens=1) if usage else {}),dict(type='message_stop')]
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=httpx.ByteStream(''.join('data: '+json.dumps(v)+'\n\n' for v in rows).encode()))
    result=module.execute(cp,transport=send,clock=lambda:NOW,expected_config_sha256=file_hash(cp));return result


@pytest.mark.parametrize('scenario',['approve','reject','invalid','unknown','cleanup','revoke','candidate_drift','expiry'])
def test_fresh_candidate_review_lifecycle_and_no_replay(candidate_review,proof,monkeypatch,scenario):
    cp,c,d,p,dc=candidate_review;before=ledger_snapshot(c['ledger_path']);approval=Path(dc['review_path']).read_bytes();result=run_review(candidate_review,proof,monkeypatch,scenario)
    assert result['verified']==(scenario in ('approve','reject')) and result['executable_approval'] is False
    assert result['new_attempts']==(0 if scenario in ('revoke','candidate_drift','expiry') else 1) and result['new_unknown']==(1 if scenario=='unknown' else 0)
    assert Path(dc['review_path']).read_bytes()==approval and result['original_history_unchanged']
    events=AuditStore(c['audit_path']).events(run_id=c['run_id']);assert events[-1]['kind']=='review' and 'Private reviewer commentary.' not in json.dumps(events)
    with pytest.raises(ValueError):api().execute(cp,transport=lambda *a:None,clock=lambda:NOW,expected_config_sha256=file_hash(cp))
    if scenario in ('approve','reject'):
        evidence=importlib.import_module('ops.pi.candidate_review_evidence');verified=evidence.inspect(cp,file_hash(cp),clock=lambda:NOW)
        assert verified['authority']=='recommendation_only' and verified['report']['recommendation']==scenario
        assert ledger_snapshot(c['ledger_path'])['events'][:len(before['events'])]==before['events']
        write(Path(c['root'])/'result.json',dict(result,report=report(c,d,recommendation='reject',reason_code='regression_risk') if scenario=='approve' else report(c,d)))
        with pytest.raises(ValueError):evidence.inspect(cp,file_hash(cp),clock=lambda:NOW)


def test_candidate_claim_cannot_be_renamed_to_repay_same_review(candidate_review,monkeypatch):
    cp,c,d,p,dc=candidate_review;module=api();monkeypatch.setattr(module,'verify_source',lambda *a:dict(machine='aarch64'));c['root']=str(Path(c['root']).parent/'renamed');write(cp,c);before=ledger_snapshot(c['ledger_path'])
    with pytest.raises(ValueError,match='candidate claim'):module.prepare(cp,clock=lambda:NOW)
    assert ledger_snapshot(c['ledger_path'])==before


def test_independent_review_runtime_can_advance_without_rewriting_finished_development(candidate_review,monkeypatch):
    cp,c,d,p,dc=candidate_review;original=Path(dc['runtime_path']);current=cp.parent/'matching-review-runtime';current.mkdir();c['runtime_path']=str(current);write(cp,c);seen=[]
    monkeypatch.setattr(api(),'verify_source',lambda path,pin:seen.append((path,pin)) or dict(machine='aarch64'))
    before={p:p.read_bytes() for p in cp.parent.rglob('*') if p.is_file()};prepared=api().prepare(cp,clock=lambda:NOW)
    assert seen==[(current,dc['runtime_sha256'])] and prepared[0]['runtime_path']==str(current) and Path(dc['runtime_path'])==original
    assert before=={p:p.read_bytes() for p in cp.parent.rglob('*') if p.is_file()}


def test_parent_profile_revocation_during_sdk_startup_prevents_reservation(candidate_review,proof,monkeypatch):
    cp,c,*_=candidate_review;before=ledger_snapshot(c['ledger_path']);result=run_review(candidate_review,proof,monkeypatch,'parent_revoke')
    assert result['new_attempts']==0 and not result['verified'] and ledger_snapshot(c['ledger_path'])==before
