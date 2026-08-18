from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.classification_ref import ClassificationDecision
from app.contracts.artifacts.provenance import Provenance
from app.contracts.planning.constraint_factor import RelationSatisfaction


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

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_project_type(cls, value: object) -> object:
        """Normalize the pre-v2 ``project`` spelling to ``site_area``."""
        if isinstance(value, dict) and value.get("target_type") == "project":
            payload = dict(value)
            payload["target_type"] = "site_area"
            return payload
        return value

    target_id: str
    target_type: Literal["site_area", "zone", "facility", "axis", "road", "linear"]
    status: Literal["ready", "placed", "unplaced", "deferred"] = "ready"
    selected_bsm: str = ""
    selected_bsms: list[str] = Field(default_factory=list)
    anchor_point: tuple[float, float] | None = None
    expected_output_kind: Literal["parcel", "polygon", "point", "line", "action"] = "parcel"
    target_binding: dict = Field(default_factory=dict)
    input_artifact_refs: list[str] = Field(default_factory=list)
    reason: str = ""
    score: float = 0.0
    score_breakdown: dict = Field(default_factory=dict)
    allocation_lineage_refs: list[str] = Field(default_factory=list)


class SiteSelectionDecision(ContractMeta):
    schema_version: Literal["2.0"] = "2.0"
    target_assignments: list[TargetAssignment] = Field(default_factory=list)
    selected_combination: list[str] = Field(default_factory=list)
    full_ranking: list[RankedCandidate] = Field(default_factory=list)
    eliminated: list[EliminatedCandidate] = Field(default_factory=list)
    decision_factors: dict = Field(default_factory=dict)
    relation_satisfaction: list[RelationSatisfaction] = Field(default_factory=list)
    scenario_id: str = "evidence_baseline"
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
        self.decision_factors["target_count"] = len(self.target_assignments)
        self.decision_factors["placed_count"] = len(placed)
        self.decision_factors["ready_count"] = sum(
            item.status == "ready" for item in self.target_assignments
        )
        self.decision_factors["unplaced_count"] = sum(
            item.status == "unplaced" for item in self.target_assignments
        )
        self.decision_factors["deferred_count"] = sum(
            item.status == "deferred" for item in self.target_assignments
        )
        self.selected_combination = list(
            dict.fromkeys(
                bsm
                for item in placed
                for bsm in ([item.selected_bsm] if item.selected_bsm else []) + item.selected_bsms
                if bsm
            )
        )
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
    classification_decision: ClassificationDecision | None = None
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
