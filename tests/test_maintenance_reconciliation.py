"""Reconciliation retains unfinished accepted work and private durable authority."""
import uuid
import pytest
from sqlalchemy import select
from myink.db import ensure_maintenance_schema,new_session,tenant_session
from myink.models import Project
from myink.maintenance import register_admission
from myink.worker.redis_client import get_redis

pytestmark=pytest.mark.pi_lab

def test_unmaterialized_and_delayed_tasks_accounted(temp_project):
    from myink.worker import handoff
    ensure_maintenance_schema()
    with new_session() as db: uid=str(db.get(Project,uuid.UUID(temp_project)).user_id)
    body={"task_id":str(uuid.uuid4()),"task_type":"chapter_generate","project_id":temp_project,"user_id":uid,"request_id":str(uuid.uuid4()),"payload":{"seq":1},"retry_count":0}
    with tenant_session(temp_project) as db: register_admission(db,body,priority=3)
    with tenant_session(temp_project) as db:
        from myink.maintenance import maintenance_view
        epoch=maintenance_view(db)["epoch"]
        receipt=handoff.reconcile_queue(db,epoch)
    assert body["task_id"] in receipt["planned_task_ids"]
    assert receipt["verified"] is False and receipt["unknown"]>0

from test_maintenance_pause import pause_lab,confirmed_graph
from test_task_budget import budget_task

def test_redis_loss_does_not_lose_pause_receipt(pause_lab,budget_task):
    from myink.worker import handoff
    from myink.task_budget import ensure_task_budget
    from myink.models.maintenance import MaintenanceExecution
    from myink.models.task_budget import TaskBudgetCall
    from myink.worker.redis_client import sse_key,lock_key,book_key,inflight_key
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{"max_requests":20})
    graph,receipt=confirmed_graph(pid,tid)
    with tenant_session(pid) as db:
        persisted_before=db.get(MaintenanceExecution,uuid.UUID(tid)).receipt
    r=get_redis();keys=[sse_key(tid),lock_key(tid),book_key(pid),inflight_key(uid,pid),"queue:task-owner:"+tid]
    for key in keys:r.delete(key)
    with tenant_session(pid) as db:
        actual=db.get(MaintenanceExecution,uuid.UUID(tid))
        assert actual.receipt==persisted_before and actual.state=="paused"
        effects=list(db.scalars(select(TaskBudgetCall).where(TaskBudgetCall.task_id==uuid.UUID(tid),TaskBudgetCall.operation_key.like("effect:%"))))
        assert len(effects)==1
        observed=handoff.reconcile_queue(db,"b9-test")
    assert observed["pause_receipts"]==[persisted_before] and observed["verified"] is False
    assert receipt["checkpoints"][0]["checkpoint_id"] and receipt["effects"][0]["id"]==str(effects[0].id)


def _grant_application_fixture():
    from sqlalchemy import text
    from myink.db import get_admin_engine
    with get_admin_engine().begin() as db:
        db.execute(text("DO $$ BEGIN CREATE ROLE myink_app NOLOGIN NOSUPERUSER NOBYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$"))
    ensure_maintenance_schema()
    with get_admin_engine().begin() as db:
        db.execute(text('GRANT USAGE ON SCHEMA public TO myink_app'))
        db.execute(text('GRANT SELECT(id) ON projects TO myink_app'))
        db.execute(text('GRANT SELECT ON tasks,task_budgets,task_budget_calls TO myink_app'))
        db.execute(text('GRANT UPDATE(status,error,updated_at) ON tasks TO myink_app'))
        db.execute(text('GRANT UPDATE(runtime_used_ms) ON task_budgets TO myink_app'))
        db.execute(text('GRANT SELECT(thread_id,checkpoint_id) ON checkpoints TO myink_app'))


from contextlib import contextmanager
@contextmanager
def _bridge_session(pid):
    from sqlalchemy import text
    with tenant_session(pid) as db:
        db.execute(text('SET LOCAL ROLE myink_app'))
        yield db


