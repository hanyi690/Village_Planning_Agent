"""Data ownership boundary for session snapshots and ingestion."""

from .model.snapshot import CollectionSnapshot, SessionDataSnapshot
from .admission import (
    CatalogAdmissionIndex,
    FeatureAdmissionVerdict,
    assert_current_world_catalog,
    build_admission_index,
    current_world_snapshot,
    feature_admission_verdict,
)
from .resource_catalog import DataResourceCatalog

__all__ = [
    "CatalogAdmissionIndex",
    "CollectionSnapshot",
    "DataResourceCatalog",
    "FeatureAdmissionVerdict",
    "SessionDataSnapshot",
    "assert_current_world_catalog",
    "build_admission_index",
    "current_world_snapshot",
    "feature_admission_verdict",
]
