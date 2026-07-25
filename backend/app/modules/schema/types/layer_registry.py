"""Unified layer type registry -- single source of truth.

Adding a new layer type: add one register_layer_type() call here.
Both DataCatalog and ingest reference this registry, so no separate
mapping maintenance needed.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel


class LayerTypeEntry(BaseModel):
    """One layer type's complete metadata."""
    layer_type: str
    model_class_name: str = ""       # e.g. "CurrentLandUseParcel"
    ingest_port: Optional[str] = None  # "result_to_parcels" | "result_to_features" | None
    ingest_arg: str = ""             # arg for ingest port (also key in _FEATURE_TYPE_REGISTRY)
    default_gdb_path: str = ""       # e.g. "current/landuse.geojson"
    description: str = ""


LAYER_TYPE_REGISTRY: Dict[str, LayerTypeEntry] = {}


def register_layer_type(
    layer_type: str,
    *,
    model_class_name: str = "",
    ingest_port: Optional[str] = None,
    ingest_arg: str = "",
    default_gdb_path: str = "",
    description: str = "",
) -> None:
    LAYER_TYPE_REGISTRY[layer_type] = LayerTypeEntry(
        layer_type=layer_type,
        model_class_name=model_class_name,
        ingest_port=ingest_port,
        ingest_arg=ingest_arg,
        default_gdb_path=default_gdb_path,
        description=description,
    )


def get_layer_entry(layer_type: str) -> Optional[LayerTypeEntry]:
    return LAYER_TYPE_REGISTRY.get(layer_type)


def get_all_layer_types() -> List[str]:
    return list(LAYER_TYPE_REGISTRY.keys())


# ── Register all known layer types ──────────────────────────────────

# Untyped layers (boundary -- wrapped as GeoFeature list, no ingest port)
register_layer_type("boundary", default_gdb_path="current/boundary.geojson",
                    description="Village boundary polygon")

# Parcel layers (ingest via result_to_parcels)
register_layer_type("landuse_current", model_class_name="CurrentLandUseParcel",
                    ingest_port="result_to_parcels", ingest_arg="current_landuse",
                    default_gdb_path="current/landuse.geojson",
                    description="Current land use parcels")
register_layer_type("landuse_planned", model_class_name="PlannedLandUseParcel",
                    ingest_port="result_to_parcels", ingest_arg="planned_landuse",
                    default_gdb_path="planned/landuse.geojson",
                    description="Planned land use parcels")

# Feature layers (ingest via result_to_features)
register_layer_type("annotation", model_class_name="CurrentAnnotation",
                    ingest_port="result_to_features", ingest_arg="current_annotation",
                    default_gdb_path="current/annotation.geojson",
                    description="Current annotations")
register_layer_type("annotation_planned", model_class_name="PlannedAnnotation",
                    ingest_port="result_to_features", ingest_arg="planned_annotation",
                    default_gdb_path="planned/annotation.geojson",
                    description="Planned annotations")
register_layer_type("road", model_class_name="CurrentRoad",
                    ingest_port="result_to_features", ingest_arg="current_road",
                    default_gdb_path="current/road.geojson",
                    description="Current roads")
register_layer_type("road_planned", model_class_name="PlannedRoad",
                    ingest_port="result_to_features", ingest_arg="planned_road",
                    default_gdb_path="planned/road.geojson",
                    description="Planned roads")
register_layer_type("admin_area", model_class_name="AdminArea",
                    ingest_port="result_to_features", ingest_arg="admin_area",
                    default_gdb_path="current/boundary.geojson",
                    description="Administrative area")
register_layer_type("admin_boundary_line", model_class_name="AdminBoundaryLine",
                    ingest_port="result_to_features", ingest_arg="admin_boundary_line",
                    default_gdb_path="current/admin_boundary_line.geojson",
                    description="Admin boundary line")
register_layer_type("farmland_protection", model_class_name="FarmlandProtection",
                    ingest_port="result_to_features", ingest_arg="farmland_protection",
                    default_gdb_path="planned/farmland_protection.geojson",
                    description="Farmland protection zone")
register_layer_type("ecological_protection", model_class_name="EcologicalRedline",
                    ingest_port="result_to_features", ingest_arg="ecological_redline",
                    default_gdb_path="planned/ecological_protection.geojson",
                    description="Ecological redline")
