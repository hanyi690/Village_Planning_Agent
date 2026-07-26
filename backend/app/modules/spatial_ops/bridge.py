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


# ── Constraint polygon index ────────────────────────────────────────


@dataclass
class ConstraintOverlap:
    """Result of a parcel overlapping a constraint polygon."""
    bsm: str
    constraint_type: str = ""      # farmland_protection / ecological_redline / historical_protection
    constraint_label: str = ""     # 永久基本农田 / 生态保护红线 / 历史文化保护
    rule: str = "禁止建设"
    overlap_area_sqm: float = 0.0
    overlap_pct: float = 0.0
    parcel_total_area_sqm: float = 0.0


# Mapping from constraint polygon attribute name to constraint metadata
_CONSTRAINT_META = {
    "farmland_protection": {"label": "永久基本农田", "rule": "禁止建设"},
    "ecological_redline": {"label": "生态保护红线", "rule": "禁止建设"},
    "historical_protection": {"label": "历史文化保护", "rule": "禁止破坏"},
    "cultivated_land_target": {"label": "耕地保护目标", "rule": "限制占用"},
    "urban_dev_boundary": {"label": "城镇开发边界", "rule": "控制开发"},
    "village_dev_boundary": {"label": "村庄建设边界", "rule": "控制建设"},
}


class ConstraintIndex:
    """Spatial index over constraint polygons (farmland, redline, etc.).

    Built from VillageBundle constraint polygon groups. Provides overlap
    queries for constraint violation checking.

    Constraint polygons are reference-layer data (上级审批成果, 不可修改),
    accessed via spatial_ops bridge - NOT stored as KG entities.
    """

    def __init__(self, gdf, crs: str = "EPSG:4326"):
        self._gdf = gdf
        self._crs = crs

    def parcel_in_constraint(self, bsm: str) -> List[ConstraintOverlap]:
        """Check if a parcel (by BSM) overlaps any constraint polygon.

        Args:
            bsm: Parcel BSM identifier.

        Returns:
            List of ConstraintOverlap for each overlapping constraint polygon.
        """
        if self._gdf is None:
            return []
        try:
            import geopandas as gpd
            from shapely.geometry import shape
        except ImportError:
            logger.error("geopandas/shapely required for ConstraintIndex")
            return []

        row = self._gdf.loc[self._gdf["bsm"] == bsm]
        if row.empty:
            return []
        parcel_geom = row.iloc[0].geometry
        if parcel_geom.is_empty:
            return []

        results = []
        gdf_metric = self._gdf.to_crs("EPSG:3857")
        parcel_metric = gpd.GeoSeries([parcel_geom], crs=self._crs).to_crs("EPSG:3857").iloc[0]
        parcel_area = parcel_metric.area

        sindex = gdf_metric.sindex
        possible = list(sindex.intersection(parcel_metric.bounds))
        for i in possible:
            if i == row.index[0]:
                continue
            c_geom = gdf_metric.iloc[i].geometry
            if not c_geom.intersects(parcel_metric):
                continue
            overlap = c_geom.intersection(parcel_metric)
            if overlap.is_empty or overlap.area == 0:
                continue
            c_bsm = self._gdf.iloc[i].get("bsm", "")
            c_type = self._gdf.iloc[i].get("constraint_type", "")
            meta = _CONSTRAINT_META.get(c_type, {"label": c_type, "rule": "限制"})
            results.append(ConstraintOverlap(
                bsm=bsm,
                constraint_type=c_type,
                constraint_label=meta["label"],
                rule=meta["rule"],
                overlap_area_sqm=round(overlap.area, 2),
                overlap_pct=round(overlap.area / parcel_area * 100, 1) if parcel_area > 0 else 0.0,
                parcel_total_area_sqm=round(parcel_area, 2),
            ))
        results.sort(key=lambda r: -r.overlap_area_sqm)
        return results

    def geometry_in_constraint(self, geometry: Dict) -> List[ConstraintOverlap]:
        """Check if an arbitrary geometry overlaps any constraint polygon.

        Args:
            geometry: GeoJSON-like geometry dict.

        Returns:
            List of ConstraintOverlap for each overlapping constraint polygon.
        """
        if self._gdf is None:
            return []
        try:
            import geopandas as gpd
            from shapely.geometry import shape
        except ImportError:
            return []

        try:
            query_geom = shape(geometry)
            if query_geom.is_empty:
                return []
            gdf_metric = self._gdf.to_crs("EPSG:3857")
            q_metric = gpd.GeoSeries([query_geom], crs=self._crs).to_crs("EPSG:3857").iloc[0]
            q_area = q_metric.area

            results = []
            sindex = gdf_metric.sindex
            possible = list(sindex.intersection(q_metric.bounds))
            for i in possible:
                c_geom = gdf_metric.iloc[i].geometry
                if not c_geom.intersects(q_metric):
                    continue
                overlap = c_geom.intersection(q_metric)
                if overlap.is_empty or overlap.area == 0:
                    continue
                c_type = self._gdf.iloc[i].get("constraint_type", "")
                meta = _CONSTRAINT_META.get(c_type, {"label": c_type, "rule": "限制"})
                results.append(ConstraintOverlap(
                    bsm="",
                    constraint_type=c_type,
                    constraint_label=meta["label"],
                    rule=meta["rule"],
                    overlap_area_sqm=round(overlap.area, 2),
                    overlap_pct=round(overlap.area / q_area * 100, 1) if q_area > 0 else 0.0,
                    parcel_total_area_sqm=round(q_area, 2),
                ))
            results.sort(key=lambda r: -r.overlap_area_sqm)
            return results
        except Exception as e:
            logger.error("[ConstraintIndex] geometry_in_constraint failed: %s", e)
            return []


def build_constraint_index(bundle) -> Optional[ConstraintIndex]:
    """Build a constraint polygon index from a VillageBundle.

    Indexes all constraint polygon groups from bundle.polygons:
      - farmland_protection
      - ecological_redline
      - historical_protection
      - cultivated_land_target
      - urban_dev_boundary
      - village_dev_boundary

    Each polygon is tagged with its constraint_type for violation reporting.

    Returns:
        ConstraintIndex for querying, or None if bundle has no constraint polygons.
    """
    try:
        import geopandas as gpd
        from shapely.geometry import shape
    except ImportError:
        logger.error("geopandas/shapely required for build_constraint_index")
        return None

    polygons = getattr(bundle, "polygons", None)
    if polygons is None:
        return None

    rows = []
    constraint_groups = [
        ("farmland_protection", polygons.farmland_protection),
        ("ecological_redline", polygons.ecological_redline),
        ("historical_protection", polygons.historical_protection),
        ("cultivated_land_target", polygons.cultivated_land_target),
        ("urban_dev_boundary", polygons.urban_dev_boundary),
        ("village_dev_boundary", polygons.village_dev_boundary),
    ]

    for ctype, items in constraint_groups:
        for item in items:
            bsm = str(getattr(item, "bsm", "")).strip()
            geom = getattr(item, "geometry", None)
            if geom is None:
                continue
            try:
                s = shape(geom)
                if s.is_empty:
                    continue
                rows.append({"bsm": bsm, "constraint_type": ctype, "geometry": s})
            except Exception:
                continue

    if not rows:
        logger.info("[ConstraintIndex] No constraint polygons in bundle")
        return None

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    idx = ConstraintIndex(gdf)
    logger.info("[ConstraintIndex] Built: %d constraint polygons", len(rows))
    return idx


__all__ = [
    "SpatialIndex", "OverlapResult", "build_spatial_index",
    "ConstraintIndex", "ConstraintOverlap", "build_constraint_index",
]
