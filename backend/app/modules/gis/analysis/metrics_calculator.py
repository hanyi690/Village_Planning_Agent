"""Computed summary metrics from GeoJSON landuse data.

All metrics are derived from actual GIS data to eliminate hardcoded values.
No LLM required — pure data computation.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Set

from app.utils.logger import get_logger
from ..zone_schema.encodings import DLBM_TO_ZONE_TYPE, get_zone_type_for_dlbm
from ..zone_schema.code_sets import (
    BASIC_FARMLAND_CODES,
    GENERAL_AGRICULTURE_CODES,
    ECOLOGICAL_CODES,
    FOREST_CODES,
    WATER_CODES,
)

logger = get_logger(__name__)

# Construction DLBM codes (all zone types that are construction)
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

    DLMJ is in m², area_ha is already in hectares.
    """
    if "area_ha" in props and isinstance(props["area_ha"], (int, float)):
        return float(props["area_ha"])
    if "DLMJ" in props and isinstance(props["DLMJ"], (int, float)):
        return float(props["DLMJ"]) / 10000.0
    if "MJ" in props and isinstance(props["MJ"], (int, float)):
        return float(props["MJ"]) / 10000.0
    return 0.0


class GISMetricsCalculator:
    """Compute summary statistics from GeoJSON landuse layers."""

    @classmethod
    def compute_land_use_metrics(cls, gis_data: Dict[str, Any]) -> Dict[str, Any]:
        """Compute comprehensive land use metrics from GIS data.

        Args:
            gis_data: Dict from data_loader.load_all() or load_current()

        Returns:
            Dict with computed metrics from real data (no hardcoded values)
        """
        landuse = gis_data.get("landuse_current_geojson", {})
        if not landuse or not landuse.get("features"):
            return cls._empty_metrics()

        # Aggregate areas by zone type
        zone_areas: Dict[str, float] = Counter()
        total_area_ha = 0.0
        dlbm_counts: Dict[str, int] = Counter()

        for feat in landuse["features"]:
            props = feat.get("properties", {})
            dlbm = str(props.get("DLBM", props.get("QMDLBM", ""))).strip()
            area = _area_ha_from_props(props)
            total_area_ha += area
            if dlbm:
                dlbm_counts[dlbm] += 1
                zone_type = get_zone_type_for_dlbm(dlbm)
                zone_areas[zone_type] += area

        # Compute category areas
        construction_area_ha = sum(
            area for dlbm, area in _dlbm_areas(landuse).items()
            if dlbm in CONSTRUCTION_DLBM_CODES
        )
        farmland_area_ha = sum(
            area for dlbm, area in _dlbm_areas(landuse).items()
            if dlbm in (BASIC_FARMLAND_CODES | GENERAL_AGRICULTURE_CODES)
        )
        ecological_area_ha = sum(
            area for dlbm, area in _dlbm_areas(landuse).items()
            if dlbm in ECOLOGICAL_CODES
        )
        forest_area_ha = sum(
            area for dlbm, area in _dlbm_areas(landuse).items()
            if dlbm in FOREST_CODES
        )
        water_area_ha = sum(
            area for dlbm, area in _dlbm_areas(landuse).items()
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

    @classmethod
    def compute_summaries(cls, gis_data: Dict[str, Any]) -> Dict[str, Any]:
        """Compute summaries in the format expected by ConflictDetector etc.

        Returns:
            {"land_use": {...}, "population": {...}, "natural_environment": {...}}
        """
        metrics = cls.compute_land_use_metrics(gis_data)

        # Try to extract population from L3 reports
        population = cls._extract_population(gis_data)

        return {
            "land_use": {
                "construction_area_ha": metrics["construction_area_ha"],
                "farmland_area_ha": metrics["farmland_area_ha"],
                "ecological_area_ha": metrics["ecological_area_ha"],
            },
            "population": population,
            "natural_environment": {
                "forest_coverage": metrics["forest_coverage"],
            },
        }

    @classmethod
    def compute_zone_distribution(cls, gis_data: Dict[str, Any]) -> Dict[str, float]:
        """Compute area_ratio for each zone type from landuse data.

        Returns:
            {zone_type: area_ratio} where ratios sum to ~1.0
        """
        metrics = cls.compute_land_use_metrics(gis_data)
        zone_areas = metrics.get("zone_areas", {})
        total = metrics.get("total_area_ha", 0)
        if total <= 0:
            return {}

        distribution = {}
        for zone_type, area in zone_areas.items():
            if area > 0:
                distribution[zone_type] = round(area / total, 4)

        # Normalize to sum to 1.0
        total_ratio = sum(distribution.values())
        if total_ratio > 0 and abs(total_ratio - 1.0) > 0.001:
            for k in distribution:
                distribution[k] = round(distribution[k] / total_ratio, 4)

        return distribution

    @staticmethod
    def _extract_population(gis_data: Dict[str, Any]) -> Dict[str, Any]:
        """Try to extract population from L3 reports."""
        try:
            from app.modules.gis.data.loader import load_l3_reports
            reports = load_l3_reports()
            for dim_key, dim_data in reports.items():
                if not isinstance(dim_data, dict):
                    continue
                summary = dim_data.get("summary", {})
                metrics = summary.get("metrics", {})
                pop = metrics.get("population")
                if pop and isinstance(pop, (int, float)):
                    return {"total": int(pop)}
        except Exception:
            pass
        return {}

    @staticmethod
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


def _dlbm_areas(geojson: Dict[str, Any]) -> Dict[str, float]:
    """Aggregate area by DLBM code from a FeatureCollection."""
    result: Dict[str, float] = Counter()
    for feat in geojson.get("features", []):
        props = feat.get("properties", {})
        dlbm = str(props.get("DLBM", props.get("QMDLBM", ""))).strip()
        if dlbm:
            result[dlbm] += _area_ha_from_props(props)
    return dict(result)
