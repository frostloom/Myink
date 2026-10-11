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
