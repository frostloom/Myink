"""No-tool SDK diagnosis has frozen evidence, one original-ledger call and no authority."""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import importlib,json,time
import httpx,pytest
from ops.pi.audit import encoded,digest,AuditStore
from ops.pi.development_inputs import file_hash,ledger_snapshot
from ops.pi.tests.test_development_inputs import config_file
from ops.pi.tests.test_live_observer import configured,Rows,run,NOW,api as observer
from ops.pi.live_diagnosis import inspect_observation
from ops.pi.diagnostic_memory import build_memory
from ops.pi.tests.test_selection_launcher import proof


def api():return importlib.import_module('ops.pi.diagnosis_launcher')


def write(path,value):path.write_bytes(encoded(value));path.chmod(0o600);return str(path)


@pytest.fixture
def diagnosis_config(config_file,configured,monkeypatch):
    cp,old=config_file;root=cp.parent
    state=root/'state';state.mkdir(mode=0o700);original_ledger=Path(old['ledger_path']);moved=state/'ledger.sqlite';original_ledger.rename(moved);old=dict(old,ledger_path=str(moved),ledger_sha256=ledger_snapshot(moved)['sha256'])
    result=run(configured,Rows(1));op,oc=configured;receipt=Path(oc['root'])/result['run_id']/'receipt.json';controller=observer()._controller()
    evidence=inspect_observation(op,file_hash(op),receipt,expected_controller_sha256=controller,clock=lambda:NOW)
    scope={k:evidence[k] for k in ('evidence_domain','source_commit','candidate_sha256','observer_controller_sha256','observer_policy_sha256','cohort_sha256')}
    export=Path(oc['audit_path']).parent/'export';memory=build_memory(export,scope,now=NOW)
    c={k:old[k] for k in ('runtime_path','runtime_sha256','ledger_path','ledger_sha256','policy_path','policy_sha256','credential_path','credential_sha256','docker','endpoint','daemon_id','image_id')}
    c.update(schema='pi-live-diagnosis-v1',mode='SIMULATED',run_id='diagnosis-one',root=str(root/'diagnosis-output'),deadline_seconds=60,
        observer_config_path=str(op),observer_config_sha256=file_hash(op),observer_controller_sha256=controller,observation_receipt_path=str(receipt),
        evidence_path=write(root/'evidence.json',evidence),evidence_sha256=digest(evidence),memory_path=write(root/'memory.json',memory),memory_sha256=digest(memory),memory_export_root=str(export),
        permit_path=str(root/'diagnosis-permit.json'),permit_sha256='0'*64,audit_path=oc['audit_path'],export_root=str(export))
    permit=dict(schema='pi-diagnosis-permit-v1',authority='analysis_only',mode=c['mode'],run_id=c['run_id'],evidence_fingerprint=evidence['evidence_fingerprint'],evidence_sha256=c['evidence_sha256'],memory_sha256=c['memory_sha256'],runtime_sha256=c['runtime_sha256'],policy_sha256=c['policy_sha256'],credential_sha256=c['credential_sha256'],ledger_path=c['ledger_path'],budget_scope='local-trial-1',budget_microyuan=10000000,max_model_requests=1,deadline_seconds=60,legacy_unknown_ids=[])
    write(Path(c['permit_path']),permit);c['permit_sha256']=file_hash(c['permit_path']);cp=root/'diagnosis-config.json';write(cp,c)
    return cp,c,evidence,memory,permit


def check(configured):return api().prepare(configured[0],clock=lambda:NOW)


def report(evidence,**changes):
    value=dict(schema='pi-live-diagnosis-report-v1',evidence_fingerprint=evidence['evidence_fingerprint'],decision='investigate',reason_code='insufficient_samples',observed_samples=evidence['observed_samples'],minimum_samples=evidence['minimum_samples'],summary='Need comparable evidence, no repair approval.');value.update(changes);return value


def test_report_is_strictly_an_investigation_not_a_permission(diagnosis_config):
    _,_,e,_,_=diagnosis_config;r=report(e)
    assert api().validate_diagnosis(r,e)==r
    for changed in (dict(approved=True),dict(decision='repair'),dict(observed_samples=20),dict(reason_code='self_approved'),dict(summary='x'*1001),dict(evidence_fingerprint='0'*64)):
        with pytest.raises(ValueError):api().validate_diagnosis(dict(r,**changed),e)


