"""Unified GIS layer-type registry -- YAML + Python hybrid architecture.

Design (v4.2b):
  YAML (gis_layer_registry.yaml) = declarative metadata
    geometry_kind, is_reference_layer, description, group, encoding_system
  Python (this file) = type bindings + ingest routing
    model_class_name -> actual class, ingest_port -> actual function

Adding a new GIS layer type:
  1. Add entry to gis_layer_registry.yaml (declarative metadata)
  2. If it maps to an existing Schema class + ingest port:
     add a binding in _TYPE_BINDINGS below
  3. If no binding exists: registry entry is still created (for discovery)
     but ingest_port stays None (future inference pipeline)

Factory: build_registry_from_yaml() merges YAML metadata + Python bindings
into GIS_LAYER_REGISTRY. Call this at module import time.

Reference: backend/app/modules/schema/README.md §八
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel


class GisLayerTypeEntry(BaseModel):
    """One GIS layer type's complete metadata."""
    gis_type_ref: str
    model_class_name: str = ""       # e.g. "CurrentLandUseParcel"
    geometry_kind: str = ""          # "point"|"line"|"polygon"|"raster"|"table"|"document"|"annotation"
    ingest_port: Optional[str] = None  # "result_to_parcels" | "result_to_features" | None
    ingest_arg: str = ""             # arg for ingest port (also key in _FEATURE_TYPE_REGISTRY)
    default_gdb_path: str = ""       # e.g. "current/landuse.geojson"
    is_reference_layer: bool = False # 三区三线等引用层 (中央审批成果, 村庄级不重建)
    description: str = ""


GIS_LAYER_REGISTRY: Dict[str, GisLayerTypeEntry] = {}


def register_gis_layer_type(
    gis_type_ref: str,
    *,
    model_class_name: str = "",
    geometry_kind: str = "",
    ingest_port: Optional[str] = None,
    ingest_arg: str = "",
    default_gdb_path: str = "",
    is_reference_layer: bool = False,
    description: str = "",
) -> None:
    """Register a GIS layer type directly (backward-compatible, also used by factory)."""
    GIS_LAYER_REGISTRY[gis_type_ref] = GisLayerTypeEntry(
        gis_type_ref=gis_type_ref,
        model_class_name=model_class_name,
        geometry_kind=geometry_kind,
        ingest_port=ingest_port,
        ingest_arg=ingest_arg,
        default_gdb_path=default_gdb_path,
        is_reference_layer=is_reference_layer,
        description=description,
    )


def get_gis_layer_entry(gis_type_ref: str) -> Optional[GisLayerTypeEntry]:
    return GIS_LAYER_REGISTRY.get(gis_type_ref)


def get_all_gis_layer_types() -> List[str]:
    return list(GIS_LAYER_REGISTRY.keys())


# ── Python bindings: layer_type -> (model_class_name, ingest_port, ingest_arg) ──

