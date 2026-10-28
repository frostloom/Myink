"""External review worker never waits on the manager's maintenance lock."""
from pathlib import Path
from threading import Event
import importlib,json,time
import httpx,pytest
from ops.pi.audit import digest
from ops.pi.development_inputs import file_hash,ledger_snapshot,read_json,authorization_hash
from ops.pi.tests.test_manager_handoff import handoff,completed,review_config,dossier_input,config_file,proof,write,NOW
from ops.pi.tests.test_diagnosis_launcher import fake_frame


def api():return importlib.import_module('ops.pi.manager_review_worker')


@pytest.fixture
def published(handoff):
    request,q,c,tc=handoff
    receipt=importlib.import_module('ops.pi.manager_handoff').publish(request,file_hash(request),clock=lambda:NOW)
    return request,q,c,tc,receipt


def select(published,proof,monkeypatch,*,abstain=False):
    request,q,c,tc,receipt=published;cycle=read_json(receipt['cycle_path']);sp=Path(cycle['selection_config_path']);sc=read_json(sp);selection=importlib.import_module('ops.pi.selection_launcher')
    class H:operation_id='selection-owned';owned={};pending={}
    class Owners:
        failed=False
        def __init__(self,*args):pass
        def add(self,h):return h
        def finish(self):return [dict(container_id='b'*64,removed=True)]
    monkeypatch.setattr(selection,'_host',lambda *args:H());monkeypatch.setattr(selection,'OwnedHosts',Owners)
    catalog=read_json(sc['catalog_path']);task=catalog[0]
    proposal=dict(task_id=task['task_id'],source_sha256=task['source_sha256'],evidence_sha256=task['evidence_sha256'],reason='Frozen reproduced existing behavior defect.')
    if abstain:proposal.update(task_id=None,source_sha256=None,evidence_sha256=None,reason='Insufficient behavior evidence; no task.')
    text=json.dumps(proposal)
    def exchange(h,config,initial,bridge,transport,limits,save,**kwargs):
        wire=dict(model=initial['model'],max_tokens=initial['max_tokens'],system=[dict(type='text',text=selection.wire_system(initial['system']))],messages=[dict(role='user',content=[dict(type='text',text=initial['prompt'])])],stream=True)
        bridge.route(dict(type='request',path='/v1/messages',headers=[['x-api-key',initial['model_token']],['x-pi-scope','local-trial-1']],body=json.dumps(wire)),transport)
        frame=fake_frame(proof[0],initial,text);save('worker-frame-private.json',frame);return frame
    monkeypatch.setattr(selection,'_exchange',exchange)
    def send(body,timeout):
        usage=dict(input_tokens=1,output_tokens=1,cache_read_input_tokens=0,cache_creation_input_tokens=0)
        events=[dict(type='message_start',message=dict(usage=usage)),dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text=text)),dict(type='message_delta',usage=dict(output_tokens=1)),dict(type='message_stop')]
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=httpx.ByteStream(''.join('data: '+json.dumps(v)+'\n\n' for v in events).encode()))
    selection.execute(sp,dict(mode='SIMULATED',source_sha256=sc['source_sha256'],tasks=catalog,input_hash='c'*64,deadline=time.monotonic()+90,cancel=Event()),transport=send,expected_config_sha256=file_hash(sp))
    return sp,sc,task


def tick(published):return api().tick(published[0],file_hash(published[0]),clock=lambda:NOW)


def test_pending_selection_is_readonly_and_reentrant(published):
    before=ledger_snapshot(published[3]['ledger_path'])
    assert tick(published)['status']=='waiting_selection'
    assert tick(published)['status']=='waiting_selection'
    assert ledger_snapshot(published[3]['ledger_path'])==before


@pytest.mark.parametrize('fault',['missing_receipt','request','manifest','cycle'])
def test_partial_or_changed_handoff_never_issues_permission(published,fault):
    request,q,c,tc,r=published
    path={'missing_receipt':Path(q['root'])/'receipt.json','request':request,'manifest':Path(r['manifest_path']),'cycle':Path(r['cycle_path'])}[fault]
    if fault=='missing_receipt':path.unlink()
    else:write(path,{})
    before=ledger_snapshot(tc['ledger_path'])
    with pytest.raises((ValueError,OSError,KeyError,TypeError)):tick(published)
    assert ledger_snapshot(tc['ledger_path'])==before and not (Path(r['lease_path']).parent/'binding').exists()


def test_verified_selection_waits_then_publishes_once_without_maintenance_lock(published,proof,monkeypatch):
    import fcntl
    sp,sc,task=select(published,proof,monkeypatch);request,q,c,tc,r=published;before=ledger_snapshot(tc['ledger_path'])
    lock=Path(q['root'])/'maintenance.lock';lock.touch(mode=0o600)
    with lock.open('rb') as held:
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert tick(published)['status']=='waiting_prepared'
        assert tick(published)['status']=='waiting_prepared'
        target=Path(q['root'])/'bundle/cycle-output/prepared'/task['task_id'];target.parent.parent.mkdir(mode=0o700);target.parent.mkdir(mode=0o700);target.mkdir(mode=0o700)
        current=dict(tc,ledger_sha256=before['sha256'],review_path=str(target/'review.json'),review_sha256='0'*64);cp=target/'config.json';write(cp,current)
        write(target/'review-request.json',dict(authorization_sha256=authorization_hash(current),plan_hash=digest(read_json(tc['plan_path'])),base=current['source_sha256'],candidate_id=current['run_id'],config_path=str(cp),task_id=task['task_id']))
        result=tick(published);assert result['status']=='published' and (target/'review.json').exists()
        # A completed publication can be read after the candidate started; no fresh prepare/republication.
        current['review_sha256']=file_hash(target/'review.json');write(cp,current)
        Path(tc['root']).mkdir(mode=0o700)
        again=tick(published);assert again['status']=='published' and again['cached'] is True
    assert ledger_snapshot(tc['ledger_path'])==before


