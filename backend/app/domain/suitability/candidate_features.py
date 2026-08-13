"""Typed, machine-readable candidate feature and availability contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.spatial.terrain_evidence import TerrainEvidenceProvenance


SuitabilityFactor = Literal[
    "terrain",
    "hazard",
    "farmland_protection",
    "ecological_protection",
    "road_access",
    "facility_coverage",
]
AvailabilityStatus = Literal["available", "source_only", "missing", "invalid"]


class EvidenceAvailabilityDiagnostic(BaseModel):
    """Availability is explicit; no missing factor receives a neutral score."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    factor: SuitabilityFactor
    status: AvailabilityStatus
    code: str
    source_fields: tuple[str, ...] = ()
    observed_count: int = Field(default=0, ge=0)
    usable_count: int = Field(default=0, ge=0)
    missing_fields: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    details: dict[str, int | float | str | bool | None] = Field(default_factory=dict)
    blocks_candidate: bool = False


class SuitabilityEvidenceAvailability(BaseModel):
    """Context-level inventory consumed by feature adapters and SELECT gates."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    policy_ref: str
    policy_digest: str
    diagnostics: tuple[EvidenceAvailabilityDiagnostic, ...]

    def for_factor(self, factor: SuitabilityFactor) -> EvidenceAvailabilityDiagnostic:
        return next(item for item in self.diagnostics if item.factor == factor)


class TerrainCandidateFeatures(BaseModel):
    """Terrain values ready for a future SELECT feature matrix."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    status: Literal["available", "missing", "invalid"]
    elevation_min_m: float | None = None
    elevation_max_m: float | None = None
    elevation_mean_m: float | None = None
    elevation_p90_m: float | None = None
    slope_mean_degrees: float | None = None
    slope_p90_degrees: float | None = None
    slope_max_degrees: float | None = None
    relief_m: float | None = None
    valid_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    classification: Literal["preferred", "conditional", "unsuitable", "unknown"]
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    hard_feasible: bool = False
    evidence_ref: str | None = None
    reason_codes: tuple[str, ...] = ()
    provenance: TerrainEvidenceProvenance | None = None


class CandidateSuitabilityFeatures(BaseModel):
    """Target-bound candidate features; this is not a selection decision."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    feature_id: str
    candidate_id: str
    target_id: str
    source_parcels: tuple[str, ...]
    geometry_source: Literal["candidate_wkt", "bundle_source_parcels", "unavailable"]
    geometry_crs: str
    policy_ref: str
    policy_digest: str
    terrain: TerrainCandidateFeatures
    availability: tuple[EvidenceAvailabilityDiagnostic, ...]
    grounding_hard_feasible: bool
    hard_feasible: bool
    blocking_codes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


__all__ = [
    "AvailabilityStatus",
    "CandidateSuitabilityFeatures",
    "EvidenceAvailabilityDiagnostic",
    "SuitabilityEvidenceAvailability",
    "SuitabilityFactor",
    "TerrainCandidateFeatures",
]
