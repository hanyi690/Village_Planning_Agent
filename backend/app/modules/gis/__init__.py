"""GIS module — core exports.

Architecture (by business function):
  - data/        — data fetching, loading, providers
  - schema/      — data definitions, encodings, classification, GDB schema, models
  - analysis/    — accessibility, coverage, conflict detection, validation
  - generation/  — zone/facility/axis generation, optimizer
  - rendering/   — map rendering, layout comparison
  - kg/          — RDF knowledge graph (PlanningKG)
  - utils/       — coordinate/geometry utilities
"""

# ── Core schema (unified: models + zone_schema + gdb_schema) ──
from .schema import (
    BBox, CRS, GeoFeature, LandUseParcel, GISDataBundle, GISMetadata,
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
    "BBox", "CRS", "GeoFeature", "LandUseParcel", "GISDataBundle", "GISMetadata",
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
