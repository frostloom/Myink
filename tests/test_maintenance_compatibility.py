"""B9 compatibility protocol rejects unsupported state instead of guessing."""
import importlib.util
import pytest
pytestmark = pytest.mark.pi_lab

def test_incompatible_protocol_rejected():
    rejected=False
    if importlib.util.find_spec('myink.maintenance_pause'):
        from myink.maintenance_pause import validate_compatibility
        try:
            validate_compatibility({'protocol':999,'schema':1,'effect_keys':1,'state':1})
        except ValueError:
            rejected=True
    assert rejected, 'incompatible candidate must be refused'


@pytest.mark.parametrize('identity',[{'serialization':'unsafe-new-serializer'}, {'state_family':'new-mutating-workflow'}])
def test_new_serializer_and_state_family_are_rejected(identity):
    from myink.maintenance_pause import validate_compatibility,PROTOCOL
    rejected=False
    try:validate_compatibility({**PROTOCOL,**identity})
    except ValueError:rejected=True
    assert rejected, 'unsupported serialized candidate state must be rejected'


CASES = ('chapter','short','batch','plan','review','tool')


def _runtime_identity(case):
    import sys, importlib.metadata as metadata
    from myink.maintenance_pause import PROTOCOL, READ_ONLY_TOOLS
    from myink.workflow.checkpointer import build_checkpointer
    from myink.db import get_admin_engine
    from sqlalchemy import text
    with get_admin_engine().connect() as db:
        schema=[tuple(r) for r in db.execute(text("SELECT table_name,column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name IN ('maintenance_executions','task_budget_calls','checkpoints','checkpoint_writes','checkpoint_blobs') ORDER BY table_name,ordinal_position"))]
    return {'python':sys.version,'interpreter':sys.executable,
        'packages':{p:metadata.version(p) for p in ('langgraph','langgraph-checkpoint','langgraph-checkpoint-postgres','langchain-core','psycopg','SQLAlchemy','msgpack')},
        'serializer':type(build_checkpointer().serde).__module__+'.'+type(build_checkpointer().serde).__name__,
        'schema':schema,'protocol':PROTOCOL,'state_family':case,'state_set':CASES,'effect_keys':1,'read_only_tools':sorted(READ_ONLY_TOOLS)}


def _version_graph(case,pid,tid,phase):
    from langgraph.graph import StateGraph,START,END
    from langgraph.types import interrupt
    from myink.workflow.state import ChapterState
    from myink.workflow.checkpointer import build_checkpointer
    from myink.workflow import nodes, tools, batch_graph as batch
    from myink.task_budget import budget_node,budget_tool_call
    from myink.db import tenant_session
    from test_maintenance_pause import request,chapter_state
    import uuid
    counts=[]
    original=nodes.node_persist
    def persist(state):
        counts.append(state['chapter_seq'])
        if phase=='pause' and (case!='batch' or state['chapter_seq']==2):request(pid,tid)
        values={**state,**chapter_state(pid,state['task_id'],state['chapter_seq'])}
        if case=='review':values['needs_review']=True
        return original(values)
    saver=build_checkpointer()
    if case=='batch':
        from myink.workflow.chapter_graph import build_chapter_graph
        nodes.node_persist=persist
        nodes.node_summarize=lambda s:{}
        batch.node_batch_plan=lambda s:{'batch_plan':{'chapters':[{'seq':1},{'seq':2}]}}
        batch.node_reflexion=lambda s:{}
        batch.node_global_audit=lambda s:{}
        batch.node_batch_end=lambda s:{}
        return batch.build_batch_graph(build_chapter_graph(saver,entry='persist'),saver),counts
    graph=StateGraph(ChapterState)
    if case=='plan':
        def plan(state):
            if phase=='pause':request(pid,tid)
            interrupt({'plan':'cross-version synthetic plan'})
            return {}
        graph.add_node('plan',budget_node(plan,'plan'));graph.add_edge(START,'plan');graph.add_edge('plan',END)
    else:
        graph.add_node('persist',budget_node(persist,'persist'))
        graph.add_node('next',budget_node(lambda s:{},'next'))
        graph.add_edge('persist','next');graph.add_edge('next',END)
        if case=='tool':
            def tool(state):
                with tenant_session(pid) as db:
                    value=budget_tool_call({'name':'inspect_facts','id':'version-read','arguments':{}},
                        lambda:tools.execute_tool(db,uuid.UUID(pid),'inspect_facts',{}))
                return {'tool_trace':[{'tool':'inspect_facts','result':value}]}
            graph.add_node('tool',budget_node(tool,'tool'));graph.add_edge(START,'tool');graph.add_edge('tool','persist')
        else:graph.add_edge(START,'persist')
    return graph.compile(checkpointer=saver),counts


