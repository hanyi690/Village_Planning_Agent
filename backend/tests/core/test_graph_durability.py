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
    state["context_version"] = "7"
    state["context_fingerprint"] = "sha256:test"
    state["context_ref"] = {"session_id": "run-1", "version": "7"}
    ref = store_artifact(state, "planned_state", "execute", "PlannedState", {"parcels": [1]})
    state["artifact_refs"] = {"planned_state": ref}
    loaded = load_artifact(state, "planned_state")
    assert loaded["parcels"] == [1]


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
    from app.agent.plan_state.state import AgentState, create_initial_state

    # These typed objects must never be persisted as initial-state defaults.
    # They are either stored via artifact_refs, or (for the EXECUTE subgraph
    # formal-mount channels) only declared as optional top-level schema fields
    # that are populated transiently and never written into create_initial_state.
    removed_fields = {
        "delivery_manifest", "planning_program", "intent",
        "grounding_result", "site_selection", "execution_plan",
        "parcel_changeset", "planned_state", "validation_report",
        "reconciliation_report", "allocated_geojson", "render_result",
        "grounding_result_ref", "site_selection_ref", "parcel_changeset_ref",
        "planned_state_ref", "validation_report_ref", "reconciliation_report_ref",
        "l3_program_ref",
    }
    annotations = set(AgentState.__annotations__.keys())
    # Yielding defaults: the transient EXECUTE subgraph channels are allowed as
    # schema annotations (LangGraph maps subgraph state by field name) but must
    # not leak into the initial checkpoint state.
    allowed_transient = {
        "intent", "site_selection", "execution_plan",
        "parcel_changeset", "planned_state", "allocated_geojson",
    }
    init_state = create_initial_state("run-durability", "v", "data")
    for field in removed_fields:
        if field in allowed_transient:
            assert field not in init_state, (
                f"{field} must not be a create_initial_state default"
            )
            continue
        assert field not in annotations, f"{field} should be removed from AgentState"


def test_state_has_context_fingerprint_and_bootstrap_flag():
    from app.agent.plan_state.state import AgentState

    annotations = set(AgentState.__annotations__.keys())
    assert "context_fingerprint" in annotations
    assert "bootstrap_context_done" in annotations


def test_bootstrap_context_node_sets_version_and_fingerprint():
    import asyncio
    from app.agent.bootstrap.context_bootstrap import bootstrap_context_node
    from unittest.mock import patch, AsyncMock, MagicMock

    state = {
        "session_id": "test-boot-1",
        "config": {"village_name": "TestVillage"},
        "context_version": "",
        "context_fingerprint": "",
        "context_ref": {"session_id": "test-boot-1", "version": ""},
        "bootstrap_context_done": False,
    }

    mock_context = AsyncMock()
    mock_context.version = 1
    mock_context.session_id = "test-boot-1"
    mock_context.snapshot_meta = MagicMock(return_value={"session_id": "test-boot-1", "version": 1})

    with patch(
        "app.agent.bootstrap.context_bootstrap.build_planning_context",
        new_callable=AsyncMock,
        return_value=mock_context,
    ):
        result = asyncio.run(bootstrap_context_node(state))

    assert result["context_version"] == "1"
    assert result["context_fingerprint"] != ""
    assert result["bootstrap_context_done"] is True
    assert result["context_ref"]["version"] == "1"


def test_bootstrap_context_is_idempotent_when_already_done():
    import asyncio
    from app.agent.bootstrap.context_bootstrap import bootstrap_context_node
    from unittest.mock import AsyncMock, MagicMock, patch

    state = {
        "session_id": "test-boot-2",
        "config": {"village_name": "TestVillage"},
        "context_version": "1",
        "context_fingerprint": "sha256:existing",
        "context_ref": {"session_id": "test-boot-2", "version": "1"},
        "bootstrap_context_done": True,
    }
    context = MagicMock(version=1, snapshot_meta=MagicMock(return_value={"version": 1}))
    with patch(
        "app.agent.bootstrap.context_bootstrap.build_planning_context",
        new_callable=AsyncMock,
        return_value=context,
    ):
        result = asyncio.run(bootstrap_context_node(state))
    assert result["context_version"] == "1"


def test_build_execute_agent_graph_accepts_checkpointer():
    from langgraph.checkpoint.memory import MemorySaver
    from app.agent.execute.execute_agent import build_execute_agent_graph

    checkpointer = MemorySaver()
    graph = build_execute_agent_graph(checkpointer=checkpointer)
    assert graph is not None


def test_checkpoint_state_has_no_geojson_or_full_business_objects():
    from app.agent.plan_state.state import create_initial_state

    state = create_initial_state("run-budget-1", "v", "data")
    state["context_version"] = "1"
    state["context_fingerprint"] = "sha256:test"
    state["context_ref"] = {"session_id": "run-budget-1", "version": "1"}
    state["bootstrap_context_done"] = True

    forbidden_keys = {
        "allocated_geojson", "render_result",
        "planned_state", "parcel_changeset", "grounding_result",
        "site_selection", "validation_report", "reconciliation_report",
        "delivery_manifest", "planning_program", "intent",
        "execution_plan",
        "grounding_result_ref", "site_selection_ref", "parcel_changeset_ref",
        "planned_state_ref", "validation_report_ref", "reconciliation_report_ref",
        "l3_program_ref",
    }
    for key in forbidden_keys:
        assert key not in state, f"checkpoint must not contain '{key}'"


def test_artifact_refs_round_trip_through_checkpoint():
    from app.agent.bootstrap.artifact_runtime import store_artifact, load_artifact
    from app.agent.plan_state.state import create_initial_state
    import json
    import tempfile
    import os
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("app.agent.bootstrap.artifact_runtime.FilesystemArtifactStore") as mock_store_cls:
            from app.services.artifact_store import FilesystemArtifactStore
            real_store = FilesystemArtifactStore(base_dir=tmp_dir)
            mock_store_cls.return_value = real_store
            mock_store_cls.side_effect = lambda *a, **kw: real_store

            state = create_initial_state("run-rt-1", "v", "data")
            state["context_version"] = "1"
            state["context_fingerprint"] = "sha256:rt"
            state["context_ref"] = {"session_id": "run-rt-1", "version": "1"}

            ref = store_artifact(state, "planned_state", "execute", "PlannedState", {"parcels": [1, 2, 3]})
            state["artifact_refs"] = {"planned_state": ref}

            serialized = json.dumps(state, default=str, sort_keys=True)
            deserialized = json.loads(serialized)
            deserialized["context_fingerprint"] = state["context_fingerprint"]

            loaded = load_artifact(deserialized, "planned_state")
            assert loaded == {"parcels": [1, 2, 3]}


def test_task_supervisor_tracks_and_cancels_tasks():
    import asyncio
    from app.services.task_supervisor import TaskSupervisor

    async def test():
        supervisor = TaskSupervisor()

        async def dummy():
            await asyncio.sleep(10)

        task = supervisor.create_task("session-1", dummy())
        assert supervisor.active_count == 1
        await asyncio.sleep(0)
        await supervisor.cancel("session-1")
        assert supervisor.active_count == 0

    asyncio.run(test())
