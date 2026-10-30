"""A finished failed planning checkpoint must retry, not replay its error."""
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from myink.worker.scheduling import invoke_batch_slice, slice_batches
from myink.workflow.runner import resume_thread


def test_failed_batch_plan_retries_without_resetting_saved_position():
    class State(TypedDict, total=False):
        batch_task_id: str
        position: int
        error: str | None
        batch_failed: bool
        batch_plan: dict

    plans, chapters = [], []

    def plan(state):
        plans.append(state['position'])
        if len(plans) == 1:
            return {'batch_failed': True, 'error': 'planner temporarily unavailable'}
        # Successful node_batch_plan only supplies the plan, not failure flags.
        return {'batch_plan': {'chapters': []}}

    graph = StateGraph(State)
    graph.add_node('batch_plan', plan)
    graph.add_node('chapter', lambda s: chapters.append(s['position']) or {})
    graph.add_node('bridge', lambda s: {'position': s['position'] + 1})
    graph.add_edge(START, 'batch_plan')
    graph.add_conditional_edges('batch_plan', lambda s: END if s.get('batch_failed') else 'chapter')
    graph.add_edge('chapter', 'bridge')
    graph.add_edge('bridge', 'chapter')
    compiled = graph.compile(checkpointer=InMemorySaver())
    config = {'configurable': {'thread_id': 'failed-batch-plan'}}
    initial = {'batch_task_id': 'failed-batch-plan', 'position': 2}
    assert invoke_batch_slice(compiled, initial, config)['error']
    assert not compiled.get_state(config).next

    with slice_batches():
        result = resume_thread(compiled, 'failed-batch-plan', {**initial, 'position': 0})
    assert plans == [2, 2]
    assert chapters == [2]
    assert not result.get('error')
    assert not result.get('batch_failed')
    assert result['scheduler_yield']

    with slice_batches():
        resume_thread(compiled, 'failed-batch-plan', {**initial, 'position': 0})
    assert plans == [2, 2]
    assert chapters == [2, 3]


def test_completed_batch_is_not_started_again_on_redelivery():
    class State(TypedDict):
        batch_task_id: str

    calls = []
    graph = StateGraph(State)
    graph.add_node('bridge', lambda state: calls.append(state['batch_task_id']) or {})
    graph.add_edge(START, 'bridge')
    graph.add_edge('bridge', END)
    compiled = graph.compile(checkpointer=InMemorySaver())
    state = {'batch_task_id': 'completed-batch'}
    config = {'configurable': {'thread_id': 'completed-batch'}}
    invoke_batch_slice(compiled, state, config)
    with slice_batches():
        resume_thread(compiled, 'completed-batch', state)
    assert calls == ['completed-batch']
