from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .classification_ref import ClassificationRef
from .contract_meta import ContractMeta
from .provenance import Provenance


class ParcelChange(BaseModel):
    bsm: str
    action: str = "modify"  # "preserve"|"reclassify"|"modify"|"split"|"merge"|"create"
    derived_from_bsms: list[str] = Field(default_factory=list)
    before_classification: ClassificationRef | None = None
    after_classification: ClassificationRef | None = None
    before_geometry_wkt: str = ""
    after_geometry_wkt: str = ""
    new_area_ha: float = 0.0


class FacilityChange(BaseModel):
    name: str
    action: str = "create"
    facility_type: str = ""
    area_sqm: float = 0.0
    center: tuple[float, float] | None = None
    derived_from_name: str = ""


class RoadChange(BaseModel):
    name: str
    action: str = "create"
    road_level: str = ""
    width_m: float = 0.0
    path: list[list[float]] = Field(default_factory=list)
    derived_from_name: str = ""


class SettlementChange(BaseModel):
    settlement_name: str
    action: str = "modify"
    new_population: float = 0.0
    new_area_ha: float = 0.0
    target_location: tuple[float, float] | None = None
    merge_into: str = ""


class ParcelChangeSet(ContractMeta):
    changes: list[ParcelChange] = Field(default_factory=list)
    area_conservation_verified: bool = False
    geometry_validity_verified: bool = False
    provenance: "Provenance | None" = None