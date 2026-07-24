"""export_gdb tool — export standard 12-layer GeoJSON package + land balance table.

Target output matches 金田村 GDB structure (5 current + 7 planned layers).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger

logger = get_logger(__name__)


from app.tools.helpers import make_result, to_tool_message


def _normalize_fields(geojson: Dict, layer_key: str) -> Dict:
    """Ensure exported GeoJSON has fields matching GDB_LAYER_REGISTRY."""
    from app.modules.schema.output.gdb import GDB_LAYER_REGISTRY

    layer_def = GDB_LAYER_REGISTRY.get(layer_key, {})
    field_specs = layer_def.get("fields", [])
    if not field_specs:
        return geojson

    field_names = [f[0] for f in field_specs]
    for feature in geojson.get("features", []):
        props = feature.setdefault("properties", {})
        for name in field_names:
            if name not in props:
                props[name] = None
    return geojson


@tool
def export_gdb(
    layout_configs: Annotated[Optional[List[Dict[str, Any]]], InjectedState("layout_configs")],
    allocated_geojson: Annotated[Optional[Dict[str, Any]], InjectedState("allocated_geojson")],
    gis_data: Annotated[Dict[str, Optional[Dict[str, Any]]], InjectedState("gis_data")],
    village_name: Annotated[str, InjectedState("village_name")],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
    output_dir: Optional[str] = None,
) -> Command:
    """Export complete 12-layer GeoJSON package matching GDB standard.

    Layers:
      current/ — boundary, landuse, road, annotation
      planned/ — landuse, farmland_protection, ecological_protection,
                  construction_zone, (+ optional layers)
      tables/ — land_balance.json
    """
    if not output_dir:
        base = Path(__file__).resolve().parents[6] / "output" / village_name
        output_dir = str(base)

    os.makedirs(output_dir, exist_ok=True)

    from app.modules.schema.output.gdb import GDB_LAYER_REGISTRY

    LAYER_GIS_KEY_MAP: Dict[str, Optional[str]] = {
        "admin_area": "boundary_geojson",
        "admin_boundary_line": None,
        "current_landuse": "landuse_current_geojson",
        "current_road": "road_geojson",
        "current_annotation": None,
        "planned_landuse": None,
        "ecological_redline": "ecological_protection_geojson",
        "farmland_protection": "farmland_protection_geojson",
        "historical_protection": "historical_protection_geojson",
        "construction_zone": "construction_zone_geojson",
        "space_control_zone": None,  # 生成层: SpaceControlZoneGenerator
        "land_use_zone": None,       # 生成层: LandUseZoneGenerator
        "hazard_points": "hazard_points_geojson",
        "planned_annotation": None,
        "planned_road": None,
    }

    exported = []

    for layer_key, layer_def in GDB_LAYER_REGISTRY.items():
        source = layer_def.get("source", "")
        gis_key = LAYER_GIS_KEY_MAP.get(layer_key)

        # planned_landuse comes from allocated_geojson, not gis_data
        # space_control_zone and land_use_zone come from layout_configs
        if layer_key == "planned_landuse":
            geojson = allocated_geojson
        elif layer_key == "space_control_zone":
            geojson = _find_layer_in_configs(layout_configs, "space_control_zone")
        elif layer_key == "land_use_zone":
            geojson = _find_layer_in_configs(layout_configs, "land_use_zone")
        elif gis_key and gis_data:
            geojson = gis_data.get(gis_key)
        else:
            geojson = None

        if geojson:
            path = os.path.join(output_dir, source)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            geojson = _normalize_fields(geojson, layer_key)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(geojson, f, ensure_ascii=False)
            exported.append(source)

    # ── Land balance table ─────────────────────────────────────
    balance_geojson = allocated_geojson or gis_data.get("landuse_current_geojson") if gis_data else None
    if balance_geojson:
        balance = _compute_land_balance(balance_geojson)
        balance_path = os.path.join(output_dir, "tables/land_balance.json")
        os.makedirs(os.path.dirname(balance_path), exist_ok=True)
        with open(balance_path, "w", encoding="utf-8") as f:
            json.dump(balance, f, ensure_ascii=False, indent=2)
        exported.append("tables/land_balance.json")

    # ── Layout config ──────────────────────────────────────────
    if layout_configs:
        config_path = os.path.join(output_dir, "layout.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(layout_configs, f, ensure_ascii=False, indent=2)
        exported.append("layout.json")

    result = make_result(True, data={
        "output_dir": output_dir,
        "exported_files": exported,
        "file_count": len(exported),
    })

    return Command(update={
        "messages": [to_tool_message(result, tool_call_id)],
    })


def _find_layer_in_configs(
    layout_configs: Optional[List[Dict[str, Any]]],
    layer_type: str,
) -> Optional[Dict[str, Any]]:
    """Extract a generated layer's GeoJSON from layout_configs."""
    if not layout_configs:
        return None
    for cfg in layout_configs:
        if cfg.get("layerType") == layer_type:
            return cfg.get("data") or cfg.get("geojson")
    return None


def _compute_land_balance(geojson: Dict) -> Dict[str, Any]:
    """Compute land use balance table from allocated GeoJSON.

    Returns structured data matching standard 用地平衡表 format.
    Area units preserved from input (typically m² for DLMJ fields).
    """
    from collections import defaultdict
    from app.modules.schema import dlbm_to_planning_zone, get_zone_type_for_dlbm

    features = geojson.get("features", [])
    zone_areas: Dict[str, float] = defaultdict(float)
    func_areas: Dict[str, float] = defaultdict(float)
    total_area = 0.0

    for feat in features:
        props = feat.get("properties", {})
        dlbm = str(props.get("DLBM", ""))
        area = float(props.get("DLMJ", props.get("area", 0)))

        pz = props.get("assigned_zone", dlbm_to_planning_zone(dlbm))
        zt = props.get("zone_type", get_zone_type_for_dlbm(dlbm))

        zone_areas[pz] += area
        func_areas[zt] += area
        total_area += area

    # Convert to hectares if values are in m² (DLMJ is in m²)
    is_sqm = total_area > 10000
    factor = 10000 if is_sqm else 1

    return {
        "total_area_ha": round(total_area / factor, 2),
        "planning_zones": {k: round(v / factor, 2) for k, v in sorted(zone_areas.items())},
        "function_zones": {k: round(v / factor, 2) for k, v in sorted(func_areas.items())},
    }
