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
    zone_type: str = ""


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
        bsm = str(p.bsm).strip()
        dlbm = str(p.dlbm).strip()
        geom = p.geometry
        if not bsm or geom is None:
            continue
        try:
            s = shape(geom)
            if s.is_empty:
                continue
            area_sqm = p.area_sqm or 0
            zt = p.zone_type
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
                        zone_type=attrs.get("zone_type", ""),
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
    landuse = parcels.get("landuse_current")
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
    "conditional_construction_zone": {"label": "有条件建设区", "rule": "条件准入"},
    "construction_ctrl_zone": {"label": "建设管制区", "rule": "控制建设"},
    "hazard_control_line": {"label": "灾害防治控制线", "rule": "禁止建设"},
    "flood_control_line": {"label": "防洪控制线", "rule": "限制建设"},
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
        ("farmland_protection", polygons.get("farmland_protection")),
        ("ecological_redline", polygons.get("ecological_redline")),
        ("historical_protection", polygons.get("historical_protection")),
        ("cultivated_land_target", polygons.get("cultivated_land_target")),
        ("urban_dev_boundary", polygons.get("urban_dev_boundary")),
        ("village_dev_boundary", polygons.get("village_dev_boundary")),
        ("conditional_construction_zone", polygons.get("construction_zone")),
        ("construction_ctrl_zone", polygons.get("construction_ctrl_zone")),
        ("hazard_control_line", polygons.get("hazard_control_line")),
        ("flood_control_line", polygons.get("flood_control_line")),
    ]

    for ctype, items in constraint_groups:
        for item in items:
            bsm = str(item.bsm).strip()
            geom = item.geometry
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


def compute_water_overlap(water_polygons, landuse_parcels, dlbm_filter="3100"):
    """For each water polygon, find completely covered DLBM=3100 parcels.

    Uses shapely.contains() — a water polygon that completely contains
    a landuse parcel means the parcel is already classified as water area.
    The water polygon is then linked via derived_from instead of duplicated.

    Args:
        water_polygons: List of WaterFeature objects (or geo-like dicts).
        landuse_parcels: List of CurrentLandUseParcel objects.
        dlbm_filter: DLBM code for water parcels (default 3100).

    Returns:
        Dict mapping water_feature_id -> [covered_bsm1, covered_bsm2, ...]
    """
    try:
        import geopandas as gpd
        from shapely.geometry import shape
    except ImportError:
        logger.error("geopandas/shapely required for compute_water_overlap")
        return {}

    # Build landuse index for DLBM=3100 parcels
    water_parcels = []
    for p in landuse_parcels:
        dlbm = str(p.dlbm).strip()
        if dlbm != dlbm_filter:
            continue
        bsm = str(p.bsm).strip()
        geom = p.geometry
        if not bsm or geom is None:
            continue
        try:
            s = shape(geom)
            if not s.is_empty:
                water_parcels.append({"bsm": bsm, "geometry": s})
        except Exception:
            continue

    if not water_parcels:
        logger.info("[compute_water_overlap] No DLBM=%s parcels found", dlbm_filter)
        return {}

    parcel_gdf = gpd.GeoDataFrame(water_parcels, crs="EPSG:4326")
    parcel_gdf_metric = parcel_gdf.to_crs("EPSG:3857")

    # For each water polygon, check which parcels it completely covers
    overlap_map = {}
    for i, wp in enumerate(water_polygons):
        geom = wp.geometry if not isinstance(wp, dict) else wp.get("geometry")
        if geom is None:
            continue
        try:
            water_s = shape(geom)
            if water_s.is_empty:
                continue
            water_metric = water_s  # keep in same CRS
            # Convert to metric for accurate containment check
            wp_series = gpd.GeoSeries([water_s], crs="EPSG:4326").to_crs("EPSG:3857")
            water_metric = wp_series.iloc[0]

            covered_bsms = []
            for j in range(len(parcel_gdf_metric)):
                p_geom = parcel_gdf_metric.iloc[j].geometry
                if water_metric.contains(p_geom):
                    covered_bsms.append(parcel_gdf_metric.iloc[j]["bsm"])

            if covered_bsms:
                wid = str(wp.bsm) or str(wp.water_name) or f"water_poly_{i}"
                overlap_map[wid] = covered_bsms
        except Exception:
            continue

    if overlap_map:
        total_covered = sum(len(v) for v in overlap_map.values())
        logger.info("[compute_water_overlap] %d water polygons cover %d DLBM=%s parcels",
                    len(overlap_map), total_covered, dlbm_filter)
    return overlap_map