def test_verified_abstention_is_terminal_without_development_permission(published,proof,monkeypatch):
    sp,sc,task=select(published,proof,monkeypatch,abstain=True);before=ledger_snapshot(sc['ledger_path'])
    assert tick(published)['status']=='no_action'
    assert tick(published)['status']=='no_action'
    assert not (Path(published[4]['lease_path']).parent/'binding/lease.json').exists() and ledger_snapshot(sc['ledger_path'])==before


def test_partial_binding_is_uncertain_and_not_replayed(published,proof,monkeypatch):
    select(published,proof,monkeypatch);binding=Path(published[4]['lease_path']).parent/'binding';binding.mkdir(mode=0o700);write(binding/'intent.json',{})
    assert tick(published)['status']=='uncertain'
    assert tick(published)['status']=='uncertain'
    assert not (binding/'lease.json').exists()


def prepared_config(published,task):
    request,q,c,tc,r=published;target=Path(q['root'])/'bundle/cycle-output/prepared'/task['task_id']
    target.parent.parent.mkdir(mode=0o700);target.parent.mkdir(mode=0o700);target.mkdir(mode=0o700)
    current=dict(tc,ledger_sha256=ledger_snapshot(tc['ledger_path'])['sha256'],review_path=str(target/'review.json'),review_sha256='0'*64);cp=target/'config.json';write(cp,current)
    write(target/'review-request.json',dict(authorization_sha256=authorization_hash(current),plan_hash=digest(read_json(tc['plan_path'])),base=current['source_sha256'],candidate_id=current['run_id'],config_path=str(cp),task_id=task['task_id']))
    return cp,current


def test_busy_original_fee_lock_waits_without_claim_or_fee(published,proof,monkeypatch):
    import fcntl
    sp,sc,task=select(published,proof,monkeypatch);before=ledger_snapshot(sc['ledger_path'])
    with Path(sc['ledger_path']).with_suffix('.tools.lock').open('rb') as held:
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert tick(published)['status']=='waiting_lock'
    assert not (Path(published[4]['lease_path']).parent/'binding').exists() and ledger_snapshot(sc['ledger_path'])==before
    assert tick(published)['status']=='waiting_prepared'


def test_partial_publication_receipt_remains_uncertain_without_replay(published,proof,monkeypatch):
    sp,sc,task=select(published,proof,monkeypatch);cp,current=prepared_config(published,task);before=ledger_snapshot(sc['ledger_path'])
    module=importlib.import_module('ops.pi.review_publisher');original=module._new
    def fail(path,value):
        if path.name=='receipt.json':raise OSError('synthetic receipt sync failure')
        return original(path,value)
    monkeypatch.setattr(module,'_new',fail)
    with pytest.raises(OSError):tick(published)
    assert (cp.parent/'review.json').exists()
    assert tick(published)['status']=='uncertain' and tick(published)['status']=='uncertain'
    assert ledger_snapshot(sc['ledger_path'])==before


@pytest.mark.parametrize('fault',['config','review','request','lease','catalog'])
def test_cached_publication_rejects_mutated_scope(published,proof,monkeypatch,fault):
    sp,sc,task=select(published,proof,monkeypatch);cp,current=prepared_config(published,task)
    assert tick(published)['status']=='published'
    if fault=='config':current['max_requests']+=1;write(cp,current)
    elif fault=='review':write(cp.parent/'review.json',{})
    elif fault=='request':write(cp.parent/'review-request.json',{})
    elif fault=='lease':write(Path(published[4]['lease_path']).parent/'binding/lease.json',{})
    else:write(Path(sc['catalog_path']),[])
    with pytest.raises((ValueError,OSError,KeyError,TypeError)):tick(published)


def test_abstention_primary_analysis_is_preserved_once_for_main(published,proof,monkeypatch):
    import importlib.util
    sp,sc,task=select(published,proof,monkeypatch,abstain=True)
    assert tick(published)['status']=='no_action' and tick(published)['status']=='no_action'
    spec=importlib.util.spec_from_file_location('worker_main_reader',Path('src/myink/pi_audit.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    events=module.AuditReader(Path(published[2]['export_root'])).events(sc['run_id'],limit=100)['items']
    primary=[e for e in events if e['details'].get('reference')=='host.selection_abstention.v1']
    result=read_json(Path(sc['root'])/'result.json')
    assert len(primary)==1 and primary[0]['details']['model_requests']==1 and primary[0]['details']['known_cost_microyuan']==result['known_cost_microyuan']
    assert primary[0]['status']=='no_change'
