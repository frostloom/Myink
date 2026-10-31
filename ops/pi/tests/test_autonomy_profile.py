"""Root source profiles produce bounded stage inputs, never model self-approval."""
from datetime import timedelta
from pathlib import Path
import importlib,pytest
from ops.pi.audit import digest
from ops.pi.development_inputs import file_hash,ledger_snapshot,read_json
from ops.pi.tests.test_investigation_launcher import research_config,diagnosis_config,config_file,configured,proof,write,NOW
from ops.pi import manager


def api():return importlib.import_module('ops.pi.autonomy_profile')


@pytest.fixture
def profile(research_config):
    cp,c,context,permit=research_config;parent=cp.parent;roots={}
    for key in ('root','permit_root','handoff_root','review_root','reproduction_root'):
        path=parent/('autonomy-'+key);path.mkdir(mode=0o700);roots[key]=str(path)
    roots['investigation_root']=str(Path(c['root']).parent)
    state=parent/'manager-state';state.mkdir(mode=0o700);state=state/'manager.sqlite';manager.init(state,Path(c['ledger_path']),mode='SIMULATED')
    inbox=parent/'inbox';inbox.mkdir(mode=0o700);lock=parent/'maintenance.lock';lock.touch(mode=0o600)
    host={k:c[k] for k in ('runtime_path','runtime_sha256','ledger_path','policy_path','policy_sha256','credential_path','credential_sha256','docker','endpoint','daemon_id','image_id')}
    observer={k:c[k] for k in ('observer_config_path','observer_config_sha256','observer_controller_sha256')}
    source={k:c[k] for k in ('source_path','source_sha256','files','reference_commit','pending_path','pending_sha256')};source['behavior']='value'
    limits=dict(investigation_seconds=60,review_seconds=60,checker_seconds=60,max_requests=30,max_tools=64,development_seconds=900,cycle_seconds=1800,review_wait_seconds=60,priority=1)
    p=dict(schema='pi-autonomy-profile-v1',authority='bounded_source_investigation_and_review',mode='SIMULATED',**roots,host=host,observer=observer,source=source,audit_path=c['audit_path'],export_root=c['export_root'],manager_state=str(state),inbox=str(inbox),lock_path=str(lock),budget_microyuan=10000000,legacy_unknown_ids=[],limits=limits,issued_at=(NOW-timedelta(minutes=1)).isoformat(),expires_at=(NOW+timedelta(hours=1)).isoformat(),worker_entry_path=str(Path(c['docker'])),controller_sha256='a'*64,checker_image_id='sha256:'+'1'*64)
    pp=parent/'autonomy-profile.json';write(pp,p);return pp,p,c,context


def test_profile_load_is_readonly_and_keeps_original_financial_scope(profile):
    pp,p,c,context=profile;before=ledger_snapshot(c['ledger_path']);loaded,now,fee=api().load(pp,file_hash(pp),clock=lambda:NOW)
    assert loaded==p and now==NOW and fee==before and ledger_snapshot(c['ledger_path'])==before


@pytest.mark.parametrize('fault',['pin','actual_shadow','authority','extra','expiry','budget','holds','limits','source','pending','overlap','scope','worker','checker'])
def test_invalid_profile_cannot_mint_any_permit(profile,fault):
    pp,p,c,context=profile
    if fault=='actual_shadow':p['mode']='ACTUAL'
    elif fault=='authority':p['authority']='model_approved'
    elif fault=='extra':p['approve']=True
    elif fault=='expiry':p['expires_at']=NOW.isoformat()
    elif fault=='budget':p['budget_microyuan']+=1
    elif fault=='holds':p['legacy_unknown_ids']=['new-unknown']
    elif fault=='limits':p['limits']['development_seconds']=1801
    elif fault=='source':p['source']['source_sha256']='f'*64
    elif fault=='pending':p['source']['pending_sha256']='f'*64
    elif fault=='overlap':p['root']=str(Path(c['ledger_path']).parent)
    elif fault=='scope':p['source']['files']=['ops/pi/policy.py']
    elif fault=='worker':p['worker_entry_path']=str(pp.parent/'missing-entry')
    elif fault=='checker':p['checker_image_id']='latest'
    write(pp,p);before=ledger_snapshot(c['ledger_path'])
    with pytest.raises((ValueError,OSError,KeyError,TypeError)):api().load(pp,'f'*64 if fault=='pin' else file_hash(pp),clock=lambda:NOW)
    assert ledger_snapshot(c['ledger_path'])==before and not list(Path(p['permit_root']).iterdir())


