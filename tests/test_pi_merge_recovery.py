"""Cross-feature recovery regressions found by the independent source review."""
import json, time, uuid
from dataclasses import replace
from types import SimpleNamespace
import pytest
from conftest import identity_headers
from test_guest_admission import guest_book, resume_guest
from test_guest_quota import guest_account
from myink.worker import handoff, amqp
from myink.db import new_session, tenant_session
from myink.models import Task

@pytest.fixture
def isolated_broker(monkeypatch):
    monkeypatch.setattr(amqp, 'settings', replace(amqp.settings, queue_prefix='-review-'+uuid.uuid4().hex))
    with amqp.connect() as conn:
        amqp.declare_topology(conn.channel())
    yield
    with amqp.connect() as conn:
        ch=conn.channel()
        for q in [amqp.main_queue(),amqp.vip_queue(),amqp.delay_queue(),amqp.vip_delay_queue(),amqp.dlq_queue()]:
            ch.queue_delete(q)
        ch.exchange_delete(amqp.exchange()); ch.exchange_delete(amqp.dlx_exchange())

def test_real_vip_ttl_predecessor(isolated_broker):
    tid=str(uuid.uuid4()); operation='review:'+tid
    body={'task_id':tid,'request_id':tid,'project_id':str(uuid.uuid4()),'retry_count':1}
    ttl=5000
    row=SimpleNamespace(state='published',body_hash=handoff.body_hash(body),task_id=uuid.UUID(tid),project_id=uuid.UUID(body['project_id']),message_id=tid,priority=amqp.settings.priority_vip,destination='delay',expiration_ms=ttl)
    amqp.publish_once(json.dumps(body),'delay',priority=row.priority,expiration_ms=ttl,operation_id=operation)
    with amqp.connect() as conn:
        ch=conn.channel(); deadline=time.monotonic()+10
        while True:
            method,properties,raw=ch.basic_get(amqp.vip_queue(),auto_ack=False)
            if method: break
            assert time.monotonic()<deadline
            conn.sleep(.1)
        try:
            assert handoff.delivery_predecessor(SimpleNamespace(get=lambda *a:row),json.loads(raw),properties)==operation
        finally: ch.basic_ack(method.delivery_tag)

def test_census_includes_real_vip_queues(isolated_broker):
    body={'task_id':str(uuid.uuid4()),'request_id':str(uuid.uuid4())}
    amqp.publish_once(json.dumps(body),'tasks',priority=amqp.settings.priority_vip)
    deliveries,unknown=handoff._queue_census()
    assert any(b.get('task_id')==body['task_id'] for _,b,_ in deliveries), deliveries

def test_guest_legacy_resume_has_worker_authority(resume_guest,monkeypatch):
    from test_guest_admission import client
    from myink.worker.processor import valid_task_owner
    b,tid,snap=resume_guest
    snap.next=('persist',)
    sent=[]
    monkeypatch.setattr(amqp,'publish_once',lambda raw,*a,**kw:sent.append(json.loads(raw)))
    response=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers)
    assert response.status_code==200,response.text
    assert valid_task_owner(sent[0]) is True

def test_guest_resume_rechecks_maintenance_in_mutation_transaction(resume_guest,monkeypatch):
    from test_guest_admission import client
    from sqlalchemy import text
    from myink.db import get_admin_engine
    from myink import guest_quota
    b,tid,snap=resume_guest
    snap.next=('persist',)
    original=guest_quota.resume_legacy
    def close_between_route_check_and_mutation(*args,**kwargs):
        with get_admin_engine().begin() as db:
            db.execute(text('UPDATE maintenance_control SET admission_closed=true WHERE id=1'))
        return original(*args,**kwargs)
    monkeypatch.setattr(guest_quota,'resume_legacy',close_between_route_check_and_mutation)
    monkeypatch.setattr(amqp,'publish_once',lambda *a,**kw:pytest.fail('closed intake must not publish'))
    try:
        response=client.post(f'/api/v1/tasks/{tid}/resume',headers=b.headers)
        assert response.status_code==503,response.text
        with tenant_session(b.pid) as db:
            assert db.get(Task,uuid.UUID(tid)).status=='failed'
    finally:
        with get_admin_engine().begin() as db:
            db.execute(text('UPDATE maintenance_control SET admission_closed=false WHERE id=1'))