@pytest.fixture
def resume_case(pause_lab,budget_task):
    from myink.task_budget import ensure_task_budget
    from myink.models import Task
    _grant_application_fixture()
    tid,pid,uid=budget_task
    snapshot={"max_requests":20}
    body={"task_id":tid,"project_id":pid,"user_id":uid,"task_type":"chapter_generate","payload":{"seq":1},"request_id":str(uuid.uuid4()),"retry_count":0,"task_budget":snapshot}
    with tenant_session(pid) as db:
        task=db.get(Task,uuid.UUID(tid));task.payload={"seq":1,"_task_budget":snapshot}
        intent=register_admission(db,body,priority=7)
    ensure_task_budget(tid,pid,uid,snapshot)
    graph,receipt=confirmed_graph(pid,tid)
    return body,intent,graph,receipt


def test_resume_bridge_records_original_outbox_atomically(resume_case):
    from myink.models.maintenance import QueueHandoff
    from myink.worker import handoff
    body,intent,graph,proof=resume_case;pid=body['project_id'];tid=body['task_id']
    with _bridge_session(pid) as db:resumed=handoff.resume_maintenance_handoffs(db,"b9-test",9)
    assert resumed
    with tenant_session(pid) as db:
        row=db.scalar(select(QueueHandoff).where(QueueHandoff.task_id==uuid.UUID(tid)))
        assert row is not None,"resume committed runnable Task without its durable original-linked outbox"
        assert row.rebuild_payload=={**body,'task_type':'chapter_resume'} and row.admission_id==intent
        assert row.authority['checkpoints']==db.get(__import__('myink.models.maintenance',fromlist=['MaintenanceExecution']).MaintenanceExecution,uuid.UUID(tid)).receipt['checkpoints']


def test_resume_bridge_failure_rolls_back_actual_pause(resume_case,monkeypatch):
    from myink.worker import handoff
    from myink.models import Task
    from myink.models.maintenance import QueueHandoff,MaintenanceExecution
    body,intent,graph,proof=resume_case;pid=body['project_id'];tid=uuid.UUID(body['task_id'])
    def lost_outbox(*a,**kw):raise ConnectionError('outbox transaction fault')
    monkeypatch.setattr(handoff,'record_handoff',lost_outbox)
    with pytest.raises(ConnectionError):
        with _bridge_session(pid) as db:handoff.resume_maintenance_handoffs(db,'b9-test',9)
    with tenant_session(pid) as db:
        assert db.get(Task,tid).status=='paused' and db.get(MaintenanceExecution,tid).state=='paused'
        assert not db.scalar(select(QueueHandoff).where(QueueHandoff.task_id==tid))


@pytest.mark.parametrize('change',['paused','cancelled','awaiting_plan','awaiting_review','budget','deployment','images','execution'])
def test_resume_bridge_preserves_stronger_wait_and_identity(resume_case,change):
    from sqlalchemy import text
    from myink.db import get_admin_engine
    from myink.worker import handoff
    from myink.models import Task
    from myink.models.maintenance import MaintenanceExecution,QueueHandoff
    from myink.models.task_budget import TaskBudget
    body,intent,graph,proof=resume_case;pid=body['project_id'];tid=uuid.UUID(body['task_id'])
    with tenant_session(pid) as db:
        if change in ('paused','cancelled','awaiting_plan','awaiting_review'):
            task=db.get(Task,tid);task.status=change;task.error='stronger user wait'
        elif change=='budget':db.get(TaskBudget,tid).pause_reason='request_limit'
        elif change=='execution':db.get(MaintenanceExecution,tid).execution_generation+=1
        else:
            execution=db.get(MaintenanceExecution,tid)
            execution.receipt={**execution.receipt,('deployment_id' if change=='deployment' else 'image_ids'):('other' if change=='deployment' else {'worker':'other'})}
    with _bridge_session(pid) as db:
        assert handoff.resume_maintenance_handoffs(db,'b9-test',9)==[]
        assert not db.scalar(select(QueueHandoff).where(QueueHandoff.task_id==tid))


