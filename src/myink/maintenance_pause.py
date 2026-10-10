"""Verified maintenance points and per-task fences, separate from budget waits.

Business receipts and graph checkpoints commit in different transactions. A
pause certificate reconciles both after the graph has unwound; it never asserts
cross-store atomicity. Requests do not revoke a currently authorized node.
"""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import time
import uuid
from sqlalchemy import select
from myink.maintenance import lock_maintenance
from myink.models import Task
from myink.models.maintenance import MaintenanceExecution

PROTOCOL = {"protocol": 1, "schema": 1, "state": 1, "effect_keys": 1}
READ_ONLY_TOOLS = frozenset({"inspect_character", "inspect_foreshadows", "inspect_plot_threads", "inspect_facts", "read_genre_reference"})
_SCOPE = ContextVar("maintenance_execution", default=None)
_NODES = ContextVar("maintenance_authorized_nodes", default=())

@dataclass(frozen=True)
class Execution:
    task_id: str
    project_id: str
    owner: str
    generation: int

class MaintenancePaused(Exception):
    def __init__(self, stage=None, *, scope=None):
        self.stage = stage
        self.scope = scope or _SCOPE.get()
        self.checkpoints = []
        super().__init__("maintenance_pause_requested")


def validate_compatibility(identity):
    if any(identity.get(k) != v for k, v in PROTOCOL.items()):
        raise ValueError("incompatible maintenance state protocol")
    if identity.get("serialization", "jsonplus") != "jsonplus":
        raise ValueError("unsupported maintenance serializer")
    if identity.get("state_family", "chapter") not in {"chapter","short","batch","plan","review","tool"}:
        raise ValueError("unsupported maintenance state family")


def _locked(db, task_id):
    control = lock_maintenance(db)
    task = db.scalar(select(Task).where(Task.id == uuid.UUID(str(task_id))).with_for_update())
    if task is None:
        raise ValueError("missing maintenance task")
    row = db.scalar(select(MaintenanceExecution).where(MaintenanceExecution.task_id == task.id).with_for_update())
    return control, task, row


def execution_view(db, task_id):
    row = db.get(MaintenanceExecution, uuid.UUID(str(task_id)))
    if row is None:
        raise ValueError("no execution identity")
    return {"execution_generation": row.execution_generation, "deployment_generation":row.deployment_generation,
            "state":row.state, "epoch":row.epoch, "owner":row.owner_token,
            "active_nodes":list(row.active_nodes), "receipt":dict(row.receipt)}


@contextmanager
def bind_execution(task_id, owner):
    from myink.db import new_session, tenant_session
    with new_session() as db:
        task = db.get(Task, uuid.UUID(str(task_id)))
        pid = str(task.project_id)
    with tenant_session(pid) as db:
        control, task, row = _locked(db, task_id)
        if row is None:
            row = MaintenanceExecution(task_id=task.id, project_id=task.project_id,
                execution_generation=0, active_nodes=[], completed_nodes=[], receipt={})
            db.add(row)
        if row.state in {"pause_requested", "paused", "interruption_unconfirmed"}:
            raise MaintenancePaused(scope=Execution(str(task_id),pid,owner,row.execution_generation))
        if row.owner_token and row.owner_token != owner:
            from myink.task_budget import TaskBudgetUnavailable
            raise TaskBudgetUnavailable("maintenance execution still owned")
        row.execution_generation += 1
        row.owner_token = owner
        row.state = "running"
        row.deployment_generation = control["generation"]
        row.receipt = {**row.receipt,"deployment_id":control["deployment_id"],"image_ids":control["image_ids"]}
        scope = Execution(str(task_id),pid,owner,row.execution_generation)
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        _SCOPE.reset(token)
        with tenant_session(pid) as db:
            _, _, row = _locked(db, task_id)
            if row.owner_token == owner and row.execution_generation == scope.generation:
                # An unwound worker is quiescent, but only durable proof may
                # certify requested work as paused. Crashed workers never get here.
                row.active_nodes = []
                if row.state == "running":
                    row.owner_token = None


