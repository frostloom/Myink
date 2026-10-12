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


@pytest.mark.parametrize('flow',['valid','patch_after_check','final_recheck','wrong_source','lint_only'])
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
    check_id='lint' if flow=='lint_only' else 'unit'
    invoke('run_check',dict(check_id=check_id,candidate_hash=broker.candidate_hash(),plan_hash=cap.plan.plan_hash),'check-a')
    if flow in ('patch_after_check','final_recheck'):
        args=patch(broker,cap,old='value = 2',new='value = 3')
        args['edits'][0]['source_hash']=sha256(source.read_bytes()).hexdigest()
        invoke('apply_patch',args,'patch-b')
        if flow=='final_recheck':
            invoke('run_check',dict(check_id='unit',candidate_hash=broker.candidate_hash(),plan_hash=cap.plan.plan_hash),'check-b')
    session=b''.join(json.dumps(record).encode()+b'\n' for record in records)
    adapter=Receipt('adapter','done',dict(owned_pid=123,session_valid=True,clear_abort_acknowledged=True,
        session_sha256=sha256(session).hexdigest(),verified_tool_calls=sorted(call_ids)))
    stopped=dict(verified=True,mode='ACTUAL',pid=123,tree_empty=True,returncode=0)
    result=m.verify_stopped_phase(broker,adapter,session,b'transcript',stopped=stopped,
        source_before=before,source_after=sha256(source.read_bytes()).hexdigest())
    assert result['verified'] is (flow in ('valid','final_recheck'))
