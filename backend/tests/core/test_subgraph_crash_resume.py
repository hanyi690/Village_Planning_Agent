"""Validate the official subgraph crash-resume mechanic used by
PlanningRuntimeService.resume_from_deepest_checkpoint.

LangGraph 1.2.9 behavior (verified against context7 + local experiment):
- A node that raises inside a compiled subgraph leaves the subgraph task pending;
  ``get_state(config, subgraphs=True)`` exposes the subgraph config (checkpoint_ns).
- Resuming from the deepest namespace checkpoint completes the run and reuses the
  previously persisted state contributions (the final state is consistent); node
  functions inside the subgraph re-execute from the namespace entry after an
  exception, so callers must keep stage side effects idempotent (CAS artifacts
  are content-addressed, and spatial_chain contains no LLM calls).
- The parent-level pre-subgraph checkpoint is preserved, so L1-L3 LLM work is
  never repeated on crash resume.
"""

from __future__ import annotations

from typing import TypedDict

import pytest

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


class State(TypedDict):
    log: list[str]
    value: str


def _make_graph(run_counter: dict):
    def node_a(state: State) -> dict:
        run_counter["a"] = run_counter.get("a", 0) + 1
        return {"log": [*state.get("log", []), "a"], "value": "from_a"}

    def node_b(state: State) -> dict:
        run_counter["b"] = run_counter.get("b", 0) + 1
        if run_counter["b"] == 1:
            raise RuntimeError("simulated crash inside subgraph")
        return {"log": [*state.get("log", []), "b"], "value": "from_b"}

    sub = (
        StateGraph(State)
        .add_node("a", node_a)
        .add_node("b", node_b)
        .add_edge(START, "a")
        .add_edge("a", "b")
        .add_edge("b", END)
    )
    subgraph = sub.compile(checkpointer=InMemorySaver())

    parent = (
        StateGraph(State)
        .add_node("sub", subgraph)
        .add_edge(START, "sub")
        .add_edge("sub", END)
    )
    return parent.compile(checkpointer=InMemorySaver())


def test_subgraph_crash_resume_completes_and_preserves_state():
    run_counter: dict = {}
    graph = _make_graph(run_counter)
    config = {"configurable": {"thread_id": "t1"}}

    with pytest.raises(RuntimeError, match="simulated crash"):
        graph.invoke({"log": [], "value": ""}, config)

    # Parent snapshot with subgraphs=True exposes the pending subgraph task.
    parent_snap = graph.get_state(config, subgraphs=True)
    tasks = parent_snap.tasks
    assert tasks, "expected a pending subgraph task after the crash"
    sub_config = tasks[0].state.config
    assert sub_config["configurable"].get("checkpoint_ns"), "expected checkpoint_ns"

    # The deepest checkpoint in that namespace carries the pre-crash state.
    resolved = graph.get_state(sub_config)
    assert resolved.next == ("b",)
    assert resolved.values["log"] == ["a"]

    # Resume from the resolved checkpoint: run completes, final state is
    # consistent, and no exception is re-raised.
    result = graph.invoke(None, resolved.config)
    assert result["log"] == ["a", "b"]
    assert result["value"] == "from_b"
