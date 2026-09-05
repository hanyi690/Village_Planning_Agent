"""Build the explicit DATA boundary scope used by provider queries."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.contracts.data.boundary_contracts import BoundaryScopeArtifact, BoundaryScopeMode
from app.contracts.data.source_contracts import DataResourceCatalogSnapshot, SourceFeature


def _is_admitted(snapshot: DataResourceCatalogSnapshot, feature: SourceFeature) -> bool:
    qualified = f"resource:{feature.dataset_ref}:{feature.source_feature_ref}"
    return any(
        item.status == "admitted"
        and (
            item.source_ref == qualified
            or item.source_ref.endswith(f":{feature.source_feature_ref}")
        )
        for item in snapshot.admission_decisions
    )


def _candidate_features(
    snapshot: DataResourceCatalogSnapshot,
    *,
    source_dataset_ref: str = "",
    source_layer_ref: str = "boundary",
) -> list[SourceFeature]:
    candidates: list[SourceFeature] = []
    for feature in snapshot.features:
        if source_dataset_ref and feature.dataset_ref != source_dataset_ref:
            continue
        layer = str(feature.layer_ref or "").strip().casefold()
        declared = str((feature.raw_attributes or {}).get("resource_kind") or "").strip().casefold()
        if layer == source_layer_ref.casefold() or declared == source_layer_ref.casefold():
            candidates.append(feature)
    return candidates


def build_boundary_scope_artifact(
    snapshot: DataResourceCatalogSnapshot,
    *,
    mode: BoundaryScopeMode = "admitted_boundary",
    source_dataset_ref: str = "",
    source_layer_ref: str = "boundary",
) -> BoundaryScopeArtifact | None:
    """Build a query scope only from admitted polygonal DATA features.

    ``polygonized_admin_boundary`` is intentionally explicit. This function
    does not polygonize arbitrary lines; a caller must provide the validated
    polygonized representation as a separate admitted feature.
    """

    if mode == "polygonized_admin_boundary" and source_layer_ref.casefold() not in {
        "polygonized_admin_boundary",
        "admin_boundary_polygon",
    }:
        raise ValueError(
            "polygonized_admin_boundary requires an explicitly named polygonized layer"
        )

    candidates = [
        feature
        for feature in _candidate_features(
            snapshot,
            source_dataset_ref=source_dataset_ref,
            source_layer_ref=source_layer_ref,
        )
        if _is_admitted(snapshot, feature)
        and feature.normalized_geometry is not None
        and str(
            getattr(feature, "normalized_geometry_kind", "unknown")
            or "unknown"
        ).casefold() == "polygon"
        and str(feature.normalized_crs or "") == "EPSG:4326"
    ]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError("boundary scope requires exactly one admitted boundary feature")
    feature = candidates[0]
    geometry = dict(feature.normalized_geometry or {})
    geometry_type = str(geometry.get("type") or "")
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("boundary scope must be a Polygon or MultiPolygon")
    representation_refs = tuple(
        item.representation_ref
        for item in snapshot.representations
        if item.source_feature_ref == feature.source_feature_ref
        and item.dataset_ref == feature.dataset_ref
    )
    if not representation_refs:
        raise ValueError("boundary scope requires a source representation")
    material = {
        "mode": mode,
        "source_snapshot_ref": snapshot.snapshot_id,
        "source_dataset_ref": feature.dataset_ref,
        "source_feature_ref": feature.source_feature_ref,
        "source_digest": feature.source_feature_digest,
        "geometry": geometry,
    }
    scope_ref = "boundary-scope:" + hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    return BoundaryScopeArtifact(
        scope_ref=scope_ref,
        source_snapshot_ref=snapshot.snapshot_id,
        source_dataset_ref=feature.dataset_ref,
        source_feature_refs=(feature.source_feature_ref,),
        source_representation_refs=representation_refs,
        source_digest=feature.source_feature_digest,
        boundary_digest=feature.source_feature_digest,
        geometry=geometry,
        geometry_type=geometry_type,
        normalized_crs=feature.normalized_crs,
        mode=mode,
        topology_repair_trace=tuple(
            item for item in feature.crs_transform if "topology_repair" in item
        ),
    )


def load_boundary_scope_artifact(
    artifact_root: str,
    run_id: str,
    *,
    branch_id: str = "main",
) -> BoundaryScopeArtifact:
    """Load the named admitted scope for an explicit provider run."""

    from app.infrastructure.artifacts import ContentAddressedArtifactRepository
    from app.infrastructure.artifacts.runtime import load_artifact

    repository = ContentAddressedArtifactRepository(artifact_root)
    descriptor = repository.get_named_ref(run_id, branch_id, "boundary_scope")
    if descriptor is None:
        raise ValueError(
            f"no admitted boundary scope named for run={run_id!r}, branch={branch_id!r}"
        )
    return load_artifact(
        {
            "run_id": run_id,
            "branch_id": branch_id,
            "artifact_root": artifact_root,
            "artifact_refs": {"boundary_scope": descriptor.model_dump(mode="json")},
        },
        "boundary_scope",
        BoundaryScopeArtifact,
    )


__all__ = ["build_boundary_scope_artifact", "load_boundary_scope_artifact"]
