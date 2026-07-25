"""Geometry computation helpers for spatial context.

Pure geometric operations: centroid, area, near-point search, parcel relations.
These are stateless functions that operate on typed features or GeoDataFrames.

[v4.3] _find_column deleted — replaced by direct attribute access (p.dlbm, p.bsm).
_find_parcels_near_point rewritten to accept typed BaseLandUseParcel list.
compute_parcel_relations computes three-layer spatial relations for KG consumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Three-layer spatial relation types ──


@dataclass
class TouchRelation:
    """L1: topological adjacency — parcels sharing a boundary."""
    bsm_a: str = ""
    bsm_b: str = ""
    dlbm_a: str = ""
    dlbm_b: str = ""
    shared_boundary_length_m: float = 0.0


@dataclass
class NearbyRelation:
    """L2: proximity — parcels within centroid distance threshold."""
    bsm_a: str = ""
    bsm_b: str = ""
    dlbm_a: str = ""
    dlbm_b: str = ""
    centroid_distance_m: float = 0.0


@dataclass
class ConnectedRelation:
    """L3: road-network connectivity - parcels crossed by the same road."""
    bsm_a: str = ""
    bsm_b: str = ""
    road_bsm: str = ""           # which road connects them
    road_length_m: float = 0.0   # length of road segment within the two parcels


@dataclass
class ParcelRelations:
    """Aggregate container for all three-layer parcel relations.

    Produced by compute_parcel_relations() — the only function in the system
    that uses geopandas/shapely for geometry computation.
    Consumed by PlanningKG._add_parcel_relations() — which only reads
    structured data, no geometry.
    """
    touches: List[TouchRelation] = field(default_factory=list)
    nearby: List[NearbyRelation] = field(default_factory=list)
    connected: List[ConnectedRelation] = field(default_factory=list)


def _compute_centroid(boundary_geojson: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Compute centroid of boundary polygon from GeoJSON FeatureCollection."""
    try:
        from app.utils.geojson_utils import geojson_to_geodataframe

        gdf = geojson_to_geodataframe(boundary_geojson)
        if gdf is None or gdf.empty:
            return None
        centroid = gdf.geometry.union_all().centroid
        return (round(centroid.x, 6), round(centroid.y, 6))
    except Exception as e:
        logger.warning("[geometry] Centroid computation failed: %s", e)
        return None


def _compute_total_area(geojson: Dict[str, Any]) -> float:
    """Compute total area in hectares from a GeoJSON FeatureCollection."""
    try:
        from app.utils.geojson_utils import geojson_to_geodataframe
        from app.utils.area_engine import calculate_area_ha

        gdf = geojson_to_geodataframe(geojson)
        if gdf is None or gdf.empty:
            return 0.0
        return sum(calculate_area_ha(geom) for geom in gdf.geometry)
    except Exception:
        return 0.0


def _find_parcels_near_point(
    parcels: List[Any],
    center: Tuple[float, float],
    radius_m: float = 200,
) -> List[str]:
    """Find parcel BSMs near a WGS84 point within radius_m.

    Accepts typed BaseLandUseParcel list — direct attribute access to p.geometry/p.bsm.
    Used when annotation village has no matching cluster in natural_villages.
    """
    parcel_ids: List[str] = []
    try:
        from shapely.geometry import Point, shape

        ref_point = Point(center[0], center[1])
        # Approximate degree radius at ~24N: 1 deg ~ 111km * cos(24) ~ 101km
        radius_deg = radius_m / 101000.0

        for p in parcels:
            geom = getattr(p, "geometry", None)
            if geom is None:
                continue
            try:
                s = shape(geom)
                if s.is_empty:
                    continue
                if ref_point.distance(s.centroid) < radius_deg:
                    bsm = str(getattr(p, "bsm", "")).strip()
                    if bsm:
                        parcel_ids.append(bsm)
            except Exception:
                continue
    except Exception as e:
        logger.debug("[geometry] Parcel near-point lookup failed: %s", e)
    return parcel_ids