def test_investigation_builder_uses_verified_fresh_evidence_and_permanent_claim(profile,monkeypatch):
    pp,p,c,context=profile;module=api();loaded,now,fee=module.load(pp,file_hash(pp),clock=lambda:NOW)
    e=importlib.import_module('ops.pi.live_diagnosis').inspect_observation(c['observer_config_path'],c['observer_config_sha256'],c['observation_receipt_path'],expected_controller_sha256=c['observer_controller_sha256'],clock=lambda:NOW)
    result=module.research(pp,file_hash(pp),c['observation_receipt_path'],clock=lambda:NOW)
    cfg=read_json(result['config_path']);permit=read_json(cfg['permit_path']);launcher=importlib.import_module('ops.pi.investigation_launcher');monkeypatch.setattr(launcher,'verify_source',lambda *args:dict(machine='aarch64'))
    assert launcher.prepare(result['config_path'],clock=lambda:NOW)[0]==cfg and cfg['root']==str(Path(p['investigation_root'])/('research-'+context['research_fingerprint']))
    assert permit['max_model_requests']==1 and permit['authority']=='test_proposal_only' and ledger_snapshot(c['ledger_path'])==fee
    with pytest.raises(ValueError):module.research(pp,file_hash(pp),c['observation_receipt_path'],clock=lambda:NOW)


@pytest.fixture
def proposed(profile,proof,monkeypatch):
    from ops.pi.tests.test_investigation_launcher import run_research
    pp,p,c,context=profile;r=api().research(pp,file_hash(pp),c['observation_receipt_path'],clock=lambda:NOW);cp=Path(r['config_path']);cfg=read_json(cp);permit=read_json(cfg['permit_path'])
    result,_,_=run_research((cp,cfg,context,permit),proof,monkeypatch)
    assert result['verified'] is True
    return profile,r,cfg


def test_reproducer_builder_authenticates_completed_proposal_and_only_mints_fixed_checker_scope(proposed):
    (pp,p,c,context),r,cfg=proposed;before=ledger_snapshot(c['ledger_path']);stage=api().reproducer(pp,file_hash(pp),r['config_path'],r['config_sha256'],clock=lambda:NOW);authority=read_json(stage['config_path'])
    assert authority['authority']=='isolated_reproducer' and authority['research_config_path']==r['config_path'] and authority['root']==str(Path(p['reproduction_root'])/('repro-'+context['research_fingerprint']))
    assert authority['max_requests']==p['limits']['max_requests'] and not Path(authority['root']).exists() and ledger_snapshot(c['ledger_path'])==before
    with pytest.raises(FileExistsError):api().reproducer(pp,file_hash(pp),r['config_path'],r['config_sha256'],clock=lambda:NOW)


def test_reproducer_builder_rejects_forged_completed_proposal(proposed):
    (pp,p,c,context),r,cfg=proposed;write(Path(cfg['root'])/'verification.json',{});before=ledger_snapshot(c['ledger_path'])
    with pytest.raises((ValueError,KeyError)):api().reproducer(pp,file_hash(pp),r['config_path'],r['config_sha256'],clock=lambda:NOW)
    assert ledger_snapshot(c['ledger_path'])==before and not list(Path(p['permit_root']).glob('reproducer-*'))


@pytest.fixture
def reproduced(proposed,monkeypatch):
    from ops.pi.tests.test_investigation_reproducer import runner
    (pp,p,c,context),r,cfg=proposed;stage=api().reproducer(pp,file_hash(pp),r['config_path'],r['config_sha256'],clock=lambda:NOW)
    result=importlib.import_module('ops.pi.investigation_reproducer').execute(stage['config_path'],stage['config_sha256'],runner=runner(monkeypatch),clock=lambda:NOW)
    assert result['eligible_for_review'] is True
    return proposed,stage,result


