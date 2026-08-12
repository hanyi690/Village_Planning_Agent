"""Development axis builder — spatial structure generation.

Extracted from engine.py _build_spatial_structure_layer().

Generates:
  - Point: 一核 (village center) based on residential parcels centroid
  - LineString: 一带 (river corridor) along water parcels skeleton
  - Polygon: 三区 (3 function zones) using parcel partitioning

Also supports AxisIntent-driven generation from LLM intent.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple


def _valid_coord(x: float, y: float) -> bool:
    """Return True if both coordinates are finite numbers."""
    return not (math.isinf(x) or math.isnan(x) or math.isinf(y) or math.isnan(y))

from app.infrastructure.logging import get_logger
from .crs_engine import project_to_metric, project_to_wgs84, get_metric_crs
from .area_engine import calculate_area_ha
from .geo_utils import safe_geo_series_union

logger = get_logger(__name__)

# Building DLBM codes for village center detection
BUILDING_DLBM_CODES = {"2121", "2122", "2124", "2125"}

# Water DLBM codes for corridor detection
WATER_DLBM_CODES = {"3100", "1110", "1140"}

# Zone colors for 三区 rendering
ZONE_COLORS = {
    "生态保育屏障区": "#2E8B57",
    "生态农业发展区": "#DEB887",
    "宜居生活建设区": "#FF6347",
}


class AxisBuilder:
    """Build development axis / spatial structure GeoJSON layers."""

    def build(
        self,
        intent: Any,
        boundary_geojson: Optional[Dict[str, Any]] = None,
        landuse_current_geojson: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build spatial structure GeoJSON from intent and parcel data.

        If intent has explicit axes, use them. Otherwise, auto-generate
        一核一带三区 from landuse parcel geometry.

        Args:
            intent: UnifiedSpatialIntent (has .axes, .metadata)
            boundary_geojson: Village boundary
            landuse_current_geojson: Current land use parcels

        Returns:
            GeoJSON FeatureCollection or None
        """
        # Try explicit axes from intent first
        axes = getattr(intent, "axes", [])
        if axes:
            return self._build_from_axes(axes, landuse_current_geojson)

        # Auto-generate from metadata + parcels
        return self._build_auto(intent, landuse_current_geojson)

    def _build_from_axes(
        self,
        axes: List[Any],
        landuse_geojson: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Build axes from explicit AxisIntent objects."""
        if not landuse_geojson or not landuse_geojson.get("features"):
            return None

        try:
            import geopandas as gpd
            from shapely import from_geojson
        except ImportError:
            return None

        # Compute village center from parcels for reference
        geoms = []
        dlbms = []
        for ft in landuse_geojson["features"]:
            g = ft.get("geometry", {})
            props = ft.get("properties", {})
            if g and g.get("coordinates"):
                try:
                    geoms.append(from_geojson(json.dumps(g)))
                    dlbms.append(str(props.get("DLBM", "")).strip())
                except Exception:
                    continue

        if not geoms:
            return None

        gdf = gpd.GeoDataFrame({"DLBM": dlbms}, geometry=geoms, crs="EPSG:4326")
        gdf = project_to_metric(gdf)
        center = safe_geo_series_union(gdf.geometry).centroid
        metric_crs = get_metric_crs(center.x)
        center_4326 = project_to_wgs84(gpd.GeoSeries([center], crs=metric_crs))[0]

        features = []

        for axis in axes:
            if isinstance(axis, dict):
                axis_type = axis.get("axis_type", "primary")
                label = axis.get("label", "")
                direction = axis.get("direction", "center")
            else:
                axis_type = axis.axis_type
                label = axis.label
                direction = str(axis.direction.value if hasattr(axis.direction, "value") else axis.direction)

            if axis_type in ("primary", "secondary"):
                # Point feature (core/node)
                features.append({
                    "type": "Feature",
                    "properties": {
                        "axis_type": axis_type,
                        "name": label or f"发展节点",
                        "direction": direction,
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [center_4326.x, center_4326.y] if _valid_coord(center_4326.x, center_4326.y) else [0.0, 0.0],
                    },
                })
            elif axis_type in ("corridor", "connector"):
                # LineString along water parcels
                line = self._build_corridor_line(landuse_geojson, gdf, gpd)
                if line:
                    features.append({
                        "type": "Feature",
                        "properties": {
                            "axis_type": axis_type,
                            "name": label or "发展廊道",
                        },
                        "geometry": line,
                    })

        if not features:
            return None

        return {"type": "FeatureCollection", "features": features}

    def _build_auto(
        self,
        intent: Any,
        landuse_geojson: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Auto-generate 一核一带三区 spatial structure."""
        metadata = getattr(intent, "metadata", {}) or {}
        structure = metadata.get("spatial_structure", "")
        if not structure:
            return None

        if not landuse_geojson or not landuse_geojson.get("features"):
            return None

        try:
            import geopandas as gpd
            from shapely import from_geojson
            from shapely.geometry import LineString
        except ImportError:
            return None

        features = []

        # Load parcels as GeoDataFrame
        geoms = []
        props = []
        for ft in landuse_geojson["features"]:
            g = ft.get("geometry", {})
            if g and g.get("coordinates"):
                try:
                    geoms.append(from_geojson(json.dumps(g)))
                    props.append(ft.get("properties", {}))
                except Exception:
                    continue

        if not geoms:
            return None

        gdf = gpd.GeoDataFrame(props, geometry=geoms, crs="EPSG:4326")
        gdf = project_to_metric(gdf)
        metric_crs = get_metric_crs(safe_geo_series_union(gdf.geometry).centroid.x)
        gdf["cx"] = gdf.geometry.centroid.x
        gdf["cy"] = gdf.geometry.centroid.y

        # 一核: Village center
        build = gdf[gdf["DLBM"].apply(lambda x: str(x).strip() in BUILDING_DLBM_CODES)]
        if len(build) > 0:
            center = safe_geo_series_union(build.geometry).centroid
            center_4326 = project_to_wgs84(gpd.GeoSeries([center], crs=metric_crs))[0]
            features.append({
                "type": "Feature",
                "properties": {
                    "axis_type": "primary",
                    "name": "一核: 村级综合服务中心",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [center_4326.x, center_4326.y] if _valid_coord(center_4326.x, center_4326.y) else [0.0, 0.0],
                },
            })

        # 一带: River corridor
        water = gdf[gdf["DLBM"].apply(lambda x: str(x).strip() in WATER_DLBM_CODES)]
        if len(water) >= 3:
            water_ctrs = [g for g in water.geometry.centroid if not g.is_empty]
            if len(water_ctrs) >= 2:
                pts = sorted(water_ctrs, key=lambda p: (p.y, p.x))
                coords = [(p.x, p.y) for p in pts]
                step = max(1, len(coords) // 8)
                simplified = coords[::step]
                if simplified[-1] != coords[-1]:
                    simplified.append(coords[-1])
                line_3857 = LineString(simplified)
                line_4326 = project_to_wgs84(gpd.GeoSeries([line_3857], crs=metric_crs))[0]
                features.append({
                    "type": "Feature",
                    "properties": {
                        "axis_type": "corridor",
                        "name": "一带: 生态景观带",
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": list(line_4326.coords),
                    },
                })

        # 三区: Function zone partitioning
        cx_med, cy_med = gdf["cx"].median(), gdf["cy"].median()
        ne = gdf[(gdf["cx"] > cx_med) & (gdf["cy"] > cy_med)]
        sw = gdf[(gdf["cx"] <= cx_med) & (gdf["cy"] <= cy_med)]
        center_mask = (gdf["cx"] > gdf["cx"].quantile(0.25)) & \
                      (gdf["cx"] < gdf["cx"].quantile(0.75)) & \
                      (gdf["cy"] > gdf["cy"].quantile(0.25)) & \
                      (gdf["cy"] < gdf["cy"].quantile(0.75))
        center_parcels = gdf[center_mask & gdf["DLBM"].apply(
            lambda x: str(x).strip() in BUILDING_DLBM_CODES)]

        zone_defs = [
            ("生态保育屏障区", ne, "northeast"),
            ("生态农业发展区", sw, "southwest"),
            ("宜居生活建设区", center_parcels, "center"),
        ]

        for name, parcels, direction in zone_defs:
            if len(parcels) == 0:
                continue
            geom = safe_geo_series_union(parcels.geometry)
            if geom.is_empty:
                continue
            simplified = geom.simplify(50, preserve_topology=True)
            geom_4326 = project_to_wgs84(gpd.GeoSeries([simplified], crs=metric_crs))[0]
            area_ha = calculate_area_ha(safe_geo_series_union(parcels.geometry), metric_crs=metric_crs)
            features.append({
                "type": "Feature",
                "properties": {
                    "axis_type": "corridor",
                    "name": name,
                    "direction": direction,
                    "area_ha": round(area_ha, 1),
                    "color": ZONE_COLORS.get(name, "#CCCCCC"),
                },
                "geometry": {
                    "type": "Polygon" if geom_4326.geom_type == "Polygon" else "MultiPolygon",
                    "coordinates": geom_4326.__geo_interface__["coordinates"],
                },
            })

        if not features:
            return None

        return {"type": "FeatureCollection", "features": features}

    @staticmethod
    def _build_corridor_line(
        landuse_geojson: Dict,
        gdf: Any,
        gpd: Any,
    ) -> Optional[Dict]:
        """Build a corridor LineString along water parcels."""
        water = gdf[gdf["DLBM"].apply(lambda x: str(x).strip() in WATER_DLBM_CODES)]
        if len(water) < 2:
            return None

        from shapely.geometry import LineString

        water_ctrs = [g for g in water.geometry.centroid if not g.is_empty]
        if len(water_ctrs) < 2:
            return None

        pts = sorted(water_ctrs, key=lambda p: (p.y, p.x))
        coords = [(p.x, p.y) for p in pts]
        step = max(1, len(coords) // 8)
        simplified = coords[::step]
        if simplified[-1] != coords[-1]:
            simplified.append(coords[-1])

        line_3857 = LineString(simplified)
        metric_crs = get_metric_crs(line_3857.centroid.x)
        line_4326 = project_to_wgs84(gpd.GeoSeries([line_3857], crs=metric_crs))[0]

        return {
            "type": "LineString",
            "coordinates": list(line_4326.coords),
        }
