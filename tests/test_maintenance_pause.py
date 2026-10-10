"""Durable maintenance node boundaries in the owned synthetic lab."""
import importlib.util
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import select, text
from myink.db import get_admin_engine, ensure_maintenance_schema, tenant_session
from myink.models import Task
from myink.models.task_budget import TaskBudgetCall
from myink.task_budget import bind_task_budget, ensure_task_budget, budget_node, budget_tool_call, TaskBudgetUnavailable
from test_task_budget import budget_task
pytestmark = pytest.mark.pi_lab

@pytest.fixture
def pause_lab():
    from ops.pi.lab.verify import verify_test_environment
    verify_test_environment()
    ensure_maintenance_schema()
    with get_admin_engine().begin() as db:
        db.execute(text("UPDATE maintenance_control SET epoch='b9-test',generation=9,admission_closed=false,consumer_blocked=false WHERE id=1"))
    yield
    with get_admin_engine().begin() as db:
        db.execute(text("UPDATE maintenance_control SET admission_closed=false,consumer_blocked=false WHERE id=1"))

def request(pid, tid):
    if importlib.util.find_spec("myink.maintenance_pause"):
        from myink.maintenance_pause import request_pause, execution_view
        with tenant_session(pid) as db:
            request_pause(db, 'b9-test', tid, execution_view(db, tid)['execution_generation'])
    else:
        # Baseline uses real existing entrypoints; no missing-module collection RED.
        with tenant_session(pid) as db:
            task=db.get(Task, uuid.UUID(tid))
            task.payload={**task.payload, '_maintenance_request':'b9-test'}

def test_request_finishes_authorized_node_stops_next(pause_lab,budget_task):
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    completed=[]
    def first(state):
        request(pid,tid)
        completed.append('first')
        return {}
    stopped=False
    with bind_task_budget(tid,'first-owner'):
        budget_node(first)({'task_id':tid})
        try:
            budget_node(lambda state: completed.append('next'), 'next')({'task_id':tid})
        except Exception as exc:
            assert type(exc).__name__=='MaintenancePaused'
            stopped=True
    assert completed==['first']
    assert stopped

def test_short_persist_has_transactional_receipt(pause_lab,budget_task):
    from myink.workflow.short_runner import persist_short_story
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    result={'chapters':[{'chapter_seq':1,'title':'one','body':'synthetic body'}]}
    with bind_task_budget(tid,'short-owner'):
        assert persist_short_story(project_id=pid,result=result)==1
    with tenant_session(pid) as db:
        receipts=list(db.scalars(select(TaskBudgetCall).where(TaskBudgetCall.task_id==uuid.UUID(tid),TaskBudgetCall.operation_key.like('effect:%short_persist%'))))
        assert len(receipts)==1
        assert receipts[0].response['persisted']==1

def test_unknown_effectful_tool_fails_closed(pause_lab,budget_task):
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    effects=[]
    with bind_task_budget(tid,'tool-owner'):
        try:
            budget_tool_call({'name':'new_mutating_tool'},lambda: effects.append('sent'))
        except TaskBudgetUnavailable:
            pass
    assert effects==[]


def graph_fixture(pid, tid, *, request_after=True):
    from langgraph.graph import StateGraph, START, END
    from myink.workflow.checkpointer import build_checkpointer
    from myink.workflow import nodes
    from myink.workflow.state import ChapterState
    graph=StateGraph(ChapterState)
    def persist(state):
        if request_after:
            request(pid,tid)
        return nodes.node_persist(state)
    graph.add_node('persist',budget_node(persist,'persist'))
    graph.add_node('next',budget_node(lambda state: {'draft':state['draft']},'next'))
    graph.add_edge(START,'persist');graph.add_edge('persist','next');graph.add_edge('next',END)
    return graph.compile(checkpointer=build_checkpointer())


def chapter_state(pid,tid,seq=1):
    return {'project_id':pid,'task_id':tid,'chapter_seq':seq,'draft':f'chapter {seq}',
            'candidates':[{'kind':'fact','payload':{'content':f'fact {seq}','category':'test','is_hard':True},'confidence':1.0}]}


