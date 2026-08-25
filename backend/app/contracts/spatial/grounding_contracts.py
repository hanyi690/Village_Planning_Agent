from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta, StageIssue
from app.contracts.artifacts.provenance import Provenance
from app.contracts.evidence.identity_contracts import infer_geometry_granularity
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.contracts.planning.constraint_factor import ConstraintFactor, RelationSatisfaction
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import GroundedPlanningProblem


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


class CandidateUncertainty(BaseModel):
    """Structured uncertainty for one grounded candidate.

    ``radius_m`` bounds the spatial extent of the resolution (0 means the
    candidate is exact parcel-bound); ``reason_code`` is a stable closed-set
    reason (e.g. ``gazetteer_fuzzy`` / ``village_cluster`` / ``bbox_only``);
    ``source`` names the provenance path that produced the candidate.
    """

    radius_m: float = 0.0
    reason_code: str = ""
    source: str = ""


class CandidateSite(BaseModel):
    site_id: str
    candidate_id: str = ""
    source_parcels: list[str] = Field(default_factory=list)
    available_geometry_wkt: str = ""
    available_area_ha: float = 0.0
    hard_constraint_result: HardConstraintResult | None = None
    metrics: dict = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    target_ref: str | None = None
    project_ref: str | None = None
    confidence: float = 0.0
    identity_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    geometry_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    suitability_score: float | None = None
    compatibility_diagnostics: list[str] = Field(default_factory=list)
    uncertainty: CandidateUncertainty | None = None
    target_kind: str = "unknown"
    expected_output_kind: str = "unknown"
    geometry: CandidateGeometry | None = None
    candidate_bbox: tuple[float, float, float, float] | None = None
    source_area_ha: float = 0.0
    coverage_ratio: float | None = None
    candidate_materialization_allowed: bool = True

    @model_validator(mode="before")
    @classmethod
    def normalize_confidence_accounting(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        payload = dict(raw)
        if payload.get("geometry") is not None:
            return payload
        if (
            payload.get("identity_confidence") is None
            and payload.get("geometry_confidence") is None
        ):
            payload["compatibility_diagnostics"] = list(dict.fromkeys([
                *list(payload.get("compatibility_diagnostics", None) or []),
                "grounding_confidence_missing",
            ]))
            if payload.get("confidence") is not None:
                payload["compatibility_diagnostics"] = list(dict.fromkeys([
                    *list(payload.get("compatibility_diagnostics", None) or []),
                    f"legacy_confidence_untrusted:{float(payload.get('confidence') or 0.0):.6f}".rstrip("0").rstrip("."),
                ]))
        return payload

    @model_validator(mode="after")
    def derive_candidate_id(self) -> "CandidateSite":
        if self.geometry is not None:
            self.candidate_id = self.geometry.candidate_id
            self.identity_confidence = float(self.geometry.identity_confidence or 0.0)
            self.geometry_confidence = float(self.geometry.geometry_confidence or 0.0)
            self.suitability_score = self.geometry.suitability_score
            self.compatibility_diagnostics = list(dict.fromkeys([
                *self.compatibility_diagnostics,
                *list(self.geometry.compatibility_diagnostics or []),
            ]))
        else:
            self.identity_confidence = max(0.0, min(1.0, float(self.identity_confidence or 0.0)))
            self.geometry_confidence = max(0.0, min(1.0, float(self.geometry_confidence or 0.0)))
        if self.geometry_confidence > 0.0 and self.identity_confidence > 0.0:
            self.confidence = self.geometry_confidence
        else:
            self.confidence = float(self.confidence or 0.0)
        return self


class GroundingResult(ContractMeta):
    schema_version: Literal["2.0"] = "2.0"
    candidates: list[CandidateSite] = Field(default_factory=list)
    unresolved: list[StageIssue] = Field(default_factory=list)
    spatial_query_evidence: list[SpatialQueryEvidence] = Field(default_factory=list)
    constraint_factors: list[ConstraintFactor] = Field(default_factory=list)
    relation_satisfaction: list[RelationSatisfaction] = Field(default_factory=list)
    problem: GroundedPlanningProblem | None = None
    provenance: "Provenance | None" = None
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)

class GroundedAnchor(ContractMeta):
    """L1 锚点接地产物：location_fact -> KG 实体/几何 + 拓扑证据（设计 §5.1/§6）。

    ``coordinate_key`` 按"同一坐标 = 同一实体"原则生成；``best_effort`` 表示
    该锚点是低置信推理兜底产物（仍带 KG/索引证据，几何永不来自 LLM）。
    """

    location_fact_ref: str = ""
    mention: str = ""
    normalized_name: str = ""
    role: str = "unknown"
    entity_ref: str = ""
    entity_type: str = ""
    geometry_ref: str | None = None
    feature_bsm: str | None = None
    source_feature_id: str | None = None
    source_layer: str | None = None
    related_parcel_bsms: list[str] = Field(default_factory=list)
    source_bsms: list[str] = Field(default_factory=list)
    relation_refs: list[str] = Field(default_factory=list)
    l1_fact_refs: list[str] = Field(default_factory=list)
    l1_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""
    topology_evidence: list[str] = Field(default_factory=list)
    coordinate_key: str = ""
    confidence: float = 0.0
    status: Literal["resolved", "ambiguous", "unresolved"] = "unresolved"
    best_effort: bool = False
    source_report_ref: str = ""
    source_span: str = ""
    query_trace: list[dict] = Field(default_factory=list)
    geometry_granularity: Literal[
        "exact_feature", "parcel_set", "settlement", "village_scope", "none"
    ] = "none"

    @model_validator(mode="after")
    def derive_geometry_granularity(self) -> "GroundedAnchor":
        if self.geometry_granularity == "none":
            self.geometry_granularity = infer_geometry_granularity(
                self.geometry_ref,
                entity_ref=self.entity_ref,
                source_bsms=self.source_bsms,
            )
        return self


__all__ = [
    "HardConstraintResult",
    "SpatialQueryEvidence",
    "CandidateSite",
    "CandidateUncertainty",
    "CandidateGeometry",
    "ConstraintFactor",
    "RelationSatisfaction",
    "GroundedPlanningProblem",
    "GroundingResult",
    "GroundedAnchor",
]