def test_recovered_rejected_gate_refunds_guest(guest_book,monkeypatch):
    from test_guest_admission import generate
    from myink.worker import enqueue
    from myink.worker.redis_client import get_redis,inflight_key
    from myink import guest_quota
    from myink.models.maintenance import AdmissionIntent
    from sqlalchemy import select
    b=guest_book
    get_redis().sadd(inflight_key(b.uid,b.pid),'busy')
    original=enqueue._run_gates
    def lost_rejection(*a,**kw):
        result=original(*a,**kw)
        assert result[0]==-2
        raise ConnectionError('lost response after definite gate rejection committed')
    monkeypatch.setattr(enqueue,'_run_gates',lost_rejection)
    monkeypatch.setattr(amqp,'publish_once',lambda *a,**kw:pytest.fail('rejected gate must not publish'))
    assert generate(b).status_code==503
    assert guest_quota.quota_view(b.uid,b.ip)['long']['used']==1
    handoff.replay_admissions(b.pid)
    with tenant_session(b.pid) as db:
        intent=db.scalar(select(AdmissionIntent).where(AdmissionIntent.project_id==uuid.UUID(b.pid)))
        assert intent.gate_state=='rejected'
    assert guest_quota.quota_view(b.uid,b.ip)['long']['used']==0

def test_vip_plan_confirmation_persists_same_tier(temp_project,temp_user,monkeypatch):
    from test_manual_plan import test_plan_confirm_api_validates_checkpoint_and_queues_exact_edited_version
    import myink.api.routes_tasks as routes
    original=routes.register_admission
    def register(db,message,**kwargs):
        assert kwargs['priority']==9,'VIP publication must match durable priority'
        return original(db,message,**kwargs)
    monkeypatch.setattr(routes,'register_admission',register)
    test_plan_confirm_api_validates_checkpoint_and_queues_exact_edited_version(temp_project,temp_user,monkeypatch,'vip',9)

def test_yield_does_not_erase_defer_lineage(temp_project,monkeypatch):
    from myink.maintenance import register_admission
    from myink.models import Project
    from myink.models.maintenance import QueueHandoff
    from myink.worker import consumer
    from unittest.mock import Mock
    from sqlalchemy import select
    with new_session() as db: uid=str(db.get(Project,uuid.UUID(temp_project)).user_id)
    tid=str(uuid.uuid4())
    body={'task_id':tid,'request_id':tid,'project_id':temp_project,'user_id':uid,'task_type':'batch_generate','payload':{'start':1,'size':3},'retry_count':0}
    with tenant_session(temp_project) as db: register_admission(db,body,priority=0)
    decisions=iter(['defer','yield','defer'])
    monkeypatch.setattr(consumer,'process',lambda *a,**kw:next(decisions))
    monkeypatch.setattr(consumer,'observe',lambda *a:None)
    publications=[]
    def publish(raw,destination,**kwargs):
        publications.append(dict(body=json.loads(raw),destination=destination,**kwargs))
    monkeypatch.setattr(amqp,'publish_once',publish)
    monkeypatch.setattr(amqp,'publish',lambda *a,**kw:pytest.fail('yield must retain a durable successor'))
    ch=Mock(); method=SimpleNamespace(delivery_tag=1)
    props=SimpleNamespace(priority=0)
    for index in range(3):
        consumer._on_message(ch,method,props,json.dumps(body),Mock(),'author')
        assert len(publications)==index+1
        sent=publications[-1]
        headers={'operation_id':sent['operation_id']}
        if sent['destination']=='delay':
            headers['x-death']=[{'queue':amqp.delay_queue(),'reason':'expired','original-expiration':str(sent['expiration_ms']),'exchange':amqp.exchange(),'routing-keys':['delay']}]
        props=SimpleNamespace(priority=0,message_id=tid,correlation_id=tid,expiration=None,headers=headers)
    assert [p['destination'] for p in publications]==['delay','tasks','delay']
    with tenant_session(temp_project) as db:
        rows=list(db.scalars(select(QueueHandoff).where(QueueHandoff.task_id==uuid.UUID(tid))))
        assert len(rows)==3 and all(r.state=='published' for r in rows)
        by={r.operation_id:r for r in rows}
        assert by[publications[1]['operation_id']].predecessor_id==publications[0]['operation_id']
        assert by[publications[2]['operation_id']].predecessor_id==publications[1]['operation_id']


def test_rejected_guest_compensation_is_atomic_and_idempotent(guest_book,monkeypatch):
    from test_guest_admission import generate
    from myink.worker import enqueue
    from myink.worker.redis_client import get_redis,inflight_key
    from myink import guest_quota
    from myink.models.maintenance import AdmissionIntent
    from sqlalchemy import select
    b=guest_book
    get_redis().sadd(inflight_key(b.uid,b.pid),'busy')
    original_gate=enqueue._run_gates
    def lost_rejection(*args,**kwargs):
        result=original_gate(*args,**kwargs)
        assert result[0]==-2
        raise ConnectionError('lost committed rejection')
    monkeypatch.setattr(enqueue,'_run_gates',lost_rejection)
    monkeypatch.setattr(amqp,'publish_once',lambda *a,**kw:pytest.fail('rejection must not publish'))
    assert generate(b).status_code==503
    release=guest_quota.release_in_session
    def interrupted(*args,**kwargs):
        release(*args,**kwargs)
        raise RuntimeError('after refund before commit')
    monkeypatch.setattr(guest_quota,'release_in_session',interrupted)
    with pytest.raises(RuntimeError,match='before commit'):
        handoff.replay_admissions(b.pid)
    assert guest_quota.quota_view(b.uid,b.ip)['long']['used']==1
    with tenant_session(b.pid) as db:
        intent=db.scalar(select(AdmissionIntent).where(AdmissionIntent.project_id==uuid.UUID(b.pid)))
        assert intent.gate_state=='rejected' and intent.publication_state=='pending'
    monkeypatch.setattr(guest_quota,'release_in_session',release)
    handoff.replay_admissions(b.pid)
    handoff.replay_admissions(b.pid)
    assert guest_quota.quota_view(b.uid,b.ip)['long']['used']==0
    with tenant_session(b.pid) as db:
        assert db.get(AdmissionIntent,intent.id).publication_state=='not_attempted'