def confirmed_graph(pid,tid):
    from myink.maintenance_pause import MaintenancePaused, invoke_graph, confirm_exception
    graph=graph_fixture(pid,tid)
    config={'configurable':{'thread_id':tid}}
    with bind_task_budget(tid,'graph-owner'):
        with pytest.raises(MaintenancePaused) as caught:
            invoke_graph(graph,chapter_state(pid,tid),config)
    receipt=confirm_exception(caught.value)
    assert receipt['checkpoints'][0]['next_node']==['next']
    assert receipt['checkpoints'][0]['checkpoint_id']
    assert receipt['checkpoints'][0]['pending_writes']
    assert receipt['effects']
    return graph,receipt


def test_resume_does_not_repeat_completed_effect(pause_lab,budget_task):
    from myink.maintenance_pause import resume_maintenance_tasks
    from myink.models import Chapter, Fact
    from myink.workflow.runner import resume_thread
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    graph,receipt=confirmed_graph(pid,tid)
    with tenant_session(pid) as db:
        assert [r['task_id'] for r in resume_maintenance_tasks(db,'b9-test',9)]==[tid]
    with bind_task_budget(tid,'resumed-owner'):
        result=resume_thread(graph,tid,{'position':0})
    assert result['draft']=='chapter 1'
    with tenant_session(pid) as db:
        assert len(list(db.scalars(select(Chapter).where(Chapter.project_id==uuid.UUID(pid)))))==1
        assert len(list(db.scalars(select(Fact).where(Fact.project_id==uuid.UUID(pid)))))==1
        assert db.scalar(select(Chapter).where(Chapter.project_id==uuid.UUID(pid))).version==1
        assert len(list(db.scalars(select(TaskBudgetCall).where(TaskBudgetCall.task_id==uuid.UUID(tid),TaskBudgetCall.operation_key.like('effect:%')))))==1


@pytest.mark.parametrize('wait', ['cancelled','paused','awaiting_plan','awaiting_review','budget'])
def test_user_budget_and_review_wait_not_resumed(pause_lab,budget_task,wait):
    from myink.maintenance_pause import resume_maintenance_tasks
    from myink.models.task_budget import TaskBudget
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    graph,receipt=confirmed_graph(pid,tid)
    with tenant_session(pid) as db:
        task=db.get(Task,uuid.UUID(tid))
        if wait=='budget':
            db.get(TaskBudget,uuid.UUID(tid)).pause_reason='request_limit'
        else:
            task.status=wait
            task.error='user wait'
    with tenant_session(pid) as db:
        assert resume_maintenance_tasks(db,'b9-test',9)==[]
        assert db.get(Task,uuid.UUID(tid)).status==('paused' if wait=='budget' else wait)


def test_unconfirmed_interruption_blocks_candidate(pause_lab,budget_task):
    from myink.maintenance_pause import expire_unconfirmed, candidate_allowed, fence_effect
    from myink.task_budget import reserve_attempt, finish_attempt
    from myink.models.task_budget import TaskBudget, TaskBudgetAttempt
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    with bind_task_budget(tid,'lost-owner'):
        permit=reserve_attempt('unknown-model',[{'role':'user','content':'synthetic'}],20)
        finish_attempt(permit)
        request(pid,tid)
    with tenant_session(pid) as db:
        assert not candidate_allowed(db,'b9-test')
        expire_unconfirmed(db,tid,now=__import__('time').time()+901)
    with tenant_session(pid) as db:
        assert not candidate_allowed(db,'b9-test')
        budget=db.get(TaskBudget,uuid.UUID(tid))
        assert budget.cost_reserved_micros>0
        assert db.scalar(select(TaskBudgetAttempt).where(TaskBudgetAttempt.task_id==uuid.UUID(tid))).status=='unknown'
    from myink.maintenance_pause import Execution, _SCOPE
    token=_SCOPE.set(Execution(tid,pid,'lost-owner',1))
    try:
        with tenant_session(pid) as db:
            with pytest.raises(TaskBudgetUnavailable): fence_effect(db)
    finally:
        _SCOPE.reset(token)