def _worker(case,phase,tid,pid):
    import json,uuid
    from sqlalchemy import select
    from ops.pi.lab.verify import verify_test_environment
    verify_test_environment()
    from myink.db import tenant_session
    from myink.models import Task,Chapter,Fact
    from myink.models.task_budget import TaskBudgetCall,TaskBudget
    from myink.maintenance_pause import (MaintenancePaused,invoke_graph,confirm_exception,resume_maintenance_tasks,
        validate_compatibility,PROTOCOL,execution_view)
    from myink.task_budget import bind_task_budget,save_short_progress
    from myink.workflow.short_runner import persist_short_story
    from myink.workflow.runner import resume_thread
    from test_maintenance_pause import request,chapter_state
    validate_compatibility({**PROTOCOL,'state_family':case,'serialization':'jsonplus'})
    graph,counts=_version_graph(case,pid,tid,phase)
    config={'configurable':{'thread_id':tid}}
    receipt=None
    if phase=='pause':
        with bind_task_budget(tid,'version-pause'):
            try:
                if case=='short':
                    result={'chapters':[{'chapter_seq':1,'title':'one','body':'cross-version'}]}
                    save_short_progress(tid,'complete',{'result':result});request(pid,tid)
                    persist_short_story(project_id=pid,result=result)
                else:
                    state=({'project_id':pid,'batch_task_id':tid,'size':2,'position':0,'start_chapter':1}
                           if case=='batch' else chapter_state(pid,tid))
                    invoke_graph(graph,state,config)
            except MaintenancePaused as exc:
                caught=exc
            else:raise AssertionError('maintenance did not pause')
        receipt=confirm_exception(caught)
    else:
        with tenant_session(pid) as db:
            before=execution_view(db,tid)['receipt']
            resumed=resume_maintenance_tasks(db,'b9-test',9)
            if case in {'plan','review'}:
                assert not resumed
                assert db.get(Task,uuid.UUID(tid)).status==('awaiting_plan' if case=='plan' else 'awaiting_review')
                receipt=before
            else:assert tid in [r['task_id'] for r in resumed]
        if case not in {'plan','review'}:
            with bind_task_budget(tid,'version-resume'):
                if case=='short':
                    from myink.task_budget import load_short_progress
                    result=load_short_progress(tid)['result']
                    assert persist_short_story(project_id=pid,result=result)==1
                    assert persist_short_story(project_id=pid,result=result)==1
                else:resume_thread(graph,tid,{})
    with tenant_session(pid) as db:
        chapters=list(db.scalars(select(Chapter).where(Chapter.project_id==uuid.UUID(pid))))
        facts=list(db.scalars(select(Fact).where(Fact.project_id==uuid.UUID(pid))))
        effects=list(db.scalars(select(TaskBudgetCall).where(TaskBudgetCall.task_id==uuid.UUID(tid),TaskBudgetCall.operation_key.like('effect:%'))))
        tools=list(db.scalars(select(TaskBudgetCall).where(TaskBudgetCall.task_id==uuid.UUID(tid),TaskBudgetCall.operation_key.like('tool:%'))))
        budget=db.get(TaskBudget,uuid.UUID(tid))
        budget_state={'limits':budget.limits,'requests_used':budget.requests_used,'reserved':budget.cost_reserved_micros}
    expected=0 if case=='plan' else 2 if case=='batch' else 1
    if phase=='resume' or case!='short':assert len(chapters)==expected
    if case in {'chapter','batch','tool'}:assert len(facts)==expected
    if case=='short' and phase=='resume':assert len(effects)==1 and chapters[0].version==1
    if case=='tool':assert len(tools)==1
    if phase=='resume':assert counts==[]
    snapshot=graph.get_state(config) if case!='short' else None
    return {'case':case,'phase':phase,'task_id':tid,'project_id':pid,'receipt':receipt,
        'chapter_count':len(chapters),'memory_count':len(facts),'effect_count':len(effects),'tool_count':len(tools),
        'versions':[c.version for c in chapters],'persist_calls':counts,'checkpoint_id':snapshot.config['configurable']['checkpoint_id'] if snapshot and snapshot.config else None,
        'next_node':list(snapshot.next) if snapshot else ['short_persist'] if phase=='pause' else [],
        'budget':budget_state,'runtime':_runtime_identity(case)}


