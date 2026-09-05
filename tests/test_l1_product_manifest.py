from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from app.contracts.artifacts.ref import ArtifactRef
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


def test_manifest_is_reference_only_and_has_target_statuses() -> None:
    manifest = L1ProductManifest(
        context_version="context-1",
        context_fingerprint="context-fingerprint",
        observation_product_ref=ref("EvidenceObservationSnapshot"),
        l1_snapshot_ref=ref("L1ObservationSnapshot"),
        binding_snapshot_ref=ref("GroundedEntityBindingSnapshot"),
        world_projection_ref=ref("L1WorldProjectionSnapshot"),
        world_model_snapshot_ref=ref("SessionWorldModelSnapshot"),
        world_model_snapshot_digest="wm-digest",
        fact_row_digest="facts-digest",
        binding_row_digest="bindings-digest",
        status="ready",
    )

    assert manifest.status == "ready"
    assert not hasattr(manifest, "fact_records")
    assert not hasattr(manifest, "bindings")


def test_manifest_rejects_workflow_route_as_product_status() -> None:
    with pytest.raises(ValidationError):
        L1ProductManifest(
            context_version="context-1",
            context_fingerprint="context-fingerprint",
            observation_product_ref=ref("EvidenceObservationSnapshot"),
            l1_snapshot_ref=ref("L1ObservationSnapshot"),
            binding_snapshot_ref=ref("GroundedEntityBindingSnapshot"),
            world_projection_ref=ref("L1WorldProjectionSnapshot"),
            world_model_snapshot_ref=ref("SessionWorldModelSnapshot"),
            world_model_snapshot_digest="wm-digest",
            fact_row_digest="facts-digest",
            binding_row_digest="bindings-digest",
            status="explore",
        )


def test_manifest_forbids_copied_rows_and_empty_digest() -> None:
    with pytest.raises(ValidationError):
        L1ProductManifest(
            context_version="context-1",
            context_fingerprint="context-fingerprint",
            observation_product_ref=ref("EvidenceObservationSnapshot"),
            l1_snapshot_ref=ref("L1ObservationSnapshot"),
            binding_snapshot_ref=ref("GroundedEntityBindingSnapshot"),
            world_projection_ref=ref("L1WorldProjectionSnapshot"),
            world_model_snapshot_ref=ref("SessionWorldModelSnapshot"),
            world_model_snapshot_digest="",
            fact_row_digest="facts-digest",
            binding_row_digest="bindings-digest",
            fact_records=[],
        )
