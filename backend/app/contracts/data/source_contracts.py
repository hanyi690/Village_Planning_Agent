"""Generic Data-owned contracts independent of Bundle field names."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


GeometryKind = Literal[
    "point",
    "line",
    "polygon",
    "multipatch",
    "collection",
    "raster",
    "opaque",
    "unknown",
]


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def source_local_cognition_ref(
    dataset_ref: str,
    source_feature_ref: str,
    *,
    logical_record_ref: str = "",
) -> str:
    """Return the shared non-authoritative DATA/KG source-local identity."""

    dataset = str(dataset_ref or "").strip()
    feature = str(source_feature_ref or "").strip()
    logical = str(logical_record_ref or "").strip()
    if logical:
        return f"source-record:{dataset}:{logical}"
    return f"source:{dataset}:{feature}"


class SourceDataset(BaseModel):
    """A source dataset manifest; it never embeds all feature payloads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_ref: str
    name: str = ""
    version: str = ""
    crs: str = ""
    source_uris: tuple[str, ...] = ()
    layer_refs: tuple[str, ...] = ()
    feature_count: int = Field(default=0, ge=0)
    digest: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def model_post_init(self, __context: Any) -> None:
        if not self.digest:
            object.__setattr__(
                self,
                "digest",
                _digest({
                    "dataset_ref": self.dataset_ref,
                    "version": self.version,
                    "crs": self.crs,
                    "source_uris": self.source_uris,
                    "layer_refs": self.layer_refs,
                    "feature_count": self.feature_count,
                }),
            )