register_layer_type("ecological_redline", model_class_name="EcologicalRedline",
                    ingest_port="result_to_features", ingest_arg="ecological_redline",
                    default_gdb_path="planned/ecological_protection.geojson",
                    description="Ecological redline (alias)")
register_layer_type("urban_dev_boundary", model_class_name="UrbanDevBoundary",
                    ingest_port="result_to_features", ingest_arg="urban_dev_boundary",
                    default_gdb_path="planned/urban_dev_boundary.geojson",
                    description="Urban development boundary")
register_layer_type("village_dev_boundary", model_class_name="VillageDevBoundary",
                    ingest_port="result_to_features", ingest_arg="village_dev_boundary",
                    default_gdb_path="planned/village_dev_boundary.geojson",
                    description="Village development boundary")
register_layer_type("cultivated_land_target", model_class_name="CultivatedLandTarget",
                    ingest_port="result_to_features", ingest_arg="cultivated_land_target",
                    default_gdb_path="planned/cultivated_land_target.geojson",
                    description="Cultivated land target")
register_layer_type("historical_protection", model_class_name="HistoricalProtection",
                    ingest_port="result_to_features", ingest_arg="historical_protection",
                    default_gdb_path="planned/historical_protection.geojson",
                    description="Historical protection zone")
register_layer_type("construction_zone", model_class_name="ConditionalConstructionZone",
                    ingest_port="result_to_features", ingest_arg="conditional_construction",
                    default_gdb_path="planned/construction_zone.geojson",
                    description="Conditional construction zone")
register_layer_type("geological_hazard_points", model_class_name="GeologicalHazardPoint",
                    ingest_port="result_to_features", ingest_arg="geological_hazard_pt",
                    default_gdb_path="planned/geological_hazard_points.geojson",
                    description="Geological hazard points")
register_layer_type("planning_scope", model_class_name="PlanningScope",
                    ingest_port="result_to_features", ingest_arg="planning_scope",
                    default_gdb_path="planned/boundary.geojson",
                    description="Planning scope boundary")
register_layer_type("land_use_zone", model_class_name="LandUseZone",
                    ingest_port="result_to_features", ingest_arg="land_use_zone",
                    default_gdb_path="planned/land_use_zone.geojson",
                    description="Land use zone")
register_layer_type("space_control_zone", model_class_name="ConstructionCtrlZone",
                    ingest_port="result_to_features", ingest_arg="construction_ctrl_zone",
                    default_gdb_path="planned/space_control_zone.geojson",
                    description="Space control zone")
register_layer_type("water", model_class_name="WaterFeature",
                    ingest_port="result_to_features", ingest_arg="water_feature",
                    default_gdb_path="current/terrain/water.geojson",
                    description="Water features")
register_layer_type("hazard_control_line", model_class_name="HazardControlLine",
                    ingest_port="result_to_features", ingest_arg="hazard_control_line",
                    default_gdb_path="planned/hazard_control_line.geojson",
                    description="Hazard control line")
register_layer_type("flood_control_line", model_class_name="FloodControlLine",
                    ingest_port="result_to_features", ingest_arg="flood_control_line",
                    default_gdb_path="planned/flood_control_line.geojson",
                    description="Flood control line")
register_layer_type("contour_line", model_class_name="ContourLine",
                    ingest_port="result_to_features", ingest_arg="contour_line",
                    default_gdb_path="current/terrain/contour.geojson",
                    description="Contour lines")
register_layer_type("elevation_point", model_class_name="ElevationPoint",
                    ingest_port="result_to_features", ingest_arg="elevation_point",
                    default_gdb_path="current/terrain/elevation_points.geojson",
                    description="Elevation points")
register_layer_type("current_building", model_class_name="CurrentBuilding",
                    ingest_port="result_to_features", ingest_arg="current_building",
                    default_gdb_path="current/building.geojson",
                    description="Current buildings")
register_layer_type("current_facility", model_class_name="CurrentFacility",
                    ingest_port="result_to_features", ingest_arg="current_facility",
                    default_gdb_path="current/facility.geojson",
                    description="Current facilities")
