"""GIS module — core exports.

Architecture (by business function):
  - data/        — data fetching, loading, providers, GDB schema
  - schema/      — data definitions, zone_schema, models (moved in Step 4)
  - analysis/    — accessibility, coverage, conflict detection, validation
  - generation/  — zone/facility/axis generation, optimizer (moved in Step 5)
  - rendering/   — map rendering, layout comparison (moved in Step 5)
  - kg/          — RDF knowledge graph (PlanningKG)
  - utils/       — coordinate/geometry utilities
"""

# ── Core data models (always available) ──
from .models import (
    BBox, CRS, GeoFeature, LandUseParcel, GISDataBundle, GISMetadata,
    EncodingRegistry, get_encoding_registry,
    ZoneIntent, FacilityIntent, AxisIntent, ConstraintIntent,
    UnifiedSpatialIntent,
    ConflictItem, ConflictReport, ViolationItem, ValidationReport,
    AllocationResult, ExportResult,
)

# ── Data layer ──
from .data.fetcher import GISDataFetcher, get_fetcher
from .data.gdb_schema import GDB_LAYER_REGISTRY

# ── Provider layer ──
from .data.providers.base import GISProvider, GeoProviderResult
from .data.providers.orchestrator import GISDataOrchestrator, get_orchestrator

# ── Zone schema exports ──
from .zone_schema import (
    DLBM_TO_ZONE_TYPE,
    ZONE_TYPE_TO_DLBMS,
    DLBM_TO_DLMC,
    get_zone_type_for_dlbm,
    PLANNING_ZONE_COLORS,
)

__all__ = [
    # Models
    "BBox", "CRS", "GeoFeature", "LandUseParcel", "GISDataBundle", "GISMetadata",
    "EncodingRegistry", "get_encoding_registry",
    "ZoneIntent", "FacilityIntent", "AxisIntent", "ConstraintIntent",
    "UnifiedSpatialIntent",
    "ConflictItem", "ConflictReport", "ViolationItem", "ValidationReport",
    "AllocationResult", "ExportResult",
    # Data
    "GISDataFetcher", "get_fetcher", "GDB_LAYER_REGISTRY",
    # Providers
    "GISProvider", "GeoProviderResult",
    "GISDataOrchestrator", "get_orchestrator",
    # Zone schema
    "DLBM_TO_ZONE_TYPE", "ZONE_TYPE_TO_DLBMS", "DLBM_TO_DLMC",
    "get_zone_type_for_dlbm",
    "PLANNING_ZONE_COLORS",
]