def test_review_builder_uses_completed_reproduction_and_separate_root_issuer(reproduced,monkeypatch):
    ((pp,p,c,context),r,cfg),stage,result=reproduced;before=ledger_snapshot(c['ledger_path']);review=api().review(pp,file_hash(pp),r['claim_path'],clock=lambda:NOW);cp=Path(review['config_path']);rc=read_json(cp)
    module=importlib.import_module('ops.pi.sdk_review_launcher');monkeypatch.setattr(module,'verify_source',lambda *args:dict(machine='aarch64'))
    assert module.prepare(cp,clock=lambda:NOW)[0]==rc and rc['template_path']==result['template_path']
    permit=read_json(rc['permit_path']);issuer=read_json(review['issuer_policy_path'])
    assert permit['authority']=='independent_review_recommendation_only' and issuer['authority']=='host_reviewed_development' and issuer['source_sha256']==read_json(rc['template_path'])['source_sha256']
    assert issuer['prepared_parent']==str(Path(p['handoff_root'])/('handoff-'+context['research_fingerprint'])/'bundle/cycle-output/prepared')
    assert not list(Path(p['handoff_root']).glob('*.task.json')) and ledger_snapshot(c['ledger_path'])==before


def test_review_builder_rejects_partial_reproduction(reproduced):
    ((pp,p,c,context),r,cfg),stage,result=reproduced;receipt=Path(p['reproduction_root'])/('repro-'+context['research_fingerprint'])/'receipt.json';receipt.unlink()
    with pytest.raises(OSError):api().review(pp,file_hash(pp),r['claim_path'],clock=lambda:NOW)
    assert not list(Path(p['permit_root']).glob('review-*'))


def test_generated_stage_inputs_drive_sdk_review_and_original_manager_handoff(reproduced,proof,monkeypatch):
    from ops.pi.tests.test_review_lease import run_review
    ((pp,p,c,context),r,cfg),stage,result=reproduced;review=api().review(pp,file_hash(pp),r['claim_path'],clock=lambda:NOW);cp=Path(review['config_path']);rc=read_json(cp)
    run_review(cp,rc,read_json(rc['dossier_path']),proof,monkeypatch,now=NOW)
    handoff=api().handoff(pp,file_hash(pp),r['claim_path'],clock=lambda:NOW);before=ledger_snapshot(c['ledger_path'])
    for module in ('ops.pi.maintenance_adapters','ops.pi.selection_launcher'):monkeypatch.setattr(module+'.verify_source',lambda *args:dict(machine='aarch64'))
    published=importlib.import_module('ops.pi.manager_handoff').publish(handoff['config_path'],handoff['config_sha256'],clock=lambda:NOW)
    assert published['status']=='published' and ledger_snapshot(c['ledger_path'])==before
    assert read_json(published['manifest_path'])['mode']=='SIMULATED' and read_json(published['lease_path'])['scope']['allowed_fee_operation_ids']==[]


@pytest.mark.parametrize('fault',['root','requests','source','scope'])
def test_review_builder_cannot_expand_root_profile_from_reproduction_output(reproduced,fault):
    ((pp,p,c,context),r,cfg),stage,result=reproduced;tc=read_json(result['template_path'])
    if fault=='root':tc['root']=str(Path(p['handoff_root'])/'foreign-candidate')
    elif fault=='requests':tc['max_requests']=p['limits']['max_requests']+1
    elif fault=='source':tc['source_sha256']='f'*64
    else:
        plan=read_json(tc['plan_path']);plan['files']=['src/foreign.py'];write(Path(tc['plan_path']),plan);tc['plan_sha256']=file_hash(tc['plan_path'])
    write(Path(result['template_path']),tc)
    if fault in ('root','requests'):
        from ops.pi.review_dossier import compile_dossier
        bq=Path(result['template_path']).parent/'baseline-request.json';outcome=result['baseline_outcome_path']
        dossier=compile_dossier(result['template_path'],file_hash(result['template_path']),bq,file_hash(bq),outcome,file_hash(outcome));write(Path(result['dossier_path']),dossier)
    with pytest.raises((ValueError,OSError,KeyError)):api().review(pp,file_hash(pp),r['claim_path'],clock=lambda:NOW)
    assert not list(Path(p['permit_root']).glob('review-*')) and not list(Path(p['permit_root']).glob('issuer-*'))


@pytest.mark.parametrize('permit,expected',[(True,(0,654)),(False,(321,654))])
def test_root_writer_assigns_explicit_worker_read_group(tmp_path,monkeypatch,permit,expected):
    module=api();calls=[];monkeypatch.setattr(module,'_owner',lambda p:(321,654));monkeypatch.setattr(module.os,'fchown',lambda fd,uid,gid:calls.append((uid,gid)))
    target=tmp_path/'owned-input.json';module.write(dict(mode='ACTUAL'),target,dict(value='fixed-host-input'),permit=permit)
    assert calls==[expected] and target.stat().st_mode&0o777==(0o640 if permit else 0o600)
