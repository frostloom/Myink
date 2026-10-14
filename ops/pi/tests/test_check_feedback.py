"""Failed-check feedback uses simulated host proofs and real broker durability."""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
import pytest
from ops.pi.contracts import Receipt
from ops.pi.tests.test_budget import policy
from ops.pi.tests.test_tools import setup, approve, call, patch
from ops.pi.tools import canonical
from ops.pi.trial_runtime import verify_stopped_phase


def host_failure(snapshot):
    return Receipt('capture-check-v2:'+'a'*64, 'blocked', {**snapshot,
        'verified':True, 'mode':'ACTUAL', 'result':'failed',
        'paired_complete':True, 'paired_objective_passed':False, 'severe_guard_veto':False,
        'report':{'verified':True,'passed':False,'guards_clear':True,
            'case_results':{'private-case':{'trace_fidelity':0,'redaction':1,'encoded_caps':1,'input_immutability':1}},
            'failures':['private-case:byte_fidelity'], 'severe':[],
            'legacy_security':{'passed':True,'failures':[],'severe':[],'aliases':{'secret':'oracle'}},
            'raw':'private-key oracle text'}})


def prepare(tmp_path, policy, callback=host_failure):
    broker,cap,root,identity=setup(tmp_path,policy,checks={'unit':callback},secret_values=('private-key',))
    approve(broker,cap)
    args=dict(check_id='unit',candidate_hash=broker.candidate_hash(),plan_hash=cap.plan.plan_hash)
    return broker,cap,args


def test_verified_failure_is_actionable_blocked_durable_and_replayed(tmp_path,policy):
    invoked=[]
    def checker(snapshot):
        invoked.append(snapshot)
        return host_failure(snapshot)
    broker,cap,args=prepare(tmp_path,policy,checker)
    receipt=call(broker,cap,'run_check',args)
    assert receipt.status=='blocked'
    feedback=receipt.evidence['check_feedback']
    assert feedback['metrics']['trace_fidelity']=={'pass':0,'fail':1}
    assert feedback['remediation_codes']==['byte_fidelity']
    assert feedback['result']=='failed' and feedback['verified'] is True
    assert receipt.evidence['check_operation_id']=='capture-check-v2:'+'a'*64
    text=canonical(asdict(receipt))
    assert all(word not in text for word in ('private-case','private-key','oracle','aliases','raw'))
    assert len(text.encode())<=16384
    assert broker.lookup('call-1','run_check',args,asdict(receipt))
    assert call(broker,cap,'run_check',deepcopy(args))==receipt
    assert len(invoked)==1
    assert broker.ledger.get(receipt.operation_id)['evidence']==receipt.evidence


@pytest.mark.parametrize('fault',['verified','mode','candidate_hash','plan_hash','base','candidate_id','generation','check_id','result','operation_id','infrastructure','oversize','metric','guard','incomplete'])
def test_untrusted_or_unbounded_failure_has_no_feedback(tmp_path,policy,fault):
    def checker(snapshot):
        r=host_failure(snapshot);e=deepcopy(r.evidence)
        if fault=='operation_id':return Receipt('private-key arbitrary text','blocked',e)
        if fault=='infrastructure':e['reason']='fixed_check_unverified'
        elif fault=='oversize':e['report']['raw']='x'*33000
        elif fault=='metric':e['report']['case_results']['private-case']['trace_fidelity']=True
        elif fault=='guard':e['report']['failures']=['private-case:private-key']
        elif fault=='incomplete':e['paired_complete']=False
        else:e[fault]=False if fault=='verified' else 'foreign'
        return Receipt(r.operation_id,r.status,e)
    broker,cap,args=prepare(tmp_path,policy,checker)
    receipt=call(broker,cap,'run_check',args)
    assert receipt.status=='blocked' and 'check_feedback' not in receipt.evidence
    assert 'private-key' not in canonical(asdict(receipt))


def test_failed_feedback_cannot_satisfy_final_phase_gate(tmp_path,policy):
    broker,cap,args=prepare(tmp_path,policy)
    records=[]
    for name,data,call_id in [('apply_patch',patch(broker,cap),'patch'),('run_check',None,'check')]:
        data=data or dict(check_id='unit',candidate_hash=broker.candidate_hash(),plan_hash=cap.plan.plan_hash)
        receipt=call(broker,cap,name,data,call_id)
        records.extend([{'message':{'role':'assistant','content':[{'type':'toolCall','id':call_id,'name':name,'arguments':data}]}},
                        {'message':{'role':'toolResult','toolCallId':call_id,'details':{'receipt':asdict(receipt)}}}])
    assert 'check_feedback' in receipt.evidence
    session=b''.join(json.dumps(r).encode()+b'\n' for r in records)
    adapter=Receipt('adapter','done',dict(owned_pid=123,session_valid=True,clear_abort_acknowledged=True,
        session_sha256=sha256(session).hexdigest(),verified_tool_calls=['check','patch']))
    result=verify_stopped_phase(broker,adapter,session,b'transcript',stopped=dict(verified=True,mode='ACTUAL',pid=123,tree_empty=True,returncode=0),
        source_before='a'*64,source_after='b'*64)
    assert result['verified'] is False


@pytest.mark.parametrize('fault',['evidence_type','typed_generation','empty_rows','nonfinite','missing_metrics','unknown_metrics'])
def test_malformed_authenticated_failure_is_denied(tmp_path,policy,fault):
    def checker(snapshot):
        r=host_failure(snapshot);e=deepcopy(r.evidence)
        if fault=='evidence_type':return Receipt(r.operation_id,'blocked',None)
        if fault=='typed_generation':e['generation']=True
        elif fault=='empty_rows':e['report']['case_results']={}
        elif fault=='nonfinite':e['report']['case_results']['private-case']['trace_fidelity']=float('nan')
        elif fault=='missing_metrics':del e['report']['case_results']['private-case']['redaction']
        elif fault=='unknown_metrics':e['report']['case_results']['private-case']['private-key']=1
        return Receipt(r.operation_id,r.status,e)
    broker,cap,args=prepare(tmp_path,policy,checker)
    receipt=call(broker,cap,'run_check',args)
    assert receipt.status=='blocked' and 'check_feedback' not in receipt.evidence


def test_source_changed_during_check_denies_feedback(tmp_path,policy):
    broker,cap,args=prepare(tmp_path,policy)
    def checker(snapshot):
        (cap.root/'app/worker.py').write_bytes(b'value = 99\n')
        return host_failure(snapshot)
    broker.checks['unit']=checker
    receipt=call(broker,cap,'run_check',args)
    assert receipt.status=='blocked' and 'check_feedback' not in receipt.evidence


def test_inconsistent_failure_counts_are_denied(tmp_path,policy):
    def checker(snapshot):
        r=host_failure(snapshot)
        r.evidence['report']['case_results']['private-case']['trace_fidelity']=1
        return r
    broker,cap,args=prepare(tmp_path,policy,checker)
    receipt=call(broker,cap,'run_check',args)
    assert receipt.status=='blocked' and 'check_feedback' not in receipt.evidence
