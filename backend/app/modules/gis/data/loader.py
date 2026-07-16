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


def compute_intent_from_gis(
    gis_data: Dict[str, Any],
    village_name: str = "金田村委会",
) -> Dict[str, Any]:
    """Compute spatial intent from actual GIS data (no LLM, no hardcoded values).

    Last-resort fallback: derives zone ratios from real landuse distribution.
    The primary flow should be L3 reports or planning markdown parsing.

    Args:
        gis_data: Dict from load_all() with landuse_current_geojson
        village_name: Village name for metadata

    Returns:
        Dict with zones[], facilities[], axes[], constraints[] from real data
    """
    from ..analysis.metrics_calculator import GISMetricsCalculator
    from ..schema.encodings import get_zone_type_for_dlbm, ZONE_TYPE_TO_DLBMS

    metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data)
    distribution = GISMetricsCalculator.compute_zone_distribution(gis_data)

    # Build zones from computed distribution
    zones = []
    for zone_type, area_ratio in sorted(distribution.items(), key=lambda x: -x[1]):
        if area_ratio < 0.001:
            continue
        dlbms = ZONE_TYPE_TO_DLBMS.get(zone_type, [])
        primary_dlbm = dlbms[0] if dlbms else "0100"
        direction = "center" if zone_type in ("居住用地", "公共服务用地", "商业用地") else "periphery"
        zones.append({
            "zone_id": f"z_{zone_type[:2]}",
            "land_use": zone_type,
            "dlbm": primary_dlbm,
            "area_ratio": area_ratio,
            "direction": direction,
            "preserve_existing": True,
        })

    # Normalize ratios to sum to 1.0
    total_ratio = sum(z["area_ratio"] for z in zones)
    if total_ratio > 0 and abs(total_ratio - 1.0) > 0.001:
        for z in zones:
            z["area_ratio"] = round(z["area_ratio"] / total_ratio, 4)

    # Build constraints from computed metrics
    constraints = []
    if metrics["construction_area_ha"] > 0:
        constraints.append({
            "constraint_id": "c1",
            "type": "construction_cap",
            "value": metrics["construction_area_ha"],
            "unit": "公顷",
        })
    if metrics["farmland_area_ha"] > 0:
        constraints.append({
            "constraint_id": "c2",
            "type": "farmland_min",
            "value": metrics["farmland_area_ha"],
            "unit": "公顷",
        })
    if metrics["ecological_area_ha"] > 0:
        constraints.append({
            "constraint_id": "c3",
            "type": "ecological_redline",
            "value": metrics["ecological_area_ha"],
            "unit": "公顷",
        })

    return {
        "zones": zones,
        "facilities": [],
        "axes": [{"axis_id": "a1", "axis_type": "primary", "direction": "east-west", "label": "主要发展轴"}],
        "constraints": constraints,
        "metadata": {
            "village_name": village_name,
            "source": "gis_data_computed",
            "computed_from": "landuse_current_geojson",
        },
    }


def _build_gis_constraints_for_llm(gis_data: Optional[Dict[str, Any]]) -> str:
    """Build GIS-measured constraints string for LLM prompt injection."""
    if not gis_data:
        return ""
    from ..analysis.metrics_calculator import GISMetricsCalculator
    metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data)
    lines = [
        "## GIS 实测约束（必须遵守）",
        f"- 建设用地面积: {metrics['construction_area_ha']} 公顷（上限）",
        f"- 耕地保有量: {metrics['farmland_area_ha']} 公顷（下限）",
        f"- 生态保护红线: {metrics['ecological_area_ha']} 公顷（下限）",
        f"- 森林覆盖率: {metrics['forest_coverage']}%",
        f"- 水域面积: {metrics['water_area_ha']} 公顷",
        f"- 村域总面积: {metrics['total_area_ha']} 公顷",
        "",
        "以上约束来自 GIS 实测数据，area_ratio 必须与这些面积一致。",
    ]
    return "\n".join(lines)


