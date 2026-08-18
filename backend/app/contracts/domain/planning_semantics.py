"""Typed planning semantics shared by L3 claims and executable programs."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, Field, model_validator


LinearAssetKind: TypeAlias = Literal[
    "road",
    "water_supply",
    "sewer",
    "stormwater",
    "power",
    "communication",
    "drainage_channel",
    "revetment",
]

LINEAR_ASSET_KINDS = frozenset(
    {
        "road",
        "water_supply",
        "sewer",
        "stormwater",
        "power",
        "communication",
        "drainage_channel",
        "revetment",
    }
)

AssetKind: TypeAlias = Literal[
    "none",
    "facility",
    "land_use",
    "axis",
    "road",
    "water_supply",
    "sewer",
    "stormwater",
    "power",
    "communication",
    "drainage_channel",
    "revetment",
]


MaterializationRole: TypeAlias = Literal[
    "land_use_assignment",
    "functional_overlay",
    "protection_overlay",
    "restoration_overlay",
    "site_footprint",
]

InterventionAction: TypeAlias = Literal[
    "preserve",
    "new",
    "expand",
    "relocate",
    "upgrade",
    "widen",
    "harden",
    "repair",
    "demolish",
]


class RoadPlanningParameters(BaseModel):
    """Normalized road semantics; all dimensions use SI metres.

    The L3 provider extracts source values and units into a draft contract.
    Domain normalization converts them to this model.  Coordinates, BSMs and
    geometry are intentionally absent and remain the responsibility of GROUND.
    """

    action: Literal["preserve", "new", "upgrade", "widen", "harden", "repair"] = "new"
    road_level: str = ""
    length_m: float | None = Field(default=None, gt=0)
    roadbed_width_m: float | None = Field(default=None, gt=0)
    pavement_width_m: float | None = Field(default=None, gt=0)
    alignment_refs: list[str] = Field(default_factory=list)
    connects: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dimensions(self) -> "RoadPlanningParameters":
        for field_name in ("roadbed_width_m", "pavement_width_m"):
            width = getattr(self, field_name)
            if width is not None and not 1.0 <= width <= 30.0:
                raise ValueError(f"{field_name} must be between 1m and 30m")
        if (
            self.roadbed_width_m is not None
            and self.pavement_width_m is not None
            and self.roadbed_width_m < self.pavement_width_m
        ):
            raise ValueError("roadbed_width_m cannot be smaller than pavement_width_m")
        if self.length_m is not None and self.length_m <= 30.0:
            raise ValueError("length_m must be greater than 30m")
        self.alignment_refs = list(dict.fromkeys(self.alignment_refs))
        self.connects = list(dict.fromkeys(self.connects))
        return self


class LinearAssetPlanningParameters(BaseModel):
    """Typed semantics for non-road linear assets before spatial grounding."""

    action: Literal["preserve", "new", "upgrade", "expand", "repair"] = "new"
    length_m: float | None = Field(default=None, gt=0)
    diameter_mm: float | None = Field(default=None, gt=0)
    material: str = ""
    alignment_refs: list[str] = Field(default_factory=list)
    connects: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_refs(self) -> "LinearAssetPlanningParameters":
        self.alignment_refs = list(dict.fromkeys(self.alignment_refs))
        self.connects = list(dict.fromkeys(self.connects))
        return self


class FacilityPlanningParameters(BaseModel):
    """Normalized semantics for a facility point before spatial grounding."""

    facility_type: str = ""
    action: Literal["preserve", "new", "expand", "relocate", "repair"] = "new"
    service_radius_m: float | None = Field(default=None, gt=0)
    capacity: float | None = Field(default=None, gt=0)
    capacity_unit: str = ""
    footprint_area_m2: float | None = Field(default=None, gt=0)


class AxisPlanningParameters(BaseModel):
    """Normalized semantics for a development axis or spatial corridor."""

    action: Literal["preserve", "new", "upgrade"] = "new"
    axis_type: Literal["primary", "secondary", "spatial_control"] = "primary"
    direction: str = ""
    reference_features: list[str] = Field(default_factory=list)
    connects: list[str] = Field(default_factory=list)
    corridor_width_m: float | None = Field(default=None, gt=0)


class PolygonPlanningParameters(BaseModel):
    """Purpose of a polygon without binding it to parcels or geometry.

    Functional zoning is a non-exclusive planning overlay.  It is distinct
    from an authoritative land-use assignment and therefore does not imply a
    parcel reclassification or a mandatory allocation area.
    """

    materialization_role: MaterializationRole
    planning_zone: str = ""
    land_use: str = ""


class SiteAreaPlanningParameters(BaseModel):
    """Scale semantics for a land-consuming site-area intervention."""

    site_type: str = ""
    action: InterventionAction = "new"
    capacity: float | None = Field(default=None, gt=0)
    capacity_unit: str = ""
    footprint_area_m2: float | None = Field(default=None, gt=0)


__all__ = [
    "AssetKind",
    "AxisPlanningParameters",
    "FacilityPlanningParameters",
    "InterventionAction",
    "LINEAR_ASSET_KINDS",
    "LinearAssetKind",
    "LinearAssetPlanningParameters",
    "MaterializationRole",
    "PolygonPlanningParameters",
    "SiteAreaPlanningParameters",
    "RoadPlanningParameters",
]
