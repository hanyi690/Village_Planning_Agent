"""Typed suitability results; no final allocation is performed here."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.schema.contracts.contract_meta import ContractMeta


class SuitabilityCandidate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    candidate_id: str
    target_id: str = ""
    source_parcels: list[str] = Field(default_factory=list)
    score: float = 0.0
    hard_feasible: bool = False
    exclusion_reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class SuitabilitySurface(ContractMeta):
    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    digest: str = ""
    parent_digests: dict[str, str] = Field(default_factory=dict)
    provenance: dict[str, object] = Field(default_factory=dict)
    candidates: list[SuitabilityCandidate] = Field(default_factory=list)
    target_diagnostics: dict[str, list[str]] = Field(default_factory=dict)


__all__ = ["SuitabilityCandidate", "SuitabilitySurface"]
