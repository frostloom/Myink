"""Trusted launcher with synthetic secrets/SQLite/HTTP/children only, no Docker."""
from contextlib import contextmanager
from dataclasses import asdict, replace
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from ops.pi import container_runtime as runtime
from ops.pi.analysis_budget import _scope_identity
from ops.pi.analysis_execution import _hash
from ops.pi.ledger import Ledger, LedgerBlocked
from ops.pi.tests.test_container_runtime import source_fixture
from ops.pi.tests.test_provider_config import creds
from ops.pi.tests.test_container_probe import Daemon, CID, DAEMON, IMAGE, ENDPOINT


def api():
    assert importlib.util.find_spec('ops.pi.analysis_launcher'), 'trusted host launcher missing'
    return importlib.import_module('ops.pi.analysis_launcher')


@pytest.fixture
def setup(tmp_path, monkeypatch):
    run,p,slots,view,report,_=runtime.synthetic_run(tmp_path/'original')
    fixture=runtime.fixture()
    monkeypatch.setattr(runtime,'fixture',lambda:fixture)
    p=replace(p,base_url='https://api.deepseek.com/anthropic',live_enabled=True,input_bound_calibrated=True)
    policy=tmp_path/'policy.json';policy.write_text(json.dumps(asdict(p)))
    private=tmp_path/'credentials';private.mkdir(mode=0o700)
    credential=private/'platform.json';credential.write_text(json.dumps(creds()));credential.chmod(0o600)
    inputs=tmp_path/'inputs.json';inputs.write_text(json.dumps(dict(views={g:view for g in runtime.GROUPS},report=report)))
    raw=tmp_path/'official.html';raw.write_text('synthetic published evidence, not current prices')
    from hashlib import sha256
    evidence=dict(schema='pi-provider-evidence-v1',policy_sha256=_hash(asdict(p)),review_reference='synthetic-review',
        valid_until=time.time()+900,price=dict(path=str(raw),sha256=sha256(raw.read_bytes()).hexdigest()),
        input_bound=dict(path=str(raw),sha256=sha256(raw.read_bytes()).hexdigest()))
    ep=tmp_path/'evidence.json';ep.write_text(json.dumps(evidence))
    with run.ledger.transaction() as db:scope=_scope_identity(db)
    source,digest=source_fixture(tmp_path,monkeypatch)
    code=runtime.verify_source(source,digest)['code_sha256']
    cfg=dict(schema='pi-analysis-launch-v1',ledger_path=str(run.ledger.path),policy_path=str(policy),
        credential_path=str(credential),input_path=str(inputs),evidence_path=str(ep),root=str(tmp_path/'result'),
        source=str(source),docker='/synthetic/docker',endpoint=ENDPOINT,daemon_id=DAEMON,image_id=IMAGE,
        runtime_sha256=digest,expected_code_sha256=code,expected_input_sha256=_hash(json.loads(inputs.read_text())),
        expected_evidence_sha256=_hash(evidence),expected_scope_sha256=scope,expected_policy_sha256=_hash(asdict(p)),
        run_id='host-launch-test',cap_microyuan=100000,deadline=time.time()+180)
    return cfg,run.ledger,p,view,report


def test_check_is_read_only_body_free_and_does_not_construct_writers(setup,monkeypatch):
    c,ledger,_,_,_=setup
    before=ledger.path.read_bytes()
    def forbidden(*a,**k):pytest.fail('check produced a side effect')
    m=api()
    monkeypatch.setattr(m,'Ledger',forbidden)
    monkeypatch.setattr(m,'_provider',forbidden)
    monkeypatch.setattr(m.ProbeHost,'create',forbidden)
    result=m.launch(c)
    assert result['status']=='checked' and result['launch_ready'] is True
    assert result['execution_requested'] is False and result['planned_slots']==30 and result['selected_slots']==2
    assert ledger.path.read_bytes()==before and not Path(c['root']).exists()
    encoded=json.dumps(result)
    for private in ('sk-synthetic',str(ledger.path),'synthetic-review','synthetic published','chars:'):
        assert private not in encoded


