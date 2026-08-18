"""Grounded planning problem: target domains plus auditable relations."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.planning.constraint_factor import (
    ConstraintFactor,
    RelationSatisfaction,
)
from app.contracts.spatial.candidate_geometry import CandidateGeometry


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sorted_strings(values: list[str]) -> list[str]:
    return sorted({item for item in values if item})


class GroundedCandidateDomain(BaseModel):
    target_id: str
    candidate_ids: list[str] = Field(default_factory=list)
    candidate_geometry_refs: list[str] = Field(default_factory=list)
    status: Literal["resolved", "candidate_only", "ambiguous", "unresolved"] = "unresolved"
    deferred_reason: str = ""

    @model_validator(mode="after")
    def canonicalize_refs(self) -> "GroundedCandidateDomain":
        self.candidate_ids = _sorted_strings(self.candidate_ids)
        self.candidate_geometry_refs = _sorted_strings(self.candidate_geometry_refs)
        return self


class GroundingBinding(BaseModel):
    binding_id: str
    target_id: str
    entity_ref: str = ""
    geometry_ref: str = ""
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonicalize_refs(self) -> "GroundingBinding":
        self.evidence_refs = _sorted_strings(self.evidence_refs)
        return self


class GroundingFinding(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"] = "warning"
    message: str
    target_id: str = ""
    relation_id: str = ""


class GroundedTargetDomain(BaseModel):
    target_id: str
    target_kind: str = "unknown"
    expected_output_kind: str = "unknown"
    candidate_site_refs: list[str] = Field(default_factory=list)
    geometry_roles: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    status: Literal["resolved", "candidate_only", "ambiguous", "unresolved"] = "unresolved"
    unresolved_reason: str = ""

    @model_validator(mode="after")
    def canonicalize_refs(self) -> "GroundedTargetDomain":
        self.candidate_site_refs = _sorted_strings(self.candidate_site_refs)
        self.geometry_roles = _sorted_strings(self.geometry_roles)
        self.evidence_refs = _sorted_strings(self.evidence_refs)
        return self


class GroundedPlanningProblem(ContractMeta):
    schema_version: Literal["2.0"] = "2.0"
    target_domains: list[GroundedTargetDomain] = Field(default_factory=list)
    constraint_factors: list[ConstraintFactor] = Field(default_factory=list)
    relation_satisfaction: list[RelationSatisfaction] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    intent_graph_fingerprint: str = ""
    baseline_ref: str = ""
    source_artifact_refs: list[str] = Field(default_factory=list)
    bindings: list[GroundingBinding] = Field(default_factory=list)
    candidate_domains: list[GroundedCandidateDomain] = Field(default_factory=list)
    candidate_geometries: list[CandidateGeometry] = Field(default_factory=list)
    network_refs: list[str] = Field(default_factory=list)
    shared_resource_refs: list[str] = Field(default_factory=list)
    unresolved: list[GroundingFinding] = Field(default_factory=list)
    deferred: list[GroundingFinding] = Field(default_factory=list)
    fingerprint: str = ""

    @model_validator(mode="after")
    def derive_fingerprint(self) -> "GroundedPlanningProblem":
        self.target_domains = sorted(self.target_domains, key=lambda item: item.target_id)
        self.constraint_factors = sorted(self.constraint_factors, key=lambda item: item.factor_id)
        self.relation_satisfaction = sorted(
            self.relation_satisfaction,
            key=lambda item: item.relation_id,
        )
        self.diagnostics = sorted([item for item in self.diagnostics if item], key=lambda item: item)
        self.source_artifact_refs = _sorted_strings(self.source_artifact_refs)
        self.bindings = sorted(self.bindings, key=lambda item: item.binding_id)
        self.candidate_domains = sorted(self.candidate_domains, key=lambda item: item.target_id)
        self.candidate_geometries = sorted(
            self.candidate_geometries,
            key=lambda item: item.candidate_id,
        )
        self.network_refs = _sorted_strings(self.network_refs)
        self.shared_resource_refs = _sorted_strings(self.shared_resource_refs)
        self.unresolved = sorted(
            self.unresolved,
            key=lambda item: (item.code, item.target_id, item.relation_id, item.message),
        )
        self.deferred = sorted(
            self.deferred,
            key=lambda item: (item.code, item.target_id, item.relation_id, item.message),
        )
        if not self.fingerprint:
            payload = self.model_dump(mode="json", exclude={"fingerprint", "created_at"})
            raw = _canonical_json(payload).encode("utf-8")
            self.fingerprint = hashlib.sha256(raw).hexdigest()
        return self


__all__ = [
    "GroundedTargetDomain",
    "GroundedCandidateDomain",
    "GroundingBinding",
    "GroundingFinding",
    "GroundedPlanningProblem",
]