def _parse_text_via_llm(
    text: str,
    village_name: str,
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Parse planning markdown text into intent via LLM (delegates to tool layer)."""
    from app.tools.gis.parse import parse_text_via_llm
    return parse_text_via_llm(text, village_name, gis_data)


def resolve_gen_intent(
    village_name: str = "金田村委会",
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Gen path: parse intent from planning markdown (with GIS constraint injection).

    Fallback: compute_intent_from_gis() if no markdown available.
    """
    try:
        from .planning_text_loader import PlanningTextLoader
        text = PlanningTextLoader.load_village_planning_markdown(village_name)
        intent = _parse_text_via_llm(text, village_name, gis_data)
        intent.setdefault("metadata", {})["source"] = "planning_markdown_llm"
        logger.info("[resolve_gen_intent] Parsed from planning markdown")
        return intent
    except FileNotFoundError:
        logger.warning("[resolve_gen_intent] No planning markdown found — cannot resolve gen intent")
    except Exception as e:
        logger.warning(f"[resolve_gen_intent] Markdown parsing failed: {e}")

    if gis_data:
        logger.warning("[resolve_gen_intent] DEGRADED: falling back to GIS data computation (no LLM)")
        intent = compute_intent_from_gis(gis_data, village_name)
        intent.setdefault("metadata", {})["source"] = "gis_data_fallback"
        intent["metadata"]["degraded"] = True
        intent["metadata"]["degraded_reason"] = "planning_markdown_not_found_or_llm_failed"
        return intent

    raise ValueError("No planning markdown found for gen intent")


def resolve_plan_intent(
    village_name: str = "金田村委会",
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Plan path: parse intent from L3 reports (with GIS constraint injection).

    Fallback: compute_intent_from_gis() if no reports available.
    """
    reports = load_l3_reports()
    if reports:
        try:
            from app.tools.gis.parse import _parse_reports_to_intent
            result = _parse_reports_to_intent(reports, village_name, gis_data)
            if result.get("success"):
                intent_json = result.get("data", {}).get("intent_json", {})
                if intent_json.get("zones"):
                    intent_json.setdefault("metadata", {})["source"] = "l3_reports_llm"
                    logger.info("[resolve_plan_intent] Parsed from L3 reports")
                    return intent_json
        except Exception as e:
            logger.warning(f"[resolve_plan_intent] L3 reports parsing failed: {e}")

    if gis_data:
        logger.warning("[resolve_plan_intent] DEGRADED: falling back to GIS data computation (no LLM)")
        intent = compute_intent_from_gis(gis_data, village_name)
        intent.setdefault("metadata", {})["source"] = "gis_data_fallback"
        intent["metadata"]["degraded"] = True
        intent["metadata"]["degraded_reason"] = "l3_reports_not_found_or_llm_failed"
        return intent

    raise ValueError("No L3 reports found for plan intent")


def get_village_params(gis_data: Dict[str, Any]) -> Dict[str, str]:
    """Compute village parameters from GIS data (replaces hardcoded strings).

    Returns:
        {"total_area": str, "land_use_description": str, "village_name": str}
    """
    from ..analysis.metrics_calculator import GISMetricsCalculator
    from ..schema.encodings import DLBM_TO_DLMC

    metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data)
    total_area = str(round(metrics["total_area_ha"], 2))

    # Derive land use description from top 3 zone types by area
    zone_areas = metrics.get("zone_areas", {})
    sorted_zones = sorted(zone_areas.items(), key=lambda x: -x[1])
    top_zones = [z for z, _ in sorted_zones[:3]]

    zone_names = {
        "农业用地": "农业用地", "生态绿地": "林地", "居住用地": "居民点",
        "水域": "水域", "交通用地": "交通", "产业用地": "产业",
        "公共服务用地": "公服", "商业用地": "商业",
    }
    descriptions = [zone_names.get(z, z) for z in top_zones]

    if descriptions:
        land_use_description = descriptions[0] + "为主，含" + "、".join(descriptions[1:])
    else:
        land_use_description = "未知"

    return {
        "total_area": total_area,
        "land_use_description": land_use_description,
        "village_name": "金田村委会",
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
