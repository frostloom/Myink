"""Generated completion review executes one fixed role and never replays payment."""
from pathlib import Path
from threading import Event
import fcntl,importlib
import pytest
from ops.pi.development_inputs import file_hash,read_json,ledger_snapshot
from ops.pi.tests.test_candidate_review_stage import stage_case,finished,stopped,completed,config_file,write,NOW
from ops.pi.tests.test_selection_launcher import proof
from ops.pi.tests.test_candidate_review_launcher import run_review


def api():return importlib.import_module('ops.pi.candidate_review_stage')


def run(case,proof,monkeypatch,scenario='approve'):
    pp,p,claim,lp,finished=case;calls=[]
    def runner(component,cp,pin,cancel):
        if component=='development_audit':
            from ops.pi.development_audit import emit
            outcome=emit(cp,pin)
            return dict(schema='pi-autonomy-worker-result-v1',component=component,mode='SIMULATED',status='done',model_requests=0,outcome=outcome)
        if component=='candidate_audit':
            from ops.pi.autonomy_audit import emit
            outcome=emit(cp,pin)
            return dict(schema='pi-autonomy-worker-result-v1',component=component,mode='SIMULATED',status='done',model_requests=0,outcome=outcome)
        assert component=='candidate_review';calls.append(component);c=read_json(cp);d=read_json(c['dossier_path']);permit=read_json(c['permit_path']);dc=read_json(read_json(c['request_path'])['config_path'])
        outcome=run_review((cp,c,d,permit,dc),proof,monkeypatch,scenario)
        return dict(schema='pi-autonomy-worker-result-v1',component=component,mode='SIMULATED',status='done' if outcome['verified'] else 'failed' if outcome['closed_verified'] else 'blocked',model_requests=outcome['new_attempts'],outcome=outcome)
    with lp.open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=api().review_once(pp,file_hash(pp),claim,lock,runner=runner,clock=lambda:NOW)
    return r,calls


@pytest.mark.parametrize('scenario,status',[('approve','review_approved'),('reject','review_rejected'),('invalid','review_failed'),('unknown','uncertain'),('cleanup','uncertain')])
def test_original_completion_to_fresh_review_once_preserves_every_attempt(stage_case,proof,monkeypatch,scenario,status):
    pp,p,claim,lp,finished=stage_case;before=ledger_snapshot(finished[1]);r,calls=run(stage_case,proof,monkeypatch,scenario)
    assert r['status']==status and r['model_requests']==1 and r['executable_approval'] is False and calls==['candidate_review']
    saved=read_json(claim/'candidate-review-outcome.json');assert saved['status']==status and saved['candidate_sha256']==finished[6]['evidence']['result']['candidate_sha256']
    current=ledger_snapshot(finished[1]);assert current['events'][:len(before['events'])]==before['events']
    again,newcalls=run(stage_case,proof,monkeypatch,scenario);assert again['cached'] is True and again['model_requests']==0 and newcalls==[] and ledger_snapshot(finished[1])==current
    assert not (Path(p['permit_root']).parent/'followup-registry.json').exists()


def test_parent_cancel_prevents_even_a_completion_claim(stage_case,proof,monkeypatch):
    pp,p,claim,lp,finished=stage_case;event=Event();event.set();before=ledger_snapshot(finished[1])
    with lp.open('rb') as lock:
        with pytest.raises(ValueError):api().review_once(pp,file_hash(pp),claim,lock,runner=lambda *a:pytest.fail('cancelled'),clock=lambda:NOW,cancel=event)
    assert not (claim/'phase-candidate_review').exists() and ledger_snapshot(finished[1])==before


