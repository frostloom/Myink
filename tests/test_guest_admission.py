"""Real HTTP admission and resume boundaries keep durable charges consistent."""
import json
import uuid
from types import SimpleNamespace

import pika
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import identity_headers
from test_guest_quota import guest_account, reserve
from myink import guest_quota as q
from myink.api.main import app
from myink.db import new_session, tenant_session
from myink.models import Project, Task
from myink.models.guest import GuestQuotaOperation
from myink.worker import enqueue as queue
from myink.worker.redis_client import get_redis, inflight_key

client = TestClient(app)


@pytest.fixture
def guest_book(guest_account, temp_project, stub_provider):
    uid, ip = guest_account
    stub_provider('金丹', '金丹')
    with new_session() as db:
        db.get(Project, uuid.UUID(temp_project)).user_id = uuid.UUID(uid)
        db.commit()
    yield SimpleNamespace(uid=uid, ip=ip, pid=temp_project,
                          headers={**identity_headers(uid),'X-Myink-Client-IP':ip})
    get_redis().delete(inflight_key(uid,temp_project))


def generate(book, **body):
    return client.post(f'/api/v1/projects/{book.pid}/chapters/{uuid.uuid4()}/generate',
                       headers=book.headers,json={'seq':1,**body})


def test_http_quota_and_batch_rejection_preserve_balance(guest_book, monkeypatch):
    b = guest_book
    reserve(q,b.uid,b.ip,amount=8)
    monkeypatch.setattr(queue.amqp,'publish_once', lambda *a,**kw:pytest.fail('must not publish'))
    response = client.post(f'/api/v1/projects/{b.pid}/batches/generate', headers=b.headers,json={'size':3})
    assert response.status_code == 429
    assert response.json() == {'error':'GUEST_QUOTA_EXHAUSTED'}
    view = client.get('/api/v1/auth/guest/quota',headers=b.headers)
    assert view.status_code == 200
    assert view.json()['long']['remaining'] == 2


@pytest.mark.parametrize('failure', ['gate','nack','not_sent','unknown'])
def test_admission_failure_windows(guest_book,monkeypatch,failure):
    b = guest_book
    if failure == 'gate':
        get_redis().sadd(inflight_key(b.uid,b.pid),'busy')
    def publish(*a,**kw):
        if failure == 'nack': raise pika.exceptions.NackError([])
        if failure == 'not_sent': raise queue.amqp.PublishNotSent('connect failed')
        raise TimeoutError('confirmation lost')
    monkeypatch.setattr(queue.amqp,'publish_once',publish)
    response = generate(b)
    assert response.status_code == (429 if failure == 'gate' else 503)
    assert q.quota_view(b.uid,b.ip)['long']['used'] == (1 if failure == 'unknown' else 0)


def test_charge_committed_before_publish_and_materialization(guest_book,monkeypatch):
    b = guest_book
    seen=[]
    def publish(raw,*a,**kw):
        message=json.loads(raw)
        with new_session() as db:
            receipt=db.get(GuestQuotaOperation,uuid.UUID(message['payload']['_guest_operation']))
            assert receipt.active and str(receipt.task_id)==message['task_id']
            assert db.get(Task,receipt.task_id) is None
        seen.append(message)
    monkeypatch.setattr(queue.amqp,'publish_once',publish)
    response=generate(b)
    assert response.status_code==202,response.text
    assert len(seen)==1
    assert q.quota_view(b.uid,b.ip)['long']['used']==1


def test_guest_invalid_ip_fails_closed(guest_book,monkeypatch):
    b=guest_book
    b.headers['X-Myink-Client-IP']='unknown'
    monkeypatch.setattr(queue.amqp,'publish_once',lambda *a,**kw:pytest.fail('must not publish'))
    response=generate(b)
    assert response.status_code==503
    assert response.json()=={'error':'GUEST_IP_UNAVAILABLE'}


@pytest.fixture
def resume_guest(guest_book,monkeypatch):
    b=guest_book
    tid=str(uuid.uuid4())
    with tenant_session(b.pid) as db:
        db.add(Task(id=uuid.UUID(tid),project_id=uuid.UUID(b.pid),task_type='chapter_generate',
                    status='failed',payload={'seq':1}))
    reserve(q,b.uid,b.ip,amount=10)
    snapshot=SimpleNamespace(values={'project_id':b.pid,'task_id':tid,'chapter_seq':1},next=('write',))
    graph=SimpleNamespace(get_state=lambda *a,**kw:snapshot)
    monkeypatch.setattr('myink.workflow.runner.get_graphs',lambda:(graph,graph))
    return b,tid,snapshot


