from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys
import pytest
from ops.pi.engine import AdministratorContext, EngineSession
from ops.pi.pi_rpc import PiAdapter


# The double is the external JSONL process, never the adapter under test.
PROCESS = r"""
import json,sys,time
mode=sys.argv[1]
from pathlib import Path
session_file=Path(sys.argv[sys.argv.index('--session')+1])
if mode=='startupfail':
    sys.stderr.write('Error: rejected secret-scope configuration\n'); sys.stderr.flush(); raise SystemExit(1)
def emit(item):
    sys.stdout.buffer.write(json.dumps(item, ensure_ascii=False).encode()+b'\n'); sys.stdout.buffer.flush()
for line in sys.stdin.buffer:
    c=json.loads(line)
    if c['type']=='prompt':
        emit({'type':'response','id':c['id'],'command':'prompt','success':True,'data':{'disposition':'handled' if mode=='handled' else 'started'}})
        if mode=='handled': continue
        emit({'type':'agent_end','messages':[]})
        if mode=='unsettled': continue
        message={'role':'assistant','content':[{'type':'text','text':'a\u2028b\u2029c'}],'stopReason':'error' if mode=='error' else 'stop'}
        if mode=='error': message['errorMessage']='provider rejected'
        emit({'type':'message_end','message':message})
        if mode!='stale': session_file.write_text('bogus' if mode=='invalidartifact' else json.dumps({'type':'session','id':'trial','cwd':str(Path.cwd())})+'\n'+json.dumps({'type':'message','message':message})+'\n')
        emit({'type':'agent_settled','aborted':False})
    elif c['type']=='clear_queue':
        emit({'type':'response','id':c['id'],'command':'clear_queue','success':True,'data':{'steering':[],'followUp':[]}})
    elif c['type']=='abort':
        emit({'type':'response','id':c['id'],'command':'abort','success':True})
        if mode=='malformeddrain': sys.stdout.buffer.write(b'not-json\n'); sys.stdout.buffer.flush()
"""


def adapter(tmp_path, mode):
    script=tmp_path/'process.py'; script.write_text(PROCESS)
    session_file=tmp_path/'session.jsonl'
    context=AdministratorContext(experiment_id='local-trial-1', plan_id='plan-1', budget_scope_id='local-trial-1', evidence_summary='read-only local preview')
    session=EngineSession(engine='pi', config_hash='a'*64, phase='analysis', session_path=session_file, resume=False)
    engine=PiAdapter([sys.executable,str(script),mode], cwd=tmp_path, env={}, config_hash='a'*64)
    return engine, context, session


def run(engine, context, session):
    return engine.run_phase(phase='analysis',prompt='hello',context=context,session=session,deadline=datetime.now(timezone.utc)+timedelta(seconds=0.6),tools=[])


def test_prompt_acceptance_and_agent_end_do_not_complete(tmp_path):
    engine,context,session=adapter(tmp_path,'unsettled')
    receipt=run(engine,context,session)
    assert receipt.status=='pending'
    assert receipt.evidence['accepted'] is True
    assert receipt.evidence['settled'] is False
    assert receipt.evidence['process_exited'] is True


def test_error_message_with_exit_zero_fails(tmp_path):
    engine,context,session=adapter(tmp_path,'error')
    receipt=run(engine,context,session)
    assert receipt.status=='failed'
    assert receipt.evidence['returncode']==0


def test_handled_prompt_does_not_wait_for_settled(tmp_path):
    engine,context,session=adapter(tmp_path,'handled')
    receipt=run(engine,context,session)
    assert receipt.status=='pending'
    assert receipt.evidence['disposition']=='handled'
    assert receipt.evidence['settled'] is False


