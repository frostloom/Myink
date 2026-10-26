"""No-tool selection proof and forwarding boundaries; no paid requests."""
from copy import deepcopy
from dataclasses import asdict,replace
from threading import Event
import json,time

import pytest

from ops.pi import selection_launcher as selection
from ops.pi.contracts import Receipt
from ops.pi.development_inputs import digest
from ops.pi.development_launcher import Limits
from ops.pi.policy import load_policy
from pathlib import Path


@pytest.fixture
def proof():
    proposal=dict(task_id='names',source_sha256='a'*64,evidence_sha256='b'*64,reason='reproduced defect')
    text=json.dumps(proposal);prompt='frozen prompt';context_hash='c'*64;config_hash='d'*64
    user=dict(role='user',content=[dict(type='text',text=prompt)])
    assistant=dict(role='assistant',content=[dict(type='text',text=text)],stopReason='stop')
    system=dict(role='system',content='',sections=dict(preamble=selection.SYSTEM,cwd='<cwd>\n/work/candidate\n</cwd>'),timestamp=1)
    rows=[dict(type='session',id='fresh',cwd='/work/candidate'),*[dict(type='message',message=m) for m in (system,user,assistant)]]
    session=''.join(json.dumps(r)+'\n' for r in rows)
    rpc=[]
    for kind in ('prompt','clear_queue','abort'):
        command=dict(id=kind,type=kind)
        if kind=='prompt':command['message']=prompt
        rpc.append(dict(direction='in',record=command))
        reply=dict(id=kind,type='response',command=kind,success=True)
        if kind=='prompt':reply['data']=dict(disposition='started')
        if kind=='clear_queue':reply['data']=dict(steering=[],followUp=[])
        rpc.append(dict(direction='out',record=reply))
        if kind=='prompt':
            rpc.extend([*[dict(direction='out',record=dict(type='message_end',message=m)) for m in (system,user,assistant)],dict(direction='out',record=dict(type='agent_settled'))])
    transcript=''.join(json.dumps(r)+'\n' for r in rpc)
    from hashlib import sha256
    e=dict(engine='pi',config_hash=config_hash,plan_id=context_hash,experiment_id='local-trial-1',budget_scope_id='local-trial-1',
        accepted=True,disposition='started',settled=True,aborted=False,errors=False,protocol_failed=False,transcript_failed=False,
        unexpected_tool=False,session_valid=True,process_exited=True,clear_abort_acknowledged=True,
        verified_tool_calls=[],pending_tool_calls=[],length_continuations=0,returncode=0,owned_pid=21,text=text,
        session_sha256=sha256(session.encode()).hexdigest())
    frame=dict(type='result',receipt=dict(asdict(Receipt('phase','done',e)),schema_version=1),session=session,transcript=transcript,network_denied=True)
    initial=dict(prompt=prompt,system=selection.SYSTEM,config_hash=config_hash,context_hash=context_hash)
    request=dict(model='deepseek-flash',max_tokens=2048,system=[dict(type='text',text=selection.SYSTEM+'\n\n<cwd>\n/work/candidate\n</cwd>')],messages=[user],stream=True)
    return frame,initial,request,proposal


def test_proof_authenticates_session_and_rpc(proof):
    frame,initial,request,proposal=proof
    r=selection.verify_selection(frame,initial,request)
    assert r['verified'] and r['text']==json.dumps(proposal)


@pytest.mark.parametrize('kind',['prompt','assistant','clear_queue','abort','missing_settled','extra_prompt','session_header','tool','wrong_config','wrong_context','wrong_system','wrong_request'])
def test_inconsistent_proof_denied(proof,kind):
    f,i,q,_=deepcopy(proof)
    rpc=[json.loads(r) for r in f['transcript'].splitlines()]
    if kind=='prompt':rpc[0]['record']['message']='replaced prompt'
    if kind=='assistant':rpc[4]['record']['message']['content'][0]['text']='replaced answer'
    if kind in ('clear_queue','abort'):
        for r in rpc:
            if r['direction']=='out' and r['record'].get('command')==kind:r['record']['success']=False
    if kind=='missing_settled':rpc=[r for r in rpc if r['record'].get('type')!='agent_settled']
    if kind=='extra_prompt':rpc.append(deepcopy(rpc[0]))
    if kind=='session_header':f['session']=f['session']+f['session'].splitlines()[0]+'\n'
    if kind=='tool':rpc.append(dict(direction='out',record=dict(type='tool_execution_start',toolName='bash')))
    if kind=='wrong_config':f['receipt']['evidence']['config_hash']='e'*64
    if kind=='wrong_context':f['receipt']['evidence']['plan_id']='e'*64
    if kind=='wrong_system':q['system']='different system'
    if kind=='wrong_request':q['messages'][0]['content'][0]['text']='different prompt'
    f['transcript']=''.join(json.dumps(r)+'\n' for r in rpc)
    with pytest.raises(ValueError):selection.verify_selection(f,i,q)


