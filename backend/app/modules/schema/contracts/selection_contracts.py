from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .contract_meta import ContractMeta
from .provenance import Provenance


class RankedCandidate(BaseModel):
    candidate_id: str
    rank: int
    score: float = 0.0
    score_breakdown: dict = Field(default_factory=dict)
    project_ref: str | None = None


class EliminatedCandidate(BaseModel):
    candidate_id: str
    elimination_reason: str = ""
    eliminated_by_constraint: str = ""


class TargetAssignment(BaseModel):
    """Authoritative SELECT binding for one stable planning target."""

    target_id: str
    target_type: Literal["project", "zone", "facility", "axis", "road"]
    status: Literal["ready", "placed", "unplaced", "deferred"] = "ready"
    selected_bsm: str = ""
    anchor_point: tuple[float, float] | None = None
    expected_output_kind: Literal["parcel", "polygon", "point", "line", "action"] = "parcel"
    target_binding: dict = Field(default_factory=dict)
    input_artifact_refs: list[str] = Field(default_factory=list)
    score: float = 0.0
    score_breakdown: dict = Field(default_factory=dict)


class SiteSelectionDecision(ContractMeta):
    schema_version: Literal["2.0"] = "2.0"
    target_assignments: list[TargetAssignment] = Field(default_factory=list)
    selected_combination: list[str] = Field(default_factory=list)
    full_ranking: list[RankedCandidate] = Field(default_factory=list)
    eliminated: list[EliminatedCandidate] = Field(default_factory=list)
    decision_factors: dict = Field(default_factory=dict)
    review_status: str = "pending_review"  # "auto" | "pending_review" | "human_approved"
    provenance: "Provenance | None" = None

    @model_validator(mode="after")
    def derive_flat_summaries(self) -> "SiteSelectionDecision":
        if self.target_assignments:
            self.refresh_derived_summaries()
        return self

    def refresh_derived_summaries(self) -> None:
        """Refresh legacy flat SELECT summaries from authoritative assignments."""
        placed = [item for item in self.target_assignments if item.status == "placed"]
        self.selected_combination = [item.selected_bsm for item in placed if item.selected_bsm]
        self.full_ranking = [
            RankedCandidate(
                candidate_id=item.selected_bsm,
                rank=index,
                score=item.score,
                score_breakdown=dict(item.score_breakdown),
                project_ref=item.target_id,
            )
            for index, item in enumerate(placed, start=1)
            if item.selected_bsm
        ]

class LandDesignBrief(BaseModel):
    project_ref: str
    footprint_conditions: list[str] = Field(default_factory=list)
    area_tolerance_pct: float = 5.0
    access_requirements: list[str] = Field(default_factory=list)
    adjacency_requirements: list[str] = Field(default_factory=list)
    setback_requirements: list[str] = Field(default_factory=list)
    preservation_requirements: list[str] = Field(default_factory=list)


__all__ = [
    "RankedCandidate",
    "EliminatedCandidate",
    "TargetAssignment",
    "SiteSelectionDecision",
    "LandDesignBrief",
]