def test_unicode_separator_is_not_record_boundary_and_stop_is_ordered(tmp_path):
    engine,context,session=adapter(tmp_path,'ok')
    receipt=run(engine,context,session)
    assert receipt.status=='done'
    assert receipt.evidence['text']=='a\u2028b\u2029c'
    commands=[r for r in map(json.loads,filter(None,Path(receipt.evidence['transcript_path']).read_text().split('\n'))) if isinstance(r,dict) and r.get('direction')=='in']
    assert [r['record']['type'] for r in commands][-2:]==['clear_queue','abort']
    assert len({r['record']['id'] for r in commands})==len(commands)


def test_foreign_or_unverified_resume_is_refused_before_spawn(tmp_path):
    engine,context,session=adapter(tmp_path,'ok')
    foreign=EngineSession(engine='other', config_hash='a'*64,phase='analysis',session_path=session.session_path,resume=True)
    with pytest.raises(ValueError): run(engine,context,foreign)
    assert not list(tmp_path.glob('*.rpc.jsonl'))


def test_nonempty_invalid_session_is_not_completion(tmp_path):
    engine,context,session=adapter(tmp_path,'invalidartifact')
    assert run(engine,context,session).status != 'done'


def test_transcript_write_failure_still_exits_owned_process_and_releases_lock(tmp_path, monkeypatch):
    engine,context,session=adapter(tmp_path,'unsettled')
    original=Path.open
    class FailingOutput:
        def write(self, value): raise OSError('disk full')
        def flush(self): pass
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
    def failed_open(path, *args, **kwargs):
        if str(path).endswith('.rpc.jsonl') and args and args[0]=='a': raise OSError('disk full')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',failed_open)
    receipt=run(engine,context,session)
    assert receipt.status!='done'
    assert engine._process.poll() is not None
    assert engine._lock.acquire(blocking=False)
    engine._lock.release()


def test_malformed_drain_record_cannot_complete(tmp_path):
    engine,context,session=adapter(tmp_path,'malformeddrain')
    receipt=run(engine,context,session)
    assert receipt.status!='done'
    assert receipt.evidence['protocol_failed'] is True


def test_startup_stderr_is_bounded_and_scope_token_redacted(tmp_path):
    engine,context,session=adapter(tmp_path,'startupfail')
    engine.env['SCOPED_GATEWAY_TOKEN']='secret-scope'
    receipt=run(engine,context,session)
    assert receipt.status=='failed'
    assert 'rejected [scoped-token] configuration' in receipt.evidence['stderr']
    assert 'secret-scope' not in receipt.evidence['stderr']


def test_resume_cannot_complete_using_old_unchanged_assistant(tmp_path):
    import hashlib
    engine,context,session=adapter(tmp_path,'stale')
    old=(json.dumps({'type':'session','id':'trial','cwd':str(tmp_path)})+'\n'+json.dumps({'type':'message','message':{'role':'assistant','stopReason':'stop','content':[{'type':'text','text':'a\u2028b\u2029c'}]}})+'\n').encode()
    session.session_path.write_bytes(old)
    resumed=EngineSession('pi','a'*64,'analysis',session.session_path,True,hashlib.sha256(old).hexdigest())
    receipt=run(engine,context,resumed)
    assert receipt.status=='pending'
    assert receipt.evidence['session_valid'] is False
    assert session.session_path.read_bytes()==old


