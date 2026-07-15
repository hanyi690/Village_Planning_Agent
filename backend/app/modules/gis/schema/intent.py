"""Spatial intent models — the canonical definition for WHAT goes WHERE.

Single source of truth for intent models. Pydantic BaseModel for runtime
validation and LLM structured output. Replaces the former dataclass versions
in planning_intent.py.

Produced by: LLM via with_structured_output(UnifiedSpatialIntent)
Consumed by: ZoneGenerator, FacilityPlacer, AxisBuilder, allocate/generate tools
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class Direction(str, Enum):
    """Spatial direction qualifier for zone/facility placement."""

    CENTER = "center"
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    NORTHEAST = "northeast"
    NORTHWEST = "northwest"
    SOUTHEAST = "southeast"
    SOUTHWEST = "southwest"
    PERIPHERY = "periphery"
    EAST_WEST = "east-west"
    NORTH_SOUTH = "north-south"


class Density(str, Enum):
    """Development density qualifier."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ZoneIntent(BaseModel):
    """Declarative intent for a functional zone.

    One per zone mentioned in planning text. Answers: what land use,
    how much area, which direction, what adjacency constraints.
    """

    zone_id: str = ""
    land_use: str = ""  # Must match PLANNING_COLORS keys
    dlbm: str = ""  # Primary DLBM code: "2121", "0600", etc.
    dlbm_aliases: List[str] = Field(default_factory=list)  # Secondary DLBM codes
    area_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    direction: Direction = Direction.CENTER
    reference_feature: str = ""
    adjacent_to: List[str] = Field(default_factory=list)
    avoid_adjacent_to: List[str] = Field(default_factory=list)
    density: Density = Density.MEDIUM
    preserve_existing: bool = True


class FacilityIntent(BaseModel):
    """Declarative intent for a facility point placement."""

    facility_id: str = ""
    facility_type: str = ""
    target_zone: str = ""
    location_hint: str = ""
    status: str = "existing"  # "existing" | "new" | "planned"


class AxisIntent(BaseModel):
    """Declarative intent for a development axis."""

    axis_id: str = ""
    axis_type: str = ""
    direction: Direction = Direction.CENTER
    connects: List[str] = Field(default_factory=list)
    label: str = ""


class ConstraintIntent(BaseModel):
    """Declarative spatial constraint for layout generation."""

    constraint_id: str = ""
    constraint_type: str = ""
    geometry_ref: str = ""
    strict: bool = True


class UnifiedSpatialIntent(BaseModel):
    """Complete spatial intent — the single source of truth for layout content.

    Produced by: ConflictResolver + LLM intent extraction from planning text
    Consumed by: ZoneGenerator, FacilityPlacer, AxisBuilder
    """

    zones: List[ZoneIntent] = Field(default_factory=list)
    facilities: List[FacilityIntent] = Field(default_factory=list)
    axes: List[AxisIntent] = Field(default_factory=list)
    constraints: List[ConstraintIntent] = Field(default_factory=list)
    conflicts_resolved: Optional[Any] = None  # ResolutionReport (avoid circular import)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def total_area_ratio(self) -> float:
        """Sum of all zone area ratios (should be <= 1.0)."""
        return sum(z.area_ratio for z in self.zones)

    def get_zone_by_id(self, zone_id: str) -> Optional[ZoneIntent]:
        for z in self.zones:
            if z.zone_id == zone_id:
                return z
        return None

    def get_zone_by_land_use(self, land_use: str) -> List[ZoneIntent]:
        return [z for z in self.zones if z.land_use == land_use]


__all__ = [
    "Direction",
    "Density",
    "ZoneIntent",
    "FacilityIntent",
    "AxisIntent",
    "ConstraintIntent",
    "UnifiedSpatialIntent",
]
