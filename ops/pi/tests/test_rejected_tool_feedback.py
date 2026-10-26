"""Malformed patch attempts are feedback only when the current broker attests rejection."""
from copy import deepcopy
from dataclasses import asdict
import json
import pytest
from ops.pi.model_gateway import _validate
from ops.pi.tools import PHASE_TOOLS, tool_definitions
from ops.pi.tests.test_tools import setup,approve,patch,call
from ops.pi.tests.test_budget import policy,ledger,request as model_request


@pytest.fixture(params=('extra','missing','wrong_type'))
def rejected(tmp_path,policy,request):
    home=tmp_path/'broker';home.mkdir()
    broker,cap,root,identity=setup(home,policy);approve(broker,cap)
    args=patch(broker,cap)
    if request.param=='extra':args['edits'][0]['unexpected']=0
    elif request.param=='missing':del args['plan_hash']
    else:args['edits']={'unexpected':0}
    before=(root/'app/worker.py').read_bytes()
    receipt=call(broker,cap,'apply_patch',args,'bad-patch')
    assert receipt.status=='blocked' and receipt.evidence['reason'] in ('unsupported or missing tool fields','tool argument type mismatch')
    assert (root/'app/worker.py').read_bytes()==before
    raw=asdict(receipt)
    body=model_request()|dict(tools=tool_definitions('develop'),messages=[
        dict(role='assistant',content=[dict(type='tool_use',id='bad-patch',name='apply_patch',input=args)]),
        dict(role='user',content=[dict(type='tool_result',tool_use_id='bad-patch',content=[dict(type='text',text=json.dumps(raw))],is_error=True)])])
    return broker,cap,root,identity,args,raw,body


def test_actual_rejection_is_safe_history_then_corrected_patch_executes(rejected,policy):
    broker,cap,root,_,_,_,body=rejected
    original=deepcopy(body)
    _validate(body,policy,PHASE_TOOLS['develop'],blocked_tool_lookup=broker.lookup)
    assert body==original and (root/'app/worker.py').read_text()=='value = 1\n'
    result=call(broker,cap,'apply_patch',patch(broker,cap),'corrected-patch')
    assert result.status=='done' and (root/'app/worker.py').read_text()=='value = 2\n'


def test_no_verifier_or_stale_authority_cannot_admit_bad_history(rejected,policy):
    broker,_,_,identity,_,_,body=rejected
    with pytest.raises(ValueError):_validate(body,policy,PHASE_TOOLS['develop'])
    identity['generation']=2
    with pytest.raises(ValueError):_validate(body,policy,PHASE_TOOLS['develop'],blocked_tool_lookup=broker.lookup)


@pytest.mark.parametrize('fault',['fake_receipt','not_error','done','uncertain','reason','version_bool','duplicate_json','string_error','wrong_input','other_tool','multi_text','extra_field','wrong_call_id','binding'])
def test_rejection_history_requires_exact_typed_bound_receipt(rejected,policy,fault):
    broker,_,_,_,_,raw,body=rejected
    body=deepcopy(body);result=body['messages'][1]['content'][0]
    if fault=='fake_receipt':raw=deepcopy(raw);raw['operation_id']='foreign'
    if fault=='not_error':result['is_error']=False
    if fault in ('done','uncertain'):raw=deepcopy(raw);raw['status']=fault
    if fault=='reason':raw=deepcopy(raw);raw['evidence']['reason']='source hash or unique exact replacement mismatch'
    if fault=='version_bool':raw=deepcopy(raw);raw['schema_version']=True
    result['content'][0]['text']=json.dumps(raw)
    if fault=='duplicate_json':result['content'][0]['text']=json.dumps(raw)[:-1]+',"status":"blocked"}'
    if fault=='string_error':result['content']='SDK validation failed'
    if fault=='wrong_input':body['messages'][0]['content'][0]['input']['unexpected']=1
    if fault=='multi_text':result['content'].append(dict(type='text',text='extra'))
    if fault=='extra_field':raw=deepcopy(raw);raw['extra']=0;result['content'][0]['text']=json.dumps(raw)
    if fault=='wrong_call_id':body['messages'][0]['content'][0]['id']='wrong-call';result['tool_use_id']='wrong-call'
    if fault=='binding':raw=deepcopy(raw);raw['evidence']['binding']='0'*64;result['content'][0]['text']=json.dumps(raw)
    if fault=='other_tool':body['messages'][0]['content'][0]['name']='run_check'
    with pytest.raises(ValueError):_validate(body,policy,PHASE_TOOLS['develop'],blocked_tool_lookup=broker.lookup)


def test_unverified_bad_history_does_not_reserve_or_contact_provider(rejected,ledger,policy):
    from ops.pi.model_gateway import forward_messages
    from ops.pi.tests.test_model_gateway import transport,success
    from ops.pi.budget import totals
    body=rejected[-1];before=totals(ledger,'local-trial-1');calls=[]
    def send(*args):calls.append(args);return transport(success)(*args)
    result=forward_messages(body,'local-trial-1',ledger=ledger,policy=policy,transport=send,
                            tool_allowlist=PHASE_TOOLS['develop'],blocked_tool_lookup=lambda *a:False)
    assert result.status_code==400 and calls==[] and totals(ledger,'local-trial-1')==before


def test_verified_history_contacts_transport_unchanged(rejected,ledger,policy):
    from ops.pi.model_gateway import forward_messages
    from ops.pi.tests.test_model_gateway import transport,success
    body=rejected[-1];seen=[]
    def send(actual,timeout):
        seen.append(deepcopy(actual));return transport(success)(actual,timeout)
    result=forward_messages(body,'local-trial-1',ledger=ledger,policy=policy,transport=send,
                            tool_allowlist=PHASE_TOOLS['develop'],blocked_tool_lookup=rejected[0].lookup)
    assert result.status_code==200 and seen==[body]


def test_callback_fault_is_fail_closed(rejected,policy):
    def broken(*args):raise RuntimeError('unavailable verifier')
    with pytest.raises(ValueError):_validate(rejected[-1],policy,PHASE_TOOLS['develop'],blocked_tool_lookup=broken)


def test_truthy_verifier_does_not_replace_true_authentication(rejected,policy):
    with pytest.raises(ValueError):_validate(rejected[-1],policy,PHASE_TOOLS['develop'],blocked_tool_lookup=lambda *args:1)


def test_sdk_flattened_text_receipt_is_still_exact_host_authentication(rejected,policy):
    body=deepcopy(rejected[-1])
    body['messages'][1]['content'][0]['content']=json.dumps(rejected[-2])
    _validate(body,policy,PHASE_TOOLS['develop'],blocked_tool_lookup=rejected[0].lookup)