def request_pause(db, epoch: str, task_id: str, generation: int) -> None:
    control, task, row = _locked(db, task_id)
    if control["epoch"] != epoch or row is None or row.execution_generation != generation or row.deployment_generation != control["generation"] or row.receipt.get("deployment_id") != control["deployment_id"] or row.receipt.get("image_ids") != control["image_ids"]:
        raise ValueError("stale maintenance request")
    if row.state == "pause_requested" and row.epoch == epoch:
        return
    if row.state != "running":
        raise ValueError("execution is not running")
    row.epoch = epoch
    row.deployment_generation = control["generation"]
    row.requested_at = time.time()
    row.state = "pause_requested"
    row.receipt = {**row.receipt,"original_wait":task.status, "protocol":dict(PROTOCOL)}


def fence_effect(db):
    """Must run BEFORE task-budget/effect locks in the same business transaction."""
    scope = _SCOPE.get()
    if scope is None:
        return
    control, task, row = _locked(db, scope.task_id)
    from myink.task_budget import TaskBudgetPaused, TaskBudgetUnavailable
    if task.status in {"cancelled", "paused", "awaiting_plan", "awaiting_review"}:
        if task.status == "paused" and row.state == "paused":
            raise MaintenancePaused(scope=scope)
        raise TaskBudgetPaused("cancelled" if task.status == "cancelled" else "manual_pause")
    if row.owner_token != scope.owner or row.execution_generation != scope.generation or row.state not in {"running", "pause_requested"} or row.deployment_generation != control["generation"] or row.receipt.get("deployment_id") != control["deployment_id"] or row.receipt.get("image_ids") != control["image_ids"]:
        raise TaskBudgetUnavailable("maintenance execution fenced")


def guard_maintenance(stage: str) -> None:
    scope = _SCOPE.get()
    if scope is None:
        return
    from myink.db import tenant_session
    with tenant_session(scope.project_id) as db:
        fence_effect(db)
        row = db.get(MaintenanceExecution, uuid.UUID(scope.task_id))
        if row.state == "pause_requested" and not _NODES.get():
            raise MaintenancePaused(stage, scope=scope)


@contextmanager
def authorized_node(stage):
    scope = _SCOPE.get()
    if scope is None:
        yield
        return
    from myink.db import tenant_session
    with tenant_session(scope.project_id) as db:
        fence_effect(db)
        row = db.get(MaintenanceExecution, uuid.UUID(scope.task_id))
        # Nested graph child entry is a new node, even while parent awaits it.
        if row.state == "pause_requested":
            raise MaintenancePaused(stage, scope=scope)
        row.active_nodes = [*row.active_nodes, stage]
    token = _NODES.set((*_NODES.get(),stage))
    success = False
    try:
        yield
        success = True
    finally:
        _NODES.reset(token)
        with tenant_session(scope.project_id) as db:
            _, _, row = _locked(db, scope.task_id)
            if row.owner_token == scope.owner and row.execution_generation == scope.generation:
                remaining = list(row.active_nodes)
                if stage in remaining:
                    remaining.remove(stage)
                row.active_nodes = remaining
                if success:
                    row.completed_nodes = [*row.completed_nodes[-63:],stage]


def invoke_graph(graph, value, config):
    from myink.task_budget import TaskBudgetPaused
    try:
        result=graph.invoke(value, config=config)
        guard_maintenance("graph:end")
        return result
    except (MaintenancePaused, TaskBudgetPaused) as exc:
        if not hasattr(exc,"checkpoints"):
            exc.scope=_SCOPE.get()
            exc.checkpoints=[]
        exc.checkpoints.append({"graph":graph,"thread_id":config["configurable"]["thread_id"]})
        raise


