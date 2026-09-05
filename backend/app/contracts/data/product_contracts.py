"""Independent immutable DATA products published by the admission boundary."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.data.source_contracts import (
    DataCapability,
    DataResourceCatalogSnapshot,
    SourceAdmissionDecision,
    SourceDataset,
    SourceFeature,
    SpatialRepresentation,
    _digest,
)


class SourceFeatureSnapshot(BaseModel):
    """Native source content and source-side metadata for one feature."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_feature_ref: str
    dataset_ref: str
    layer_ref: str = ""
    geometry: dict[str, Any] | None = None
    geometry_kind: str = "unknown"
    source_crs: str = ""
    raw_attributes: dict[str, Any] = Field(default_factory=dict)
    normalized_claims: dict[str, Any] = Field(default_factory=dict)
    unmapped_attributes: dict[str, Any] = Field(default_factory=dict)
    source_feature_digest: str = ""
    validity_status: str = "unknown"
    diagnostics: tuple[str, ...] = ()

    def model_post_init(self, __context: Any) -> None:
        if not self.source_feature_digest:
            object.__setattr__(
                self,
                "source_feature_digest",
                _digest({
                    "source_feature_ref": self.source_feature_ref,
                    "dataset_ref": self.dataset_ref,
                    "layer_ref": self.layer_ref,
                    "geometry": self.geometry,
                    "geometry_kind": self.geometry_kind,
                    "source_crs": self.source_crs,
                    "raw_attributes": self.raw_attributes,
                    "normalized_claims": self.normalized_claims,
                    "unmapped_attributes": self.unmapped_attributes,
                    "validity_status": self.validity_status,
                    "diagnostics": self.diagnostics,
                }),
            )


class NormalizedFeatureSnapshot(BaseModel):
    """Normalized spatial representation joined to its source digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_feature_ref: str
    dataset_ref: str
    normalized_geometry: dict[str, Any] | None = None
    geometry_kind: str = "unknown"
    normalized_geometry_kind: str = "unknown"
    source_crs: str = ""
    normalized_crs: str = ""
    crs_transform: tuple[str, ...] = ()
    topology_repair_audit: dict[str, Any] = Field(default_factory=dict)
    source_feature_digest: str
    digest: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.digest:
            object.__setattr__(
                self,
                "digest",
                _digest({
                    "source_feature_ref": self.source_feature_ref,
                    "dataset_ref": self.dataset_ref,
                    "normalized_geometry": self.normalized_geometry,
                    "geometry_kind": self.geometry_kind,
                    "normalized_geometry_kind": self.normalized_geometry_kind,
                    "source_crs": self.source_crs,
                    "normalized_crs": self.normalized_crs,
                    "crs_transform": self.crs_transform,
                    "topology_repair_audit": self.topology_repair_audit,
                    "source_feature_digest": self.source_feature_digest,
                }),
            )


class SourceSnapshotArtifact(BaseModel):
    """Immutable source product; native geometry stays in this product only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    dataset: SourceDataset
    datasets: tuple[SourceDataset, ...] = ()
    features: tuple[SourceFeatureSnapshot, ...] = ()
    admission_decisions: tuple[SourceAdmissionDecision, ...] = ()
    source_ref: str = ""
    content_digest: str = ""
    policy_version: str = "current-world-admission-v1"
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
                    "admission_decisions": [item.model_dump(mode="json") for item in self.admission_decisions],
                    "source_ref": self.source_ref,
                    "content_digest": self.content_digest,
                    "policy_version": self.policy_version,
                }),
            )


class NormalizedResourceArtifact(BaseModel):
    """Immutable normalized-resource product without source attributes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    features: tuple[NormalizedFeatureSnapshot, ...] = ()
    normalized_crs: str = "EPSG:4326"
    policy_version: str = "current-world-admission-v1"
    digest: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.digest:
            object.__setattr__(
                self,
                "digest",
                _digest({
                    "snapshot_id": self.snapshot_id,
                    "features": [item.digest for item in self.features],
                    "normalized_crs": self.normalized_crs,
                    "policy_version": self.policy_version,
                }),
            )


class RepresentationSnapshotArtifact(BaseModel):
    """Immutable representation product."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    representations: tuple[SpatialRepresentation, ...] = ()
    digest: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.digest:
            object.__setattr__(
                self,
                "digest",
                _digest({
                    "snapshot_id": self.snapshot_id,
                    "representations": [item.model_dump(mode="json") for item in self.representations],
                }),
            )


