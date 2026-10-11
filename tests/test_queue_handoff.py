"""Owned real-service queue handoff regressions; no paid providers."""
import json
import uuid
import pytest
from sqlalchemy import select
from myink.db import ensure_maintenance_schema, new_session, tenant_session
from myink.models import Project
from myink.worker import consumer

pytestmark = pytest.mark.pi_lab

@pytest.fixture
def admitted(temp_project):
    from myink.maintenance import register_admission
    ensure_maintenance_schema()
    with new_session() as db:
        uid=str(db.get(Project, uuid.UUID(temp_project)).user_id)
    body={"task_id":str(uuid.uuid4()),"task_type":"chapter_generate","project_id":temp_project,"user_id":uid,"payload":{"seq":1},"request_id":str(uuid.uuid4()),"retry_count":0,"task_budget":{"max_requests":20}}
    with tenant_session(temp_project) as db:
        register_admission(db,body,priority=7)
    return body

def test_callback_commits_outbox_before_ack(admitted,monkeypatch):
    from sqlalchemy import inspect,text
    from myink.db import get_admin_engine
    from types import SimpleNamespace
    from myink.worker.redis_client import get_redis
    body=admitted
    monkeypatch.setattr(consumer,"may_consume",lambda:True)
    monkeypatch.setattr(consumer,"valid_task_owner",lambda body:True)
    monkeypatch.setattr(consumer,"process",lambda *a,**k:"retry")
    monkeypatch.setattr(consumer,"observe",lambda *a,**k:None)
    def ack(tag):
        engine=get_admin_engine()
        assert inspect(engine).has_table("queue_handoffs"), "ACK lost the original without a durable handoff"
        with engine.connect() as db:
            row=db.execute(text("SELECT task_id,message_id,state FROM queue_handoffs WHERE task_id=:tid"),{"tid":uuid.UUID(body["task_id"])}).one_or_none()
        assert row is not None and str(row.task_id)==body["task_id"] and row.message_id==body["request_id"]
        raise ConnectionError("simulated interruption immediately before actual ACK")
    ch=SimpleNamespace(basic_ack=ack)
    with pytest.raises(ConnectionError):
        consumer._on_message(ch,SimpleNamespace(delivery_tag=1),SimpleNamespace(priority=7),json.dumps(body).encode(),get_redis(),"test")

def test_ambiguous_publish_retains_outbox(admitted,monkeypatch):
    from myink.models.maintenance import QueueHandoff
    from myink.worker import handoff
    body=admitted; body["retry_count"]=1
    operation="ack-publish:"+body["task_id"]
    with tenant_session(body["project_id"]) as db:
        handoff.record_handoff(db,body,"delay",operation,expiration_ms=5000)
    def interrupted(*a,**k): raise ConnectionError("lost confirm")
    monkeypatch.setattr(handoff.amqp,"publish_once",interrupted)
    receipt=handoff.publish_handoff(operation)
    assert receipt["state"]=="unknown"
    with tenant_session(body["project_id"]) as db:
        row=db.scalar(select(QueueHandoff).where(QueueHandoff.operation_id==operation))
        assert row.state=="unknown" and row.rebuild_payload==body

def test_repeated_record_preserves_operation(admitted):
    from myink.worker import handoff
    from myink.models.maintenance import QueueHandoff
    body=admitted;operation="confirm-receipt:"+body["task_id"]
    with tenant_session(body["project_id"]) as db:
        first=handoff.record_handoff(db,body,"delay",operation,expiration_ms=5000)
    with tenant_session(body["project_id"]) as db:
        second=handoff.record_handoff(db,body,"delay",operation,expiration_ms=5000)
    assert first["operation_id"]==second["operation_id"]
    with tenant_session(body["project_id"]) as db:
        rows=db.scalars(select(QueueHandoff).where(QueueHandoff.operation_id==operation)).all()
        assert len(rows)==1 and rows[0].body_hash==first["body_hash"]


