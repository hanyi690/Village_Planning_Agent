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
GeometryGranularity = Literal[
    "exact_feature", "parcel_set", "settlement", "village_scope", "none"
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
    # Target semantic role (e.g. site_footprint vs protection_overlay).  It
    # is distinct from ``role`` above, which describes geometry provenance
    # and executability.
    materialization_role: str = ""
    wkt: str = ""
    crs: str = "EPSG:4326"
    granularity: GeometryGranularity = "none"
    source_ref: str = ""
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    uncertainty_radius_m: float = 0.0
    uncertainty_reason: str = ""
    source_bsms: list[str] = Field(default_factory=list)
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
        if not self.candidate_id:
            payload = {
                "target_id": self.target_id,
                "kind": self.kind,
                "role": self.role,
                "materialization_role": self.materialization_role,
                "wkt": self.wkt,
                "crs": self.crs,
                "granularity": self.granularity,
                "source_ref": self.source_ref,
                "source_refs": self.source_refs,
                "source_bsms": self.source_bsms,
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
    "GeometryGranularity",
    "CandidateGeometry",
]
