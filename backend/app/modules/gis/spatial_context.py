"""Spatial context computation — derive compact spatial context from GIS data.

Computes SpatialContext (~2KB) from raw GIS data bundles (~5MB).
This is the "spatial grounding" step that lets PARSE Agent understand
spatial references like "east of Liu village group" without raw geometry.

Inspired by:
  - Spatial-Agent: "spatial grounding" — semantic to computational representation
  - GeoWorkbench: compute_spatial_context() as explicit pipeline stage
  - OpenEarthAgent: compact "spatial working memory" concept
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger
from app.modules.gis.schema.contracts import (
    ConstraintSummary,
    FacilityAnchor,
    LanduseEntry,
    NaturalVillageAnchor,
    SpatialContext,
    SpatialRelation,
    TerrainProfile,
)
from app.modules.gis.schema.spatial_types import ANNOTATION_LABEL_TYPE_MAP

logger = get_logger(__name__)


# ── Main entry point ────────────────────────────────────────────────


def compute_spatial_context(gis_data: Dict[str, Any]) -> SpatialContext:
    """Compute compact spatial context from GIS data bundle.

    Args:
        gis_data: Dict with keys like 'boundary_geojson', 'landuse_current_geojson',
                  'farmland_protection_geojson', 'ecological_protection_geojson', etc.

    Returns:
        SpatialContext: ~2KB compact representation for LLM injection.
    """
    ctx = SpatialContext()

    # 1. Base statistics from landuse
    landuse_geojson = gis_data.get("landuse_current_geojson") or gis_data.get("landuse_geojson")
    if landuse_geojson:
        ctx.landuse_distribution = _compute_landuse_distribution(landuse_geojson)
        ctx.parcel_count = sum(e.count for e in ctx.landuse_distribution)
        ctx.total_area_ha = round(sum(e.area_ha for e in ctx.landuse_distribution), 2)

    # 2. Village center from boundary
    boundary_geojson = gis_data.get("boundary_geojson")
    if boundary_geojson:
        ctx.village_center = _compute_centroid(boundary_geojson)

    # 3. Construction boundary area
    construction_geojson = gis_data.get("construction_zone_geojson")
    if construction_geojson:
        ctx.construction_boundary_ha = _compute_total_area(construction_geojson)

    # 4. Natural village anchors
    if landuse_geojson:
        ctx.natural_villages = _cluster_natural_villages(
            landuse_geojson,
            place_aliases=_load_place_aliases(),
        )

    # 5. Spatial relations
    if landuse_geojson and ctx.natural_villages:
        ctx.spatial_relations = _compute_spatial_relations(
            landuse_geojson,
            ctx.natural_villages,
        )

    # 6. Constraint summary from protection layers
    ctx.constraint_summary = _compute_constraint_summary(gis_data)

    # 7. Zone adjacency
    if landuse_geojson:
        ctx.zone_adjacency = _compute_zone_adjacency(landuse_geojson)

    # 8. Facility anchors from annotation.geojson (precise coordinates)
    annotation_geojson = gis_data.get("annotation_geojson")
    if annotation_geojson:
        ctx.facility_anchors = _extract_facility_anchors(annotation_geojson)
        ctx.annotation_villages = _extract_annotation_villages(annotation_geojson)

    # 9. Merge annotation villages into natural_villages (annotation names more precise)
    if ctx.annotation_villages:
        _merge_annotation_villages(ctx, landuse_geojson)

    # 10. Terrain profile (P2 reserved — no-op when DEM data unavailable)
    ctx.terrain_profile = _compute_terrain_profile(gis_data)

    logger.info(
        "[SpatialContext] Computed: %d parcels, %d villages, %d relations, %d constraints, "
        "%d facility anchors",
        ctx.parcel_count,
        len(ctx.natural_villages),
        len(ctx.spatial_relations),
        len(ctx.constraint_summary),
        len(ctx.facility_anchors),
    )

    return ctx


# ── Sub-computations ────────────────────────────────────────────────


def _compute_centroid(boundary_geojson: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Compute centroid of boundary polygon."""
    try:
        from app.utils.geojson_utils import geojson_to_geodataframe

        gdf = geojson_to_geodataframe(boundary_geojson)
        if gdf is None or gdf.empty:
            return None
        centroid = gdf.geometry.union_all().centroid
        return (round(centroid.x, 6), round(centroid.y, 6))
    except Exception as e:
        logger.warning("[SpatialContext] Centroid computation failed: %s", e)
        return None


