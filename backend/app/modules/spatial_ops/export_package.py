"""Export the standard GeoJSON planning package and land-balance table.

The output layout follows the configured GIS layer registry.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _safe_run_key(value: str) -> str:
    key = re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+", "_", value.strip())
    return key.strip("._") or "unnamed"


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


def export_gdb_package(
    layout_configs: Optional[List[Dict[str, Any]]],
    allocated_geojson: Optional[Dict[str, Any]],
    gis_data: Dict[str, Optional[Dict[str, Any]]],
    village_name: str,
    output_dir: Optional[str] = None,
    session_id: str = "",
    validation_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Export a complete GeoJSON package without LangChain tool wrapping.

    Layers:
      current/ — boundary, landuse, road, annotation
      planned/ — landuse, farmland_protection, ecological_protection,
                  construction_zone, (+ optional layers)
      tables/ — land_balance.json
    """
    if not output_dir:
        project_root = Path(__file__).resolve().parents[4]
        run_key = _safe_run_key(session_id or village_name)
        base = project_root / "output" / "gis" / run_key
        output_dir = str(base)

    os.makedirs(output_dir, exist_ok=True)

    from app.modules.schema.output.gdb import GDB_LAYER_REGISTRY

    LAYER_GIS_KEY_MAP: Dict[str, Optional[str]] = {
        "admin_area": "boundary_geojson",
        "admin_boundary_line": None,
        "current_landuse": "landuse_current_geojson",
        "current_road": "road_geojson",
        "current_annotation": "annotation_geojson",
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
    layout_candidates = {
        "planned_annotation": ("facility_point",),
        "planned_road": ("planned_road_candidates", "planned_road"),
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
        elif layer_key in layout_candidates:
            geojson = next(
                (
                    layer
                    for candidate in layout_candidates[layer_key]
                    if (layer := _find_layer_in_configs(layout_configs, candidate))
                ),
                None,
            )
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
    balance_geojson = allocated_geojson or (gis_data or {}).get(
        "landuse_current_geojson"
    )
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

    manifest = {
        "schema_version": "1.0",
        "session_id": session_id,
        "village_name": village_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "producer": "app.agent.gis.layout_pipeline",
        "validation": validation_result or {},
        "layout_layers": [
            {
                "layer_type": cfg.get("layerType") or cfg.get("layer_type") or "unknown",
                "feature_count": len(
                    (cfg.get("data") or {}).get("features", [])
                    or cfg.get("features", [])
                ),
            }
            for cfg in layout_configs or []
        ],
        "exported_files": list(exported),
    }
    manifest_path = os.path.join(output_dir, "run_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    exported.append("run_manifest.json")

    return {
        "status": "completed",
        "output_dir": output_dir,
        "exported_files": exported,
        "file_count": len(exported),
    }


def _find_layer_in_configs(
    layout_configs: Optional[List[Dict[str, Any]]],
    layer_type: str,
) -> Optional[Dict[str, Any]]:
    """Extract a generated layer's GeoJSON from layout_configs."""
    if not layout_configs:
        return None
    for cfg in layout_configs:
        if (cfg.get("layerType") or cfg.get("layer_type")) == layer_type:
            data = cfg.get("data") or cfg.get("geojson")
            if data:
                return data
            if cfg.get("features") is not None:
                return {"type": "FeatureCollection", "features": cfg["features"]}
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