def test_missing_intent_is_unknown_not_execution(temp_project):
    from myink.worker.processor import valid_task_owner
    from myink.worker.handoff import QueueAuthorityUnknown
    with new_session() as db: uid=str(db.get(Project,uuid.UUID(temp_project)).user_id)
    body={"task_id":str(uuid.uuid4()),"project_id":temp_project,"user_id":uid,"task_type":"chapter_generate","payload":{"seq":1},"request_id":str(uuid.uuid4())}
    with pytest.raises(QueueAuthorityUnknown):valid_task_owner(body)


def test_gate_duplicate_does_not_charge_twice(admitted):
    from myink.worker import enqueue as enq
    from myink.worker.redis_client import get_redis
    body=admitted;r=get_redis();prefix="b10-gate:"+body["task_id"]
    keys=[prefix+":"+str(i) for i in range(6)]
    try:
        first=enq._run_gates(r,keys,task_id=body["task_id"],quota_n=2,cost_est=0,project_id=body["project_id"],platform_chapter_max=10)
        second=enq._run_gates(r,keys,task_id=body["task_id"],quota_n=2,cost_est=0,project_id=body["project_id"],platform_chapter_max=10)
        assert first==second and int(r.get(keys[0]))==2 and int(r.get(keys[5]))==2
        enq._compensate(r,keys,task_id=body["task_id"],quota_n=2,platform_chapter_max=10)
        enq._compensate(r,keys,task_id=body["task_id"],quota_n=2,platform_chapter_max=10)
        assert int(r.get(keys[0]))==0 and int(r.get(keys[5]))==0
    finally:r.delete(*keys,"rate:intent:"+body["task_id"])


def test_crash_before_ack_preserves_original(admitted):
    _actual_rabbit_process_crash_handoff(admitted,"before-ack")

@pytest.mark.parametrize("boundary",["outbox-before-ack","after-ack"])
def test_ack_then_publish_failure_has_outbox(admitted,boundary):
    _actual_rabbit_process_crash_handoff(admitted,boundary)

def test_confirm_then_receipt_failure_deduplicates_effect(admitted):
    _actual_rabbit_process_crash_handoff(admitted,"confirm-before-receipt")

