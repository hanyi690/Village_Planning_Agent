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
from app.contracts.evidence.requirement_contracts import EvidenceRequirement


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sorted_strings(values: list[str]) -> list[str]:
    return sorted({item for item in values if item})


class CandidateCompleteness(BaseModel):
    """Deterministic GROUND gate projection for candidate readiness."""

    status: Literal[
        "candidate_complete",
        "incomplete",
        "human_required",
        "not_groundable",
    ] = "incomplete"
    target_ids: tuple[str, ...] = Field(default_factory=tuple)
    missing_candidate_target_ids: tuple[str, ...] = Field(default_factory=tuple)
    missing_geometry_target_ids: tuple[str, ...] = Field(default_factory=tuple)
    unresolved_target_ids: tuple[str, ...] = Field(default_factory=tuple)
    candidate_only_target_ids: tuple[str, ...] = Field(default_factory=tuple)
    ambiguous_target_ids: tuple[str, ...] = Field(default_factory=tuple)
    degraded_geometry_target_ids: tuple[str, ...] = Field(default_factory=tuple)
    reasons: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.status == "candidate_complete"


class GroundedCandidateDomain(BaseModel):
    target_id: str
    candidate_ids: list[str] = Field(default_factory=list)
    candidate_geometry_refs: list[str] = Field(default_factory=list)
    geometry_granularities: list[str] = Field(default_factory=list)
    geometry_uncertainty_radius_m: float = Field(default=0.0, ge=0)
    geometry_uncertainty_reasons: list[str] = Field(default_factory=list)
    selection_mode: Literal["all_members", "choose_one", "choose_subset"] = "choose_one"
    min_selected: int = Field(default=0, ge=0)
    max_selected: int | None = Field(default=None, ge=0)
    binding_ref: str = ""
    status: Literal["resolved", "candidate_only", "ambiguous", "unresolved"] = "unresolved"
    deferred_reason: str = ""

    @model_validator(mode="after")
    def canonicalize_refs(self) -> "GroundedCandidateDomain":
        self.candidate_ids = _sorted_strings(self.candidate_ids)
        self.candidate_geometry_refs = _sorted_strings(self.candidate_geometry_refs)
        self.geometry_granularities = _sorted_strings(self.geometry_granularities)
        self.geometry_uncertainty_reasons = _sorted_strings(self.geometry_uncertainty_reasons)
        if self.selection_mode == "all_members" and self.candidate_ids:
            self.min_selected = len(self.candidate_ids)
            self.max_selected = len(self.candidate_ids)
        elif self.selection_mode == "choose_one" and self.candidate_ids:
            self.min_selected = 1
            self.max_selected = 1
        elif self.max_selected is not None and self.max_selected < self.min_selected:
            raise ValueError("max_selected must be >= min_selected")
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


class ParcelResource(BaseModel):
    """One source parcel resource available to a bounded SELECT solver.

    Candidate geometry is target-specific; this record is the shared
    capacity ledger keyed by the source BSM.  It is deliberately separate so
    two targets cannot each assume they own the same parcel extent.
    """

    resource_id: str = Field(min_length=1)
    bsm: str = Field(min_length=1)
    geometry_ref: str = Field(min_length=1)
    source_area_ha: float = Field(gt=0)
    eligible_area_ha: float = Field(default=0.0, ge=0)
    availability_status: Literal[
        "fully_available",
        "partially_available",
        "fully_unavailable",
        "unknown",
    ] = "unknown"
    candidate_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    adjacent_parcel_bsms: list[str] = Field(default_factory=list)
    adjacency_evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonicalize(self) -> "ParcelResource":
        self.candidate_ids = _sorted_strings(self.candidate_ids)
        self.source_refs = _sorted_strings(self.source_refs)
        self.evidence_refs = _sorted_strings(self.evidence_refs)
        self.adjacent_parcel_bsms = _sorted_strings(self.adjacent_parcel_bsms)
        self.adjacency_evidence_refs = _sorted_strings(self.adjacency_evidence_refs)
        tolerance = 1e-9
        if self.eligible_area_ha > self.source_area_ha + tolerance:
            raise ValueError("parcel eligible area cannot exceed source area")
        if self.availability_status == "fully_unavailable" and self.eligible_area_ha > tolerance:
            raise ValueError("fully_unavailable parcel resource cannot have eligible area")
        if self.availability_status == "partially_available" and self.eligible_area_ha <= tolerance:
            raise ValueError("partially_available parcel resource requires eligible area")
        if self.availability_status == "fully_available" and self.eligible_area_ha <= tolerance:
            raise ValueError("fully_available parcel resource requires eligible area")
        return self