def test_failed_body_manual_resume_requires_new_quota(resume_guest,monkeypatch):
    b,tid,snap=resume_guest
    # A real durable attempt exists even when the body call itself never returned.
    assert hasattr(q,'record_body_attempt'), 'body attempts must survive provider failure'
    q.record_body_attempt(tid, f'{tid}:write:ch1:r0:p0:re0:bg0')
    monkeypatch.setattr(queue.amqp,'publish_once',lambda *a,**kw:pytest.fail('must not publish'))
    result=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers)
    assert result.status_code==429,result.text
    with new_session() as db:
        assert db.get(Task,uuid.UUID(tid)).status=='failed'


@pytest.mark.parametrize('status,next_node', [('paused','write'),('failed','persist'),('failed','summarize')])
def test_zero_quota_first_continuation_and_save_are_allowed(resume_guest,monkeypatch,status,next_node):
    b,tid,snap=resume_guest
    snap.next=(next_node,)
    with new_session() as db:
        db.get(Task,uuid.UUID(tid)).status=status
        db.commit()
    sent=[]
    monkeypatch.setattr(queue.amqp,'publish_once',lambda raw,*a,**kw:sent.append(json.loads(raw)))
    result=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers)
    assert result.status_code==200,result.text
    assert len(sent)==1
    assert q.quota_view(b.uid,b.ip)['long']['used']==10


def test_review_revision_cannot_be_added_after_free_resume_admission(resume_guest,monkeypatch):
    from myink.models import MemoryCandidate
    from myink.workflow.review import resolve_review
    b,tid,snap=resume_guest
    with tenant_session(b.pid) as db:
        db.add(MemoryCandidate(project_id=uuid.UUID(b.pid),kind='fact',source_chapter=1,payload={},
                               status='rejected',review={'mode':'revise','applied':False}))
    graph=SimpleNamespace(checkpointer=None)
    monkeypatch.setattr('myink.workflow.chapter_graph.build_chapter_graph',
        lambda **kw:SimpleNamespace(invoke=lambda *a,**kw:pytest.fail('unadmitted body revision executed')))
    with pytest.raises(q.GuestQuotaError,match='GUEST_REVIEW_NOT_ADMITTED'):
        resolve_review(graph,snap.values,task_id=tid)


@pytest.mark.parametrize('mode,status', [('revise',429),('memory_only',200)])
def test_candidate_rejection_resume_charges_only_requested_body_revision(resume_guest,monkeypatch,mode,status):
    from myink.models import MemoryCandidate
    b,tid,snap=resume_guest
    snap.next=()
    snap.values['needs_review']=True
    with tenant_session(b.pid) as db:
        db.get(Task,uuid.UUID(tid)).status='awaiting_review'
        cand=MemoryCandidate(project_id=uuid.UUID(b.pid),kind='fact',source_chapter=1,payload={})
        db.add(cand)
        db.flush()
        cid=str(cand.id)
    rejected=client.post(f'/api/v1/projects/{b.pid}/candidates/{cid}/reject',headers=b.headers,json={'mode':mode})
    assert rejected.status_code==200,rejected.text
    sent=[]
    monkeypatch.setattr(queue.amqp,'publish_once',lambda raw,*a,**kw:sent.append(raw))
    resumed=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers)
    assert resumed.status_code==status,resumed.text
    assert len(sent)==int(status==200)


@pytest.mark.parametrize('budgeted', [False,True])
@pytest.mark.parametrize('failure', ['nack','unknown'])
def test_failed_resume_compensation_and_same_budget_operation_retry(guest_book,monkeypatch,budgeted,failure):
    from myink.task_budget import ensure_task_budget
    b=guest_book
    tid=str(uuid.uuid4())
    with tenant_session(b.pid) as db:
        db.add(Task(id=uuid.UUID(tid),project_id=uuid.UUID(b.pid),task_type='chapter_generate',
                    status='failed',payload={'seq':1}))
    if budgeted:
        ensure_task_budget(tid,b.pid,b.uid,{'max_requests':100})
    snap=SimpleNamespace(values={'project_id':b.pid,'task_id':tid,'chapter_seq':1},next=('write',))
    graph=SimpleNamespace(get_state=lambda *a,**kw:snap)
    monkeypatch.setattr('myink.workflow.runner.get_graphs',lambda:(graph,graph))
    q.record_body_attempt(tid,f'{tid}:write:ch1:r0:p0:re0:bg0')
    reserve(q,b.uid,b.ip,amount=9)
    calls=[]
    def publish(raw,*a,**kw):
        calls.append(json.loads(raw))
        if len(calls)==1:
            if failure=='nack': raise pika.exceptions.NackError([])
            raise TimeoutError('confirm lost')
    monkeypatch.setattr(queue.amqp,'publish_once',publish)
    body={'operation_id':str(uuid.uuid4())} if budgeted else {}
    first=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json=body)
    assert first.status_code==503,first.text
    assert q.quota_view(b.uid,b.ip)['long']['used']==(9 if failure=='nack' else 10)
    second=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json=body)
    assert second.status_code==200,second.text
    assert len(calls)==(2 if failure=='nack' else 1)
    assert q.quota_view(b.uid,b.ip)['long']['used']==10