def _actual_rabbit_process_crash_handoff(admitted,boundary):
    import os,sys,subprocess,time
    from pathlib import Path
    from myink.maintenance import intent_outcome
    from myink.worker import amqp,handoff
    from myink.worker.redis_client import get_redis
    from myink.models import Task,Chapter,Event
    from myink.models.maintenance import AdmissionIntent,QueueHandoff
    from myink.models.task_budget import TaskBudgetCall
    from ops.pi.lab.verify import verify_test_environment
    verify_test_environment()
    body=admitted;r=get_redis();key="b10:boundary:"+body["task_id"]
    # This is a genuine original confirmed delivery, not a fixture stand-in.
    amqp.publish_once(json.dumps(body),amqp.KEY_TASKS,priority=7)
    with tenant_session(body["project_id"]) as db:
        intent=db.scalar(select(AdmissionIntent).where(AdmissionIntent.task_id==uuid.UUID(body["task_id"])))
        intent_id=intent.id
    intent_outcome(intent_id,body["project_id"],publication_state="published")
    processes=[];logs=[]
    def start(mode=None):
        env=dict(os.environ)
        if mode:env.update(B10_BOUNDARY=mode,B10_TASK=body["task_id"])
        log=Path(os.environ["TMPDIR"])/("b10-"+body["task_id"]+"-"+str(len(processes))+".log")
        f=log.open("w");logs.append((f,log))
        process=subprocess.Popen([sys.executable,str(Path(__file__).with_name("_mp_worker.py"))],cwd=Path(__file__).parents[1],env=env,stdout=f,stderr=f)
        processes.append(process);return process
    try:
        process=start(boundary);deadline=time.monotonic()+60
        while not r.exists(key) and time.monotonic()<deadline:
            if process.poll() is not None:pytest.fail(logs[-1][1].read_text())
            time.sleep(.1)
        assert r.exists(key), "actual child failed to reach boundary"
        proof=json.loads(r.get(key));assert proof=={"pid":process.pid,"stage":boundary}
        with tenant_session(body["project_id"]) as db:
            task=db.get(Task,uuid.UUID(body["task_id"]));assert task.status=="done"
            memory_before=len(list(db.scalars(select(Event).where(Event.project_id==uuid.UUID(body["project_id"])))))
            assert memory_before==1
            rows=list(db.scalars(select(QueueHandoff).where(QueueHandoff.task_id==task.id)))
            if boundary!="before-ack":
                assert len(rows)==1 and rows[0].state in {"pending","unknown"}
                original_operation=rows[0].operation_id
                assert rows[0].rebuild_payload["retry_count"]==1 and rows[0].priority==7 and rows[0].expiration_ms==1000
        process.kill();process.wait(timeout=10);assert process.returncode<0
        # Read the genuine broker after exact child death; no delivery-tag identity.
        with amqp.connect() as connection:
            channel=connection.channel()
            queued=channel.queue_declare(amqp.main_queue(),passive=True).method.message_count
        if boundary=="before-ack":assert queued>=1
        replacement=start();deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            with tenant_session(body["project_id"]) as db:
                rows=list(db.scalars(select(QueueHandoff).where(QueueHandoff.task_id==uuid.UUID(body["task_id"]))))
                published=all(row.state=="published" for row in rows)
            with amqp.connect() as connection:
                channel=connection.channel();main_empty=channel.queue_declare(amqp.main_queue(),passive=True).method.message_count==0
            deliveries,uncertain=handoff._queue_census()
            empty=main_empty and not any(message.get("task_id")==body["task_id"] for queue,message in deliveries)
            if published and empty:break
            time.sleep(.2)
        assert published and empty
        replacement.terminate();replacement.wait(timeout=10)
        deliveries,uncertain=handoff._queue_census()
        assert uncertain==0 and not any(message.get("task_id")==body["task_id"] for queue,message in deliveries)
        with tenant_session(body["project_id"]) as db:
            assert len(list(db.scalars(select(Chapter).where(Chapter.project_id==uuid.UUID(body["project_id"])))))==1
            effects=list(db.scalars(select(TaskBudgetCall).where(TaskBudgetCall.task_id==uuid.UUID(body["task_id"]),TaskBudgetCall.operation_key.like("effect:%"))))
            assert len(effects)==1
            assert len(list(db.scalars(select(Event).where(Event.project_id==uuid.UUID(body["project_id"])))))==memory_before
            if boundary!="before-ack":
                row=db.get(QueueHandoff,original_operation)
                assert row.message_id==body["request_id"] and str(row.task_id)==body["task_id"]
        evidence={"boundary":boundary,"task_id":body["task_id"],"message_id":body["request_id"],"child_pid":process.pid,"replacement_pid":replacement.pid,"original_broker_count":queued,"effects":len(effects),"memory_rows":memory_before,"original_operation":original_operation if boundary!="before-ack" else None}
        Path("/mnt/e/tools/myink-pi/evidence/b10-case-"+body["task_id"]+".json").write_text(json.dumps(evidence,indent=2))
        print(json.dumps(evidence))
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        for f,log in logs:f.close()
        r.delete(key)


