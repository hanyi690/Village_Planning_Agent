"""Geometry computation helpers for spatial context.

Pure geometric operations: centroid, area, near-point search, parcel relations.
These are stateless functions that operate on typed features or GeoDataFrames.

[v4.3] _find_column deleted — replaced by direct attribute access (p.dlbm, p.bsm).
_find_parcels_near_point rewritten to accept typed BaseLandUseParcel list.
compute_parcel_relations computes three-layer spatial relations for KG consumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Integral
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

    Cross-layer fields use existing predicates (intersects, touches, nearby)
    to avoid ontology bloat.
    """
    touches: List[TouchRelation] = field(default_factory=list)
    nearby: List[NearbyRelation] = field(default_factory=list)
    connected: List[ConnectedRelation] = field(default_factory=list)
    # cross-layer: road geometry crosses/intersects parcel
    parcel_road_intersects: List[tuple] = field(default_factory=list)  # [(parcel_bsm, road_bsm)]
    # cross-layer: water body touches parcel boundary
    parcel_water_touches: List[tuple] = field(default_factory=list)    # [(parcel_bsm, water_id)]


def _compute_centroid(boundary_geojson: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Compute centroid of boundary polygon from GeoJSON FeatureCollection."""
    try:
        from .geojson_utils import geojson_to_geodataframe

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
        from .geojson_utils import geojson_to_geodataframe
        from .area_engine import calculate_area_ha

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
    Used when annotation village has no matching cluster in residential_clusters.
    """
    parcel_ids: List[str] = []
    try:
        from shapely.geometry import Point, shape

        ref_point = Point(center[0], center[1])
        # Approximate degree radius at ~24N: 1 deg ~ 111km * cos(24) ~ 101km
        radius_deg = radius_m / 101000.0

        for p in parcels:
            geom = p.geometry
            if geom is None:
                continue
            try:
                s = shape(geom)
                if s.is_empty:
                    continue
                if ref_point.distance(s.centroid) < radius_deg:
                    bsm = str(p.bsm).strip()
                    if bsm:
                        parcel_ids.append(bsm)
            except Exception:
                continue
    except Exception as e:
        logger.debug("[geometry] Parcel near-point lookup failed: %s", e)
    return parcel_ids


def compute_parcel_relations(parcels: List[Any], roads: Optional[List[Any]] = None,
                              water_bodies: Optional[List[Any]] = None) -> ParcelRelations:
    """Compute three-layer + cross-layer spatial relations from typed parcel list.

    This is the ONLY function in the system that uses geopandas/shapely
    for geometry computation. KG consumes the returned ParcelRelations
    struct without any geometry dependency.

    Layers:
      L1 touches: parcels sharing a boundary, with shared boundary length
      L2 nearby:  parcels within area-weighted centroid distance threshold
      L3 connected: parcels crossed by the same road (road-network connectivity)
      Cross-layer: parcel↔road intersects, parcel↔water touches

    Args:
        parcels: List of typed CurrentLandUseParcel objects.
        roads:   Optional list of typed CurrentRoad objects for L3 connectivity.
        water_bodies: Optional list of typed WaterFeature objects for cross-layer touches.

    Returns:
        ParcelRelations with touches, nearby, connected, parcel_road_intersects,
        and parcel_water_touches lists.
    """
    from shapely.geometry import shape
    from shapely.ops import transform
    from shapely.strtree import STRtree
    try:
        from shapely.validation import make_valid
    except ImportError:  # pragma: no cover - Shapely 1.x fallback
        make_valid = None
    try:
        from pyproj import Transformer
        _project = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
    except Exception:
        _project = None

    def _safe_geometry(value: Any):
        """Materialize a valid geometry before any GEOS predicate.

        Uploaded GeoJSON is preserved unchanged for audit; relation computation
        uses this derived copy.  Invalid rings are repaired with the official
        Shapely ``make_valid`` operation and unusable results fail closed.
        """
        try:
            geom = shape(value)
            if geom.is_empty:
                return None
            if not geom.is_valid and make_valid is not None:
                geom = make_valid(geom)
            if geom.is_empty or not geom.is_valid:
                return None
            return geom
        except Exception:
            return None

    def _metric(geom):
        if _project is None:
            return geom
        try:
            return transform(_project, geom)
        except Exception:
            return None

    def _query_indices(tree, geom, geoms):
        try:
            hits = tree.query(geom)
            if len(hits) == 0:
                return []
            first = hits[0]
            if isinstance(first, Integral):
                return [int(i) for i in hits]
            positions = {id(g): i for i, g in enumerate(geoms)}
            return [positions[id(g)] for g in hits if id(g) in positions]
        except Exception:
            return []

    if not parcels:
        return ParcelRelations()

    # Build GeoDataFrame from typed parcels
    rows = []
    for p in parcels:
        bsm = str(p.bsm).strip()
        dlbm = str(p.dlbm).strip()
        area_sqm = p.area_sqm or 0
        geom = p.geometry
        if not bsm or geom is None:
            continue
        try:
            s = _safe_geometry(geom)
            if s is None:
                continue
            composite_key = f"{bsm}_{dlbm}_{int(area_sqm)}"
            rows.append({"bsm": bsm, "dlbm": dlbm, "area_sqm": area_sqm,
                         "composite_key": composite_key, "geometry": s})
        except Exception:
            continue

    if not rows:
        return ParcelRelations()

    parcel_meta = [(r["bsm"], r["dlbm"], r["area_sqm"]) for r in rows]
    parcel_geoms = [r["geometry"] for r in rows]
    metric_geoms = [_metric(g) for g in parcel_geoms]
    valid = [i for i, g in enumerate(metric_geoms) if g is not None and not g.is_empty]
    parcel_meta = [parcel_meta[i] for i in valid]
    parcel_geoms = [parcel_geoms[i] for i in valid]
    metric_geoms = [metric_geoms[i] for i in valid]
    if not metric_geoms:
        return ParcelRelations()
    parcel_tree = STRtree(metric_geoms)

    result = ParcelRelations()

    # L1: topological touches
    try:
        for i, geom_i in enumerate(metric_geoms):
            possible = _query_indices(parcel_tree, geom_i, metric_geoms)
            for j in possible:
                if i >= j:
                    continue
                geom_j = metric_geoms[j]
                if geom_i.touches(geom_j):
                    try:
                        shared = geom_i.intersection(geom_j).length
                    except Exception:
                        shared = 0.0
                    result.touches.append(TouchRelation(
                        bsm_a=parcel_meta[i][0], bsm_b=parcel_meta[j][0],
                        dlbm_a=parcel_meta[i][1], dlbm_b=parcel_meta[j][1],
                        shared_boundary_length_m=round(shared, 2),
                    ))
    except Exception as e:
        logger.warning("[geometry] L1 touches computation failed: %s", e)

    # L2: nearby (area-weighted centroid distance threshold)
    try:
        # Materialize geometry and metadata once.  Repeated GeoSeries.iloc
        # access inside the O(n²) loop is both slow and unstable with the
        # Windows pandas/geopandas stack on the real 660-parcel fixture.
        centroids = [g.centroid for g in metric_geoms]
        # area-weighted: larger parcels have wider nearby range
        sqrt_areas = [max(g.area, 1) ** 0.5 for g in metric_geoms]
        for i in range(len(centroids)):
            for j in range(i + 1, len(centroids)):
                dist = centroids[i].distance(centroids[j])
                threshold = min(500.0, max(200.0, (sqrt_areas[i] + sqrt_areas[j]) * 2))
                if dist <= threshold:
                    result.nearby.append(NearbyRelation(
                        bsm_a=parcel_meta[i][0], bsm_b=parcel_meta[j][0],
                        dlbm_a=parcel_meta[i][1], dlbm_b=parcel_meta[j][1],
                        centroid_distance_m=round(dist, 2),
                    ))
    except Exception as e:
        logger.warning("[geometry] L2 nearby computation failed: %s", e)

    # L3: connected via road network + cross-layer parcel↔road intersects
    if roads:
        try:
            from shapely.geometry import shape as _shape
            road_geoms = []
            for ri_rd, rd in enumerate(roads):
                rd_bsm = str(rd.bsm).strip()
                rd_name = str(rd.road_name).strip() or f"道路_{ri_rd}"
                rd_geom = rd.geometry
                if rd_geom is None:
                    continue
                try:
                    rs = _safe_geometry(rd_geom)
                    if rs is None:
                        continue
                    road_geoms.append((rd_bsm, rd_name, rs))
                except Exception:
                    continue

            if road_geoms:
                rd_metric = [(r[0], r[1], _metric(r[2])) for r in road_geoms]
                for ri, (road_bsm, road_name, road_geom) in enumerate(rd_metric):
                    if road_geom is None or road_geom.is_empty:
                        continue
                    rd_id = road_bsm or road_name
                    # Find parcels this road crosses
                    possible_idx = _query_indices(parcel_tree, road_geom, metric_geoms)
                    crossed_bsms = []
                    for pi in possible_idx:
                        pgeom = metric_geoms[pi]
                        if road_geom.crosses(pgeom) or road_geom.intersects(pgeom):
                            crossed_bsms.append((parcel_meta[pi][0], pgeom))
                            # cross-layer: record parcel↔road intersects
                            result.parcel_road_intersects.append(
                                (parcel_meta[pi][0], rd_id)
                            )
                    # All pairs of parcels crossed by the same road are connected
                    for a in range(len(crossed_bsms)):
                        for b in range(a + 1, len(crossed_bsms)):
                            try:
                                # Current land-use parcels are a partition and
                                # therefore do not overlap.  Measuring each
                                # parcel intersection separately is equivalent
                                # to intersecting their union, but avoids a
                                # repeated GEOS polygon-union call for every
                                # road/parcel pair (which is prohibitively
                                # expensive and unstable on Windows).
                                clip_len = (
                                    road_geom.intersection(crossed_bsms[a][1]).length
                                    + road_geom.intersection(crossed_bsms[b][1]).length
                                )
                            except Exception:
                                clip_len = 0.0
                            result.connected.append(ConnectedRelation(
                                bsm_a=crossed_bsms[a][0],
                                bsm_b=crossed_bsms[b][0],
                                road_bsm=rd_id,
                                road_length_m=round(clip_len, 2),
                            ))
        except Exception as e:
            logger.warning("[geometry] L3 connected computation failed: %s", e)

    # Cross-layer: parcel↔water touches
    if water_bodies:
        try:
            from shapely.geometry import shape as _shape
            water_geoms = []
            for w in water_bodies:
                w_id = str(w.bsm).strip()
                w_geom = w.geometry
                if not w_id or w_geom is None:
                    continue
                try:
                    ws = _safe_geometry(w_geom)
                    if ws is None:
                        continue
                    water_geoms.append((w_id, ws))
                except Exception:
                    continue

            if water_geoms:
                w_metric = [(w[0], _metric(w[1])) for w in water_geoms]
                for wi, (water_id, water_geom) in enumerate(w_metric):
                    if water_geom is None or water_geom.is_empty:
                        continue
                    possible_idx = _query_indices(parcel_tree, water_geom, metric_geoms)
                    for pi in possible_idx:
                        parcel_geom = metric_geoms[pi]
                        if parcel_geom.touches(water_geom) or parcel_geom.intersects(water_geom):
                            result.parcel_water_touches.append(
                                (parcel_meta[pi][0], water_id)
                            )
        except Exception as e:
            logger.warning("[geometry] Cross-layer water computation failed: %s", e)

    logger.info(
        "[geometry] Parcel relations: %d touches, %d nearby, %d connected, "
        "%d parcel↔road, %d parcel↔water",
        len(result.touches), len(result.nearby), len(result.connected),
        len(result.parcel_road_intersects), len(result.parcel_water_touches),
    )
    return result


def point_in_polygon(point: Tuple[float, float], geometry: Dict[str, Any]) -> bool:
    """Ray-casting point-in-polygon for GeoJSON Polygon/MultiPolygon (pure python)."""
    if not point or not geometry:
        return False
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "Polygon":
        coords = [coords]
    px, py = float(point[0]), float(point[1])
    for poly in coords:
        if not poly:
            continue
        ring = poly[0] if isinstance(poly[0], list) else poly
        inside = False
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = float(ring[i][0]), float(ring[i][1])
            xj, yj = float(ring[j][0]), float(ring[j][1])
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        if inside:
            return True
    return False


def village_boundary_geometry(bundle: Any) -> Optional[Dict[str, Any]]:
    """First village boundary polygon (admin_areas, fallback planning_scope)."""
    if bundle is None:
        return None
    for key in ("admin_areas", "planning_scope"):
        for f in bundle.polygons.get(key) or []:
            geom = f.geometry if not isinstance(f, dict) else f.get("geometry")
            if geom:
                return geom
    return None


__all__ = [
    "_compute_centroid",
    "_compute_total_area",
    "_find_parcels_near_point",
    "compute_parcel_relations",
    "ParcelRelations",
    "TouchRelation",
    "NearbyRelation",
    "ConnectedRelation",
    "point_in_polygon",
    "village_boundary_geometry",
]