def test_short_resume_has_one_persist_and_durable_progress(pause_lab,budget_task):
    from myink.maintenance_pause import MaintenancePaused, confirm_exception, resume_maintenance_tasks
    from myink.task_budget import save_short_progress, load_short_progress
    from myink.workflow import short_runner
    from myink.models import Chapter, ChapterVersion
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    result={'chapters':[{'chapter_seq':1,'title':'one','body':'synthetic'}]}
    with bind_task_budget(tid,'short-first'):
        save_short_progress(tid,'complete',{'result':result})
        request(pid,tid)
        with pytest.raises(MaintenancePaused) as caught:
            short_runner.persist_short_story(project_id=pid,result=result)
    receipt=confirm_exception(caught.value)
    assert receipt['short_stage']=='complete'
    assert receipt['effects']==[]
    with tenant_session(pid) as db: resume_maintenance_tasks(db,'b9-test',9)
    with bind_task_budget(tid,'short-second'):
        assert short_runner.persist_short_story(project_id=pid,result=result)==1
        assert short_runner.persist_short_story(project_id=pid,result=result)==1
        assert load_short_progress(tid)['stage']=='persisted'
    with tenant_session(pid) as db:
        assert db.scalar(select(Chapter).where(Chapter.project_id==uuid.UUID(pid))).version==1
        assert list(db.scalars(select(ChapterVersion).where(ChapterVersion.project_id==uuid.UUID(pid))))==[]


def test_batch_child_parent_checkpoint_matches_position(pause_lab,budget_task,monkeypatch):
    from myink.workflow import nodes, batch_graph as batch
    from myink.workflow.chapter_graph import build_chapter_graph
    from myink.workflow.checkpointer import build_checkpointer
    from myink.maintenance_pause import MaintenancePaused, invoke_graph, confirm_exception, resume_maintenance_tasks
    from myink.workflow.runner import resume_thread
    from myink.models import Chapter, Fact
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    original=nodes.node_persist
    counts=[]
    def persist(state):
        counts.append(state['chapter_seq'])
        if state['chapter_seq']==2:request(pid,tid)
        return original({**state,**chapter_state(pid,state['task_id'],state['chapter_seq'])})
    monkeypatch.setattr(nodes,'node_persist',persist)
    monkeypatch.setattr(nodes,'node_summarize',lambda s:{})
    monkeypatch.setattr(batch,'node_batch_plan',lambda s:{'batch_plan':{'chapters':[{'seq':1},{'seq':2}]}})
    for name in ['node_reflexion','node_global_audit','node_batch_end']:
        monkeypatch.setattr(batch,name,lambda s:{})
    saver=build_checkpointer()
    graph=batch.build_batch_graph(build_chapter_graph(saver,entry='persist'),saver)
    state={'project_id':pid,'batch_task_id':tid,'position':0,'size':2,'start_chapter':1}
    with bind_task_budget(tid,'batch-first'):
        with pytest.raises(MaintenancePaused) as caught: invoke_graph(graph,state,{'configurable':{'thread_id':tid}})
    receipt=confirm_exception(caught.value)
    assert len(receipt['checkpoints'])==2
    parent=next(p for p in receipt['checkpoints'] if p['thread_id']==tid)
    assert parent['parent_position']==1
    assert parent['next_node']==['chapter']
    with tenant_session(pid) as db:resume_maintenance_tasks(db,'b9-test',9)
    with bind_task_budget(tid,'batch-second'):resume_thread(graph,tid,state)
    assert counts==[1,2]
    with tenant_session(pid) as db:
        assert len(list(db.scalars(select(Chapter).where(Chapter.project_id==uuid.UUID(pid)))))==2
        assert len(list(db.scalars(select(Fact).where(Fact.project_id==uuid.UUID(pid)))))==2


def test_tool_inventory_round_trip_and_processor_pause_propagate(pause_lab,budget_task,monkeypatch):
    from myink.workflow import nodes, tools
    from myink.maintenance_pause import READ_ONLY_TOOLS, MaintenancePaused
    from myink.worker import processor
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    assert READ_ONLY_TOOLS==set(tools._EXECUTORS)
    with bind_task_budget(tid,'read-owner'):
        with tenant_session(pid) as db:
            result=budget_tool_call({'name':'inspect_facts','id':'read1','arguments':{}},lambda:tools.execute_tool(db,uuid.UUID(pid),'inspect_facts',{}))
            assert 'facts' in result
    exc=MaintenancePaused(scope=None)
    def stop(body):raise exc
    monkeypatch.setattr(processor,'_dispatch',stop)
    monkeypatch.setattr(processor,'_pub_status',lambda *a,**k:None)
    with pytest.raises(MaintenancePaused) as caught:processor._run_bound({},tid,'chapter_generate',pid)
    assert caught.value is exc