def test_host_review_and_blocked_nextday_plan_are_admin_readable_without_duplicate_cost(stage_case,proof,monkeypatch):
    from ops.pi.audit import AuditStore
    from myink.pi_audit import AuditReader
    pp,p,claim,lp,finished=stage_case;r,calls=run(stage_case,proof,monkeypatch)
    events=[e for e in AuditStore(p['audit_path']).events(run_id=finished[2]) if e['details'].get('reference','').startswith('candidate.')];assert len(events)==2
    assert events[0]['details']['reference']=='candidate.host_completion.v1' and events[0]['details']['decision']=='review_approved'
    assert events[1]['kind']=='followup' and events[1]['status']=='blocked' and events[1]['followups'][0]['status']=='blocked'
    assert all('model_requests' not in event['details'] and 'known_cost_microyuan' not in event['details'] for event in events)
    reader=AuditReader(p['export_root']);assert reader.events(finished[2])['total']==8
    again,newcalls=run(stage_case,proof,monkeypatch);assert newcalls==[] and len(AuditStore(p['audit_path']).events(run_id=finished[2]))==8


def test_complete_development_tools_and_fees_are_projected_once_even_if_reviewer_fails(stage_case,proof,monkeypatch):
    from ops.pi.audit import AuditStore
    from myink.pi_audit import AuditReader
    pp,p,claim,lp,finished=stage_case;r,calls=run(stage_case,proof,monkeypatch,'invalid')
    rows=AuditStore(p['audit_path']).events(run_id=finished[2]);tools=[e for e in rows if e['kind']=='tool']
    assert [e['details']['tool_name'] for e in tools]==['apply_patch','run_check','candidate_status']
    dev=next(e for e in rows if e['kind']=='development');assert dev['details']['model_requests']==7 and dev['changes']==[dict(path='src/a.py',category='production',added=1,deleted=1)]
    assert dev['details']['known_cost_microyuan']==finished[6]['evidence']['result']['known_cost_microyuan']
    assert next(e for e in rows if e['kind']=='test')['details']['test_failures']==0
    assert next(e for e in rows if e['kind']=='deployment')['status']=='no_release'
    again,newcalls=run(stage_case,proof,monkeypatch,'invalid');assert again['cached'] and newcalls==[] and len(AuditStore(p['audit_path']).events(run_id=finished[2]))==len(rows)
    daily=AuditReader(p['export_root']).daily('2026-10-29');assert daily['change_scope'] and daily['versions']


@pytest.mark.parametrize('component',['development_audit','candidate_audit'])
def test_projection_failure_retains_claim_and_never_replays_model(stage_case,proof,monkeypatch,component):
    module=importlib.import_module('ops.pi.development_audit' if component=='development_audit' else 'ops.pi.autonomy_audit')
    def fail(*a):raise OSError('synthetic projection failure')
    monkeypatch.setattr(module,'emit',fail);pp,p,claim,lp,finished=stage_case;before=ledger_snapshot(finished[1]);r,calls=run(stage_case,proof,monkeypatch)
    assert r['status']=='uncertain' and calls==([] if component=='development_audit' else ['candidate_review'])
    after=ledger_snapshot(finished[1]);again,newcalls=run(stage_case,proof,monkeypatch)
    assert again['status']=='uncertain' and again['model_requests']==0 and newcalls==[] and ledger_snapshot(finished[1])==after
    if component=='development_audit':assert after==before