def test_live_disabled_check_succeeds_but_execution_cannot_write(setup):
    c,ledger,p,_,_=setup
    p=replace(p,live_enabled=False)
    Path(c['policy_path']).write_text(json.dumps(asdict(p)));c['expected_policy_sha256']=_hash(asdict(p))
    e=json.loads(Path(c['evidence_path']).read_text());e['policy_sha256']=c['expected_policy_sha256']
    Path(c['evidence_path']).write_text(json.dumps(e));c['expected_evidence_sha256']=_hash(e)
    before=ledger.path.read_bytes()
    assert api().launch(c)['launch_ready'] is False
    with pytest.raises(LedgerBlocked,match='^analysis launch blocked$'):api().launch(c,execute=True)
    assert not Path(c['root']).exists() and ledger.path.read_bytes()==before


@pytest.mark.parametrize('field,value',[
    ('cap_microyuan',True),('cap_microyuan',1),('cap_microyuan',20000001),
    ('deadline',1),('deadline',float('nan')),('deadline',float('inf')),('deadline',True),
    ('expected_scope_sha256','0'*64),('expected_policy_sha256','0'*64),
    ('expected_input_sha256','0'*64),('expected_code_sha256','0'*64),
    ('expected_evidence_sha256','0'*64),('run_id','../bad'),('image_id','latest'),
    ('endpoint','tcp://127.0.0.1:2375'),('schema','other'),('extra','PRIVATE')])
def test_invalid_identity_or_limits_cannot_mutate_ledger(setup,field,value):
    c,ledger,_,_,_=setup;before=ledger.path.read_bytes()
    with pytest.raises(LedgerBlocked,match='^analysis launch blocked$'):
        api().launch(c|{field:value},execute=True)
    assert ledger.path.read_bytes()==before and not Path(c['root']).exists()


@pytest.mark.parametrize('what',['credential-mode','directory-mode','price-bytes','expired-evidence','long-deadline','input-drift','duplicate-json','existing-root'])
def test_unreviewed_or_insecure_inputs_block_before_intent(setup,what):
    c,ledger,_,_,_=setup
    if what=='credential-mode':Path(c['credential_path']).chmod(0o644)
    elif what=='directory-mode':Path(c['credential_path']).parent.chmod(0o755)
    elif what=='price-bytes':Path(json.loads(Path(c['evidence_path']).read_text())['price']['path']).write_text('changed')
    elif what=='expired-evidence':
        e=json.loads(Path(c['evidence_path']).read_text());e['valid_until']=time.time()-1
        Path(c['evidence_path']).write_text(json.dumps(e));c['expected_evidence_sha256']=_hash(e)
    elif what=='long-deadline':c['deadline']=time.time()+601
    elif what=='input-drift':Path(c['input_path']).write_text('{}')
    elif what=='duplicate-json':Path(c['input_path']).write_text('{"views":{},"views":{},"report":{}}')
    else:Path(c['root']).mkdir()
    before=ledger.path.read_bytes()
    with pytest.raises(LedgerBlocked):api().launch(c,execute=True)
    assert ledger.path.read_bytes()==before


def test_cli_redacts_invalid_private_paths(tmp_path,capsys):
    c=tmp_path/'PRIVATE.json';c.write_text('{"schema":"PRIVATE"}')
    assert api().main(['--config',str(c),'--execute'])==2
    result=capsys.readouterr()
    assert json.loads(result.out)==dict(status='blocked',error='analysis launch blocked')
    assert result.err==''


def worker():
    return importlib.import_module('ops.pi.lab.container_runtime_worker')


def initial(setup):
    _,_,_,view,report=setup
    from ops.pi.analysis_execution import prepare_contract_slots
    slots=prepare_contract_slots({g:view for g in runtime.GROUPS},report,model='deepseek-flash',cwd=Path('/work/candidate'))
    return dict(slot_index=1,token='a'*64,slot=slots[1],view=view,report=report,deadline=time.time()+40)


def test_worker_uses_host_frozen_candidate_not_synthetic_default(setup):
    value=initial(setup)
    assert callable(getattr(worker(),'prepare_initial',None)), 'frozen worker input interface missing'
    parsed=worker().prepare_initial(value)
    assert parsed['slot']['slot_id']=='r1:recall.events:candidate'
    assert parsed['slot']==value['slot'] and parsed['model']=='deepseek-flash'


@pytest.mark.parametrize('what',['expired','later','drift','index','extra','oversize','token'])
def test_worker_rejects_drift_or_unbounded_initial_frame(setup,what):
    value=initial(setup)
    if what=='expired':value['deadline']=1
    elif what=='later':value['deadline']=time.time()+91
    elif what=='drift':value['slot']['request']['model']='foreign'
    elif what=='index':value['slot_index']=True
    elif what=='extra':value['provider_key']='PRIVATE'
    elif what=='oversize':value['report']['PRIVATE']='x'*524289
    else:value['token']='x\n'+'a'*62
    assert callable(getattr(worker(),'prepare_initial',None)), 'frozen worker input interface missing'
    with pytest.raises(ValueError):worker().prepare_initial(value)