CONTINUATION_PROCESS = r"""
import json,sys,time,os
from pathlib import Path
mode=sys.argv[1]
mutation=mode.removeprefix('verified')
f=Path(sys.argv[sys.argv.index('--session')+1])
turn=0
def rewrite_old(header=False,assistant=False):
    rows=[json.loads(r) for r in f.read_bytes().splitlines()]
    if header:rows[0]['id']='rewritten-owned'
    elif assistant:
        next(r['message'] for r in rows if r.get('message',{}).get('role')=='assistant')['content'][0]['text']='rewritten earlier assistant text'
    else:rows[1]['message']['content'][0]['text']='rewritten earlier ordinary text'
    f.write_bytes(b''.join(json.dumps(r).encode()+b'\n' for r in rows))
def emit(r):
    sys.stdout.buffer.write(json.dumps(r).encode()+b'\n');sys.stdout.buffer.flush()
def append(r):
    with f.open('ab') as h: h.write(json.dumps(r).encode()+b'\n')
for line in sys.stdin.buffer:
    c=json.loads(line);kind=c['type']
    if kind=='prompt':
        turn+=1
        if turn>1 and mode in ('rejected','handled','queued','wrongack'):
            emit({'type':'response','id':c['id'],'command':'steer' if mode=='wrongack' else kind,'success':mode!='rejected','data':{'disposition':mode if mode in ('handled','queued') else 'started'}})
            continue
        if turn>1 and mutation in ('rewritetextafter','rewriteheaderafter','rewriteassistantafter'):
            rewrite_old(header=mutation=='rewriteheaderafter',assistant=mutation=='rewriteassistantafter')
        if turn>1:
            (f.parent/'prefix.json').write_text(json.dumps({'sha256':__import__('hashlib').sha256(f.read_bytes()).hexdigest(),'size':f.stat().st_size}))
        emit({'type':'response','id':c['id'],'command':kind,'success':True,'data':{'disposition':'started'}})
        if turn>1 and mode=='noevents':continue
        stop='length' if turn==1 or mode=='alwayslength' else 'stop'
        if mode in ('verifiedtwolengths','rewritesecondstate') and turn==2:stop='length'
        if mode=='normal':stop='stop'
        if mode=='error':stop='error'
        message={'role':'assistant','stopReason':stop,'content':[{'type':'text','text':'truncated' if stop=='length' else 'finished'}]}
        if mode=='error':message['errorMessage']='provider failed'
        if not f.exists():append({'type':'session','id':'owned','cwd':str(Path.cwd())})
        append({'type':'message','message':{'role':'user','content':[{'type':'text','text':c['message']}]}})
        if turn==1 and 'rewriteassistant' in mutation:
            earlier={'role':'assistant','stopReason':'stop','content':[{'type':'text','text':'earlier ordinary assistant text'}]}
            append({'type':'message','message':earlier})
            emit({'type':'message_end','message':earlier})
        if turn==1 and (mode.startswith('verified') or mode=='forgedresult'):
            args={'path':'source.py'}
            receipt={'operation_id':'read:owned','status':'done','evidence':{'sha256':'a'*64}}
            content=[{'type':'text','text':json.dumps(receipt)}]
            call={'type':'toolCall','id':'owned-read','name':'read_source','arguments':args}
            append({'type':'message','message':{'role':'assistant','stopReason':'toolUse','content':[call]}})
            append({'type':'message','message':{'role':'toolResult','toolCallId':'owned-read','toolName':'read_source','details':{'receipt':receipt},'content':content,'isError':False}})
            emit({'type':'tool_execution_start','toolCallId':'owned-read','toolName':'read_source','args':args})
            emit({'type':'tool_execution_end','toolCallId':'owned-read','toolName':'read_source','result':{'details':{'receipt':receipt},'content':content},'isError':False})
        append({'type':'message','message':message})
        if mode=='unverified':emit({'type':'tool_execution_start','toolCallId':'foreign','toolName':'bash','args':{}})
        if mode=='pending':emit({'type':'tool_execution_start','toolCallId':'pending','toolName':'read_source','args':{}})
        emit({'type':'message_end','message':message})
        emit({'type':'agent_settled','aborted':mode=='aborted'})
    elif kind=='get_state':
        if mode=='expired':time.sleep(0.7)
        if mutation in ('rewritetextstate','rewriteheaderstate','rewriteassistantstate','transientheaderstate'):rewrite_old(header=mutation in ('rewriteheaderstate','transientheaderstate'),assistant=mutation=='rewriteassistantstate')
        if mode=='rewritesecondstate' and turn==2:
            rows=[json.loads(r) for r in f.read_bytes().splitlines()]
            rows[3]['message']['content'][0]['text']='rewritten continuation instruction'
            f.write_bytes(b''.join(json.dumps(r).encode()+b'\n' for r in rows))
        data={'sessionFile':str(f),'sessionId':'owned','isStreaming':False,'isCompacting':False,'pendingMessageCount':0}
        if mutation in ('rewriteheaderstate','transientheaderstate'):data['sessionId']='rewritten-owned'
        if mode=='streaming':data['isStreaming']=True
        if mode=='compacting':data['isCompacting']=True
        if mode=='queuedstate':data['pendingMessageCount']=1
        if mode=='foreignsession':data['sessionFile']=str(f.parent/'other.jsonl')
        if mode=='foreignid':data['sessionId']='other'
        if mode=='missingstate':del data['isStreaming']
        if mode=='guarderror':emit({'type':'extension_error'})
        if mode=='corruptafterstate':append({'type':'message','message':{'role':'assistant','stopReason':'length','content':[{'type':'toolCall','id':'unobserved','name':'read_source','arguments':{}}]}})
        emit({'type':'response','id':c['id'],'command':kind,'success':True,'data':data})
    elif kind in ('clear_queue','abort'):
        emit({'type':'response','id':c['id'],'command':kind,'success':True})
"""


