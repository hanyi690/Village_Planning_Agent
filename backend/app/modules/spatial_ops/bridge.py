"""Spatial bridge — EXECUTE agent's interface to bundle geometries.

Maps KG entities (identified by BSM) back to their original geometry
in the VillageBundle for spatial analysis: overlap, proximity, constraint
checking, area measurement.

Usage:
    from app.modules.spatial_ops import build_spatial_index

    idx = build_spatial_index(bundle)
    geom = idx.get_parcel_geometry("441426211000055682")
    overlaps = idx.parcels_intersecting(planned_geometry)

Architecture:
    spatial_ops (this module) computes ad-hoc spatial queries.
    KG stores BSM + derived attributes only, never full geometry.
    EXECUTE agent calls this bridge for any spatial verification.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OverlapResult:
    bsm: str
    dlbm: str = ""
    overlap_area_sqm: float = 0.0
    overlap_pct: float = 0.0
    parcel_total_area_sqm: float = 0.0
    current_zone_type: str = ""


def _build_rtree(parcels):
    try:
        import geopandas as gpd
        from shapely.geometry import shape
    except ImportError:
        logger.error("geopandas/shapely required for spatial bridge")
        return None, {}

    rows = []
    bsm_to_attrs = {}
    for p in parcels:
        bsm = str(getattr(p, "bsm", "")).strip()
        dlbm = str(getattr(p, "dlbm", "")).strip()
        geom = getattr(p, "geometry", None)
        if not bsm or geom is None:
            continue
        try:
            s = shape(geom)
            if s.is_empty:
                continue
            area_sqm = getattr(p, "area_sqm", 0) or 0
            zt = getattr(p, "zone_type", "")
            rows.append({"bsm": bsm, "geometry": s})
            bsm_to_attrs[bsm] = {
                "dlbm": dlbm,
                "area_sqm": area_sqm,
                "zone_type": zt,
            }
        except Exception:
            continue

    if not rows:
        return None, bsm_to_attrs

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    return gdf, bsm_to_attrs


class SpatialIndex:
    """Spatial index over bundle geometries.

    Built from VillageBundle at runtime. Provides ad-hoc query methods
    for EXECUTE agent: geometry lookup, spatial overlap, proximity search.
    """

    def __init__(self, gdf, bsm_to_attrs: Dict[str, Dict], crs: str = "EPSG:4326"):
        self._gdf = gdf
        self._bsm_to_attrs = bsm_to_attrs
        self._crs = crs

    # ── Individual lookup ──

    def get_parcel_geometry(self, bsm: str) -> Optional[Dict]:
        if self._gdf is None:
            return None
        row = self._gdf.loc[self._gdf["bsm"] == bsm]
        if row.empty:
            return None
        from shapely.geometry import mapping
        geom = row.iloc[0].geometry
        return mapping(geom)

    def get_parcel_attrs(self, bsm: str) -> Dict:
        return self._bsm_to_attrs.get(bsm, {})

    def has_parcel(self, bsm: str) -> bool:
        return bsm in self._bsm_to_attrs

    # ── Spatial queries ──

    def parcels_intersecting(self, geometry: Dict) -> List[OverlapResult]:
        if self._gdf is None:
            return []
        from shapely.geometry import shape
        try:
            query_geom = shape(geometry)
            if query_geom.is_empty:
                return []
            import geopandas as gpd

            gdf_metric = self._gdf.to_crs("EPSG:3857")
            q_gs = gpd.GeoSeries([query_geom], crs=self._crs).to_crs("EPSG:3857")
            query_metric = q_gs.iloc[0]

            results = []
            sindex = gdf_metric.sindex
            possible = list(sindex.intersection(query_metric.bounds))
            for i in possible:
                p_geom = gdf_metric.iloc[i].geometry
                if p_geom.intersects(query_metric):
                    bsm = self._gdf.iloc[i].bsm
                    attrs = self._bsm_to_attrs.get(bsm, {})
                    overlap_area = p_geom.intersection(query_metric).area
                    results.append(OverlapResult(
                        bsm=bsm,
                        dlbm=attrs.get("dlbm", ""),
                        overlap_area_sqm=round(overlap_area, 2),
                        overlap_pct=round(overlap_area / attrs.get("area_sqm", 1) * 100, 1) if attrs.get("area_sqm", 0) > 0 else 0.0,
                        parcel_total_area_sqm=attrs.get("area_sqm", 0),
                        current_zone_type=attrs.get("zone_type", ""),
                    ))
            results.sort(key=lambda r: -r.overlap_area_sqm)
            return results
        except Exception as e:
            logger.error("[SpatialIndex] parcels_intersecting failed: %s", e)
            return []

    def parcels_within_bbox(self, bbox: Tuple[float, float, float, float]) -> List[Dict]:
        if self._gdf is None:
            return []
        from shapely.geometry import box
        bbox_poly = box(bbox[0], bbox[1], bbox[2], bbox[3])
        mask = self._gdf.geometry.intersects(bbox_poly)
        results = []
        for _, row in self._gdf[mask].iterrows():
            bsm = row["bsm"]
            attrs = self._bsm_to_attrs.get(bsm, {})
            results.append({"bsm": bsm, **attrs})
        return results

    def parcels_within_distance(self, bsm: str, distance_m: float = 200) -> List[Dict]:
        if self._gdf is None or bsm not in self._bsm_to_attrs:
            return []
        row = self._gdf.loc[self._gdf["bsm"] == bsm]
        if row.empty:
            return []
        ref_geom = row.iloc[0].geometry
        gdf_metric = self._gdf.to_crs("EPSG:3857")
        import geopandas as gpd
        ref_metric = gpd.GeoSeries([ref_geom], crs=self._crs).to_crs("EPSG:3857").iloc[0]
        buffer = ref_metric.buffer(distance_m)
        sindex = gdf_metric.sindex
        possible = list(sindex.intersection(buffer.bounds))
        results = []
        for i in possible:
            p_geom = gdf_metric.iloc[i].geometry
            dist = p_geom.distance(ref_metric)
            if dist <= distance_m and i != row.index[0]:
                b = self._gdf.iloc[i].bsm
                attrs = self._bsm_to_attrs.get(b, {})
                results.append({"bsm": b, "distance_m": round(dist, 2), **attrs})
        return results

    def get_all_bsms(self) -> List[str]:
        return list(self._bsm_to_attrs.keys())

    @property
    def parcel_count(self) -> int:
        return len(self._bsm_to_attrs)


def build_spatial_index(bundle) -> Optional[SpatialIndex]:
    """Build spatial index from a VillageBundle.

    Entry point for EXECUTE agent. Call once at session start, reuse
    the SpatialIndex for ad-hoc spatial queries.

    Args:
        bundle: VillageBundle with polygons.landuse_current populated.

    Returns:
        SpatialIndex for querying, or None if bundle has no parcels.
    """
    parcels = getattr(bundle, "polygons", None)
    if parcels is None:
        return None
    landuse = getattr(parcels, "landuse_current", [])
    if not landuse:
        logger.warning("[SpatialIndex] No parcels in bundle")
        return None

    gdf, bsm_to_attrs = _build_rtree(landuse)
    if gdf is None:
        logger.warning("[SpatialIndex] Failed to build R-tree")
        return None

    idx = SpatialIndex(gdf, bsm_to_attrs)
    logger.info("[SpatialIndex] Built: %d parcels", idx.parcel_count)
    return idx


__all__ = [
    "SpatialIndex", "OverlapResult", "build_spatial_index",
]