def test_duplicate_json_proof_rejected(proof):
    f,i,q,_=proof;f['transcript']+='{"direction":"in","direction":"out","record":{}}\n'
    with pytest.raises(ValueError):selection.verify_selection(f,i,q)


def bridge(proof,monkeypatch):
    _,initial,request,_=proof
    policy=replace(load_policy(Path('ops/pi/policy.example.json')),live_enabled=True,input_bound_calibrated=True)
    calls=[]
    def forward(body,*a,**kwargs):calls.append(kwargs);raise RuntimeError('sentinel before HTTP')
    monkeypatch.setattr(selection,'forward_messages',forward)
    b=selection.NoToolBridge(policy,object(),Limits(1,0,10,Event()),'scoped',initial,lambda *a:None)
    frame=dict(type='request',path='/v1/messages',headers=[['x-api-key','scoped'],['x-pi-scope','local-trial-1']],body=json.dumps(request))
    return b,frame,calls


@pytest.mark.parametrize('route',['/v1/tools','/host/verify','/v1/unknown'])
def test_non_model_route_never_forwards(proof,monkeypatch,route):
    b,f,calls=bridge(proof,monkeypatch);f['path']=route
    with pytest.raises(ValueError):b.route(f,None)
    assert calls==[]


def test_bad_token_never_forwards(proof,monkeypatch):
    b,f,calls=bridge(proof,monkeypatch);f['headers'][0][1]='wrong'
    with pytest.raises(ValueError):b.route(f,None)
    assert calls==[]


def test_single_forward_and_strict_no_tools(proof,monkeypatch):
    b,f,calls=bridge(proof,monkeypatch)
    with pytest.raises(RuntimeError,match='sentinel'):b.route(f,None)
    with pytest.raises(ValueError):b.route(f,None)
    assert len(calls)==1 and calls[0]['tool_allowlist']==()


def test_request_drift_denied_before_forward(proof,monkeypatch):
    b,f,calls=bridge(proof,monkeypatch);body=json.loads(f['body']);body['messages'][0]['content'][0]['text']='changed';f['body']=json.dumps(body)
    with pytest.raises(ValueError):b.route(f,None)
    assert calls==[]


def test_invalid_worker_rejected_before_container_creation():
    from ops.pi.development_launcher import _exchange
    class Host:
        def create(self,*a,**k):pytest.fail('unexpected container')
    with pytest.raises(ValueError,match='worker'):
        _exchange(Host(),{},None,None,None,None,None,worker='../../elsewhere')


def test_phase_cancel_does_not_poison_parent_cycle():
    parent=Event();child=selection.PhaseCancel(parent);child.set()
    assert child.is_set() and not parent.is_set()
    other=selection.PhaseCancel(parent);parent.set();assert other.wait(.1)


from ops.pi.tests.test_development_inputs import config_file


@pytest.fixture
def selection_config(config_file,monkeypatch):
    from ops.pi.development_inputs import file_hash,ledger_snapshot,authorization_hash,read_json
    cp,old=config_file;root=cp.parent
    catalog=[dict(task_id='names',problem='existing defect',source_sha256=old['source_sha256'],evidence_sha256='b'*64,
        test_sha256=old['test_sha256'],test_cases=old['test_cases'],files=['src/a.py'],baseline=dict(tests=1,cases=old['test_cases'],
        failures=1,errors=0,skipped=0,failed_cases=old['test_cases'],error_cases=[]))]
    p=root/'catalog.json';p.write_text(json.dumps(catalog));p.chmod(0o600)
    c={k:old[k] for k in selection.FIELDS if k in old}
    c.update(schema='pi-maintenance-selection-v1',run_id='selection-test',root=str(root/'selection-output'),
        catalog_path=str(p),catalog_sha256=file_hash(p),deadline_seconds=60,review_path=str(root/'selection-review.json'),review_sha256='0'*64)
    review=dict(source='independent_review',verified=True,result='approved',reviewer='test-review',
        authorization_sha256=authorization_hash(c),plan_hash=digest(catalog),base=c['source_sha256'],
        candidate_id=c['run_id'],owner='local-development-controller',generation=1)
    p=Path(c['review_path']);p.write_text(json.dumps(review));p.chmod(0o600);c['review_sha256']=file_hash(p)
    cp=root/'selection-config.json';cp.write_text(json.dumps(c));cp.chmod(0o600)
    monkeypatch.setattr(selection,'verify_source',lambda *a:{})
    return cp,c,catalog


def test_selection_preflight_has_no_side_effects(selection_config):
    cp,c,_=selection_config
    before={p.name:p.read_bytes() for p in cp.parent.iterdir() if p.is_file()}
    assert selection.check(cp)['ready']
    assert before=={p.name:p.read_bytes() for p in cp.parent.iterdir() if p.is_file()}
    assert not Path(c['root']).exists() and not Path(c['ledger_path']).with_suffix('.tools.lock').exists()


