"""Typed demand contracts; demand never contains candidate parcels."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.schema.contracts.contract_meta import ContractMeta


DemandKind = Literal[
    "project",
    "facility",
    "road",
    "axis",
    "zone",
    "restoration",
    "protection",
    "action",
]


class DemandItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    demand_id: str
    target_id: str
    kind: DemandKind
    geometry_kind: Literal["parcel", "polygon", "point", "line", "action"]
    quantity: float | None = None
    quantity_unit: str = ""
    phase: Literal["short", "medium", "long"] = "short"
    objective_refs: list[str] = Field(default_factory=list)
    claim_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    spatial_requirements: dict[str, object] = Field(default_factory=dict)


class DemandPortfolio(ContractMeta):
    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    digest: str = ""
    parent_digests: dict[str, str] = Field(default_factory=dict)
    provenance: dict[str, object] = Field(default_factory=dict)
    demands: list[DemandItem] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


__all__ = ["DemandKind", "DemandItem", "DemandPortfolio"]
