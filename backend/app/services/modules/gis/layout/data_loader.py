"""Jin Tian village real data loader — maps GeoJSON files to pipeline format.

Loads data/gis/jintian/current/ and planned/ directories into the gis_data
dictionary structure expected by the GIS layout pipeline.

File → gis_data key mapping:
  current/boundary.geojson       → boundary_geojson
  current/landuse.geojson        → landuse_current_geojson
  current/road.geojson           → road_geojson
  current/admin_boundary_line.geojson → admin_boundary_line_geojson
  current/annotation.geojson     → annotation_geojson
  planned/farmland_protection.geojson    → farmland_protection_geojson
  planned/ecological_protection.geojson  → ecological_protection_geojson
  planned/historical_protection.geojson  → historical_protection_geojson
  planned/construction_zone.geojson      → construction_zone_geojson
  planned/geological_hazard_points.geojson → geological_hazard_geojson
  planned/landuse.geojson        → landuse_planned_geojson
  planned/road.geojson           → road_planned_geojson
  planned/annotation.geojson     → annotation_planned_geojson
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.settings import JINTIAN_GIS_DIR, PROJECT_ROOT
from app.utils.logger import get_logger

logger = get_logger(__name__)

CURRENT_DIR = JINTIAN_GIS_DIR / "current"
PLANNED_DIR = JINTIAN_GIS_DIR / "planned"

# current/ file → gis_data key
_CURRENT_FILE_MAP = {
    "boundary.geojson": "boundary_geojson",
    "landuse.geojson": "landuse_current_geojson",
    "road.geojson": "road_geojson",
    "admin_boundary_line.geojson": "admin_boundary_line_geojson",
    "annotation.geojson": "annotation_geojson",
}

# planned/ file → gis_data key
_PLANNED_FILE_MAP = {
    "landuse.geojson": "landuse_planned_geojson",
    "road.geojson": "road_planned_geojson",
    "annotation.geojson": "annotation_planned_geojson",
    "farmland_protection.geojson": "farmland_protection_geojson",
    "ecological_protection.geojson": "ecological_protection_geojson",
    "historical_protection.geojson": "historical_protection_geojson",
    "construction_zone.geojson": "construction_zone_geojson",
    "geological_hazard_points.geojson": "geological_hazard_geojson",
}

# L3 reports path (used by PARSE agent and KG builder)
L3_REPORT_PATH = (
    PROJECT_ROOT / "output" / "experiments" / "rag" / "g1" / "iter0" / "layer3_reports.json"
)

# Baseline reports fallback
L3_BASELINE_PATH = PROJECT_ROOT / "output" / "experiments" / "baseline" / "baseline_reports.json"


def _load_geojson(path: Path) -> Dict[str, Any]:
    """Load a GeoJSON file, return empty FeatureCollection on failure."""
    if not path.exists():
        logger.warning(f"[DataLoader] File not found: {path}")
        return {"type": "FeatureCollection", "features": []}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    feat_count = len(data.get("features", []))
    logger.debug(f"[DataLoader] Loaded {path.name}: {feat_count} features")
    return data


def load_current() -> Dict[str, Any]:
    """Load all current status layers from data/gis/jintian/current/.

    Returns:
        Dict with keys: boundary_geojson, landuse_current_geojson,
        road_geojson, admin_boundary_line_geojson, annotation_geojson
    """
    result: Dict[str, Any] = {}
    for filename, key in _CURRENT_FILE_MAP.items():
        result[key] = _load_geojson(CURRENT_DIR / filename)
    return result


def load_planned() -> Dict[str, Any]:
    """Load all planned (ground truth) layers from data/gis/jintian/planned/.

    Returns:
        Dict with keys: landuse_planned_geojson, road_planned_geojson,
        farmland_protection_geojson, ecological_protection_geojson,
        historical_protection_geojson, construction_zone_geojson,
        geological_hazard_geojson, annotation_planned_geojson
    """
    result: Dict[str, Any] = {}
    for filename, key in _PLANNED_FILE_MAP.items():
        result[key] = _load_geojson(PLANNED_DIR / filename)
    return result


def load_all() -> Dict[str, Any]:
    """Load both current and planned data into a single gis_data dict.

    This is the primary entry point for pipeline testing — returns a dict
    matching the gis_data structure expected by generate_layout and export_gdb.
    """
    data = load_current()
    data.update(load_planned())
    return data


def load_l3_reports() -> Dict[str, Any]:
    """Load L3 reports from available paths.

    Tries RAG path first, then baseline fallback.

    Returns:
        {dim_key: {"summary": {"metrics": {...}}, "content": "..."}}
    """
    raw = _load_raw_reports()

    result: Dict[str, Any] = {}
    for dim_key, content in raw.items():
        if not isinstance(content, str):
            continue
        result[dim_key] = {
            "summary": {"metrics": _extract_metrics_regex(content)},
            "content": content,
        }
    return result


def _load_raw_reports() -> Dict[str, str]:
    """Load raw L3 report strings from JSON file."""
    for path in [L3_REPORT_PATH, L3_BASELINE_PATH]:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("reports", {})
    logger.warning("[DataLoader] No L3 reports found")
    return {}


def _extract_metrics_regex(content: str) -> Dict[str, Any]:
    """Extract numeric metrics from L3 report content via regex."""
    import re

    metrics: Dict[str, Any] = {}
    patterns = [
        (r"([\d.]+)\s*公顷", "area_ha"),
        (r"([\d.]+)\s*亩", "area_mu"),
        (r"(\d+)\s*人", "population"),
        (r"(\d+)\s*户", "households"),
        (r"([\d.]+)\s*%", "percentage"),
        (r"([\d.]+)\s*万元", "amount_wan_yuan"),
        (r"([\d.]+)\s*km", "length_km"),
        (r"([\d.]+)\s*m[²2]", "area_sqm"),
    ]
    for pat, key in patterns:
        m = re.search(pat, content)
        if m:
            val = m.group(1)
            metrics[key] = float(val) if "." in val else int(val)

    specific = [
        (r"建设用地.*?([\d.]+)\s*公顷", "建设用地规模_公顷"),
        (r"耕地.*?([\d.]+)\s*公顷", "耕地保有量_公顷"),
        (r"生态保护红线.*?([\d.]+)\s*公顷", "生态保护红线面积"),
        (r"永久基本农田.*?([\d.]+)\s*公顷", "永久基本农田_公顷"),
        (r"森林覆盖率.*?([\d.]+)\s*%", "森林覆盖率_百分比"),
        (r"林地.*?([\d.]+)\s*公顷", "林地保有量_公顷"),
    ]
    for pat, key in specific:
        m = re.search(pat, content)
        if m:
            metrics[key] = float(m.group(1))

    return metrics


def make_default_intent() -> Dict[str, Any]:
    """Build default planning intent for Jin Tian village (no LLM required).

    Zone ratios derived from actual landuse distribution:
      - 农业用地 (0100/0110/0200): ~80%
      - 居住用地 (2121/2122): ~1.3%
      - 生态绿地 (0300/0400): ~15%
      - 公共服务 (0800): ~3%
    """
    return {
        "zones": [
            {
                "zone_id": "z_farm",
                "land_use": "农业用地",
                "dlbm": "0200",
                "area_ratio": 0.80,
                "direction": "periphery",
                "preserve_existing": True,
            },
            {
                "zone_id": "z_eco",
                "land_use": "生态绿地",
                "dlbm": "0300",
                "area_ratio": 0.15,
                "direction": "periphery",
                "preserve_existing": True,
            },
            {
                "zone_id": "z_farm2",
                "land_use": "农业用地",
                "dlbm": "0110",
                "area_ratio": 0.03,
                "direction": "center",
                "preserve_existing": True,
            },
            {
                "zone_id": "z_build",
                "land_use": "居住用地",
                "dlbm": "2121",
                "area_ratio": 0.013,
                "direction": "center",
                "preserve_existing": True,
            },
        ],
        "facilities": [
            {"facility_id": "f1", "facility_type": "村委会", "status": "现状保留", "location_hint": "村庄中心", "direction": "center"},
            {"facility_id": "f2", "facility_type": "学校", "status": "现状保留", "location_hint": "居住区", "direction": "center"},
            {"facility_id": "f3", "facility_type": "卫生站", "status": "规划新建", "location_hint": "居住区南侧", "direction": "south"},
            {"facility_id": "f4", "facility_type": "文化站", "status": "规划新建", "location_hint": "村庄中心", "direction": "center"},
            {"facility_id": "f5", "facility_type": "养老服务", "status": "规划新建", "location_hint": "居住区", "direction": "center"},
            {"facility_id": "f6", "facility_type": "产业服务中心", "status": "规划新建", "location_hint": "村庄入口", "direction": "east"},
        ],
        "axes": [
            {"axis_id": "a1", "axis_type": "primary", "direction": "east-west", "label": "主要发展轴"},
            {"axis_id": "a2", "axis_type": "corridor", "direction": "north-south", "label": "生态廊道"},
        ],
        "constraints": [
            {"constraint_id": "c1", "type": "construction_cap", "value": 30.5, "unit": "公顷"},
            {"constraint_id": "c2", "type": "farmland_min", "value": 78.83, "unit": "公顷"},
            {"constraint_id": "c3", "type": "ecological_redline", "value": 0, "unit": "公顷"},
        ],
        "metadata": {
            "spatial_structure": "一核一带三区",
            "village_name": "金田村委会",
        },
    }


def get_data_summary(gis_data: Dict[str, Any]) -> Dict[str, Any]:
    """Compute summary statistics for loaded data.

    Returns feature counts and basic area info per layer.
    """
    summary: Dict[str, Any] = {}
    for key, geojson in gis_data.items():
        if not isinstance(geojson, dict) or "features" not in geojson:
            continue
        feats = geojson.get("features", [])
        feat_count = len(feats)
        geom_types: Dict[str, int] = {}
        for f in feats:
            gt = f.get("geometry", {}).get("type", "None")
            geom_types[gt] = geom_types.get(gt, 0) + 1
        summary[key] = {"feature_count": feat_count, "geometry_types": geom_types}
    return summary