@pytest.mark.parametrize('state,expected',[('failed','execution_stopped'),('blocked','execution_stopped'),('pending','uncertain'),('done','no_action')])
def test_stopped_or_abstaining_manager_has_auditable_unknowns_without_review(stage_case,proof,monkeypatch,state,expected):
    from ops.pi import manager
    from ops.pi.contracts import Receipt
    from ops.pi.audit import digest,AuditStore
    pp,p,claim,lp,finished=stage_case;oldstate,billing,taskid,qp,q,c,result=finished
    _,_,rows,*_=manager._snapshot(oldstate,billing,'SIMULATED');old=rows['manager:task:'+taskid];dp=rows[old['operation_id']+':dispatch'];new=oldstate.with_name('terminal-manager.sqlite');manager.init(new,billing,mode='SIMULATED');ledger=manager.Ledger(new,existing=True)
    ledger.intent(old['operation_id'],old['kind'],old['payload']);ledger.finish(Receipt(old['operation_id'],'done',old['evidence']));ledger.intent(dp['operation_id'],dp['kind'],dp['payload'])
    if state!='pending':
        evidence=dict(dp['evidence'],verified=state=='done',next_action='observe' if state=='done' else None)
        if state=='done':
            result=dict(result,evidence=dict(result['evidence'],next_action='observe'));write(qp.parent/'cycle-output/result.json',result);evidence['cycle_result_sha256']=digest(result)
        ledger.finish(Receipt(dp['operation_id'],state,evidence))
    p['manager_state']=str(new);write(pp,p);calls=[]
    def runner(component,cp,pin,cancel):
        assert component=='manager_audit';calls.append(component)
        from ops.pi.autonomy_audit import emit
        return dict(schema='pi-autonomy-worker-result-v1',component=component,mode='SIMULATED',status='done',model_requests=0,outcome=emit(cp,pin))
    with lp.open('rb') as lock:r=api().observe_manager(pp,file_hash(pp),claim,lock,runner=runner,clock=lambda:NOW)
    assert r['status']==expected and r['model_requests']==0 and calls==['manager_audit'] and not (claim/'candidate-review-config.json').exists()
    event=AuditStore(p['audit_path']).events(run_id=taskid)[0];assert event['details']['decision']==expected and event['details']['model_requests'] is None and event['details']['range_complete'] is False
    with lp.open('rb') as lock:again=api().observe_manager(pp,file_hash(pp),claim,lock,runner=runner,clock=lambda:NOW)
    assert again['cached'] and len(calls)==1


@pytest.mark.parametrize('error',[ValueError,OSError])
def test_paid_review_host_verification_failure_is_durable_and_admin_readable(stage_case,proof,monkeypatch,error):
    from ops.pi.audit import AuditStore
    def invalid(*a,**kw):raise error('synthetic post-paid verification failure')
    monkeypatch.setattr('ops.pi.candidate_review_evidence.inspect',invalid)
    pp,p,claim,lp,finished=stage_case;r,calls=run(stage_case,proof,monkeypatch)
    assert r['status']=='uncertain' and r['model_requests']==1 and r['recommendation'] is None and not r['followup_registered'] and calls==['candidate_review']
    assert read_json(claim/'candidate-review-outcome.json')['status']=='uncertain'
    rows=AuditStore(p['audit_path']).events(run_id=finished[2]);host=next(e for e in rows if e['details'].get('reference')=='candidate.host_completion.v1')
    assert host['status']=='uncertain' and host['details']['reason']=='host_candidate_evidence_unverified'
    assert rows[-1]['followups'][0]['status']=='blocked' and 'known_cost_microyuan' not in host['details']
    again,newcalls=run(stage_case,proof,monkeypatch);assert again['cached'] and again['status']=='uncertain' and again['model_requests']==0 and newcalls==[] and len(AuditStore(p['audit_path']).events(run_id=finished[2]))==len(rows)


def test_code_regression_baseline_failure_count_is_preserved_for_admin_metrics(stage_case,proof,monkeypatch):
    from ops.pi.audit import AuditStore
    module=importlib.import_module('ops.pi.development_audit');original=module.inspect
    def authenticated(*a,**kw):
        value=original(*a,**kw);value['development']['dossier']['model_view']['baseline']=dict(evidence_domain='code_regression',reproduction=dict(failures=3));return value
    monkeypatch.setattr(module,'inspect',authenticated);pp,p,claim,lp,finished=stage_case;run(stage_case,proof,monkeypatch)
    event=next(e for e in AuditStore(p['audit_path']).events(run_id=finished[2]) if e['kind']=='test');assert event['details']['baseline_failures']==3