_TYPE_BINDINGS: Dict[str, tuple] = {
    # Parcel layers
    "landuse_current":     ("CurrentLandUseParcel",     "result_to_parcels",  "current_landuse"),
    "landuse_planned":     ("PlannedLandUseParcel",     "result_to_parcels",  "planned_landuse"),
    # Annotation layers
    "annotation":          ("CurrentAnnotation",        "result_to_features", "current_annotation"),
    "annotation_planned":  ("PlannedAnnotation",        "result_to_features", "planned_annotation"),
    # Transport
    "road":                ("CurrentRoad",              "result_to_features", "current_road"),
    "road_planned":        ("PlannedRoad",              "result_to_features", "planned_road"),
    # Admin
    "admin_area":          ("AdminArea",                "result_to_features", "admin_area"),
    "admin_boundary_line": ("AdminBoundaryLine",        "result_to_features", "admin_boundary_line"),
    # Protection / reference
    "farmland_protection": ("FarmlandProtection",       "result_to_features", "farmland_protection"),
    "ecological_protection": ("EcologicalRedline",      "result_to_features", "ecological_redline"),
    "ecological_redline":  ("EcologicalRedline",        "result_to_features", "ecological_redline"),
    "urban_dev_boundary":  ("UrbanDevBoundary",         "result_to_features", "urban_dev_boundary"),
    "village_dev_boundary": ("VillageDevBoundary",      "result_to_features", "village_dev_boundary"),
    "cultivated_land_target": ("CultivatedLandTarget",  "result_to_features", "cultivated_land_target"),
    "historical_protection": ("HistoricalProtection",   "result_to_features", "historical_protection"),
    "construction_zone":   ("ConditionalConstructionZone", "result_to_features", "conditional_construction"),
    "geological_hazard_points": ("GeologicalHazardPoint", "result_to_features", "geological_hazard_pt"),
    "planning_scope":      ("PlanningScope",            "result_to_features", "planning_scope"),
    "land_use_zone":       ("LandUseZone",              "result_to_features", "land_use_zone"),
    "space_control_zone":  ("ConstructionCtrlZone",     "result_to_features", "construction_ctrl_zone"),
    # Water
    "water":               ("WaterFeature",             "result_to_features", "water_feature"),
    # Hazard
    "hazard_control_line": ("HazardControlLine",        "result_to_features", "hazard_control_line"),
    "flood_control_line":  ("FloodControlLine",         "result_to_features", "flood_control_line"),
    # Terrain
    "contour_line":        ("ContourLine",              "result_to_features", "contour_line"),
    "elevation_point":     ("ElevationPoint",           "result_to_features", "elevation_point"),
    # Facility
    "current_building":    ("CurrentBuilding",          "result_to_features", "current_building"),
    "current_facility":    ("CurrentFacility",          "result_to_features", "current_facility"),
    "facility_planned":    ("PlannedFacility",          "result_to_features", "planned_facility"),
    # Raster
    "dem":                 ("DEMInput",                 "result_to_raster",   "dem"),
    "dom":                 ("DOMInput",                 "result_to_raster",   "dom"),
    # Reference (no ingest port - no source configured yet)
    "three_zone":          ("ThreeZoneItem",            None,                 ""),
    # Group F (no ingest port)
    "soil_type":           ("SoilType",                 None,                 ""),
    "soil_erosion":        ("SoilErosion",              None,                 ""),
    "watershed":           ("Watershed",                None,                 ""),
    "nature_reserve":      ("NatureReserve",            None,                 ""),
    "hydrogeology_zone":   ("HydrogeologyZone",         None,                 ""),
    # Table (no ingest port)
    "population":          ("PopulationTable",          None,                 ""),
    "construction_projects": ("ConstructionProjectTable", None,               ""),
    "control_rules":       ("ControlRuleTable",         None,                 ""),
    "planning_indicators": ("PlanningIndicatorTable",   None,                 ""),
    "land_use_structure":  ("LandUseStructureTable",    None,                 ""),
}


