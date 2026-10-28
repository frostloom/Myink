"""Independent no-tool recommendations never publish FileReview permissions."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import importlib,json
import httpx,pytest
from ops.pi.audit import AuditStore,encoded,digest
from ops.pi.development_inputs import file_hash,ledger_snapshot
from ops.pi.review_dossier import compile_dossier
from ops.pi.tests.test_review_dossier import dossier_input,config_file
from ops.pi.tests.test_selection_launcher import proof
from ops.pi.tests.test_diagnosis_launcher import fake_frame

NOW=datetime(2026,10,29,0,0,tzinfo=timezone.utc)


def api():return importlib.import_module('ops.pi.sdk_review_launcher')


def write(p,v):p.write_bytes(encoded(v));p.chmod(0o600)


@pytest.fixture
def review_config(dossier_input):
    tp,tc,qp,q,op,o=dossier_input;parent=tp.parent;state=parent/'state';state.mkdir(mode=0o700)
    moved=state/'ledger.sqlite';Path(tc['ledger_path']).rename(moved);tc['ledger_path']=str(moved);write(tp,tc)
    d=compile_dossier(tp,file_hash(tp),qp,file_hash(qp),op,file_hash(op));dp=parent/'review-dossier.json';write(dp,d)
    audit=parent/'audit';audit.mkdir(mode=0o700);AuditStore(audit/'events.sqlite')
    c={k:tc[k] for k in ('runtime_path','runtime_sha256','ledger_path','ledger_sha256','policy_path','policy_sha256','credential_path','credential_sha256','docker','endpoint','daemon_id','image_id')}
    c.update(schema='pi-sdk-review-v1',role='independent_review',mode='SIMULATED',run_id='review-one',root=str(parent/'review-output'),deadline_seconds=60,
        template_path=str(tp),template_sha256=file_hash(tp),baseline_request_path=str(qp),baseline_request_sha256=file_hash(qp),outcome_path=str(op),outcome_sha256=file_hash(op),
        dossier_path=str(dp),dossier_sha256=file_hash(dp),permit_path=str(parent/'review-permit.json'),permit_sha256='0'*64,audit_path=str(audit/'events.sqlite'),export_root=str(parent/'export'))
    permit=dict(schema='pi-sdk-review-permit-v1',authority='independent_review_recommendation_only',mode=c['mode'],role=c['role'],run_id=c['run_id'],dossier_sha256=c['dossier_sha256'],semantic_sha256=d['semantic_sha256'],runtime_sha256=c['runtime_sha256'],policy_sha256=c['policy_sha256'],credential_sha256=c['credential_sha256'],ledger_path=c['ledger_path'],budget_scope='local-trial-1',budget_microyuan=10000000,max_model_requests=1,deadline_seconds=60,legacy_unknown_ids=[],issued_at=(NOW-timedelta(minutes=1)).isoformat(),expires_at=(NOW+timedelta(hours=1)).isoformat())
    write(Path(c['permit_path']),permit);c['permit_sha256']=file_hash(c['permit_path']);cp=parent/'review-config.json';write(cp,c)
    return cp,c,d,permit,tc


def recommendation(c,d,**changes):
    value=dict(schema='pi-independent-review-recommendation-v1',semantic_sha256=d['semantic_sha256'],dossier_sha256=c['dossier_sha256'],recommendation='approve',reason_code='validated_expectation',summary='Frozen test expectation matches existing source behavior contract.');value.update(changes);return value


def test_review_preflight_is_readonly_and_model_report_is_not_file_approval(review_config,monkeypatch):
    cp,c,d,p,tc=review_config;module=api();monkeypatch.setattr(module,'verify_source',lambda *args:dict(machine='aarch64'))
    before={p:p.read_bytes() for p in cp.parent.rglob('*') if p.is_file()};module.prepare(cp,clock=lambda:NOW)
    assert before=={p:p.read_bytes() for p in cp.parent.rglob('*') if p.is_file()} and not Path(c['root']).exists()
    good=recommendation(c,d);assert module.validate_recommendation(good,c,d)==good
    for bad in (dict(approved=True),dict(semantic_sha256='e'*64),dict(recommendation='execute'),dict(reason_code='self_approved'),dict(summary='x'*1001)):
        with pytest.raises(ValueError):module.validate_recommendation(dict(good,**bad),c,d)


@pytest.mark.parametrize('fault',['role','dossier','ledger','permit','authority','cap','expired','future','root_overlap','sidecar','actual_shadow','extra','root_audit_sidecar','export_audit_sidecar'])
def test_bad_review_scope_never_starts_sdk_or_billing(review_config,monkeypatch,fault):
    cp,c,d,p,tc=review_config;module=api();monkeypatch.setattr(module,'verify_source',lambda *args:dict(machine='aarch64'))
    if fault=='role':c['role']='developer_self_review'
    elif fault in ('dossier','ledger','permit'):c[fault+'_sha256']='f'*64
    elif fault=='authority':p['authority']='execute_development'
    elif fault=='cap':p['max_model_requests']=2
    elif fault=='expired':p['expires_at']=(NOW-timedelta(seconds=1)).isoformat()
    elif fault=='future':p['issued_at']=(NOW+timedelta(seconds=1)).isoformat()
    elif fault=='root_overlap':c['root']=str(Path(tc['source_path'])/'inside')
    elif fault=='sidecar':alias=Path(c['audit_path']+'-journal');alias.write_bytes(Path(c['dossier_path']).read_bytes());alias.chmod(0o600);c['dossier_path']=str(alias)
    elif fault=='actual_shadow':c['mode']='ACTUAL'
    elif fault=='root_audit_sidecar':c['root']=c['audit_path']+'-journal'
    elif fault=='export_audit_sidecar':c['export_root']=c['audit_path']+'-journal'
    else:c['approved']=True
    if fault in ('authority','cap','expired','future'):write(Path(c['permit_path']),p);c['permit_sha256']=file_hash(c['permit_path'])
    write(cp,c);before=ledger_snapshot(c['ledger_path'])
    with pytest.raises((ValueError,OSError)):module.prepare(cp,clock=lambda:NOW)
    assert ledger_snapshot(c['ledger_path'])==before and not Path(c['root']).exists()


@pytest.mark.parametrize('scenario',['approve','reject','bad_report','bad_receipt','unknown_usage','cleanup','before_revoke','source_revoke','gold_revoke','policy_drift','credential_missing'])
def test_independent_sdk_lifecycle_fee_and_permission_separation(review_config,proof,monkeypatch,scenario):
    cp,c,d,p,tc=review_config;module=api();host_module=importlib.import_module('ops.pi.no_tool_host');monkeypatch.setattr(module,'verify_source',lambda *args:dict(machine='aarch64'))
    class Host:operation_id='synthetic';owned={};pending={}
    monkeypatch.setattr(host_module,'_host',lambda *args:Host())
    class Owners:
        failed=False
        def __init__(self,*args):pass
        def add(self,h):return h
        def finish(self):
            if scenario=='cleanup':raise RuntimeError('synthetic cleanup failure')
            return [dict(container_id='owned',removed=True)]
    monkeypatch.setattr(host_module,'OwnedHosts',Owners)
    value=recommendation(c,d,**(dict(recommendation='reject',reason_code='unsupported_expectation') if scenario=='reject' else dict(approved=True) if scenario=='bad_report' else {}));text=json.dumps(value)
    def exchange(host,config,initial,bridge,transport,limits,write,**kwargs):
        assert kwargs['worker']=='selection.py' and str(cp.parent) not in initial['prompt'] and initial['system']==module.SYSTEM
        if scenario=='before_revoke':Path(c['permit_path']).write_bytes(b'{}')
        if scenario=='source_revoke':
            source=Path(tc['source_path'])/d['model_view']['source_files'][0]['path'];source.write_bytes(source.read_bytes()+b'\n# revoked\n')
        if scenario=='gold_revoke':Path(tc['test_path']).write_bytes(Path(tc['test_path']).read_bytes()+b'\n# revoked\n')
        request=dict(model=initial['model'],max_tokens=initial['max_tokens'],system=[dict(type='text',text=initial['system']+'\n\n<cwd>\n/work/candidate\n</cwd>')],messages=[dict(role='user',content=[dict(type='text',text=initial['prompt'])])],stream=True)
        bridge.route(dict(type='request',path='/v1/messages',headers=[['x-api-key',initial['model_token']],['x-pi-scope','local-trial-1']],body=json.dumps(request)),transport)
        if scenario=='policy_drift':Path(c['policy_path']).write_bytes(b'operator-revoked')
        if scenario=='credential_missing':Path(c['credential_path']).unlink()
        frame=fake_frame(proof[0],initial,text)
        if scenario=='bad_receipt':frame['receipt']['evidence']['protocol_failed']=True
        return frame
    monkeypatch.setattr(host_module,'_exchange',exchange)
    def send(body,timeout):
        usage={} if scenario=='unknown_usage' else dict(input_tokens=1,output_tokens=1,cache_read_input_tokens=0,cache_creation_input_tokens=0)
        events=[dict(type='message_start',message=dict(usage=usage)),dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text=text)),dict(type='message_delta',usage=dict(output_tokens=1) if usage else {}),dict(type='message_stop')]
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=httpx.ByteStream(''.join('data: '+json.dumps(v)+'\n\n' for v in events).encode()))
    original=Path(c['policy_path']).read_bytes();approval=Path(tc['review_path']).read_bytes();before=ledger_snapshot(c['ledger_path'])
    result=module.execute(cp,transport=send,clock=lambda:NOW,expected_config_sha256=file_hash(cp))
    assert result['verified']==(scenario in ('approve','reject')) and result['executable_approval'] is False
    assert result['new_attempts']==(0 if scenario in ('before_revoke','source_revoke','gold_revoke') else 1) and result['new_unknown']==(1 if scenario=='unknown_usage' else 0)
    assert Path(tc['review_path']).read_bytes()==approval and not Path(tc['root']).exists() and result['original_history_unchanged']
    assert Path(c['policy_path']).read_bytes()==(b'operator-revoked' if scenario=='policy_drift' else original)
    events=AuditStore(c['audit_path']).events(run_id=c['run_id']);assert any(e['kind']=='review' for e in events)
    assert text not in json.dumps(events)  # Full untrusted summary/report stays private.
    assert ledger_snapshot(c['ledger_path'])['events'][:len(before['events'])]==before['events']
    with pytest.raises(ValueError):module.execute(cp,transport=send,clock=lambda:NOW,expected_config_sha256=file_hash(cp))


def test_intent_directory_sync_failure_keeps_claim_without_paid_request(review_config,monkeypatch):
    cp,c,d,p,tc=review_config;module=api();host_module=importlib.import_module('ops.pi.no_tool_host');monkeypatch.setattr(module,'verify_source',lambda *args:dict(machine='aarch64'))
    original=host_module.os.fsync;calls=[]
    def sync(fd):
        calls.append(fd)
        if len(calls)==3:raise OSError('synthetic directory sync failure')
        return original(fd)
    monkeypatch.setattr(host_module.os,'fsync',sync);before=ledger_snapshot(c['ledger_path'])
    with pytest.raises(OSError):module.execute(cp,transport=lambda *args:None,clock=lambda:NOW,expected_config_sha256=file_hash(cp))
    assert (Path(c['root'])/'intent.json').is_file() and ledger_snapshot(c['ledger_path'])==before
    with pytest.raises(ValueError):module.execute(cp,transport=lambda *args:None,clock=lambda:NOW,expected_config_sha256=file_hash(cp))