CHILD=r'''
import json,sys,hashlib
from ops.pi.container_runtime import fixture
from ops.pi.relay_stream import receive_response
x=json.loads(sys.stdin.readline());s=x['slot'];token=x['token']
def request(body,key):
 print(json.dumps(dict(type='request',path='/v1/messages',headers=[['x-api-key',key],['X-Pi-Scope','local-trial-1'],['Content-Type','application/json']],body=json.dumps(body))),flush=True)
 status=[];chunks=[]
 receive_response(sys.stdin.buffer.readline,status.append,chunks.append)
 return dict(status=status[0],body=b''.join(chunks).decode())
assert request(s['request'],'wrong')['status']==403
assert request(s['request']|{'model':'foreign'},token)['status']==403
request(s['request'],token)
assert request(s['request'],token)['status']==403
answer=fixture().synthetic_answer()
session='\n'.join(json.dumps(row) for row in [dict(type='session',id='session-'+str(x['slot_index']),cwd='/work/candidate'),dict(type='message',message=dict(role='assistant',stopReason='stop',content=[dict(type='text',text=json.dumps(answer))]))])+'\n'
r={k:s[k] for k in ('slot_id','request_sha256','system_sha256','prompt_sha256','view_sha256','report_sha256')}
r.update(engine_status='done',contract_valid=True,analysis=answer,evidence=dict(session_valid=True,process_exited=True,clear_abort_acknowledged=True,returncode=0,unexpected_tool=False,verified_tool_calls=[],pending_tool_calls=[],session_sha256=hashlib.sha256(session.encode()).hexdigest()))
print(json.dumps(dict(type='result',result=r,session=session,runtime=dict(node='v24.22.0',pi='1.1.0',uid=65534,machine='aarch64',network_denied=True))),flush=True)
'''


def install_external_boundaries(monkeypatch,mode='known'):
    """Fake Docker only; real host gateway/budget, real stdio process and mock HTTP provider."""
    m=api();processes=[];calls=[];real_popen=subprocess.Popen
    class LocalDaemon(Daemon):
        def run(self,args,**kw):
            if args[3:4]==['inspect'] and processes and processes[-1].poll() is not None and CID in self.objects:
                self.objects[CID]['State'].update(Running=False,Pid=0,ExitCode=0)
            if args[3:4]==['rm'] and mode=='cleanup-failure':
                return subprocess.CompletedProcess(args,1,'','synthetic remove failure')
            return super().run(args,**kw)
    daemon=LocalDaemon()
    monkeypatch.setattr(m.subprocess,'run',daemon.run)
    def popen(command,**kw):
        if mode=='attach-failure':raise OSError('PRIVATE-attach-error')
        if mode=='timeout':script='import time;time.sleep(2)'
        elif mode=='duplicate-session':script=CHILD.replace("id='session-'+str(x['slot_index'])","id='same-session'")
        else:script=CHILD
        process=real_popen([sys.executable,'-u','-c',script],**kw);processes.append(process);return process
    monkeypatch.setattr(m.subprocess,'Popen',popen)
    @contextmanager
    def provider(policy,credentials):
        send,client=runtime.mock_transport(calls)
        try:
            if mode=='unknown':
                def send(body,timeout):
                    calls.append('attempt')
                    raise OSError('PRIVATE-upstream-error')
            yield send
        finally:client.close()
    monkeypatch.setattr(m,'_provider',provider)
    return processes,calls,daemon


def test_two_slots_use_real_atomic_ledger_and_private_gateway_once_each(setup,monkeypatch):
    c,ledger,_,_,_=setup
    processes,calls,daemon=install_external_boundaries(monkeypatch)
    result=api().launch(c,execute=True)
    assert result['status']=='completed' and result['execution_requested'] is True
    assert [s['status'] for s in result['slots']]==['DONE','DONE']+['NOT_RUN']*28
    assert len(processes)==2 and len(calls)==2 and not daemon.objects
    assert all(p.poll()==0 for p in processes)
    assert all(row['http_statuses']==[403,403,200,403] for row in result['cases'])
    with ledger.transaction() as db:
        rows=db.execute("SELECT * FROM operations WHERE kind='model-attempt'").fetchall()
        assert len(rows)==2 and all(r['status']=='done' for r in rows)
    assert result['production_ready'] is False and result['billing_verified'] is False
    encoded=json.dumps(result)
    assert 'sk-synthetic' not in encoded and 'r1:recall.events' in encoded and str(ledger.path) not in encoded
    with pytest.raises(LedgerBlocked):api().launch(c|{'root':str(Path(c['root']).with_name('retry'))},execute=True)
    assert len(calls)==2


