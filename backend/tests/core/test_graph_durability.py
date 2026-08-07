from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing import TypedDict

from app.agent.bootstrap.artifact_runtime import store_artifact, load_artifact
from app.agent.plan_state.state import create_initial_state


class State(TypedDict, total=False):
    value: int
    answer: str


def test_parent_checkpointer_and_interrupt_replay():
    calls = []

    def child(state):
        calls.append("child")
        return {"value": state.get("value", 0) + 1}

    def pause(state):
        answer = interrupt({"question": "continue"})
        return {"answer": answer}

    child_graph = StateGraph(State)
    child_graph.add_node("child", child)
    child_graph.add_edge(START, "child")
    child_graph.add_edge("child", END)
    compiled_child = child_graph.compile()

    parent = StateGraph(State)
    parent.add_node("child", compiled_child)
    parent.add_node("pause", pause)
    parent.add_edge(START, "child")
    parent.add_edge("child", "pause")
    parent.add_edge("pause", END)
    graph = parent.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "durability"}}
    first = graph.invoke({"value": 0}, config=config)
    assert first["__interrupt__"]
    resumed = graph.invoke(Command(resume="ok"), config=config)
    assert resumed["answer"] == "ok"
    assert calls == ["child"]


def test_checkpoint_state_contains_refs_not_payload():
    state = create_initial_state("run-1", "v", "data")
    state["context_ref"] = {"session_id": "run-1", "version": "7"}
    ref = store_artifact(state, "planned_state", "execute", "PlannedState", {"parcels": [1]})
    state["artifact_refs"] = {"planned_state": ref}
    assert state["planned_state"] is None
    assert load_artifact(state, "planned_state")["parcels"] == [1]


def test_artifact_ref_carries_context_fingerprint():
    from app.modules.ports.artifact_store import ArtifactRef

    ref = ArtifactRef(
        context_version="1",
        context_fingerprint="sha256:abc123",
        artifact_id="test-1",
        module="parse",
        run_id="run-1",
    )
    assert ref.context_fingerprint == "sha256:abc123"
    dumped = ref.model_dump(mode="json")
    assert "context_fingerprint" in dumped


def test_store_and_load_artifact_with_fingerprint():
    from app.agent.bootstrap.artifact_runtime import store_artifact, load_artifact

    state = create_initial_state("run-fp-1", "v", "data")
    state["context_version"] = "1"
    state["context_fingerprint"] = "sha256:abc"
    state["context_ref"] = {"session_id": "run-fp-1", "version": "1"}
    ref = store_artifact(state, "planned_state", "execute", "PlannedState", {"x": 1})
    assert ref["context_fingerprint"] == "sha256:abc"
    state["artifact_refs"] = {"planned_state": ref}

    loaded = load_artifact(state, "planned_state")
    assert loaded == {"x": 1}


def test_load_artifact_rejects_fingerprint_mismatch():
    from app.agent.bootstrap.artifact_runtime import store_artifact, load_artifact, ArtifactReplayError
    import pytest

    state = create_initial_state("run-fp-2", "v", "data")
    state["context_version"] = "1"
    state["context_fingerprint"] = "sha256:original"
    state["context_ref"] = {"session_id": "run-fp-2", "version": "1"}
    ref = store_artifact(state, "planned_state", "execute", "PlannedState", {"x": 1})
    state["artifact_refs"] = {"planned_state": ref}

    state["context_fingerprint"] = "sha256:tampered"
    with pytest.raises(ArtifactReplayError, match="fingerprint"):
        load_artifact(state, "planned_state")


def test_state_has_no_full_typed_business_objects():
    from app.agent.plan_state.state import AgentState

    removed_fields = {
        "delivery_manifest", "planning_program", "intent",
        "grounding_result", "site_selection", "execution_plan",
        "parcel_changeset", "planned_state", "validation_report",
        "reconciliation_report", "allocated_geojson", "render_result",
        "layout_configs",
        "grounding_result_ref", "site_selection_ref", "parcel_changeset_ref",
        "planned_state_ref", "validation_report_ref", "reconciliation_report_ref",
        "l3_program_ref",
    }
    annotations = set(AgentState.__annotations__.keys())
    for field in removed_fields:
        assert field not in annotations, f"{field} should be removed from AgentState"


def test_state_has_context_fingerprint_and_bootstrap_flag():
    from app.agent.plan_state.state import AgentState

    annotations = set(AgentState.__annotations__.keys())
    assert "context_fingerprint" in annotations
    assert "bootstrap_context_done" in annotations
