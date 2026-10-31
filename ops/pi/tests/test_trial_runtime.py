"""Metering fence and phase gates without real transport or processes."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import pytest
from ops.pi.tests.test_budget import policy, ledger, request
from ops.pi.budget import reserve, settle, totals


def module():
    assert (Path(__file__).parents[1]/'trial_runtime.py').is_file(), 'fixed trial helpers missing'
    return importlib.import_module('ops.pi.trial_runtime')


def test_phase_fence_inherits_probes_and_survives_restart(ledger, policy):
    m = module()
    for _ in range(4): settle(ledger, reserve(ledger,'local-trial-1',request(),policy), None)
    m.ensure_phase_fence(ledger)
    sent = []
    send = m.phase_transport(ledger, 'plan', lambda body, timeout: sent.append(body) or object())
    for _ in range(11):
        reserve(ledger,'local-trial-1',request(),policy); send(request(),1)
    reserve(ledger,'local-trial-1',request(),policy)
    with pytest.raises(ValueError): send(request(),1)
    assert len(sent)==11 and totals(ledger,'local-trial-1')[0]==16
    assert m.ensure_phase_fence(ledger)['allocations']['analysis']==15


def test_phase_transport_denies_unreserved_and_replay(ledger):
    m=module(); m.ensure_phase_fence(ledger)
    send=m.phase_transport(ledger,'develop',lambda *_:pytest.fail('unreserved transport'))
    with pytest.raises(ValueError): send({},1)


def test_runtime_phase_requires_acceptance_before_engine(tmp_path):
    m=module()
    result=m.run_engine_phase(engine=None, phase='plan', prompt='fixed', session=None,
        plan_id='plan1', deadline=datetime.now(timezone.utc)+timedelta(seconds=30), acceptance=None)
    assert result.status=='blocked'


@pytest.mark.parametrize('flow',['valid','patch_after_check','final_recheck','wrong_source','lint_only',
    'missing_status','status_before_check','stale_status','wrong_status_identity','wrong_status_base','wrong_status_generation',
    'wrong_status_hash','published_status','missing_check_receipt'])
def test_fixround1_stopped_phase_requires_check_of_final_candidate(tmp_path,policy,flow):
    """Real broker rows/patches; runner and stopped-process evidence are simulated."""
    from hashlib import sha256
    import json
    from ops.pi.contracts import Receipt
    from ops.pi.tests.test_tools import setup,approve,call,patch
    m=module(); broker,cap,root,_=setup(tmp_path,policy); approve(broker,cap)
    source=root/'app/worker.py'; before=sha256(source.read_bytes()).hexdigest()
    records=[]; call_ids=[]
    def invoke(name,args,call_id):
        receipt=call(broker,cap,name,args,call_id)
        assert receipt.status=='done'
        call_ids.append(call_id)
        records.extend([{'type':'message','message':{'role':'assistant','content':[
            {'type':'toolCall','id':call_id,'name':name,'arguments':args}]}},
            {'type':'message','message':{'role':'toolResult','toolCallId':call_id,
                'details':{'receipt':asdict(receipt)}}}])
    def checker(snapshot):
        return Receipt('fixed-check:'+str(len(records)),'done',{**snapshot,'verified':True,'mode':'ACTUAL',
            'result':'passed','source_sha256':'0'*64 if flow=='wrong_source' else sha256(source.read_bytes()).hexdigest()})
    broker.checks={'unit':checker,'lint':checker}
    invoke('apply_patch',patch(broker,cap),'patch-a')
    if flow in ('status_before_check','stale_status'):
        invoke('candidate_status',{},'status-early')
    check_id='lint' if flow=='lint_only' else 'unit'
    invoke('run_check',dict(check_id=check_id,candidate_hash=broker.candidate_hash(),plan_hash=cap.plan.plan_hash),'check-a')
    if flow in ('patch_after_check','final_recheck','stale_status'):
        args=patch(broker,cap,old='value = 2',new='value = 3')
        args['edits'][0]['source_hash']=sha256(source.read_bytes()).hexdigest()
        invoke('apply_patch',args,'patch-b')
        if flow in ('final_recheck','stale_status'):
            invoke('run_check',dict(check_id='unit',candidate_hash=broker.candidate_hash(),plan_hash=cap.plan.plan_hash),'check-b')
    if flow not in ('missing_status','status_before_check','stale_status'):
        if flow in ('wrong_status_identity','wrong_status_base','wrong_status_generation','wrong_status_hash','published_status','missing_check_receipt'):
            from unittest.mock import patch as mock_patch
            original=broker._execute
            def wrong_identity(name,args):
                value=original(name,args)
                if name=='candidate_status':
                    key,bad={
                        'wrong_status_identity':('candidate_id','foreign-candidate'),
                        'wrong_status_base':('base','foreign-base'),
                        'wrong_status_generation':('generation',True),
                        'wrong_status_hash':('candidate_hash','0'*64),
                        'published_status':('published',True),
                        'missing_check_receipt':('receipts',[]),
                    }[flow]
                    value[key]=bad
                return value
            with mock_patch.object(broker,'_execute',side_effect=wrong_identity):
                invoke('candidate_status',{},'status-final')
        else:
            invoke('candidate_status',{},'status-final')
    session=b''.join(json.dumps(record).encode()+b'\n' for record in records)
    adapter=Receipt('adapter','done',dict(owned_pid=123,session_valid=True,clear_abort_acknowledged=True,
        session_sha256=sha256(session).hexdigest(),verified_tool_calls=sorted(call_ids)))
    stopped=dict(verified=True,mode='ACTUAL',pid=123,tree_empty=True,returncode=0)
    result=m.verify_stopped_phase(broker,adapter,session,b'transcript',stopped=stopped,
        source_before=before,source_after=sha256(source.read_bytes()).hexdigest())
    assert result['verified'] is (flow in ('valid','final_recheck'))


def _plan_records(broker, cap, proposals):
    """Build stopped-session records from actual authenticated broker calls."""
    import json
    from ops.pi.tests.test_tools import call
    records=[];receipts=[]
    for call_id, plan in proposals:
        args={'plan':json.loads(json.dumps(asdict(plan)))}
        receipt=call(broker,cap,'propose_plan',args,call_id)
        receipts.append(receipt)
        records.extend([{'message':{'role':'assistant','content':[
            {'type':'toolCall','id':call_id,'name':'propose_plan','arguments':args}]}},
            {'message':{'role':'toolResult','toolCallId':call_id,'details':{'receipt':asdict(receipt)}}}])
    return records,receipts


def _reconcile_plan(broker, records):
    import json
    from hashlib import sha256
    from ops.pi.contracts import Receipt
    session=b''.join(json.dumps(record).encode()+b'\n' for record in records)
    ids=sorted(block['id'] for record in records for block in record['message'].get('content',[]) if block.get('type')=='toolCall')
    adapter=Receipt('adapter','done',dict(owned_pid=123,session_valid=True,clear_abort_acknowledged=True,
        session_sha256=sha256(session).hexdigest(),verified_tool_calls=ids))
    return module().verify_stopped_phase(broker,adapter,session,b'transcript',
        stopped=dict(verified=True,mode='ACTUAL',pid=123,tree_empty=True,returncode=0),source_before='a'*64,source_after='a'*64)


def test_stopped_plan_selects_current_authenticated_proposal_preserving_history(tmp_path,policy):
    from dataclasses import replace
    from ops.pi.tests.test_tools import setup
    from ops.pi.tests.test_plans import candidate,baseline
    from ops.pi.tools import ControlledTools
    broker,cap,root,identity=setup(tmp_path,policy,phase='plan')
    _,old=_plan_records(broker,cap,[('historical-plan',candidate(hypothesis='historical proposal'))])
    assert old[0].status=='done'
    with broker.ledger.transaction() as c:
        old_rows=[list(row) for row in c.execute('SELECT * FROM operations ORDER BY operation_id')]
        old_events=[list(row) for row in c.execute('SELECT * FROM events ORDER BY id')]
    current=candidate(hypothesis='current proposal');new_cap=replace(cap,generation=2,plan=current)
    new_identity={**identity,'generation':2}
    current_broker=ControlledTools(broker.ledger,policy,capability=new_cap,scope_token='new-scoped-only',
        identity=lambda:new_identity,baseline=baseline(),metrics={})
    records,receipts=_plan_records(current_broker,new_cap,[('current-plan',current)])
    assert receipts[0].status=='done'
    result=_reconcile_plan(current_broker,records)
    assert result['verified'] is True
    assert result['proposed_plan']==dict(operation_id=receipts[0].operation_id,
        plan=receipts[0].evidence['plan'],plan_hash=current.plan_hash)
    with broker.ledger.transaction() as c:
        assert all(tuple(c.execute('SELECT * FROM operations WHERE operation_id=?',(row[0],)).fetchone())==tuple(row) for row in old_rows)
        assert [list(row) for row in c.execute('SELECT * FROM events ORDER BY id')][:len(old_events)]==old_events
        assert not c.execute("SELECT 1 FROM operations WHERE kind IN ('model-attempt','phase-admission','model-scope','tool_approval','independent_review')").fetchone()


@pytest.mark.parametrize('second_valid',[True,False])
def test_stopped_plan_rejects_multiple_current_proposals(tmp_path,policy,second_valid):
    from ops.pi.tests.test_tools import setup
    from ops.pi.tests.test_plans import candidate
    broker,cap,_,_=setup(tmp_path,policy,phase='plan')
    records,_=_plan_records(broker,cap,[('plan-a',candidate()),('plan-b',candidate(sample_floor=20 if second_valid else 19))])
    assert _reconcile_plan(broker,records)['verified'] is False


@pytest.mark.parametrize('rule_state',['blocked','failed','unverified','wrong_hash'])
def test_stopped_plan_rejects_done_tool_with_unsuccessful_rules(tmp_path,policy,rule_state):
    from unittest.mock import patch
    from ops.pi.contracts import Receipt
    from ops.pi.tests.test_tools import setup
    from ops.pi.tests.test_plans import candidate
    broker,cap,_,_=setup(tmp_path,policy,phase='plan');plan=candidate()
    if rule_state=='blocked':
        records,receipts=_plan_records(broker,cap,[('current-plan',candidate(sample_floor=19))])
    else:
        # Genuine broker/ledger receipt with a faulty deterministic-rule producer, not forged lookup.
        rule=Receipt('plan_rules:'+plan.plan_hash,'failed' if rule_state=='failed' else 'done',
            dict(plan_hash='0'*64 if rule_state=='wrong_hash' else plan.plan_hash,verified=rule_state!='unverified',source='deterministic_rules'))
        with patch('ops.pi.tools.validate_plan',return_value=rule):
            records,receipts=_plan_records(broker,cap,[('current-plan',plan)])
    assert receipts[0].status=='done'
    assert _reconcile_plan(broker,records)['verified'] is False


@pytest.mark.parametrize('tamper',['binding','operation_id','call_id','arguments','plan','plan_hash'])
def test_stopped_plan_rejects_tampered_current_call_or_receipt(tmp_path,policy,tamper):
    from ops.pi.tests.test_tools import setup
    from ops.pi.tests.test_plans import candidate
    broker,cap,_,_=setup(tmp_path,policy,phase='plan')
    records,_=_plan_records(broker,cap,[('current-plan',candidate())])
    actual=records[1]['message']['details']['receipt']
    if tamper=='binding':actual['evidence']['binding']='0'*64
    elif tamper=='operation_id':actual['operation_id']='tool:foreign:current-plan'
    elif tamper=='call_id':
        records[0]['message']['content'][0]['id']='foreign-call'
        records[1]['message']['toolCallId']='foreign-call'
    elif tamper=='arguments':records[0]['message']['content'][0]['arguments']['plan']['hypothesis']='changed argument'
    elif tamper=='plan':actual['evidence']['plan']['hypothesis']='changed receipt'
    else:actual['evidence']['plan_hash']='0'*64
    assert _reconcile_plan(broker,records)['verified'] is False


def test_stopped_plan_rejects_foreign_binding_and_history_only(tmp_path,policy):
    from dataclasses import replace
    from ops.pi.tests.test_tools import setup
    from ops.pi.tests.test_plans import candidate,baseline
    from ops.pi.tools import ControlledTools
    broker,cap,_,identity=setup(tmp_path,policy,phase='plan')
    records,_=_plan_records(broker,cap,[('historical-plan',candidate())])
    new_cap=replace(cap,generation=2);new_identity={**identity,'generation':2}
    current=ControlledTools(broker.ledger,policy,capability=new_cap,scope_token='current-scoped-only',
        identity=lambda:new_identity,baseline=baseline(),metrics={})
    assert _reconcile_plan(current,records)['verified'] is False
    assert _reconcile_plan(current,[])['verified'] is False
    assert broker.ledger.get('tool:'+cap.session_id+':historical-plan')['status']=='done'
