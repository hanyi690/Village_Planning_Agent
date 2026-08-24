"""地块多因子上下文构造（B3）— 供自定义功能区规则求值。

Vocabulary context is used by the current materialization boundary in docs/design/03_PLANNING_EXECUTION.md.

每地块：dlbm / area_ha / slope_deg(DEM) / road_distance_m / zone_membership / poi_hits
因子缺失降级：slope 无 DEM → 999（slope_lt 视为通过）；
              road 无道路 → 99999（road_distance_lt 视为不通过）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _load_dem_slope(bundle: Any) -> Optional[Dict[str, float]]:
    """DEM（terrain/dem.tif）→ 每地块质心坡度（度）。失败返回 None（slope 因子降级）。"""
    try:
        import numpy as np
        import rasterio
        from shapely.geometry import shape

        rasters = getattr(bundle, "rasters", None)
        # RasterLayerGroup 是 Pydantic 模型：直接取 dem 字段（迭代模型得到的是字段名）
        dem = None
        if rasters is not None:
            dem_feature = getattr(rasters, "dem", None)
            if dem_feature is not None:
                dem = getattr(dem_feature, "path", None) or getattr(
                    dem_feature, "data_path", None
                )
        if not dem:
            return None
        with rasterio.open(str(dem)) as src:
            elev = src.read(1).astype("float64")
            # rasterio 1.3 无 rasterio.terrain → np.gradient 自实现坡度（度）。
            # DEM 为 EPSG:4326 度网格：像素尺寸换算为米（纬度校正）后再求梯度。
            deg_x = abs(src.transform.a)
            deg_y = abs(src.transform.e)
            lat_mid = (src.bounds.top + src.bounds.bottom) / 2.0
            import math
            m_per_deg_lat = 110540.0
            m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_mid))
            dx_m = deg_x * m_per_deg_lon
            dy_m = deg_y * m_per_deg_lat
            # gradient 的 varargs 依次对应 axis0(y)、axis1(x)
            gy, gx = np.gradient(elev, dy_m, dx_m)
            slope_arr = np.degrees(np.arctan(np.hypot(gx, gy)))
            transform = src.transform
            result = {}
            for f in (bundle.polygons.get("landuse_current") or []):
                geom = getattr(f, "geometry", None)  # getattr intentional: defensive over feature types
                if not geom:
                    continue
                c = shape(geom).centroid
                row, col = ~transform * (c.x, c.y)
                r, c_ = int(round(row)), int(round(col))
                if 0 <= r < slope_arr.shape[0] and 0 <= c_ < slope_arr.shape[1]:
                    val = float(slope_arr[r, c_])
                    if np.isfinite(val):
                        result[str(getattr(f, "bsm", ""))] = val  # getattr intentional: defensive over feature types
            return result
    except Exception as e:
        logger.debug("[Context] DEM slope unavailable: %s", type(e).__name__)
        return None


def _road_distances(bundle: Any) -> Dict[str, float]:
    """每地块质心到最近现状道路的距离（米）。"""
    try:
        from shapely.geometry import shape
        from shapely.ops import nearest_points

        roads = []
        for f in (bundle.lines.get("roads_current") or []) + (bundle.lines.get("roads_planned") or []):
            geom = getattr(f, "geometry", None)  # getattr intentional: defensive over feature types
            if geom:
                roads.append(shape(geom))
        if not roads:
            return {}
        result = {}
        for f in (bundle.polygons.get("landuse_current") or []):
            geom = getattr(f, "geometry", None)  # getattr intentional: defensive over feature types
            if not geom:
                continue
            c = shape(geom).centroid
            best = min((c.distance(r) for r in roads), default=99999.0)
            result[str(getattr(f, "bsm", ""))] = best * 111320.0  # getattr intentional: defensive over feature types; 度→米近似
        return result
    except Exception as e:
        logger.debug("[Context] road distance unavailable: %s", type(e).__name__)
        return {}


def _zone_membership(bundle: Any) -> Dict[str, List[str]]:
    """每地块的三线成员（生态红线/基本农田）。"""
    try:
        from shapely.geometry import shape
        from shapely.ops import unary_union

        membership: Dict[str, List[str]] = {}
        for key, label in (
            ("ecological_redline", "in_ecological_redline"),
            ("farmland_protection", "in_basic_farmland"),
        ):
            geoms = [shape(getattr(f, "geometry", None)) for f in (bundle.polygons.get(key) or [])]  # getattr intentional: defensive over feature types
            geoms = [g for g in geoms if g is not None and not g.is_empty]
            if not geoms:
                continue
            union = unary_union(geoms)
            for f in (bundle.polygons.get("landuse_current") or []):
                geom = getattr(f, "geometry", None)  # getattr intentional: defensive over feature types
                if geom and shape(geom).intersects(union):
                    membership.setdefault(str(getattr(f, "bsm", "")), []).append(label)  # getattr intentional: defensive over feature types
        return membership
    except Exception as e:
        logger.debug("[Context] zone membership unavailable: %s", type(e).__name__)
        return {}


def _poi_hits(bundle: Any) -> Dict[str, List[Dict[str, str]]]:
    """每地块邻近 POI（历史保护面质心名称）。"""
    try:
        from shapely.geometry import shape
        from shapely.ops import unary_union

        hits: Dict[str, List[Dict[str, str]]] = {}
        for f in (bundle.polygons.get("historical_protection") or []):
            geom = getattr(f, "geometry", None)  # getattr intentional: defensive over feature types
            name = str(getattr(f, "protection_level", "") or "历史保护")
            if not geom:
                continue
            c = shape(geom).centroid
            for p in (bundle.polygons.get("landuse_current") or []):
                pgeom = getattr(p, "geometry", None)  # getattr intentional: defensive over feature types
                if pgeom and shape(pgeom).distance(c) < 0.003:  # ~300m
                    hits.setdefault(str(getattr(p, "bsm", "")), []).append({"name": name})  # getattr intentional: defensive over feature types
        return hits
    except Exception as e:
        logger.debug("[Context] poi unavailable: %s", type(e).__name__)
        return {}


def build_parcel_contexts(
    parcels: List[Dict[str, Any]],
    bundle: Any,
) -> Dict[str, Dict[str, Any]]:
    """批量构造地块多因子上下文（bsm → context dict）。"""
    slopes = _load_dem_slope(bundle)
    road_d = _road_distances(bundle)
    zones = _zone_membership(bundle)
    pois = _poi_hits(bundle)

    contexts: Dict[str, Dict[str, Any]] = {}
    for p in parcels:
        bsm = str(p.get("bsm", ""))
        contexts[bsm] = {
            "dlbm": str(p.get("dlbm", "")),
            "area_ha": float(p.get("area_ha", 0) or 0),
            "slope_deg": float((slopes or {}).get(bsm, 999)),
            "road_distance_m": float(road_d.get(bsm, 99999)),
            "zone_membership": list(zones.get(bsm, [])),
            "poi_hits": list(pois.get(bsm, [])),
        }
    logger.info("[Context] built %d parcel contexts (slope=%s road=%s zone=%s poi=%s)",
                len(contexts), bool(slopes), bool(road_d), bool(zones), bool(pois))
    return contexts


__all__ = ["build_parcel_contexts"]