def test_budgeted_failed_body_replay_rejected_before_appending_budget(resume_guest,monkeypatch):
    from myink.task_budget import ensure_task_budget,budget_view
    b,tid,snap=resume_guest
    ensure_task_budget(tid,b.pid,b.uid,{'max_requests':100})
    q.record_body_attempt(tid,f'{tid}:write:ch1:r0:p0:re0:bg0')
    monkeypatch.setattr(queue.amqp,'publish_once',lambda *a,**kw:pytest.fail('must not publish'))
    result=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,
                      json={'operation_id':str(uuid.uuid4()),'add_requests':2})
    assert result.status_code==429,result.text
    assert budget_view(tid)['limits']['max_requests']==100


def test_batch_failed_resume_charges_current_chapter_only(guest_book,monkeypatch):
    b=guest_book
    tid=str(uuid.uuid4())
    with tenant_session(b.pid) as db:
        db.add(Task(id=uuid.UUID(tid),project_id=uuid.UUID(b.pid),task_type='batch_generate',
                    status='failed',payload={'start':1,'size':8}))
    reserve(q,b.uid,b.ip,amount=8)
    q.record_body_attempt(tid,f'{tid}:ch3:write:ch3:r0:p0:re0:bg0')
    chapter=SimpleNamespace(get_state=lambda *a,**kw:SimpleNamespace(
        values={'project_id':b.pid,'task_id':f'{tid}:ch3','chapter_seq':3},next=('write',)))
    batch=SimpleNamespace(get_state=lambda *a,**kw:SimpleNamespace(values={'start_chapter':1,'position':2},next=('chapter',)))
    monkeypatch.setattr('myink.workflow.runner.get_graphs',lambda:(chapter,batch))
    monkeypatch.setattr(queue.amqp,'publish_once',lambda *a,**kw:None)
    result=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers)
    assert result.status_code==200,result.text
    assert q.quota_view(b.uid,b.ip)['long']['used']==9


def test_worker_rejects_missing_and_released_guest_receipt(guest_book,monkeypatch):
    from myink.worker import processor
    b=guest_book
    body={'task_id':str(uuid.uuid4()),'task_type':'chapter_generate','project_id':b.pid,
          'user_id':b.uid,'payload':{}}
    assert processor.process(body)=='skip'
    receipt=q.reserve(user_id=b.uid,client_ip=b.ip,dimension='long',amount=1,
                      operation_id=str(uuid.uuid4()),task_id=body['task_id'])
    body['payload']['_guest_operation']=receipt
    assert q.valid_message(body)
    q.release(receipt)
    assert processor.process(body)=='skip'


def test_nacked_budget_resume_with_new_operation_cannot_become_free(guest_book,monkeypatch):
    from myink.task_budget import ensure_task_budget
    b=guest_book
    tid=str(uuid.uuid4())
    with tenant_session(b.pid) as db:
        db.add(Task(id=uuid.UUID(tid),project_id=uuid.UUID(b.pid),task_type='chapter_generate',
                    status='failed',payload={'seq':1}))
    ensure_task_budget(tid,b.pid,b.uid,{})
    snap=SimpleNamespace(values={'task_id':tid,'chapter_seq':1},next=('write',))
    graph=SimpleNamespace(get_state=lambda *a,**kw:snap)
    monkeypatch.setattr('myink.workflow.runner.get_graphs',lambda:(graph,graph))
    q.record_body_attempt(tid,f'{tid}:write:ch1:r0:p0:re0:bg0')
    calls=[]
    def publish(raw,*a,**kw):
        calls.append(raw)
        if len(calls)==1: raise pika.exceptions.NackError([])
    monkeypatch.setattr(queue.amqp,'publish_once',publish)
    first=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json={'operation_id':str(uuid.uuid4())})
    assert first.status_code==503
    second=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json={'operation_id':str(uuid.uuid4())})
    assert second.status_code==200,second.text
    assert q.quota_view(b.uid,b.ip)['long']['used']==1


def test_short_whole_story_rewrite_charges_one_each(guest_book,monkeypatch):
    from myink.short.form import ShortParams
    b=guest_book
    with new_session() as db:
        db.get(Project,uuid.UUID(b.pid)).form='short'
        db.commit()
    monkeypatch.setattr('myink.workflow.short_runner.short_params_for',lambda _:ShortParams(6,2000))
    sent=[]
    monkeypatch.setattr(queue.amqp,'publish_once',lambda raw,*a,**kw:sent.append(json.loads(raw)))
    for _ in range(2):
        result=client.post(f'/api/v1/projects/{b.pid}/short/generate',headers=b.headers)
        assert result.status_code==202,result.text
        get_redis().delete(inflight_key(b.uid,b.pid))
    blocked=client.post(f'/api/v1/projects/{b.pid}/short/generate',headers=b.headers)
    assert blocked.status_code==429,blocked.text
    assert q.quota_view(b.uid,b.ip)=={'short':{'limit':2,'used':2,'remaining':0},'long':{'limit':10,'used':0,'remaining':10}}
    assert len({message['payload']['_guest_operation'] for message in sent})==2


