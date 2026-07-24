"""Jin Tian village GeoJSON loader - maps files to pipeline gis_data dict.

Loads data/gis/jintian/current/ and planned/ directories into the gis_data
dictionary structure expected by the GIS layout pipeline.

NOTE: LLM/intent parsing functions (resolve_gen_intent, resolve_plan_intent,
parse_text_via_llm, compute_intent_from_gis, get_village_params, etc.) were
migrated to app/tools/gis/parse.py in Phase 5. L3 report loading was
migrated to app/modules/data/documents/loader.py. This module now retains
only the GeoJSON file -> gis_data dict loading.

File -> gis_data key mapping:
  current/boundary.geojson       -> boundary_geojson
  current/landuse.geojson        -> landuse_current_geojson
  current/road.geojson           -> road_geojson
  current/admin_boundary_line.geojson -> admin_boundary_line_geojson
  current/annotation.geojson     -> annotation_geojson
  planned/farmland_protection.geojson    -> farmland_protection_geojson
  planned/ecological_protection.geojson  -> ecological_protection_geojson
  planned/historical_protection.geojson  -> historical_protection_geojson
  planned/construction_zone.geojson      -> construction_zone_geojson
  planned/geological_hazard_points.geojson -> geological_hazard_geojson
  planned/landuse.geojson        -> landuse_planned_geojson
  planned/road.geojson           -> road_planned_geojson
  planned/annotation.geojson     -> annotation_planned_geojson
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from app.core.settings import JINTIAN_GIS_DIR
from app.utils.logger import get_logger

logger = get_logger(__name__)

CURRENT_DIR = JINTIAN_GIS_DIR / "current"
PLANNED_DIR = JINTIAN_GIS_DIR / "planned"

# current/ file -> gis_data key
_CURRENT_FILE_MAP = {
    "boundary.geojson": "boundary_geojson",
    "landuse.geojson": "landuse_current_geojson",
    "road.geojson": "road_geojson",
    "admin_boundary_line.geojson": "admin_boundary_line_geojson",
    "annotation.geojson": "annotation_geojson",
}

# planned/ file -> gis_data key
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
    """Load all current status layers from data/gis/jintian/current/."""
    result: Dict[str, Any] = {}
    for filename, key in _CURRENT_FILE_MAP.items():
        result[key] = _load_geojson(CURRENT_DIR / filename)
    return result


def load_planned() -> Dict[str, Any]:
    """Load all planned (ground truth) layers from data/gis/jintian/planned/."""
    result: Dict[str, Any] = {}
    for filename, key in _PLANNED_FILE_MAP.items():
        result[key] = _load_geojson(PLANNED_DIR / filename)
    return result


def load_all() -> Dict[str, Any]:
    """Load both current and planned data into a single gis_data dict.

    This is the primary entry point for pipeline testing - returns a dict
    matching the gis_data structure expected by generate_layout and export_gdb.
    """
    data = load_current()
    data.update(load_planned())
    return data


__all__ = [
    "load_current",
    "load_planned",
    "load_all",
]
