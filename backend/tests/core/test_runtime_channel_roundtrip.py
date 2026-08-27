"""The runtime channel replaces the workflow_progress artifact carrier."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.contracts.artifacts import ArtifactRef
from app.workflow.runtime_adapter import initial_workflow_state, materialize_workflow_state, pack_workflow_patch
from app.workflow.state import WorkflowState


def _artifact_ref_payload(seed: str, created_at: datetime) -> dict:
    def digest(suffix: str) -> str:
        return "sha256:" + hashlib.sha256(f"{seed}:{suffix}".encode()).hexdigest()

    return ArtifactRef(
        digest=digest("blob"),
        descriptor_digest=digest("descriptor"),
        size_bytes=1,
        schema_id="TestArtifact",
        schema_version="3",
        semantic_digest=digest("semantic"),
        producer_stage="TEST",
        run_id="run-1",
        branch_id="main",
        created_at=created_at,
    ).model_dump(mode="json")


def test_runtime_channel_is_a_declared_workflow_state_field():
    assert "runtime" in WorkflowState.__annotations__


def test_initial_state_carries_runtime_channel():
    state = initial_workflow_state({"session_id": "s1", "phase": "layer1", "paused_stage": "ground"})
    assert "runtime" in state
    assert state["paused_stage"] == "ground"
    assert "paused_stage" not in state["runtime"]


def test_pack_and_materialize_roundtrip_preserves_stage_local_keys():
    initial = initial_workflow_state({"session_id": "s1", "phase": "layer1"})
    packed = pack_workflow_patch(initial, {"current_stage": "ground", "next_stage": "select", "paused_stage": "l1"})
    assert "runtime" in packed
    materialized = materialize_workflow_state(packed)
    assert materialized["current_stage"] == "ground"
    assert materialized["next_stage"] == "select"
    assert materialized["paused_stage"] == "l1"


def test_runtime_channel_excludes_reducer_and_identity_keys():
    initial = initial_workflow_state({
        "session_id": "s1", "phase": "layer1",
        "artifact_refs": {}, "retry_counts": {"ground": 1}, "messages": [],
    })
    carrier = initial["runtime"]
    assert "session_id" not in carrier
    assert "artifact_refs" not in carrier
    assert "phase" not in carrier
    assert "messages" not in carrier
    assert carrier["retry_counts"] == {"ground": 1}


def test_parallel_provider_failures_are_first_class_checkpoint_channels():
    state = initial_workflow_state({
        "session_id": "s1",
        "phase": "layer3",
        "fatal_error": {"code": "llm_stream_timeout", "dimension": "traffic"},
        "provider_failures": [
            {"code": "llm_stream_timeout", "dimension": "traffic"},
        ],
        "dimension_retry_counts": {"traffic": 1},
    })

    assert state["fatal_error"]["dimension"] == "traffic"
    assert state["provider_failures"][0]["dimension"] == "traffic"
    assert state["dimension_retry_counts"] == {"traffic": 1}
    assert "provider_failures" not in state["runtime"]

    cleared = pack_workflow_patch(state, {
        "fatal_error": None,
        "provider_failures": [],
    })
    assert cleared["fatal_error"] is None
    assert cleared["provider_failures"] == []


def test_explicit_none_clears_reducer_channel():
    state = initial_workflow_state({
        "session_id": "s1",
        "phase": "layer1",
        "layer_just_completed": 1,
    })

    cleared = pack_workflow_patch(state, {"layer_just_completed": None})

    assert "layer_just_completed" in cleared
    assert cleared["layer_just_completed"] is None


def test_successful_worker_does_not_clear_sibling_provider_failure():
    async def successful_worker(_state):
        return {"completed_dimensions": {"layer1": ["location"]}}

    state = initial_workflow_state({
        "session_id": "s1",
        "phase": "layer1",
        "provider_failures": [],
    })
    from app.workflow.runtime_adapter import adapt_node

    projection = asyncio.run(adapt_node(successful_worker, worker=True)(state))

    assert "provider_failures" not in projection


def test_failed_worker_keeps_explicit_provider_failure_update():
    async def failed_worker(_state):
        return {
            "provider_failures": [
                {"code": "llm_stream_timeout", "dimension": "land_use"},
            ],
        }

    state = initial_workflow_state({"session_id": "s1", "phase": "layer1"})
    from app.workflow.runtime_adapter import adapt_node

    projection = asyncio.run(adapt_node(failed_worker, worker=True)(state))

    assert projection["provider_failures"][0]["dimension"] == "land_use"


def test_materialize_unions_raw_runtime_and_top_level_artifact_refs():
    from app.infrastructure.runtime.planning_runtime_service import (
        _materialize_workflow_state_preserving_artifacts,
    )

    base_time = datetime(2026, 8, 17, tzinfo=timezone.utc)
    top_level_manifest = _artifact_ref_payload("manifest-old", base_time)
    runtime_manifest = _artifact_ref_payload(
        "manifest-new", base_time + timedelta(seconds=1)
    )
    spatial = _artifact_ref_payload("spatial", base_time)

    materialized = _materialize_workflow_state_preserving_artifacts(
        {
            "artifact_refs": {
                "delivery_manifest": top_level_manifest,
            },
            "runtime": {
                "artifact_refs": {
                    "delivery_manifest": runtime_manifest,
                    "delivery_spatial_snapshot": spatial,
                },
            },
        }
    )

    assert set(materialized["artifact_refs"]) == {
        "delivery_manifest",
        "delivery_spatial_snapshot",
    }
    assert (
        materialized["artifact_refs"]["delivery_manifest"]["descriptor_digest"]
        == runtime_manifest["descriptor_digest"]
    )


def test_artifact_ref_merge_filters_falsy_invalid_and_keeps_newer_descriptor():
    from app.infrastructure.runtime.planning_runtime_service import (
        _merge_nonempty_artifact_refs,
    )

    base_time = datetime(2026, 8, 17, tzinfo=timezone.utc)
    older = _artifact_ref_payload("manifest-old", base_time)
    newer = _artifact_ref_payload("manifest-new", base_time + timedelta(seconds=1))

    merged = _merge_nonempty_artifact_refs(
        {
            "delivery_manifest": older,
            "empty_string": "",
            "empty_list": [],
            "false_value": False,
            "empty_dict": {},
            "malformed": {"descriptor_digest": "not-a-ref"},
        },
        {"delivery_manifest": newer},
    )

    assert set(merged) == {"delivery_manifest"}
    assert merged["delivery_manifest"]["descriptor_digest"] == newer["descriptor_digest"]


@pytest.mark.asyncio
async def test_diagnostic_state_update_preserves_delivery_refs_from_runtime_carrier(monkeypatch):
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

    base_time = datetime(2026, 8, 17, tzinfo=timezone.utc)
    delivery_refs = {
        "delivery_manifest": _artifact_ref_payload("manifest", base_time),
        "delivery_spatial_snapshot": _artifact_ref_payload("spatial", base_time),
        "render_artifacts": _artifact_ref_payload("artifacts", base_time),
        "render_layers": _artifact_ref_payload("layers", base_time),
    }
    graph = SimpleNamespace()
    graph.snapshot = SimpleNamespace(
        values={
            "session_id": "session-1",
            "artifact_refs": {
                "reconcile_gate": _artifact_ref_payload("gate", base_time),
            },
            "runtime": {"artifact_refs": delivery_refs},
        }
    )

    async def aget_state(_config):
        return graph.snapshot

    async def aupdate_state(_config, updates, as_node=None):
        graph.updated = updates
        graph.as_node = as_node

    graph.aget_state = aget_state
    graph.aupdate_state = aupdate_state
    monkeypatch.setattr(PlanningRuntimeService, "_initialized", True)
    monkeypatch.setattr(PlanningRuntimeService, "_graph", graph)

    await PlanningRuntimeService.aupdate_state(
        "session-1",
        {
            "delivery_status": "diagnostic_only",
            "phase": "completed",
            "current_stage": "reconcile",
            "next_stage": "TERMINAL",
            "artifact_refs": {
                "delivery_manifest": "",
                "delivery_spatial_snapshot": [],
                "render_artifacts": False,
                "render_layers": {},
            },
        },
        as_node="end_diagnostic",
    )

    assert graph.as_node == "end_diagnostic"
    assert graph.updated["artifact_refs"] == {
        "reconcile_gate": _artifact_ref_payload("gate", base_time),
        **delivery_refs,
    }
