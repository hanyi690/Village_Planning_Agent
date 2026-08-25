"""Small typed contracts that close the P1 planning lineage boundary.

The builders in this module are intentionally deterministic.  They only use
typed intervention/spec/relation data already produced by the planning
pipeline; they never turn prose or an untrusted mapping into evidence.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.planning.constraint_factor import ConstraintFactor, RelationSatisfaction
from app.contracts.spatial.spatial_reference_contracts import SpatialReferenceSpec


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sorted_refs(values: Sequence[str]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


class PhysicalProject(BaseModel):
    """Canonical solver unit assembled from one or more dimension claims."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    project_id: str = ""
    package_ref: str = Field(min_length=1)
    variant_key: str = Field(min_length=1)
    materialization_role: str = ""
    assembly_mode: Literal["canonical", "split"] = "canonical"
    component_claim_refs: list[str] = Field(default_factory=list)
    component_fact_refs: list[str] = Field(default_factory=list)
    target_refs: list[str] = Field(default_factory=list)
    intervention_refs: list[str] = Field(default_factory=list)
    fingerprint: str = ""

    @model_validator(mode="after")
    def canonicalize_and_fingerprint(self) -> "PhysicalProject":
        self.package_ref = self.package_ref.strip()
        self.variant_key = self.variant_key.strip()
        self.materialization_role = self.materialization_role.strip()
        for name in (
            "component_claim_refs",
            "component_fact_refs",
            "target_refs",
            "intervention_refs",
        ):
            setattr(self, name, _sorted_refs(getattr(self, name)))
        payload = self.model_dump(mode="json", exclude={"project_id", "fingerprint"})
        derived_id = f"physical-project:{_digest(payload)[:24]}"
        if self.project_id and self.project_id != derived_id:
            raise ValueError("physical project id does not match canonical content")
        if self.fingerprint and self.fingerprint != _digest(payload):
            raise ValueError("physical project fingerprint does not match content")
        self.project_id = derived_id
        self.fingerprint = _digest(payload)
        return self