def continuation_adapter(tmp_path, mode, maximum=1, guard=None):
    engine,context,session=adapter(tmp_path,'ok')
    (tmp_path/'process.py').write_text(CONTINUATION_PROCESS)
    engine.command[-1]=mode
    # Explicit local test availability; the production gateway remains authoritative.
    engine=PiAdapter(engine.command,cwd=tmp_path,env={},config_hash='a'*64,
        max_length_continuations=maximum,continuation_guard=guard if guard is not None else (lambda: True))
    session=EngineSession('pi','a'*64,'develop',session.session_path,False)
    return engine,context,session


def run_continuation(engine, context, session):
    return engine.run_phase(phase='develop',prompt='authorized edit and check',context=context,session=session,
        deadline=datetime.now(timezone.utc)+timedelta(seconds=0.6),tools=list(engine.authorized_tools))


def commands(receipt):
    return [r['record'] for r in map(json.loads,Path(receipt.evidence['transcript_path']).read_text().splitlines()) if r['direction']=='in']


def test_length_continues_in_same_owned_process_and_preserves_session(tmp_path):
    engine,context,session=continuation_adapter(tmp_path,'ok')
    receipt=run_continuation(engine,context,session)
    assert receipt.status=='done'
    assert receipt.evidence['process_exited'] is True
    assert receipt.evidence['owned_pid']==engine._process.pid
    assert [r['type'] for r in commands(receipt)]==['prompt','get_state','prompt','clear_queue','abort']
    records=[json.loads(r) for r in session.session_path.read_bytes().splitlines()]
    assert [r['message']['stopReason'] for r in records if r.get('message',{}).get('role')=='assistant']==['length','stop']
    assert sum(r.get('type')=='session' for r in records)==1
    assert len(commands(receipt)[2]['message'].encode())<=1024
    import hashlib
    prefix=json.loads((tmp_path/'prefix.json').read_text())
    assert hashlib.sha256(session.session_path.read_bytes()[:prefix['size']]).hexdigest()==prefix['sha256']


@pytest.mark.parametrize('maximum',[0,1,2])
def test_length_continuation_count_is_finite(tmp_path, maximum):
    engine,context,session=continuation_adapter(tmp_path,'alwayslength',maximum)
    receipt=run_continuation(engine,context,session)
    assert receipt.status!='done'
    assert sum(r['type']=='prompt' for r in commands(receipt))==1+maximum
    assert receipt.evidence['process_exited'] is True


@pytest.mark.parametrize('mode',['normal','error','aborted','unverified','pending'])
def test_no_continuation_for_normal_or_unsafe_terminal(tmp_path,mode):
    engine,context,session=continuation_adapter(tmp_path,mode)
    if mode=='pending':
        engine.authorized_tools=('read_source',)
        engine.tool_verifier=lambda *args: True
    receipt=run_continuation(engine,context,session)
    assert sum(r['type']=='prompt' for r in commands(receipt))==1
    assert receipt.status==('done' if mode=='normal' else 'failed' if mode=='error' else 'pending')


