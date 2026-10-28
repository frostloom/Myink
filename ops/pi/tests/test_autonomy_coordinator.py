"""Finite coordinator uses generated permissions and original manager admission."""
from pathlib import Path
from threading import Event
import fcntl,importlib
import pytest
from ops.pi.development_inputs import file_hash,ledger_snapshot,read_json
from ops.pi.tests.test_autonomy_profile import profile,research_config,diagnosis_config,config_file,configured,proof,write,NOW


def api():return importlib.import_module('ops.pi.autonomy_coordinator')


def kernels(profile,proof,monkeypatch,scenario='task'):
    from ops.pi.tests.test_investigation_launcher import run_research
    from ops.pi.tests.test_investigation_reproducer import runner as baseline_runner
    from ops.pi.tests.test_review_lease import run_review
    pp,p,c,context=profile;calls=[]
    def execute(component,cp,pin,cancel):
        with Path(p['lock_path']).open('rb') as check:
            with pytest.raises(BlockingIOError):fcntl.flock(check,fcntl.LOCK_EX|fcntl.LOCK_NB)
        calls.append(component);cfg=read_json(cp)
        if component=='investigation':
            outcome,_,_=run_research((cp,cfg,read_json(cfg['input_path']),read_json(cfg['permit_path'])),proof,monkeypatch,'no_task' if scenario=='no_task' else 'bad_output' if scenario=='bad_output' else 'task',cancel=cancel)
        elif component=='reproducer':outcome=importlib.import_module('ops.pi.investigation_reproducer').execute(cp,pin,runner=baseline_runner(monkeypatch,'green' if scenario=='green' else 'failed'),clock=lambda:NOW,cancel=cancel)
        elif component=='sdk_review':
            if scenario=='reject':
                helper=importlib.import_module('ops.pi.tests.test_review_lease');original=helper.recommendation
                monkeypatch.setattr(helper,'recommendation',lambda c,d:original(c,d,recommendation='reject',reason_code='unsupported_expectation'))
            outcome=run_review(cp,cfg,read_json(cfg['dossier_path']),proof,monkeypatch,now=NOW)
        elif component=='manager_handoff':
            for module in ('ops.pi.maintenance_adapters','ops.pi.selection_launcher'):monkeypatch.setattr(module+'.verify_source',lambda *args:dict(machine='aarch64'))
            outcome=importlib.import_module('ops.pi.manager_handoff').publish(cp,pin,clock=lambda:NOW,cancel=cancel)
            if scenario=='lost_handoff':raise RuntimeError('synthetic parent lost handoff result')
        elif component=='coordinator_audit':outcome=importlib.import_module('ops.pi.autonomy_audit').emit(cp,pin)
        else:raise AssertionError('arbitrary phase forbidden')
        count=outcome['new_attempts'] if component in ('investigation','sdk_review') else outcome['model_requests'];state='done'
        if component in ('investigation','sdk_review') and not outcome['verified']:state='failed' if outcome['closed_verified'] else 'blocked'
        return dict(schema='pi-autonomy-worker-result-v1',component=component,mode='SIMULATED',status=state,model_requests=count,outcome=outcome)
    return execute,calls


def test_source_pipeline_admits_once_registers_worker_and_reentry_has_zero_calls(profile,proof,monkeypatch):
    pp,p,c,context=profile;run,calls=kernels(profile,proof,monkeypatch);before=ledger_snapshot(c['ledger_path']);result=api().run(pp,file_hash(pp),runner=run,clock=lambda:NOW)
    assert result['status']=='admitted' and result['model_requests']==2 and calls==['investigation','reproducer','sdk_review','manager_handoff','coordinator_audit']
    assert len(list(Path(p['inbox']).glob('*.task.json')))==1 and result['pending_file_hashes']=={'src/a.py':file_hash(Path(p['source']['source_path'])/'src/a.py')}
    registry=Path(p['permit_root']).parent/'review-worker-registry.json';assert len(read_json(registry)['entries'])==1
    cached=api().run(pp,file_hash(pp),runner=run,clock=lambda:NOW);assert cached['status']=='cached' and cached['model_requests']==0 and len(calls)==5
    assert ledger_snapshot(c['ledger_path'])['events'][:len(before['events'])]==before['events']
    with Path(p['lock_path']).open('rb') as lock:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)