def _compute_landuse_distribution(landuse_geojson: Dict[str, Any]) -> List[LanduseEntry]:
    """Compute land-use distribution from current landuse GeoJSON.

    Encoding note: 现状层 DLBM = appendix5 编码 (2121=宅基地).
    使用 DLBM_TO_DLMC (合并多体系) 做名称查询，get_zone_type_for_dlbm 做分区查询。
    """
    try:
        from app.utils.geojson_utils import geojson_to_geodataframe
        from app.utils.area_engine import calculate_area_ha
        from app.modules.gis.schema import get_zone_type_for_dlbm, dlbm_to_planning_zone, DLBM_TO_DLMC

        gdf = geojson_to_geodataframe(landuse_geojson)
        if gdf is None or gdf.empty:
            return []

        dlbm_col = _find_column(gdf, ["DLBM", "dlbm"])
        if not dlbm_col:
            return []

        entries = []
        for dlbm, group in gdf.groupby(dlbm_col):
            dlbm_str = str(dlbm).strip()
            area_ha = sum(calculate_area_ha(geom) for geom in group.geometry)
            zone_type = get_zone_type_for_dlbm(dlbm_str)
            planning_zone = dlbm_to_planning_zone(dlbm_str)
            name = DLBM_TO_DLMC.get(dlbm_str, dlbm_str)

            entries.append(LanduseEntry(
                dlbm=dlbm_str,  # appendix5 编码 (现状层)
                name=name,
                count=len(group),
                area_ha=round(area_ha, 2),
                zone_type=zone_type,
                planning_zone=planning_zone,
            ))

        return sorted(entries, key=lambda e: e.area_ha, reverse=True)
    except Exception as e:
        logger.warning("[SpatialContext] Landuse distribution failed: %s", e)
        return []