def test_confirm_requires_quiescence_and_real_checkpoint(pause_lab,budget_task):
    from myink.maintenance_pause import confirm_pause, authorized_node, execution_view
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    with bind_task_budget(tid,'active-owner'):
        with authorized_node('active'):
            request(pid,tid)
            with tenant_session(pid) as db:
                view=execution_view(db,tid)
                with pytest.raises(ValueError,match='quiescence'):
                    confirm_pause(db,tid,{'kind':'short'},{'task_id':tid,'owner':'active-owner','generation':view['execution_generation']})
        with tenant_session(pid) as db:
            with pytest.raises(ValueError,match='durable short'):
                confirm_pause(db,tid,{'kind':'short'},{'task_id':tid,'owner':'active-owner','generation':view['execution_generation']})


@pytest.mark.parametrize('wait',['cancelled','paused','awaiting_plan','awaiting_review','budget'])
def test_wait_race_keeps_reason_and_confirms_only_durable_hold(pause_lab,budget_task,wait):
    from myink.maintenance_pause import MaintenancePaused,invoke_graph,confirm_exception,candidate_allowed,resume_maintenance_tasks,execution_view
    from myink.models.task_budget import TaskBudget
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    graph=graph_fixture(pid,tid)
    with bind_task_budget(tid,'racing-owner'):
        with pytest.raises(MaintenancePaused) as caught:invoke_graph(graph,chapter_state(pid,tid),{'configurable':{'thread_id':tid}})
    with tenant_session(pid) as db:
        task=db.get(Task,uuid.UUID(tid));task.status='paused' if wait=='budget' else wait
        task.error='stronger wait'
        if wait=='budget':db.get(TaskBudget,uuid.UUID(tid)).pause_reason='request_limit'
    receipt=confirm_exception(caught.value)
    assert receipt['waiting_reason']==('request_limit' if wait=='budget' else wait)
    with tenant_session(pid) as db:
        assert candidate_allowed(db,'b9-test')
        assert execution_view(db,tid)['state']=='waiting'
        assert resume_maintenance_tasks(db,'b9-test',9)==[]
        assert db.get(Task,uuid.UUID(tid)).error=='stronger wait'


def test_actual_plan_interrupt_is_preserved_by_maintenance(pause_lab,budget_task):
    from langgraph.graph import StateGraph,START,END
    from langgraph.types import interrupt
    from myink.workflow.state import ChapterState
    from myink.workflow.checkpointer import build_checkpointer
    from myink.maintenance_pause import MaintenancePaused,invoke_graph,confirm_exception,resume_maintenance_tasks
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    def plan(state):
        request(pid,tid)
        interrupt({'plan':'synthetic plan'})
        return {}
    graph=StateGraph(ChapterState);graph.add_node('plan',budget_node(plan,'plan'))
    graph.add_edge(START,'plan');graph.add_edge('plan',END)
    graph=graph.compile(checkpointer=build_checkpointer())
    with bind_task_budget(tid,'plan-owner'):
        with pytest.raises(MaintenancePaused) as caught:invoke_graph(graph,{'task_id':tid,'project_id':pid},{'configurable':{'thread_id':tid}})
    receipt=confirm_exception(caught.value)
    assert receipt['waiting_reason']=='awaiting_plan'
    with tenant_session(pid) as db:
        assert db.get(Task,uuid.UUID(tid)).status=='awaiting_plan'
        assert resume_maintenance_tasks(db,'b9-test',9)==[]


def test_actual_registered_new_effectful_tool_is_refused(pause_lab,budget_task,monkeypatch):
    from myink.workflow import tools
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    effects=[]
    monkeypatch.setitem(tools._EXECUTORS,'new_effectful_tool',lambda *a:effects.append('sent'))
    with bind_task_budget(tid,'tool-owner'):
        with tenant_session(pid) as db:
            with pytest.raises(TaskBudgetUnavailable):
                budget_tool_call({'name':'new_effectful_tool','arguments':{}},lambda:tools.execute_tool(db,uuid.UUID(pid),'new_effectful_tool',{}))
    assert effects==[]