def test_resume_bridge_real_broker_duplicate_no_charge_effect_once(resume_case,monkeypatch):
    import json
    from myink.worker import handoff,amqp,consumer,processor
    from myink.models import Chapter,Fact,Task
    from myink.models.task_budget import TaskBudgetCall,TaskBudget
    body,intent,graph,proof=resume_case;pid=body['project_id'];tid=uuid.UUID(body['task_id'])
    r=get_redis();key='b10-resume-quota:'+body['task_id'];r.set(key,2)
    try:
        with _bridge_session(pid) as db:first=handoff.resume_maintenance_handoffs(db,'b9-test',9)
        with _bridge_session(pid) as db:
            second=handoff.resume_maintenance_handoffs(db,'b9-test',9)
            budget=db.get(TaskBudget,tid);budget_before=(budget.requests_used,budget.cost_used_micros,budget.runtime_used_ms)
        assert len(first)==len(second)==1 and first[0]['operation_id']==second[0]['operation_id']
        assert handoff.publish_handoff(first[0]['operation_id'])['state']=='published'
        assert handoff.publish_handoff(second[0]['operation_id'])['state']=='published'
        monkeypatch.setattr(processor,'get_graphs',lambda:(graph,graph))
        with amqp.connect() as connection:
            channel=connection.channel();amqp.declare_topology(channel)
            count=channel.queue_declare(amqp.main_queue(),passive=True).method.message_count
            tags=[];own=[]
            try:
                for _ in range(count):
                    method,properties,raw=channel.basic_get(amqp.main_queue(),auto_ack=False)
                    if method is None:break
                    message=json.loads(raw)
                    if message.get('task_id')==body['task_id']:own.append((method,properties,raw))
                    else:tags.append(method.delivery_tag)
                assert len(own)==1
                method,properties,raw=own[0]
                assert properties.message_id==body['request_id'] and properties.priority==7
                consumer._on_message(channel,method,properties,raw,r,'actual-b10-resume')
            finally:
                for tag in tags:channel.basic_nack(tag,requeue=True)
        with tenant_session(pid) as db:
            assert db.get(Task,tid).status=='done'
            assert len(list(db.scalars(select(Chapter).where(Chapter.project_id==uuid.UUID(pid)))))==1
            assert len(list(db.scalars(select(Fact).where(Fact.project_id==uuid.UUID(pid)))))==1
            assert len(list(db.scalars(select(TaskBudgetCall).where(TaskBudgetCall.task_id==tid,TaskBudgetCall.operation_key.like('effect:%')))))==1
            budget=db.get(TaskBudget,tid);assert budget.requests_used==budget_before[0] and budget.cost_used_micros==budget_before[1]
        assert int(r.get(key))==2
    finally:r.delete(key)


def test_actual_fresh_census_covers_accepted_unmaterialized(temp_project):
    import os,json
    from sqlalchemy import text
    from myink.db import get_admin_engine
    from myink.worker import handoff,amqp
    from myink.maintenance import intent_outcome
    from ops.pi.lab.verify import verify_test_environment
    verify_test_environment()
    assert os.environ.get('B10_CENSUS_DESCRIPTOR')
    with new_session() as db:uid=str(db.get(Project,uuid.UUID(temp_project)).user_id)
    body={"task_id":str(uuid.uuid4()),"task_type":"chapter_generate","project_id":temp_project,"user_id":uid,"payload":{"seq":1},"request_id":str(uuid.uuid4()),"retry_count":0}
    with tenant_session(temp_project) as db:intent=register_admission(db,body,priority=7)
    amqp.publish_once(json.dumps(body),'tasks',priority=7)
    intent_outcome(intent,temp_project,publication_state='published')
    with get_admin_engine().begin() as db:db.execute(text("UPDATE maintenance_control SET admission_closed=true,consumer_blocked=true WHERE id=1"))
    try:
        with new_session() as db:
            from myink.maintenance import maintenance_view
            epoch=maintenance_view(db)['epoch']
            proof=handoff.reconcile_queue(db,epoch)
        assert proof['verified'] and proof['unknown']==0 and body['task_id'] in proof['planned_task_ids']
        assert proof['queue_messages']==1
        deliveries,unknown=handoff._queue_census()
        assert unknown==0 and [message for queue,message,metadata in deliveries]==[body]
        from pathlib import Path
        operation=json.loads(Path(os.environ['B10_CENSUS_DESCRIPTOR']).read_text())['operation_id']
        Path('/mnt/e/tools/myink-pi/evidence/b10-census-'+operation+'.json').write_text(json.dumps({k:v for k,v in proof.items() if k!='pause_receipts'},indent=2))
    finally:
        with get_admin_engine().begin() as db:db.execute(text("UPDATE maintenance_control SET admission_closed=false,consumer_blocked=false WHERE id=1"))