def _cluster_natural_villages(
    landuse_geojson: Dict[str, Any],
    place_aliases: Dict[str, str] = None,
) -> List[NaturalVillageAnchor]:
    """Cluster residential parcels into natural village anchors.

    Strategy:
      1. Filter residential parcels (DLBM matching residential codes)
      2. Group by spatial proximity (DBSCAN or simple distance clustering)
      3. Match cluster names against place_aliases
      4. Compute adjacency from neighboring parcels
    """
    try:
        from app.utils.geojson_utils import geojson_to_geodataframe

        gdf = geojson_to_geodataframe(landuse_geojson)
        if gdf is None or gdf.empty:
            return []

        dlbm_col = _find_column(gdf, ["DLBM", "dlbm"])
        if not dlbm_col:
            return []

        # Filter residential parcels via DictionaryCenter zone_type lookup
        # Supports both current (2121=GHYTBM) and planned (2030=三调) DLBM encodings
        from app.modules.gis.schema import get_dlbms_for_zone_type
        _RESIDENTIAL_DLBMS = set(get_dlbms_for_zone_type("居住用地"))
        residential = gdf[
            gdf[dlbm_col].astype(str).str.strip().isin(_RESIDENTIAL_DLBMS)
        ]
        if residential.empty:
            return []

        # Simple clustering: group by centroid proximity (within 200m)
        from shapely.ops import unary_union
        from app.utils.crs_engine import project_to_metric

        gdf_metric = project_to_metric(residential)
        if gdf_metric is None or gdf_metric.empty:
            return []

        # Buffer and dissolve to find clusters
        buffers = gdf_metric.geometry.buffer(150)  # 150m buffer
        merged = unary_union(buffers.tolist())

        # Each connected component is a cluster
        if merged.geom_type == "Polygon":
            components = [merged]
        elif merged.geom_type == "MultiPolygon":
            components = list(merged.geoms)
        else:
            return []

        anchors = []
        place_aliases = place_aliases or {}

        for i, component in enumerate(components):
            # Find parcels within this cluster
            cluster_centroid = component.centroid
            # Project back to WGS84 for the centroid
            from app.utils.crs_engine import project_to_wgs84
            # Find parcels whose metric centroid falls within the cluster
            mask = gdf_metric.geometry.centroid.within(component.buffer(10))
            cluster_parcels = residential[mask]

            if cluster_parcels.empty:
                continue

            # Compute WGS84 centroid directly from residential parcels
            cluster_wgs84 = residential[mask]
            if not cluster_wgs84.empty:
                wgs84_center = cluster_wgs84.geometry.union_all().centroid
                center = (round(wgs84_center.x, 6), round(wgs84_center.y, 6))
            else:
                center = None

            # Get parcel IDs
            bsm_col = _find_column(cluster_parcels, ["BSM", "bsm"])
            parcel_ids = cluster_parcels[bsm_col].astype(str).tolist() if bsm_col else []

            # Dominant land use
            dominant = cluster_parcels[dlbm_col].astype(str).str.strip().mode().iloc[0] if len(cluster_parcels) > 0 else ""

            # Try to match name from place_aliases by proximity
            name = f"VillageGroup_{i + 1}"
            for alias_name, alias_center_str in place_aliases.items():
                # Simple string matching for now
                # TODO: implement coordinate-based matching
                pass

            # Compute adjacency (simplified: check neighboring non-residential parcels)
            adjacent_zones = []
            non_residential = gdf[
                ~gdf[dlbm_col].astype(str).str.strip().isin(_RESIDENTIAL_DLBMS)
            ]
            if not non_residential.empty:
                non_res_metric = project_to_metric(non_residential)
                if non_res_metric is not None and not non_res_metric.empty:
                    nearby = non_res_metric[non_res_metric.geometry.distance(component.boundary) < 100]
                    if not nearby.empty:
                        from app.modules.gis.schema import get_zone_type_for_dlbm
                        adjacent_zones = list(set(
                            get_zone_type_for_dlbm(str(d).strip())
                            for d in nearby[dlbm_col].values
                        ))

            anchors.append(NaturalVillageAnchor(
                name=name,
                center=center,
                parcel_ids=parcel_ids[:20],  # Limit to avoid bloat
                dominant_landuse=dominant,
                adjacent_to=adjacent_zones[:5],
            ))

        return anchors
    except Exception as e:
        logger.warning("[SpatialContext] Natural village clustering failed: %s", e)
        return []


def _compute_spatial_relations(
    landuse_geojson: Dict[str, Any],
    natural_villages: List[NaturalVillageAnchor],
) -> List[SpatialRelation]:
    """Compute spatial relations between natural villages and zones.

    Uses centroid-based direction computation and distance-based topology.
    """
    relations = []

    try:
        if len(natural_villages) < 2:
            return relations

        # Compute pairwise direction relations between villages
        for i, v1 in enumerate(natural_villages):
            for j, v2 in enumerate(natural_villages):
                if i >= j:
                    continue

                dx = v2.center[0] - v1.center[0]  # longitude diff
                dy = v2.center[1] - v1.center[1]  # latitude diff

                # Determine direction
                if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                    continue

                # Use angle to determine primary direction
                import math
                angle = math.degrees(math.atan2(dy, dx))

                if -22.5 <= angle < 22.5:
                    direction = "east_of"
                elif 22.5 <= angle < 67.5:
                    direction = "north_of"  # NE -> primarily north
                elif 67.5 <= angle < 112.5:
                    direction = "north_of"
                elif 112.5 <= angle < 157.5:
                    direction = "north_of"  # NW -> primarily north
                elif angle >= 157.5 or angle < -157.5:
                    direction = "west_of"
                elif -157.5 <= angle < -112.5:
                    direction = "south_of"  # SW -> primarily south
                elif -112.5 <= angle < -67.5:
                    direction = "south_of"
                elif -67.5 <= angle < -22.5:
                    direction = "south_of"  # SE -> primarily south
                else:
                    direction = "near"

                relations.append(SpatialRelation(
                    subject=v2.name,
                    relation=direction,
                    object=v1.name,
                    confidence=0.9,
                    source="geometry_computed",
                ))

                # Add reverse relation
                reverse_map = {
                    "east_of": "west_of",
                    "west_of": "east_of",
                    "north_of": "south_of",
                    "south_of": "north_of",
                    "near": "near",
                }
                relations.append(SpatialRelation(
                    subject=v1.name,
                    relation=reverse_map.get(direction, "near"),
                    object=v2.name,
                    confidence=0.9,
                    source="geometry_computed",
                ))

        # Add containment relations: villages contained by construction boundary
        for v in natural_villages:
            relations.append(SpatialRelation(
                subject="construction_boundary",
                relation="contains",
                object=v.name,
                confidence=1.0,
                source="geometry_computed",
            ))

    except Exception as e:
        logger.warning("[SpatialContext] Spatial relations failed: %s", e)

    return relations