@pytest.mark.parametrize('stage,body_node,expected', [('complete','short_write',200),('reviewed','short_revise',429),('written','short_continue',429)])
def test_short_resume_replays_only_attempted_body_stage(guest_book,monkeypatch,stage,body_node,expected):
    from myink.models.task_budget import TaskBudgetCall
    from myink.task_budget import ensure_task_budget
    b=guest_book
    tid=str(uuid.uuid4())
    with tenant_session(b.pid) as db:
        db.add(Task(id=uuid.UUID(tid),project_id=uuid.UUID(b.pid),task_type='short_generate',
                    status='failed',payload={'chapter_count':2}))
    ensure_task_budget(tid,b.pid,b.uid,{})
    with tenant_session(b.pid) as db:
        db.add(TaskBudgetCall(task_id=uuid.UUID(tid),project_id=uuid.UUID(b.pid),operation_key='short:progress',
            input_hash='progress',response={'stage':stage,'review':{'verdict':'revise'},'bodies':['a','']}))
    q.record_body_attempt(tid,f'{tid}:{body_node}')
    reserve(q,b.uid,b.ip,dimension='short',amount=2)
    sent=[]
    monkeypatch.setattr(queue.amqp,'publish_once',lambda *a,**kw:sent.append(a))
    result=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers)
    assert result.status_code==expected,result.text
    assert bool(sent)==(expected==200)


def test_guest_storage_failure_prevents_publication(guest_book,monkeypatch):
    from sqlalchemy.exc import OperationalError
    def unavailable(*a,**kw):
        raise OperationalError('read ledger',{},Exception('offline'))
    monkeypatch.setattr(q,'reserve_in_session',unavailable)
    monkeypatch.setattr(queue.amqp,'publish_once',lambda *a,**kw:pytest.fail('must not publish'))
    result=generate(guest_book)
    assert result.status_code==503,result.text
    assert result.json()=={'error':'GUEST_QUOTA_UNAVAILABLE'}


def test_body_marker_precedes_provider_failure_and_system_retry_does_not_charge(guest_book):
    from myink.models.guest import GuestBodyAttempt
    from myink.task_budget import bind_task_budget,bind_budget_operation,budgeted_call,ensure_task_budget
    b=guest_book
    tid=str(uuid.uuid4())
    with tenant_session(b.pid) as db:
        db.add(Task(id=uuid.UUID(tid),project_id=uuid.UUID(b.pid),task_type='chapter_generate',status='running',payload={}))
    ensure_task_budget(tid,b.pid,b.uid,{})
    reserve(q,b.uid,b.ip)
    stage=f'{tid}:write:ch1:r0:p0:re0:bg0'
    @budgeted_call
    def provider(chain,messages,**kw):
        with new_session() as db:
            assert db.get(GuestBodyAttempt,(uuid.UUID(tid),stage)) is not None
        raise RuntimeError('provider failed after sending')
    chain=SimpleNamespace(chain=[],prices={},providers=[],thinking_enabled=False)
    for owner in ('first-worker','redelivery-worker'):
        with bind_task_budget(tid,owner),bind_budget_operation(stage):
            with pytest.raises(RuntimeError,match='provider failed'):
                provider(chain,[])
    assert q.quota_view(b.uid,b.ip)['long']['used']==1


def test_guest_creation_skips_platform_lifetime_caps(guest_account,monkeypatch,stub_provider):
    stub_provider("金丹", "金丹")
    from dataclasses import replace
    from sqlalchemy import delete
    from myink.api import routes_book,routes_short_creation,routes_tasks
    from myink.models import User,ShortCreationSession
    from test_platform_key_quota import _seed_active_session,_commit
    uid,ip=guest_account
    with new_session() as db:
        user=db.get(User,uuid.UUID(uid))
        user.platform_long_used=user.platform_short_used=100
        db.commit()
    monkeypatch.setattr(routes_book,'platform_key_active',lambda *a:True)
    monkeypatch.setattr(routes_short_creation,'platform_key_active',lambda *a:True)
    monkeypatch.setattr(routes_book,'settings',replace(routes_book.settings,platform_long_quota=1,books_per_day_max=1000))
    monkeypatch.setattr(routes_short_creation,'settings',replace(routes_short_creation.settings,platform_short_quota=1))
    monkeypatch.setattr(routes_book,'_short_outline_draft',lambda *a,**kw:({'outline_error':'isolated preparation failure'},{}))
    try:
        long=client.post('/api/v1/projects',headers=identity_headers(uid),json={
            'title':'guest planning','premise':'a story','chapter_count':50,'storyline':'line'})
        assert long.status_code==200,long.text
        sid=_seed_active_session(uid)
        short=_commit(uid,sid)
        assert short.status_code==502,short.text
        assert 'PLAN_FAILED' in short.text
        with new_session() as db:
            user=db.get(User,uuid.UUID(uid))
            assert user.platform_long_used==user.platform_short_used==100
    finally:
        with new_session() as db:
            db.execute(delete(ShortCreationSession).where(ShortCreationSession.user_id==uuid.UUID(uid)))
            db.execute(delete(Project).where(Project.user_id==uuid.UUID(uid)))
            db.commit()