@pytest.mark.parametrize("change",["payload","type","paused"])
def test_matching_legacy_identity_cannot_be_forged(temp_project,change):
    from myink.models import Task
    from myink.worker.processor import valid_task_owner
    from myink.worker.handoff import QueueAuthorityUnknown
    with new_session() as db: uid=str(db.get(Project,uuid.UUID(temp_project)).user_id)
    tid=uuid.uuid4();body={"task_id":str(tid),"task_type":"chapter_generate","project_id":temp_project,"user_id":uid,"payload":{"seq":1}}
    with tenant_session(temp_project) as db:db.add(Task(id=tid,project_id=uuid.UUID(temp_project),task_type="chapter_generate",status="queued",payload={"seq":1}))
    assert valid_task_owner(body) is True
    if change=="payload":body["payload"]={"seq":2}
    if change=="type":body["task_type"]="batch_resume"
    if change=="paused":
        with tenant_session(temp_project) as db:task=db.get(Task,tid);task.status="paused";task.error="user paused"
    with pytest.raises(QueueAuthorityUnknown):valid_task_owner(body)


def test_actual_private_handoff_roles(admitted):
    from sqlalchemy import text
    from myink.db import get_admin_engine,ensure_maintenance_schema
    from myink.worker.handoff import record_handoff
    engine=get_admin_engine()
    with engine.begin() as db:
        for role in ("myink_app","myink_report"):
            db.execute(text(f"DO $$ BEGIN CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$"))
        db.execute(text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO myink_report"))
    ensure_maintenance_schema()
    with tenant_session(admitted["project_id"]) as db:record_handoff(db,admitted,"delay","role:"+admitted["task_id"],expiration_ms=5000)
    for role in ("myink_report","myink_maintenance_stats","myink_maintenance_control"):
        with engine.connect() as db:
            db.execute(text(f"SET ROLE {role}"))
            with pytest.raises(Exception):db.execute(text("SELECT rebuild_payload FROM public.queue_handoffs"))
            db.rollback()
    with engine.begin() as db:
        db.execute(text("SET LOCAL ROLE myink_maintenance_stats"))
        assert db.scalar(text("SELECT count(*) FROM public.maintenance_handoff_counts"))>0
    with engine.begin() as db:
        db.execute(text("SET LOCAL ROLE myink_app"))
        assert not db.scalar(text("SELECT has_column_privilege(current_user,'queue_handoffs','rebuild_payload','UPDATE')"))
        assert db.scalar(text("SELECT count(*) FROM queue_handoffs"))==0
        db.execute(text("SELECT set_config('app.tenant_id',:pid,true)"),{"pid":admitted["project_id"]})
        assert db.scalar(text("SELECT count(*) FROM queue_handoffs"))>=1


def test_redis_marker_loss_is_unknown_not_new_charge(admitted):
    from myink.worker import enqueue as enq
    from myink.worker.redis_client import get_redis
    body=admitted;r=get_redis();keys=["b10-loss:"+body["task_id"]+":"+str(i) for i in range(6)]
    try:
        assert enq._run_gates(r,keys,task_id=body["task_id"],quota_n=2,cost_est=0,project_id=body["project_id"])[0]==1
        r.delete("rate:intent:"+body["task_id"],keys[0],keys[1],keys[3])
        result=enq._run_gates(r,keys,task_id=body["task_id"],quota_n=2,cost_est=0,project_id=body["project_id"],fresh=False)
        assert result==(-6,"GATE_UNKNOWN") and r.get(keys[0]) is None
        assert enq._compensate(r,keys,task_id=body["task_id"],quota_n=2) is False
        assert r.get(keys[0]) is None
    finally:r.delete(*keys,"rate:intent:"+body["task_id"])


@pytest.mark.parametrize("boundary",["intent-before-gate","gate-before-receipt","compensate-before-receipt","intake-confirm-before-receipt"])
def test_actual_intake_pg_redis_rabbit_crashes(temp_project,boundary):
    import os,sys,subprocess,time
    from pathlib import Path
    from myink.worker.handoff import reconcile_admission_gate,replay_admissions
    from myink.models.maintenance import AdmissionIntent,QueueHandoff
    from myink.models import Task,Chapter
    from myink.worker.redis_client import get_redis
    from ops.pi.lab.verify import verify_test_environment
    verify_test_environment()
    with new_session() as db:uid=str(db.get(Project,uuid.UUID(temp_project)).user_id)
    r=get_redis();key="b10:intake:"+temp_project;processes=[];logs=[];inputs={};marker=None
    def start(mode=None):
        env=dict(os.environ)
        if mode:env.update(B10_INTAKE=mode,B10_PROJECT=temp_project,B10_USER=uid)
        log=Path(os.environ["TMPDIR"])/("b10-intake-"+temp_project+"-"+str(len(processes))+".log")
        f=log.open("w");logs.append((f,log))
        process=subprocess.Popen([sys.executable,str(Path(__file__).with_name("_mp_worker.py"))],cwd=Path(__file__).parents[1],env=env,stdout=f,stderr=f)
        processes.append(process);return process
    try:
        process=start(boundary);deadline=time.monotonic()+45
        while not r.exists(key) and time.monotonic()<deadline:
            if process.poll() is not None:pytest.fail(logs[-1][1].read_text())
            time.sleep(.1)
        assert r.exists(key)
        proof=json.loads(r.get(key));assert proof["pid"]==process.pid and proof["stage"]==boundary
        tid=proof["task_id"]
        with tenant_session(temp_project) as db:
            intent=db.scalar(select(AdmissionIntent).where(AdmissionIntent.task_id==uuid.UUID(tid)))
            intent_id=intent.id;inputs=dict(intent.quota_inputs);original_hash=intent.payload_hash
            assert inputs["date"] in inputs["keys"][0] and intent.rebuild_payload["task_id"]==tid
            assert intent.gate_state=="unknown" if boundary!="intake-confirm-before-receipt" else intent.gate_state=="accepted"
            marker="rate:intent:"+str(intent_id)
            before_quota=int(r.get(inputs["keys"][0]) or 0)
        process.kill();process.wait(timeout=10);assert process.returncode<0
        state=reconcile_admission_gate(intent_id,temp_project)
        if boundary=="intent-before-gate":
            assert state=="unknown" and r.get(marker) is None and int(r.get(inputs["keys"][0]) or 0)==before_quota
        elif boundary=="compensate-before-receipt":
            assert state=="compensated" and json.loads(r.get(marker))["state"]=="compensated"
            assert int(r.get(inputs["keys"][0]) or 0)==before_quota
        else:
            assert state=="accepted" and int(r.get(inputs["keys"][0]))==before_quota
            replay_admissions(temp_project);replacement=start();deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                with tenant_session(temp_project) as db:
                    task=db.get(Task,uuid.UUID(tid))
                    if task and task.status=="done":break
                time.sleep(.2)
            assert task and task.status=="done"
            with tenant_session(temp_project) as db:
                assert len(list(db.scalars(select(Chapter).where(Chapter.project_id==uuid.UUID(temp_project)))))==1
                unchanged=db.get(AdmissionIntent,intent_id)
                assert str(unchanged.task_id)==tid and unchanged.payload_hash==original_hash and unchanged.publication_state=="published"
        evidence={"boundary":boundary,"task_id":tid,"intent_id":str(intent_id),"child_pid":process.pid,"state":state,"original_hash":original_hash,"original_date":inputs["date"],"quota_before":before_quota,"quota_after":int(r.get(inputs["keys"][0]) or 0)}
        Path("/mnt/e/tools/myink-pi/evidence/b10-intake-case-"+tid+".json").write_text(json.dumps(evidence,indent=2))
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        for f,log in logs:f.close()
        r.delete(key)
        if inputs:r.delete(*inputs["keys"])
        if marker:r.delete(marker)



def test_actual_sealed_frozen_prefix_drift_refused(monkeypatch):
    from dataclasses import replace
    import myink.config as config
    from ops.pi.lab.verify import verify_test_environment
    verify_test_environment()
    monkeypatch.setattr(config,"settings",replace(config.settings,queue_prefix="-mp-"))
    with pytest.raises(ValueError,match="frozen business fixture settings drift"):verify_test_environment()


def test_delay_without_ttl_is_refused(admitted):
    from myink.worker.handoff import record_handoff
    with tenant_session(admitted["project_id"]) as db:
        with pytest.raises(ValueError,match="delay TTL"):
            record_handoff(db,admitted,"delay","invalid-delay:"+admitted["task_id"])


def test_incomplete_historical_delay_is_retained_unknown(admitted,monkeypatch):
    from myink.worker import handoff
    from myink.models.maintenance import QueueHandoff
    operation='historical-incomplete:'+admitted['task_id']
    with tenant_session(admitted['project_id']) as db:
        db.add(QueueHandoff(operation_id=operation,message_id=admitted['request_id'],task_id=uuid.UUID(admitted['task_id']),project_id=uuid.UUID(admitted['project_id']),body_hash=handoff.body_hash(admitted),destination='delay',state='pending',rebuild_payload=admitted,priority=7,expiration_ms=None,authority={}))
    def prohibited(*a,**kw):pytest.fail('incomplete historical delay must not publish')
    monkeypatch.setattr(handoff.amqp,'publish_once',prohibited)
    assert handoff.publish_handoff(operation)['state']=='unknown'
    with tenant_session(admitted['project_id']) as db:
        row=db.get(QueueHandoff,operation);assert row.expiration_ms is None and row.rebuild_payload==admitted and row.state=='unknown'


def test_outbox_authority_cannot_fall_back_past_existing_intent(admitted):
    from myink.models import Task
    from myink.worker.handoff import record_handoff,QueueAuthorityUnknown
    changed={**admitted,'request_id':str(uuid.uuid4())}
    with tenant_session(admitted['project_id']) as db:
        db.add(Task(id=uuid.UUID(admitted['task_id']),project_id=uuid.UUID(admitted['project_id']),task_type=admitted['task_type'],status='queued',payload=admitted['payload']))
    with tenant_session(admitted['project_id']) as db:
        with pytest.raises(QueueAuthorityUnknown):record_handoff(db,changed,'tasks','wrong-known-intake:'+admitted['task_id'])


def test_valid_unmaterialized_unknown_delivery_is_retained_in_dlq(temp_project):
    from myink.worker import amqp,handoff
    from myink.worker.redis_client import get_redis
    from myink.models import Task
    from pathlib import Path
    with new_session() as db:uid=str(db.get(Project,uuid.UUID(temp_project)).user_id)
    body={'task_id':str(uuid.uuid4()),'project_id':temp_project,'user_id':uid,'task_type':'chapter_generate','payload':{'seq':1},'request_id':str(uuid.uuid4()),'retry_count':0}
    amqp.publish_once(json.dumps(body),'tasks',priority=7)
    with amqp.connect() as connection:
        channel=connection.channel();amqp.declare_topology(channel)
        held=[];found=False
        try:
            count=channel.queue_declare(amqp.main_queue(),passive=True).method.message_count
            for _ in range(count):
                method,properties,raw=channel.basic_get(amqp.main_queue(),auto_ack=False)
                if method is None:break
                if json.loads(raw).get('task_id')==body['task_id']:
                    consumer._on_message(channel,method,properties,raw,get_redis(),'actual-unknown-refusal');found=True
                else:held.append(method.delivery_tag)
        finally:
            for tag in held:channel.basic_nack(tag,requeue=True)
        assert found
    deliveries,uncertain=handoff._queue_census()
    assert uncertain==0 and (amqp.dlq_queue(),body) in deliveries
    with tenant_session(temp_project) as db:
        assert db.get(Task,uuid.UUID(body['task_id'])) is None
        from myink.maintenance import maintenance_view
        proof=handoff.reconcile_queue(db,maintenance_view(db)['epoch'])
        assert body['task_id'] in proof['planned_task_ids'] and proof['unknown']>0 and not proof['verified']
    Path('/mnt/e/tools/myink-pi/evidence/b10-unknown-body-'+body['task_id']+'.json').write_text(json.dumps(body))


def test_real_successive_defer_ttl_deliveries_keep_distinct_outboxes(admitted,monkeypatch,request):
    import time
    from myink.worker import handoff,amqp
    from myink.worker.redis_client import get_redis
    from myink.models.maintenance import QueueHandoff
    from myink.worker.redis_client import sse_key
    def finalize_exact_sse():
        import os,hashlib
        from pathlib import Path
        import redis
        from myink.config import settings
        from ops.pi.lab.verify import verify_test_environment
        from myink.models.maintenance import AdmissionIntent
        verify_test_environment()
        descriptor=json.loads(Path(os.environ['B10_CENSUS_DESCRIPTOR']).read_text())
        with tenant_session(admitted['project_id']) as db:
            intent=db.scalar(select(AdmissionIntent).where(AdmissionIntent.task_id==uuid.UUID(admitted['task_id'])))
            assert intent and intent.payload_hash==handoff.body_hash(admitted)
        deliveries,uncertain=handoff._queue_census();assert uncertain==0
        raw=redis.Redis.from_url(settings.redis_url,decode_responses=False)
        values=raw.xrange(sse_key(admitted['task_id']))
        exported=json.dumps([[i.hex(),[[k.hex(),v.hex()] for k,v in fields.items()]] for i,fields in values],separators=(',',':')).encode()
        path=Path('/mnt/e/tools/myink-pi/evidence/b10-sse-'+descriptor['operation_id']+'-'+admitted['task_id']+'.json')
        path.write_bytes(exported)
        path.with_suffix('.sha256').write_text(hashlib.sha256(exported).hexdigest())
        raw.delete(sse_key(admitted['task_id']))
    request.addfinalizer(finalize_exact_sse)
    monkeypatch.setattr(consumer,'process',lambda *a,**kw:'defer')
    monkeypatch.setattr(consumer,'observe',lambda *a,**kw:None)
    amqp.publish_once(json.dumps(admitted),'tasks',priority=7)
    from myink.models.maintenance import AdmissionIntent
    from myink.maintenance import intent_outcome
    with tenant_session(admitted['project_id']) as db:intent_id=db.scalar(select(AdmissionIntent.id).where(AdmissionIntent.task_id==uuid.UUID(admitted['task_id'])))
    intent_outcome(intent_id,admitted['project_id'],publication_state='published')
    operations=[]
    for iteration in range(2):
        found=False;deadline=time.monotonic()+12
        while not found and time.monotonic()<deadline:
            with amqp.connect() as connection:
                channel=connection.channel();amqp.declare_topology(channel)
                count=channel.queue_declare(amqp.main_queue(),passive=True).method.message_count;held=[]
                try:
                    for _ in range(count):
                        method,properties,raw=channel.basic_get(amqp.main_queue(),auto_ack=False)
                        if method is None:break
                        if json.loads(raw).get('task_id')==admitted['task_id']:
                            consumer._on_message(channel,method,properties,raw,get_redis(),'actual-repeat-defer');found=True;break
                        held.append(method.delivery_tag)
                finally:
                    for tag in held:channel.basic_nack(tag,requeue=True)
            if not found:time.sleep(.1)
        assert found,'real TTL original delivery did not return'
        with tenant_session(admitted['project_id']) as db:
            rows=list(db.scalars(select(QueueHandoff).where(QueueHandoff.task_id==uuid.UUID(admitted['task_id']))))
            assert len(rows)==iteration+1,'second real defer ACK reused published outbox and lost its delivery'
            assert all(row.rebuild_payload==admitted and row.expiration_ms==5000 and row.priority==7 for row in rows)
            operations=[row.operation_id for row in rows]
            if iteration==1:
                successor=next(row for row in rows if row.predecessor_id is not None)
                assert successor.predecessor_id in operations and successor.predecessor_id!=successor.operation_id
    assert len(set(operations))==2
    # Restore real processing and consume the second genuine TTL delivery.
    monkeypatch.undo()
    import os,sys,subprocess
    from pathlib import Path
    from myink.models import Task,Chapter,Event
    from myink.models.task_budget import TaskBudgetCall
    log=Path(os.environ['TMPDIR'])/('b10-successive-'+admitted['task_id']+'.log')
    with log.open('w') as stream:
        process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('_mp_worker.py'))],cwd=Path(__file__).parents[1],env=dict(os.environ),stdout=stream,stderr=stream)
        try:
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                with tenant_session(admitted['project_id']) as db:
                    task=db.get(Task,uuid.UUID(admitted['task_id']))
                    if task and task.status=='done':break
                time.sleep(.1)
            assert task and task.status=='done',log.read_text()
            with tenant_session(admitted['project_id']) as db:
                assert len(list(db.scalars(select(Chapter).where(Chapter.project_id==uuid.UUID(admitted['project_id'])))))==1
                assert len(list(db.scalars(select(Event).where(Event.project_id==uuid.UUID(admitted['project_id'])))))==1
                assert len(list(db.scalars(select(TaskBudgetCall).where(TaskBudgetCall.task_id==uuid.UUID(admitted['task_id']),TaskBudgetCall.operation_key.like('effect:%')))))==1
                from myink.models.task_budget import TaskBudget
                assert db.get(TaskBudget,uuid.UUID(admitted['task_id'])).limits['max_requests']==20
        finally:
            process.terminate();process.wait(timeout=10)
    deliveries,uncertain=handoff._queue_census()
    assert uncertain==0 and not any(message.get('task_id')==admitted['task_id'] for queue,message in deliveries)
    Path('/mnt/e/tools/myink-pi/evidence/b10-successive-'+admitted['task_id']+'.json').write_text(json.dumps({'task_id':admitted['task_id'],'message_id':admitted['request_id'],'operation_ids':operations,'child_pid':process.pid,'ttl_ms':5000,'priority':7,'retry_count':0,'effects':1,'task_budget_max_requests':20,'chapters':1,'memory_rows':1},indent=2))