@pytest.mark.parametrize('destination',['tasks','delay'])
def test_closed_maintenance_accounts_for_vip_topology(isolated_broker,temp_project,destination):
    from sqlalchemy import text
    from myink.db import get_admin_engine
    from myink.models import Project
    from myink.maintenance import register_admission,intent_outcome
    with new_session() as db: owner=str(db.get(Project,uuid.UUID(temp_project)).user_id)
    tid=str(uuid.uuid4()); epoch='merge-'+uuid.uuid4().hex
    # Retain the entire database census; other tests deliberately leave unknowns.
    with get_admin_engine().begin() as db:
        baseline_control=dict(db.execute(text('SELECT epoch,admission_closed,consumer_blocked FROM maintenance_control WHERE id=1')).mappings().one())
        db.execute(text('UPDATE maintenance_control SET epoch=:epoch,admission_closed=true,consumer_blocked=true WHERE id=1'),{'epoch':epoch})
    try:
        with tenant_session(temp_project) as db: baseline=handoff.reconcile_queue(db,epoch)
    finally:
        with get_admin_engine().begin() as db:
            db.execute(text('UPDATE maintenance_control SET epoch=:epoch,admission_closed=:admission_closed,consumer_blocked=:consumer_blocked WHERE id=1'),baseline_control)
    body=dict(task_id=tid,request_id=tid,project_id=temp_project,user_id=owner,task_type='chapter_generate',payload={'seq':1},retry_count=0)
    with tenant_session(temp_project) as db:
        intent=register_admission(db,body,priority=9)
        if destination=='delay':
            handoff.record_handoff(db,body,'delay','census:'+tid,priority=9,expiration_ms=5000)
    if destination=='tasks':
        amqp.publish_once(json.dumps(body),'tasks',priority=9)
    else:
        assert handoff.publish_handoff('census:'+tid)['state']=='published'
    intent_outcome(intent,temp_project,publication_state='published')
    with get_admin_engine().begin() as db:
        old=dict(db.execute(text('SELECT epoch,admission_closed,consumer_blocked FROM maintenance_control WHERE id=1')).mappings().one())
        db.execute(text('UPDATE maintenance_control SET epoch=:epoch,admission_closed=true,consumer_blocked=true WHERE id=1'),{'epoch':epoch})
    try:
        with tenant_session(temp_project) as db: result=handoff.reconcile_queue(db,epoch)
        assert result['unknown']==baseline['unknown'],(baseline,result)
        assert result['verified']==(baseline['unknown']==0)
        assert result['queue_messages']==1 and tid in result['planned_task_ids']
    finally:
        with get_admin_engine().begin() as db:
            db.execute(text('UPDATE maintenance_control SET epoch=:epoch,admission_closed=:admission_closed,consumer_blocked=:consumer_blocked WHERE id=1'),old)


def test_uncertain_outbox_cannot_refund_guest(guest_book,monkeypatch):
    from test_guest_admission import generate
    from myink import guest_quota
    from myink.models.maintenance import AdmissionIntent
    from sqlalchemy import select
    b=guest_book;sent=[]
    monkeypatch.setattr(amqp,'publish_once',lambda raw,*a,**kw:sent.append(json.loads(raw)))
    assert generate(b).status_code==202
    with tenant_session(b.pid) as db:
        intent=db.scalar(select(AdmissionIntent).where(AdmissionIntent.project_id==uuid.UUID(b.pid)))
        handoff.record_handoff(db,sent[0],'tasks','uncertain:'+str(intent.id),priority=intent.priority)
        intent.gate_state='rejected';intent.publication_state='pending'
    monkeypatch.setattr(amqp,'publish_once',lambda *a,**kw:pytest.fail('possible delivery must not be reclassified'))
    handoff.replay_admissions(b.pid)
    assert guest_quota.quota_view(b.uid,b.ip)['long']['used']==1
    with tenant_session(b.pid) as db:
        assert db.get(AdmissionIntent,intent.id).publication_state=='pending'