class PhysicalProjectAssembly(BaseModel):
    """Stable assembly and component-to-project join for TARGET/GROUND."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    projects: list[PhysicalProject] = Field(default_factory=list)
    component_project_refs: dict[str, str] = Field(default_factory=dict)
    fingerprint: str = ""

    @model_validator(mode="after")
    def canonicalize_and_fingerprint(self) -> "PhysicalProjectAssembly":
        self.projects = sorted(self.projects, key=lambda item: item.project_id)
        self.component_project_refs = {
            str(key): str(value)
            for key, value in sorted(self.component_project_refs.items())
            if str(key).strip() and str(value).strip()
        }
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        derived = _digest(payload)
        if self.fingerprint and self.fingerprint != derived:
            raise ValueError("physical project assembly fingerprint does not match content")
        self.fingerprint = derived
        return self

    def project_for_component(self, component_ref: str) -> PhysicalProject | None:
        project_ref = self.component_project_refs.get(component_ref, "")
        return next((item for item in self.projects if item.project_id == project_ref), None)


def _intervention_variant(intervention: object) -> str:
    explicit = str(getattr(intervention, "variant_key", "") or "").strip()
    if explicit:
        return explicit
    return _canonical_json({
        "category": str(getattr(intervention, "category", "") or ""),
        "output_kind": str(getattr(intervention, "expected_output_kind", "") or ""),
        "asset_kind": str(getattr(intervention, "asset_kind", "") or ""),
    })


def build_physical_project_assembly(
    interventions: Sequence[object],
    claims: Sequence[object] = (),
) -> PhysicalProjectAssembly:
    """Group same-package compatible interventions into canonical projects."""

    claim_by_id = {
        str(getattr(claim, "claim_id", "")): claim
        for claim in claims
        if str(getattr(claim, "claim_id", "")).strip()
    }
    groups: dict[tuple[str, str, str], list[object]] = {}
    for intervention in interventions:
        package_ref = str(getattr(intervention, "project_package_ref", "") or "").strip()
        if not package_ref or str(getattr(intervention, "planning_role", "")) != "spatial_intervention":
            continue
        key = (
            package_ref,
            _intervention_variant(intervention),
            str(getattr(intervention, "materialization_role", "") or "").strip(),
        )
        groups.setdefault(key, []).append(intervention)

    projects: list[PhysicalProject] = []
    component_refs: dict[str, str] = {}
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda item: str(getattr(item, "intervention_id", "")))
        claim_refs = [
            claim_ref
            for member in members
            for claim_ref in (getattr(member, "claim_refs", None) or [])
        ]
        fact_refs = [
            fact_ref
            for member in members
            for fact_ref in (getattr(member, "source_fact_refs", None) or [])
        ]
        for claim_ref in list(claim_refs):
            claim = claim_by_id.get(str(claim_ref))
            if claim is not None:
                fact_refs.extend(getattr(claim, "source_fact_refs", None) or [])
        project = PhysicalProject(
            package_ref=key[0],
            variant_key=key[1],
            materialization_role=key[2],
            component_claim_refs=claim_refs,
            component_fact_refs=fact_refs,
            target_refs=[str(getattr(item, "target_id", "")) for item in members],
            intervention_refs=[str(getattr(item, "intervention_id", "")) for item in members],
        )
        projects.append(project)
        for member in members:
            intervention_ref = str(getattr(member, "intervention_id", "") or "").strip()
            target_ref = str(getattr(member, "target_id", "") or "").strip()
            for component_ref in (intervention_ref, target_ref, *list(getattr(member, "claim_refs", None) or [])):
                if component_ref:
                    component_refs[component_ref] = project.project_id
    return PhysicalProjectAssembly(projects=projects, component_project_refs=component_refs)


class GroundingRequest(BaseModel):
    """Formal GROUND request, including source authority and pending state."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = ""
    target_ref: str = Field(min_length=1)
    physical_project_ref: str = ""
    intervention_ref: str = ""
    component_claim_refs: list[str] = Field(default_factory=list)
    component_fact_refs: list[str] = Field(default_factory=list)
    semantic_spec: SpatialReferenceSpec
    retrieval_scopes: list[str] = Field(default_factory=list)
    source_collection_key: str = ""
    source_snapshot_ref: str = ""
    source_snapshot_digest: str = ""
    source_binding_ref: str = ""
    source_binding_fingerprint: str = ""
    requested_geometry_kind: Literal["parcel", "polygon", "point", "line", "action", "unknown"] = "unknown"
    materialization_role: str = ""
    status: Literal["ready", "pending"] = "pending"
    defer_reason: str = ""
    request_fingerprint: str = ""

    @model_validator(mode="after")
    def canonicalize_and_validate(self) -> "GroundingRequest":
        self.component_claim_refs = _sorted_refs(self.component_claim_refs)
        self.component_fact_refs = _sorted_refs(self.component_fact_refs)
        self.retrieval_scopes = _sorted_refs(self.retrieval_scopes)
        self.source_collection_key = self.source_collection_key.strip()
        self.source_snapshot_ref = self.source_snapshot_ref.strip()
        self.source_snapshot_digest = self.source_snapshot_digest.strip()
        self.source_binding_ref = self.source_binding_ref.strip()
        self.materialization_role = self.materialization_role.strip()
        if self.source_binding_ref:
            binding_payload = {
                "binding_ref": self.source_binding_ref,
                "collection": self.source_collection_key,
                "snapshot": self.source_snapshot_ref,
                "digest": self.source_snapshot_digest,
            }
            derived_binding = f"source-binding:{_digest(binding_payload)[:24]}"
            if self.source_binding_fingerprint and self.source_binding_fingerprint != derived_binding:
                raise ValueError("source binding fingerprint does not match content")
            self.source_binding_fingerprint = derived_binding
        reasons: list[str] = []
        if not self.source_snapshot_ref:
            reasons.append("source_snapshot_missing")
        if not self.source_binding_ref:
            reasons.append("source_binding_missing")
        if self.semantic_spec.unresolved_reason:
            reasons.append(self.semantic_spec.unresolved_reason)
        if self.defer_reason:
            reasons.append(self.defer_reason)
        if reasons:
            self.status = "pending"
            self.defer_reason = ";".join(dict.fromkeys(reasons))
        elif self.status != "ready":
            self.status = "ready"
        payload = self.model_dump(mode="json", exclude={"request_id", "status", "defer_reason", "request_fingerprint"})
        derived = _digest(payload)
        if self.request_fingerprint and self.request_fingerprint != derived:
            raise ValueError("grounding request fingerprint does not match content")
        self.request_fingerprint = derived
        self.request_id = self.request_id or f"grounding-request:{derived[:24]}"
        return self