@pytest.mark.parametrize('mode',['unknown','cleanup-failure','attach-failure','timeout'])
def test_uncertain_billing_or_container_failure_stops_before_next_slot(setup,monkeypatch,mode):
    c,ledger,_,_,_=setup
    processes,calls,daemon=install_external_boundaries(monkeypatch,mode)
    if mode=='timeout':c['deadline']=time.time()+.6
    result=api().launch(c,execute=True)
    assert result['status']=='blocked'
    assert len(processes)<=1 and len(calls)<=1
    assert result['slots'][1]['status']=='NOT_RUN'
    assert all(p.poll() is not None for p in processes)
    if mode=='cleanup-failure':assert any(not r.get('removed') for r in result['cleanup'])
    else:assert not daemon.objects
    if mode=='unknown':
        with ledger.transaction() as db:
            row=db.execute("SELECT * FROM operations WHERE kind='model-attempt'").fetchone()
            assert row['status']=='uncertain'
            assert json.loads(row['evidence'])['charged_microyuan']==json.loads(row['payload'])['reserved_microyuan']
    assert 'PRIVATE' not in json.dumps(result)


@pytest.mark.parametrize('kind',['missing','empty'])
def test_existing_ledger_mode_never_bootstraps_missing_or_empty_file(tmp_path,kind):
    path=tmp_path/'canonical.sqlite'
    if kind=='empty':path.touch()
    before=path.read_bytes() if path.exists() else None
    with pytest.raises(LedgerBlocked):Ledger(path,existing=True)
    assert (path.read_bytes() if path.exists() else None)==before


def test_duplicate_session_never_becomes_second_durable_done(setup,monkeypatch):
    c,ledger,_,_,_=setup
    processes,calls,daemon=install_external_boundaries(monkeypatch,'duplicate-session')
    result=api().launch(c,execute=True)
    assert result['status']=='blocked' and len(calls)==2
    assert [s['status'] for s in result['slots']]==['DONE','UNCERTAIN']+['NOT_RUN']*28
    assert all(p.poll()==0 for p in processes) and not daemon.objects


@pytest.mark.parametrize('cleanup_failure', ['none', 'remove', 'reconcile', 'slot'])
@pytest.mark.parametrize('kind,reason,observed', [('overflow', 'response_size_limit', 1048577), ('utf8', 'invalid_utf8', 1)])
def test_relay_failure_records_bounded_reason_without_body_or_refund(setup, monkeypatch, kind, reason, observed, cleanup_failure):
    import httpx
    from ops.pi.tests.test_model_gateway import transport
    c, ledger, _, _, _ = setup
    processes, calls, daemon = install_external_boundaries(monkeypatch, 'cleanup-failure' if cleanup_failure=='remove' else 'known')
    if cleanup_failure in ('reconcile', 'slot'):
        def fail(*args): raise OSError('PRIVATE-cleanup-error')
        monkeypatch.setattr(api().ProbeHost, 'reconcile' if cleanup_failure=='reconcile' else 'stop', fail)
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            if kind == 'utf8': yield b'\xff'
            else:
                # Keep 50000 valid pings across chunks, without making tiny-yield
                # scheduling exhaust the slot deadline before the aggregate cap.
                for remaining in range(50000, 0, -64):
                    yield b'data: {"type":"ping"}\n\n' * min(64, remaining)
    @contextmanager
    def provider(policy, credentials):
        def handler(req):
            calls.append('one')
            return httpx.Response(200, headers={'content-type':'text/event-stream'}, stream=Stream())
        yield transport(handler)
    monkeypatch.setattr(api(), '_provider', provider)
    result = api().launch(c, execute=True)
    assert result['status'] == 'blocked' and len(calls) == 1
    assert result['failure_detail'] == dict(slot_index=0, stage='relay', reason=reason, response_bytes=observed, http_status=200)
    assert result['slots'][0]['status'] == 'UNCERTAIN' and result['slots'][1]['status'] == 'NOT_RUN'
    assert result['failure_class'] == ('UnicodeDecodeError' if kind=='utf8' else 'ValueError')
    if cleanup_failure not in ('remove', 'slot'): assert not daemon.objects
    else: assert any(not row['removed'] for row in result['cleanup'])
    assert all(p.poll() is not None for p in processes)
    with ledger.transaction() as db:
        rows=db.execute("SELECT * FROM operations WHERE kind='model-attempt'").fetchall()
        assert len(rows)==1 and rows[0]['status']=='uncertain'
        assert json.loads(rows[0]['evidence'])['charged_microyuan']==json.loads(rows[0]['payload'])['reserved_microyuan']
    assert 'data:' not in json.dumps(result) and 'SECRET' not in json.dumps(result)