class CapabilityIndexArtifact(BaseModel):
    """Immutable capability product."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    capabilities: tuple[DataCapability, ...] = ()
    digest: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.digest:
            object.__setattr__(
                self,
                "digest",
                _digest({
                    "snapshot_id": self.snapshot_id,
                    "capabilities": [item.model_dump(mode="json") for item in self.capabilities],
                }),
            )


def source_product(snapshot: DataResourceCatalogSnapshot, *, source_ref: str = "", content_digest: str = "") -> SourceSnapshotArtifact:
    return SourceSnapshotArtifact(
        snapshot_id=snapshot.snapshot_id,
        dataset=snapshot.dataset,
        datasets=snapshot.datasets,
        features=tuple(
            SourceFeatureSnapshot(
                source_feature_ref=feature.source_feature_ref,
                dataset_ref=feature.dataset_ref,
                layer_ref=feature.layer_ref,
                geometry=feature.geometry,
                geometry_kind=feature.geometry_kind,
                source_crs=feature.source_crs,
                raw_attributes=feature.raw_attributes,
                normalized_claims=feature.normalized_claims,
                unmapped_attributes=feature.unmapped_attributes,
                source_feature_digest=feature.source_feature_digest,
                validity_status=feature.validity_status,
                diagnostics=tuple(feature.diagnostics),
            )
            for feature in snapshot.features
        ),
        admission_decisions=snapshot.admission_decisions,
        source_ref=source_ref,
        content_digest=content_digest,
        policy_version=snapshot.admission_policy_version,
    )


def normalized_product(snapshot: DataResourceCatalogSnapshot) -> NormalizedResourceArtifact:
    return NormalizedResourceArtifact(
        snapshot_id=snapshot.snapshot_id,
        features=tuple(
            NormalizedFeatureSnapshot(
                source_feature_ref=feature.source_feature_ref,
                dataset_ref=feature.dataset_ref,
                normalized_geometry=feature.normalized_geometry,
                geometry_kind=feature.geometry_kind,
                normalized_geometry_kind=feature.normalized_geometry_kind,
                source_crs=feature.source_crs,
                normalized_crs=feature.normalized_crs,
                crs_transform=feature.crs_transform,
                topology_repair_audit=feature.topology_repair_audit,
                source_feature_digest=feature.source_feature_digest,
            )
            for feature in snapshot.features
        ),
    )


def compose_catalog(
    source: SourceSnapshotArtifact,
    normalized: NormalizedResourceArtifact,
    representations: RepresentationSnapshotArtifact,
    capabilities: CapabilityIndexArtifact,
    *,
    expected_digest: str = "",
) -> DataResourceCatalogSnapshot:
    normalized_by_key = {
        (item.dataset_ref, item.source_feature_ref): item
        for item in normalized.features
    }
    features: list[SourceFeature] = []
    for item in source.features:
        normalized_item = normalized_by_key.get((item.dataset_ref, item.source_feature_ref))
        if normalized_item is None:
            raise ValueError(f"normalized product missing {item.dataset_ref}:{item.source_feature_ref}")
        features.append(SourceFeature(
            source_feature_ref=item.source_feature_ref,
            dataset_ref=item.dataset_ref,
            layer_ref=item.layer_ref,
            geometry=item.geometry,
            normalized_geometry=normalized_item.normalized_geometry,
            geometry_kind=normalized_item.geometry_kind,
            normalized_geometry_kind=normalized_item.normalized_geometry_kind,
            source_crs=item.source_crs,
            normalized_crs=normalized_item.normalized_crs,
            crs_transform=normalized_item.crs_transform,
            topology_repair_audit=normalized_item.topology_repair_audit,
            raw_attributes=item.raw_attributes,
            normalized_claims=item.normalized_claims,
            unmapped_attributes=item.unmapped_attributes,
            source_feature_digest=item.source_feature_digest,
            validity_status=item.validity_status,
            diagnostics=list(item.diagnostics),
        ))
    snapshot = DataResourceCatalogSnapshot(
        snapshot_id=source.snapshot_id,
        dataset=source.dataset,
        datasets=source.datasets,
        features=tuple(features),
        representations=representations.representations,
        capabilities=capabilities.capabilities,
        admission_decisions=source.admission_decisions,
        admission_policy_version=source.policy_version,
    )
    if expected_digest and snapshot.digest != expected_digest:
        raise ValueError("component products compose to an unexpected catalog digest")
    return snapshot


__all__ = [
    "CapabilityIndexArtifact",
    "NormalizedFeatureSnapshot",
    "NormalizedResourceArtifact",
    "RepresentationSnapshotArtifact",
    "SourceFeatureSnapshot",
    "SourceSnapshotArtifact",
    "compose_catalog",
    "normalized_product",
    "source_product",
]