def test_resume_bridge_trusted_adapter_uses_actual_application_role(resume_case,monkeypatch,tmp_path):
    from sqlalchemy import create_engine,event,text
    from sqlalchemy.orm import sessionmaker
    import myink.db as database
    from myink.config import settings
    from myink.models.maintenance import QueueHandoff
    from myink.maintenance import maintenance_view
    from ops.pi.maintenance import resume_queue
    from ops.pi.contracts import Identity
    from ops.pi.ledger import Ledger
    body,intent,graph,proof=resume_case
    with database.get_admin_engine().begin() as db:
        db.execute(text('GRANT USAGE ON SCHEMA public TO myink_app'))
        db.execute(text('GRANT SELECT(id) ON projects TO myink_app'))
        db.execute(text('GRANT SELECT ON tasks,task_budgets,task_budget_calls TO myink_app'))
        db.execute(text('GRANT UPDATE(status,error,updated_at) ON tasks TO myink_app'))
        db.execute(text('GRANT UPDATE(runtime_used_ms) ON task_budgets TO myink_app'))
        db.execute(text('GRANT SELECT(thread_id,checkpoint_id) ON checkpoints TO myink_app'))
        control=maintenance_view(db)
    identity=Identity(control['deployment_id'],control['generation'],control['owner'],control['image_ids'])
    engine=create_engine(settings.database_url)
    @event.listens_for(engine,'connect')
    def actual_role(connection,record):
        with connection.cursor() as cursor:cursor.execute('SET ROLE myink_app')
        connection.commit()
    try:
        with engine.connect() as db:
            assert db.execute(text("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()==('myink_app',False,False)
        @event.listens_for(engine,'handle_error')
        def private_denial(context):
            import os,json
            from pathlib import Path
            operation=json.loads(Path(os.environ['B10_CENSUS_DESCRIPTOR']).read_text())['operation_id']
            Path('/mnt/e/tools/myink-pi/evidence/b10-role-denial-'+operation+'.txt').write_text(str(context.original_exception))
        # Exit this scope before dependent fixture teardown; ordinary cleanup retains its own role.
        with monkeypatch.context() as scoped:
            scoped.setattr(database,'get_engine',lambda:engine)
            scoped.setattr(database,'_SessionLocal',sessionmaker(bind=engine,expire_on_commit=False,autoflush=False))
            receipt=resume_queue(Ledger(tmp_path/'actual-app-resume.sqlite'),identity,'b9-test')
            assert receipt.status=='done' and receipt.evidence['resumed']>=1,receipt.evidence
            with database.tenant_session(body['project_id']) as db:
                row=db.scalar(select(QueueHandoff).where(QueueHandoff.task_id==uuid.UUID(body['task_id'])))
                assert row and row.state=='published' and row.admission_id==intent
            with engine.connect() as db:
                assert db.scalar(text('SELECT count(*) FROM queue_handoffs'))==0
    finally:engine.dispose()


@pytest.mark.parametrize('change',['operation','priority','expiration','message','correlation','dlq'])
def test_review_census_invalid_predecessor_blocks_closed_barrier(temp_project,change):
    import json
    from sqlalchemy import text
    from myink.db import get_admin_engine
    from myink.worker import handoff,amqp
    from myink.maintenance import intent_outcome,maintenance_view
    with new_session() as db:uid=str(db.get(Project,uuid.UUID(temp_project)).user_id)
    body={"task_id":str(uuid.uuid4()),"task_type":"chapter_generate","project_id":temp_project,"user_id":uid,"payload":{"seq":1},"request_id":str(uuid.uuid4()),"retry_count":0}
    with tenant_session(temp_project) as db:intent=register_admission(db,body,priority=7)
    amqp.publish_once(json.dumps(body),'tasks',priority=7)
    intent_outcome(intent,temp_project,publication_state='published')
    with get_admin_engine().begin() as db:db.execute(text("UPDATE maintenance_control SET admission_closed=true,consumer_blocked=true WHERE id=1"))
    try:
        with new_session() as db:baseline=handoff.reconcile_queue(db,maintenance_view(db)['epoch'])
        # Add a duplicate original body with conflicting real broker metadata.
        # Full retained global census/denominator stays intact, not filtered.
        import pika
        properties=pika.BasicProperties(delivery_mode=2,priority=6 if change=='priority' else 7,
            message_id=str(uuid.uuid4()) if change=='message' else body['request_id'],
            correlation_id=str(uuid.uuid4()) if change=='correlation' else body['task_id'],
            expiration='50000' if change=='expiration' else None,
            headers={'operation_id':'unknown-predecessor:'+body['task_id']} if change=='operation' else None)
        with amqp.connect() as connection:
            channel=connection.channel();amqp.declare_topology(channel);channel.confirm_delivery()
            channel.basic_publish(exchange=amqp.dlx_exchange() if change=='dlq' else amqp.exchange(),
                routing_key='dlq' if change=='dlq' else 'tasks',body=json.dumps(body),properties=properties,mandatory=True)
        with new_session() as db:result=handoff.reconcile_queue(db,maintenance_view(db)['epoch'])
        assert result['unknown']>=baseline['unknown']+1,"invalid actual broker predecessor contributed no unknown"
        actual,uncertain=handoff._queue_census()
        assert uncertain==0 and len([row for row in actual if row[1]==body])==2
    finally:
        with get_admin_engine().begin() as db:db.execute(text("UPDATE maintenance_control SET admission_closed=false,consumer_blocked=false WHERE id=1"))


@pytest.mark.parametrize('field',['control','execution_deployment','receipt_deployment','execution'])
def test_review_pause_generation_only_change_blocks_census(resume_case,monkeypatch,field):
    from sqlalchemy import text
    from myink.db import get_admin_engine
    from myink.worker import handoff
    from myink.maintenance import intent_outcome
    from myink.models.maintenance import MaintenanceExecution
    body,intent,graph,proof=resume_case;pid=body['project_id'];tid=body['task_id']
    intent_outcome(intent,pid,publication_state='published')
    actual=handoff._queue_census()
    monkeypatch.setattr(handoff,'_queue_census',lambda:actual)
    with get_admin_engine().begin() as db:db.execute(text("UPDATE maintenance_control SET admission_closed=true,consumer_blocked=true WHERE id=1"))
    try:
        with new_session() as db:baseline=handoff.reconcile_queue(db,'b9-test')
        if field=='control':
            with get_admin_engine().begin() as db:db.execute(text("UPDATE maintenance_control SET generation=generation+1 WHERE id=1"))
        else:
            with tenant_session(pid) as db:
                row=db.get(MaintenanceExecution,uuid.UUID(tid))
                if field=='execution_deployment':row.deployment_generation+=1
                elif field=='execution':row.execution_generation+=1
                else:row.receipt={**row.receipt,'deployment_generation':row.receipt['deployment_generation']+1}
        with new_session() as db:result=handoff.reconcile_queue(db,'b9-test')
        assert result['unknown']>=baseline['unknown']+1 and result['verified'] is False,"stale pause generation contributed no unknown"
    finally:
        with get_admin_engine().begin() as db:db.execute(text("UPDATE maintenance_control SET generation=9,admission_closed=false,consumer_blocked=false WHERE id=1"))
