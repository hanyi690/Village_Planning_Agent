"""Computed summary metrics from GeoJSON landuse data.

All metrics are derived from actual GIS data to eliminate hardcoded values.
No LLM required — pure data computation.

Core computation (compute_land_use_metrics) extracted to
app.modules.schema.metrics for use by KG builder without
importing from the tools layer.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Set

from app.utils.logger import get_logger
from app.modules.schema.encodings.code_sets import get_zone_type_for_dlbm, DLBM_TO_ZONE_TYPE
from app.modules.schema import (
    BASIC_FARMLAND_CODES,
    GENERAL_AGRICULTURE_CODES,
    ECOLOGICAL_CODES,
    FOREST_CODES,
    WATER_CODES,
)
from app.modules.schema.utils.metrics import compute_land_use_metrics as _schema_compute

logger = get_logger(__name__)


class GISMetricsCalculator:
    """Compute summary statistics from GeoJSON landuse layers.

    Delegates core computation to schema.metrics.compute_land_use_metrics
    and adds optional geometry-based area overrides from protection layers.
    """

    @classmethod
    def compute_land_use_metrics(cls, gis_data: Dict[str, Any]) -> Dict[str, Any]:
        """Compute comprehensive land use metrics from GIS data.

        Uses schema.metrics for pure DLBM aggregation, then overrides
        with protection layer geometry areas when available.
        """
        metrics = _schema_compute(gis_data)

        # Override with protection layer geometry areas when available
        eco_layer_area = cls._layer_geometry_area_ha(gis_data, "ecological_protection_geojson")
        farm_layer_area = cls._layer_geometry_area_ha(gis_data, "farmland_protection_geojson")
        constr_layer_area = cls._layer_geometry_area_ha(gis_data, "construction_zone_geojson")

        if eco_layer_area > 0:
            metrics["ecological_area_ha"] = round(eco_layer_area, 2)
        if farm_layer_area > 0:
            metrics["farmland_area_ha"] = round(farm_layer_area, 2)
        if constr_layer_area > 0:
            metrics["construction_area_ha"] = round(constr_layer_area, 2)

        return metrics

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
            from app.modules.data.documents import load_l3_reports
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
    def _layer_geometry_area_ha(gis_data: Dict[str, Any], key: str) -> float:
        """Compute total area in hectares from a GIS layer's geometry.

        Uses calculate_area_ha for accurate metric-area computation.
        Returns 0.0 if the layer is missing or empty.
        """
        geojson = gis_data.get(key) if gis_data else None
        if not geojson or not geojson.get("features"):
            return 0.0
        try:
            from app.utils.geojson_utils import geojson_to_geodataframe
            from app.utils.area_engine import calculate_area_ha
            gdf = geojson_to_geodataframe(geojson)
            if gdf is None or gdf.empty:
                return 0.0
            return round(sum(calculate_area_ha(g) for g in gdf.geometry), 2)
        except Exception as e:
            logger.debug("[Metrics] Layer %s area computation failed: %s", key, e)
            return 0.0