def _graph_proof(record, allowed_errors=()):
    from langgraph.checkpoint.postgres import PostgresSaver
    graph, tid = record["graph"], record["thread_id"]
    saver = graph.checkpointer
    if not isinstance(saver, PostgresSaver):
        raise ValueError("durable PostgreSQL checkpoint required")
    config = {"configurable":{"thread_id":tid}}
    snapshot = graph.get_state(config)
    persisted = saver.get_tuple(config)
    if persisted is None or not snapshot.config or not snapshot.values:
        raise ValueError("no durable graph state")
    cid = persisted.config["configurable"]["checkpoint_id"]
    if snapshot.config["configurable"]["checkpoint_id"] != cid:
        raise ValueError("checkpoint changed during confirmation")
    pending = [(str(t), str(c)) for t,c,v in persisted.pending_writes]
    for t,c,v in persisted.pending_writes:
        if c == "__error__" and v not in {"MaintenancePaused('maintenance_pause_requested')",*allowed_errors}:
            raise ValueError("unconfirmed node error")
    waiting = "awaiting_review" if snapshot.values.get("needs_review") else "awaiting_plan" if snapshot.values.get("awaiting_plan") or any(t.interrupts for t in snapshot.tasks) else None
    return {"thread_id":tid,"checkpoint_id":cid,"next_node":list(snapshot.next),
            "pending_writes":pending,"parent_position":snapshot.values.get("position"),"waiting_reason":waiting}


def confirm_pause(db, task_id: str, checkpoint: dict, message: dict) -> dict:
    control, task, row = _locked(db, task_id)
    from myink.models.task_budget import TaskBudget, TaskBudgetCall, TaskBudgetAttempt
    budget = db.scalar(select(TaskBudget).where(TaskBudget.task_id==task.id).with_for_update())
    if row is None or row.state != "pause_requested" or row.active_nodes:
        raise ValueError("execution has not reached quiescence")
    if (message.get("task_id") != str(task.id) or message.get("owner") != row.owner_token
        or message.get("generation") != row.execution_generation or control["epoch"] != row.epoch
        or control["generation"] != row.deployment_generation or control["deployment_id"] != row.receipt.get("deployment_id") or control["image_ids"] != row.receipt.get("image_ids")):
        raise ValueError("stale maintenance confirmation")
    if task.status not in {"queued","running","paused","cancelled","awaiting_plan","awaiting_review"}:
        raise ValueError("task is already terminal")
    waiting = (budget.pause_reason if budget else None) or (task.status if task.status not in {"queued","running"} else None)
    if db.scalar(select(TaskBudgetAttempt.id).where(TaskBudgetAttempt.task_id==task.id,
        TaskBudgetAttempt.owner_token==row.owner_token,TaskBudgetAttempt.status.in_(["reserved","unknown"])).limit(1)):
        raise ValueError("model interruption remains unconfirmed")
    validate_compatibility(row.receipt.get("protocol",{}))
    if checkpoint.get("kind") == "graph":
        # Only an independently persisted stronger wait authorizes its exact
        # error representation; arbitrary error strings cannot certify safety.
        reason=(budget.pause_reason if budget else None) or ("cancelled" if task.status=="cancelled" else "manual_pause" if task.status in {"paused","awaiting_plan","awaiting_review"} else None)
        allowed=[f"TaskBudgetPaused('Task budget paused: {reason}')"] if reason else []
        proofs = [_graph_proof(record, allowed) for record in checkpoint["records"]]
        if not proofs or not any(p["thread_id"] == str(task.id) for p in proofs):
            raise ValueError("root checkpoint required")
        waiting = waiting or next((p["waiting_reason"] for p in proofs if p.get("waiting_reason")),None)
        progress = None
    elif checkpoint.get("kind") == "short":
        saved=db.scalar(select(TaskBudgetCall).where(TaskBudgetCall.task_id==task.id,
            TaskBudgetCall.operation_key=='short:progress',TaskBudgetCall.input_hash=='progress'))
        if saved is None or saved.response.get('stage') not in {'written','continued','reviewed','complete','persisted'}:
            raise ValueError("durable short progress required")
        progress=dict(saved.response)
        next_stage={'written':'short_continue_or_review','continued':'short_review','reviewed':'short_rewrite_or_persist','complete':'short_persist','persisted':'done'}[progress['stage']]
        proofs=[{"thread_id":str(task.id),"checkpoint_id":str(saved.id),"next_node":[next_stage],"pending_writes":[]}]
    else:
        raise ValueError("unknown checkpoint format")
    effects=list(db.scalars(select(TaskBudgetCall).where(TaskBudgetCall.task_id==task.id,TaskBudgetCall.operation_key.like('effect:%'))))
    if progress and progress['stage']=='persisted' and not any('short_persist' in e.operation_key for e in effects):
        raise ValueError("short persisted progress lacks transaction receipt")
    receipt={"task_id":str(task.id),"parent":str(task.id) if len(proofs)>1 else None,
        "epoch":row.epoch,"generation":row.execution_generation,"deployment_generation":row.deployment_generation,
        "completed":list(row.completed_nodes),"checkpoints":proofs,"original_wait":row.receipt['original_wait'],
        "transaction":"committed","effects":[{'key':e.operation_key,'id':str(e.id)} for e in effects],
        "message":dict(message),"locks":"released_after_commit","protocol":dict(PROTOCOL),"short_stage":progress['stage'] if progress else None,"waiting_reason":waiting,"deployment_id":row.receipt["deployment_id"],"image_ids":row.receipt["image_ids"]}
    row.receipt=receipt
    row.execution_generation += 1
    row.owner_token=None
    row.state='waiting' if waiting else 'paused'
    if waiting:
        if task.status in {'queued','running'}:
            task.status=waiting if waiting in {'awaiting_plan','awaiting_review','cancelled'} else 'paused'
    else:
        task.status='paused'
        task.error='maintenance'
    receipt['status']=task.status
    return receipt


