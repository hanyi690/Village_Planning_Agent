"""GIS schema — unified data definitions, encodings, and output specifications.

Combines former models/, zone_schema/, and data/gdb_schema.py into one package:
  - canonical.py        — BBox, CRS, GeoFeature, GISDataBundle, GISMetadata
  - intent.py           — ZoneIntent, FacilityIntent, AxisIntent, UnifiedSpatialIntent
  - pipeline.py         — ConflictItem, ConflictReport, ValidationReport, ExportResult
  - ingestion.py        — ingest_* (pure injection port); types in spatial_types
  - encoding_registry.py — EncodingRegistry, get_encoding_registry
  - dicts/              — YAML-driven Code Dictionary Center (single source of truth)
  - colors.py           — ZONE_TYPE_COLORS, PLANNING_ZONE_COLORS, color lookup
  - dynamic_zoning.py   — DynamicZoningEngine
  - gdb.py              — GDB_LAYER_REGISTRY, enrich_gdb_fields

All encoding/code-set symbols are now derived from dicts/ YAML data.
Import from this package for convenience, or use dicts/ directly.
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

# ── Canonical data models ──
from .canonical import (
    BBox,
    CRS,
    GeoFeature,
    ProviderLandParcel,
    GISDataBundle,
    GISMetadata,
)

# ── Data contracts (intent + pipeline) ──
from .contracts import (
    Direction,
    Density,
    ZoneIntent,
    FacilityIntent,
    AxisIntent,
    ConstraintIntent,
    UnifiedSpatialIntent,
    ConflictItem,
    ConflictReport,
    ViolationItem,
    ValidationReport,
    AllocationResult,
    ExportResult,
)

# ── Encoding registry (lives in classification) ──
from .classification import EncodingRegistry, get_encoding_registry

# ── Dictionary Center (single source of truth) ──
from .dicts import get_center, CodeDictionary, ProposalTable, DictionaryCenter
from .dicts.candidate_engine import (
    ClassificationProposal,
    CandidateEngine,
    get_candidate_engine,
)

# ── Ingestion layer (pure injection port) ──
from .ingestion import (
    ingest_landuse,
    ingest_current_landuse,
    ingest_planned_landuse,
    ingest_feature,
    ingest_raster,
)

# ── Raster input types (DEM/DOM — not in GDB output) ──
from .raster_types import (
    RasterInput,
    DEMInput,
    DOMInput,
    TerrainAnalysisResult,
    SLOPE_CLASSES,
    ASPECT_CLASSES,
)

# ── Spatial feature types (full taxonomy) ──
from .spatial_types import (
    # Base + LandUse types (moved from ingestion)
    SpatialFeature,
    BaseLandUseParcel,
    CurrentLandUseParcel,
    PlannedLandUseParcel,
    # Encoding constants
    GB_T21010, TUGUI, APPENDIX5, GHFLBM_SYS, YDYHFL, VNE,
    # Group A
    AdminArea,
    AdminBoundaryLine,
    CurrentBuilding,
    CurrentRoad,
    CurrentFacility,
    CurrentAnnotation,
    PlannedRoad,
    GeologicalHazardPoint,
    ConditionalConstructionZone,
    ControlLine,
    FarmlandProtection,
    EcologicalRedline,
    CultivatedLandTarget,
    UrbanDevBoundary,
    VillageDevBoundary,
    HazardControlLine,
    FloodControlLine,
    HistoricalProtection,
    LandUseZone,
    ConstructionCtrlZone,
    PlanningScope,
    ContourLine,
    ElevationPoint,
    WaterFeature,
    PlannedAnnotation,
    SPACE_CONTROL_ZONE_TYPES,
    SPACE_CONTROL_ZONE_COLORS,
)

# ── Colors ──
from .colors import (
    ZONE_TYPE_COLORS,
    FACILITY_STATUS_COLORS,
    FACILITY_TYPE_COLORS,
    DEFAULT_ZONE_COLOR,
    PLANNING_ZONE_COLORS,
    PLANNING_ZONE_RENDERING,
    PRIMARY_ZONE_COLORS,
    SENSITIVITY_COLORS,
    INFRA_COLORS,
    ISOCHRONE_COLORS,
    SPACE_CONTROL_COLORS,
    get_zone_color,
    get_facility_color,
    get_infra_color,
)

# ── Dynamic zoning ──
from .dynamic_zoning import DynamicZoningEngine

# ── GDB output schema ──
from .gdb import (
    FEATURE_TYPE_CODES,
    DEFAULT_GDB_PREFIX,
    DEFAULT_GDB_DATE,
    GDB_LAYER_REGISTRY,
    INTERNAL_LAYER_TO_GDB_KEYS,
    GDB_DTYPE_TO_PYTHON,
    GdbFieldSpec,
    LayerDef,
    make_gdb_layer_name,
    get_gdb_layer_names,
    get_gdb_fields,
    get_internal_layer_for_gdb_key,
    get_gdb_keys_for_internal_layer,
    get_gdb_layers_by_category,
    enrich_gdb_fields,
)

# ── SSE event contracts ──
from .events import (
    GISAnalysisData,
    GISLayerConfig,
    GISMapOptions,
    GisResultEvent,
    GisLayerUpdateEvent,
)

# ── LandUseClass (from dicts, for backward compat) ──
from .classification import LandUseClass


# ── Code sets (all encoding-derived dicts & lookup functions) ──
from .code_sets import (
    # Dicts
    DLBM_TO_DLMC, DLBM_TO_ZONE_TYPE, ZONE_TYPE_TO_DLBMS,
    DLBM_TO_PLANNING_ZONE, DLBM_TO_PRIMARY_ZONE,
    ZONE_TYPES, PLANNING_ZONES, PRIMARY_ZONES,
    PLANNING_ZONE_NAMES, PRIMARY_ZONE_NAMES,
    PLANNING_ZONE_TO_PRIMARY_ZONE,
    GHYTMC_TO_ZONE_TYPE, GHYTMC_TO_DLMC,
    GHFLBM_MEANING, GHFLBM_TO_ZONE_TYPE, GHFLBM_TO_GHYTBMS,
    GHYTBM_TO_GHYTMC, GHYTBM_TO_YDYHFLDM,
    YDYHFLDM_TO_NAME, GHYTBM_TO_ZONE_TYPE,
    VNE_CODE_TO_NAME, VNE_TO_ZONE_TYPE, ZONE_TYPE_TO_VNE,
    GHYTBM_TO_VNE,
    THREE_LINE_TYPES, CONSTRUCTION_ZONE_DEF, ANNOTATION_CATEGORIES,
    SDDLBM_TO_YDYHFLDM, ELEMENT_CODE_PREFIXES,
    # Code sets
    BASIC_FARMLAND_CODES, GENERAL_AGRICULTURE_CODES,
    ECOLOGICAL_CODES, FOREST_CODES,
    FORESTRY_CODES, WATER_CODES,
    ECOLOGICAL_PROTECTION_CODES, ECOLOGICAL_CONTROL_CODES,
    PROTECTED_DLBM_CODES,
    CONSTRUCTION_USE_TYPES, CONSTRUCTION_ZONE_TYPES,
    # Functions
    is_basic_farmland, is_general_agriculture,
    get_zone_type_for_dlbm, get_dlbms_for_zone_type,
    get_zone_type_for_planned_dlbm,
    get_zone_type_for_ghytmc, get_primary_zone,
    dlbm_to_planning_zone, get_primary_zone_for_planning_zone,
    get_zone_type_for_ghflbm, get_zone_type_for_ghytbm,
    get_ghytmc_for_ghytbm,
    get_zone_type_for_vne, get_vne_for_zone_type,
    convert_sddlbm_to_ydyhfldm, get_vne_for_ghytbm,
    parse_element_code,
)

from .classification import ClassificationSchema, get_schema

# SCHEMA via classification module __getattr__ (lazy load)
try:
    from .classification import SCHEMA  # noqa: F811
except ImportError:
    SCHEMA = None  # type: ignore[assignment]



__all__ = [
    # Canonical
    "BBox", "CRS", "GeoFeature", "ProviderLandParcel", "GISDataBundle", "GISMetadata",
    # Spatial types (full taxonomy — ingestion + spatial_types)
    "SpatialFeature",
    "AdminArea", "AdminBoundaryLine",
    "CurrentBuilding", "CurrentRoad", "CurrentFacility", "CurrentAnnotation",
    "PlannedRoad", "PlannedAnnotation", "GeologicalHazardPoint", "ConditionalConstructionZone",
    "ControlLine", "FarmlandProtection", "EcologicalRedline",
    "CultivatedLandTarget", "UrbanDevBoundary", "VillageDevBoundary",
    "HazardControlLine", "FloodControlLine", "HistoricalProtection",
    "LandUseZone", "ConstructionCtrlZone", "PlanningScope",
    "ContourLine", "ElevationPoint", "WaterFeature",
    # Raster input (not in GDB output)
    "RasterInput", "DEMInput", "DOMInput", "TerrainAnalysisResult",
    "SLOPE_CLASSES", "ASPECT_CLASSES",
    "SPACE_CONTROL_ZONE_TYPES", "SPACE_CONTROL_ZONE_COLORS",
    # Intent
    "Direction", "Density",
    "ZoneIntent", "FacilityIntent", "AxisIntent", "ConstraintIntent",
    "UnifiedSpatialIntent",
    # Pipeline
    "ConflictItem", "ConflictReport", "ViolationItem", "ValidationReport",
    "AllocationResult", "ExportResult",
    # Encoding registry
    "EncodingRegistry", "get_encoding_registry",
    # Dictionary Center
    "get_center", "CodeDictionary", "ProposalTable", "DictionaryCenter",
    "ClassificationProposal", "CandidateEngine", "get_candidate_engine",
    # Ingestion (input boundary — typed parcels)
    "BaseLandUseParcel", "CurrentLandUseParcel", "PlannedLandUseParcel",
    "GB_T21010", "TUGUI", "APPENDIX5", "GHFLBM_SYS", "YDYHFL", "VNE",
    "ingest_landuse", "ingest_current_landuse", "ingest_planned_landuse",
    "ingest_feature", "ingest_raster",
    # Classification
    "LandUseClass", "ClassificationSchema", "get_schema", "SCHEMA",
    "ZONE_TYPES", "PLANNING_ZONES", "PRIMARY_ZONES",
    # Encodings
    "DLBM_TO_DLMC", "DLBM_TO_ZONE_TYPE", "ZONE_TYPE_TO_DLBMS",
    "DLBM_TO_PLANNING_ZONE", "DLBM_TO_PRIMARY_ZONE",
    "get_zone_type_for_dlbm", "get_dlbms_for_zone_type",
    "get_zone_type_for_planned_dlbm",
    "GHYTMC_TO_ZONE_TYPE", "GHYTMC_TO_DLMC", "get_zone_type_for_ghytmc",
    "dlbm_to_planning_zone", "get_primary_zone",
    "PLANNING_ZONE_NAMES", "PRIMARY_ZONE_NAMES",
    "PLANNING_ZONE_TO_PRIMARY_ZONE", "get_primary_zone_for_planning_zone",
    "GHFLBM_MEANING", "GHFLBM_TO_ZONE_TYPE", "GHFLBM_TO_GHYTBMS",
    "get_zone_type_for_ghflbm",
    "GHYTBM_TO_GHYTMC", "GHYTBM_TO_YDYHFLDM",
    "YDYHFLDM_TO_NAME", "GHYTBM_TO_ZONE_TYPE",
    "get_zone_type_for_ghytbm", "get_ghytmc_for_ghytbm",
    # Code sets
    "BASIC_FARMLAND_CODES", "GENERAL_AGRICULTURE_CODES",
    "ECOLOGICAL_CODES", "FOREST_CODES",
    "FORESTRY_CODES", "WATER_CODES",
    "ECOLOGICAL_PROTECTION_CODES", "ECOLOGICAL_CONTROL_CODES",
    "PROTECTED_DLBM_CODES",
    "CONSTRUCTION_USE_TYPES", "CONSTRUCTION_ZONE_TYPES",
    "is_basic_farmland", "is_general_agriculture",
    "THREE_LINE_TYPES", "CONSTRUCTION_ZONE_DEF", "ANNOTATION_CATEGORIES",
    "VNE_CODE_TO_NAME", "VNE_TO_ZONE_TYPE", "ZONE_TYPE_TO_VNE",
    "get_zone_type_for_vne", "get_vne_for_zone_type",
    "SDDLBM_TO_YDYHFLDM", "convert_sddlbm_to_ydyhfldm",
    "GHYTBM_TO_VNE", "get_vne_for_ghytbm",
    "ELEMENT_CODE_PREFIXES", "parse_element_code",
    # Colors
    "ZONE_TYPE_COLORS", "FACILITY_STATUS_COLORS", "FACILITY_TYPE_COLORS",
    "DEFAULT_ZONE_COLOR", "PLANNING_ZONE_COLORS", "PLANNING_ZONE_RENDERING",
    "PRIMARY_ZONE_COLORS", "SENSITIVITY_COLORS", "INFRA_COLORS",
    "ISOCHRONE_COLORS", "SPACE_CONTROL_COLORS",
    "get_zone_color", "get_facility_color", "get_infra_color",
    # Dynamic zoning
    "DynamicZoningEngine",
    # GDB
    "FEATURE_TYPE_CODES", "DEFAULT_GDB_PREFIX", "DEFAULT_GDB_DATE",
    "GDB_LAYER_REGISTRY", "INTERNAL_LAYER_TO_GDB_KEYS", "GDB_DTYPE_TO_PYTHON",
    "GdbFieldSpec", "LayerDef",
    "make_gdb_layer_name", "get_gdb_layer_names", "get_gdb_fields",
    "get_internal_layer_for_gdb_key", "get_gdb_keys_for_internal_layer",
    "get_gdb_layers_by_category", "enrich_gdb_fields",
    # SSE events
    "GISAnalysisData", "GISLayerConfig", "GISMapOptions",
    "GisResultEvent", "GisLayerUpdateEvent",
]