@pytest.mark.parametrize('already_used', [8,9])
def test_queued_budget_review_resume_with_new_id_reuses_admission(guest_book,monkeypatch,already_used):
    from myink.models import MemoryCandidate
    from myink.task_budget import ensure_task_budget
    from myink.worker import processor
    b=guest_book
    tid=str(uuid.uuid4())
    with tenant_session(b.pid) as db:
        db.add(Task(id=uuid.UUID(tid),project_id=uuid.UUID(b.pid),task_type='chapter_generate',
                    status='awaiting_review',payload={'seq':1}))
        db.add(MemoryCandidate(project_id=uuid.UUID(b.pid),kind='fact',source_chapter=1,payload={},
                               status='rejected',review={'mode':'revise','applied':False}))
    ensure_task_budget(tid,b.pid,b.uid,{})
    reserve(q,b.uid,b.ip,amount=already_used)
    snap=SimpleNamespace(values={'task_id':tid,'chapter_seq':1,'needs_review':True},next=())
    graph=SimpleNamespace(get_state=lambda *a,**kw:snap)
    monkeypatch.setattr('myink.workflow.runner.get_graphs',lambda:(graph,graph))
    sent=[]
    executed=[]
    monkeypatch.setattr(queue.amqp,'publish_once',lambda raw,*a,**kw:sent.append(json.loads(raw)))
    monkeypatch.setattr(processor,'_dispatch',lambda body:executed.append(body['budget_operation_id']) or {})
    first_id=str(uuid.uuid4())
    for operation in (first_id,str(uuid.uuid4())):
        result=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json={'operation_id':operation})
        assert result.status_code==200,result.text
    assert len(sent)==1
    assert q.quota_view(b.uid,b.ip)['long']['used']==already_used+1
    with new_session() as db:
        assert db.get(Task,uuid.UUID(tid)).payload['_budget_resume_operation']==first_id
    assert processor.process(sent[0])=='terminal'
    assert processor.process(sent[0])=='skip'
    assert executed==[first_id]


def _cached_guest_task(book,task_type):
    from myink.task_budget import ensure_task_budget
    tid=str(uuid.uuid4())
    with tenant_session(book.pid) as db:
        db.add(Task(id=uuid.UUID(tid),project_id=uuid.UUID(book.pid),task_type=task_type,
                    status='running',payload={'seq':1,'chapter_count':1}))
    receipt=q.reserve(user_id=book.uid,client_ip=book.ip,dimension='short' if task_type=='short_generate' else 'long',
                      amount=1,operation_id=str(uuid.uuid4()),task_id=tid)
    with new_session() as db:
        db.get(Task,uuid.UUID(tid)).payload={'seq':1,'chapter_count':1,'_guest_operation':receipt}
        db.commit()
    ensure_task_budget(tid,book.pid,book.uid,{})
    return tid


def test_failed_write_cached_result_recovers_through_resume_and_real_graph_at_zero_quota(guest_book,monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import StateGraph,START,END
    from myink.providers.base import FallbackChain
    from myink.task_budget import bind_task_budget,budget_node
    from myink.workflow import runner
    from myink.workflow.state import ChapterState
    from test_task_budget_recovery import MeteredStub
    b=guest_book
    tid=_cached_guest_task(b,'chapter_generate')
    provider=MeteredStub(['cached正文'])
    chain=FallbackChain(provider,['deepseek-v4-flash'])
    node_calls=[]
    def write(state):
        response=chain.generate([{'role':'user','content':'same write request'}],max_tokens=20)
        node_calls.append(response.content)
        if len(node_calls)==1:
            raise RuntimeError('post-call bookkeeping failed')
        return {'draft':response.content}
    builder=StateGraph(ChapterState)
    builder.add_node('write',budget_node(write,'write'))
    builder.add_edge(START,'write')
    builder.add_edge('write',END)
    graph=builder.compile(checkpointer=InMemorySaver())
    state={'project_id':b.pid,'task_id':tid,'chapter_seq':1}
    with bind_task_budget(tid,'first'):
        with pytest.raises(RuntimeError,match='post-call bookkeeping'):
            graph.invoke(state,{'configurable':{'thread_id':tid}})
    assert provider.calls==1
    assert graph.get_state({'configurable':{'thread_id':tid}}).next==('write',)
    with new_session() as db:
        db.get(Task,uuid.UUID(tid)).status='failed'
        db.commit()
    reserve(q,b.uid,b.ip,amount=9)
    monkeypatch.setattr(runner,'get_graphs',lambda:(graph,graph))
    sent=[]
    monkeypatch.setattr(queue.amqp,'publish_once',lambda raw,*a,**kw:sent.append(json.loads(raw)))
    result=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json={'operation_id':str(uuid.uuid4())})
    assert result.status_code==200,result.text
    with bind_task_budget(tid,'recovery'):
        recovered=runner.resume_thread(graph,tid,state)
    assert recovered['draft']=='cached正文'
    assert provider.calls==1
    assert len(sent)==1
    assert q.quota_view(b.uid,b.ip)['long']['used']==10


