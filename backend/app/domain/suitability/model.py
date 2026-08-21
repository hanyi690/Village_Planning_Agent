"""Typed suitability results; no final allocation is performed here."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.contract_meta import ContractMeta


class SuitabilityCandidate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    candidate_id: str
    target_id: str = ""
    source_parcels: list[str] = Field(default_factory=list)
    score: float = 0.0
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    hard_feasible: bool = False
    exclusion_reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    available_geometry_wkt: str = ""
    available_area_ha: float = 0.0
    source_area_ha: float = 0.0
    coverage_ratio: float | None = Field(default=None, ge=0, le=1)
    geometry_operation: str = "bundle_extent"
    geometry_crs: str = "EPSG:4326"
    geometry_diagnostics: list[str] = Field(default_factory=list)
    policy_ref: str = ""
    feature_ref: str = ""
    availability_diagnostics: list[dict[str, object]] = Field(default_factory=list)


class SuitabilitySurface(ContractMeta):
    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    digest: str = ""
    parent_digests: dict[str, str] = Field(default_factory=dict)
    provenance: dict[str, object] = Field(default_factory=dict)
    candidates: list[SuitabilityCandidate] = Field(default_factory=list)
    target_diagnostics: dict[str, list[str]] = Field(default_factory=dict)


__all__ = ["SuitabilityCandidate", "SuitabilitySurface"]
