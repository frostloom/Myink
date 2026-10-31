"""Shared RPC cap retains an explicit authenticated completion path."""
from dataclasses import asdict
import json
from threading import Event
import pytest
from ops.pi.development_launcher import Limits,Bridge
from ops.pi.tools import ToolDenied
from ops.pi.tests.test_tools import setup,call
from ops.pi.tests.test_budget import policy


def limits():return Limits(18,28,60,Event(),completion_reserve=8)
def pair(l,name,args=None):
    l.before_tool(name,args or {});l.claim('tool')
    try:l.admit_tool(name,args or {})
    finally:l.claim('verify')


def test_warning_preserves_eight_rpc_for_real_completion_path():
    l=limits()
    for _ in range(9):pair(l,'read_source')
    with pytest.raises(ToolDenied,match='completion'):pair(l,'read_source')
    assert l.maximum['tool']-l.count['tool']==8
    for name,args in [('candidate_status',{}),('apply_patch',{}),('run_check',{'check_id':'unit'}),('candidate_status',{})]:pair(l,name,args)
    assert l.count['tool']==28
    with pytest.raises(ValueError):l.claim('verify')


def test_repeated_read_stops_before_spending_reserved_rpc():
    l=limits()
    for _ in range(9):pair(l,'read_source')
    with pytest.raises(ToolDenied):pair(l,'read_source')
    old=dict(l.count)
    with pytest.raises(ValueError,match='completion'):l.before_tool('read_source',{})
    assert l.count==old


@pytest.mark.parametrize('tool,args,remaining', [('apply_patch',{},4),('run_check',{'check_id':'unit'},2),('run_check',{'check_id':'lint'},8),('run_check',{'check_id':'contract'},8)])
def test_completion_only_cannot_consume_required_followups(tool,args,remaining):
    l=limits();l.count['tool']=28-remaining
    with pytest.raises(ValueError,match='completion'):l.before_tool(tool,args)


def test_odd_remaining_rpc_never_spends_reserve_on_warning():
    l=limits();l.count['tool']=19
    with pytest.raises(ValueError,match='completion'):l.before_tool('read_source',{})
    assert l.count['tool']==19


def test_small_total_rejected_before_execution():
    with pytest.raises(ValueError,match='completion'):Limits(18,10,60,Event(),completion_reserve=8)


def test_bridge_blocked_read_is_durable_authenticated_feedback(tmp_path,policy):
    l=limits();l.count['tool']=18
    b,c,_,_=setup(tmp_path,policy,admit_tool=l.admit_tool)
    bridge=Bridge({},policy,None,b,c,l,'model','scoped-only',lambda *a:None)
    args=dict(path='app/worker.py',start_line=1,end_line=1)
    frame=dict(type='request',path='/v1/tools',headers=[['x-pi-scope','local-trial-1'],['x-api-key','scoped-only']],body=json.dumps(dict(tool='read_source',call_id='last-read',arguments=args)))
    response=json.loads(bridge.route(frame,None)['body']);assert response['status']=='blocked' and 'completion' in response['evidence']['reason']
    verify=dict(type='request',path='/host/verify',headers=[],body=json.dumps(dict(call_id='last-read',name='read_source',args=args,receipt=response)))
    assert json.loads(bridge.route(verify,None)['body'])['verified'] is True
    assert l.count['tool']==20
    assert bridge.posts==[]


def test_old_limit_users_remain_shared_rpc_compatible():
    l=Limits(1,2,60,Event());l.claim('tool');l.claim('verify')
    with pytest.raises(ValueError):l.claim('tool')

from ops.pi.tests.test_development_inputs import config_file


def test_template_rejects_too_small_completion_budget(config_file):
    from ops.pi.development_inputs import prepare_template
    cp,c=config_file;c['max_tools']=11;cp.write_text(json.dumps(c))
    with pytest.raises(ValueError,match='completion RPC'):prepare_template(cp)


def test_launcher_wires_host_caps_and_shared_rpc_prompt(config_file,monkeypatch):
    from ops.pi import development_launcher as launcher
    cp,c=config_file
    class Host:
        owned={};pending={};operation_id='synthetic'
        def reconcile(self):pass
        def _daemon(self):pass
        def _call(self,*a):return type('Output',(),{'stdout':''})()
    monkeypatch.setattr(launcher,'_host',lambda *a:Host())
    captured=[]
    def stop(host,config,initial,bridge,transport,limits,write):
        captured.append(True)
        assert bridge.broker.source_read_limits==(4096,12288)
        assert limits.completion_reserve==8
        assert str(c['max_tools'])+' shared tool/verification RPCs' in initial['prompt']
        raise RuntimeError('synthetic stop before provider')
    monkeypatch.setattr(launcher,'_exchange',stop)
    result=launcher.execute(cp,transport=lambda *a:None)
    assert captured and result['failure_class']=='RuntimeError' and result['policy_restored'] and result['new_attempts']==0


def test_successful_same_call_replay_keeps_original_receipt_and_rpc_reserve(tmp_path,policy):
    l=limits();b,c,_,_=setup(tmp_path,policy,admit_tool=l.admit_tool)
    bridge=Bridge({},policy,None,b,c,l,'model','scoped-only',lambda *a:None)
    args=dict(path='app/worker.py',start_line=1,end_line=1)
    frame=dict(type='request',path='/v1/tools',headers=[['x-pi-scope','local-trial-1'],['x-api-key','scoped-only']],body=json.dumps(dict(tool='read_source',call_id='old',arguments=args)))
    old=json.loads(bridge.route(frame,None)['body']);assert old['status']=='done'
    l.count['tool']=18
    replay=json.loads(bridge.route(frame,None)['body']);assert replay==old
    verify=dict(type='request',path='/host/verify',headers=[],body=json.dumps(dict(call_id='old',name='read_source',args=args,receipt=replay)))
    assert json.loads(bridge.route(verify,None)['body'])['verified'] is True and l.count['tool']==20
    with pytest.raises(ValueError,match='completion'):bridge.route(frame,None)
    assert l.count['tool']==20


def test_malformed_completion_check_stops_with_bounded_error():
    l=limits();l.count['tool']=20
    with pytest.raises(ValueError,match='completion'):l.before_tool('run_check',[])
