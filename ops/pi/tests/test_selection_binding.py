"""A derived lease must bind the gateway's actual selection UUID, never a guess."""
from pathlib import Path
from threading import Event
import importlib,json,time
import httpx,pytest
from ops.pi.audit import digest
from ops.pi.development_inputs import authorization_hash,file_hash,ledger_snapshot,read_json
from ops.pi.tests.test_review_lease import completed,write,NOW
from ops.pi.tests.test_sdk_review_launcher import review_config
from ops.pi.tests.test_review_dossier import dossier_input,config_file
from ops.pi.tests.test_selection_launcher import proof
from ops.pi.tests.test_diagnosis_launcher import fake_frame


@pytest.fixture
def selected(completed,proof,monkeypatch,request):
    pp,p,cp,c,tc=completed;lease=importlib.import_module('ops.pi.review_lease').create(pp,file_hash(pp),cp,file_hash(cp),clock=lambda:NOW)
    selection=importlib.import_module('ops.pi.selection_launcher');monkeypatch.setattr(selection,'verify_source',lambda *args:dict(machine='aarch64'))
    class H:operation_id='selection-owned';owned={};pending={}
    class Owners:
        failed=False
        def __init__(self,*args):pass
        def add(self,h):return h
        def finish(self):return [dict(container_id='b'*64,removed=True)]
    monkeypatch.setattr(selection,'_host',lambda *args:H());monkeypatch.setattr(selection,'OwnedHosts',Owners)
    catalog=read_json(c['outcome_path'])['catalog'];catalog_path=cp.parent/'selected-catalog.json';write(catalog_path,catalog)
    sc={k:tc[k] for k in selection.FIELDS if k in tc};sc.update(schema='pi-maintenance-selection-v1',prompt_version=2,run_id='actual-uuid-selection',root=str(cp.parent/'selection-output'),ledger_sha256=ledger_snapshot(c['ledger_path'])['sha256'],catalog_path=str(catalog_path),catalog_sha256=file_hash(catalog_path),deadline_seconds=60,review_path=str(cp.parent/'selection-review.json'),review_sha256='0'*64)
    sp=cp.parent/'selection-config.json';write(sp,sc)
    importlib.import_module('ops.pi.selection_review_issuer').issue(lease['lease_path'],lease['lease_sha256'],sp,file_hash(sp),clock=lambda:NOW)
    sc['review_sha256']=file_hash(sc['review_path']);write(sp,sc)
    task=catalog[0];proposal=dict(task_id=task['task_id'],source_sha256=task['source_sha256'],evidence_sha256=task['evidence_sha256'],reason='Frozen reproduced existing behavior defect.')
    if getattr(request,'param',None)=='abstain':proposal.update(task_id=None,source_sha256=None,evidence_sha256=None,reason='Insufficient behavior evidence; no task.')
    text=json.dumps(proposal)
    def exchange(h,config,initial,bridge,transport,limits,save,**kwargs):
        request=dict(model=initial['model'],max_tokens=initial['max_tokens'],system=[dict(type='text',text=selection.wire_system(initial['system']))],messages=[dict(role='user',content=[dict(type='text',text=initial['prompt'])])],stream=True)
        bridge.route(dict(type='request',path='/v1/messages',headers=[['x-api-key',initial['model_token']],['x-pi-scope','local-trial-1']],body=json.dumps(request)),transport)
        frame=fake_frame(proof[0],initial,text);save('worker-frame-private.json',frame);return frame
    monkeypatch.setattr(selection,'_exchange',exchange)
    def send(body,timeout):
        usage=dict(input_tokens=1,output_tokens=1,cache_read_input_tokens=0,cache_creation_input_tokens=0)
        events=[dict(type='message_start',message=dict(usage=usage)),dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text=text)),dict(type='message_delta',usage=dict(output_tokens=1)),dict(type='message_stop')]
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=httpx.ByteStream(''.join('data: '+json.dumps(v)+'\n\n' for v in events).encode()))
    context=dict(mode='SIMULATED',source_sha256=sc['source_sha256'],tasks=catalog,input_hash='c'*64,deadline=time.monotonic()+90,cancel=Event())
    result=selection.execute(sp,context,transport=send,expected_config_sha256=file_hash(sp));assert result['verified'] is True
    return pp,p,cp,c,tc,lease,sp,sc,result


