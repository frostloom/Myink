"""Dedicated proposal-only SDK role over authenticated observation and original fees."""
from pathlib import Path
from datetime import timedelta
import importlib,json
import httpx,pytest
from ops.pi.audit import encoded,AuditStore
from ops.pi.development_inputs import file_hash,ledger_snapshot,tree_hash,read_json
from ops.pi.investigation_inputs import compile_context
from ops.pi.tests.test_diagnosis_launcher import diagnosis_config,config_file,configured,proof,fake_frame,NOW


def write(p,v):p.write_bytes(encoded(v));p.chmod(0o600)


@pytest.fixture
def research_config(diagnosis_config):
    old_cp,old,e,m,permit=diagnosis_config;parent=old_cp.parent
    credentials=read_json(old['credential_path']);credentials['PLATFORM_MODEL_API_KEY']='local-private-provider-key';write(Path(old['credential_path']),credentials)
    source=parent/'source';pending=parent/'pending-findings.json';write(pending,[])
    context=compile_context(source,tree_hash(source),['src/a.py'],e,credential_literal=credentials['PLATFORM_MODEL_API_KEY']);input_path=parent/'research-input.json';write(input_path,context)
    claims=parent/'investigations';claims.mkdir(mode=0o700)
    c={k:old[k] for k in ('mode','runtime_path','runtime_sha256','ledger_path','ledger_sha256','policy_path','policy_sha256','credential_path','docker','endpoint','daemon_id','image_id','observer_config_path','observer_config_sha256','observer_controller_sha256','observation_receipt_path','evidence_path','evidence_sha256','audit_path','export_root')}
    c.update(schema='pi-investigation-v1',role='investigation',run_id='investigation-one',root=str(claims/('research-'+context['research_fingerprint'])),credential_sha256=file_hash(old['credential_path']),deadline_seconds=60,source_path=str(source),source_sha256=tree_hash(source),files=['src/a.py'],reference_commit=None,pending_path=str(pending),pending_sha256=file_hash(pending),input_path=str(input_path),input_sha256=file_hash(input_path),permit_path=str(parent/'research-permit.json'),permit_sha256='0'*64)
    p=dict(schema='pi-investigation-permit-v1',authority='test_proposal_only',mode=c['mode'],role=c['role'],run_id=c['run_id'],research_fingerprint=context['research_fingerprint'],evidence_fingerprint=e['evidence_fingerprint'],input_sha256=c['input_sha256'],evidence_sha256=c['evidence_sha256'],source_sha256=c['source_sha256'],pending_sha256=c['pending_sha256'],runtime_sha256=c['runtime_sha256'],policy_sha256=c['policy_sha256'],credential_sha256=c['credential_sha256'],ledger_path=c['ledger_path'],claim_root=str(claims),budget_scope='local-trial-1',budget_microyuan=10000000,max_model_requests=1,deadline_seconds=60,legacy_unknown_ids=[],issued_at=(NOW-timedelta(minutes=1)).isoformat(),expires_at=(NOW+timedelta(minutes=10)).isoformat())
    write(Path(c['permit_path']),p);c['permit_sha256']=file_hash(c['permit_path']);cp=parent/'investigation-config.json';write(cp,c);return cp,c,context,p


def api():return importlib.import_module('ops.pi.investigation_launcher')


def proposal(context,**changes):
    from ops.pi.audit import digest
    r=dict(schema='pi-test-proposal-v1',input_sha256=digest(context),decision='task',problem='Proposed existing-behavior defect requiring independent review.',files=['src/a.py'],test_source='import unittest\nfrom a import value\nclass Case(unittest.TestCase):\n def test_value(self): self.assertEqual(value,2)\n',summary='This test is untrusted, no execution permission.');r.update(changes);return r


def test_investigation_preflight_reads_verified_observation_without_any_mutation(research_config,monkeypatch):
    cp,c,context,p=research_config;module=api();monkeypatch.setattr(module,'verify_source',lambda *args:dict(machine='aarch64'))
    before={p:p.read_bytes() for p in cp.parent.rglob('*') if p.is_file()};value=module.prepare(cp,clock=lambda:NOW)
    assert value[0]==c and before=={p:p.read_bytes() for p in cp.parent.rglob('*') if p.is_file()} and not Path(c['root']).exists()


