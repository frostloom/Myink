"""Model requests and shared RPC must both leave a finite completion path."""
import json
from threading import Event
import pytest
from ops.pi.development_launcher import Limits, Bridge
from ops.pi.development_inputs import prepare_template
from ops.pi.tools import ToolDenied
from ops.pi.tests.test_completion_budget import pair
from ops.pi.tests.test_tools import setup
from ops.pi.tests.test_budget import policy
from ops.pi.tests.test_development_inputs import config_file


def limits(): return Limits(12,40,60,Event(),completion_reserve=8)

def test_model_warning_stops_read_with_plenty_of_rpc():
    l=limits();l.count.update(model=8,tool=2)
    with pytest.raises(ToolDenied,match='completion'): pair(l,'read_source')
    assert l.completion_only and l.count==dict(model=8,tool=4)
    before=dict(l.count)
    with pytest.raises(ValueError,match='completion'): l.before_tool('read_source',{})
    assert l.count==before

def test_warning_leaves_exact_model_sequence_for_patch_check_status_final():
    l=limits();l.count.update(model=8,tool=2)
    with pytest.raises(ToolDenied): pair(l,'read_source')
    for tool,args in [('apply_patch',{}),('run_check',{'check_id':'unit'}),('candidate_status',{})]:
        l.claim('model');pair(l,tool,args)
    l.claim('model')  # Final assistant response with no tool.
    assert l.count==dict(model=12,tool=10)
    with pytest.raises(ValueError,match='model request limit'): l.claim('model')

@pytest.mark.parametrize('tool,args,remaining',[
    ('apply_patch',{},2),('run_check',{'check_id':'unit'},1),('candidate_status',{},0),
    ('run_check',{'check_id':'lint'},4),('run_check',[],4),('unknown',{},4)])
def test_finishing_tool_cannot_spend_required_future_models(tool,args,remaining):
    l=limits();l.count['model']=12-remaining;before=dict(l.count)
    with pytest.raises(ValueError,match='completion'): l.before_tool(tool,args)
    assert l.count==before

@pytest.mark.parametrize('remaining',[0,1,2,3])
def test_late_read_stops_without_spending_warning_rpc(remaining):
    l=limits();l.count['model']=12-remaining;before=dict(l.count)
    with pytest.raises(ValueError,match='completion'): l.before_tool('read_source',{})
    assert l.count==before

def test_rpc_trigger_cannot_bypass_model_followup_requirements():
    l=limits();l.count.update(model=10,tool=30)
    with pytest.raises(ValueError,match='completion'): l.before_tool('apply_patch',{})
    assert l.count==dict(model=10,tool=30)

def test_model_warning_cannot_consume_odd_rpc_finishing_reserve():
    l=limits();l.count.update(model=8,tool=31)
    with pytest.raises(ValueError,match='completion'): l.before_tool('read_source',{})
    assert l.count==dict(model=8,tool=31)

def test_authenticated_request_warning_and_verify_spend_no_provider_call(tmp_path,policy):
    l=limits();l.count['model']=8
    b,c,_,_=setup(tmp_path,policy,admit_tool=l.admit_tool)
    bridge=Bridge({},policy,None,b,c,l,'model','scoped-only',lambda *a:None)
    args=dict(path='app/worker.py',start_line=1,end_line=1)
    frame=dict(type='request',path='/v1/tools',headers=[['x-pi-scope','local-trial-1'],['x-api-key','scoped-only']],body=json.dumps(dict(tool='read_source',call_id='model-warning',arguments=args)))
    response=json.loads(bridge.route(frame,None)['body'])
    assert response['status']=='blocked' and 'completion' in response['evidence']['reason']
    verify=dict(type='request',path='/host/verify',headers=[],body=json.dumps(dict(call_id='model-warning',name='read_source',args=args,receipt=response)))
    assert json.loads(bridge.route(verify,None)['body'])['verified'] is True
    assert l.count==dict(model=8,tool=2) and bridge.posts==[]
    with pytest.raises(ValueError,match='completion'): bridge.route(frame,None)
    assert l.count==dict(model=8,tool=2)