@pytest.mark.parametrize('body_node', ['short_write','short_continue','short_revise'])
def test_failed_short_cached_body_recovers_through_resume_and_real_runner(guest_book,monkeypatch,body_node):
    from myink.providers.base import FallbackChain
    from myink.task_budget import bind_task_budget,save_short_progress
    from myink.workflow import short_runner,nodes
    from myink.short.form import ShortParams
    from test_task_budget_recovery import MeteredStub
    b=guest_book
    tid=_cached_guest_task(b,'short_generate')
    provider=MeteredStub(['=== CHAPTER 1 CONTENT ===\n缓存中的短篇正文'])
    chain=FallbackChain(provider,['deepseek-v4-flash'])
    brief={'chapter_count':1,'chars_per_chapter':1000,'outline':{}}
    monkeypatch.setattr(short_runner,'make_chain',lambda *a,**kw:chain)
    monkeypatch.setattr(short_runner,'_outline',lambda *a,**kw:{})
    monkeypatch.setattr(short_runner,'_load_brief',lambda *a,**kw:brief)
    monkeypatch.setattr(short_runner,'_review',lambda *a,**kw:({'verdict':'pass','issues':[]},None))
    failed=[]
    def record_run(db,**kwargs):
        if kwargs['node']==body_node and not failed:
            failed.append(True)
            raise RuntimeError('post-call bookkeeping failed')
    monkeypatch.setattr(nodes,'record_run',record_run)
    for name in ('short_write_messages','short_continue_messages','short_revise_messages'):
        monkeypatch.setattr(short_runner.prompts,name,lambda *a,**kw:[{'role':'user','content':'same body request'}])
    form=ShortParams(1,1000)
    with bind_task_budget(tid,'first'):
        if body_node!='short_write':
            save_short_progress(tid,'written' if body_node=='short_continue' else 'reviewed',
                {'brief':brief,'bodies':['' if body_node=='short_continue' else 'original'],
                 'review':{'verdict':'revise','issues':[]}})
        with pytest.raises(RuntimeError,match='post-call bookkeeping'):
            short_runner.run_short_story(project_id=b.pid,task_id=tid,form=form)
    assert provider.calls==1
    with new_session() as db:
        db.get(Task,uuid.UUID(tid)).status='failed'
        db.commit()
    reserve(q,b.uid,b.ip,dimension='short',amount=1)
    sent=[]
    monkeypatch.setattr(queue.amqp,'publish_once',lambda raw,*a,**kw:sent.append(json.loads(raw)))
    result=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json={'operation_id':str(uuid.uuid4())})
    assert result.status_code==200,result.text
    with bind_task_budget(tid,'recovery'):
        recovered=short_runner.resume_short_story(project_id=b.pid,task_id=tid,form=form)
    assert recovered['chapters'][0]['body']=='缓存中的短篇正文'
    assert provider.calls==1
    assert len(sent)==1
    assert q.quota_view(b.uid,b.ip)['short']['used']==2