def build_grounding_request(
    spec: SpatialReferenceSpec,
    *,
    physical_project_ref: str = "",
    component_claim_refs: Sequence[str] = (),
    component_fact_refs: Sequence[str] = (),
    source_snapshot_ref: str = "",
    source_snapshot_digest: str = "",
    defer_reason: str = "",
) -> GroundingRequest:
    reference_kind = str(spec.reference.kind if spec.reference is not None else "")
    requested_geometry_kind = {
        "bsm": "parcel",
    }.get(reference_kind, "unknown")
    return GroundingRequest(
        target_ref=str(spec.target_id or spec.intervention_id or spec.spec_id),
        physical_project_ref=physical_project_ref,
        intervention_ref=str(spec.intervention_id or ""),
        component_claim_refs=list(component_claim_refs),
        component_fact_refs=list(component_fact_refs),
        semantic_spec=spec,
        retrieval_scopes=spec.all_retrieval_scopes(),
        source_collection_key=str(spec.source_collection_key or ""),
        source_snapshot_ref=str(source_snapshot_ref or spec.source_snapshot_ref or ""),
        source_snapshot_digest=str(source_snapshot_digest or spec.source_snapshot_digest or ""),
        source_binding_ref=str(spec.source_binding_ref or ""),
        requested_geometry_kind=requested_geometry_kind,
        materialization_role=str(spec.materialization_role or ""),
        defer_reason=defer_reason,
    )


