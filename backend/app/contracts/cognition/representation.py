"""Purpose-specific geometry representation contract."""

from __future__ import annotations

from typing import Literal

from app.contracts.base import StrictContractModel


class SpatialRepresentation(StrictContractModel):
    representation_ref: str
    entity_ref: str
    geometry_ref: str
    role: str = ""
    geometry_kind: str = "unknown"
    crs: str = ""
    dataset_ref: str = ""
    source_feature_ref: str = ""
    resource_ref: str = ""
    authority: str = ""
    valid_time: str = ""
    source_crs: str = ""
    normalized_crs: str = ""
    source_snapshot_ref: str = ""
    content_digest: str = ""
    source_record_refs: tuple[str, ...] = ()
    derived_from_refs: tuple[str, ...] = ()
    status: Literal["proposed", "accepted", "rejected", "superseded"] = "proposed"


__all__ = ["SpatialRepresentation"]
