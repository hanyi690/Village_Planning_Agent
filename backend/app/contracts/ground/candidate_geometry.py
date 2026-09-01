"""Typed candidate geometry contracts for evidence-first grounding."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


GeometryKind = Literal["point", "line", "polygon", "multipatch", "unknown"]
GeometryRole = Literal[
    "execution_geometry",
    "anchor_geometry",
    "corridor_candidate",
    "parcel_candidate",
    "scope_geometry",
    "unknown",
]
AvailabilityStatus = Literal[
    "fully_available",
    "partially_available",
    "fully_unavailable",
    "unknown",
]
CandidateMembership = Literal["alternative", "required_member"]
GeometryGranularity = Literal[
    "exact_feature", "parcel_extent", "parcel_set", "settlement", "village_scope", "bbox", "corridor", "none"
]
SpatialDomainKind = Literal[
    "exact_feature", "parcel_extent", "parcel_set", "bbox", "corridor", "village_scope", "unknown"
]


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric


def _clamp_unit_interval(value: Any) -> float:
    return max(0.0, min(1.0, _finite_float(value, 0.0)))


class CandidateSchemaDiagnostic(BaseModel):
    """Typed schema/readiness diagnostic for one candidate artifact."""

    code: str
    message: str
    field: str = ""
    refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonicalize(self) -> "CandidateSchemaDiagnostic":
        self.refs = sorted({str(item) for item in self.refs if str(item).strip()})
        return self


class CandidateGeometry(BaseModel):
    """A geometry claim with an explicit semantic role.

    A parcel union used to search for a utility corridor is deliberately not
    labelled as an execution line.  This prevents downstream workers from
    treating a recall geometry as a final GIS feature.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = ""
    target_id: str = ""
    physical_project_ref: str = ""
    component_claim_refs: list[str] = Field(default_factory=list)
    component_fact_refs: list[str] = Field(default_factory=list)
    kind: GeometryKind = "unknown"
    role: GeometryRole = "unknown"
    # ``alternative`` means SELECT must choose among competing identities.
    # ``required_member`` is reserved for an explicitly bound source
    # collection whose members jointly form one target (for example a
    # current-road network).  Geometry provenance alone must never imply that
    # every same-name feature should be executed.
    candidate_membership: CandidateMembership = "alternative"
    # Target semantic role (e.g. site_footprint vs protection_overlay).  It
    # is distinct from ``role`` above, which describes geometry provenance
    # and executability.
    materialization_role: str = ""
    wkt: str = ""
    # Parent usable extent before a target-sized footprint is carved out.
    # It is distinct from ``wkt`` when a large parcel is subdivided.
    eligible_geometry_wkt: str = ""
    crs: str = "EPSG:4326"
    source_crs: str = ""
    source_snapshot_ref: str = ""
    resource_digest: str = ""
    operation: str = "read"
    granularity: GeometryGranularity = "none"
    spatial_domain_kind: SpatialDomainKind = "unknown"
    candidate_bbox: tuple[float, float, float, float] | None = None
    source_area_ha: float | None = Field(default=None, ge=0)
    planning_area_ha: float | None = Field(default=None, ge=0)
    coverage_ratio: float | None = Field(default=None, ge=0, le=1)
    source_ref: str = ""
    source_refs: list[str] = Field(default_factory=list)
    part_ref: str = ""
    resource_refs: list[str] = Field(default_factory=list)
    representation_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    identity_confidence: float | None = Field(default=None, ge=0, le=1)
    geometry_confidence: float | None = Field(default=None, ge=0, le=1)
    suitability_score: float | None = None
    schema_status: Literal["valid", "pending", "schema_invalid"] = "pending"
    schema_diagnostics: list[CandidateSchemaDiagnostic] = Field(default_factory=list)
    uncertainty_radius_m: float = 0.0
    uncertainty_reason: str = ""
    source_bsms: list[str] = Field(default_factory=list)
    feature_bsms: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    entity_refs: list[str] = Field(default_factory=list)
    relation_refs: list[str] = Field(default_factory=list)
    l1_fact_refs: list[str] = Field(default_factory=list)
    l1_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""
    source_binding_ref: str = ""
    subgeometry_operation: str = "bundle_extent"
    subgeometry_diagnostics: list[str] = Field(default_factory=list)
    generation_operation: str = "grounded_candidate"
    hard_constraint_status: Literal["pending", "passed", "failed", "deferred", "unknown"] = "pending"
    # Availability is distinct from hard-constraint status.  A source parcel
    # may contain both prohibited and usable subareas, so a failed whole-parcel
    # probe must not erase a valid clipped footprint.
    availability_status: AvailabilityStatus = "unknown"
    eligible_area_ha: float | None = Field(default=None, ge=0)
    excluded_area_ha: float | None = Field(default=None, ge=0)
    adjacent_parcel_bsms: list[str] = Field(default_factory=list)
    adjacency_evidence_refs: list[str] = Field(default_factory=list)
    suitability_components: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def derive_stable_candidate_id(self) -> "CandidateGeometry":
        if self.source_ref and self.source_ref not in self.source_refs:
            self.source_refs = [*self.source_refs, self.source_ref]
        self.source_refs = sorted({item for item in self.source_refs if item})
        self.resource_refs = sorted({
            str(item) for item in self.resource_refs
            if str(item).strip()
        })
        self.representation_refs = sorted({
            str(item) for item in self.representation_refs
            if str(item).strip()
        })
        self.resource_refs = sorted({
            *self.resource_refs,
            *(item for item in self.source_refs if str(item).startswith("resource:")),
        })
        self.evidence_refs = sorted({item for item in self.evidence_refs if item})
        self.component_claim_refs = sorted({
            str(item) for item in self.component_claim_refs if str(item).strip()
        })
        self.component_fact_refs = sorted({
            str(item) for item in self.component_fact_refs if str(item).strip()
        })
        self.source_bsms = sorted({item for item in self.source_bsms if item})
        self.feature_bsms = sorted({item for item in self.feature_bsms if item})
        self.source_feature_ids = sorted({item for item in self.source_feature_ids if item})
        self.entity_refs = sorted({item for item in self.entity_refs if item})
        self.relation_refs = sorted({item for item in self.relation_refs if item})
        self.l1_fact_refs = sorted({item for item in self.l1_fact_refs if item})
        self.subgeometry_diagnostics = sorted({item for item in self.subgeometry_diagnostics if item})
        self.adjacent_parcel_bsms = sorted({item for item in self.adjacent_parcel_bsms if item})
        self.adjacency_evidence_refs = sorted({item for item in self.adjacency_evidence_refs if item})
        if not self.candidate_id:
            payload = {
                "target_id": self.target_id,
                "kind": self.kind,
                "role": self.role,
                "candidate_membership": self.candidate_membership,
                "materialization_role": self.materialization_role,
                "wkt": self.wkt,
                "eligible_geometry_wkt": self.eligible_geometry_wkt,
                "crs": self.crs,
                "granularity": self.granularity,
                "spatial_domain_kind": self.spatial_domain_kind,
                "candidate_bbox": self.candidate_bbox,
                "source_area_ha": self.source_area_ha,
                "planning_area_ha": self.planning_area_ha,
                "coverage_ratio": self.coverage_ratio,
                "source_ref": self.source_ref,
                "source_refs": self.source_refs,
                "part_ref": self.part_ref,
                "resource_refs": self.resource_refs,
                "representation_refs": self.representation_refs,
                "source_bsms": self.source_bsms,
                "feature_bsms": self.feature_bsms,
                "source_feature_ids": self.source_feature_ids,
                "entity_refs": self.entity_refs,
                "relation_refs": self.relation_refs,
                "l1_fact_refs": self.l1_fact_refs,
                "l1_snapshot_ref": self.l1_snapshot_ref,
                "bundle_snapshot_digest": self.bundle_snapshot_digest,
                "source_binding_ref": self.source_binding_ref,
                "subgeometry_operation": self.subgeometry_operation,
                "subgeometry_diagnostics": self.subgeometry_diagnostics,
                "evidence_refs": self.evidence_refs,
                "generation_operation": self.generation_operation,
                "availability_status": self.availability_status,
                "eligible_area_ha": self.eligible_area_ha,
                "excluded_area_ha": self.excluded_area_ha,
                "adjacent_parcel_bsms": self.adjacent_parcel_bsms,
                "adjacency_evidence_refs": self.adjacency_evidence_refs,
            }
            raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            self.candidate_id = f"candidate:{hashlib.sha256(raw).hexdigest()[:24]}"
        return self

    @model_validator(mode="after")
    def canonicalize_schema(self) -> "CandidateGeometry":
        if self.suitability_score is not None:
            self.suitability_score = _finite_float(self.suitability_score, 0.0)
        diagnostics = list(self.schema_diagnostics)
        if self.identity_confidence is None:
            diagnostics.append(CandidateSchemaDiagnostic(
                code="grounding_identity_confidence_missing",
                message="candidate geometry is missing explicit identity_confidence",
                field="identity_confidence",
            ))
        if self.geometry_confidence is None:
            diagnostics.append(CandidateSchemaDiagnostic(
                code="grounding_geometry_confidence_missing",
                message="candidate geometry is missing explicit geometry_confidence",
                field="geometry_confidence",
            ))
        self.schema_diagnostics = sorted(
            {item.model_dump_json(): item for item in diagnostics}.values(),
            key=lambda item: (item.code, item.field, item.message),
        )
        if self.schema_status != "schema_invalid":
            self.schema_status = "pending" if self.schema_diagnostics else "valid"
        return self

    @model_validator(mode="after")
    def validate_availability_semantics(self) -> "CandidateGeometry":
        """Reject contradictory whole-parcel/partial-availability claims."""
        tolerance = 1e-9
        source = float(self.source_area_ha or 0.0)
        eligible = self.eligible_area_ha
        excluded = self.excluded_area_ha
        if source > tolerance:
            if eligible is not None and float(eligible) > source + tolerance:
                raise ValueError("eligible_area_ha cannot exceed source_area_ha")
            if excluded is not None and float(excluded) > source + tolerance:
                raise ValueError("excluded_area_ha cannot exceed source_area_ha")
            if self.planning_area_ha is not None and float(self.planning_area_ha) > source + tolerance:
                raise ValueError("planning_area_ha cannot exceed source_area_ha")
        if (
            eligible is not None
            and self.planning_area_ha is not None
            and float(self.planning_area_ha) > float(eligible) + tolerance
        ):
            raise ValueError("planning_area_ha cannot exceed eligible_area_ha")
        if self.availability_status == "fully_unavailable":
            if eligible is not None and float(eligible) > tolerance:
                raise ValueError("fully_unavailable candidate cannot have eligible area")
            if self.planning_area_ha is not None and float(self.planning_area_ha) > tolerance:
                raise ValueError("fully_unavailable candidate cannot have planning area")
        elif self.availability_status == "partially_available":
            if eligible is not None and float(eligible) <= tolerance:
                raise ValueError("partially_available candidate requires positive eligible area")
        elif self.availability_status == "fully_available":
            if excluded is not None and float(excluded) > tolerance:
                raise ValueError("fully_available candidate cannot have excluded area")
        return self

    @property
    def is_executable(self) -> bool:
        return (
            self.grounding_ready
            and self.role == "execution_geometry"
            and bool(self.wkt)
            # A geometry string is only a materialization value.  The
            # executable authority must be a DATA representation backed by a
            # loadable resource.  This prevents a legacy bundle/provider
            # geometry from being promoted to SELECT merely because it has a
            # valid WKT and a non-zero confidence.
            and bool(self.target_id)
            and len(self.entity_refs) == 1
            and bool(self.part_ref)
            and len(self.resource_refs) == 1
            and len(self.representation_refs) == 1
            and len(self.source_feature_ids) == 1
            and bool(self.materialization_role)
            and bool(self.evidence_refs)
            and bool(self.source_snapshot_ref)
            and bool(self.resource_digest)
            and bool(self.crs)
            and self.granularity == "exact_feature"
            and self.spatial_domain_kind == "exact_feature"
            and self.hard_constraint_status == "passed"
            and self.availability_status in {
                "fully_available",
                "partially_available",
            }
            and not self.uncertainty_reason.startswith("duplicate_bsm_geometry_identity")
        )

    @property
    def grounding_ready(self) -> bool:
        return self.grounding_confidence_trusted

    @property
    def grounding_confidence_trusted(self) -> bool:
        if self.schema_status != "valid":
            return False
        if self.identity_confidence is None or self.geometry_confidence is None:
            return False
        return self.identity_confidence > 0.0 and self.geometry_confidence > 0.0

    @property
    def grounding_needs_review(self) -> bool:
        return not self.grounding_confidence_trusted


__all__ = [
    "GeometryKind",
    "GeometryRole",
    "CandidateMembership",
    "AvailabilityStatus",
    "GeometryGranularity",
    "SpatialDomainKind",
    "CandidateSchemaDiagnostic",
    "CandidateGeometry",
]