def api():return importlib.import_module('ops.pi.selection_binding')


def test_real_gateway_uuid_binds_derived_immutable_lease_and_publishes(selected):
    pp,p,cp,c,tc,parent,sp,sc,result=selected;before=ledger_snapshot(c['ledger_path']);original=Path(parent['lease_path']).read_bytes()
    assert read_json(parent['lease_path'])['scope']['allowed_fee_operation_ids']==[]
    bound=api().bind(parent['lease_path'],parent['lease_sha256'],sp,file_hash(sp),clock=lambda:NOW)
    value=read_json(bound['lease_path']);assert value['scope']['allowed_fee_operation_ids']==[result['model_posts'][0]['attempt_id']]
    assert Path(parent['lease_path']).read_bytes()==original and ledger_snapshot(c['ledger_path'])==before
    target=Path(p['prepared_parent'])/'value-fix';target.mkdir(mode=0o700);current=dict(tc,ledger_sha256=before['sha256'],review_path=str(target/'review.json'),review_sha256='0'*64);config=target/'config.json';write(config,current)
    write(target/'review-request.json',dict(authorization_sha256=authorization_hash(current),plan_hash=digest(read_json(tc['plan_path'])),base=current['source_sha256'],candidate_id=current['run_id'],config_path=str(config),task_id='value-fix'))
    published=importlib.import_module('ops.pi.review_publisher').publish(bound['lease_path'],bound['lease_sha256'],config,clock=lambda:NOW)
    assert published['status']=='published' and ledger_snapshot(c['ledger_path'])==before
    with pytest.raises(ValueError):api().bind(parent['lease_path'],parent['lease_sha256'],sp,file_hash(sp),clock=lambda:NOW)


@pytest.mark.parametrize('fault',['initial','manifest','mode','frame','verification','result','before','after','request','selected_task','cleanup','pin'])
def test_unverified_selection_never_binds_or_mutates_fee(selected,fault):
    pp,p,cp,c,tc,parent,sp,sc,result=selected;root=Path(sc['root']);pin=file_hash(sp)
    if fault=='pin':pin='f'*64
    else:
        names={'initial':'initial-private.json','manifest':'manifest-private.json','mode':'manifest-private.json','frame':'worker-frame-private.json','verification':'verification.json','result':'result.json','before':'ledger-before-private.json','after':'ledger-after-private.json','request':'request-private.json','selected_task':'result.json','cleanup':'result.json'}
        path=root/names[fault];value=read_json(path)
        if fault=='mode':value['mode']='ACTUAL'
        elif fault=='selected_task':value['proposal']['task_id']='other'
        elif fault=='cleanup':value['cleanup'][0]['removed']=False
        else:value={}
        write(path,value)
    before=ledger_snapshot(c['ledger_path'])
    with pytest.raises((ValueError,OSError,KeyError,TypeError)):api().bind(parent['lease_path'],parent['lease_sha256'],sp,pin,clock=lambda:NOW)
    assert not (Path(parent['lease_path']).parent/'binding').exists() and ledger_snapshot(c['ledger_path'])==before


