"""Versioned policy contracts for candidate suitability evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.spatial.terrain_evidence import TerrainSuitabilityPolicy


class FactorAvailabilityPolicy(BaseModel):
    """Declare whether one evidence factor blocks when unavailable."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    required: bool
    on_unavailable: Literal["block_candidate", "report_only"]


class SuitabilityFactorPolicies(BaseModel):
    """Closed factor set; callers must make every missing-data choice explicit."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    terrain: FactorAvailabilityPolicy
    hazard: FactorAvailabilityPolicy
    farmland_protection: FactorAvailabilityPolicy
    ecological_protection: FactorAvailabilityPolicy
    road_access: FactorAvailabilityPolicy
    facility_coverage: FactorAvailabilityPolicy


class VersionedSuitabilityPolicy(BaseModel):
    """Explicit, immutable policy input for candidate feature construction."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    terrain: TerrainSuitabilityPolicy
    factors: SuitabilityFactorPolicies
    hazard_min_distance_m: float = Field(gt=0)
    road_preferred_distance_m: float = Field(gt=0)
    facility_preferred_distance_m: float = Field(gt=0)

    @model_validator(mode="after")
    def terrain_must_fail_closed(self) -> "VersionedSuitabilityPolicy":
        terrain = self.factors.terrain
        if not terrain.required or terrain.on_unavailable != "block_candidate":
            raise ValueError("terrain factor must be required and block when unavailable")
        return self

    @property
    def ref(self) -> str:
        return f"{self.policy_id}@{self.policy_version}"

    @property
    def digest(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload).hexdigest()


__all__ = [
    "FactorAvailabilityPolicy",
    "SuitabilityFactorPolicies",
    "VersionedSuitabilityPolicy",
    "load_suitability_policy",
]


def load_suitability_policy(path: str | Path | None = None) -> VersionedSuitabilityPolicy:
    """Load the explicit versioned policy used by SELECT.

    Policy thresholds are data, not hidden algorithm constants.  The default
    file is repository-owned and records its planning-standard provenance.
    """
    import yaml
    from app.core.settings import DATA_DIR

    policy_path = Path(path) if path is not None else DATA_DIR / "planning_standards" / "suitability_policy.yaml"
    payload = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    payload.pop("provenance", None)
    return VersionedSuitabilityPolicy.model_validate(payload)