def test_cached_success_keeps_original_receipt_but_no_new_read_after_model_threshold(tmp_path,policy):
    l=limits();b,c,_,_=setup(tmp_path,policy,admit_tool=l.admit_tool)
    bridge=Bridge({},policy,None,b,c,l,'model','scoped-only',lambda *a:None)
    args=dict(path='app/worker.py',start_line=1,end_line=1)
    frame=dict(type='request',path='/v1/tools',headers=[['x-pi-scope','local-trial-1'],['x-api-key','scoped-only']],body=json.dumps(dict(tool='read_source',call_id='cached',arguments=args)))
    old=json.loads(bridge.route(frame,None)['body']);assert old['status']=='done'
    l.count['model']=8
    assert json.loads(bridge.route(frame,None)['body'])==old
    verify=dict(type='request',path='/host/verify',headers=[],body=json.dumps(dict(call_id='cached',name='read_source',args=args,receipt=old)))
    assert json.loads(bridge.route(verify,None)['body'])['verified'] is True
    before=dict(l.count)
    with pytest.raises(ValueError,match='completion'): bridge.route(frame,None)
    assert l.count==before and bridge.posts==[]

@pytest.mark.parametrize('requests',[1,2,3,4,5,6])
def test_small_active_model_budget_rejected_before_any_enable(config_file,requests):
    cp,c=config_file;c['max_requests']=requests;cp.write_text(json.dumps(c))
    ledger=__import__('pathlib').Path(c['ledger_path']);before=ledger.read_bytes()
    with pytest.raises(ValueError,match='completion model'): prepare_template(cp)
    assert ledger.read_bytes()==before
    with pytest.raises(ValueError,match='completion model'): Limits(requests,40,60,Event(),completion_reserve=8)

def test_seven_requests_support_initial_status_read_warning_and_finish():
    l=Limits(7,40,60,Event(),completion_reserve=8)
    l.claim('model');pair(l,'candidate_status')
    l.claim('model');pair(l,'read_source')
    l.claim('model')
    with pytest.raises(ToolDenied):pair(l,'read_source')
    for tool,args in [('apply_patch',{}),('run_check',{'check_id':'unit'}),('candidate_status',{})]:
        l.claim('model');pair(l,tool,args)
    l.claim('model');assert l.count['model']==7

def test_legacy_short_limits_and_hard_caps_are_unchanged():
    l=Limits(1,2,60,Event());l.claim('model');pair(l,'read_source')
    assert l.count==dict(model=1,tool=2)
    with pytest.raises(ValueError,match='model request limit'): l.claim('model')

def test_launcher_model_reserve_prompt_and_wiring(config_file,monkeypatch):
    from ops.pi import development_launcher as launcher
    cp,c=config_file
    class Host:
        owned={};pending={};operation_id='synthetic'
        def reconcile(self): pass
        def _daemon(self): pass
        def _call(self,*a): return type('Output',(),{'stdout':''})()
    monkeypatch.setattr(launcher,'_host',lambda *a:Host())
    captured=[]
    def stop(host,config,initial,bridge,transport,l,write):
        captured.append(True)
        assert 'four model requests remain' in initial['prompt']
        assert bridge.broker.source_read_limits==(4096,12288) and l.completion_reserve==8
        l.count['model']=l.maximum['model']-4
        with pytest.raises(ToolDenied): pair(l,'read_source')
        raise RuntimeError('synthetic stop before provider')
    monkeypatch.setattr(launcher,'_exchange',stop)
    result=launcher.execute(cp,transport=lambda *a:None)
    assert captured and result['new_attempts']==0 and result['policy_restored'] and result['failure_class']=='RuntimeError'