def confirm_exception(exc):
    scope=exc.scope
    if scope is None:
        return None
    from myink.db import tenant_session
    with tenant_session(scope.project_id) as db:
        kind='graph' if exc.checkpoints else 'short'
        return confirm_pause(db,scope.task_id,{'kind':kind,'records':exc.checkpoints},
            {'task_id':scope.task_id,'owner':scope.owner,'generation':scope.generation,'stage':exc.stage})


def expire_unconfirmed(db, task_id, *, now=None):
    _, task, row=_locked(db,task_id)
    if row.state!='pause_requested' or (now if now is not None else time.time()) < row.requested_at+900:
        raise ValueError('pause deadline has not elapsed')
    row.state='interruption_unconfirmed'
    row.execution_generation += 1
    row.owner_token=None
    # Do not settle/refund model reservations or call a force kill safe.
    return {'task_id':str(task.id),'state':row.state,'candidate_allowed':False}


def candidate_allowed(db, epoch):
    lock_maintenance(db)
    from sqlalchemy import text
    return not db.scalar(text("SELECT coalesce(sum(executions),0) FROM public.maintenance_execution_counts WHERE epoch=:epoch AND state IN ('pause_requested','interruption_unconfirmed')"),{'epoch':epoch})


def resume_maintenance_tasks(db, epoch: str, expected_generation: int) -> list[dict]:
    control=lock_maintenance(db)
    if control['epoch']!=epoch or control['generation']!=expected_generation or control['admission_closed'] or control['consumer_blocked']:
        raise ValueError('stale or closed maintenance resume')
    ids=list(db.scalars(select(MaintenanceExecution.task_id).where(MaintenanceExecution.epoch==epoch)))
    resumed=[]
    from myink.models.task_budget import TaskBudget
    for tid in ids:
        _,task,row=_locked(db,tid)
        budget=db.scalar(select(TaskBudget).where(TaskBudget.task_id==tid).with_for_update())
        if row.state!='paused' or row.deployment_generation!=expected_generation or task.status!='paused' or task.error!='maintenance' or (budget and budget.pause_reason):
            continue
        validate_compatibility(row.receipt.get('protocol',{}))
        if row.execution_generation!=row.receipt['generation']+1 or row.owner_token or row.active_nodes:
            continue
        task.status='queued'
        task.error=None
        row.state='running'
        resumed.append(dict(row.receipt))
    return resumed