def test_preflight_is_readonly_and_binds_context_memory_permit(diagnosis_config,monkeypatch):
    cp,c,e,m,p=diagnosis_config;module=api();monkeypatch.setattr(module,'verify_source',lambda *a:dict(machine='aarch64'))
    before={x:x.read_bytes() for x in cp.parent.rglob('*') if x.is_file()}
    prepared=check(diagnosis_config)
    assert prepared[0]==c and not Path(c['root']).exists() and not Path(c['ledger_path']).with_suffix('.tools.lock').exists()
    assert before=={x:x.read_bytes() for x in cp.parent.rglob('*') if x.is_file()}


@pytest.mark.parametrize('fault',['schema','evidence','memory','permit','ledger','policy','credential','observer','controller','deadline','extra','output_overlap','export_overlap','source_drift','memory_expired','permit_authority','permit_cap','permit_fingerprint','actual_shadow_ledger'])
def test_bad_frozen_authority_rejected_before_any_session(diagnosis_config,monkeypatch,fault):
    cp,c,e,m,p=diagnosis_config;module=api();monkeypatch.setattr(module,'verify_source',lambda *a:dict(machine='aarch64'))
    if fault in ('evidence','memory','permit','ledger','policy','credential'):c[fault+'_sha256']='f'*64
    elif fault=='schema':c['schema']='other'
    elif fault=='observer':c['observer_config_sha256']='f'*64
    elif fault=='controller':c['observer_controller_sha256']='f'*64
    elif fault=='deadline':c['deadline_seconds']=121
    elif fault=='extra':c['shell']='forbidden'
    elif fault=='output_overlap':c['root']=str(cp.parent)
    elif fault=='export_overlap':c['export_root']=str(cp.parent)
    elif fault=='source_drift':Path(c['observation_receipt_path']).write_text('{}')
    elif fault=='memory_expired':
        m['expires_at']=(NOW-timedelta(seconds=1)).isoformat();write(Path(c['memory_path']),m);c['memory_sha256']=digest(m)
    elif fault in ('permit_authority','permit_cap','permit_fingerprint'):
        if fault=='permit_authority':p['authority']='execute_development'
        elif fault=='permit_cap':p['max_model_requests']=2
        else:p['evidence_fingerprint']='f'*64
        write(Path(c['permit_path']),p);c['permit_sha256']=file_hash(c['permit_path'])
    else:c['mode']='ACTUAL'
    write(cp,c)
    with pytest.raises((ValueError,OSError)):check(diagnosis_config)


def fake_frame(base,initial,text):
    frame=deepcopy(base);rows=[json.loads(s) for s in frame['session'].splitlines()]
    messages=[r['message'] for r in rows if r['type']=='message']
    messages[0]['sections']['preamble']=initial['system'];messages[1]['content'][0]['text']=initial['prompt'];messages[2]['content'][0]['text']=text
    frame['session']=''.join(json.dumps(r)+'\n' for r in rows)
    rpc=[json.loads(s) for s in frame['transcript'].splitlines()];index=0
    for row in rpc:
        r=row['record']
        if row['direction']=='in' and r['type']=='prompt':r['message']=initial['prompt']
        if row['direction']=='out' and r['type']=='message_end':r['message']=messages[index];index+=1
    frame['transcript']=''.join(json.dumps(r)+'\n' for r in rpc)
    frame['receipt']['evidence'].update(config_hash=initial['config_hash'],plan_id=initial['context_hash'],text=text,session_sha256=sha256(frame['session'].encode()).hexdigest())
    return frame


