"""Typed candidate geometry contracts for evidence-first grounding."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


class CandidateGeometry(BaseModel):
    """A geometry claim with an explicit semantic role.

    A parcel union used to search for a utility corridor is deliberately not
    labelled as an execution line.  This prevents downstream workers from
    treating a recall geometry as a final GIS feature.
    """

    candidate_id: str = ""
    target_id: str = ""
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
    granularity: GeometryGranularity = "none"
    spatial_domain_kind: SpatialDomainKind = "unknown"
    candidate_bbox: tuple[float, float, float, float] | None = None
    source_area_ha: float | None = Field(default=None, ge=0)
    planning_area_ha: float | None = Field(default=None, ge=0)
    coverage_ratio: float | None = Field(default=None, ge=0, le=1)
    source_ref: str = ""
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.0
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
        self.evidence_refs = sorted({item for item in self.evidence_refs if item})
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
            self.role == "execution_geometry"
            and bool(self.wkt)
            and self.availability_status != "fully_unavailable"
            # A parcel candidate without an availability proof must not be
            # widened back to its complete cadastral extent. Exact feature
            # geometries may remain executable when availability is unknown;
            # parcel extents/sets require explicit clipping or availability.
            and not (
                self.availability_status == "unknown"
                and self.kind == "polygon"
                and self.spatial_domain_kind in {"parcel_extent", "parcel_set"}
            )
            and not self.uncertainty_reason.startswith("duplicate_bsm_geometry_identity")
        )


__all__ = [
    "GeometryKind",
    "GeometryRole",
    "CandidateMembership",
    "AvailabilityStatus",
    "GeometryGranularity",
    "SpatialDomainKind",
    "CandidateGeometry",
]