# ── Cross-layer spatial relation computation ────────────────────────

_PLN_NS = "http://village-planning.org/ontology#"

_POLYGON_LAYERS = [
    ("parcel",                  "landuse_current"),
    ("farmland_protection",     "farmland_protection"),
    ("ecological_redline",      "ecological_redline"),
    ("historical_protection",   "historical_protection"),
    ("zone_conditional",        "construction_zone"),
    ("admin",                   "admin_areas"),
    ("water",                   "water_bodies"),
    ("zone_jsydgzq",            "construction_ctrl_zones"),
    ("tdyt",                    "land_use_zones"),
]

_POINT_LAYERS = [
    ("facility",  "facilities_current"),
    ("building",  "buildings"),
    ("hazard",    "hazard_points"),
    ("elevpt",    "elevation_points"),
]

_LINE_LAYERS = [
    ("road",       "roads_current"),
    ("adminline",  "admin_boundaries"),
    ("contour",    "contour_lines"),
    ("hazard_line","hazard_control_lines"),
]


def _collect_entities(bundle, layer_defs, geom_field="geometry"):
    """Extract (prefix, uri, shapely_geom) tuples from bundle layers."""
    collected = []
    polygons = getattr(bundle, "polygons", None)
    lines = getattr(bundle, "lines", None)
    points = getattr(bundle, "points", None)
    from shapely.geometry import shape

    for prefix, attr_name in layer_defs:
        container = polygons
        if attr_name in ("roads_current", "admin_boundaries", "contour_lines",
                         "hazard_control_lines", "roads_planned"):
            container = lines
        elif attr_name in ("facilities_current", "buildings", "hazard_points",
                           "elevation_points", "annotations_current"):
            container = points
        if container is None:
            continue
        items = container.get(attr_name)
        for item in items:
            geom = getattr(item, geom_field, None)
            if geom is None:
                continue
            bsm = str(item.bsm).strip()
            if not bsm:
                continue
            try:
                s = shape(geom)
                if s.is_empty:
                    continue
                uri = f"{_PLN_NS}{prefix}_{bsm}"
                collected.append((prefix, uri, s))
            except Exception:
                continue
    return collected


