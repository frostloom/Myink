"""Reviewed regression inputs must enter the original manager without manual JSON approval."""
from pathlib import Path
import importlib,pytest
from ops.pi.development_inputs import file_hash,ledger_snapshot,read_json
from ops.pi.tests.test_review_lease import completed,write,NOW
from ops.pi.tests.test_sdk_review_launcher import review_config
from ops.pi.tests.test_review_dossier import dossier_input,config_file
from ops.pi.tests.test_selection_launcher import proof
from ops.pi import manager


@pytest.fixture
def handoff(completed,monkeypatch):
    pp,p,review_cp,review_c,tc=completed;parent=review_cp.parent;root=parent/'handoff';p['prepared_parent']=str(root/'bundle/cycle-output/prepared');write(pp,p)
    receipt=parent/'reproduction-receipt.json';write(receipt,dict(schema='pi-reproduction-result-v1',status='reproduced',eligible_for_review=True,model_requests=0,template_path=review_c['template_path'],dossier_path=review_c['dossier_path'],baseline_outcome_path=review_c['outcome_path']))
    inbox=parent/'inbox';inbox.mkdir(mode=0o700);state=parent/'manager-state';state.mkdir(mode=0o700);state=state/'manager.sqlite';manager.init(state,Path(tc['ledger_path']),mode='SIMULATED')
    value=dict(schema='pi-reviewed-manager-handoff-v1',mode='SIMULATED',root=str(root),issuer_policy_path=str(pp),issuer_policy_sha256=file_hash(pp),review_config_path=str(review_cp),review_config_sha256=file_hash(review_cp),reproduction_receipt_path=str(receipt),reproduction_receipt_sha256=file_hash(receipt),cycle_id='new-cycle',selection_run_id='new-selection',task_id='new-manager-task',manager_state=str(state),inbox=str(inbox),deadline_seconds=1800,review_wait_seconds=60,priority=1)
    request=parent/'handoff-request.json';write(request,value)
    for module in ('ops.pi.maintenance_adapters','ops.pi.selection_launcher'):monkeypatch.setattr(module+'.verify_source',lambda *args:dict(machine='aarch64'))
    return request,value,review_c,tc


def api():return importlib.import_module('ops.pi.manager_handoff')


def test_reviewed_handoff_is_ingested_once_by_original_manager_without_model(handoff):
    request,c,review,tc=handoff;before=ledger_snapshot(tc['ledger_path']);r=api().publish(request,file_hash(request),clock=lambda:NOW)
    assert r['status']=='published' and r['model_requests']==0 and ledger_snapshot(tc['ledger_path'])==before
    manifest=read_json(r['manifest_path']);assert manifest['task_id']==c['task_id'] and manifest['mode']=='SIMULATED'
    _,_,rows,tasks,_=manager._snapshot(Path(c['manager_state']),Path(tc['ledger_path']),'SIMULATED')
    assert manager._ingest(Path(c['inbox']),Path(c['manager_state']),Path(tc['ledger_path']),'SIMULATED',rows,tasks) is True
    _,_,rows,tasks,_=manager._snapshot(Path(c['manager_state']),Path(tc['ledger_path']),'SIMULATED')
    assert manager._ingest(Path(c['inbox']),Path(c['manager_state']),Path(tc['ledger_path']),'SIMULATED',rows,tasks) is False
    template=read_json(r['template_path']);assert template['ledger_sha256']==before['sha256'] and template['root']==tc['root']
    assert read_json(Path(r['bundle_path']).parent/'selection-review.json')['source']=='independent_review'
    with pytest.raises(ValueError):api().publish(request,file_hash(request),clock=lambda:NOW)


@pytest.mark.parametrize('fault',['receipt','policy','review','inbox_alias','root_alias','actual_shadow','extra','export_alias'])
def test_incomplete_or_foreign_handoff_never_publishes(handoff,fault):
    request,c,review,tc=handoff
    if fault in ('receipt','policy','review'):c[{'receipt':'reproduction_receipt_sha256','policy':'issuer_policy_sha256','review':'review_config_sha256'}[fault]]='f'*64
    elif fault=='inbox_alias':c['inbox']=str(Path(tc['ledger_path']).parent)
    elif fault=='root_alias':c['root']=tc['source_path']
    elif fault=='actual_shadow':c['mode']='ACTUAL'
    elif fault=='export_alias':
        c['root']=str(Path(review['export_root'])/'aliased-handoff');policy=read_json(c['issuer_policy_path']);policy['prepared_parent']=str(Path(c['root'])/'bundle/cycle-output/prepared');write(Path(c['issuer_policy_path']),policy);c['issuer_policy_sha256']=file_hash(c['issuer_policy_path'])
    else:c['approved']=True
    write(request,c);before=ledger_snapshot(tc['ledger_path'])
    with pytest.raises((ValueError,OSError,KeyError,TypeError)):api().publish(request,file_hash(request),clock=lambda:NOW)
    assert ledger_snapshot(tc['ledger_path'])==before and not list(Path(c['inbox']).glob('*.task.json'))


def test_partial_handoff_keeps_claim_and_never_retries_publication(handoff,monkeypatch):
    request,c,review,tc=handoff;module=api();original=module._new
    def fail(path,value):
        if path.name=='receipt.json' and path.parent==Path(c['root']):raise OSError('synthetic final receipt sync failure')
        return original(path,value)
    monkeypatch.setattr(module,'_new',fail);before=ledger_snapshot(tc['ledger_path'])
    with pytest.raises(OSError):module.publish(request,file_hash(request),clock=lambda:NOW)
    assert (Path(c['root'])/'intent.json').exists() and not (Path(c['root'])/'receipt.json').exists()
    assert (Path(c['inbox'])/(c['task_id']+'.task.json')).exists()
    with pytest.raises(ValueError):module.publish(request,file_hash(request),clock=lambda:NOW)
    assert ledger_snapshot(tc['ledger_path'])==before
