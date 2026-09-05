from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.l1.l1_contracts import EvidenceGap, L1ObservationSnapshot
from app.contracts.workflow.workflow_contracts import GateDecision, PendingRequest
from app.infrastructure.artifacts.runtime import ArtifactReplayError
from app.modules.l1.finalization import (
    finalize_l1_product,
    load_ready_l1_product_manifest,
)
from app.contracts.l1.product_manifest import L1ProductManifest


def ref(schema_id: str, seed: str | None = None) -> ArtifactRef:
    digest = hashlib.sha256((seed or schema_id).encode()).hexdigest()
    value = f"sha256:{digest}"
    return ArtifactRef(
        digest=value,
        descriptor_digest=value,
        semantic_digest=value,
        size_bytes=0,
        schema_id=schema_id,
        schema_version="1",
        producer_stage="test",
        run_id="run-1",
        branch_id="main",
    )


def base_state() -> dict:
    refs = {
        "l1_snapshot": ref("L1ObservationSnapshot", "snapshot"),
        "l1_observations": ref("EvidenceObservationSnapshot", "observations"),
        "l1_bindings": ref("GroundedEntityBindingSnapshot", "bindings"),
        "l1_world_projection": ref("L1WorldProjectionSnapshot", "projection"),
        "world_model_snapshot": ref("SessionWorldModelSnapshot", "source-wm"),
        "world_model_current_snapshot": ref(
            "SessionWorldModelSnapshot", "current-wm"
        ),
        "l1_gate": ref("GateDecision", "gate"),
    }
    return {
        "run_id": "run-1",
        "session_id": "session-1",
        "branch_id": "main",
        "context_version": "context-2",
        "context_fingerprint": "context-fingerprint",
        "artifact_root": "test-artifacts",
        "artifact_refs": refs,
    }


def install_fakes(monkeypatch, *, gate: GateDecision | None = None):
    import app.modules.l1.finalization as finalization

    state = base_state()
    snapshot = L1ObservationSnapshot(
        context_version="context-1",
        context_fingerprint="context-fingerprint",
        facts=["fact-1"],
        evidence_gaps=[],
    )
    bindings = SimpleNamespace(bindings=[])
    projection = SimpleNamespace(
        resulting_world_model_snapshot_digest="current-wm-digest",
        resulting_context_version="context-2",
    )
    resolved_gate = gate or GateDecision(
        stage="l1", passed=True, context_version="context-2"
    )
    stored_ref = ref("L1ProductManifest", "manifest")

    monkeypatch.setattr(
        finalization,
        "validate_l1_world_projection_transition",
        lambda _state: projection,
    )
    monkeypatch.setattr(
        finalization,
        "load_artifact",
        lambda _state, key, _model: snapshot if key == "l1_snapshot" else bindings,
    )
    monkeypatch.setattr(finalization, "load_root_gate", lambda _state, _stage: resolved_gate)
    monkeypatch.setattr(
        finalization,
        "store_artifact",
        lambda *_args, **_kwargs: stored_ref.model_dump(mode="json"),
    )
    return state, stored_ref


def test_finalize_persists_ready_reference_manifest(monkeypatch) -> None:
    state, stored_ref = install_fakes(monkeypatch)

    patch = finalize_l1_product(state)

    assert patch["artifact_refs"]["l1_product_manifest"] == stored_ref.model_dump(
        mode="json"
    )
    assert patch["l1_finalization"]["status"] == "ready"


def test_finalize_replay_returns_same_manifest_ref(monkeypatch) -> None:
    state, stored_ref = install_fakes(monkeypatch)

    first = finalize_l1_product(state)
    second = finalize_l1_product(state)

    assert first["artifact_refs"]["l1_product_manifest"] == stored_ref.model_dump(
        mode="json"
    )
    assert second["artifact_refs"]["l1_product_manifest"] == first["artifact_refs"][
        "l1_product_manifest"
    ]


def test_finalize_marks_human_required_ground_gap(monkeypatch) -> None:
    gate = GateDecision(
        stage="l1",
        passed=False,
        feedback_route="HUMAN",
        pending_requests=[
            PendingRequest(
                request_id="mention-ambiguous",
                stage="l1",
                request_type="identity_human_confirmation",
            )
        ],
        context_version="context-2",
    )
    state, _ = install_fakes(monkeypatch, gate=gate)

    patch = finalize_l1_product(state)

    assert patch["l1_finalization"]["status"] == "human_required"
    assert patch["l1_finalization"]["terminal_gap_refs"] == [
        "mention-ambiguous"
    ]


def test_finalize_rejects_missing_required_ref(monkeypatch) -> None:
    state, _ = install_fakes(monkeypatch)
    del state["artifact_refs"]["l1_bindings"]

    with pytest.raises(ArtifactReplayError, match="l1_bindings"):
        finalize_l1_product(state)


def test_load_ready_manifest_checks_exact_child_closure(monkeypatch) -> None:
    import app.modules.l1.finalization as finalization

    state = base_state()
    refs = {
        key: ArtifactRef.model_validate(value)
        for key, value in state["artifact_refs"].items()
    }
    manifest = L1ProductManifest(
        context_version="context-2",
        context_fingerprint="context-fingerprint",
        observation_product_ref=refs["l1_observations"],
        l1_snapshot_ref=refs["l1_snapshot"],
        binding_snapshot_ref=refs["l1_bindings"],
        world_projection_ref=refs["l1_world_projection"],
        world_model_snapshot_ref=refs["world_model_current_snapshot"],
        world_model_snapshot_digest="current-wm-digest",
        fact_row_digest="facts-digest",
        binding_row_digest="bindings-digest",
        status="ready",
    )
    manifest_ref = ref("L1ProductManifest", "manifest").model_copy(
        update={
            "parent_digests": {
                key: value.digest for key, value in refs.items()
            }
        }
    )
    state["artifact_refs"]["l1_product_manifest"] = manifest_ref
    monkeypatch.setattr(finalization, "validate_artifact_context", lambda *_args: None)
    monkeypatch.setattr(
        finalization,
        "validate_l1_world_projection_transition",
        lambda _state: None,
    )
    monkeypatch.setattr(
        finalization,
        "load_artifact",
        lambda _state, key, _model: manifest if key == "l1_product_manifest" else None,
    )

    assert load_ready_l1_product_manifest(state) == manifest
