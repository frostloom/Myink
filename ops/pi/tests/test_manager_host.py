"""An autonomous admission is not executable until its coordinator is complete."""
from pathlib import Path
import importlib
import pytest
from ops.pi.development_inputs import file_hash,read_json,ledger_snapshot
from ops.pi.tests.test_autonomy_coordinator import profile,research_config,diagnosis_config,config_file,configured,proof,write,NOW,kernels


def api():return importlib.import_module('ops.pi.manager_host')


@pytest.fixture
def ready(profile,proof,monkeypatch):
    pp,p,c,context=profile;runner,calls=kernels(profile,proof,monkeypatch);r=importlib.import_module('ops.pi.autonomy_coordinator').run(pp,file_hash(pp),runner=runner,clock=lambda:NOW);assert r['status']=='admitted'
    path=pp.parent/'manager-host.json';value=dict(schema='pi-closed-manager-host-v1',mode='SIMULATED',state_path=p['manager_state'],billing_path=p['host']['ledger_path'],inbox=p['inbox'],autonomy_root=p['root'],handoff_root=p['handoff_root']);write(path,value)
    return path,value,p,context


def test_original_manager_is_called_only_after_completed_coordinator(ready,monkeypatch):
    cp,c,p,context=ready;calls=[];before=ledger_snapshot(c['billing_path'])
    def run(*args,**kwargs):calls.append((args,kwargs));return dict(status='done',dispatched=0)
    monkeypatch.setattr('ops.pi.manager.run',run);result=api().run(cp,file_hash(cp),executor=lambda *a:None,clock=lambda:NOW)
    assert result['status']=='done' and len(calls)==1 and calls[0][1]['max_tasks']==1 and calls[0][1]['seconds']==2100 and calls[0][1]['idle_seconds']==0
    assert ledger_snapshot(c['billing_path'])==before


@pytest.mark.parametrize('fault',['missing_coordinator','changed_manifest','changed_phase','changed_result','changed_handoff_receipt','expired_issuer','actual_injection','extra'])
def test_incomplete_or_unbound_admission_cannot_reach_manager(ready,monkeypatch,fault):
    cp,c,p,context=ready;claim=Path(p['root'])/context['research_fingerprint'];handoff_root=Path(p['handoff_root'])/('handoff-'+context['research_fingerprint'])
    if fault=='missing_coordinator':(claim/'receipt.json').unlink()
    elif fault=='changed_manifest':write(next(Path(p['inbox']).glob('*.task.json')),dict(mode='foreign'))
    elif fault=='changed_phase':write(claim/'phase-manager_handoff/receipt.json',{})
    elif fault=='changed_result':write(claim/'phase-manager_handoff/result-private.json',{})
    elif fault=='changed_handoff_receipt':write(handoff_root/'receipt.json',{})
    elif fault=='expired_issuer':
        request=read_json(Path(p['handoff_root'])/('request-'+context['research_fingerprint']+'.json'));issuer=Path(request['issuer_policy_path']);data=read_json(issuer);data['expires_at']=NOW.isoformat();write(issuer,data)
    elif fault=='actual_injection':c['mode']='ACTUAL';write(cp,c)
    else:c['shell']='command';write(cp,c)
    calls=[];monkeypatch.setattr('ops.pi.manager.run',lambda *a,**kw:calls.append(True));before=ledger_snapshot(c['billing_path'])
    with pytest.raises((ValueError,OSError,KeyError,TypeError)):api().run(cp,file_hash(cp),executor=lambda *a:None,clock=lambda:NOW)
    assert not calls and ledger_snapshot(c['billing_path'])==before


def test_cancelled_historical_task_does_not_require_expired_live_permission(ready,monkeypatch):
    from ops.pi import manager
    cp,c,p,context=ready;m=read_json(next(Path(p['inbox']).glob('*.task.json')))
    manager.enqueue(c['state_path'],c['billing_path'],m['task_id'],m['request_path'],m['request_sha256'],priority=m['priority'],mode='SIMULATED');manager.cancel_task(c['state_path'],c['billing_path'],m['task_id'],'withdrawn before dispatch',mode='SIMULATED')
    (Path(p['root'])/context['research_fingerprint']/'receipt.json').unlink();calls=[];monkeypatch.setattr(manager,'run',lambda *a,**kw:calls.append(True) or dict(status='done',dispatched=0))
    assert api().run(cp,file_hash(cp),executor=lambda *a:None,clock=lambda:NOW)['status']=='done' and calls==[True]