def test_selection_binding_exposes_verified_cost_and_stage_to_main_reader(selected):
    import importlib.util
    pp,p,cp,c,tc,parent,sp,sc,result=selected
    bound=api().bind(parent['lease_path'],parent['lease_sha256'],sp,file_hash(sp),clock=lambda:NOW)
    receipt=read_json(Path(bound['lease_path']).parent/'receipt.json')
    assert receipt['status']=='bound' and receipt['lease_sha256']==bound['lease_sha256']
    spec=importlib.util.spec_from_file_location('binding_main_reader',Path('src/myink/pi_audit.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    events=module.AuditReader(Path(c['export_root'])).events(sc['run_id'],limit=100)['items']
    event=next(e for e in events if e['details'].get('reference')=='host.selection_binding.v1')
    assert event['kind']=='analysis' and event['details']['model_requests']==1 and event['details']['known_cost_microyuan']==result['known_cost_microyuan']
    assert {e['kind'] for e in event['evidence']}=={'selection_verification','original_review_lease','bound_development_lease'}


def test_bound_selection_drives_original_adapter_and_file_review(selected,monkeypatch):
    from threading import Thread
    from ops.pi.maintenance_adapters import FrozenDevelopmentAdapter,FileReview
    pp,p,cp,c,tc,parent,sp,sc,result=selected
    bound=api().bind(parent['lease_path'],parent['lease_sha256'],sp,file_hash(sp),clock=lambda:NOW)
    refreshed=dict(tc,ledger_sha256=ledger_snapshot(c['ledger_path'])['sha256']);template=cp.parent/'post-selection-template.json';write(template,refreshed)
    task=read_json(sc['catalog_path'])[0];captured=[];failure=[]
    monkeypatch.setattr('ops.pi.maintenance_adapters.verify_source',lambda *args:dict(machine='aarch64'))
    def publisher():
        try:
            config=Path(p['prepared_parent'])/task['task_id']/'config.json';until=time.monotonic()+8
            while not (config.parent/'review-request.json').exists():
                if time.monotonic()>=until:raise TimeoutError('no prepared request')
                time.sleep(.01)
            captured.append(importlib.import_module('ops.pi.review_publisher').publish(bound['lease_path'],bound['lease_sha256'],config,clock=lambda:NOW))
        except Exception as error:failure.append(error)
    thread=Thread(target=publisher);thread.start()
    adapter=FrozenDevelopmentAdapter({task['task_id']:dict(path=str(template),sha256=file_hash(template))},p['prepared_parent'],c['ledger_path'],FileReview(10))
    receipt=adapter(dict(cancel=Event(),deadline=time.monotonic()+1800,task=task,mode='SIMULATED',input_hash='d'*64,operation_id='bound-freeze'))
    thread.join(timeout=10)
    assert not thread.is_alive() and not failure and receipt.status=='done' and captured[0]['status']=='published'
    from ops.pi.development_inputs import prepare
    assert prepare(receipt.evidence['config_path'])[0]['ledger_sha256']==ledger_snapshot(c['ledger_path'])['sha256']


def test_partial_binding_receipt_cannot_authorize_or_replay(selected,monkeypatch):
    pp,p,cp,c,tc,parent,sp,sc,result=selected;module=api();original=module._new
    def sync_failure(path,value):
        if path.name=='receipt.json':raise OSError('synthetic binding receipt sync failure')
        return original(path,value)
    monkeypatch.setattr(module,'_new',sync_failure);before=ledger_snapshot(c['ledger_path'])
    with pytest.raises(OSError):module.bind(parent['lease_path'],parent['lease_sha256'],sp,file_hash(sp),clock=lambda:NOW)
    derived=Path(parent['lease_path']).parent/'binding/lease.json';assert derived.exists()
    with pytest.raises(ValueError):module.bind(parent['lease_path'],parent['lease_sha256'],sp,file_hash(sp),clock=lambda:NOW)
    config=Path(p['prepared_parent'])/'value-fix/config.json'
    with pytest.raises(OSError):importlib.import_module('ops.pi.review_publisher').publish(derived,file_hash(derived),config,clock=lambda:NOW)
    assert ledger_snapshot(c['ledger_path'])==before and not (config.parent/'review.json').exists()


@pytest.mark.parametrize('selected',['abstain'],indirect=True)
def test_verified_abstention_keeps_paid_receipt_without_development_lease(selected):
    pp,p,cp,c,tc,parent,sp,sc,result=selected;before=ledger_snapshot(c['ledger_path'])
    assert result['verified'] is True and result['proposal']['task_id'] is None and result['new_attempts']==1
    with pytest.raises(ValueError,match='abstained'):api().bind(parent['lease_path'],parent['lease_sha256'],sp,file_hash(sp),clock=lambda:NOW)
    assert ledger_snapshot(c['ledger_path'])==before and not (Path(parent['lease_path']).parent/'binding').exists()