@pytest.mark.parametrize('fault',['role','evidence','input','pending','permit','authority','cap','expiry','source','root','actual_shadow','extra'])
def test_invalid_research_authority_stops_before_sdk_and_fees(research_config,monkeypatch,fault):
    cp,c,context,p=research_config;module=api();monkeypatch.setattr(module,'verify_source',lambda *args:dict(machine='aarch64'))
    if fault=='role':c['role']='developer'
    elif fault in ('evidence','input','pending','permit'):c[fault+'_sha256']='f'*64
    elif fault=='authority':p['authority']='execute_development'
    elif fault=='cap':p['max_model_requests']=2
    elif fault=='expiry':p['expires_at']=NOW.isoformat()
    elif fault=='source':(Path(c['source_path'])/'src/a.py').write_text('changed')
    elif fault=='root':c['root']=str(Path(c['root']).parent/'fresh-run-escape')
    elif fault=='actual_shadow':c['mode']='ACTUAL'
    else:c['approved']=True
    if fault in ('authority','cap','expiry'):write(Path(c['permit_path']),p);c['permit_sha256']=file_hash(c['permit_path'])
    write(cp,c);before=ledger_snapshot(c['ledger_path'])
    with pytest.raises((ValueError,OSError)):module.prepare(cp,clock=lambda:NOW)
    assert ledger_snapshot(c['ledger_path'])==before and not Path(c['root']).exists()


@pytest.mark.parametrize('scenario',['task','no_task','bad_output','bad_receipt','unknown_usage','cleanup','before_revoke','policy_revoke','renamed_reentry'])
def test_one_proposal_session_preserves_original_fees_and_never_approves_development(research_config,proof,monkeypatch,scenario):
    cp,c,context,p=research_config;module=api();host=importlib.import_module('ops.pi.no_tool_host');monkeypatch.setattr(module,'verify_source',lambda *args:dict(machine='aarch64'))
    class H:operation_id='research-owned';owned={};pending={}
    class Owners:
        failed=False
        def __init__(self,*args):pass
        def add(self,h):return h
        def finish(self):
            if scenario=='cleanup':raise RuntimeError('synthetic cleanup failure')
            return [dict(container_id='b'*64,removed=True)]
    monkeypatch.setattr(host,'_host',lambda *args:H());monkeypatch.setattr(host,'OwnedHosts',Owners)
    value=proposal(context,**(dict(decision='no_task',problem=None,files=[],test_source=None) if scenario=='no_task' else dict(approved=True) if scenario=='bad_output' else {}));text=json.dumps(value)
    def exchange(h,config,initial,bridge,transport,limits,save,**kwargs):
        assert initial['system']==module.SYSTEM and str(cp.parent) not in initial['prompt'] and kwargs['worker']=='selection.py'
        if scenario=='before_revoke':write(Path(c['permit_path']),{})
        body=dict(model=initial['model'],max_tokens=initial['max_tokens'],system=[dict(type='text',text=module.wire_system(initial['system']))],messages=[dict(role='user',content=[dict(type='text',text=initial['prompt'])])],stream=True)
        bridge.route(dict(type='request',path='/v1/messages',headers=[['x-api-key',initial['model_token']],['x-pi-scope','local-trial-1']],body=json.dumps(body)),transport)
        if scenario=='policy_revoke':Path(c['policy_path']).write_bytes(b'operator-revoked')
        frame=fake_frame(proof[0],initial,text)
        if scenario=='bad_receipt':frame['receipt']['evidence']['protocol_failed']=True
        save('worker-frame-private.json',frame);return frame
    monkeypatch.setattr(host,'_exchange',exchange)
    def send(body,timeout):
        usage={} if scenario=='unknown_usage' else dict(input_tokens=1,output_tokens=1,cache_read_input_tokens=0,cache_creation_input_tokens=0)
        events=[dict(type='message_start',message=dict(usage=usage)),dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text=text)),dict(type='message_delta',usage=dict(output_tokens=1) if usage else {}),dict(type='message_stop')]
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=httpx.ByteStream(''.join('data: '+json.dumps(v)+'\n\n' for v in events).encode()))
    result=module.execute(cp,transport=send,clock=lambda:NOW,expected_config_sha256=file_hash(cp))
    assert result['verified']==(scenario in ('task','no_task','renamed_reentry')) and result['executable_approval'] is False
    assert result['new_attempts']==(0 if scenario=='before_revoke' else 1) and result['new_unknown']==(1 if scenario=='unknown_usage' else 0)
    assert result['original_history_unchanged'] and not list(cp.parent.glob('**/task-draft.json'))
    events=AuditStore(c['audit_path']).events(run_id=c['run_id']);assert any(e['kind']=='analysis' for e in events) and text not in json.dumps(events)
    with pytest.raises(ValueError):module.execute(cp,transport=send,clock=lambda:NOW,expected_config_sha256=file_hash(cp))

    if scenario=='renamed_reentry':
        newer=dict(c,run_id='investigation-renamed',ledger_sha256=ledger_snapshot(c['ledger_path'])['sha256'])
        new_permit=dict(p,run_id=newer['run_id']);permit_path=cp.parent/'renamed-permit.json';write(permit_path,new_permit)
        newer.update(permit_path=str(permit_path),permit_sha256=file_hash(permit_path));new_cp=cp.parent/'renamed-config.json';write(new_cp,newer)
        before=ledger_snapshot(c['ledger_path'])
        with pytest.raises(ValueError,match='fingerprint claim'):module.execute(new_cp,transport=send,clock=lambda:NOW,expected_config_sha256=file_hash(new_cp))
        assert ledger_snapshot(c['ledger_path'])==before