class ParcelResourcePool(BaseModel):
    """Shared parcel capacity and adjacency context for SELECT replay."""

    pool_id: str = Field(min_length=1)
    resources: list[ParcelResource] = Field(default_factory=list)
    provenance_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonicalize(self) -> "ParcelResourcePool":
        self.resources = sorted(self.resources, key=lambda item: item.bsm)
        self.provenance_refs = _sorted_strings(self.provenance_refs)
        bsms = [item.bsm for item in self.resources]
        if len(bsms) != len(set(bsms)):
            raise ValueError("parcel resource pool cannot contain duplicate BSM resources")
        return self


def derive_parcel_resource_pool(
    candidate_geometries: list[CandidateGeometry],
    *,
    pool_id: str = "grounded-parcel-pool",
) -> ParcelResourcePool | None:
    """Build a conservative shared resource view from source-backed candidates.

    This helper never invents capacity.  Candidates without a source BSM,
    positive source area, or geometry/evidence lineage are omitted.  A pool
    with no valid resource is represented as ``None`` so specialized SELECT
    remains explicitly unresolved.
    """

    grouped: dict[str, list[CandidateGeometry]] = {}
    for candidate in candidate_geometries:
        source_area = float(candidate.source_area_ha or 0.0)
        if source_area <= 0 or not candidate.wkt:
            continue
        for bsm in candidate.source_bsms:
            if bsm:
                grouped.setdefault(str(bsm), []).append(candidate)
    resources: list[ParcelResource] = []
    for bsm, candidates in sorted(grouped.items()):
        # Coarse bundle extents are retained in the candidate catalog for
        # recall, but they must not poison a source parcel's availability
        # proof when SELECT has an exact, source-backed member for the same
        # BSM.  If no executable member exists, retain the raw set so the
        # resource remains explicitly unresolved/fail-closed.
        executable_candidates = [
            item
            for item in candidates
            if bool(getattr(item, "is_executable", False))
            and str(getattr(item, "hard_constraint_status", "") or "")
            == "passed"
        ]
        if executable_candidates:
            candidates = executable_candidates
        source_areas = [float(item.source_area_ha or 0.0) for item in candidates]
        source_area = max(source_areas)
        eligible_values = [
            float(item.eligible_area_ha)
            for item in candidates
            if item.eligible_area_ha is not None
        ]
        eligible_area = max(eligible_values or [0.0])
        statuses = {str(item.availability_status) for item in candidates}
        if len(statuses) > 1 or "unknown" in statuses:
            # Candidate-specific suitability facts may describe different
            # exclusions on the same source BSM.  A mixed status set is not a
            # parcel-wide availability fact, so keep the shared resource
            # unresolved instead of collapsing it to full or partial.
            availability = "unknown"
        elif "partially_available" in statuses:
            availability = "partially_available"
        elif "fully_available" in statuses:
            availability = "fully_available"
        else:
            availability = "fully_unavailable"
        if availability in {"fully_available", "partially_available"} and eligible_area <= 1e-9:
            # A status without a positive eligibility measurement is not a
            # usable capacity fact.  Keep it explicit as unknown instead of
            # making the resource pool constructor fail or inventing area.
            availability = "unknown"
        refs = sorted({
            ref
            for item in candidates
            for ref in [*item.source_refs, *item.source_feature_ids]
            if ref
        })
        evidence = sorted({
            ref
            for item in candidates
            for ref in item.evidence_refs
            if ref
        })
        geometry_ref = next(
            (
                ref
                for item in candidates
                for ref in [*item.source_feature_ids, *item.source_refs]
                if ref
            ),
            f"parcel:{bsm}",
        )
        resources.append(ParcelResource(
            resource_id=f"parcel-resource:{bsm}",
            bsm=bsm,
            geometry_ref=geometry_ref,
            source_area_ha=source_area,
            eligible_area_ha=min(max(eligible_area, 0.0), source_area),
            availability_status=availability,
            candidate_ids=[item.candidate_id for item in candidates],
            source_refs=refs,
            evidence_refs=evidence,
            adjacent_parcel_bsms=[
                neighbor
                for item in candidates
                for neighbor in item.adjacent_parcel_bsms
            ],
            adjacency_evidence_refs=[
                ref
                for item in candidates
                for ref in item.adjacency_evidence_refs
            ],
        ))
    if not resources:
        return None
    return ParcelResourcePool(pool_id=pool_id, resources=resources)


