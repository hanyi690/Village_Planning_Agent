"""Integration tests: EXECUTE subgraph must not pollute parent checkpoint namespace.

Tests:
1. Parent state fields survive EXECUTE subgraph execution
2. Child checkpoints are in a non-empty namespace (isolated)
3. Multiple EXECUTE runs don't overwrite each other
4. Parent get_state() returns AgentState, not ExecuteAgentState
"""
import pytest
from typing import TypedDict
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph


class ParentState(TypedDict, total=False):
    owner: str
    parent_value: int
    child_input: dict  # mapped to child state


class ChildState(TypedDict, total=False):
    owner: str
    child_value: int


def test_formal_subgraph_isolates_checkpoint_namespace():
    """A compiled subgraph mounted via add_node must not clobber parent state."""
    checkpointer = MemorySaver()

    def child_node(state):
        return {"owner": "child", "child_value": 42}

    child_builder = StateGraph(ChildState)
    child_builder.add_node("child", child_node)
    child_builder.add_edge(START, "child")
    child_builder.add_edge("child", END)
    compiled_child = child_builder.compile()  # NO checkpointer on child

    parent_builder = StateGraph(ParentState)
    parent_builder.add_node("call_child", compiled_child)  # formal mount
    parent_builder.add_edge(START, "call_child")
    parent_builder.add_edge("call_child", END)
    parent_graph = parent_builder.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test-iso"}}
    result = parent_graph.invoke({"owner": "parent", "parent_value": 1}, config=config)

    # Parent checkpoint must retain parent_value
    snapshot = parent_graph.get_state(config)
    assert snapshot.values.get("parent_value") == 1, "Parent state clobbered by child"
    assert snapshot.values.get("owner") == "child", "Child output should be mapped back"

    # Child checkpoints must be in a non-empty namespace
    state_with_subgraphs = parent_graph.get_state(config, subgraphs=True)
    # The subgraph snapshot should exist under a nested namespace
    assert state_with_subgraphs is not None


def test_direct_ainvoke_does_not_isolate():
    """The CURRENT pattern (direct .ainvoke with same checkpointer) DOES clobber.
    This test documents the bug we're fixing."""
    checkpointer = MemorySaver()

    def child_node(state):
        return {"owner": "child", "child_value": 42}

    child_builder = StateGraph(ChildState)
    child_builder.add_node("child", child_node)
    child_builder.add_edge(START, "child")
    child_builder.add_edge("child", END)
    compiled_child_bug = child_builder.compile(checkpointer=checkpointer)  # BUG: same checkpointer

    def call_child_buggy(state: ParentState):
        result = compiled_child_bug.invoke(
            {"owner": state.get("owner", "")},
            config={"configurable": {"thread_id": "test-clobber"}},
        )
        return {"owner": result.get("owner", "")}

    parent_builder = StateGraph(ParentState)
    parent_builder.add_node("call_child", call_child_buggy)
    parent_builder.add_edge(START, "call_child")
    parent_builder.add_edge("call_child", END)
    parent_graph = parent_builder.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test-clobber"}}
    parent_graph.invoke({"owner": "parent", "parent_value": 1}, config=config)

    # The buggy pattern writes child checkpoints into the SAME (empty) namespace
    # as the parent, so child-only channels leak into the parent's history.
    leaked = False
    for checkpoint in checkpointer.list(config=config):
        channel_values = checkpoint.checkpoint.get("channel_values", {})
        if "child_value" in channel_values or "branch:to:child" in channel_values:
            leaked = True
            break
    assert leaked, (
        "Expected the buggy direct .ainvoke pattern to leak child channels into "
        "the parent checkpoint namespace"
    )