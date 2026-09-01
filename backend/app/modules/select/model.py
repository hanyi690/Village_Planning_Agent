"""Typed portfolio allocation output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.contract_meta import ContractMeta


AllocationStatus = Literal["OPTIMAL", "FEASIBLE", "INFEASIBLE", "MODEL_INVALID", "UNKNOWN"]


class AllocationAssignment(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    demand_id: str
    target_id: str
    candidate_id: str = ""
    source_parcels: list[str] = Field(default_factory=list)
    resource_refs: list[str] = Field(default_factory=list)
    representation_refs: list[str] = Field(default_factory=list)
    geometry_ref: str = ""
    status: Literal["assigned", "unplaced", "deferred", "action"]
    reason: str = ""


class PortfolioDecision(ContractMeta):
    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    digest: str = ""
    parent_digests: dict[str, str] = Field(default_factory=dict)
    provenance: dict[str, object] = Field(default_factory=dict)
    solver_status: AllocationStatus = "UNKNOWN"
    assignments: list[AllocationAssignment] = Field(default_factory=list)
    unmet_demand: list[str] = Field(default_factory=list)
    objective_value: float = 0.0
    diagnostics: list[str] = Field(default_factory=list)


__all__ = ["AllocationStatus", "AllocationAssignment", "PortfolioDecision"]
