"""Offline controller/adapter integration; external Pi double is explicitly simulated."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pytest
from ops.pi.tests.test_budget import policy, ledger, request
from ops.pi.tests.test_tools import setup, call
from ops.pi.tests.test_pi_rpc import PROCESS, adapter
from ops.pi.pi_config import make_pi_config
from ops.pi.pi_rpc import PiAdapter
from ops.pi import tools


def definitions(phase='analysis'):
    assert hasattr(tools,'tool_definitions'), 'fixed tool schemas missing'
    return tools.tool_definitions(phase)


def test_gateway_requires_host_fixed_allowlist_and_complete_schema(ledger,policy):
    from ops.pi.model_gateway import forward_messages
    from ops.pi.tests.test_model_gateway import transport,success
    defs=definitions()
    body=request()|{'tools':defs}
    assert forward_messages(body,'local-trial-1',ledger=ledger,policy=policy,transport=transport(success)).status_code==400
    assert forward_messages(body,'local-trial-1',ledger=ledger,policy=policy,transport=transport(success),tool_allowlist=tuple(d['name'] for d in defs)).status_code==200
    changed=deepcopy(body);changed['tools'][0]['input_schema']['properties']['sql']={'type':'string'}
    assert forward_messages(changed,'local-trial-1',ledger=ledger,policy=policy,transport=transport(success),tool_allowlist=tuple(d['name'] for d in defs)).status_code==400


def test_gateway_tool_history_requires_paired_ids_and_correct_role(ledger,policy):
    from ops.pi.model_gateway import forward_messages
    from ops.pi.tests.test_model_gateway import transport,success
    defs=definitions(); grant=tuple(d['name'] for d in defs)
    body=request()|{'tools':defs,'messages':[
        {'role':'assistant','content':[{'type':'tool_use','id':'call-1','name':'candidate_status','input':{}}]},
        {'role':'user','content':[{'type':'tool_result','tool_use_id':'call-1','content':'done','is_error':False}]}]}
    assert forward_messages(body,'local-trial-1',ledger=ledger,policy=policy,transport=transport(success),tool_allowlist=grant).status_code==200
    for fault in ('id','role','field','unpaired'):
        bad=deepcopy(body)
        if fault=='id':bad['messages'][1]['content'][0]['tool_use_id']='unknown'
        elif fault=='role':bad['messages'][1]['role']='assistant'
        elif fault=='field':bad['messages'][0]['content'][0]['capability']={'approved':True}
        else:bad['messages'].pop()
        assert forward_messages(bad,'local-trial-1',ledger=ledger,policy=policy,transport=transport(success),tool_allowlist=grant).status_code==400


def test_config_pins_only_owned_extension_schema_and_guard(tmp_path):
    from types import SimpleNamespace
    root=Path(__file__).parents[1]
    extension=root/'extensions/controlled-tools.ts';schema=root/'extensions/tool-schemas.json';guard=root/'lab/pi-wire-guard.mjs'
    assert extension.is_file() and schema.is_file(),'controlled extension missing'
    profile={'phase':'analysis','extension_sha256':hashlib.sha256(extension.read_bytes()).hexdigest(),
             'schema_sha256':hashlib.sha256(schema.read_bytes()).hexdigest(),'guard_sha256':hashlib.sha256(guard.read_bytes()).hexdigest(),
             'broker_url':'http://127.0.0.1:8088','scope_token':'tool-only'}
    config=make_pi_config(tmp_path,{'base_url':'http://127.0.0.1:8088','scope_token':'model-only'},SimpleNamespace(model='mock-model',max_tokens=64),controlled_tools=profile)
    assert config['args'].count('-e')==1 and str(extension) in config['args']
    assert '--no-builtin-tools' in config['args'] and '--no-mcp' in config['args']
    assert config['env']['PI_TOOL_PHASE']=='analysis'
    controlled_model=config['models']['providers']['myink-budget']['models'][0]
    assert controlled_model.get('compat')=={'supportsEagerToolInputStreaming':False}
    assert controlled_model.get('headers')=={'anthropic-beta':''}
    legacy=make_pi_config(tmp_path,{'base_url':'http://127.0.0.1:8088','scope_token':'model-only'},SimpleNamespace(model='mock-model',max_tokens=64))
    legacy_model=legacy['models']['providers']['myink-budget']['models'][0]
    assert legacy_model=={'id':'mock-model','name':'mock-model','reasoning':False,
        'input':['text'],'contextWindow':1000000,'maxTokens':64}
    assert {k:v for k,v in controlled_model.items() if k not in ('compat','headers')}==legacy_model
    assert '--no-tools' in legacy['args'] and '-e' not in legacy['args']
    bad={**profile,'extension_sha256':'0'*64}
    with pytest.raises(ValueError):make_pi_config(tmp_path,{'base_url':'http://127.0.0.1:8088','scope_token':'model-only'},SimpleNamespace(model='mock-model',max_tokens=64),controlled_tools=bad)


@pytest.mark.parametrize('fault',['ok','unknown','mismatch','pending','nested','forged','session_omits_result'])
def test_adapter_correlates_rpc_tool_events_with_authoritative_receipts_and_session(tmp_path,policy,fault):
    broker,cap,_,_=setup(tmp_path,policy,phase='analysis')
    expected=asdict(call(broker,cap,'candidate_status',call_id='call-1'))
    engine,context,session=adapter(tmp_path,'ok')
    result={'content':[{'type':'text','text':json.dumps(expected,sort_keys=True,separators=(',',':'))}],'details':{'receipt':expected}}
    if fault=='forged':result['details']['receipt']={**expected,'status':'failed'}
    start={'type':'tool_execution_start','toolCallId':'call-1','toolName':'candidate_status','args':{}}
    end={'type':'tool_execution_end','toolCallId':'call-1','toolName':'candidate_status','result':result,'isError':False}
    if fault=='unknown':start['toolName']='bash';end['toolName']='bash'
    if fault=='mismatch':end['toolCallId']='other'
    if fault=='nested':start['parentToolCallId']='parent'
    events='        emit('+repr(start)+')\n'
    if fault!='pending':events+='        emit('+repr(end)+')\n'
    tc={'role':'assistant','content':[{'type':'toolCall','id':'call-1','name':'candidate_status','arguments':{}}],'stopReason':'toolUse'}
    tr={'role':'toolResult','toolCallId':'call-1','toolName':'candidate_status',**result,'isError':False}
    script=PROCESS.replace("        emit({'type':'agent_end','messages':[]})",events+"        emit({'type':'agent_end','messages':[]})")
    extra=[tc] if fault=='session_omits_result' else [tc,tr]
    prefix="+''.join(json.dumps({'type':'message','message':m})+'\\n' for m in "+repr(extra)+")"
    script=script.replace("+'\\n'+json.dumps({'type':'message','message':message})", "+'\\n'"+prefix+"+json.dumps({'type':'message','message':message})")
    (tmp_path/'process.py').write_text(script)
    engine=PiAdapter(engine.command,cwd=tmp_path,env={},config_hash='a'*64,
                     authorized_tools=('candidate_status',),tool_verifier=broker.lookup)
    receipt=engine.run_phase(phase='analysis',prompt='finite mock',context=context,session=session,
        deadline=datetime.now(timezone.utc)+timedelta(seconds=3),tools=['candidate_status'])
    assert (receipt.status=='done') is (fault=='ok')
    if fault=='ok':assert receipt.evidence['verified_tool_calls']==['call-1']


def test_http_broker_uses_distinct_scoped_token_and_never_model_capability(tmp_path,policy):
    from ops.pi.control import make_gateway_handler
    from ops.pi.tests.test_pi_gateway import Socket
    from ops.pi.budget import totals
    import io
    broker,cap,_,_=setup(tmp_path,policy,phase='analysis')
    body=json.dumps({'tool':'candidate_status','call_id':'http-1','arguments':{}}).encode()
    sock=Socket(b'x-api-key: scoped-only\r\nX-Pi-Scope: local-trial-1\r\n',body)
    sock.raw=io.BytesIO(sock.raw.getvalue().replace(b'/v1/messages',b'/v1/tools',1))
    make_gateway_handler(broker.ledger,policy,lambda *_:pytest.fail('tool reached model'),
        scope_token='model-token',tool_broker=broker)(sock,('127.0.0.1',1),object())
    assert b'200 OK' in sock.output and b'"status": "done"' in sock.output
    assert totals(broker.ledger,'local-trial-1')==(0,0)
    bad=Socket(b'x-api-key: model-token\r\nX-Pi-Scope: local-trial-1\r\n',b'{')
    bad.raw=io.BytesIO(bad.raw.getvalue().replace(b'/v1/messages',b'/v1/tools',1))
    make_gateway_handler(broker.ledger,policy,lambda *_:pytest.fail('tool reached model'),
        scope_token='model-token',tool_broker=broker)(bad,('127.0.0.1',1),object())
    assert b'403 Forbidden' in bad.output


def test_mock_stream_framing_passes_real_gateway_usage_parser(ledger,policy):
    import importlib.util
    import httpx
    from ops.pi.model_gateway import forward_messages
    from ops.pi.tests.test_model_gateway import transport
    path=Path(__file__).parents[1]/'lab/pi-tools-mock.py'
    spec=importlib.util.spec_from_file_location('controlled_mock',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    response=forward_messages(request()|{'stream':True},'local-trial-1',ledger=ledger,policy=policy,
        transport=transport(lambda _:httpx.Response(200,stream=m.SyntheticStream(1,'candidate_status',{}))))
    assert b'message_stop' in b''.join(response.body)
    assert ledger.get(response.attempt_id)['status']=='done'