@pytest.mark.parametrize('remaining', [0,1])
def test_cached_stage_changed_input_charges_at_uncached_boundary_once(guest_book,monkeypatch,remaining):
    from dataclasses import replace
    from myink.providers.base import FallbackChain
    from myink.task_budget import bind_task_budget,bind_budget_operation,TaskBudgetUnavailable
    from test_task_budget_recovery import MeteredStub
    b=guest_book
    tid=_cached_guest_task(b,'chapter_generate')
    class RetryProvider(MeteredStub):
        def generate(self,*args,**kwargs):
            response=super().generate(*args,**kwargs)
            return replace(response,error='transient failure') if self.calls==2 else response
    provider=RetryProvider(['original cached body','failed attempt','system retry body'])
    chain=FallbackChain(provider,['deepseek-v4-flash'])
    stage=f'{tid}:write:ch1:r0:p0:re0:bg0'
    with bind_task_budget(tid,'first'),bind_budget_operation(stage):
        chain.generate([{'role':'user','content':'original input'}],max_tokens=20)
    with new_session() as db:
        db.get(Task,uuid.UUID(tid)).status='failed'
        db.commit()
    reserve(q,b.uid,b.ip,amount=9-remaining)
    snap=SimpleNamespace(values={'task_id':tid,'chapter_seq':1},next=('write',))
    graph=SimpleNamespace(get_state=lambda *a,**kw:snap)
    monkeypatch.setattr('myink.workflow.runner.get_graphs',lambda:(graph,graph))
    monkeypatch.setattr(queue.amqp,'publish_once',lambda *a,**kw:None)
    result=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json={'operation_id':str(uuid.uuid4())})
    assert result.status_code==200,result.text
    assert q.quota_view(b.uid,b.ip)['long']['used']==10-remaining
    with bind_task_budget(tid,'recovery'),bind_budget_operation(stage):
        if remaining:
            assert chain.generate([{'role':'user','content':'changed input'}],max_tokens=20).error
        else:
            with pytest.raises(TaskBudgetUnavailable,match='GUEST_QUOTA_EXHAUSTED'):
                chain.generate([{'role':'user','content':'changed input'}],max_tokens=20)
    assert provider.calls==(2 if remaining else 1)
    assert q.quota_view(b.uid,b.ip)['long']['used']==10
    # Automatic retry of an already charged provider failure keeps the operation.
    # A pause caused by no quota must preserve the still-unpaid cache-miss guard.
    if remaining:
        with bind_task_budget(tid,'redelivery'),bind_budget_operation(stage):
            assert chain.generate([{'role':'user','content':'changed input'}],max_tokens=20).content=='system retry body'
        assert provider.calls==3
    else:
        with new_session() as db:
            db.get(Task,uuid.UUID(tid)).status='paused'
            db.commit()
        resumed=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json={'operation_id':str(uuid.uuid4())})
        assert resumed.status_code==200,resumed.text
        with bind_task_budget(tid,'paused-recovery'),bind_budget_operation(stage):
            with pytest.raises(TaskBudgetUnavailable,match='GUEST_QUOTA_EXHAUSTED'):
                chain.generate([{'role':'user','content':'changed input'}],max_tokens=20)
        assert provider.calls==1
    assert q.quota_view(b.uid,b.ip)['long']['used']==10


def test_cached_replay_guard_transaction_failure_never_calls_provider(guest_book,monkeypatch):
    from sqlalchemy.exc import OperationalError
    from myink.providers.base import FallbackChain
    from myink.task_budget import bind_task_budget,bind_budget_operation,TaskBudgetUnavailable
    from test_task_budget_recovery import MeteredStub
    b=guest_book
    tid=_cached_guest_task(b,'chapter_generate')
    provider=MeteredStub(['cached','must not execute'])
    chain=FallbackChain(provider,['deepseek-v4-flash'])
    stage=f'{tid}:write:ch1:r0:p0:re0:bg0'
    with bind_task_budget(tid,'first'),bind_budget_operation(stage):
        chain.generate([{'role':'user','content':'original'}],max_tokens=20)
    with new_session() as db:
        db.get(Task,uuid.UUID(tid)).status='failed'
        db.commit()
    snap=SimpleNamespace(values={'task_id':tid,'chapter_seq':1},next=('write',))
    graph=SimpleNamespace(get_state=lambda *a,**kw:snap)
    monkeypatch.setattr('myink.workflow.runner.get_graphs',lambda:(graph,graph))
    monkeypatch.setattr(queue.amqp,'publish_once',lambda *a,**kw:None)
    result=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json={'operation_id':str(uuid.uuid4())})
    assert result.status_code==200,result.text
    def unavailable(*a,**kw):
        raise OperationalError('reserve guest replay',{},Exception('database unavailable'))
    monkeypatch.setattr(q,'_reserve_keys',unavailable)
    with bind_task_budget(tid,'recovery'),bind_budget_operation(stage):
        with pytest.raises(TaskBudgetUnavailable,match='guest body accounting unavailable'):
            chain.generate([{'role':'user','content':'changed'}],max_tokens=20)
    assert provider.calls==1
    assert q.quota_view(b.uid,b.ip)['long']['used']==1