def test_invalid_result_has_distinct_stage_after_relay_success(setup, monkeypatch):
    c, ledger, _, _, _ = setup
    monkeypatch.setattr(sys.modules[__name__], 'CHILD', CHILD.replace('contract_valid=True', 'contract_valid=False'))
    processes, calls, daemon=install_external_boundaries(monkeypatch)
    result=api().launch(c, execute=True)
    assert result['status']=='blocked' and len(calls)==1
    assert result['failure_detail']['stage']=='result_verify'
    assert result['failure_detail']['reason']=='stage_failed'
    assert result['slots'][1]['status']=='NOT_RUN' and not daemon.objects
    assert all(p.poll()==0 for p in processes)
    with ledger.transaction() as db:
        rows=db.execute("SELECT * FROM operations WHERE kind='model-attempt'").fetchall()
        assert len(rows)==1 and rows[0]['status']=='done'
        assert json.loads(rows[0]['evidence'])['usage_known'] is True
        assert json.loads(rows[0]['evidence'])['charged_microyuan']==834


def test_unknown_usage_failure_is_distinct_from_valid_contract(setup, monkeypatch):
    import httpx
    from ops.pi.tests.test_model_gateway import transport
    c, ledger, _, _, _=setup
    processes, calls, daemon=install_external_boundaries(monkeypatch)
    @contextmanager
    def provider(policy, credentials):
        def handler(req):
            calls.append('one')
            return httpx.Response(200, stream=httpx.ByteStream(b'data: {"type":"ping"}\n\n'))
        yield transport(handler)
    monkeypatch.setattr(api(), '_provider', provider)
    result=api().launch(c,execute=True)
    assert result['status']=='blocked' and len(calls)==1
    assert result['failure_detail']['stage']=='usage_check'
    assert result['failure_detail']['reason']=='stage_failed'
    assert result['slots'][0]['status']=='UNCERTAIN' and result['slots'][1]['status']=='NOT_RUN'
    assert not daemon.objects and all(p.poll()==0 for p in processes)


def test_large_valid_sse_completes_without_confusing_wire_bytes_with_session(setup,monkeypatch):
    import httpx
    c,ledger,_,_,_=setup
    processes,calls,daemon=install_external_boundaries(monkeypatch)
    @contextmanager
    def provider(policy,credentials):
        send,client=runtime.mock_transport(calls)
        def padded(body,timeout):
            reply=send(body,timeout)
            class Stream(httpx.SyncByteStream):
                def __iter__(self):
                    for _ in range(4000):yield b'data: {"type":"ping"}\n\n'
                    yield from reply.iter_raw()
                def close(self):reply.close()
            return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())
        try:yield padded
        finally:client.close()
    monkeypatch.setattr(api(),'_provider',provider)
    result=api().launch(c,execute=True)
    assert result['status']=='completed' and len(calls)==2 and result['failure_detail'] is None
    assert [s['status'] for s in result['slots']]==['DONE','DONE']+['NOT_RUN']*28
    assert not daemon.objects and all(p.poll()==0 for p in processes)
    with ledger.transaction() as db:
        rows=db.execute("SELECT * FROM operations WHERE kind='model-attempt'").fetchall()
        assert len(rows)==2 and all(row['status']=='done' for row in rows)


@pytest.mark.parametrize('selected',[1,2])
def test_v2_selection_check_is_explicit_and_read_only(setup,monkeypatch,selected):
    c,ledger,_,_,_=setup
    before=ledger.path.read_bytes()
    def forbidden(*a,**k):pytest.fail('check produced a side effect')
    monkeypatch.setattr(api(),'Ledger',forbidden)
    monkeypatch.setattr(api(),'_provider',forbidden)
    monkeypatch.setattr(api().ProbeHost,'create',forbidden)
    result=api().launch(c|dict(schema='pi-analysis-launch-v2',selected_slots=selected))
    assert result['status']=='checked' and result['selected_slots']==selected
    assert result['planned_slots']==30 and not result['execution_requested']
    assert ledger.path.read_bytes()==before and not Path(c['root']).exists()


