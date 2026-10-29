"""Readonly stopped-development proof must agree with tools, candidate and fees."""
from dataclasses import asdict
from pathlib import Path
from hashlib import sha256
import importlib,json
import pytest
from ops.pi.audit import encoded
from ops.pi.development_inputs import file_hash,tree_hash,ledger_snapshot,read_json,OWNER
from ops.pi.ledger import Ledger
from ops.pi.contracts import Receipt
from ops.pi.plans import Plan
from ops.pi.policy import load_policy
from ops.pi.tools import ControlledTools,ToolCapability
from ops.pi.trial_runtime import verify_stopped_phase
from ops.pi.budget import reserve,settle
from ops.pi.tests.test_candidate_dossier import completed,config_file,write
from ops.pi.tests.test_tools import call,approve


def api():return importlib.import_module('ops.pi.development_evidence')


@pytest.fixture
def stopped(completed):
    qp,q,c,r,report=completed;root=Path(c['root']);candidate=root/'candidate';(candidate/'src/a.py').write_text('value = 1\n')
    plan=Plan(**{k:tuple(v) if isinstance(v,list) else v for k,v in read_json(c['plan_path']).items()});policy=load_policy(Path(c['policy_path']))
    cap=ToolCapability(c['run_id'],c['run_id'],candidate,c['source_sha256'],OWNER,1,'develop',plan.files,plan)
    identity=dict(owner=OWNER,generation=1,candidate_id=c['run_id'],base=c['source_sha256'])
    def unit(snapshot):return Receipt('development-check:one','done',dict(snapshot,verified=True,mode='ACTUAL',result='passed',source_sha256=tree_hash(candidate),tests=1,skipped=0))
    broker=ControlledTools(Ledger(root/'tools.sqlite'),policy,capability=cap,scope_token='synthetic-only',identity=lambda:identity,baseline=read_json(c['baseline_path']),metrics={},checks={'unit':unit})
    broker.ledger.path.chmod(0o600);review_id=c['run_id']+':review';broker.ledger.intent(review_id,'independent_review',dict(plan_hash=plan.plan_hash));broker.ledger.finish(Receipt(review_id,'done',read_json(c['review_path'])));broker.approve_plan(plan.plan_hash,review_id);records=[];calls=[]
    def invoke(name,args,call_id):
        actual=call(broker,cap,name,args,call_id);assert actual.status=='done';calls.append(call_id)
        records.extend([dict(type='message',message=dict(role='assistant',content=[dict(type='toolCall',id=call_id,name=name,arguments=args)])),dict(type='message',message=dict(role='toolResult',toolCallId=call_id,details=dict(receipt=asdict(actual))))])
    invoke('apply_patch',dict(plan_hash=plan.plan_hash,base=cap.base,candidate_hash=broker.candidate_hash(),edits=[dict(path='src/a.py',source_hash=file_hash(candidate/'src/a.py'),old='value = 1',new='value = 2')]),'patch')
    invoke('run_check',dict(check_id='unit',candidate_hash=broker.candidate_hash(),plan_hash=plan.plan_hash),'unit')
    invoke('candidate_status',{},'status')
    session=''.join(json.dumps(row)+'\n' for row in records);transcript='synthetic stopped transcript'
    receipt=Receipt('development-sdk','done',dict(engine='pi',phase='develop',owned_pid=123,returncode=0,session_valid=True,clear_abort_acknowledged=True,session_sha256=sha256(session.encode()).hexdigest(),verified_tool_calls=sorted(calls),protocol_failed=False,errors=[]))
    frame=dict(type='result',receipt=asdict(receipt),session=session,transcript=transcript,network_denied=True);write(root/'worker-frame-private.json',frame)
    proof=verify_stopped_phase(broker,receipt,session.encode(),transcript.encode(),stopped=dict(verified=True,mode='ACTUAL',pid=123,tree_empty=True,returncode=0),source_before=c['source_sha256'],source_after=tree_hash(candidate));assert proof['verified'] is True
    write(root/'phase-verification.json',proof);q['phase_sha256']=file_hash(root/'phase-verification.json')
    before=ledger_snapshot(c['ledger_path']);write(root/'ledger-before-private.json',before);ledger=Ledger(Path(c['ledger_path']),existing=True);posts=[]
    for _ in range(7):
        permit=reserve(ledger,'local-trial-1',dict(model=policy.model,max_tokens=policy.max_tokens,messages=[dict(role='user',content='synthetic')]),policy);settle(ledger,permit,dict(input_tokens=1,output_tokens=1,cache_read_input_tokens=0,cache_creation_input_tokens=0));posts.append(dict(status=200,attempt_id=permit.attempt_id))
    after=ledger_snapshot(c['ledger_path']);write(root/'ledger-after-private.json',after);added=[x for x in after['operations'] if x['kind']=='model-attempt']
    r.update(model_posts=posts,known_cost_microyuan=sum(json.loads(x['evidence'])['charged_microyuan'] for x in added));write(root/'result.json',r);q['result_sha256']=file_hash(root/'result.json');write(qp,q)
    return qp,q,c,r,frame