@pytest.mark.parametrize('drift',['generation','deployment_id','image_ids'])
def test_actual_control_drift_fences_business_transaction(pause_lab,budget_task,drift):
    from myink.task_budget import load_effect,save_effect
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    with get_admin_engine().connect() as db:before=dict(db.execute(text('SELECT * FROM maintenance_control WHERE id=1')).mappings().one())
    with bind_task_budget(tid,'drift-owner'):
        try:
            with get_admin_engine().begin() as db:
                if drift=='generation':db.execute(text('UPDATE maintenance_control SET generation=generation+1 WHERE id=1'))
                elif drift=='deployment_id':db.execute(text("UPDATE maintenance_control SET deployment_id='new-manual-deployment' WHERE id=1"))
                else:db.execute(text('UPDATE maintenance_control SET image_ids=CAST(:images AS json) WHERE id=1'),{'images':__import__('json').dumps({'worker':'new-manual-image'})})
            with tenant_session(pid) as db:
                with pytest.raises(TaskBudgetUnavailable):load_effect(db,('effect:drift','hash'))
        finally:
            with get_admin_engine().begin() as db:
                db.execute(text('UPDATE maintenance_control SET generation=:generation,deployment_id=:deployment_id,image_ids=CAST(:images AS json) WHERE id=1'),
                    {'generation':before['generation'],'deployment_id':before['deployment_id'],'images':__import__('json').dumps(before['image_ids'])})
    with tenant_session(pid) as db:
        assert not db.scalar(select(TaskBudgetCall).where(TaskBudgetCall.task_id==uuid.UUID(tid),TaskBudgetCall.operation_key=='effect:drift'))


def test_candidate_blocker_is_global_without_raw_cross_tenant_access(pause_lab,budget_task):
    from sqlalchemy.orm import Session
    from myink.maintenance_pause import candidate_allowed
    tid,pid,uid=budget_task;ensure_task_budget(tid,pid,uid,{'max_requests':20})
    with bind_task_budget(tid,'global-owner'):request(pid,tid)
    with Session(get_admin_engine()) as db:
        db.execute(text('SET LOCAL ROLE myink_app'))
        db.execute(text("SELECT set_config('app.tenant_id', :pid, true)"),{'pid':str(uuid.uuid4())})
        assert db.scalar(text('SELECT count(*) FROM maintenance_executions'))==0
        assert not candidate_allowed(db,'b9-test')


def test_actual_private_execution_roles_and_both_report_bootstraps(pause_lab,budget_task):
    from pathlib import Path
    from ops.pi.lab.verify import verify_test_environment
    from sqlalchemy.orm import Session
    from myink.maintenance_pause import request_pause,execution_view
    tid,pid,uid=budget_task;ensure_task_budget(tid,pid,uid,{'max_requests':20})
    with bind_task_budget(tid,'acl-owner'):
        with tenant_session(pid) as db:generation=execution_view(db,tid)['execution_generation']
        with get_admin_engine().begin() as db:db.execute(text('GRANT SELECT,UPDATE ON public.tasks TO myink_app'))
        with Session(get_admin_engine()) as db:
            db.execute(text('SET LOCAL ROLE myink_app'))
            db.execute(text("SELECT set_config('app.tenant_id', :pid, true)"),{'pid':pid})
            request_pause(db,'b9-test',tid,generation)
            db.commit()
    for role in ('myink_report','myink_maintenance_stats','myink_maintenance_control'):
        with get_admin_engine().begin() as db:
            db.execute(text(f'SET LOCAL ROLE {role}'))
            assert not db.scalar(text("SELECT has_table_privilege(current_user,'public.maintenance_executions','SELECT')"))
    with get_admin_engine().begin() as db:
        db.execute(text('SET LOCAL ROLE myink_maintenance_stats'))
        assert db.scalar(text('SELECT count(*) FROM maintenance_execution_counts'))>=1
    with get_admin_engine().begin() as db:
        db.execute(text('SET LOCAL ROLE myink_app'))
        assert not db.scalar(text("SELECT has_column_privilege(current_user,'public.maintenance_executions','task_id','UPDATE')"))
        assert not db.scalar(text("SELECT has_column_privilege(current_user,'public.maintenance_executions','project_id','UPDATE')"))
        assert not db.scalar(text("SELECT has_table_privilege(current_user,'public.maintenance_executions','DELETE')"))
    for name in ('scripts/create-report-role.sh','docker/initdb/01-roles.sh'):
        script=(Path(__file__).parents[1]/name).read_text()
        # Execute each changed DO block verbatim after the real blanket grant.
        block='DO $$ BEGIN'+script.split('DO $$ BEGIN',1)[1].split('END $$;',1)[0]+'END $$;'
        with get_admin_engine().begin() as db:
            db.execute(text('GRANT SELECT ON ALL TABLES IN SCHEMA public TO myink_report'))
            db.execute(text(block))
            db.execute(text('SET LOCAL ROLE myink_report'))
            assert not db.scalar(text("SELECT has_table_privilege(current_user,'public.maintenance_executions','SELECT')"))
            assert db.scalar(text('SELECT count(*) FROM projects'))>=1