def build_registry_from_yaml(yaml_path: Optional[str] = None) -> None:
    """Build GIS_LAYER_REGISTRY from YAML metadata + Python type bindings.

    Merges declarative metadata from gis_layer_registry.yaml with class/ingest
    bindings from _TYPE_BINDINGS. Entries in YAML that have no Python binding
    still get a registry entry (for discovery), but with empty ingest_port.

    Args:
        yaml_path: path to gis_layer_registry.yaml. Default: sibling of this file.
    """
    if yaml_path is None:
        yaml_path = str(Path(__file__).parent / "gis_layer_registry.yaml")

    # Load YAML metadata
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        try:
            # Fallback to old name for transition period
            yaml_path = str(Path(__file__).parent / "layer_registry.yaml")
            with open(yaml_path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            _build_from_bindings_only()
            return

    gis_layer_types = yaml_data.get("layer_types", {})
    if not gis_layer_types:
        _build_from_bindings_only()
        return

    for gis_type_ref, meta in gis_layer_types.items():
        binding = _TYPE_BINDINGS.get(gis_type_ref)
        model_class_name = binding[0] if binding else ""
        ingest_port = binding[1] if binding else None
        ingest_arg = binding[2] if binding else ""

        register_gis_layer_type(
            gis_type_ref,
            model_class_name=model_class_name,
            geometry_kind=meta.get("geometry_kind", ""),
            ingest_port=ingest_port,
            ingest_arg=ingest_arg,
            default_gdb_path=meta.get("default_gdb_path", ""),
            is_reference_layer=meta.get("is_reference_layer", False),
            description=meta.get("description", ""),
        )


def _build_from_bindings_only() -> None:
    """Fallback: build registry from _TYPE_BINDINGS + inline defaults only.

    Used when gis_layer_registry.yaml is not available.
    Geometry_kind and is_reference_layer are hardcoded here as they
    were in the original register_gis_layer_type() calls.
    """
    _FALLBACK_TYPES = {
        "boundary":               ("polygon", False),
        "landuse_current":        ("polygon", False),
        "landuse_planned":        ("polygon", False),
        "annotation":             ("annotation", False),
        "annotation_planned":     ("annotation", False),
        "road":                   ("line", False),
        "road_planned":           ("line", False),
        "admin_area":             ("polygon", False),
        "admin_boundary_line":    ("line", False),
        "farmland_protection":    ("polygon", True),
        "ecological_protection":  ("polygon", True),
        "ecological_redline":     ("polygon", True),
        "urban_dev_boundary":     ("polygon", True),
        "village_dev_boundary":   ("polygon", True),
        "cultivated_land_target": ("polygon", True),
        "historical_protection":  ("polygon", True),
        "construction_zone":      ("polygon", False),
        "geological_hazard_points": ("point", False),
        "planning_scope":         ("polygon", False),
        "land_use_zone":          ("polygon", False),
        "space_control_zone":     ("polygon", False),
        "water":                  ("polygon", False),
        "hazard_control_line":    ("polygon", False),
        "flood_control_line":     ("polygon", False),
        "contour_line":           ("line", False),
        "elevation_point":        ("point", False),
        "current_building":       ("point", False),
        "current_facility":       ("point", False),
        "facility_planned":       ("point", False),
        "dem":                    ("raster", False),
        "dom":                    ("raster", False),
        "three_zone":             ("polygon", True),
        "soil_type":              ("polygon", False),
        "soil_erosion":           ("polygon", False),
        "watershed":              ("polygon", False),
        "nature_reserve":         ("polygon", False),
        "hydrogeology_zone":      ("polygon", False),
        "population":             ("table", False),
        "construction_projects":  ("table", False),
        "control_rules":          ("table", False),
        "planning_indicators":    ("table", False),
        "land_use_structure":     ("table", False),
    }

    for lt, binding in _TYPE_BINDINGS.items():
        kind, ref = _FALLBACK_TYPES.get(lt, ("", False))
        register_gis_layer_type(
            lt,
            model_class_name=binding[0],
            geometry_kind=kind,
            ingest_port=binding[1],
            ingest_arg=binding[2],
            is_reference_layer=ref,
            description=lt,
        )

    # Register types not in _TYPE_BINDINGS
    for lt, (kind, ref) in _FALLBACK_TYPES.items():
        if lt not in {b[0] for b in _TYPE_BINDINGS.values() if False}:
            if lt not in GIS_LAYER_REGISTRY:
                register_gis_layer_type(lt, geometry_kind=kind, is_reference_layer=ref, description=lt)


# ── Initialize registry at import time ──

build_registry_from_yaml()


__all__ = [
    "GisLayerTypeEntry",
    "GIS_LAYER_REGISTRY",
    "register_gis_layer_type",
    "get_gis_layer_entry",
    "get_all_gis_layer_types",
    "build_registry_from_yaml",
]