def test_simulation_cannot_mutate_the_canonical_fee_ledger(research_config,monkeypatch):
    cp,c,context,p=research_config;module=api();monkeypatch.setattr(module,'CANONICAL',Path(c['ledger_path']));monkeypatch.setattr(module,'verify_source',lambda *args:dict(machine='aarch64'))
    before=ledger_snapshot(c['ledger_path'])
    with pytest.raises(ValueError,match='SIMULATED requires isolated billing'):module.prepare(cp,clock=lambda:NOW)
    assert ledger_snapshot(c['ledger_path'])==before and not Path(c['root']).exists()


def test_formatted_input_advertises_canonical_proposal_identity(research_config,monkeypatch):
    from ops.pi.audit import digest
    cp,c,context,p=research_config;module=api();monkeypatch.setattr(module,'verify_source',lambda *args:dict(machine='aarch64'))
    Path(c['input_path']).write_text(json.dumps(context,indent=2)+'\n');c['input_sha256']=file_hash(c['input_path']);p['input_sha256']=c['input_sha256']
    write(Path(c['permit_path']),p);c['permit_sha256']=file_hash(c['permit_path']);write(cp,c)
    prepared=module.prepare(cp,clock=lambda:NOW);wire=json.loads(module.prompt(c,prepared[2]).split('\n',1)[1])
    assert wire['input_sha256']==digest(context) and wire['input_sha256']!=c['input_sha256']
    assert module.validate_output(proposal(context),c,prepared[2])['decision']=='task'


def test_input_binding_rejects_bool_that_compares_equal_to_host_count(research_config,monkeypatch):
    cp,c,context,p=research_config;module=api();monkeypatch.setattr(module,'verify_source',lambda *args:dict(machine='aarch64'))
    forged=dict(context,observed_samples=True);write(Path(c['input_path']),forged);c['input_sha256']=file_hash(c['input_path']);p['input_sha256']=c['input_sha256']
    write(Path(c['permit_path']),p);c['permit_sha256']=file_hash(c['permit_path']);write(cp,c)
    before=ledger_snapshot(c['ledger_path'])
    with pytest.raises(ValueError,match='input drift'):module.prepare(cp,clock=lambda:NOW)
    assert ledger_snapshot(c['ledger_path'])==before