def _review_execution_case(book,monkeypatch,*,fail_revision_once=False):
    from langgraph.checkpoint.memory import InMemorySaver
    from myink.models import Chapter,MemoryCandidate
    from myink.providers.base import FallbackChain
    from myink.task_budget import bind_task_budget,bind_budget_operation
    from myink.workflow import nodes,runner
    from myink.workflow.chapter_graph import build_chapter_graph
    from myink.worker import processor
    from test_task_budget_recovery import MeteredStub
    tid=_cached_guest_task(book,'chapter_generate')
    provider=MeteredStub(['original cached draft','new reviewed draft'])
    chain=FallbackChain(provider,['deepseek-v4-flash'])
    with bind_task_budget(tid,'initial'),bind_budget_operation(f'{tid}:write:ch1:r0:p0:re0:bg0'):
        chain.generate([{'role':'user','content':'original draft'}],max_tokens=20)
    revision_calls=[]
    def revise(state):
        response=chain.generate([{'role':'user','content':json.dumps(state.get('context') or {},sort_keys=True)}],max_tokens=20)
        revision_calls.append(response.content)
        if fail_revision_once and len(revision_calls)==1:
            raise RuntimeError('revision bookkeeping failed after saved response')
        return {'draft':response.content,'revision_count':1}
    monkeypatch.setattr(nodes,'node_revise',revise)
    for name in ('extract','validate','summarize'):
        monkeypatch.setattr(nodes,'node_'+name,lambda state:{})
    monkeypatch.setattr(nodes,'node_audit',lambda state:{'audit_verdict':{'verdict':'pass'}})
    monkeypatch.setattr(nodes,'node_persist',lambda state:{'needs_review':False,'persisted':True})
    graph=build_chapter_graph(checkpointer=InMemorySaver())
    graph.update_state({'configurable':{'thread_id':tid}},
        {'project_id':book.pid,'task_id':tid,'chapter_seq':1,'draft':'original cached draft',
         'needs_review':True,'candidates':[]},as_node='summarize')
    for module in (runner,processor):
        monkeypatch.setattr(module,'get_graphs',lambda:(graph,None))
    with tenant_session(book.pid) as db:
        db.get(Task,uuid.UUID(tid)).status='awaiting_review'
        db.add(Chapter(project_id=uuid.UUID(book.pid),chapter_seq=1,status='awaiting_review',content='original cached draft'))
        candidate=MemoryCandidate(project_id=uuid.UUID(book.pid),source_chapter=1,kind='fact',payload={'content':'late setting'})
        db.add(candidate)
        db.flush()
        cid=str(candidate.id)
    sent=[]
    monkeypatch.setattr(queue.amqp,'publish_once',lambda raw,*a,**kw:sent.append(json.loads(raw)))
    return tid,cid,provider,sent


@pytest.mark.parametrize('remaining', [0,1])
def test_late_rejected_candidate_new_revision_cannot_use_initial_write_cache(guest_book,monkeypatch,remaining):
    from myink.worker import processor
    b=guest_book
    tid,cid,provider,sent=_review_execution_case(b,monkeypatch)
    reserve(q,b.uid,b.ip,amount=9-remaining)
    free=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json={'operation_id':str(uuid.uuid4())})
    assert free.status_code==200,free.text
    rejected=client.post(f'/api/v1/projects/{b.pid}/candidates/{cid}/reject',headers=b.headers,json={'mode':'revise'})
    assert rejected.status_code==200,rejected.text
    assert processor.process(sent[0])=='terminal'
    with new_session() as db:
        task=db.get(Task,uuid.UUID(tid))
        assert task.status=='failed'
        assert 'GUEST_REVIEW_NOT_ADMITTED' in task.error
    assert provider.calls==1
    retried=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json={'operation_id':str(uuid.uuid4())})
    if retried.status_code==200:
        assert processor.process(sent[1])=='terminal'
    else:
        assert remaining==0 and retried.status_code==429,retried.text
        assert retried.json()=={'error':'GUEST_QUOTA_EXHAUSTED'}
    assert provider.calls==1+remaining
    assert q.quota_view(b.uid,b.ip)['long']['used']==10
    if remaining:
        with new_session() as db:
            assert db.get(Task,uuid.UUID(tid)).status=='done'


def test_same_review_revision_cached_response_recovers_free_at_zero_quota(guest_book,monkeypatch):
    from myink.worker import processor
    from myink.models import MemoryCandidate
    b=guest_book
    tid,cid,provider,sent=_review_execution_case(b,monkeypatch,fail_revision_once=True)
    reserve(q,b.uid,b.ip,amount=8)
    rejected=client.post(f'/api/v1/projects/{b.pid}/candidates/{cid}/reject',headers=b.headers,json={'mode':'revise'})
    assert rejected.status_code==200,rejected.text
    first=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json={'operation_id':str(uuid.uuid4())})
    assert first.status_code==200,first.text
    assert processor.process(sent[0])=='terminal'
    assert provider.calls==2
    with new_session() as db:
        assert db.get(Task,uuid.UUID(tid)).status=='failed'
    assert q.quota_view(b.uid,b.ip)['long']['used']==10
    recovered=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers,json={'operation_id':str(uuid.uuid4())})
    assert recovered.status_code==200,recovered.text
    assert processor.process(sent[1])=='terminal'
    assert provider.calls==2
    assert q.quota_view(b.uid,b.ip)['long']['used']==10
    with new_session() as db:
        assert db.get(Task,uuid.UUID(tid)).status=='done'
