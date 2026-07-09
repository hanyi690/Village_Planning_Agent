"""GIS Layout Engine - spatial layout generation pipeline."""

from .engine import SpatialLayoutEngine
from .conflict_detector import ConflictDetector, ConflictReport
from .conflict_resolver import ConflictResolver, ResolutionReport
from .planning_intent import (
    Direction,
    Density,
    ZoneIntent,
    FacilityIntent,
    AxisIntent,
    ConstraintIntent,
    UnifiedSpatialIntent,
)
from .zone_generator import ZoneGenerator
from .map_renderer import MapRenderer
from .zone_schema import (
    ZONE_TYPE_COLORS,
    FACILITY_STATUS_COLORS,
    DLBM_TO_ZONE_TYPE,
    ZONE_TYPE_TO_DLBMS,
    PLANNED_DLBM_TO_ZONE_TYPE,
    GHYTMC_TO_ZONE_TYPE,
    DLBM_TO_PLANNING_ZONE,
    PLANNING_ZONE_RENDERING,
    PLANNING_ZONE_COLORS,
    get_zone_color,
    get_zone_type_for_dlbm,
    get_zone_type_for_planned_dlbm,
    get_zone_type_for_ghytmc,
    get_dlbms_for_zone_type,
    dlbm_to_planning_zone,
)

__all__ = [
    "SpatialLayoutEngine",
    "ConflictDetector",
    "ConflictReport",
    "ConflictResolver",
    "ResolutionReport",
    "Direction",
    "Density",
    "ZoneIntent",
    "FacilityIntent",
    "AxisIntent",
    "ConstraintIntent",
    "UnifiedSpatialIntent",
    "ZoneGenerator",
    "MapRenderer",
    "ZONE_TYPE_COLORS",
    "FACILITY_STATUS_COLORS",
    "DLBM_TO_ZONE_TYPE",
    "ZONE_TYPE_TO_DLBMS",
    "PLANNED_DLBM_TO_ZONE_TYPE",
    "GHYTMC_TO_ZONE_TYPE",
    "DLBM_TO_PLANNING_ZONE",
    "PLANNING_ZONE_RENDERING",
    "PLANNING_ZONE_COLORS",
    "get_zone_color",
    "get_zone_type_for_dlbm",
    "get_zone_type_for_planned_dlbm",
    "get_zone_type_for_ghytmc",
    "get_dlbms_for_zone_type",
    "dlbm_to_planning_zone",
]