@pytest.mark.parametrize('mode',['streaming','compacting','queuedstate','foreignsession','foreignid','missingstate','expired','guarderror','corruptafterstate'])
def test_continuation_requires_verified_owned_idle_state_and_original_deadline(tmp_path,mode):
    engine,context,session=continuation_adapter(tmp_path,mode)
    receipt=run_continuation(engine,context,session)
    assert receipt.status!='done'
    assert sum(r['type']=='prompt' for r in commands(receipt))==1
    assert receipt.evidence['process_exited'] is True


@pytest.mark.parametrize('mode',['rejected','handled','queued','wrongack','noevents'])
def test_continuation_requires_started_ack_and_new_completion_events(tmp_path,mode):
    engine,context,session=continuation_adapter(tmp_path,mode)
    receipt=run_continuation(engine,context,session)
    assert receipt.status!='done'
    assert sum(r['type']=='prompt' for r in commands(receipt))==2
    assert receipt.evidence['process_exited'] is True


@pytest.mark.parametrize('available',[False,None,1])
def test_exhausted_or_unverified_local_allowance_prevents_prompt(tmp_path,available):
    engine,context,session=continuation_adapter(tmp_path,'ok',guard=lambda: available)
    receipt=run_continuation(engine,context,session)
    assert receipt.status!='done'
    assert sum(r['type']=='prompt' for r in commands(receipt))==1


def test_allowance_is_rechecked_after_idle_ack_before_prompt(tmp_path):
    checks=iter([True,False])
    engine,context,session=continuation_adapter(tmp_path,'ok',guard=lambda: next(checks))
    receipt=run_continuation(engine,context,session)
    assert receipt.status!='done'
    assert [r['type'] for r in commands(receipt)]==['prompt','get_state','clear_queue','abort']


@pytest.mark.parametrize('maximum',[-1,3,True,1.0])
def test_invalid_continuation_limit_is_rejected_before_spawn(tmp_path,maximum):
    with pytest.raises(ValueError):
        PiAdapter([sys.executable],cwd=tmp_path,env={},config_hash='a'*64,
            max_length_continuations=maximum,continuation_guard=lambda: True)


def test_opt_in_requires_local_gate_before_spawn(tmp_path):
    with pytest.raises(ValueError):
        PiAdapter([sys.executable],cwd=tmp_path,env={},config_hash='a'*64,max_length_continuations=1)


def test_opt_in_is_only_for_fresh_development_phase(tmp_path):
    engine,context,session=continuation_adapter(tmp_path,'ok')
    session=EngineSession('pi','a'*64,'analysis',session.session_path,False)
    with pytest.raises(ValueError):run(engine,context,session)
    assert not list(tmp_path.glob('*.rpc.jsonl'))


@pytest.mark.parametrize('remaining_sends,remaining_tools',[(0,1),(1,0),(0,0)])
def test_local_observed_send_or_tool_exhaustion_is_not_a_new_allowance(tmp_path,remaining_sends,remaining_tools):
    engine,context,session=continuation_adapter(tmp_path,'ok',
        guard=lambda: remaining_sends>0 and remaining_tools>0)
    receipt=run_continuation(engine,context,session)
    assert receipt.status!='done'
    assert sum(r['type']=='prompt' for r in commands(receipt))==1


def test_guard_exception_fails_closed_and_stops_owned_process(tmp_path):
    def unavailable():raise RuntimeError('local counter unreadable')
    engine,context,session=continuation_adapter(tmp_path,'ok',guard=unavailable)
    receipt=run_continuation(engine,context,session)
    assert receipt.status!='done'
    assert receipt.evidence['process_exited'] is True
    assert sum(r['type']=='prompt' for r in commands(receipt))==1


