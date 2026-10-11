"""Private PostgreSQL outbox; unknown publication retains the original identity.

Business code deliberately has no dependency on the host maintenance installation.
"""
from __future__ import annotations
import hashlib
import json
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from sqlalchemy import select,text
from myink.db import new_session,tenant_session
from myink.maintenance import lock_maintenance
from myink.models import Project,Task
from myink.models.maintenance import AdmissionIntent,MaintenanceExecution,QueueHandoff
from myink.worker import amqp


class QueueAuthorityUnknown(RuntimeError):
    """Retain this message for reconciliation; never grant execution."""



_PUBLICATION_LANES=ContextVar("admission_publication_lanes",default={})


@contextmanager
def admission_lane(intent_id,project_id,*,reentrant=False):
    """One original intent, bounded try-lock, physically closed on every exit."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    from myink.db import get_engine
    identity=str(uuid.UUID(str(intent_id)));project=str(uuid.UUID(str(project_id)))
    active=_PUBLICATION_LANES.get()
    if identity in active:
        yield active[identity][1] if reentrant and active[identity][0]==project else None
        return
    key=int.from_bytes(hashlib.sha256(("myink-admission:"+identity).encode()).digest()[:8],"big",signed=True)
    engine=create_engine(get_engine().url,poolclass=NullPool,connect_args={"connect_timeout":5},isolation_level="AUTOCOMMIT")
    connection=None;acquired=False;token=None
    try:
        connection=engine.connect()
        connection.execute(text("SET statement_timeout=5000"))
        acquired=connection.scalar(text("SELECT pg_try_advisory_lock(:key)"),{"key":key})
        if not acquired:
            yield None
            return
        with tenant_session(project) as db:
            intent=db.get(AdmissionIntent,uuid.UUID(identity))
            if intent is None or str(intent.project_id)!=project:raise QueueAuthorityUnknown("unknown original publication lane")
        token=_PUBLICATION_LANES.set({**active,identity:(project,connection)})
        yield connection
    finally:
        if token is not None:_PUBLICATION_LANES.reset(token)
        try:
            if acquired:connection.execute(text("SELECT pg_advisory_unlock(:key)"),{"key":key})
        finally:
            try:
                if connection is not None:connection.close()
            finally:engine.dispose()


def body_hash(body):
    return hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def admission_for(db,body):
    tid=uuid.UUID(body["task_id"])
    digest=body_hash(body)
    intents=list(db.scalars(select(AdmissionIntent).where(AdmissionIntent.task_id==tid)))
    exact=next((i for i in intents if i.payload_hash==digest),None)
    if exact:
        return exact if exact.gate_state in ("accepted","not_required") and exact.publication_state not in ("rejected","not_attempted") else None
    delivery=db.scalar(select(QueueHandoff).where(QueueHandoff.task_id==tid,QueueHandoff.body_hash==digest))
    if delivery and delivery.admission_id:
        intent=db.get(AdmissionIntent,delivery.admission_id)
        if intent and intent.gate_state in ("accepted","not_required") and intent.publication_state not in ("rejected","not_attempted"):
            return intent
    return None


def _delay_valid(body,expiration_ms):
    from myink.config import settings
    retry=int(body.get('retry_count',0))
    permitted={settings.worker_defer_backoff_s*1000}
    if 0<retry<=settings.worker_max_retries:
        permitted.add(settings.worker_backoff_base*(2**(retry-1))*1000)
    return type(expiration_ms) is int and expiration_ms>0 and expiration_ms in permitted


def record_handoff(db,body:dict,destination:str,operation_id:str,*,priority=0,expiration_ms=None,maintenance_proof=None,predecessor_id=None):
    if destination not in ("tasks","delay","dlq") or not operation_id or len(operation_id)>256:
        raise ValueError("invalid controlled handoff")
    lock_maintenance(db)
    if destination=="delay" and not _delay_valid(body,expiration_ms):raise ValueError("invalid delay TTL")
    digest=body_hash(body)
    if predecessor_id is not None:
        previous=db.get(QueueHandoff,predecessor_id)
        prior=dict(body)
        if int(body.get('retry_count',0))>0:prior['retry_count']=int(body['retry_count'])-1
        if (previous is None or previous.state not in ('unknown','published')
                or str(previous.task_id)!=body['task_id'] or str(previous.project_id)!=body['project_id']
                or previous.message_id!=str(body.get('request_id') or body['task_id']) or previous.priority!=priority
                or previous.body_hash not in (digest,body_hash(prior)) or previous.destination not in ('tasks','delay')
                or (previous.destination=='delay' and not _delay_valid(previous.rebuild_payload,previous.expiration_ms))):
            raise QueueAuthorityUnknown('unverified handoff predecessor')
    row=db.get(QueueHandoff,operation_id,with_for_update=True)
    if row:
        if (row.body_hash,row.destination,row.priority,row.expiration_ms,row.predecessor_id)!=(digest,destination,priority,expiration_ms,predecessor_id):
            raise ValueError("handoff identity conflict")
        return {"operation_id":row.operation_id,"body_hash":row.body_hash,"state":row.state}
    intent=_maintenance_authority(db,body,maintenance_proof) if maintenance_proof is not None else admission_for(db,body)
    # A retry may change ONLY retry_count by one from an authorized original.
    if intent is None and int(body.get("retry_count",0))>0:
        original=dict(body,retry_count=int(body["retry_count"])-1)
        intent=admission_for(db,original)
    if intent is None:
        if db.scalar(select(AdmissionIntent.id).where(AdmissionIntent.task_id==uuid.UUID(body["task_id"]))) is not None:
            raise QueueAuthorityUnknown("known intake cannot use legacy fallback")
        task=db.get(Task,uuid.UUID(body["task_id"]))
        if (task is None or task.project_id!=uuid.UUID(body["project_id"]) or task.status not in ("queued","running")
                or task.task_type!=body.get("task_type")
                or {k:v for k,v in (task.payload or {}).items() if k not in {"_gate_user_id","_task_budget","_budget_resume_operation"}}!=(body.get("payload") or {})):
            raise QueueAuthorityUnknown("handoff has no durable intake authority")
    row=QueueHandoff(operation_id=operation_id,message_id=str(body.get("request_id") or body["task_id"]),
        task_id=uuid.UUID(body["task_id"]),project_id=uuid.UUID(body["project_id"]),admission_id=intent.id if intent else None,
        body_hash=digest,destination=destination,state="pending",rebuild_payload=json.loads(json.dumps(body)),
        priority=priority,expiration_ms=expiration_ms,authority=maintenance_proof or {},predecessor_id=predecessor_id)
    db.add(row);db.flush()
    return {"operation_id":operation_id,"body_hash":digest,"state":"pending"}


def delivery_predecessor(db,body,properties):
    """Broker headers grant lineage only after immutable PG and property matching."""
    headers=getattr(properties,'headers',None)
    if headers is None:return None
    if not isinstance(headers,dict):raise QueueAuthorityUnknown('unknown delivery headers')
    if 'operation_id' not in headers:return None
    operation=headers['operation_id']
    if not isinstance(operation,str) or not operation or len(operation)>256:
        raise QueueAuthorityUnknown('invalid delivery predecessor')
    row=db.get(QueueHandoff,operation)
    if (row is None or row.state not in ('unknown','published') or row.body_hash!=body_hash(body)
            or str(row.task_id)!=body['task_id'] or str(row.project_id)!=body['project_id']
            or row.message_id!=str(body.get('request_id') or body['task_id'])
            or getattr(properties,'message_id',None)!=row.message_id
            or getattr(properties,'correlation_id',None)!=body['task_id']
            or getattr(properties,'priority',None)!=row.priority):
        raise QueueAuthorityUnknown('delivery predecessor identity conflict')
    expiration=getattr(properties,'expiration',None)
    if row.destination=='tasks':
        if expiration!=(str(row.expiration_ms) if row.expiration_ms is not None else None):
            raise QueueAuthorityUnknown('delivery predecessor properties conflict')
    elif row.destination=='delay':
        if (not _delay_valid(body,row.expiration_ms) or expiration is not None
                or not any(isinstance(death,dict) and death.get('queue')==amqp.delay_queue()
                    and death.get('reason')=='expired' and death.get('original-expiration')==str(row.expiration_ms)
                    and death.get('exchange')==amqp.exchange() and death.get('routing-keys')==[amqp.KEY_DELAY]
                    for death in headers.get('x-death',[]))):
            raise QueueAuthorityUnknown('delivery predecessor delay proof conflict')
    else:raise QueueAuthorityUnknown('delivery predecessor destination conflict')
    return operation


def _project_for(operation_id):
    # Project ids are already readable by the existing application role. Private
    # payload lookup stays in each project transaction under FORCE RLS.
    with new_session() as db: projects=list(db.scalars(select(Project.id)))
    for pid in projects:
        with tenant_session(pid) as db:
            row=db.get(QueueHandoff,operation_id)
            if row is not None and row.project_id==pid:return pid
    raise QueueAuthorityUnknown("unknown handoff operation")


def publish_handoff(operation_id:str):
    pid=_project_for(operation_id)
    with tenant_session(pid) as db:
        row=db.get(QueueHandoff,operation_id)
        admission_id=row.admission_id
    if admission_id is None:return _publish_handoff(operation_id,pid)
    with admission_lane(admission_id,pid,reentrant=True) as lane:
        if lane is None:return {"operation_id":operation_id,"state":"unknown"}
        with tenant_session(pid) as db:
            intent=db.get(AdmissionIntent,admission_id)
            if intent.gate_state not in ("accepted","not_required") or intent.publication_state in ("rejected","not_attempted"):
                return {"operation_id":operation_id,"state":"unknown"}
        return _publish_handoff(operation_id,pid)


def _publish_handoff(operation_id,pid):
    with tenant_session(pid) as db:
        row=db.get(QueueHandoff,operation_id,with_for_update=True)
        if row.state=="published":return {"operation_id":operation_id,"state":"published"}
        row.state="unknown"
        if row.destination=="delay" and not _delay_valid(row.rebuild_payload,row.expiration_ms):
            return {"operation_id":operation_id,"state":"unknown"}
        body=dict(row.rebuild_payload);priority=row.priority;expiration=row.expiration_ms;destination=row.destination
    try:
        amqp.publish_once(json.dumps(body,ensure_ascii=False),destination,priority=priority,expiration_ms=expiration,
                          operation_id=operation_id)
    except amqp.PublishNotSent:
        # An earlier attempt may have been confirmed without its PG receipt.
        return {"operation_id":operation_id,"state":"unknown"}
    except Exception:
        return {"operation_id":operation_id,"state":"unknown"}
    with tenant_session(pid) as db:
        row=db.get(QueueHandoff,operation_id,with_for_update=True);row.state="published"
    return {"operation_id":operation_id,"state":"published"}


def reconcile_admission_gate(intent_id,project_id):
    """Observe the original atomic marker; Redis absence never authorizes charge."""
    from myink.worker.enqueue import _GATES_LUA
    from myink.worker.redis_client import get_redis
    from myink.maintenance import intent_outcome
    with tenant_session(project_id) as db:
        intent=db.get(AdmissionIntent,uuid.UUID(str(intent_id)))
        if intent is None:raise QueueAuthorityUnknown("unknown intake")
        if intent.gate_state not in ("pending","unknown"):return intent.gate_state
        inputs=dict(intent.quota_inputs)
    if not inputs:return "unknown"
    keys=inputs["keys"];limits=inputs["limits"]
    args=[inputs["task_id"],str(inputs["quota_n"]),str(inputs["cost_est"]),str(limits[0]),str(limits[1]),str(limits[2]),str(limits[3]),inputs["project_id"],str(inputs["platform_chapter_max"])]
    fingerprint=hashlib.sha256(json.dumps([keys,args],separators=(",",":"),allow_nan=False).encode()).hexdigest()
    result=get_redis().eval(_GATES_LUA,7,*keys,"rate:intent:"+str(intent_id),*args,fingerprint,"recover")
    state="accepted" if int(result[0])==1 else "compensated" if result[1]=="INTENT_COMPENSATED" else "rejected" if -5<=int(result[0])<=-1 else "unknown"
    intent_outcome(intent_id,project_id,gate_state=state)
    return state


def replay_admissions(project_id,*,intent_ids=None):
    from myink.maintenance import intent_outcome
    from myink.worker.redis_client import get_redis
    with tenant_session(project_id) as db:
        query=select(AdmissionIntent.id).where(AdmissionIntent.project_id==uuid.UUID(str(project_id)),
            AdmissionIntent.publication_state.in_(("pending","unknown")))
        if intent_ids is not None:query=query.where(AdmissionIntent.id.in_(intent_ids))
        ids=list(db.scalars(query))
    for intent_id in ids:
        with admission_lane(intent_id,project_id) as lane:
            if lane is None:continue
            with tenant_session(project_id) as db:
                intent=db.get(AdmissionIntent,intent_id)
                if intent.publication_state not in ("pending","unknown"):continue
                gate=intent.gate_state;body=dict(intent.rebuild_payload);priority=intent.priority
            if gate in ("pending","unknown"):gate=reconcile_admission_gate(intent_id,project_id)
            if gate not in ("accepted","not_required"):continue
            with tenant_session(project_id) as db:
                task=db.get(Task,uuid.UUID(body["task_id"]))
                if task and task.status not in ("queued","running"):continue
                operation="admission:"+str(intent_id)
                record_handoff(db,body,"tasks",operation,priority=priority)
            # Commit unknown before ownership/publish so a crash cannot authorize refund.
            intent_outcome(intent_id,project_id,publication_state="unknown")
            get_redis().set("queue:task-owner:"+body["task_id"],json.dumps({"user_id":body["user_id"],"project_id":body["project_id"]}),ex=86400)
            receipt=publish_handoff(operation)
            intent_outcome(intent_id,project_id,publication_state="published" if receipt["state"]=="published" else "unknown")


_REPLAY_POSITION=None


def replay_handoffs(max_operations=20):
    """Bounded fair scheduling; the volatile cursor grants no execution authority."""
    global _REPLAY_POSITION
    if type(max_operations) is not int or not 1<=max_operations<=20:raise ValueError("invalid replay batch")
    with new_session() as db:projects=sorted(db.scalars(select(Project.id)),key=str)
    if not projects:return
    position=_REPLAY_POSITION
    if position:
        index=next((i for i,pid in enumerate(projects) if str(pid)>=position[0]),0)
        projects=projects[index:]+projects[:index]
    remaining=max_operations
    for pid in projects:
        for kind,model,column in (("admission",AdmissionIntent,AdmissionIntent.id),("handoff",QueueHandoff,QueueHandoff.operation_id)):
            if position and str(pid)==position[0] and kind<position[1]:continue
            with tenant_session(pid) as db:
                states=AdmissionIntent.publication_state.in_(("pending","unknown")) if kind=="admission" else QueueHandoff.state.in_(("pending","unknown"))
                query=select(column).where(model.project_id==pid,states)
                if position and str(pid)==position[0] and kind==position[1]:
                    query=query.where(column>(uuid.UUID(position[2]) if kind=="admission" else position[2]))
                ids=list(db.scalars(query.order_by(column).limit(remaining)))
            for identity in ids:
                _REPLAY_POSITION=(str(pid),kind,str(identity));remaining-=1
                if kind=="admission":replay_admissions(pid,intent_ids=[identity])
                else:publish_handoff(identity)
                if not remaining:return
    _REPLAY_POSITION=None


def _queue_census():
    deliveries=[];unknown=0
    with amqp.connect() as connection:
        channel=connection.channel();amqp.declare_topology(channel)
        for queue in (amqp.main_queue(),amqp.delay_queue(),amqp.dlq_queue()):
            snapshot=channel.queue_declare(queue,passive=True).method
            if snapshot.consumer_count or snapshot.message_count>1000:unknown+=1;continue
            tags=[]
            try:
                for _ in range(snapshot.message_count):
                    method,properties,raw=channel.basic_get(queue,auto_ack=False)
                    if method is None:unknown+=1;break
                    tags.append(method.delivery_tag)
                    try:body=json.loads(raw)
                    except (ValueError,TypeError):unknown+=1;continue
                    metadata={key:getattr(properties,key,None) for key in
                        ('message_id','correlation_id','priority','expiration','headers','delivery_mode')}
                    metadata.update(exchange=method.exchange,routing_key=method.routing_key,redelivered=method.redelivered)
                    deliveries.append((queue,body,metadata))
            finally:
                for tag in tags:channel.basic_nack(tag,requeue=True)
    return deliveries,unknown


def reconcile_queue(db,epoch:str):
    control=lock_maintenance(db)
    intents=list(db.scalars(select(AdmissionIntent)))
    handoffs=list(db.scalars(select(QueueHandoff)))
    tasks=list(db.scalars(select(Task)))
    executions=list(db.scalars(select(MaintenanceExecution)))
    planned={str(i.task_id) for i in intents if i.gate_state not in ("rejected","compensated")}
    planned.update(str(h.task_id) for h in handoffs)
    planned.update(str(t.id) for t in tasks if t.status not in ("done","cancelled","failed"))
    unknown=sum(i.gate_state in ("pending","unknown") or i.publication_state in ("pending","unknown") for i in intents)
    unknown+=sum(h.state!="published" for h in handoffs)
    unknown+=sum(e.state in ("pause_requested","interruption_unconfirmed") or bool(e.owner_token or e.active_nodes) for e in executions)
    pauses=[dict(e.receipt) for e in executions if e.state=="paused"]
    from myink.models.task_budget import TaskBudgetCall
    for execution in executions:
        if execution.state!="paused":continue
        receipt=execution.receipt
        if (not receipt or receipt.get("epoch")!=epoch or receipt.get("deployment_id")!=control["deployment_id"]
                or receipt.get("image_ids")!=control["image_ids"] or execution.owner_token or execution.active_nodes
                or execution.epoch!=epoch or execution.deployment_generation!=control["generation"]
                or receipt.get("deployment_generation")!=control["generation"]
                or type(receipt.get("generation")) is not int
                or execution.execution_generation!=receipt["generation"]+1):
            unknown+=1;continue
        from myink.maintenance_pause import validate_compatibility
        try:validate_compatibility(receipt.get("protocol",{}))
        except (ValueError,TypeError,KeyError):unknown+=1;continue
        effects={str(effect.id) for effect in db.scalars(select(TaskBudgetCall).where(TaskBudgetCall.task_id==execution.task_id,TaskBudgetCall.operation_key.like("effect:%")))}
        if {effect["id"] for effect in receipt.get("effects",[])}!=effects:unknown+=1
        for checkpoint in receipt.get("checkpoints",[]):
            if not checkpoint.get("checkpoint_id"):unknown+=1;continue
            short=db.get(TaskBudgetCall,uuid.UUID(checkpoint["checkpoint_id"])) if len(checkpoint["checkpoint_id"])==36 else None
            if short is None:
                actual=db.scalar(text("SELECT 1 FROM checkpoints WHERE thread_id=:thread AND checkpoint_id=:checkpoint LIMIT 1"),{"thread":checkpoint["thread_id"],"checkpoint":checkpoint["checkpoint_id"]})
                if actual!=1:unknown+=1

    if control["epoch"]!=epoch or not control["consumer_blocked"] or not control["admission_closed"]:unknown+=1
    try:
        deliveries,uncertain=_queue_census();unknown+=uncertain
        present=set()
        for queue,body,metadata in deliveries:
            if not isinstance(body,dict) or "task_id" not in body:unknown+=1;continue
            present.add(str(body["task_id"]));planned.add(str(body["task_id"]))
            try:
                intent=admission_for(db,body)
                from types import SimpleNamespace
                if queue==amqp.dlq_queue() or intent is None:
                    raise QueueAuthorityUnknown("quarantined or unproven delivery")
                if (metadata.get("delivery_mode")!=2 or metadata.get("exchange")!=amqp.exchange()
                        or metadata.get("routing_key")!=("delay" if queue==amqp.delay_queue() else "tasks")):
                    raise QueueAuthorityUnknown("delivery topology properties conflict")
                if queue==amqp.delay_queue():
                    operation=(metadata.get("headers") or {}).get("operation_id")
                    previous=db.get(QueueHandoff,operation) if isinstance(operation,str) else None
                    if (previous is None or previous.state not in ("unknown","published") or previous.destination!="delay"
                            or previous.body_hash!=body_hash(body) or previous.task_id!=uuid.UUID(body["task_id"])
                            or previous.project_id!=uuid.UUID(body["project_id"]) or previous.message_id!=metadata.get("message_id")
                            or metadata.get("correlation_id")!=str(previous.task_id) or metadata.get("priority")!=previous.priority
                            or not _delay_valid(body,previous.expiration_ms) or metadata.get("expiration")!=str(previous.expiration_ms)):
                        raise QueueAuthorityUnknown("delay queue properties conflict")
                    predecessor=operation
                else:predecessor=delivery_predecessor(db,body,SimpleNamespace(**metadata))
                if predecessor is None:
                    if (queue!=amqp.main_queue() or metadata.get("priority")!=intent.priority
                            or metadata.get("message_id")!=intent.message_id
                            or metadata.get("correlation_id")!=str(intent.task_id)
                            or metadata.get("expiration") is not None):
                        raise QueueAuthorityUnknown("original delivery properties conflict")
            except (QueueAuthorityUnknown,ValueError,TypeError,KeyError,AttributeError):
                unknown+=1
        from myink.worker.redis_client import get_redis,lock_key,book_key
        r=get_redis()
        unknown+=sum(bool(r.exists(lock_key(str(t.id))) or r.exists(book_key(str(t.project_id)))) for t in tasks if t.status not in ("done","cancelled","failed"))
        for task in tasks:
            if task.status in ("queued","running") and str(task.id) not in present:
                unknown+=1
        for i in intents:
            if i.gate_state in ("accepted","not_required") and i.publication_state=="published":
                task=next((t for t in tasks if t.id==i.task_id),None)
                if task is None and str(i.task_id) not in present:unknown+=1
    except Exception:unknown+=1;deliveries=[]
    return {"epoch":epoch,"planned_task_ids":sorted(planned),"planned":len(planned),"unknown":unknown,
            "pause_receipts":pauses,"queue_messages":len(deliveries),"handoffs":len(handoffs),"verified":unknown==0}


def _maintenance_authority(db,body,proof):
    """Only an actual same-deployment confirmed PG pause grants controlled resume."""
    from myink.maintenance_pause import validate_compatibility
    from myink.models.task_budget import TaskBudget,TaskBudgetCall
    control=lock_maintenance(db)
    tid=uuid.UUID(body['task_id'])
    task=db.get(Task,tid,with_for_update=True)
    execution=db.get(MaintenanceExecution,tid,with_for_update=True)
    budget=db.get(TaskBudget,tid,with_for_update=True)
    if (task is None or execution is None or budget is None or budget.pause_reason
            or task.status!='queued' or task.error or execution.state!='running'
            or execution.owner_token or execution.active_nodes or execution.receipt!=proof
            or proof.get('epoch')!=control['epoch'] or proof.get('deployment_generation')!=control['generation']
            or execution.epoch!=control['epoch'] or execution.deployment_generation!=control['generation']
            or execution.execution_generation!=proof.get('generation',-2)+1
            or proof.get('deployment_id')!=control['deployment_id'] or proof.get('image_ids')!=control['image_ids']
            or proof.get('original_wait') not in ('queued','running') or proof.get('waiting_reason')
            or proof.get('transaction')!='committed' or proof.get('locks')!='released_after_commit'
            or control['admission_closed'] or control['consumer_blocked']):
        raise QueueAuthorityUnknown('maintenance resume authority unconfirmed')
    validate_compatibility(proof.get('protocol',{}))
    effects={(str(e.id),e.operation_key) for e in db.scalars(select(TaskBudgetCall).where(TaskBudgetCall.task_id==tid,TaskBudgetCall.operation_key.like('effect:%')))}
    if {(e['id'],e['key']) for e in proof.get('effects',[])}!=effects or not proof.get('checkpoints'):
        raise QueueAuthorityUnknown('maintenance durable proof changed')
    for checkpoint in proof['checkpoints']:
        if not db.scalar(text('SELECT 1 FROM checkpoints WHERE thread_id=:thread AND checkpoint_id=:checkpoint LIMIT 1'),
                         {'thread':checkpoint['thread_id'],'checkpoint':checkpoint['checkpoint_id']}):
            raise QueueAuthorityUnknown('maintenance checkpoint missing')
    for intent in db.scalars(select(AdmissionIntent).where(AdmissionIntent.task_id==tid)):
        original=dict(intent.rebuild_payload)
        resume_type={'chapter_generate':'chapter_resume','chapter_resume':'chapter_resume','batch_generate':'batch_resume','batch_resume':'batch_resume'}.get(original.get('task_type'))
        stored={k:v for k,v in (task.payload or {}).items() if k not in {'_gate_user_id','_task_budget','_budget_resume_operation'}}
        if (resume_type and task.task_type==original.get('task_type') and stored==original.get('payload',{})
                and (task.payload or {}).get('_task_budget')==original.get('task_budget') and body=={**original,'task_type':resume_type}
                and intent.gate_state in ('accepted','not_required') and intent.publication_state not in ('rejected','not_attempted')
                and intent.project_id==task.project_id and str(intent.user_id)==body['user_id']):return intent
    raise QueueAuthorityUnknown('maintenance original intake missing')


def resume_maintenance_handoffs(db,epoch,expected_generation):
    """Caller commits Task CAS and rebuild outbox together, then publishes IDs."""
    from myink.maintenance_pause import resume_maintenance_tasks
    control=lock_maintenance(db)
    if (control['epoch']!=epoch or control['generation']!=expected_generation
            or control['admission_closed'] or control['consumer_blocked']):raise ValueError('stale or closed maintenance resume')
    receipts=resume_maintenance_tasks(db,epoch,expected_generation)
    result=[]
    for proof in receipts:
        tid=uuid.UUID(proof['task_id'])
        intent=db.scalar(select(AdmissionIntent).where(AdmissionIntent.task_id==tid).order_by(AdmissionIntent.created_at))
        if intent is None:raise QueueAuthorityUnknown('maintenance original intake missing')
        body=dict(intent.rebuild_payload)
        resume_type={'chapter_generate':'chapter_resume','chapter_resume':'chapter_resume','batch_generate':'batch_resume','batch_resume':'batch_resume'}.get(body['task_type'])
        if resume_type is None:raise QueueAuthorityUnknown('unsupported controlled maintenance resume')
        body['task_type']=resume_type
        operation='maintenance-resume:'+epoch+':'+str(tid)+':'+body_hash(proof)
        result.append(record_handoff(db,body,'tasks',operation,priority=intent.priority,maintenance_proof=proof))
    if not receipts:
        for row in db.scalars(select(QueueHandoff).where(QueueHandoff.operation_id.like('maintenance-resume:'+epoch+':%'))):
            proof=row.authority
            task=db.get(Task,row.task_id)
            if (proof.get('deployment_generation')==expected_generation and proof.get('deployment_id')==control['deployment_id']
                    and proof.get('image_ids')==control['image_ids'] and task and task.status in ('queued','running','done')):
                result.append({'operation_id':row.operation_id,'body_hash':row.body_hash,'state':row.state})
    return result