def test_legacy_budgetless_late_effect_is_fenced(pause_lab,budget_task):
    from myink.maintenance_pause import expire_unconfirmed
    from myink.task_budget import load_effect,save_effect
    from myink.models import Chapter
    tid,pid,uid=budget_task
    with bind_task_budget(tid,'legacy-owner'):
        request(pid,tid)
        with tenant_session(pid) as db:expire_unconfirmed(db,tid,now=__import__('time').time()+901)
        with tenant_session(pid) as db:
            try:
                load_effect(db,('effect:legacy-late','hash'))
                db.add(Chapter(project_id=uuid.UUID(pid),chapter_seq=1,content='obsolete owner late write',status='confirmed'))
                save_effect(db,('effect:legacy-late','hash'),{'persisted':True})
            except TaskBudgetUnavailable:
                pass
    with tenant_session(pid) as db:
        assert list(db.scalars(select(Chapter).where(Chapter.project_id==uuid.UUID(pid))))==[]


def test_legacy_budgetless_checkpoint_cannot_falsely_confirm(pause_lab,budget_task):
    from myink.maintenance_pause import MaintenancePaused,invoke_graph,confirm_exception,candidate_allowed,execution_view
    tid,pid,uid=budget_task
    graph=graph_fixture(pid,tid)
    with bind_task_budget(tid,'legacy-owner'):
        with pytest.raises(MaintenancePaused) as caught:invoke_graph(graph,chapter_state(pid,tid),{'configurable':{'thread_id':tid}})
    rejected=False
    try:confirm_exception(caught.value)
    except ValueError:rejected=True
    assert rejected, 'legacy checkpoint without durable effect ledger cannot certify safe pause'
    with tenant_session(pid) as db:
        assert execution_view(db,tid)['state']=='pause_requested'
        assert not candidate_allowed(db,'b9-test')


def test_cached_short_receipt_exit_still_observes_pause(pause_lab,budget_task,monkeypatch):
    from contextlib import contextmanager
    from myink.workflow import short_runner
    from myink.maintenance_pause import MaintenancePaused,confirm_exception
    from myink.models import Chapter
    tid,pid,uid=budget_task
    ensure_task_budget(tid,pid,uid,{'max_requests':20})
    result={'chapters':[{'chapter_seq':1,'title':'one','body':'cached body'}]}
    original=short_runner.authorized_node
    @contextmanager
    def request_at_exit(stage):
        with original(stage):
            yield
            request(pid,tid)
    stopped=None
    with bind_task_budget(tid,'cached-owner'):
        assert short_runner.persist_short_story(project_id=pid,result=result)==1
        monkeypatch.setattr(short_runner,'authorized_node',request_at_exit)
        try:short_runner.persist_short_story(project_id=pid,result=result)
        except MaintenancePaused as exc:stopped=exc
    assert stopped is not None, 'cached node exit must return maintenance pause decision'
    receipt=confirm_exception(stopped)
    assert receipt['short_stage']=='persisted' and len(receipt['effects'])==1
    with tenant_session(pid) as db:
        assert db.scalar(select(Chapter).where(Chapter.project_id==uuid.UUID(pid))).version==1