@pytest.mark.parametrize('authentic',[True,False])
def test_continuation_preserves_authoritative_tool_correlation(tmp_path,authentic):
    engine,context,session=continuation_adapter(tmp_path,'verified' if authentic else 'forgedresult')
    engine.authorized_tools=('read_source',)
    engine.tool_verifier=lambda call_id,name,args,receipt: authentic and call_id=='owned-read' and name=='read_source' and args=={'path':'source.py'} and receipt=={'operation_id':'read:owned','status':'done','evidence':{'sha256':'a'*64}}
    receipt=run_continuation(engine,context,session)
    assert receipt.status==('done' if authentic else 'pending')
    assert receipt.evidence['verified_tool_calls']==(['owned-read'] if authentic else [])
    assert sum(r['type']=='prompt' for r in commands(receipt))==(2 if authentic else 1)


@pytest.mark.parametrize('mode,prompt_count',[
    ('rewritetextstate',1),('rewriteheaderstate',1),
    ('rewritetextafter',2),('rewriteheaderafter',2)])
def test_continuation_rejects_rewritten_original_text_or_session_header(tmp_path,mode,prompt_count):
    engine,context,session=continuation_adapter(tmp_path,mode)
    receipt=run_continuation(engine,context,session)
    assert receipt.status!='done'
    assert receipt.evidence['session_valid'] is False
    assert sum(r['type']=='prompt' for r in commands(receipt))==prompt_count
    assert receipt.evidence['process_exited'] is True



def test_prefix_is_rechecked_after_local_guard_before_prompt(tmp_path):
    checks=0
    def mutate_on_second_gate():
        nonlocal checks
        checks+=1
        if checks==2:
            session.session_path.write_bytes(session.session_path.read_bytes().replace(
                b'authorized edit and check',b'changed earlier user text'))
        return True
    engine,context,session=continuation_adapter(tmp_path,'ok',guard=mutate_on_second_gate)
    receipt=run_continuation(engine,context,session)
    assert receipt.status!='done'
    assert receipt.evidence['session_valid'] is False
    assert sum(r['type']=='prompt' for r in commands(receipt))==1


def test_second_length_pins_all_new_bytes_before_next_continuation(tmp_path):
    engine,context,session=continuation_adapter(tmp_path,'rewritesecondstate',maximum=2)
    receipt=run_continuation(engine,context,session)
    assert receipt.status!='done'
    assert receipt.evidence['session_valid'] is False
    assert sum(r['type']=='prompt' for r in commands(receipt))==2


def test_two_continuations_keep_earlier_authenticated_tool_enumeration(tmp_path):
    engine,context,session=continuation_adapter(tmp_path,'verifiedtwolengths',maximum=2)
    engine.authorized_tools=('read_source',)
    engine.tool_verifier=lambda call_id,name,args,receipt: call_id=='owned-read' and name=='read_source' and args=={'path':'source.py'} and receipt=={'operation_id':'read:owned','status':'done','evidence':{'sha256':'a'*64}}
    receipt=run_continuation(engine,context,session)
    assert receipt.status=='done'
    assert receipt.evidence['verified_tool_calls']==['owned-read']
    assert sum(r['type']=='prompt' for r in commands(receipt))==3
    assert receipt.evidence['length_continuations']==2


@pytest.mark.parametrize('mutation,prompt_count',[
    ('rewritetextstate',1),('rewriteheaderstate',1),('rewriteassistantstate',1),
    ('rewritetextafter',2),('rewriteheaderafter',2),('rewriteassistantafter',2)])
