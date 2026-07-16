"""GIS schema — unified data definitions, encodings, and output specifications.

Combines former models/, zone_schema/, and data/gdb_schema.py into one package:
  - canonical.py        — BBox, CRS, GeoFeature, LandUseParcel, GISDataBundle, GISMetadata
  - intent.py           — ZoneIntent, FacilityIntent, AxisIntent, UnifiedSpatialIntent
  - pipeline.py         — ConflictItem, ConflictReport, ValidationReport, ExportResult
  - output_profile.py   — OutputProfile, LayerSpec, FieldSpec
  - encoding_registry.py — EncodingRegistry, get_encoding_registry
  - classification.py   — LandUseClass, _CLASSES, ClassificationSchema, SCHEMA
  - encodings.py        — DLBM_TO_DLMC, DLBM_TO_ZONE_TYPE, lookup functions
  - code_sets.py        — BASIC_FARMLAND_CODES, THREE_LINE_TYPES, V/N/E mappings
  - colors.py           — ZONE_TYPE_COLORS, PLANNING_ZONE_COLORS, color lookup
  - dynamic_zoning.py   — DynamicZoningEngine
  - gdb.py              — GDB_LAYER_REGISTRY, enrich_gdb_fields
"""

# ── Canonical data models ──
from .canonical import (
    BBox,
    CRS,
    GeoFeature,
    LandUseParcel,
    GISDataBundle,
    GISMetadata,
)

# ── Intent models ──
from .intent import (
    Direction,
    Density,
    ZoneIntent,
    FacilityIntent,
    AxisIntent,
    ConstraintIntent,
    UnifiedSpatialIntent,
)

# ── Pipeline output models ──
from .pipeline import (
    ConflictItem,
    ConflictReport,
    ViolationItem,
    ValidationReport,
    AllocationResult,
    ExportResult,
)

# ── Encoding registry ──
from .encoding_registry import EncodingRegistry, get_encoding_registry

# ── Output profile ──
from .output_profile import OutputProfile, LayerSpec, FieldSpec, get_output_profile

# ── Classification (was zone_schema/schema.py) ──
from .classification import (
    LandUseClass,
    ClassificationSchema,
    SCHEMA,
    ZONE_TYPES,
    PLANNING_ZONES,
    PRIMARY_ZONES,
)

# ── Encodings ──
from .encodings import (
    DLBM_TO_DLMC,
    DLBM_TO_ZONE_TYPE,
    ZONE_TYPE_TO_DLBMS,
    get_zone_type_for_dlbm,
    get_dlbms_for_zone_type,
    get_zone_type_for_planned_dlbm,
    GHYTMC_TO_ZONE_TYPE,
    GHYTMC_TO_DLMC,
    get_zone_type_for_ghytmc,
    DLBM_TO_PLANNING_ZONE,
    DLBM_TO_PRIMARY_ZONE,
    dlbm_to_planning_zone,
    get_primary_zone,
    PLANNING_ZONE_NAMES,
    PRIMARY_ZONE_NAMES,
    PLANNING_ZONE_TO_PRIMARY_ZONE,
    get_primary_zone_for_planning_zone,
    GHFLBM_MEANING,
    GHFLBM_TO_ZONE_TYPE,
    GHFLBM_TO_GHYTBMS,
    get_zone_type_for_ghflbm,
    GHYTBM_TO_GHYTMC,
    GHYTBM_TO_YDYHFLDM,
    YDYHFLDM_TO_NAME,
    GHYTBM_TO_ZONE_TYPE,
    get_zone_type_for_ghytbm,
    get_ghytmc_for_ghytbm,
)

# ── Code sets ──
from .code_sets import (
    BASIC_FARMLAND_CODES,
    GENERAL_AGRICULTURE_CODES,
    ECOLOGICAL_CODES,
    FOREST_CODES,
    GRASSLAND_CODES,
    FORESTRY_CODES,
    WATER_CODES,
    ECOLOGICAL_PROTECTION_CODES,
    ECOLOGICAL_CONTROL_CODES,
    PROTECTED_DLBM_CODES,
    CONSTRUCTION_USE_TYPES,
    CONSTRUCTION_ZONE_TYPES,
    is_basic_farmland,
    is_general_agriculture,
    THREE_LINE_TYPES,
    CONSTRUCTION_ZONE_DEF,
    ANNOTATION_CATEGORIES,
    VNE_CODE_TO_NAME,
    VNE_TO_ZONE_TYPE,
    ZONE_TYPE_TO_VNE,
    get_zone_type_for_vne,
    get_vne_for_zone_type,
    SDDLBM_TO_YDYHFLDM,
    convert_sddlbm_to_ydyhfldm,
    GHYTBM_TO_VNE,
    get_vne_for_ghytbm,
    ELEMENT_CODE_PREFIXES,
    parse_element_code,
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

__all__ = [
    # Canonical
    "BBox", "CRS", "GeoFeature", "LandUseParcel", "GISDataBundle", "GISMetadata",
    # Intent
    "Direction", "Density",
    "ZoneIntent", "FacilityIntent", "AxisIntent", "ConstraintIntent",
    "UnifiedSpatialIntent",
    # Pipeline
    "ConflictItem", "ConflictReport", "ViolationItem", "ValidationReport",
    "AllocationResult", "ExportResult",
    # Encoding registry
    "EncodingRegistry", "get_encoding_registry",
    # Output profile
    "OutputProfile", "LayerSpec", "FieldSpec", "get_output_profile",
    # Classification
    "LandUseClass", "ClassificationSchema", "SCHEMA",
    "ZONE_TYPES", "PLANNING_ZONES", "PRIMARY_ZONES",
    # Encodings
    "DLBM_TO_DLMC", "DLBM_TO_ZONE_TYPE", "ZONE_TYPE_TO_DLBMS",
    "get_zone_type_for_dlbm", "get_dlbms_for_zone_type",
    "get_zone_type_for_planned_dlbm",
    "GHYTMC_TO_ZONE_TYPE", "GHYTMC_TO_DLMC", "get_zone_type_for_ghytmc",
    "DLBM_TO_PLANNING_ZONE", "DLBM_TO_PRIMARY_ZONE",
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
    "ECOLOGICAL_CODES", "FOREST_CODES", "GRASSLAND_CODES",
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
