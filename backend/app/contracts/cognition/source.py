"""Lossless source-side cognition contracts."""

from __future__ import annotations

from app.contracts.base import StrictContractModel


class SourceFieldProfile(StrictContractModel):
    name: str
    physical_type: str
    nullable: bool = True
    unique_ratio: float = 0.0
    null_ratio: float = 0.0
    samples: tuple[str, ...] = ()


class SourceGeometryFieldProfile(StrictContractModel):
    name: str
    geometry_kinds: tuple[str, ...] = ()
    crs_refs: tuple[str, ...] = ()


class SourceRecord(StrictContractModel):
    """Immutable source-side record admitted into the WM current snapshot."""

    source_record_ref: str
    dataset_ref: str
    collection_ref: str = ""
    source_feature_ref: str
    source_snapshot_ref: str
    raw_attribute_ref: str = ""
    source_geometry_refs: tuple[str, ...] = ()
    valid_time: str = ""
    input_role: str = "current_evidence"
    admission_status: str = "admitted"
    source_digest: str


class SourceCollectionSnapshot(StrictContractModel):
    collection_ref: str
    dataset_ref: str
    name: str = ""
    fields: tuple[SourceFieldProfile, ...] = ()
    geometry_fields: tuple[SourceGeometryFieldProfile, ...] = ()
    feature_refs: tuple[str, ...] = ()


class SourceCatalogSnapshot(StrictContractModel):
    snapshot_ref: str
    dataset_refs: tuple[str, ...] = ()
    collection_refs: tuple[str, ...] = ()
    feature_refs: tuple[str, ...] = ()
    digest: str


__all__ = [
    "SourceCatalogSnapshot",
    "SourceCollectionSnapshot",
    "SourceRecord",
    "SourceFieldProfile",
    "SourceGeometryFieldProfile",
]