@pytest.mark.parametrize('field,value',[('schema','other'),('deadline_seconds',121),('deadline_seconds',True),('ledger_sha256','e'*64),('policy_sha256','e'*64),('catalog_sha256','e'*64),('runtime_sha256','bad'),('source_sha256','e'*64),('review_sha256','e'*64)])
def test_selection_input_drift_denied(selection_config,field,value,monkeypatch):
    cp,c,_=selection_config;c[field]=value;cp.write_text(json.dumps(c))
    if field=='runtime_sha256':monkeypatch.setattr(selection,'verify_source',lambda *a:(_ for _ in ()).throw(ValueError('bad runtime')))
    with pytest.raises(ValueError):selection.check(cp)
    assert not Path(c['root']).exists()


def test_selection_failed_exchange_audits_without_spending(selection_config,monkeypatch):
    from ops.pi.development_inputs import ledger_snapshot
    cp,c,catalog=selection_config;before=ledger_snapshot(c['ledger_path']);cancel=Event()
    class Host:
        def __init__(self):self.owned={};self.pending={};self.operation_id='synthetic'
        def reconcile(self):pass
        def _daemon(self):pass
        def _call(self,*a):return type('Output',(),{'stdout':''})()
    monkeypatch.setattr(selection,'_host',lambda *a:Host())
    def fail(*args,**kwargs):raise RuntimeError('synthetic exit')
    monkeypatch.setattr(selection,'_exchange',fail)
    ctx=dict(source_sha256=c['source_sha256'],tasks=catalog,input_hash='c'*64,deadline=time.monotonic()+90,cancel=cancel)
    r=selection.execute(cp,ctx,transport=lambda *a:None)
    assert not r['verified'] and not r['execution_verified'] and r['new_attempts']==r['new_unknown']==0
    assert r['policy_restored'] and r['original_history_unchanged'] and not cancel.is_set()
    assert ledger_snapshot(c['ledger_path'])==before
    with pytest.raises(ValueError):selection.execute(cp,ctx,transport=lambda *a:None)


def test_duplicated_session_even_with_recomputed_digest_is_denied(proof):
    from hashlib import sha256
    f,i,q,_=proof;f['session']+=f['session'].splitlines()[0]+'\n'
    f['receipt']['evidence']['session_sha256']=sha256(f['session'].encode()).hexdigest()
    with pytest.raises(ValueError):selection.verify_selection(f,i,q)


def test_fake_success_acknowledgement_is_denied(proof):
    f,i,q,_=proof;rpc=[json.loads(r) for r in f['transcript'].splitlines()]
    for r in rpc:
        if r['record'].get('command')=='abort':r['record']['success']=1
    f['transcript']=''.join(json.dumps(r)+'\n' for r in rpc)
    with pytest.raises(ValueError):selection.verify_selection(f,i,q)


def test_selection_proposal_prompt_carries_stage_and_authorization():
    config=dict(run_id='a',root='/private/output',review_path='/private/review',review_sha256='x')
    prompt=selection.selection_prompt(config,[],'c'*64)
    assert 'c'*64 in prompt and selection.authorization_hash(config) in prompt


def test_pinned_pi_cwd_footer_is_exact_and_not_arbitrary(proof):
    _,initial,request,_=proof
    request['system']=[dict(type='text',text=initial['system']+'\n\n<cwd>\n/work/candidate\n</cwd>')]
    selection.request_matches(request,initial)
    for wrong in (initial['system'],initial['system']+'\n\n<cwd>\n/elsewhere\n</cwd>',request['system'][0]['text']+'\nextra'):
        request['system']=[dict(type='text',text=wrong)]
        with pytest.raises(ValueError,match='request drift'):selection.request_matches(request,initial)


@pytest.mark.parametrize('kind',['system_preamble','system_cwd','system_extra','missing_system','missing_user_end'])
def test_fixed_system_session_and_all_rpc_messages_are_bound(proof,kind):
    from hashlib import sha256
    f,i,q,_=proof;rows=[json.loads(r) for r in f['session'].splitlines()];rpc=[json.loads(r) for r in f['transcript'].splitlines()]
    if kind=='system_preamble':rows[1]['message']['sections']['preamble']='changed'
    if kind=='system_cwd':rows[1]['message']['sections']['cwd']='<cwd>/other</cwd>'
    if kind=='system_extra':rows[1]['message']['sections']['extra']='injected'
    if kind=='missing_system':rows.pop(1)
    if kind=='missing_user_end':rpc=[r for r in rpc if not (r['record'].get('type')=='message_end' and r['record']['message']['role']=='user')]
    f['session']=''.join(json.dumps(r)+'\n' for r in rows);f['receipt']['evidence']['session_sha256']=sha256(f['session'].encode()).hexdigest();f['transcript']=''.join(json.dumps(r)+'\n' for r in rpc)
    with pytest.raises(ValueError):selection.verify_selection(f,i,q)
