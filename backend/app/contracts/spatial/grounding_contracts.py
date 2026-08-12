from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.contracts.artifacts.contract_meta import ContractMeta, StageIssue
from app.contracts.artifacts.provenance import Provenance


class HardConstraintResult(BaseModel):
    constraint_id: str = ""
    passed: bool = True
    violation_detail: str = ""


class SpatialQueryEvidence(BaseModel):
    query_type: str = ""
    query_params: dict = Field(default_factory=dict)
    result_count: int = 0
    result_refs: list[str] = Field(default_factory=list)
    target_id: str = ""
    spec_id: str = ""


class CandidateSite(BaseModel):
    site_id: str
    source_parcels: list[str] = Field(default_factory=list)
    available_geometry_wkt: str = ""
    available_area_ha: float = 0.0
    hard_constraint_result: HardConstraintResult | None = None
    metrics: dict = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    target_ref: str | None = None
    project_ref: str | None = None


class GroundingResult(ContractMeta):
    schema_version: Literal["2.0"] = "2.0"
    candidates: list[CandidateSite] = Field(default_factory=list)
    unresolved: list[StageIssue] = Field(default_factory=list)
    spatial_query_evidence: list[SpatialQueryEvidence] = Field(default_factory=list)
    provenance: "Provenance | None" = None

__all__ = [
    "HardConstraintResult",
    "SpatialQueryEvidence",
    "CandidateSite",
    "GroundingResult",
]