def test_raw_prefix_rewrite_is_denied_even_with_authentic_tool_correlations(tmp_path,mutation,prompt_count):
    engine,context,session=continuation_adapter(tmp_path,'verified'+mutation)
    engine.authorized_tools=('read_source',)
    engine.tool_verifier=lambda call_id,name,args,receipt: call_id=='owned-read' and name=='read_source' and args=={'path':'source.py'} and receipt=={'operation_id':'read:owned','status':'done','evidence':{'sha256':'a'*64}}
    receipt=run_continuation(engine,context,session)
    assert receipt.status!='done'
    assert receipt.evidence['session_valid'] is False
    assert receipt.evidence['verified_tool_calls']==['owned-read']
    assert sum(r['type']=='prompt' for r in commands(receipt))==prompt_count



def test_transient_header_identity_cannot_become_idle_state_authority(tmp_path,monkeypatch):
    engine,context,session=continuation_adapter(tmp_path,'verifiedtransientheaderstate')
    engine.authorized_tools=('read_source',)
    engine.tool_verifier=lambda call_id,name,args,receipt: call_id=='owned-read' and name=='read_source' and args=={'path':'source.py'} and receipt=={'operation_id':'read:owned','status':'done','evidence':{'sha256':'a'*64}}
    original_read=Path.read_bytes
    def transient_read(path):
        raw=original_read(path)
        if path==session.session_path and b'rewritten-owned' in raw:
            # Real process changed the header for get_state; restore immediately after
            # this read, before the following validation, to expose the identity race.
            path.write_bytes(engine._continuation_prefix)
        return raw
    monkeypatch.setattr(Path,'read_bytes',transient_read)
    receipt=run_continuation(engine,context,session)
    assert receipt.status!='done'
    assert receipt.evidence['verified_tool_calls']==['owned-read']
    assert sum(r['type']=='prompt' for r in commands(receipt))==1
    assert receipt.evidence['process_exited'] is True


def test_shutdown_waits_for_acknowledged_writer_flush_before_closing_pipe(tmp_path,monkeypatch):
    """A peer can ACK an unbuffered write before the sender finishes flush()."""
    import time
    from ops.pi import pi_rpc
    original=pi_rpc.subprocess.Popen
    class DelayedAbortFlush:
        def __init__(self,pipe):self.pipe=pipe;self.abort=False
        def write(self,value):
            self.abort=json.loads(value)['type']=='abort'
            return self.pipe.write(value)
        def flush(self):
            if self.abort:time.sleep(.1)
            return self.pipe.flush()
        def close(self):return self.pipe.close()
    def spawn(*args,**kwargs):
        process=original(*args,**kwargs);process.stdin=DelayedAbortFlush(process.stdin);return process
    monkeypatch.setattr(pi_rpc.subprocess,'Popen',spawn)
    engine,context,session=adapter(tmp_path,'ok');receipt=run(engine,context,session)
    assert receipt.status=='done' and receipt.evidence['protocol_failed'] is False
    assert engine._threads[2].is_alive() is False


def test_shutdown_writer_timeout_stays_failed_even_with_peer_ack(tmp_path,monkeypatch):
    import time
    from ops.pi import pi_rpc
    original=pi_rpc.subprocess.Popen
    class StalledFlush:
        def __init__(self,pipe):self.pipe=pipe;self.abort=False
        def write(self,value):self.abort=json.loads(value)['type']=='abort';return self.pipe.write(value)
        def flush(self):
            if self.abort:time.sleep(.35)
            return self.pipe.flush()
        def close(self):return self.pipe.close()
    def spawn(*args,**kwargs):
        process=original(*args,**kwargs);process.stdin=StalledFlush(process.stdin);return process
    monkeypatch.setattr(pi_rpc.subprocess,'Popen',spawn)
    engine,context,session=adapter(tmp_path,'ok');receipt=run(engine,context,session)
    assert receipt.status!='done' and receipt.evidence['writer_failed'] is True
    assert receipt.evidence['protocol_failed'] is True and engine._process.poll() is not None


def test_malformed_reader_diagnostic_remains_distinct(tmp_path):
    engine,context,session=adapter(tmp_path,'malformeddrain');receipt=run(engine,context,session)
    assert receipt.status!='done' and receipt.evidence['reader_failed'] is True