def _compute_constraint_summary(gis_data: Dict[str, Any]) -> List[ConstraintSummary]:
    """Compute constraint summary from protection zone layers."""
    summaries = []

    try:
        # Farmland protection
        farmland = gis_data.get("farmland_protection_geojson")
        if farmland:
            area = _compute_total_area(farmland)
            summaries.append(ConstraintSummary(
                zone_type="farmland_protection",
                rule="禁止建设",
                area_ha=round(area, 2),
                geometry_type="MultiPolygon",
                overlaps_with=[],
            ))

        # Ecological protection
        ecological = gis_data.get("ecological_protection_geojson")
        if ecological:
            area = _compute_total_area(ecological)
            summaries.append(ConstraintSummary(
                zone_type="ecological_protection",
                rule="禁止建设",
                area_ha=round(area, 2),
                geometry_type="MultiPolygon",
                overlaps_with=["farmland_protection"] if farmland else [],
            ))

        # Historical protection
        historical = gis_data.get("historical_protection_geojson")
        if historical:
            area = _compute_total_area(historical)
            summaries.append(ConstraintSummary(
                zone_type="historical_protection",
                rule="限制建设",
                area_ha=round(area, 2),
                geometry_type="MultiPolygon",
                overlaps_with=[],
            ))

    except Exception as e:
        logger.warning("[SpatialContext] Constraint summary failed: %s", e)

    return summaries


def _compute_zone_adjacency(landuse_geojson: Dict[str, Any]) -> Dict[str, List[str]]:
    """Compute zone adjacency matrix summary from landuse data."""
    try:
        from app.utils.geojson_utils import geojson_to_geodataframe
        from app.modules.gis.schema import get_zone_type_for_dlbm

        gdf = geojson_to_geodataframe(landuse_geojson)
        if gdf is None or gdf.empty:
            return {}

        dlbm_col = _find_column(gdf, ["DLBM", "dlbm"])
        if not dlbm_col:
            return {}

        # Add zone_type column
        gdf["zone_type"] = gdf[dlbm_col].astype(str).str.strip().apply(get_zone_type_for_dlbm)

        # Build adjacency from touching parcels
        adjacency: Dict[str, set] = {}
        for i in range(len(gdf)):
            zone_i = gdf.iloc[i]["zone_type"]
            if not zone_i:
                continue
            if zone_i not in adjacency:
                adjacency[zone_i] = set()

            geom_i = gdf.iloc[i].geometry
            # Check neighbors (limit to nearby parcels for performance)
            for j in range(max(0, i - 50), min(len(gdf), i + 50)):
                if i == j:
                    continue
                zone_j = gdf.iloc[j]["zone_type"]
                if not zone_j or zone_j == zone_i:
                    continue
                geom_j = gdf.iloc[j].geometry
                if geom_i.touches(geom_j) or geom_i.distance(geom_j) < 0.0001:
                    adjacency[zone_i].add(zone_j)

        return {k: sorted(v) for k, v in adjacency.items() if v}
    except Exception as e:
        logger.warning("[SpatialContext] Zone adjacency failed: %s", e)
        return {}


# ── Utility functions ────────────────────────────────────────────────


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


def _find_column(gdf, candidates: List[str]) -> Optional[str]:
    """Find first matching column name in GeoDataFrame."""
    for col in candidates:
        if col in gdf.columns:
            return col
    return None


