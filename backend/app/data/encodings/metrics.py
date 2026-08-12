"""Land use metrics computation — pure aggregation from GIS data.

The delivery and validation layers use this pure function directly. It owns
land-use aggregation without importing the deleted GIS dev-tool pipeline.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Set

from .code_sets import (
    BASIC_FARMLAND_CODES,
    GENERAL_AGRICULTURE_CODES,
    ECOLOGICAL_CODES,
    FOREST_CODES,
    WATER_CODES,
)


# Construction codes in the source DLBM system only. These are analytical
# groupings and must never be used to create a planning classification.
CONSTRUCTION_DLBM_CODES: Set[str] = set()
for _zt, _dlbms in {
    "居住用地": ["0700", "0701", "0702", "2121", "2030"],
    "产业用地": ["0600", "0601", "0602", "0603", "0610", "0620", "2100", "2124"],
    "公共服务用地": ["0800", "0801", "0802", "0803", "0806", "0810", "0900", "2122", "2125"],
    "交通用地": ["1000", "1001", "1002", "1003", "1004", "1005", "1006", "1040", "2123", "2126", "2200"],
    "商业用地": ["0500"],
}.items():
    CONSTRUCTION_DLBM_CODES.update(_dlbms)


def _area_ha_from_props(props: Dict[str, Any]) -> float:
    """Extract area in hectares from feature properties.

    DLMJ is in m2, area_ha is already in hectares.
    """
    if "area_ha" in props and isinstance(props["area_ha"], (int, float)):
        return float(props["area_ha"])
    if "DLMJ" in props and isinstance(props["DLMJ"], (int, float)):
        return float(props["DLMJ"]) / 10000.0
    if "MJ" in props and isinstance(props["MJ"], (int, float)):
        return float(props["MJ"]) / 10000.0
    return 0.0


def _dlbm_areas(geojson: Dict[str, Any]) -> Dict[str, float]:
    """Aggregate area by DLBM code from a FeatureCollection."""
    result: Dict[str, float] = Counter()
    for feat in geojson.get("features", []):
        props = feat.get("properties", {})
        # QMDLBM (planned end-of-period code) takes priority over DLBM (current)
        dlbm = str(props.get("QMDLBM", props.get("DLBM", ""))).strip()
        if dlbm:
            result[dlbm] += _area_ha_from_props(props)
    return dict(result)


def _empty_metrics() -> Dict[str, Any]:
    return {
        "construction_area_ha": 0.0,
        "farmland_area_ha": 0.0,
        "ecological_area_ha": 0.0,
        "forest_coverage": 0.0,
        "water_area_ha": 0.0,
        "total_area_ha": 0.0,
        "zone_areas": {},
        "dlbm_counts": {},
    }


def compute_land_use_metrics(gis_data: Dict[str, Any]) -> Dict[str, Any]:
    """Compute land use metrics from GIS data — pure DLBM aggregation.

    This is the canonical pure aggregation used by KG and delivery checks.

    Computes area by zone_type from DLBM codes in landuse_current_geojson.
    When protection layer geometry is available in gis_data, the caller
    protection areas are supplied by their dedicated data-layer collections.

    Args:
        gis_data: Dict with 'landuse_current_geojson' key containing
                  a GeoJSON FeatureCollection of landuse parcels.

    Returns:
        Dict with construction_area_ha, farmland_area_ha, ecological_area_ha,
        forest_coverage, water_area_ha, total_area_ha, zone_areas, dlbm_counts.
    """
    landuse = gis_data.get("landuse_current_geojson", {})
    if not landuse or not landuse.get("features"):
        return _empty_metrics()

    # Aggregate areas by zone type
    zone_areas: Dict[str, float] = Counter()
    total_area_ha = 0.0
    dlbm_counts: Dict[str, int] = Counter()

    for feat in landuse["features"]:
        props = feat.get("properties", {})
        dlbm = str(props.get("QMDLBM", props.get("DLBM", ""))).strip()
        area = _area_ha_from_props(props)
        total_area_ha += area
        if dlbm:
            dlbm_counts[dlbm] += 1
            # Wave A.1: zone_type is not derived from DLBM in activity chain.
            # Use parcel's own zone_type attribute if provided, else '未分类'.
            zone_type = str(props.get("zone_type", "")).strip() or "未分类"
            zone_areas[zone_type] += area

    # Compute category areas
    dlbm_area_map = _dlbm_areas(landuse)
    construction_area_ha = sum(
        area for dlbm, area in dlbm_area_map.items()
        if dlbm in CONSTRUCTION_DLBM_CODES
    )
    farmland_area_ha = sum(
        area for dlbm, area in dlbm_area_map.items()
        if dlbm in (BASIC_FARMLAND_CODES | GENERAL_AGRICULTURE_CODES)
    )
    ecological_area_ha = sum(
        area for dlbm, area in dlbm_area_map.items()
        if dlbm in ECOLOGICAL_CODES
    )
    forest_area_ha = sum(
        area for dlbm, area in dlbm_area_map.items()
        if dlbm in FOREST_CODES
    )
    water_area_ha = sum(
        area for dlbm, area in dlbm_area_map.items()
        if dlbm in WATER_CODES
    )

    forest_coverage = (forest_area_ha / total_area_ha * 100) if total_area_ha > 0 else 0.0

    return {
        "construction_area_ha": round(construction_area_ha, 2),
        "farmland_area_ha": round(farmland_area_ha, 2),
        "ecological_area_ha": round(ecological_area_ha, 2),
        "forest_coverage": round(forest_coverage, 2),
        "water_area_ha": round(water_area_ha, 2),
        "total_area_ha": round(total_area_ha, 2),
        "zone_areas": {k: round(v, 2) for k, v in zone_areas.items()},
        "dlbm_counts": dict(dlbm_counts),
    }


__all__ = [
    "compute_land_use_metrics",
    "CONSTRUCTION_DLBM_CODES",
]
