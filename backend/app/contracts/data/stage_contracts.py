"""Typed DATA stage products used by the workflow bootstrap.

The data layer deliberately keeps the complete catalog in its own CAS
artifact.  This module contains only the bounded stage summary and therefore
remains safe to carry in a workflow checkpoint or a diagnostic response.
"""

from __future__ import annotations

from typing import Literal

from app.contracts.artifacts.contract_meta import ContractMeta


class DataGapRecord(ContractMeta):
    """A source-bound DATA problem with an explicit recovery owner."""

    stage: Literal["data"] = "data"
    gap_ref: str
    source_feature_ref: str = ""
    source_digest: str = ""
    missing_fields: tuple[str, ...] = ()
    reason: str
    status: Literal["open", "deferred", "resolved"] = "open"
    blocking: bool = True
    earliest_resolution_stage: Literal["data", "human"] = "data"
    recovery_pointer: str = ""


class DataStageSnapshot(ContractMeta):
    """Bounded, reloadable summary of one normalized DATA snapshot."""

    stage: Literal["data"] = "data"
    status: Literal["ready", "blocked"] = "ready"
    catalog_ref: str = ""
    catalog_digest: str = ""
    data_snapshot_ref: str = ""
    source_snapshot_id: str = ""
    source_snapshot_digest: str = ""
    dataset_count: int = 0
    feature_count: int = 0
    representation_count: int = 0
    capability_count: int = 0
    admission_decision_count: int = 0
    admitted_source_count: int = 0
    excluded_source_count: int = 0
    quarantined_source_count: int = 0
    admission_decision_refs: tuple[str, ...] = ()
    deferred_media_count: int = 0
    diagnostics: tuple[str, ...] = ()
    gap_refs: tuple[str, ...] = ()
    gaps: tuple[DataGapRecord, ...] = ()
    receipt_ref: str = ""
    lifecycle_state: str = ""
    lifecycle: tuple[str, ...] = ()


__all__ = ["DataGapRecord", "DataStageSnapshot"]