def compute_cross_layer_relations(bundle) -> Dict[str, list]:
    """Compute all cross-layer spatial relations from bundle geometry.

    Uses shapely strict geometric predicates for every entity pair:
      - Point entities within polygon  →  located_in
      - Polygon overlaps polygon       →  intersects (with overlap_pct)
      - Line intersects polygon        →  intersects

    Returns dict compatible with PlanningKG._add_cross_type_relations:
      - "located_in":  [(subj_uri, obj_uri), ...]
      - "intersects":  [(subj_uri, obj_uri, overlap_pct), ...]
      - "contains":    [(subj_uri, obj_uri), ...]

    Returns empty dict if shapely/geopandas unavailable or bundle empty.
    """
    try:
        import geopandas as gpd
        from shapely.geometry import shape
        from shapely.validation import make_valid
    except ImportError:
        logger.error("geopandas/shapely required for compute_cross_layer_relations")
        return {}

    polygons = getattr(bundle, "polygons", None)
    if polygons is None:
        return {}

    result: Dict[str, list] = {"located_in": [], "intersects": [], "contains": []}

    def _fix_geom(g):
        g = make_valid(g) if not g.is_valid else g
        return g.buffer(0) if not g.is_valid else g

    # 1. Collect all polygon entities and fix invalid geometries
    poly_entries = _collect_entities(bundle, _POLYGON_LAYERS)
    if not poly_entries:
        return result

    poly_entries = [(p, u, _fix_geom(s)) for p, u, s in poly_entries]

    # 2. Collect point entities
    point_entries = [(_p, u, _fix_geom(s)) for _p, u, s in _collect_entities(bundle, _POINT_LAYERS)]

    # 3. Collect line entities
    line_entries = [(_p, u, _fix_geom(s)) for _p, u, s in _collect_entities(bundle, _LINE_LAYERS)]

    def _safe_contains(a, b):
        try:
            return a.contains(b)
        except Exception:
            return False

    def _safe_intersects(a, b):
        try:
            return a.intersects(b)
        except Exception:
            return False

    def _safe_intersection(a, b):
        try:
            return a.intersection(b)
        except Exception:
            import shapely
            return shapely.geometry.Polygon()

    # ── Located_in: point entities within polygon entities ──
    if point_entries:
        poly_gdf_idx = gpd.GeoDataFrame(
            [{"uri": u, "geometry": s} for _p, u, s in poly_entries], crs="EPSG:4326",
        ).to_crs("EPSG:3857")
        sindex = poly_gdf_idx.sindex

        for _prefix, pt_uri, pt_s in point_entries:
            pt_geom = gpd.GeoSeries([pt_s], crs="EPSG:4326").to_crs("EPSG:3857").iloc[0]
            try:
                candidates = list(sindex.intersection(pt_geom.bounds))
            except Exception:
                continue
            for c in candidates:
                poly_geom = poly_gdf_idx.iloc[c].geometry
                if poly_geom.contains(pt_geom):
                    result["located_in"].append((pt_uri, poly_gdf_idx.iloc[c].uri))
                    result["contains"].append((poly_gdf_idx.iloc[c].uri, pt_uri))
                    break

    # ── Intersects: parcels overlapping protection/constraint zones ──
    protection_types = {"farmland_protection", "ecological_redline",
                        "historical_protection", "zone_conditional"}

    parcel_rows = []
    prot_rows = []
    for _p, uri, s in poly_entries:
        if _p == "parcel":
            parcel_rows.append((uri, s))
        elif _p in protection_types:
            prot_rows.append((uri, s))

    if parcel_rows and prot_rows:
        prot_gdf = gpd.GeoDataFrame(
            [{"uri": uri, "geometry": s} for uri, s in prot_rows], crs="EPSG:4326",
        ).to_crs("EPSG:3857")

        sindex = prot_gdf.sindex
        for pa_uri, pa_s in parcel_rows:
            pa_geom = gpd.GeoSeries([pa_s], crs="EPSG:4326").to_crs("EPSG:3857").iloc[0]
            pa_area = pa_geom.area
            try:
                candidates = list(sindex.intersection(pa_geom.bounds))
            except Exception:
                continue
            for c in candidates:
                pc_geom = prot_gdf.iloc[c].geometry
                if not _safe_intersects(pa_geom, pc_geom):
                    continue
                overlap = _safe_intersection(pa_geom, pc_geom)
                if overlap.is_empty or overlap.area == 0:
                    continue
                pc_uri = prot_gdf.iloc[c].uri
                overlap_pct = round(overlap.area / pa_area * 100, 1) if pa_area > 0 else 0.0
                result["intersects"].append((pa_uri, pc_uri, overlap_pct))

    # ── Intersects: line entities intersecting protection polygons ──
    if line_entries and prot_rows:
        prot_gdf = gpd.GeoDataFrame(
            [{"uri": uri, "geometry": s} for uri, s in prot_rows], crs="EPSG:4326",
        ).to_crs("EPSG:3857")
        sindex = prot_gdf.sindex
        for _prefix, li_uri, li_s in line_entries:
            li_geom = gpd.GeoSeries([li_s], crs="EPSG:4326").to_crs("EPSG:3857").iloc[0]
            try:
                candidates = list(sindex.intersection(li_geom.bounds))
            except Exception:
                continue
            for c in candidates:
                pc_geom = prot_gdf.iloc[c].geometry
                if _safe_intersects(li_geom, pc_geom):
                    result["intersects"].append((li_uri, prot_gdf.iloc[c].uri, 0.0))

    # ── Located_in: road/line within admin_area ──
    admin_entries = [(u, s) for p, u, s in poly_entries if p == "admin"]
    if line_entries and admin_entries:
        admin_gdf = gpd.GeoDataFrame(
            [{"uri": uri, "geometry": s} for uri, s in admin_entries], crs="EPSG:4326",
        ).to_crs("EPSG:3857")
        sindex = admin_gdf.sindex
        for _prefix, li_uri, li_s in line_entries:
            li_geom = gpd.GeoSeries([li_s], crs="EPSG:4326").to_crs("EPSG:3857").iloc[0]
            try:
                candidates = list(sindex.intersection(li_geom.bounds))
            except Exception:
                continue
            for c in candidates:
                ad_geom = admin_gdf.iloc[c].geometry
                if _safe_contains(ad_geom, li_geom):
                    result["located_in"].append((li_uri, admin_gdf.iloc[c].uri))
                    break

    total = len(result["located_in"]) + len(result["intersects"]) + len(result["contains"])
    if total:
        logger.info(
            "[compute_cross_layer_relations] %d relations: %d located_in, %d intersects, %d contains",
            total, len(result["located_in"]), len(result["intersects"]), len(result["contains"]),
        )
    return result


__all__ = [
    "SpatialIndex", "OverlapResult", "build_spatial_index",
    "ConstraintIndex", "ConstraintOverlap", "build_constraint_index",
    "compute_water_overlap",
    "compute_cross_layer_relations",
]
