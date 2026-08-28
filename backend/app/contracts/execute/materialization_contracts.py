"""Formal execution/materialization contracts.

These records are consumed by EXECUTE workers and are deliberately independent
of the retired SELECT decision contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.contracts.artifacts.classification_ref import ClassificationDecision


class TargetAssignment(BaseModel):
    """One approval-bound materializer target binding."""

    target_id: str
    target_type: Literal["site_area", "zone", "facility", "axis", "road", "linear"]
    status: Literal["ready", "placed", "unplaced", "deferred"] = "ready"
    selected_bsm: str = ""
    selected_bsms: list[str] = Field(default_factory=list)
    feature_bsm: str = ""
    source_feature_id: str = ""
    entity_ref: str = ""
    relation_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    l1_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""
    anchor_point: tuple[float, float] | None = None
    expected_output_kind: Literal["parcel", "polygon", "point", "line", "action"] = "parcel"
    target_binding: dict = Field(default_factory=dict)
    input_artifact_refs: list[str] = Field(default_factory=list)
    reason: str = ""
    score: float = 0.0
    score_breakdown: dict = Field(default_factory=dict)
    allocation_lineage_refs: list[str] = Field(default_factory=list)
    availability_status: Literal[
        "fully_available",
        "partially_available",
        "fully_unavailable",
        "unknown",
    ] = "unknown"
    eligible_area_ha: float | None = Field(default=None, ge=0)
    excluded_area_ha: float | None = Field(default=None, ge=0)
    adjacent_parcel_bsms: list[str] = Field(default_factory=list)
    adjacency_evidence_refs: list[str] = Field(default_factory=list)


class LandDesignBrief(BaseModel):
    """Optional deterministic design constraints for a materializer target."""

    project_ref: str
    classification_decision: ClassificationDecision | None = None
    footprint_conditions: list[str] = Field(default_factory=list)
    area_tolerance_pct: float = 5.0
    access_requirements: list[str] = Field(default_factory=list)
    adjacency_requirements: list[str] = Field(default_factory=list)
    setback_requirements: list[str] = Field(default_factory=list)
    preservation_requirements: list[str] = Field(default_factory=list)


__all__ = ["TargetAssignment", "LandDesignBrief"]