@pytest.mark.parametrize('case',CASES)
@pytest.mark.parametrize('direction',[('stable','candidate'),('candidate','stable')])
def test_two_distinct_executable_versions_restore_durable_state(pause_lab,budget_task,case,direction):
    import json,os,subprocess,sys,hashlib
    from pathlib import Path
    from myink.task_budget import ensure_task_budget
    from ops.pi.lab.verify import verify_test_environment
    verify_test_environment()
    registry=json.loads(Path('/opt/myink-pi-lab/b9-versions.json').read_text())
    assert registry['stable']['commit']!=registry['candidate']['commit']
    assert registry['stable']['executable_sha256']!=registry['candidate']['executable_sha256']
    tid,pid,uid=budget_task;ensure_task_budget(tid,pid,uid,{'max_requests':20})
    results=[]
    for phase,label in zip(('pause','resume'),direction):
        identity=registry[label]
        root=Path('/opt/myink-pi-lab/versions')/identity['commit']
        source=root/'src/myink/maintenance_pause.py'
        assert hashlib.sha256(source.read_bytes()).hexdigest()==identity['executable_sha256']
        env=dict(os.environ);env['PYTHONPATH']=str(root/'src')+':'+str(root/'tests')+':'+str(root)
        completed=subprocess.run([sys.executable,str(root/'tests/test_maintenance_compatibility.py'),case,phase,tid,pid],
            cwd=root,env=env,text=True,capture_output=True,timeout=120)
        assert completed.returncode==0,completed.stdout+completed.stderr
        result=json.loads(next(l.removeprefix('B9_RESULT:') for l in completed.stdout.splitlines() if l.startswith('B9_RESULT:')))
        assert result['runtime']['state_family']==case
        results.append({**result,'source':identity})
    first,second=results
    for key in ('python','interpreter','packages','schema','serializer','protocol','effect_keys','state_set','read_only_tools'):
        assert first['runtime'][key]==second['runtime'][key]
    assert first['budget']==second['budget']
    if case in {'chapter','tool'}:assert second['chapter_count']==second['memory_count']==second['effect_count']==1
    if case=='batch':assert second['chapter_count']==second['memory_count']==second['effect_count']==2
    if case in {'plan','review'}:
        assert first['checkpoint_id']==second['checkpoint_id'] and first['next_node']==second['next_node']
    evidence=Path('/mnt/e/tools/myink-pi/evidence')/f"b9-version-{direction[0]}-to-{direction[1]}-{case}.json"
    evidence.write_text(json.dumps(results,indent=2))


from test_maintenance_pause import pause_lab,budget_task

if __name__=='__main__':
    import sys,json
    print('B9_RESULT:'+json.dumps(_worker(*sys.argv[1:]),default=str))
