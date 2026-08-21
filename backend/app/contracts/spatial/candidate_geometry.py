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
        if not self.candidate_id:
            payload = {
                "target_id": self.target_id,
                "kind": self.kind,
                "role": self.role,
                "candidate_membership": self.candidate_membership,
                "materialization_role": self.materialization_role,
                "wkt": self.wkt,
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
            }
            raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            self.candidate_id = f"candidate:{hashlib.sha256(raw).hexdigest()[:24]}"
        return self

    @property
    def is_executable(self) -> bool:
        return self.role == "execution_geometry" and bool(self.wkt)


__all__ = [
    "GeometryKind",
    "GeometryRole",
    "CandidateMembership",
    "GeometryGranularity",
    "SpatialDomainKind",
    "CandidateGeometry",
]