def _load_place_aliases() -> Dict[str, str]:
    """Load place name aliases from YAML config.

    Returns:
        Dict mapping alias_name -> canonical_name or coordinates.
    """
    try:
        from pathlib import Path
        import yaml

        aliases_path = Path("data/gis/place_aliases.yaml")
        if not aliases_path.exists():
            return {}

        with open(aliases_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data
    except Exception as e:
        logger.debug("[SpatialContext] Place aliases not loaded: %s", e)
        return {}


# ── Annotation extraction (precise coordinates from GIS) ─────────────


def _extract_facility_anchors(annotation_geojson: Dict[str, Any]) -> List[FacilityAnchor]:
    """Extract facility anchors from annotation.geojson.

    Filters for 现状设施点 features, maps annotation text to facility type,
    and extracts precise WGS84 coordinates.
    """
    anchors = []
    features = annotation_geojson.get("features", [])

    for ft in features:
        props = ft.get("properties", {})
        category = props.get("分类", props.get("category", ""))

        if category != "现状设施点":
            continue

        text = props.get("注记", props.get("text", ""))
        if not text:
            continue

        # Map annotation text to facility type
        facility_type = ANNOTATION_LABEL_TYPE_MAP.get(text, "公共服务")

        # Extract coordinates
        geometry = ft.get("geometry", {})
        coords = geometry.get("coordinates", [0, 0])
        if not coords or len(coords) < 2:
            continue

        center = (round(float(coords[0]), 6), round(float(coords[1]), 6))

        anchors.append(FacilityAnchor(
            name=text,
            facility_type=facility_type,
            category=category,
            center=center,
        ))

    if anchors:
        logger.info(
            "[SpatialContext] Extracted %d facility anchors from annotations", len(anchors)
        )
    return anchors


def _extract_annotation_villages(annotation_geojson: Dict[str, Any]) -> List[NaturalVillageAnchor]:
    """Extract village name anchors from annotation.geojson.

    Filters for 村名 features, extracts precise WGS84 coordinates.
    These replace the cluster-derived VillageGroup_N names from step 4.
    """
    anchors = []
    features = annotation_geojson.get("features", [])

    for ft in features:
        props = ft.get("properties", {})
        category = props.get("分类", props.get("category", ""))

        if category != "村名":
            continue

        text = props.get("注记", props.get("text", ""))
        if not text:
            continue

        # Extract coordinates
        geometry = ft.get("geometry", {})
        coords = geometry.get("coordinates", [0, 0])
        if not coords or len(coords) < 2:
            continue

        center = (round(float(coords[0]), 6), round(float(coords[1]), 6))

        anchors.append(NaturalVillageAnchor(
            name=text,
            center=center,
            parcel_ids=[],  # Populated in _merge_annotation_villages
            dominant_landuse="居住用地",
            adjacent_to=[],
        ))

    if anchors:
        logger.info(
            "[SpatialContext] Extracted %d village name anchors from annotations", len(anchors)
        )
    return anchors


def _merge_annotation_villages(
    ctx: SpatialContext,
    landuse_geojson: Optional[Dict[str, Any]] = None,
) -> None:
    """Merge annotation village names into natural_villages.

    Strategy:
      1. For each annotation village, find the nearest cluster in natural_villages
      2. Replace cluster name (VillageGroup_N) with annotation name (八社村)
      3. Update center to annotation's precise coordinate
      4. Keep cluster's parcel_ids (which came from GIS analysis)
      5. Any unmatched annotation villages are appended
    """
    if not ctx.annotation_villages:
        return

    used_cluster_indices = set()

    for ann_v in ctx.annotation_villages:
        ann_lon, ann_lat = ann_v.center

        # Find nearest cluster within 300m (approx 0.003 degrees at 24°N)
        best_idx = None
        best_dist = float("inf")
        for i, nv in enumerate(ctx.natural_villages):
            if i in used_cluster_indices:
                continue
            nv_lon, nv_lat = nv.center
            dist = ((ann_lon - nv_lon) ** 2 + (ann_lat - nv_lat) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_idx = i

        if best_idx is not None and best_dist < 0.003:
            # Merge: replace cluster name with annotation name
            cluster = ctx.natural_villages[best_idx]
            ctx.natural_villages[best_idx] = NaturalVillageAnchor(
                name=ann_v.name,            # Use annotation name (e.g. "八社村")
                center=ann_v.center,        # Use annotation's precise coordinate
                parcel_ids=cluster.parcel_ids,  # Keep cluster's parcel analysis
                dominant_landuse=cluster.dominant_landuse,
                adjacent_to=cluster.adjacent_to,
            )
            used_cluster_indices.add(best_idx)
        else:
            # No nearby cluster — find nearby parcels from landuse
            parcel_ids = []
            if landuse_geojson:
                parcel_ids = _find_parcels_near_point(
                    landuse_geojson, ann_v.center, radius_m=200
                )
            # Append as new village
            ctx.natural_villages.append(NaturalVillageAnchor(
                name=ann_v.name,
                center=ann_v.center,
                parcel_ids=parcel_ids[:20],
                dominant_landuse="居住用地",
                adjacent_to=[],
            ))

    logger.info(
        "[SpatialContext] Merged %d annotation villages into %d natural_villages",
        len(ctx.annotation_villages), len(ctx.natural_villages),
    )


def _find_parcels_near_point(
    landuse_geojson: Dict[str, Any],
    center: Tuple[float, float],
    radius_m: float = 200,
) -> List[str]:
    """Find parcel BSMs near a WGS84 point within radius_m.

    Used when annotation village has no matching cluster in natural_villages.
    """
    parcel_ids = []
    try:
        from shapely.geometry import Point

        ref_point = Point(center[0], center[1])
        # Approximate degree radius at ~24°N: 1° ≈ 111km * cos(24°) ≈ 101km
        radius_deg = radius_m / 101000.0

        for ft in landuse_geojson.get("features", []):
            geom = ft.get("geometry", {})
            if not geom:
                continue
            from shapely.geometry import shape
            s = shape(geom)
            if s.is_empty:
                continue
            if ref_point.distance(s.centroid) < radius_deg:
                bsm = str(ft.get("properties", {}).get("BSM", "")).strip()
                if bsm:
                    parcel_ids.append(bsm)
    except Exception as e:
        logger.debug("[SpatialContext] Parcel near-point lookup failed: %s", e)
    return parcel_ids


# ── Terrain profile (P2 reserved — DEM data not yet available) ─────


def _compute_terrain_profile(gis_data: Dict[str, Any]) -> Optional[TerrainProfile]:
    """Compute terrain profile from DEM analysis results (P2 reserved).

    When DEM data is available via TerrainAnalyzer, this extracts the
    slope/aspect/suitability area percentage breakdowns and wraps them
    in a TerrainProfile for LLM prompt injection.

    Current behavior: returns None when no terrain analysis data exists,
    allowing the pipeline to function normally without DEM.

    Args:
        gis_data: Full GIS data dict — may contain "terrain_analysis" key
                  with a TerrainAnalysisResult value.

    Returns:
        TerrainProfile if terrain analysis data is available, None otherwise.
    """
    terrain_analysis = gis_data.get("terrain_analysis") if gis_data else None
    if terrain_analysis is None:
        return None

    try:
        from app.modules.gis.schema.raster_types import TerrainAnalysisResult

        # Accept both typed TerrainAnalysisResult and dict
        if isinstance(terrain_analysis, TerrainAnalysisResult):
            profile = TerrainProfile(
                slope_area_pct=dict(getattr(terrain_analysis, "slope_area_pct", {}) or {}),
                aspect_area_pct=dict(getattr(terrain_analysis, "aspect_area_pct", {}) or {}),
                suitability_area_pct=dict(getattr(terrain_analysis, "suitability_area_pct", {}) or {}),
            )
        elif isinstance(terrain_analysis, dict):
            profile = TerrainProfile(
                slope_area_pct=dict(terrain_analysis.get("slope_area_pct", {}) or {}),
                aspect_area_pct=dict(terrain_analysis.get("aspect_area_pct", {}) or {}),
                suitability_area_pct=dict(terrain_analysis.get("suitability_area_pct", {}) or {}),
            )
        else:
            return None

        has_data = any([profile.slope_area_pct, profile.aspect_area_pct, profile.suitability_area_pct])
        if has_data:
            logger.info(
                "[SpatialContext] Terrain profile: %d slope classes, %d aspect classes, %d suitability classes",
                len(profile.slope_area_pct), len(profile.aspect_area_pct), len(profile.suitability_area_pct),
            )
            return profile

        return None
    except Exception as e:
        logger.debug("[SpatialContext] Terrain profile extraction skipped: %s", e)
        return None


__all__ = ["compute_spatial_context"]
