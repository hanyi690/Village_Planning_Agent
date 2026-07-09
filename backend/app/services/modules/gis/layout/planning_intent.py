"""
Declarative planning intent models for GIS layout generation.

These models represent WHAT should be placed WHERE (semantically),
not HOW to compute the geometry (that's ZoneGenerator's job).

LLM produces these intents from planning text + conflict resolution;
algorithms turn them into GeoJSON using reference data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .conflict_resolver import ResolutionReport


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


@dataclass
class ZoneIntent:
    """Declarative intent for a functional zone.

    ZoneIntent answers: what land use, how much area, which direction,
    what adjacency constraints. Geometry computation is ZoneGenerator's job.
    """
    zone_id: str
    land_use: str          # Must match PLANNING_COLORS keys: 居住用地, 产业用地, etc.
    dlbm: str              # Primary DLBM code: "2121", "0600", "0900", etc.
    area_ratio: float      # Target area as fraction of total boundary area (0.0-1.0)
    direction: Direction   # Preferred placement direction within boundary
    reference_feature: str = ""   # Semantic anchor: "near village committee", etc.
    adjacent_to: List[str] = field(default_factory=list)
    avoid_adjacent_to: List[str] = field(default_factory=list)
    density: Density = Density.MEDIUM
    preserve_existing: bool = True  # Prefer reclassifying existing parcels over new geometry
    dlbm_aliases: List[str] = field(default_factory=list)  # Secondary DLBM codes to include


@dataclass
class FacilityIntent:
    """Declarative intent for a facility point placement."""
    facility_id: str
    facility_type: str     # 村委会, 学校, 卫生站, etc.
    target_zone: str       # zone_id of the zone this facility belongs to
    location_hint: str = ""  # "village center", "near main road", etc.
    status: str = "existing"  # existing / planned / upgraded


@dataclass
class AxisIntent:
    """Declarative intent for a development axis."""
    axis_id: str
    axis_type: str         # primary / secondary / corridor
    direction: Direction   # Overall axis orientation
    connects: List[str] = field(default_factory=list)  # zone_ids or facility_ids
    label: str = ""        # Display name: "主要发展轴", etc.


@dataclass
class ConstraintIntent:
    """Declarative constraint for layout generation."""
    constraint_id: str
    constraint_type: str   # farmland_protection / ecological_redline / historical / hazard
    geometry_ref: str = ""  # Reference to GIS data layer key
    strict: bool = True    # If True, zone cannot overlap; if False, warn only


@dataclass
class UnifiedSpatialIntent:
    """Unified planning intent after conflict resolution.

    This is the single source of truth for what the layout should contain.
    Produced by ConflictResolver + LLM intent extraction from planning text.
    Consumed by ZoneGenerator / FacilityPlacer / AxisBuilder.
    """
    zones: List[ZoneIntent] = field(default_factory=list)
    facilities: List[FacilityIntent] = field(default_factory=list)
    axes: List[AxisIntent] = field(default_factory=list)
    constraints: List[ConstraintIntent] = field(default_factory=list)
    conflicts_resolved: Optional[ResolutionReport] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

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