def _candidate_completeness(
    target_domains: list[GroundedTargetDomain],
    candidate_domains: list[GroundedCandidateDomain],
    unresolved: list[GroundingFinding],
    deferred: list[GroundingFinding],
) -> CandidateCompleteness:
    target_map = {item.target_id: item for item in target_domains if item.target_id}
    candidate_map = {item.target_id: item for item in candidate_domains if item.target_id}
    target_ids = tuple(sorted(set(target_map).union(candidate_map)))
    unresolved_ids = tuple(
        sorted(
            {
                item.target_id
                for item in unresolved
                if item.target_id
            }
            .union(
                item.target_id
                for item in target_domains
                if item.status == "unresolved" and item.target_id
            )
        )
    )
    unresolved_candidate_ids = {
        item.target_id
        for item in candidate_domains
        if item.status == "unresolved" and item.target_id
    }
    candidate_only_ids = {
        item.target_id
        for item in candidate_domains
        if item.status == "candidate_only" and item.target_id
    }
    ambiguous_candidate_ids = {
        item.target_id
        for item in candidate_domains
        if item.status == "ambiguous" and item.target_id
    }
    unresolved_ids = tuple(sorted(set(unresolved_ids).union(unresolved_candidate_ids)))
    ambiguous_ids = {
        item.target_id
        for item in target_domains
        if item.status == "ambiguous" and item.target_id
    }
    deferred_ids = {
        item.target_id
        for item in deferred
        if item.target_id
    }
    missing_candidates = {
        target_id
        for target_id in target_ids
        if target_id not in candidate_map
        or not candidate_map[target_id].candidate_ids
        or target_map.get(target_id) is not None
        and (
            target_map[target_id].status != "resolved"
            or not target_map[target_id].candidate_site_refs
        )
    }
    missing_geometry = {
        target_id
        for target_id, domain in candidate_map.items()
        if domain.candidate_ids and not domain.candidate_geometry_refs
    }
    degraded_geometry = {
        target_id
        for target_id, domain in candidate_map.items()
        if domain.geometry_uncertainty_reasons
    }
    reasons: list[str] = []
    if unresolved_candidate_ids:
        reasons.append("one or more candidate domains remain unresolved")
    if candidate_only_ids:
        reasons.append("one or more candidate domains are candidate-only and require review")
    if ambiguous_candidate_ids:
        reasons.append("one or more candidate domains are ambiguous and require review")
    if unresolved_ids:
        reasons.append("unresolved grounding findings remain")
    if ambiguous_ids:
        reasons.append("ambiguous target identities require human review")
    if deferred_ids:
        reasons.append("deferred grounding targets require an explicit decision")
    if missing_candidates:
        reasons.append("one or more targets have no resolved candidate members")
    if missing_geometry:
        reasons.append("one or more candidate members have no geometry reference")
    if degraded_geometry:
        reasons.append("one or more candidate geometries are degraded or uncertain and require policy review")
    if not target_ids:
        reasons.append("no grounded planning targets are available")
    if unresolved_ids:
        status = "not_groundable"
    elif (
        ambiguous_ids
        or deferred_ids
        or degraded_geometry
        or (candidate_only_ids - missing_geometry)
        or ambiguous_candidate_ids
    ):
        status = "human_required"
    elif missing_candidates or missing_geometry or not target_ids:
        status = "incomplete"
    else:
        status = "candidate_complete"
    return CandidateCompleteness(
        status=status,
        target_ids=target_ids,
        missing_candidate_target_ids=tuple(sorted(missing_candidates)),
        missing_geometry_target_ids=tuple(sorted(missing_geometry)),
        unresolved_target_ids=unresolved_ids,
        candidate_only_target_ids=tuple(sorted(candidate_only_ids)),
        ambiguous_target_ids=tuple(sorted(ambiguous_candidate_ids)),
        degraded_geometry_target_ids=tuple(sorted(degraded_geometry)),
        reasons=tuple(dict.fromkeys(reasons)),
    )