def test_v2_single_slot_completes_without_trying_second_despite_available_budget(setup,monkeypatch):
    c,ledger,_,_,_=setup
    processes,calls,daemon=install_external_boundaries(monkeypatch)
    result=api().launch(c|dict(schema='pi-analysis-launch-v2',selected_slots=1),execute=True)
    assert result['status']=='completed' and result['selected_slots']==1
    assert len(calls)==len(processes)==len(result['cases'])==len(result['cleanup'])==1
    assert [s['status'] for s in result['slots']]==['DONE']+['NOT_RUN']*29
    assert not daemon.objects and all(p.poll()==0 for p in processes)
    with ledger.transaction() as db:
        rows=db.execute("SELECT * FROM operations WHERE kind='model-attempt'").fetchall()
        assert len(rows)==1 and rows[0]['status']=='done'
        assert json.loads(rows[0]['payload'])['analysis_slot_index']==0


def test_v2_single_unknown_keeps_reservation_and_other_slots_not_run(setup,monkeypatch):
    c,ledger,_,_,_=setup
    processes,calls,daemon=install_external_boundaries(monkeypatch,'unknown')
    result=api().launch(c|dict(schema='pi-analysis-launch-v2',selected_slots=1),execute=True)
    assert result['status']=='blocked' and len(calls)==len(processes)==1
    assert [s['status'] for s in result['slots']]==['UNCERTAIN']+['NOT_RUN']*29
    assert not daemon.objects
    with ledger.transaction() as db:
        rows=db.execute("SELECT * FROM operations WHERE kind='model-attempt'").fetchall()
        assert len(rows)==1 and rows[0]['status']=='uncertain'
        assert json.loads(rows[0]['evidence'])['charged_microyuan']==json.loads(rows[0]['payload'])['reserved_microyuan']


@pytest.mark.parametrize('selection',[True,False,0,3,-1,1.0,'1',None,[],{}])
def test_v2_invalid_selection_cannot_reach_writers(setup,monkeypatch,selection):
    c,ledger,_,_,_=setup;before=ledger.path.read_bytes()
    def forbidden(*a,**k):pytest.fail('invalid selection reached side effect')
    monkeypatch.setattr(api(),'Ledger',forbidden)
    monkeypatch.setattr(api(),'_provider',forbidden)
    with pytest.raises(LedgerBlocked):api().launch(c|dict(schema='pi-analysis-launch-v2',selected_slots=selection),execute=True)
    assert ledger.path.read_bytes()==before and not Path(c['root']).exists()


def test_v2_missing_selection_and_v1_extra_selection_are_rejected(setup):
    c,ledger,_,_,_=setup;before=ledger.path.read_bytes()
    for change in (dict(schema='pi-analysis-launch-v2'),dict(selected_slots=1)):
        with pytest.raises(LedgerBlocked):api().launch(c|change,execute=True)
    assert ledger.path.read_bytes()==before and not Path(c['root']).exists()


def test_v2_config_hash_binds_selected_count(setup):
    c,_,_,_,_=setup
    one=api().launch(c|dict(schema='pi-analysis-launch-v2',selected_slots=1))
    two=api().launch(c|dict(schema='pi-analysis-launch-v2',selected_slots=2))
    assert one['config_sha256']!=two['config_sha256']


def test_v2_disabled_single_slot_cannot_execute(setup):
    c,ledger,p,_,_=setup
    p=replace(p,live_enabled=False)
    Path(c['policy_path']).write_text(json.dumps(asdict(p)));c['expected_policy_sha256']=_hash(asdict(p))
    e=json.loads(Path(c['evidence_path']).read_text());e['policy_sha256']=c['expected_policy_sha256']
    Path(c['evidence_path']).write_text(json.dumps(e));c['expected_evidence_sha256']=_hash(e)
    c|=dict(schema='pi-analysis-launch-v2',selected_slots=1)
    before=ledger.path.read_bytes()
    assert api().launch(c)['launch_ready'] is False
    with pytest.raises(LedgerBlocked):api().launch(c,execute=True)
    assert ledger.path.read_bytes()==before and not Path(c['root']).exists()