class DecisionFingerprint(BaseModel):
    """Question identity used to validate a HUMAN decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_ref: str = Field(min_length=1)
    physical_project_ref: str = ""
    grounding_request_fingerprint: str = ""
    source_snapshot_ref: str = ""
    source_snapshot_digest: str = ""
    constraint_fingerprint: str = ""
    evaluator_key: str = ""
    evaluator_version: str = ""
    fingerprint: str = ""

    @model_validator(mode="after")
    def derive_fingerprint(self) -> "DecisionFingerprint":
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        derived = _digest(payload)
        if self.fingerprint and self.fingerprint != derived:
            raise ValueError("decision fingerprint does not match content")
        object.__setattr__(self, "fingerprint", derived)
        return self


def build_decision_fingerprint(
    *,
    target_ref: str,
    physical_project_ref: str = "",
    grounding_request_fingerprint: str = "",
    source_snapshot_ref: str = "",
    source_snapshot_digest: str = "",
    constraint_fingerprint: str = "",
    evaluator_key: str = "",
    evaluator_version: str = "",
) -> DecisionFingerprint:
    return DecisionFingerprint(
        target_ref=target_ref,
        physical_project_ref=physical_project_ref,
        grounding_request_fingerprint=grounding_request_fingerprint,
        source_snapshot_ref=source_snapshot_ref,
        source_snapshot_digest=source_snapshot_digest,
        constraint_fingerprint=constraint_fingerprint,
        evaluator_key=evaluator_key,
        evaluator_version=evaluator_version,
    )


class HumanDecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    decision_id: str = ""
    decision_fingerprint: DecisionFingerprint
    action: Literal["approve", "reject", "defer", "changes_requested"]
    decided_by: str = Field(min_length=1)
    comment: str = ""
    record_fingerprint: str = ""

    @model_validator(mode="after")
    def derive_record_fingerprint(self) -> "HumanDecisionRecord":
        payload = self.model_dump(mode="json", exclude={"decision_id", "record_fingerprint"})
        derived = _digest(payload)
        if self.record_fingerprint and self.record_fingerprint != derived:
            raise ValueError("human decision record fingerprint does not match content")
        self.record_fingerprint = derived
        self.decision_id = self.decision_id or f"human-decision:{derived[:24]}"
        return self

    def assert_current(self, current: DecisionFingerprint) -> None:
        if self.decision_fingerprint.fingerprint != current.fingerprint:
            raise ValueError("human decision fingerprint is stale")


class RelationReadiness(BaseModel):
    """Deterministic relation readiness used by SELECT preflight."""

    model_config = ConfigDict(extra="forbid")

    factor_id: str
    hard: bool
    status: Literal["ready", "blocked", "advisory", "pending"]
    evaluator_key: str
    evaluator_version: str = ""
    required_refs: list[str] = Field(default_factory=list)
    source_snapshot_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


def build_relation_readiness(
    factor: ConstraintFactor,
    satisfaction: RelationSatisfaction | None = None,
    *,
    evaluator_available: bool = True,
) -> RelationReadiness:
    evaluator_key = str(factor.evaluator_key or factor.kind)
    evaluator_version = str(
        factor.evaluator_version
        or (getattr(satisfaction, "evaluator_version", "") if satisfaction else "")
        or ""
    )
    required_refs = _sorted_refs(factor.required_refs)
    snapshots = _sorted_refs(factor.source_snapshot_refs)
    evidence = _sorted_refs([
        *factor.evidence_refs,
        *(getattr(satisfaction, "evidence_refs", None) or [] if satisfaction else []),
    ])
    reasons: list[str] = []
    status = str(getattr(satisfaction, "status", "") or factor.status)
    if factor.semantic_status != "valid":
        reasons.append(f"semantic:{factor.semantic_status}")
    if factor.input_status != "ready":
        reasons.append(f"input:{factor.input_status}")
    if factor.solver_supported is False:
        reasons.append("solver_unsupported")
    if not evaluator_available:
        reasons.append("evaluator_missing")
    if "source_snapshot" in required_refs and not snapshots:
        reasons.append("source_snapshot_missing")
    if factor.hard and status in {"pending", "deferred", "not_evaluable", "unknown"}:
        reasons.append(f"evaluation:{status}")
    if factor.hard and status in {"satisfied", "violated", "partially_satisfied"} and not evidence:
        reasons.append("evaluation_evidence_missing")
    if reasons:
        readiness_status = "blocked" if factor.hard else "advisory"
    elif factor.hard:
        readiness_status = "ready"
    else:
        readiness_status = "ready" if status in {"satisfied", "violated", "partially_satisfied"} else "pending"
    return RelationReadiness(
        factor_id=factor.factor_id,
        hard=factor.hard,
        status=readiness_status,
        evaluator_key=evaluator_key,
        evaluator_version=evaluator_version,
        required_refs=required_refs,
        source_snapshot_refs=snapshots,
        evidence_refs=evidence,
        reasons=sorted(set(reasons)),
    )


__all__ = [
    "DecisionFingerprint",
    "GroundingRequest",
    "HumanDecisionRecord",
    "PhysicalProject",
    "PhysicalProjectAssembly",
    "RelationReadiness",
    "build_decision_fingerprint",
    "build_grounding_request",
    "build_physical_project_assembly",
    "build_relation_readiness",
]