def compute_parcel_relations(parcels: List[Any], roads: Optional[List[Any]] = None) -> ParcelRelations:
    """Compute three-layer spatial relations from typed parcel list.

    This is the ONLY function in the system that uses geopandas/shapely
    for geometry computation. KG consumes the returned ParcelRelations
    struct without any geometry dependency.

    Layers:
      L1 touches: parcels sharing a boundary, with shared boundary length
      L2 nearby:  parcels within 200m centroid distance
      L3 connected: parcels crossed by the same road (road-network connectivity)

    Args:
        parcels: List of typed CurrentLandUseParcel objects.
        roads:   Optional list of typed CurrentRoad objects for L3 connectivity.

    Returns:
        ParcelRelations with touches, nearby, and connected lists.
    """
    import geopandas as gpd
    from shapely.geometry import shape

    if not parcels:
        return ParcelRelations()

    # Build GeoDataFrame from typed parcels
    rows = []
    for p in parcels:
        bsm = str(getattr(p, "bsm", "")).strip()
        dlbm = str(getattr(p, "dlbm", "")).strip()
        area_sqm = getattr(p, "area_sqm", 0) or 0
        geom = getattr(p, "geometry", None)
        if not bsm or geom is None:
            continue
        try:
            s = shape(geom)
            if s.is_empty:
                continue
            composite_key = f"{bsm}_{dlbm}_{int(area_sqm)}"
            rows.append({"bsm": bsm, "dlbm": dlbm, "area_sqm": area_sqm,
                         "composite_key": composite_key, "geometry": s})
        except Exception:
            continue

    if not rows:
        return ParcelRelations()

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    gdf_metric = gdf.to_crs("EPSG:3857")

    result = ParcelRelations()

    # L1: topological touches
    try:
        sindex = gdf_metric.sindex
        for i in range(len(gdf_metric)):
            geom_i = gdf_metric.iloc[i].geometry
            possible = list(sindex.intersection(geom_i.bounds))
            for j in possible:
                if i >= j:
                    continue
                geom_j = gdf_metric.iloc[j].geometry
                if geom_i.touches(geom_j):
                    try:
                        shared = geom_i.intersection(geom_j).length
                    except Exception:
                        shared = 0.0
                    result.touches.append(TouchRelation(
                        bsm_a=gdf.iloc[i].bsm, bsm_b=gdf.iloc[j].bsm,
                        dlbm_a=gdf.iloc[i].dlbm, dlbm_b=gdf.iloc[j].dlbm,
                        shared_boundary_length_m=round(shared, 2),
                    ))
    except Exception as e:
        logger.warning("[geometry] L1 touches computation failed: %s", e)

    # L2: nearby (centroid distance <= 200m)
    try:
        centroids = gdf_metric.geometry.centroid
        for i in range(len(centroids)):
            for j in range(i + 1, len(centroids)):
                dist = centroids.iloc[i].distance(centroids.iloc[j])
                if dist <= 200:
                    result.nearby.append(NearbyRelation(
                        bsm_a=gdf.iloc[i].bsm, bsm_b=gdf.iloc[j].bsm,
                        dlbm_a=gdf.iloc[i].dlbm, dlbm_b=gdf.iloc[j].dlbm,
                        centroid_distance_m=round(dist, 2),
                    ))
    except Exception as e:
        logger.warning("[geometry] L2 nearby computation failed: %s", e)

    # L3: connected via road network
    if roads:
        try:
            from shapely.geometry import shape as _shape
            road_geoms = []
            for rd in roads:
                rd_bsm = str(getattr(rd, "bsm", "")).strip()
                rd_geom = getattr(rd, "geometry", None)
                if rd_geom is None:
                    continue
                try:
                    rs = _shape(rd_geom)
                    if rs.is_empty:
                        continue
                    road_geoms.append((rd_bsm, rs))
                except Exception:
                    continue

            if road_geoms:
                rd_metric = gpd.GeoDataFrame(
                    {"road_bsm": [r[0] for r in road_geoms],
                     "geometry": [r[1] for r in road_geoms]},
                    crs="EPSG:4326",
                ).to_crs("EPSG:3857")

                parcel_sindex = gdf_metric.sindex
                for ri in range(len(rd_metric)):
                    road_geom = rd_metric.iloc[ri].geometry
                    road_bsm = rd_metric.iloc[ri].road_bsm
                    # Find parcels this road crosses
                    possible_idx = list(parcel_sindex.intersection(road_geom.bounds))
                    crossed_bsms = []
                    for pi in possible_idx:
                        if road_geom.crosses(gdf_metric.iloc[pi].geometry) or                            road_geom.intersects(gdf_metric.iloc[pi].geometry):
                            crossed_bsms.append((gdf.iloc[pi].bsm, gdf_metric.iloc[pi].geometry))
                    # All pairs of parcels crossed by the same road are connected
                    for a in range(len(crossed_bsms)):
                        for b in range(a + 1, len(crossed_bsms)):
                            try:
                                clip_len = road_geom.intersection(
                                    crossed_bsms[a][1].union(crossed_bsms[b][1])
                                ).length
                            except Exception:
                                clip_len = 0.0
                            result.connected.append(ConnectedRelation(
                                bsm_a=crossed_bsms[a][0],
                                bsm_b=crossed_bsms[b][0],
                                road_bsm=road_bsm,
                                road_length_m=round(clip_len, 2),
                            ))
        except Exception as e:
            logger.warning("[geometry] L3 connected computation failed: %s", e)

    logger.info(
        "[geometry] Parcel relations: %d touches, %d nearby, %d connected",
        len(result.touches), len(result.nearby), len(result.connected),
    )
    return result


__all__ = [
    "_compute_centroid",
    "_compute_total_area",
    "_find_parcels_near_point",
    "compute_parcel_relations",
    "ParcelRelations",
    "TouchRelation",
    "NearbyRelation",
    "ConnectedRelation",
]