@pytest.mark.parametrize('scenario',['pass','bad_output','bad_receipt','unknown_usage','cleanup','exchange_failure','config_drift','credential_missing','policy_drift','memory_drift','config_before_request','permit_before_request'])
def test_simulated_full_flow_preserves_fee_history_and_closes_policy(diagnosis_config,proof,monkeypatch,scenario):
    cp,c,e,m,p=diagnosis_config;module=api();monkeypatch.setattr(module,'verify_source',lambda *a:dict(machine='aarch64'))
    class Host:
        operation_id='synthetic';owned={};pending={}
    monkeypatch.setattr(module,'_host',lambda *a:Host())
    class Owners:
        failed=False
        def __init__(self,*a):pass
        def add(self,h):return h
        def finish(self):
            if scenario=='cleanup':raise RuntimeError('synthetic cleanup failure')
            return [dict(removed=True,container_id='owned')]
    monkeypatch.setattr(module,'OwnedHosts',Owners)
    def exchange(host,config,initial,bridge,transport,limits,write,**kwargs):
        assert kwargs['worker']=='selection.py'
        if scenario=='exchange_failure':raise RuntimeError('synthetic SDK failure')
        text=json.dumps(report(e,decision='repair') if scenario=='bad_output' else report(e))
        request=dict(model=initial['model'],max_tokens=initial['max_tokens'],system=[dict(type='text',text=initial['system']+'\n\n<cwd>\n/work/candidate\n</cwd>')],messages=[dict(role='user',content=[dict(type='text',text=initial['prompt'])])],stream=True)
        if scenario=='config_before_request':cp.write_bytes(cp.read_bytes()+b' ')
        elif scenario=='permit_before_request':Path(c['permit_path']).write_bytes(b'{}')
        bridge.route(dict(type='request',path='/v1/messages',headers=[['x-api-key',initial['model_token']],['x-pi-scope','local-trial-1']],body=json.dumps(request)),transport)
        if scenario=='config_drift':cp.write_bytes(cp.read_bytes()+b' ')
        elif scenario=='credential_missing':Path(c['credential_path']).unlink()
        elif scenario=='policy_drift':Path(c['policy_path']).write_bytes(b'host-revoked-policy')
        elif scenario=='memory_drift':Path(c['memory_path']).write_bytes(b'{}')
        frame=fake_frame(proof[0],initial,text)
        if scenario=='bad_receipt':frame['receipt']['evidence']['protocol_failed']=True
        return frame
    monkeypatch.setattr(module,'_exchange',exchange)
    original=Path(c['policy_path']).read_bytes();credential=Path(c['credential_path']).read_bytes();before=ledger_snapshot(c['ledger_path'])
    def send(body,timeout):
        usage={} if scenario=='unknown_usage' else dict(input_tokens=1,output_tokens=1,cache_read_input_tokens=0,cache_creation_input_tokens=0)
        text=json.dumps(report(e,decision='repair') if scenario=='bad_output' else report(e))
        events=[dict(type='message_start',message=dict(usage=usage)),dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text=text)),dict(type='message_delta',usage=dict(output_tokens=1) if usage else {}),dict(type='message_stop')]
        raw=''.join('data: '+json.dumps(v)+'\n\n' for v in events).encode()
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=httpx.ByteStream(raw))
    result=module.execute(cp,transport=send,clock=lambda:NOW,expected_config_sha256=file_hash(cp))
    assert result['mode']=='SIMULATED' and result['verified']==(scenario=='pass')
    assert Path(c['policy_path']).read_bytes()==(b'host-revoked-policy' if scenario=='policy_drift' else original)
    if scenario=='credential_missing':assert not Path(c['credential_path']).exists() and not result['credential_unchanged']
    else:assert Path(c['credential_path']).read_bytes()==credential
    assert result['original_history_unchanged'] and result['policy_restored']==(scenario!='policy_drift')
    assert result['new_attempts']==(0 if scenario in ('exchange_failure','config_before_request','permit_before_request') else 1)
    assert result['new_unknown']==(1 if scenario=='unknown_usage' else 0)
    assert before['events']==ledger_snapshot(c['ledger_path'])['events'][:len(before['events'])]
    with pytest.raises(ValueError):module.execute(cp,transport=send,clock=lambda:NOW,expected_config_sha256=file_hash(cp))
    events=AuditStore(c['audit_path']).events(run_id=c['run_id'])
    assert {'analysis','memory','version'}<={event['kind'] for event in events}
    assert next(event for event in events if event['kind']=='analysis')['details']['model_requests']==result['new_attempts']
    if scenario=='unknown_usage':
        # A fresh run/config/checkpoint must not reclassify a newly unknown charge as legacy.
        c.update(run_id='diagnosis-two',root=str(cp.parent/'diagnosis-two'),ledger_sha256=ledger_snapshot(c['ledger_path'])['sha256'])
        p['run_id']=c['run_id'];write(Path(c['permit_path']),p);c['permit_sha256']=file_hash(c['permit_path']);write(cp,c)
        with pytest.raises(ValueError,match='new unknown billing'):module.prepare(cp,clock=lambda:NOW)
        assert not Path(c['root']).exists()


def test_actual_diagnosis_rejects_injected_transport_without_spending(diagnosis_config):
    cp,c,*_=diagnosis_config;c['mode']='ACTUAL';write(cp,c)
    with pytest.raises(ValueError,match='ACTUAL'):api().execute(cp,transport=lambda *a:pytest.fail('sent'),expected_config_sha256=file_hash(cp))