@pytest.mark.parametrize('scenario,status,models,phases',[
    ('no_task','no_task',1,['investigation','coordinator_audit']),
    ('green','not_reproduced',1,['investigation','reproducer','coordinator_audit']),
    ('reject','review_rejected',2,['investigation','reproducer','sdk_review','coordinator_audit']),
    ('bad_output','failed',1,['investigation','coordinator_audit']),
    ('lost_handoff','uncertain',2,['investigation','reproducer','sdk_review','manager_handoff','coordinator_audit'])])
def test_failure_no_task_and_rejection_never_admit_or_replay(profile,proof,monkeypatch,scenario,status,models,phases):
    pp,p,c,context=profile;run,calls=kernels(profile,proof,monkeypatch,scenario);result=api().run(pp,file_hash(pp),runner=run,clock=lambda:NOW)
    assert result['status']==status and result['model_requests']==models and calls==phases and not list(Path(p['inbox']).glob('*.task.json'))
    again=api().run(pp,file_hash(pp),runner=run,clock=lambda:NOW)
    assert again['model_requests']==0 and calls==phases
    if scenario=='lost_handoff':
        claim=Path(p['root'])/context['research_fingerprint'];assert read_json(claim/'withdrawal/receipt.json')['status']=='withdrawn'


def test_worker_registration_failure_withdraws_only_own_visible_manifest(profile,proof,monkeypatch):
    pp,p,c,context=profile;run,calls=kernels(profile,proof,monkeypatch)
    def fail(*args,**kwargs):raise OSError('synthetic registry publish failure')
    monkeypatch.setattr(api(),'_register',fail);result=api().run(pp,file_hash(pp),runner=run,clock=lambda:NOW)
    assert result['status']=='uncertain' and not list(Path(p['inbox']).glob('*.task.json')) and (Path(p['root'])/context['research_fingerprint']/'withdrawal/receipt.json').exists()


def test_live_competing_lock_returns_without_claim_or_call(profile,proof,monkeypatch):
    pp,p,c,context=profile;run,calls=kernels(profile,proof,monkeypatch)
    with Path(p['lock_path']).open('rb') as held:
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB);result=api().run(pp,file_hash(pp),runner=run,clock=lambda:NOW)
    assert result['status']=='lock_busy' and result['model_requests']==0 and not calls and not list(Path(p['root']).iterdir())


def test_incomplete_prior_claim_freezes_new_investigation_without_replay(profile,proof,monkeypatch):
    pp,p,c,context=profile;claim=Path(p['root'])/('a'*64);claim.mkdir(mode=0o700);write(claim/'intent.json',dict(status='pending'))
    run,calls=kernels(profile,proof,monkeypatch);result=api().run(pp,file_hash(pp),runner=run,clock=lambda:NOW)
    assert result['status']=='uncertain' and result['model_requests']==0 and not calls


def test_current_goal_keeps_actual_callback_and_cancelled_start_closed(profile,proof,monkeypatch):
    pp,p,c,context=profile;run,calls=kernels(profile,proof,monkeypatch);event=Event();event.set()
    assert api().run(pp,file_hash(pp),runner=run,clock=lambda:NOW,cancel=event)['status']=='cancelled'
    p['mode']='ACTUAL';write(pp,p)
    with pytest.raises(ValueError):api().run(pp,file_hash(pp),runner=run,clock=lambda:NOW)
    assert not calls and not list(Path(p['root']).iterdir())


def test_main_reader_can_link_full_flow_without_double_counting_model_cost(profile,proof,monkeypatch):
    import importlib.util
    pp,p,c,context=profile;runner,calls=kernels(profile,proof,monkeypatch);result=api().run(pp,file_hash(pp),runner=runner,clock=lambda:NOW)
    spec=importlib.util.spec_from_file_location('coordinator_main_reader',Path('src/myink/pi_audit.py'));reader_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader_module)
    events=reader_module.AuditReader(Path(p['export_root'])).events('auto-'+context['research_fingerprint'][:32],limit=100)['items']
    event=next(e for e in events if e['details'].get('reference')=='autonomy.coordinator.v1')
    assert event['details']['operation_id']==context['research_fingerprint'] and 'model_requests' not in event['details'] and 'known_cost_microyuan' not in event['details']
    assert {e['kind'] for e in event['evidence']}=={'root_source_profile','phase_investigation','phase_reproducer','phase_sdk_review','phase_manager_handoff'}
    assert any(e['kind']=='version' and e['version']['controller_sha256']==p['controller_sha256'] for e in events)