@pytest.mark.parametrize('change',['operation','message','correlation','priority','expiration','body','pending'])
def test_actual_broker_predecessor_identity_is_verified(admitted,change):
    import copy
    from myink.worker import handoff,amqp
    from myink.models.maintenance import QueueHandoff
    operation='predecessor-negative:'+admitted['task_id']
    with tenant_session(admitted['project_id']) as db:handoff.record_handoff(db,admitted,'tasks',operation,priority=7)
    assert handoff.publish_handoff(operation)['state']=='published'
    with amqp.connect() as connection:
        channel=connection.channel();amqp.declare_topology(channel)
        count=channel.queue_declare(amqp.main_queue(),passive=True).method.message_count
        held=[];found=False
        try:
            for _ in range(count):
                method,properties,raw=channel.basic_get(amqp.main_queue(),auto_ack=False)
                if method is None:break
                held.append(method.delivery_tag)
                if json.loads(raw).get('task_id')!=admitted['task_id']:continue
                found=True;altered=copy.deepcopy(properties);body=copy.deepcopy(admitted)
                if change=='operation':altered.headers['operation_id']='foreign-unrecorded'
                elif change=='message':altered.message_id=str(uuid.uuid4())
                elif change=='correlation':altered.correlation_id=str(uuid.uuid4())
                elif change=='priority':altered.priority=6
                elif change=='expiration':altered.expiration='5000'
                elif change=='body':body['payload']={'seq':2}
                elif change=='pending':
                    with tenant_session(admitted['project_id']) as db:db.get(QueueHandoff,operation).state='pending'
                with tenant_session(admitted['project_id']) as db:
                    with pytest.raises(handoff.QueueAuthorityUnknown):handoff.delivery_predecessor(db,body,altered)
                break
            assert found
        finally:
            for tag in held:channel.basic_nack(tag,requeue=True)