class SourceFeature(BaseModel):
    """One generic source feature with lossless raw attributes."""

    model_config = ConfigDict(extra="allow")

    source_feature_ref: str
    dataset_ref: str
    layer_ref: str = ""
    geometry: dict[str, Any] | None = None
    # ``geometry`` is the lossless native payload.  Spatial consumers use the
    # normalized view when it is available; keeping both prevents a CRS
    # conversion from destroying auditability.
    normalized_geometry: dict[str, Any] | None = None
    normalized_geometry_kind: GeometryKind = "unknown"
    geometry_kind: GeometryKind = "unknown"
    source_crs: str = ""
    normalized_crs: str = ""
    crs_transform: tuple[str, ...] = ()
    topology_repair_audit: dict[str, Any] = Field(default_factory=dict)
    raw_attributes: dict[str, Any] = Field(default_factory=dict)
    normalized_claims: dict[str, Any] = Field(default_factory=dict)
    unmapped_attributes: dict[str, Any] = Field(default_factory=dict)
    source_feature_digest: str = ""
    validity_status: Literal["valid", "invalid", "missing", "unknown"] = "unknown"
    diagnostics: list[str] = Field(default_factory=list)

    @field_validator("geometry")
    @classmethod
    def _geometry_shape(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and (not isinstance(value, dict) or not value.get("type")):
            raise ValueError("geometry must be a GeoJSON geometry object")
        return value

    def model_post_init(self, __context: Any) -> None:
        if self.geometry_kind == "unknown" and isinstance(self.geometry, dict):
            inferred = {
                "point": "point",
                "multipoint": "point",
                "linestring": "line",
                "multilinestring": "line",
                "polygon": "polygon",
                "multipolygon": "polygon",
                "multipatch": "multipatch",
                "geometrycollection": "collection",
            }.get(str(self.geometry.get("type") or "").casefold())
            if inferred is None and self.geometry.get("type"):
                inferred = "opaque"
            if inferred:
                object.__setattr__(self, "geometry_kind", inferred)
        if self.normalized_geometry_kind == "unknown" and isinstance(
            self.normalized_geometry,
            dict,
        ):
            normalized = {
                "point": "point",
                "multipoint": "point",
                "linestring": "line",
                "multilinestring": "line",
                "polygon": "polygon",
                "multipolygon": "polygon",
                "multipatch": "multipatch",
                "geometrycollection": "collection",
            }.get(
                str(self.normalized_geometry.get("type") or "").casefold()
            )
            if normalized is None and self.normalized_geometry.get("type"):
                normalized = "opaque"
            if normalized:
                object.__setattr__(self, "normalized_geometry_kind", normalized)
        if not self.source_feature_digest:
            object.__setattr__(
                self,
                "source_feature_digest",
                _digest({
                    "source_feature_ref": self.source_feature_ref,
                    "geometry": self.geometry,
                    "normalized_geometry": self.normalized_geometry,
                    "normalized_geometry_kind": self.normalized_geometry_kind,
                    "source_crs": self.source_crs,
                    "normalized_crs": self.normalized_crs,
                    "crs_transform": self.crs_transform,
                    "topology_repair_audit": self.topology_repair_audit,
                    "raw_attributes": self.raw_attributes,
                }),
            )


class SpatialRepresentation(BaseModel):
    """A purpose-specific representation owned by Data/KG boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    representation_ref: str
    entity_ref: str = ""
    # Feature references are human-readable but scoped to this dataset.  The
    # explicit lineage field prevents consumers from treating a bare "1" as a
    # process-wide key when catalogs are merged.
    dataset_ref: str = ""
    source_feature_ref: str = ""
    purpose: str = ""
    geometry_kind: GeometryKind = "unknown"
    geometry_ref: str = ""
    resource_ref: str = ""
    crs: str = ""
    source_crs: str = ""
    normalized_crs: str = ""
    crs_transform: tuple[str, ...] = ()
    source_snapshot_ref: str = ""
    content_digest: str = ""
    derived_from: tuple[str, ...] = ()
    component_refs: tuple[str, ...] = ()
    status: Literal["available", "read_only", "unresolved", "deprecated"] = "available"


class DataCapability(BaseModel):
    """An operation the Data resource can deterministically perform."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_ref: str
    resource_ref: str
    operation: str
    geometry_kind: GeometryKind = "unknown"
    crs: str = ""
    source_snapshot_ref: str = ""
    content_digest: str = ""
    parameters_schema: dict[str, Any] = Field(default_factory=dict)


class SourceAdmissionDecision(BaseModel):
    """Auditable decision separating current facts from control/output data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_ref: str
    source_ref: str
    source_digest: str = ""
    input_role: Literal[
        "current_evidence",
        "planning_brief",
        "planning_instruction",
        "reference_plan",
        "planned_output",
        "unclassified",
    ] = "unclassified"
    status: Literal[
        "admitted",
        "control_only",
        "reference_only",
        "excluded",
        "quarantined",
    ] = "quarantined"
    resource_kind: str = ""
    reason: str = ""
    recovery_pointer: str = ""


class DataResourceCatalogSnapshot(BaseModel):
    """Bounded index consumed by KG, GROUND and SELECT."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    dataset: SourceDataset
    datasets: tuple[SourceDataset, ...] = ()
    features: tuple[SourceFeature, ...] = ()
    representations: tuple[SpatialRepresentation, ...] = ()
    capabilities: tuple[DataCapability, ...] = ()
    admission_decisions: tuple[SourceAdmissionDecision, ...] = ()
    admission_policy_version: str = "current-world-admission-v1"
    digest: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.digest:
            object.__setattr__(
                self,
                "digest",
                _digest({
                    "snapshot_id": self.snapshot_id,
                    "dataset": self.dataset.digest,
                    "datasets": [item.digest for item in self.datasets],
                    "features": [item.source_feature_digest for item in self.features],
                    "representations": [
                        {
                            "representation_ref": item.representation_ref,
                            "entity_ref": item.entity_ref,
                            "dataset_ref": item.dataset_ref,
                            "source_feature_ref": item.source_feature_ref,
                            "resource_ref": item.resource_ref,
                            "geometry_ref": item.geometry_ref,
                            "crs": item.crs,
                            "source_crs": item.source_crs,
                            "normalized_crs": item.normalized_crs,
                            "source_snapshot_ref": item.source_snapshot_ref,
                            "content_digest": item.content_digest,
                            "status": item.status,
                        }
                        for item in self.representations
                    ],
                    "capabilities": [
                        {
                            "capability_ref": item.capability_ref,
                            "resource_ref": item.resource_ref,
                            "operation": item.operation,
                            "geometry_kind": item.geometry_kind,
                            "crs": item.crs,
                            "source_snapshot_ref": item.source_snapshot_ref,
                            "content_digest": item.content_digest,
                            "parameters_schema": item.parameters_schema,
                        }
                        for item in self.capabilities
                    ],
                    "admission_decisions": [
                        item.model_dump(mode="json")
                        for item in self.admission_decisions
                    ],
                    "admission_policy_version": self.admission_policy_version,
                }),
            )


class DataResourceCatalogIndexSnapshot(BaseModel):
    """Lightweight catalog pointer over independent DATA product artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    catalog_digest: str
    source_snapshot_ref: str
    source_snapshot_digest: str
    normalized_resource_ref: str
    normalized_resource_digest: str
    representation_snapshot_ref: str
    representation_snapshot_digest: str
    capability_index_ref: str
    capability_index_digest: str
    dataset_refs: tuple[str, ...] = ()
    dataset_digests: tuple[str, ...] = ()
    feature_refs: tuple[str, ...] = ()
    feature_digests: tuple[str, ...] = ()
    representation_refs: tuple[str, ...] = ()
    representation_digests: tuple[str, ...] = ()
    capability_refs: tuple[str, ...] = ()
    capability_digests: tuple[str, ...] = ()
    admission_decision_refs: tuple[str, ...] = ()
    admission_policy_version: str = "current-world-admission-v1"
    digest: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.digest:
            object.__setattr__(
                self,
                "digest",
                _digest({
                    "snapshot_id": self.snapshot_id,
                    "catalog_digest": self.catalog_digest,
                    "source_snapshot_ref": self.source_snapshot_ref,
                    "source_snapshot_digest": self.source_snapshot_digest,
                    "normalized_resource_ref": self.normalized_resource_ref,
                    "normalized_resource_digest": self.normalized_resource_digest,
                    "representation_snapshot_ref": self.representation_snapshot_ref,
                    "representation_snapshot_digest": self.representation_snapshot_digest,
                    "capability_index_ref": self.capability_index_ref,
                    "capability_index_digest": self.capability_index_digest,
                    "dataset_refs": self.dataset_refs,
                    "dataset_digests": self.dataset_digests,
                    "feature_refs": self.feature_refs,
                    "feature_digests": self.feature_digests,
                    "representation_refs": self.representation_refs,
                    "representation_digests": self.representation_digests,
                    "capability_refs": self.capability_refs,
                    "capability_digests": self.capability_digests,
                    "admission_decision_refs": self.admission_decision_refs,
                    "admission_policy_version": self.admission_policy_version,
                }),
            )


__all__ = [
    "GeometryKind",
    "SourceDataset",
    "SourceFeature",
    "SpatialRepresentation",
    "DataCapability",
    "SourceAdmissionDecision",
    "DataResourceCatalogSnapshot",
    "DataResourceCatalogIndexSnapshot",
    "source_local_cognition_ref",
]
