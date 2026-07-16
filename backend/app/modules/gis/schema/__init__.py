"""GIS schema — unified data definitions, encodings, and output specifications.

Combines former models/, zone_schema/, and data/gdb_schema.py into one package:
  - canonical.py        — BBox, CRS, GeoFeature, LandUseParcel, GISDataBundle, GISMetadata
  - intent.py           — ZoneIntent, FacilityIntent, AxisIntent, UnifiedSpatialIntent
  - pipeline.py         — ConflictItem, ConflictReport, ValidationReport, ExportResult
  - output_profile.py   — OutputProfile, LayerSpec, FieldSpec
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

# ── Dictionary Center (single source of truth) ──
from .dicts import get_center, CodeDictionary, ProposalTable, DictionaryCenter
from .dicts.candidate_engine import (
    ClassificationProposal,
    CandidateEngine,
    get_candidate_engine,
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


# ============================================================
# Encoding & code-set symbols — derived from DictionaryCenter
# ============================================================

_dlbm = get_center().get("dlbm")
_ghytbm = get_center().get("ghytbm")
_ghflbm = get_center().get("ghflbm")
_ydyhfldm = get_center().get("ydyhfldm")
_vne = get_center().get("vne")
_tl = get_center().get("three_line_types")
_ec = get_center().get("element_codes")
_sddlbm = get_center().get_proposal("sddlbm_to_ydyhfldm")

# ── DLBM code sets ──
BASIC_FARMLAND_CODES: Set[str] = _dlbm.to_set("code", filter_tag="BASIC_FARMLAND")
GENERAL_AGRICULTURE_CODES: Set[str] = _dlbm.to_set("code", filter_tag="GENERAL_AGRICULTURE")
ECOLOGICAL_CODES: Set[str] = _dlbm.to_set("code", filter_tag="ECOLOGICAL")
FOREST_CODES: Set[str] = _dlbm.to_set("code", filter_tag="FOREST")
GRASSLAND_CODES: Set[str] = _dlbm.to_set("code", filter_tag="GRASSLAND")
FORESTRY_CODES: Set[str] = _dlbm.to_set("code", filter_tag="FORESTRY")
WATER_CODES: Set[str] = _dlbm.to_set("code", filter_tag="WATER")

ECOLOGICAL_PROTECTION_CODES: Set[str] = FOREST_CODES | WATER_CODES
ECOLOGICAL_CONTROL_CODES: Set[str] = GRASSLAND_CODES
PROTECTED_DLBM_CODES: Set[str] = BASIC_FARMLAND_CODES | GENERAL_AGRICULTURE_CODES | ECOLOGICAL_CODES

CONSTRUCTION_USE_TYPES: Set[str] = {"居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"}
CONSTRUCTION_ZONE_TYPES = CONSTRUCTION_USE_TYPES

# ── DLBM → DLMC → Zone type mappings ──
DLBM_TO_DLMC: Dict[str, str] = _dlbm.to_dict("code", "name")
DLBM_TO_ZONE_TYPE: Dict[str, str] = _dlbm.to_dict("code", "zone_type")
DLBM_TO_PLANNING_ZONE: Dict[str, str] = _dlbm.to_dict("code", "planning_zone")
DLBM_TO_PRIMARY_ZONE: Dict[str, str] = _dlbm.to_dict("code", "primary_zone")

ZONE_TYPE_TO_DLBMS: Dict[str, List[str]] = {}
for _code, _zt in DLBM_TO_ZONE_TYPE.items():
    ZONE_TYPE_TO_DLBMS.setdefault(_zt, []).append(_code)

# ── Zone hierarchy ──
ZONE_TYPES: List[str] = sorted(set(DLBM_TO_ZONE_TYPE.values()))
PLANNING_ZONES: List[str] = sorted(set(DLBM_TO_PLANNING_ZONE.values()))
PRIMARY_ZONES: List[str] = ["生态空间", "农业空间", "建设空间"]

PLANNING_ZONE_NAMES: List[str] = [
    "生态保护区", "生态控制区", "农田保护区",
    "一般农业区", "村庄建设区", "林业发展区",
]
PRIMARY_ZONE_NAMES: List[str] = ["生态空间", "农业空间", "建设空间"]

PLANNING_ZONE_TO_PRIMARY_ZONE: Dict[str, str] = {
    "生态保护区": "生态空间",
    "生态控制区": "生态空间",
    "农田保护区": "农业空间",
    "一般农业区": "农业空间",
    "村庄建设区": "建设空间",
    "林业发展区": "农业空间",
}

# ── GHYTMC planning use names ──
GHYTMC_TO_ZONE_TYPE: Dict[str, str] = _ghytbm.to_dict("name", "zone_type")
GHYTMC_TO_DLMC: Dict[str, str] = _ghytbm.to_dict("name", "name")

# ── GHFLBM / GHYTBM planning classification codes ──
GHFLBM_MEANING: Dict[str, str] = _ghflbm.to_dict("code", "name")
GHFLBM_TO_ZONE_TYPE: Dict[str, str] = _ghflbm.to_dict("code", "zone_type")

GHFLBM_TO_GHYTBMS: Dict[str, List[str]] = {}
for _entry in _ghflbm.raw.get("classes", []):
    _ghflbm_code = _entry.get("code", "")
    _ghytbms = _entry.get("ghytbms", [])
    if _ghflbm_code and _ghytbms:
        GHFLBM_TO_GHYTBMS[_ghflbm_code] = _ghytbms

GHYTBM_TO_GHYTMC: Dict[str, str] = _ghytbm.to_dict("code", "name")
GHYTBM_TO_YDYHFLDM: Dict[str, str] = _ghytbm.to_dict("code", "ydyhfldm")
GHYTBM_TO_ZONE_TYPE: Dict[str, str] = _ghytbm.to_dict("code", "zone_type")

YDYHFLDM_TO_NAME: Dict[str, str] = _ydyhfldm.to_dict("code", "name")

# ── V/N/E village planning land classification ──
VNE_CODE_TO_NAME: Dict[str, str] = _vne.to_dict("code", "name")
VNE_TO_ZONE_TYPE: Dict[str, str] = _vne.to_dict("code", "zone_type")

ZONE_TYPE_TO_VNE: Dict[str, str] = {}
for _entry in _vne.raw.get("classes", []):
    _zt = _entry.get("zone_type", "")
    _code = _entry.get("code", "")
    if _zt and _code and _zt not in ZONE_TYPE_TO_VNE:
        ZONE_TYPE_TO_VNE[_zt] = _code

GHYTBM_TO_VNE: Dict[str, str] = _ghytbm.to_dict("code", "vne")

# ── Three-line control layer definitions ──
THREE_LINE_TYPES: Dict[str, Dict[str, str]] = {}
for layer in _tl.raw.get("layers", []):
    key = layer.pop("key", "")
    if key:
        THREE_LINE_TYPES[key] = layer

_cz = _tl.raw.get("construction_zone", {})
CONSTRUCTION_ZONE_DEF: Dict[str, str] = _cz if isinstance(_cz, dict) else {}

ANNOTATION_CATEGORIES: Dict[str, str] = {
    item["key"]: item["value"]
    for item in _tl.raw.get("annotation_categories", [])
}

# ── SDDLBM → YDYHFLDM base conversion ──
SDDLBM_TO_YDYHFLDM: Dict[str, Tuple[str, str]] = _sddlbm.to_dict()

# ── Element classification codes ──
ELEMENT_CODE_PREFIXES: Dict[str, str] = _ec.raw.get("prefixes", {})


# ── Lookup functions ──

def is_basic_farmland(dlbm: str) -> bool:
    return str(dlbm).strip() in BASIC_FARMLAND_CODES

def is_general_agriculture(dlbm: str) -> bool:
    return str(dlbm).strip() in GENERAL_AGRICULTURE_CODES

def get_zone_type_for_dlbm(dlbm: str) -> str:
    return DLBM_TO_ZONE_TYPE.get(dlbm, "农业用地")

def get_dlbms_for_zone_type(zone_type: str) -> List[str]:
    return ZONE_TYPE_TO_DLBMS.get(zone_type, [])

def get_zone_type_for_planned_dlbm(dlbm: str) -> str:
    return get_zone_type_for_dlbm(dlbm)

def get_zone_type_for_ghytmc(ghytmc: str) -> str:
    return GHYTMC_TO_ZONE_TYPE.get(str(ghytmc).strip(), "农业用地")

def get_primary_zone(dlbm: str) -> str:
    return DLBM_TO_PRIMARY_ZONE.get(str(dlbm).strip(), "农业空间")

def dlbm_to_planning_zone(dlbm: str) -> str:
    return DLBM_TO_PLANNING_ZONE.get(str(dlbm).strip(), "一般农业区")

def get_primary_zone_for_planning_zone(planning_zone: str) -> str:
    return PLANNING_ZONE_TO_PRIMARY_ZONE.get(planning_zone, "农业空间")

def get_zone_type_for_ghflbm(ghflbm: str) -> str:
    return GHFLBM_TO_ZONE_TYPE.get(str(ghflbm).strip(), "农业用地")

def get_zone_type_for_ghytbm(ghytbm: str) -> str:
    return GHYTBM_TO_ZONE_TYPE.get(str(ghytbm).strip(), "农业用地")

def get_ghytmc_for_ghytbm(ghytbm: str) -> str:
    return GHYTBM_TO_GHYTMC.get(str(ghytbm).strip(), "")

def get_zone_type_for_vne(vne_code: str) -> str:
    return VNE_TO_ZONE_TYPE.get(str(vne_code).strip(), "农业用地")

def get_vne_for_zone_type(zone_type: str) -> str:
    return ZONE_TYPE_TO_VNE.get(zone_type, "E9")

def convert_sddlbm_to_ydyhfldm(sddlbm: str) -> Tuple[str, str]:
    result = SDDLBM_TO_YDYHFLDM.get(str(sddlbm).strip())
    if result:
        return result
    return (sddlbm, "无对应")

def get_vne_for_ghytbm(ghytbm: str) -> str:
    return GHYTBM_TO_VNE.get(str(ghytbm).strip(), "E9")

def parse_element_code(code: str) -> Dict[str, str]:
    code = str(code).strip()
    if len(code) < 10:
        return {"code": code, "category": "unknown", "major_class": code[:2] if len(code) >= 2 else ""}
    major = code[:2]
    category = "base_geographic" if major == "10" else "spatial_planning" if major == "20" else "other"
    result = {"code": code, "category": category, "major_class": major}
    if category == "spatial_planning" and len(code) >= 4:
        result["sub_class"] = code[2]
        result["minor_class"] = code[3]
        if code[3] == "6":
            result["planning_level"] = "village"
            if len(code) >= 5:
                first_level = code[4]
                level_map = {"1": "全域总体规划", "2": "专项规划", "3": "详细规划"}
                result["first_level"] = level_map.get(first_level, first_level)
    return result


# ── Classification schema (from dicts) ──
_CLASSES = _dlbm.to_land_use_classes()

from .classification import ClassificationSchema
SCHEMA = ClassificationSchema()


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
    # Dictionary Center
    "get_center", "CodeDictionary", "ProposalTable", "DictionaryCenter",
    "ClassificationProposal", "CandidateEngine", "get_candidate_engine",
    # Classification
    "LandUseClass", "ClassificationSchema", "SCHEMA",
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