class GroundedPlanningProblem(ContractMeta):
    schema_version: Literal["2.0"] = "2.0"
    # Optional typed routing fact compiled by TARGET_PROJECTION/GROUND.  The
    # structural ``auto`` value is derived only from closed domains and
    # relations; it never means that a backend may silently guess.
    solver_kind: Literal[
        "auto",
        "single_choice",
        "coverage",
        "parcel_assignment",
        "network_path",
        "topology_layout",
        "bounded_multiobjective",
    ] = "auto"
    solver_kind_reasons: list[str] = Field(default_factory=list)
    # ``full`` is the immutable GROUND planning boundary.  A
    # ``deferred_target_subset`` is a new SELECT-owned planning boundary
    # derived from it after an explicit DeferralLedger decision.  Keeping the
    # parent fingerprint on the child prevents a scoped re-solve from being
    # mistaken for a fresh grounding result.
    scope_policy: Literal["full", "deferred_target_subset"] = "full"
    parent_problem_fingerprint: str = ""
    deferred_target_ids: list[str] = Field(default_factory=list)
    scope_reason: str = ""
    scope_source_refs: list[str] = Field(default_factory=list)
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
    parcel_resource_pool: ParcelResourcePool | None = None
    network_refs: list[str] = Field(default_factory=list)
    shared_resource_refs: list[str] = Field(default_factory=list)
    unresolved: list[GroundingFinding] = Field(default_factory=list)
    deferred: list[GroundingFinding] = Field(default_factory=list)
    candidate_completeness: CandidateCompleteness = Field(default_factory=CandidateCompleteness)
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)
    fingerprint: str = ""

    @model_validator(mode="after")
    def derive_fingerprint(self) -> "GroundedPlanningProblem":
        self.solver_kind_reasons = _sorted_strings(self.solver_kind_reasons)
        self.target_domains = sorted(self.target_domains, key=lambda item: item.target_id)
        self.constraint_factors = sorted(self.constraint_factors, key=lambda item: item.factor_id)
        self.relation_satisfaction = sorted(
            self.relation_satisfaction,
            key=lambda item: item.relation_id,
        )
        self.diagnostics = sorted([item for item in self.diagnostics if item], key=lambda item: item)
        self.deferred_target_ids = _sorted_strings(self.deferred_target_ids)
        self.scope_source_refs = _sorted_strings(self.scope_source_refs)
        self.source_artifact_refs = _sorted_strings(self.source_artifact_refs)
        self.bindings = sorted(self.bindings, key=lambda item: item.binding_id)
        self.candidate_domains = sorted(self.candidate_domains, key=lambda item: item.target_id)
        self.candidate_geometries = sorted(
            self.candidate_geometries,
            key=lambda item: item.candidate_id,
        )
        if self.parcel_resource_pool is None:
            self.parcel_resource_pool = derive_parcel_resource_pool(
                self.candidate_geometries,
                pool_id=f"grounded-parcel-pool:{self.intent_graph_fingerprint or 'unknown'}",
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
        self.candidate_completeness = _candidate_completeness(
            self.target_domains,
            self.candidate_domains,
            self.unresolved,
            self.deferred,
        )
        if not self.fingerprint:
            payload = self.model_dump(
                mode="json",
                exclude={
                    "fingerprint",
                    "created_at",
                    "candidate_completeness",
                    "evidence_requirements",
                },
            )
            raw = _canonical_json(payload).encode("utf-8")
            self.fingerprint = hashlib.sha256(raw).hexdigest()
        return self

    @property
    def can_solve(self) -> bool:
        return self.candidate_completeness.ready


__all__ = [
    "GroundedTargetDomain",
    "CandidateCompleteness",
    "GroundedCandidateDomain",
    "GroundingBinding",
    "GroundingFinding",
    "ParcelResource",
    "ParcelResourcePool",
    "derive_parcel_resource_pool",
    "GroundedPlanningProblem",
]
