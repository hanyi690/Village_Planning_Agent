"""GIS module — core exports.

Architecture (schema migrated to app.modules.schema):
  - data/        — data fetching, loading, providers

Migrated out (see docs/gis/proposals/03_TOOL_FIRST_ARCHITECTURE.md):
  - schema/      → app.modules.schema/ (top-level shared contract)
  - spatial_context → app.modules.spatial_ops/
  - analysis/    → tools/gis/_conflict/, _validation/, _analytics/
  - generation/  → tools/gis/_generation/
  - rendering/   → tools/gis/_rendering/
  - kg/          → modules/kg/
  - utils/       → app/utils/
"""

# ── Core schema (moved to app.modules.schema — top-level shared contract) ──
from app.modules.schema import (
    BBox, CRS, GeoFeature, ProviderLandParcel, GISDataBundle, GISMetadata,
    SpatialFeature,
    BaseLandUseParcel, CurrentLandUseParcel, PlannedLandUseParcel,
    AdminArea, AdminBoundaryLine,
    CurrentBuilding, CurrentRoad, CurrentFacility, CurrentAnnotation,
    PlannedRoad, GeologicalHazardPoint, ConditionalConstructionZone,
    ControlLine, FarmlandProtection, EcologicalRedline,
    CultivatedLandTarget, UrbanDevBoundary, VillageDevBoundary,
    HazardControlLine, FloodControlLine, HistoricalProtection,
    LandUseZone, ConstructionCtrlZone, PlanningScope,
    SPACE_CONTROL_ZONE_TYPES, SPACE_CONTROL_ZONE_COLORS,
    EncodingRegistry, get_encoding_registry,
    ZoneIntent, FacilityIntent, AxisIntent, ConstraintIntent,
    UnifiedSpatialIntent,
    ConflictItem, ConflictReport, ViolationItem, ValidationReport,
    AllocationResult, ExportResult,
    DLBM_TO_ZONE_TYPE,
    ZONE_TYPE_TO_DLBMS,
    DLBM_TO_DLMC,
    get_zone_type_for_dlbm,
    PLANNING_ZONE_COLORS,
    GDB_LAYER_REGISTRY,
)

# ── Data layer ──
from .data.fetcher import GISDataFetcher, get_fetcher

# ── Provider layer ──
from .data.providers.base import GISProvider, GeoProviderResult
from .data.providers.orchestrator import GISDataOrchestrator, get_orchestrator

__all__ = [
    # Schema
    "BBox", "CRS", "GeoFeature", "ProviderLandParcel", "GISDataBundle", "GISMetadata",
    "SpatialFeature",
    "BaseLandUseParcel", "CurrentLandUseParcel", "PlannedLandUseParcel",
    "AdminArea", "AdminBoundaryLine",
    "CurrentBuilding", "CurrentRoad", "CurrentFacility", "CurrentAnnotation",
    "PlannedRoad", "GeologicalHazardPoint", "ConditionalConstructionZone",
    "ControlLine", "FarmlandProtection", "EcologicalRedline",
    "CultivatedLandTarget", "UrbanDevBoundary", "VillageDevBoundary",
    "HazardControlLine", "FloodControlLine", "HistoricalProtection",
    "LandUseZone", "ConstructionCtrlZone", "PlanningScope",
    "SPACE_CONTROL_ZONE_TYPES", "SPACE_CONTROL_ZONE_COLORS",
    "EncodingRegistry", "get_encoding_registry",
    "ZoneIntent", "FacilityIntent", "AxisIntent", "ConstraintIntent",
    "UnifiedSpatialIntent",
    "ConflictItem", "ConflictReport", "ViolationItem", "ValidationReport",
    "AllocationResult", "ExportResult",
    "DLBM_TO_ZONE_TYPE", "ZONE_TYPE_TO_DLBMS", "DLBM_TO_DLMC",
    "get_zone_type_for_dlbm",
    "PLANNING_ZONE_COLORS",
    "GDB_LAYER_REGISTRY",
    # Data
    "GISDataFetcher", "get_fetcher",
    # Providers
    "GISProvider", "GeoProviderResult",
    "GISDataOrchestrator", "get_orchestrator",
]
