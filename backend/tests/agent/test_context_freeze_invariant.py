"""Context-freeze invariant acceptance tests.

P0-1 defensive refactor: verifies that a versioned artifact can never be
persisted without an established PlanningContext (non-empty context_version
and a matching context_ref).
"""

import pytest

from app.agent.bootstrap.layer_aggregate_node import layer_aggregate_node
from app.agent.l1_observe.aggregate import l1_aggregate


@pytest.mark.asyncio
async def test_l1_aggregate_bootstraps_context_before_persisting(monkeypatch):
    captured_states = {}

    async def fake_bootstrap(state):
        captured_states["bootstrap"] = state
        return {
            "bootstrap_context_done": True,
            "context_version": "1",
            "context_fingerprint": "sha256:abc123",
            "context_ref": {
                "session_id": state.get("session_id", ""),
                "version": "1",
            },
        }

    async def fake_l1(state, *, base_dir=".run-tmp"):
        captured_states["l1"] = state
        return {
            "l1_snapshot_ref": {
                "artifact_id": "l1-test-v1",
                "context_version": state.get("context_version", ""),
            },
            "l1_gate_decision": {"passed": True},
        }

    monkeypatch.setattr(
        "app.agent.bootstrap.context_bootstrap.bootstrap_context_node",
        fake_bootstrap,
    )
    monkeypatch.setattr(
        "app.agent.l1_observe.aggregate.l1_aggregate",
        fake_l1,
    )

    state = {
        "session_id": "test-freeze-001",
        "run_id": "test-freeze-001",
        "context_version": "",
        "layer_just_completed": 1,
    }
    result = await layer_aggregate_node(state)

    captured = captured_states["l1"]
    assert captured["context_version"] == "1"
    assert result["l1_snapshot_ref"]["context_version"] == "1"
    assert result["context_version"] == "1"
    assert result["context_ref"]["version"] == "1"


@pytest.mark.asyncio
async def test_bootstrap_failure_blocks_aggregate(monkeypatch):
    aggregate_called = {"called": False}

    async def fake_bootstrap(state):
        return {
            "bootstrap_context_done": True,
            "context_version": "",
            "context_fingerprint": "",
        }

    async def fake_l1(state, *, base_dir=".run-tmp"):
        aggregate_called["called"] = True
        return {"l1_snapshot_ref": {"artifact_id": "should-not-happen"}}

    monkeypatch.setattr(
        "app.agent.bootstrap.context_bootstrap.bootstrap_context_node",
        fake_bootstrap,
    )
    monkeypatch.setattr(
        "app.agent.l1_observe.aggregate.l1_aggregate",
        fake_l1,
    )

    state = {
        "session_id": "test-fail-001",
        "context_version": "",
        "layer_just_completed": 1,
    }
    with pytest.raises((RuntimeError, Exception), match="context"):
        await layer_aggregate_node(state)

    assert aggregate_called["called"] is False


@pytest.mark.asyncio
async def test_l1_aggregate_rejects_empty_context_directly(tmp_path):
    state = {
        "session_id": "test-direct-001",
        "run_id": "test-direct-001",
        "context_version": "",
    }
    with pytest.raises((RuntimeError, AssertionError), match="context"):
        await l1_aggregate(state, base_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_all_layer_artifacts_share_same_context_version(monkeypatch):
    versions = []

    async def fake_bootstrap(state):
        return {
            "bootstrap_context_done": True,
            "context_version": "1",
            "context_fingerprint": "sha256:abc123",
            "context_ref": {
                "session_id": state.get("session_id", ""),
                "version": "1",
            },
        }

    async def make_fake_aggregate():
        async def fake_aggregate(state, *, base_dir=".run-tmp"):
            versions.append(state.get("context_version", ""))
            return {}
        return fake_aggregate

    monkeypatch.setattr(
        "app.agent.bootstrap.context_bootstrap.bootstrap_context_node",
        fake_bootstrap,
    )
    monkeypatch.setattr(
        "app.agent.l1_observe.aggregate.l1_aggregate",
        await make_fake_aggregate(),
    )
    monkeypatch.setattr(
        "app.agent.l2_strategize.aggregate.l2_aggregate",
        await make_fake_aggregate(),
    )
    monkeypatch.setattr(
        "app.agent.l3_plan.aggregate.l3_aggregate",
        await make_fake_aggregate(),
    )

    base_state = {
        "session_id": "test-shared-001",
        "run_id": "test-shared-001",
    }

    layer_1_state = dict(base_state)
    layer_1_state["context_version"] = ""
    layer_1_state["layer_just_completed"] = 1
    await layer_aggregate_node(layer_1_state)

    for layer in (2, 3):
        layer_state = dict(base_state)
        layer_state["context_version"] = "1"
        layer_state["context_ref"] = {
            "session_id": "test-shared-001",
            "version": "1",
        }
        layer_state["layer_just_completed"] = layer
        await layer_aggregate_node(layer_state)

    assert all(v == "1" for v in versions)


@pytest.mark.asyncio
async def test_l1_strict_recovery_after_cache_loss():
    """Save L1 artifact with valid context, then load_artifact must succeed."""
    from datetime import datetime, timezone

    from app.agent.bootstrap.artifact_runtime import store_artifact, load_artifact
    from app.modules.schema.contracts.l1_contracts import L1Snapshot

    import shutil
    from pathlib import Path

    shutil.rmtree(Path(".run-tmp", "test-recover-001"), ignore_errors=True)

    state = {
        "session_id": "test-recover-001",
        "run_id": "test-recover-001",
        "context_version": "1",
        "context_fingerprint": "sha256:test",
        "context_ref": {"session_id": "test-recover-001", "version": "1"},
        "artifact_refs": {},
    }
    snapshot = L1Snapshot(
        session_id="test-recover-001",
        context_version="1",
        context_fingerprint="sha256:test",
        village_name="test",
        planning_period="2022-2035",
        facts=[],
        facts_by_dimension={},
        created_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
    )
    # store_artifact returns a dict ref; MUST write it back into artifact_refs
    ref = store_artifact(
        state, "l1_snapshot", "l1_observe", "L1Snapshot", snapshot
    )
    state["artifact_refs"]["l1_snapshot"] = ref

    # load_artifact must succeed and version must match
    loaded = load_artifact(state, "l1_snapshot", L1Snapshot)
    assert loaded is not None, (
        "load_artifact returned None - artifact_refs may not contain the ref "
        "or the store path doesn't match."
    )
    assert str(loaded.context_version) == "1"
    assert str(loaded.context_fingerprint) == "sha256:test"