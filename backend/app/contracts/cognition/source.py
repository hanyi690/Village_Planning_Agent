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


class SourceFeatureRecord(StrictContractModel):
    source_record_ref: str
    collection_ref: str
    source_feature_id: str
    attributes_ref: str
    geometry_refs: tuple[str, ...] = ()
    content_digest: str


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
    "SourceFeatureRecord",
    "SourceFieldProfile",
    "SourceGeometryFieldProfile",
]
