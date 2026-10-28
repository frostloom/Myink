"""Only host policy plus a closed authentic SDK recommendation can create a lease."""
from datetime import timedelta
from pathlib import Path
import importlib,json
import httpx,pytest
from ops.pi.audit import encoded
from ops.pi.development_inputs import file_hash,ledger_snapshot,read_json
from ops.pi.tests.test_sdk_review_launcher import review_config,recommendation,NOW
from ops.pi.tests.test_review_dossier import dossier_input,config_file
from ops.pi.tests.test_selection_launcher import proof
from ops.pi.tests.test_diagnosis_launcher import fake_frame


def write(p,v):p.write_bytes(encoded(v));p.chmod(0o600)


@pytest.fixture
def completed(review_config,proof,monkeypatch):
    cp,c,d,permit,tc=review_config;module=importlib.import_module('ops.pi.sdk_review_launcher');host=importlib.import_module('ops.pi.no_tool_host')
    monkeypatch.setattr(module,'verify_source',lambda *args:dict(machine='aarch64'))
    class H:operation_id='owned-review';owned={};pending={}
    class Owners:
        failed=False
        def __init__(self,*args):pass
        def add(self,h):return h
        def finish(self):return [dict(container_id='a'*64,removed=True)]
    monkeypatch.setattr(host,'_host',lambda *args:H());monkeypatch.setattr(host,'OwnedHosts',Owners)
    text=json.dumps(recommendation(c,d))
    def exchange(h,config,initial,bridge,transport,limits,save,**kwargs):
        request=dict(model=initial['model'],max_tokens=initial['max_tokens'],system=[dict(type='text',text=initial['system']+'\n\n<cwd>\n/work/candidate\n</cwd>')],messages=[dict(role='user',content=[dict(type='text',text=initial['prompt'])])],stream=True)
        bridge.route(dict(type='request',path='/v1/messages',headers=[['x-api-key',initial['model_token']],['x-pi-scope','local-trial-1']],body=json.dumps(request)),transport)
        frame=fake_frame(proof[0],initial,text);save('worker-frame-private.json',frame);return frame
    monkeypatch.setattr(host,'_exchange',exchange)
    def send(body,timeout):
        usage=dict(input_tokens=1,output_tokens=1,cache_read_input_tokens=0,cache_creation_input_tokens=0)
        events=[dict(type='message_start',message=dict(usage=usage)),dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text=text)),dict(type='message_delta',usage=dict(output_tokens=1)),dict(type='message_stop')]
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=httpx.ByteStream(''.join('data: '+json.dumps(v)+'\n\n' for v in events).encode()))
    result=module.execute(cp,transport=send,clock=lambda:NOW,expected_config_sha256=file_hash(cp));assert result['verified'] is True
    root=cp.parent/'leases';root.mkdir(mode=0o700);prepared=cp.parent/'prepared';prepared.mkdir(mode=0o700)
    policy=dict(schema='pi-review-issuer-policy-v1',authority='host_reviewed_development',mode='SIMULATED',root=str(root),prepared_parent=str(prepared),review_config_parent=str(cp.parent),source_sha256=tc['source_sha256'],allowed_files=['src/a.py'],runtime_sha256=c['runtime_sha256'],policy_sha256=c['policy_sha256'],credential_sha256=c['credential_sha256'],ledger_path=c['ledger_path'],budget_microyuan=10000000,legacy_unknown_ids=[],max_requests=tc['max_requests'],max_tools=tc['max_tools'],deadline_seconds=tc['deadline_seconds'],issued_at=(NOW-timedelta(minutes=1)).isoformat(),expires_at=(NOW+timedelta(hours=1)).isoformat())
    pp=cp.parent/'issuer-policy.json';write(pp,policy);return pp,policy,cp,c,tc


def api():return importlib.import_module('ops.pi.review_lease')


def test_real_sdk_proof_creates_private_durable_lease_without_approval(completed):
    pp,p,cp,c,tc=completed;before=ledger_snapshot(c['ledger_path'])
    result=api().create(pp,file_hash(pp),cp,file_hash(cp),selection_operation_id='fixed-selection',clock=lambda:NOW)
    record=read_json(result['lease_path']);assert record['scope']['semantic_sha256'] and record['scope']['fee_checkpoint']==before
    assert record['scope']['allowed_fee_operation_ids']==['fixed-selection'] and ledger_snapshot(c['ledger_path'])==before
    assert result['authority']=='lease_only' and record['scope']['authority']=='host_exact_file_review'
    assert not Path(tc['root']).exists() and not (Path(p['prepared_parent'])/'value-fix/review.json').exists()
    with pytest.raises(ValueError):api().create(pp,file_hash(pp),cp,file_hash(cp),selection_operation_id='fixed-selection',clock=lambda:NOW)


@pytest.mark.parametrize('fault',['policy_authority','policy_source','policy_files','policy_limit','expired','initial','frame','request','verification','result','fee_before','fee_after','cleanup','unknown','root_overlap','actual_injection'])
def test_unverified_sdk_or_host_scope_never_creates_lease(completed,fault):
    pp,p,cp,c,tc=completed;root=Path(c['root'])
    if fault.startswith('policy_'):
        if fault=='policy_authority':p['authority']='independent_review_recommendation_only'
        elif fault=='policy_source':p['source_sha256']='f'*64
        elif fault=='policy_files':p['allowed_files']=['src/other.py']
        else:p['max_requests']=0
    elif fault=='expired':p['expires_at']=NOW.isoformat()
    elif fault=='root_overlap':p['root']=tc['source_path']
    elif fault=='actual_injection':p['mode']='ACTUAL'
    elif fault=='unknown':p['legacy_unknown_ids']=['new-unknown']
    else:
        names={'initial':'initial-private.json','frame':'worker-frame-private.json','request':'request-private.json','verification':'verification.json','result':'result.json','fee_before':'ledger-before-private.json','fee_after':'ledger-after-private.json','cleanup':'result.json'}
        target=root/names[fault]
        if fault=='cleanup':value=read_json(target);value['cleanup'][0]['removed']=False;write(target,value)
        else:write(target,{})
    write(pp,p);before=ledger_snapshot(c['ledger_path'])
    with pytest.raises((ValueError,OSError,KeyError,TypeError)):api().create(pp,file_hash(pp),cp,file_hash(cp),selection_operation_id='fixed-selection',clock=lambda:NOW)
    assert not list(Path(p['root']).glob('lease-*')) and ledger_snapshot(c['ledger_path'])==before


def test_unbound_lease_can_reserve_future_original_cycle_prepared_directory(completed):
    pp,p,cp,c,tc=completed;p['prepared_parent']=str(cp.parent/'planned-cycle/cycle-output/prepared');write(pp,p)
    value=api().create(pp,file_hash(pp),cp,file_hash(cp),clock=lambda:NOW)
    assert read_json(value['lease_path'])['scope']['allowed_fee_operation_ids']==[]
    assert not Path(p['prepared_parent']).exists()
