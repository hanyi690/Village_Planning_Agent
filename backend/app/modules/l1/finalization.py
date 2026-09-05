"""L1 post-GROUND final-view finalization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.cognition.stage_contracts import L1WorldProjectionSnapshot
from app.contracts.evidence.identity_contracts import (
    EvidenceObservationSnapshot,
    GroundedEntityBindingSnapshot,
)
from app.contracts.l1.l1_contracts import L1ObservationSnapshot
from app.contracts.l1.product_manifest import L1ProductManifest, L1ProductStatus
from app.contracts.workflow.workflow_contracts import GateDecision
from app.contracts.cognition.snapshot import SessionWorldModelSnapshot
from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.infrastructure.artifacts.runtime import (
    ArtifactReplayError,
    load_artifact,
    store_artifact,
    validate_artifact_context,
    validate_l1_world_projection_transition,
)
from app.workflow.state import load_root_gate


_REQUIRED_REFS = (
    "l1_snapshot",
    "l1_observations",
    "l1_bindings",
    "l1_world_projection",
    "world_model_snapshot",
    "world_model_current_snapshot",
    "l1_gate",
)


def _required_ref(state: Mapping[str, Any], key: str) -> ArtifactRef:
    raw = (state.get("artifact_refs") or {}).get(key)
    if not raw:
        raise ArtifactReplayError(f"L1 finalization requires artifact ref: {key}")
    try:
        return ArtifactRef.model_validate(raw)
    except Exception as exc:
        raise ArtifactReplayError(f"L1 finalization ref is invalid: {key}") from exc


def _gap_refs(
    snapshot: L1ObservationSnapshot,
    gate: GateDecision,
    bindings: GroundedEntityBindingSnapshot,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    open_refs: set[str] = set()
    terminal_refs: set[str] = set()

    for gap in snapshot.evidence_gaps:
        if not gap.gap_id:
            continue
        open_refs.add(gap.gap_id)
        if (
            gap.outcome_status in {"human_required", "not_available"}
            or not gap.recoverable
        ):
            terminal_refs.add(gap.gap_id)

    for request in gate.pending_requests:
        request_id = str(request.request_id or "").strip()
        if not request_id:
            continue
        open_refs.add(request_id)
        if "human" in str(request.request_type or "").casefold():
            terminal_refs.add(request_id)

    for binding in bindings.bindings:
        mention_ref = str(getattr(binding, "mention_ref", "") or "").strip()
        identity_status = str(getattr(binding, "identity_status", "") or "").strip()
        location_status = str(
            getattr(binding, "location_expression_status", "") or ""
        ).strip()
        if identity_status in {"ambiguous", "unresolved"} or location_status in {
            "ambiguous",
            "unresolved",
        }:
            if mention_ref:
                open_refs.add(mention_ref)
                terminal_refs.add(mention_ref)

    return tuple(sorted(open_refs)), tuple(sorted(terminal_refs))


def _product_status(
    gate: GateDecision,
    open_gap_refs: tuple[str, ...],
    terminal_gap_refs: tuple[str, ...],
) -> L1ProductStatus:
    if gate.passed and not open_gap_refs and not terminal_gap_refs:
        return "ready"
    if str(gate.feedback_route or "").upper() == "HUMAN" or terminal_gap_refs:
        return "human_required"
    if open_gap_refs:
        return "partial"
    return "blocked"


def finalize_l1_product(state: Mapping[str, Any]) -> dict[str, Any]:
    """Publish one immutable, reference-only final L1 product manifest.

    All child artifacts are reloaded or validated before the manifest is
    written.  A lineage/runtime mismatch raises ``ArtifactReplayError``;
    semantic ambiguity remains represented as a typed non-ready product.
    """

    refs = {key: _required_ref(state, key) for key in _REQUIRED_REFS}
    projection = validate_l1_world_projection_transition(dict(state))
    snapshot = load_artifact(dict(state), "l1_snapshot", L1ObservationSnapshot)
    load_artifact(
        dict(state), "l1_observations", EvidenceObservationSnapshot
    )
    bindings = load_artifact(
        dict(state), "l1_bindings", GroundedEntityBindingSnapshot
    )
    load_artifact(
        dict(state), "l1_world_projection", L1WorldProjectionSnapshot
    )
    load_artifact(
        dict(state), "world_model_snapshot", SessionWorldModelSnapshot
    )
    load_artifact(
        dict(state), "world_model_current_snapshot", SessionWorldModelSnapshot
    )
    gate = load_root_gate(dict(state), "l1")
    if snapshot is None or bindings is None or gate is None:
        raise ArtifactReplayError("L1 finalization child artifact is empty")
    if gate.stage.strip().lower() != "l1":
        raise ArtifactReplayError("L1 finalization gate stage mismatch")

    open_gap_refs, terminal_gap_refs = _gap_refs(snapshot, gate, bindings)
    status = _product_status(gate, open_gap_refs, terminal_gap_refs)
    projection_digest = str(
        getattr(projection, "resulting_world_model_snapshot_digest", "") or ""
    ).strip()
    if not projection_digest:
        projection_digest = refs["world_model_current_snapshot"].semantic_digest

    manifest = L1ProductManifest(
        context_version=str(
            state.get("context_version")
            or getattr(projection, "resulting_context_version", "")
            or snapshot.context_version
        ),
        context_fingerprint=str(
            state.get("context_fingerprint") or snapshot.context_fingerprint
        ),
        observation_product_ref=refs["l1_observations"],
        l1_snapshot_ref=refs["l1_snapshot"],
        binding_snapshot_ref=refs["l1_bindings"],
        world_projection_ref=refs["l1_world_projection"],
        world_model_snapshot_ref=refs["world_model_current_snapshot"],
        world_model_snapshot_digest=projection_digest,
        fact_row_digest=semantic_checksum(snapshot.fact_records),
        binding_row_digest=semantic_checksum(bindings.bindings),
        open_gap_refs=open_gap_refs,
        terminal_gap_refs=terminal_gap_refs,
        status=status,
    )
    manifest_ref = store_artifact(
        dict(state),
        "l1_product_manifest",
        "l1_final",
        "L1ProductManifest",
        manifest,
        parent_keys=_REQUIRED_REFS,
    )
    return {
        "artifact_refs": {"l1_product_manifest": manifest_ref},
        "l1_finalization": {
            "status": status,
            "fact_row_digest": manifest.fact_row_digest,
            "binding_row_digest": manifest.binding_row_digest,
            "open_gap_refs": list(open_gap_refs),
            "terminal_gap_refs": list(terminal_gap_refs),
        },
    }


def load_ready_l1_product_manifest(
    state: Mapping[str, Any],
) -> L1ProductManifest:
    """Reload and prove the exact ready final view consumed by L2/L3."""

    manifest_ref = _required_ref(state, "l1_product_manifest")
    validate_artifact_context(dict(state), "l1_product_manifest", manifest_ref)
    manifest = load_artifact(dict(state), "l1_product_manifest", L1ProductManifest)
    if manifest is None:
        raise ArtifactReplayError("L1ProductManifest payload is empty")

    child_refs = {
        key: _required_ref(state, key)
        for key in _REQUIRED_REFS
    }
    expected_parents = {
        key: ref.digest for key, ref in child_refs.items()
    }
    if manifest_ref.parent_digests != dict(sorted(expected_parents.items())):
        raise ArtifactReplayError(
            "L1ProductManifest parent closure is not exact"
        )

    field_refs = {
        "l1_snapshot": manifest.l1_snapshot_ref,
        "l1_observations": manifest.observation_product_ref,
        "l1_bindings": manifest.binding_snapshot_ref,
        "l1_world_projection": manifest.world_projection_ref,
        "world_model_current_snapshot": manifest.world_model_snapshot_ref,
    }
    for key, manifest_child in field_refs.items():
        active = child_refs[key]
        if any(
            getattr(manifest_child, field) != getattr(active, field)
            for field in ("digest", "descriptor_digest", "semantic_digest")
        ):
            raise ArtifactReplayError(
                f"L1ProductManifest child ref mismatch: {key}"
            )

    validate_l1_world_projection_transition(dict(state))
    if manifest.context_version != str(state.get("context_version") or ""):
        raise ArtifactReplayError(
            "L1ProductManifest context version mismatch"
        )
    if manifest.status != "ready":
        raise RuntimeError(
            "L2/L3 require a ready L1ProductManifest; "
            f"current status={manifest.status}"
        )
    return manifest


__all__ = ["finalize_l1_product", "load_ready_l1_product_manifest"]