def test_reauthenticates_actual_tool_rows_and_original_fee_prefix_readonly(stopped):
    qp,q,c,r,frame=stopped;before={p:p.read_bytes() for p in qp.parent.rglob('*') if p.is_file()};proof=api().inspect(qp,file_hash(qp))
    assert proof['authority']=='completed_development_only' and proof['candidate_sha256']==r['candidate_sha256'] and proof['model_requests']==7
    assert proof['known_cost_microyuan']==r['known_cost_microyuan'] and [row['payload']['tool'] for row in proof['tools']]==['apply_patch','run_check','candidate_status']
    assert before=={p:p.read_bytes() for p in qp.parent.rglob('*') if p.is_file()}


@pytest.mark.parametrize('fault',['frame','protocol','session','transcript','foreign_tool','phase','cost','posts','after','before','unknown','tools','candidate'])
def test_declared_success_without_authenticated_development_never_authorizes_review(stopped,fault):
    qp,q,c,r,frame=stopped;root=Path(c['root'])
    if fault=='frame':frame['network_denied']=False
    elif fault=='protocol':frame['receipt']['evidence']['protocol_failed']=True
    elif fault=='session':frame['session']+='{}\n'
    elif fault=='transcript':frame['transcript']+='changed'
    elif fault=='foreign_tool':frame['session']=frame['session'].replace('value = 2','value = 3')
    elif fault=='phase':
        phase=read_json(root/'phase-verification.json');phase['final_check_operation_id']='foreign';write(root/'phase-verification.json',phase);q['phase_sha256']=file_hash(root/'phase-verification.json')
    elif fault=='cost':r['known_cost_microyuan']+=1
    elif fault=='posts':r['model_posts'][0]['attempt_id']='foreign'
    elif fault=='after':
        snap=read_json(root/'ledger-after-private.json');snap['events']=[];write(root/'ledger-after-private.json',snap)
    elif fault=='before':
        snap=read_json(root/'ledger-before-private.json');snap['sha256']='f'*64;write(root/'ledger-before-private.json',snap)
    elif fault=='unknown':
        ledger=Ledger(Path(c['ledger_path']),existing=True);permit=reserve(ledger,'local-trial-1',dict(max_tokens=1),load_policy(Path(c['policy_path'])));settle(ledger,permit,None)
    elif fault=='tools':(root/'tools.sqlite').rename(root/'tools-missing.sqlite')
    else:(root/'candidate/src/a.py').write_text('value = 999\n')
    write(root/'worker-frame-private.json',frame);write(root/'result.json',r);q['result_sha256']=file_hash(root/'result.json');write(qp,q)
    with pytest.raises((ValueError,OSError)):api().inspect(qp,file_hash(qp))
