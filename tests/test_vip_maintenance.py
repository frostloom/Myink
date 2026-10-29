"""Batch slicing must retain the graph identity needed for durable pause proof."""
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import InMemorySaver

from myink.maintenance_pause import MaintenancePaused
from myink.worker.scheduling import invoke_batch_slice


def test_batch_slice_pause_retains_checkpoint_identity():
    class State(TypedDict):
        position: int

    def pause(state):
        raise MaintenancePaused('slice')

    graph = StateGraph(State)
    graph.add_node('bridge', pause)
    graph.add_edge(START, 'bridge')
    graph.add_edge('bridge', END)
    compiled = graph.compile(checkpointer=InMemorySaver())
    config = {'configurable': {'thread_id': 'maintenance-slice'}, 'recursion_limit': 64}
    with pytest.raises(MaintenancePaused) as caught:
        invoke_batch_slice(compiled, {'position': 0}, config)
    assert caught.value.checkpoints == [{'graph': compiled, 'thread_id': 'maintenance-slice'}]
