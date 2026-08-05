from __future__ import annotations

from pydantic import BaseModel, Field

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


class SiteSelectionDecision(ContractMeta):
    selected_combination: list[str] = Field(default_factory=list)
    full_ranking: list[RankedCandidate] = Field(default_factory=list)
    eliminated: list[EliminatedCandidate] = Field(default_factory=list)
    decision_factors: dict = Field(default_factory=dict)
    review_status: str = "pending_review"  # "auto" | "pending_review" | "human_approved"
    provenance: "Provenance | None" = None

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
    "SiteSelectionDecision",
    "LandDesignBrief",
]