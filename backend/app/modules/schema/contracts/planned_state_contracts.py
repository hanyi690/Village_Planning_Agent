from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .contract_meta import ContractMeta
from .provenance import Provenance


class PlannedParcel(BaseModel):
    bsm: str = ""
    project_ref: str = ""
    planning_land_use: str = ""
    zone_type: str = ""
    area_ha: float = 0.0
    geometry: str = ""  # WKT
    derived_from_bsms: list[str] = Field(default_factory=list)
    derived_from_zone_target: str = ""
    source_spec: str = ""
    decided_by: str = ""
    operation: str = ""
    area_change_ha: float = 0.0


class PlannedZone(BaseModel):
    zone_type: str = ""
    area_ha: float = 0.0
    name: str = ""
    geometry: str = ""
    derived_from_zone_target: str = ""


class CoverageDomain(BaseModel):
    """Explicit boundary whose declared zones must form a partition/coverage."""

    domain_id: str
    domain_type: Literal["partition", "coverage"] = "partition"
    boundary_geometry: str
    zone_refs: list[str] = Field(default_factory=list)


class PlannedFacility(BaseModel):
    name: str = ""
    facility_type: str = ""
    lon: float = 0.0
    lat: float = 0.0
    service_radius: float = 0.0
    geometry: str = ""
    derived_from_target: str = ""


class PlannedRoad(BaseModel):
    name: str = ""
    road_level: str = ""
    width_m: float = 0.0
    geometry: str = ""
    derived_from_target: str = ""


class PlannedAxis(BaseModel):
    name: str = ""
    reference_feature: str = ""
    direction: str = ""
    geometry: str = ""
    derived_from_target: str = ""


class PlannedProjectPoint(BaseModel):
    """Small spatial marker for a project whose output is a point."""

    project_ref: str = ""
    name: str = ""
    geometry: str = ""


class PlannedState(ContractMeta):
    version: str = "v1"
    parcels: list[PlannedParcel] = Field(default_factory=list)
    zones: list[PlannedZone] = Field(default_factory=list)
    coverage_domains: list[CoverageDomain] = Field(default_factory=list)
    facilities: list[PlannedFacility] = Field(default_factory=list)
    project_points: list[PlannedProjectPoint] = Field(default_factory=list)
    roads: list[PlannedRoad] = Field(default_factory=list)
    axes: list[PlannedAxis] = Field(default_factory=list)
    source: str = ""
    provenance: "Provenance | None" = None
