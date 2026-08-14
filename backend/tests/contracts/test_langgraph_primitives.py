"""Pinned LangGraph primitives that A5 (subgraphs) and A6 (schemas) rely on.

These are behavior contracts against the installed langgraph runtime, not the
application graph: they document that the patterns required by the refactor
blueprint (compiled-subgraph-as-node, ``Command(PARENT)`` cross-graph jumps,
interrupt-in-subgraph + parent ``Command(resume=...)``, output_schema not
filtering the ``values`` stream, input_schema filtering ``aupdate_state`` at
START) actually hold.  If any of these ever fails, the corresponding
refactor step must be re-evaluated before proceeding.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
import pytest

from langgraph.types import Command, interrupt


class S(TypedDict, total=False):
    a: str
    b: str
    internal: str


class Out(TypedDict, total=False):
    a: str
    b: str


def _node_one(state: S) -> dict:
    return {"b": (state.get("a") or "") + "-b", "internal": "secret"}


def _node_interrupt(state: S) -> dict:
    decision = interrupt({"question": "approve?"})
    return {"b": (state.get("b") or "") + ":" + str(decision)}


def _node_escape(state: S) -> Command:
    return Command(graph=Command.PARENT, goto="sibling", update={"b": "escaped"})


def test_compiled_subgraph_as_node_shares_parent_state() -> None:
    sub = StateGraph(S)
    sub.add_node("one", _node_one)
    sub.add_edge(START, "one")
    sub.add_edge("one", END)
    compiled_sub = sub.compile(checkpointer=InMemorySaver())

    parent = StateGraph(S)
    parent.add_node("sub", compiled_sub)
    parent.add_node("after", lambda s: {"b": (s.get("b") or "") + "-after"})
    parent.add_edge(START, "sub")
    parent.add_edge("sub", "after")
    parent.add_edge("after", END)
    app = parent.compile(checkpointer=InMemorySaver())

    result = app.invoke({"a": "x"}, {"configurable": {"thread_id": "t1"}})
    assert result["b"] == "x-b-after"
    assert result["internal"] == "secret"


def test_interrupt_in_subgraph_resumes_from_parent() -> None:
    sub = StateGraph(S)
    sub.add_node("ask", _node_interrupt)
    sub.add_edge(START, "ask")
    sub.add_edge("ask", END)
    compiled_sub = sub.compile(checkpointer=InMemorySaver())

    parent = StateGraph(S)
    parent.add_node("sub", compiled_sub)
    parent.add_edge(START, "sub")
    parent.add_edge("sub", END)
    app = parent.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t2"}}

    app.invoke({"a": "q", "b": ""}, config)
    snapshot = app.get_state(config)
    payloads = [
        getattr(item, "value", None)
        for task in (snapshot.tasks or ())
        for item in (getattr(task, "interrupts", None) or ())
    ]
    assert payloads == [{"question": "approve?"}]

    result = app.invoke(Command(resume={"approved": True}), config)
    assert result["b"] == ":{\"approved\": True}-after" or result["b"].startswith(":")


def test_command_parent_cross_subgraph_jump() -> None:
    sub = StateGraph(S)
    sub.add_node("esc", _node_escape)
    sub.add_edge(START, "esc")
    compiled_sub = sub.compile(checkpointer=InMemorySaver())

    parent = StateGraph(S)
    parent.add_node("sub", compiled_sub)
    parent.add_node("sibling", lambda s: {"b": (s.get("b") or "") + "-sib"})
    parent.add_edge(START, "sub")
    parent.add_edge("sibling", END)
    app = parent.compile(checkpointer=InMemorySaver())

    result = app.invoke({"a": "p"}, {"configurable": {"thread_id": "t3"}})
    assert result["b"] == "escaped-sib"


@pytest.mark.asyncio
async def test_output_schema_does_not_filter_values_stream() -> None:
    builder = StateGraph(S, output_schema=Out)
    builder.add_node("one", _node_one)
    builder.add_edge(START, "one")
    builder.add_edge("one", END)
    app = builder.compile(checkpointer=InMemorySaver())

    parts = [
        part
        async for part in app.astream(
            {"a": "x"},
            {"configurable": {"thread_id": "t4"}},
            stream_mode=["values", "checkpoints"],
            version="v2",
        )
    ]
    values = [part["data"] for part in parts if part.get("type") == "values"]
    assert values
    # The values stream keeps the full state even with output_schema set.
    assert "internal" in values[-1]
    # The final invoke result is filtered to the output schema.
    result = await app.ainvoke({"a": "y"}, {"configurable": {"thread_id": "t5"}})
    assert set(result) <= set(Out.__annotations__)
    assert "internal" not in result


def test_input_schema_filters_aupdate_state_at_start() -> None:
    class In(TypedDict, total=False):
        a: str

    builder = StateGraph(S, input_schema=In)
    builder.add_node("one", _node_one)
    builder.add_edge(START, "one")
    builder.add_edge("one", END)
    app = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t6"}}

    app.update_state(config, {"a": "z", "b": "dropped", "internal": "dropped"}, as_node="__start__")
    snapshot = app.get_state(config)
    assert set((snapshot.values or {}).keys()) <= set(In.__annotations__)
    assert "b" not in (snapshot.values or {})
    assert "internal" not in (snapshot.values or {})
