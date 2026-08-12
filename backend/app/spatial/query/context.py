"""Spatial context computation — ContextBlock-based spatial cognition cards.

[v4.3] Replaces monolithic SpatialContext with modular ContextBlock architecture.
Each _build_* generator produces one self-describing spatial cognition card.
compute_context_blocks() is the sole public entry point.

Consumers filter by ContextBlockType, sort by priority, truncate by token budget.
No raw GeoJSON dict traversal — direct typed attribute access on VillageBundle.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.utils.logger import get_logger
from app.contracts.spatial.context_contracts import (
    ConstraintSummary,
    ConstraintZoneAnchor,
    ContextBlock,
    ContextBlockType,
    FacilityAnchor,
    LanduseEntry,
    ResidentialClusterAnchor,
    SpatialRelation,
    TerrainProfile,
)
from app.data.model.canonical import VillageBundle
from app.data.model.spatial_types import ANNOTATION_LABEL_TYPE_MAP

from app.spatial.model.geometry import (
    _compute_centroid,
    _compute_total_area,
    _find_parcels_near_point,
)
from app.spatial.model.relations import (
    _compute_spatial_relations,
    _compute_zone_adjacency,
)

logger = get_logger(__name__)


# ── Generator registry ────────────────────────────────────────────────

_GENERATORS: Dict[ContextBlockType, Callable] = {}


def _register_generators() -> None:
    """Register all ContextBlock generators (module-level lazy init)."""
    if _GENERATORS:
        return
    _GENERATORS.update({
        ContextBlockType.VILLAGE_META: _build_village_meta,
        ContextBlockType.LANDUSE_DIST: _build_landuse_dist,
        ContextBlockType.RESIDENTIAL_CLUSTERS: _build_residential_clusters,
        ContextBlockType.SPATIAL_RELATIONS: _build_spatial_relations_block,
        ContextBlockType.CONSTRAINTS: _build_constraints,
        ContextBlockType.FACILITIES: _build_facilities,
        ContextBlockType.TERRAIN: _build_terrain,
        ContextBlockType.ZONE_ADJACENCY: _build_zone_adjacency_block,
    })


# ── Public API ─────────────────────────────────────────────────────────


def compute_context_blocks(
    bundle: VillageBundle,
    requested: Optional[List[ContextBlockType]] = None,
    max_token_budget: int = 1500,
) -> List[ContextBlock]:
    """Generate spatial cognition cards from a VillageBundle.

    Sole public entry point for spatial context. Returns a list of ContextBlock
    cards that downstream consumers filter, sort, and budget-trim.

    Args:
        bundle: VillageBundle with morphology groups populated.
        requested: Specific block types to generate (None = all).
        max_token_budget: Approximate token limit; blocks beyond this are trimmed.

    Returns:
        List of ContextBlock cards sorted by priority, trimmed to token budget.
    """
    _register_generators()

    if requested is None:
        requested = list(ContextBlockType)

    blocks: List[ContextBlock] = []
    for bt in requested:
        gen = _GENERATORS.get(bt)
        if gen is None:
            continue
        try:
            block = gen(bundle)
            if block is not None:
                blocks.append(block)
        except Exception as e:
            logger.warning("[ContextBlocks] Generator %s failed: %s", bt.value, e)

    blocks.sort(key=lambda b: b.priority)

    total = 0
    trimmed: List[ContextBlock] = []
    for b in blocks:
        # v4.8.1: CJK-aware token estimation (len/1.5 instead of len/4)
        text = b.to_markdown()
        cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        non_cjk = len(text) - cjk_count
        est = int(cjk_count + non_cjk / 4)
        if total + est > max_token_budget:
            break
        trimmed.append(b)
        total += est

    logger.info(
        "[ContextBlocks] Generated %d blocks (%d after token trim), token est=%d",
        len(blocks), len(trimmed), total,
    )
    return trimmed


# ── Block generators ───────────────────────────────────────────────────


def _build_village_meta(bundle: VillageBundle) -> ContextBlock:
    """Build village metadata block from bundle metadata and polygon data."""
    meta = bundle.metadata
    data: Dict[str, Any] = {
        "village_name": bundle.village_name or meta.village_name,
    }

    # Center from boundary
    boundary = bundle.boundary
    if boundary is not None and hasattr(boundary, "geometry") and boundary.geometry:
        try:
            from app.data.model.canonical import _spatial_feature_to_geojson
            feat = _spatial_feature_to_geojson(boundary)
            fc = {"type": "FeatureCollection", "features": [feat]}
            center = _compute_centroid(fc)
            if center:
                data["center"] = list(center)
        except Exception:
            pass

    # Areas
    data["parcel_count"] = bundle.parcel_count
    data["total_area_ha"] = round(bundle.total_area_ha, 2)

    # Construction boundary area
    if bundle.polygons.get("construction_zone"):
        from app.data.model.canonical import _features_to_fc
        construction_fc = _features_to_fc(bundle.polygons.get("construction_zone"))
        data["construction_boundary_ha"] = round(_compute_total_area(construction_fc), 2)
    else:
        data["construction_boundary_ha"] = 0.0

    return ContextBlock(
        block_type=ContextBlockType.VILLAGE_META,
        title=f"村庄概况: {data.get('village_name', '')}",
        data=data,
        source="VillageBundle.metadata + polygons",
        priority=5,
    )


def _build_landuse_dist(bundle: VillageBundle) -> ContextBlock:
    """Build land-use distribution block from typed parcels.

    Groups by p.dlbm (direct attribute access, no _find_column).
    """
    from collections import defaultdict

    parcels = bundle.polygons.get("landuse_current")
    if not parcels:
        return ContextBlock(
            block_type=ContextBlockType.LANDUSE_DIST,
            title="用地分布",
            data={"entries": [], "note": "无现状用地数据"},
            source="VillageBundle.polygons.landuse_current",
            priority=10,
        )

    groups: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "area_ha": 0.0, "zone_type": ""}
    )
    for p in parcels:
        dlbm = str(p.dlbm).strip()
        if not dlbm:
            continue
        groups[dlbm]["count"] += 1
        area = p.area_sqm / 10000.0
        groups[dlbm]["area_ha"] += area
        if not groups[dlbm]["zone_type"]:
            groups[dlbm]["zone_type"] = p.zone_type

    # Enrich with encoding names
    try:
        from app.data.encodings.code_sets import DLBM_TO_DLMC
    except ImportError:
        DLBM_TO_DLMC = {}

    entries = sorted(
        [
            {
                "dlbm": k,
                "name": DLBM_TO_DLMC.get(k, k),
                "count": v["count"],
                "area_ha": round(v["area_ha"], 2),
                "zone_type": v["zone_type"],
            }
            for k, v in groups.items()
        ],
        key=lambda e: e["area_ha"],
        reverse=True,
    )

    return ContextBlock(
        block_type=ContextBlockType.LANDUSE_DIST,
        title="用地分布",
        data={"entries": entries},
        source="VillageBundle.polygons.landuse_current",
        priority=10,
    )


def _build_residential_clusters(bundle: VillageBundle) -> ContextBlock:
    """Build residential cluster anchors by clustering residential parcels (居民点).

    Uses typed CurrentLandUseParcel list with p.dlbm/p.geometry/p.bsm.
    Annotation villages (from points.annotations_current) are merged for naming.
    """
    parcels = bundle.polygons.get("landuse_current")
    if not parcels:
        return ContextBlock(
            block_type=ContextBlockType.RESIDENTIAL_CLUSTERS,
            title="居民点",
            data={"villages": [], "note": "无居住用地数据"},
            source="VillageBundle.polygons.landuse_current",
            priority=20,
        )

    try:
        from shapely.geometry import shape
        from shapely.ops import unary_union
        from app.data.encodings.code_sets import get_dlbms_for_zone_type

        _RESIDENTIAL_DLBMS = set(get_dlbms_for_zone_type("居住用地"))

        # Build GeoDataFrame from typed parcels for spatial clustering
        import geopandas as gpd
        from app.utils.crs_engine import project_to_metric

        geoms = []
        dlbms = []
        bsms = []
        for p in parcels:
            dlbm = str(p.dlbm).strip()
            if dlbm not in _RESIDENTIAL_DLBMS:
                continue
            geom = p.geometry
            if geom is None:
                continue
            try:
                geoms.append(shape(geom))
                dlbms.append(dlbm)
                bsms.append(str(p.bsm).strip())
            except Exception:
                continue

        if not geoms:
            return ContextBlock(
                block_type=ContextBlockType.RESIDENTIAL_CLUSTERS,
                title="居民点",
                data={"villages": [], "note": "无居住用地"},
                source="VillageBundle.polygons.landuse_current",
                priority=20,
            )

        gdf = gpd.GeoDataFrame(
            {"dlbm": dlbms, "bsm": bsms, "geometry": geoms}, crs="EPSG:4326"
        )

        # Project to metric for distance-based clustering
        gdf_metric = project_to_metric(gdf)
        if gdf_metric is None or gdf_metric.empty:
            return ContextBlock(
                block_type=ContextBlockType.RESIDENTIAL_CLUSTERS,
                title="居民点",
                data={"villages": [], "note": "投影失败"},
                source="VillageBundle.polygons.landuse_current",
                priority=20,
            )

        # Buffer and dissolve to find clusters
        buffers = gdf_metric.geometry.buffer(150)  # 150m buffer
        merged = unary_union(buffers.tolist())

        if merged.geom_type == "Polygon":
            components = [merged]
        elif merged.geom_type == "MultiPolygon":
            components = list(merged.geoms)
        else:
            return ContextBlock(
                block_type=ContextBlockType.RESIDENTIAL_CLUSTERS,
                title="居民点",
                data={"villages": [], "note": "无可聚类几何"},
                source="VillageBundle.polygons.landuse_current",
                priority=20,
            )

        # Extract annotation villages for naming
        annotation_villages = _extract_annotation_villages_from_typed(
            bundle.points.get("annotations_current")
        )

        anchors: List[ResidentialClusterAnchor] = []
        used_indices: set = set()

        for i, component in enumerate(components):
            mask = gdf_metric.geometry.centroid.within(component.buffer(10))
            cluster_gdf = gdf[mask]
            if cluster_gdf.empty:
                continue

            # WGS84 centroid
            wgs84_center = cluster_gdf.geometry.union_all().centroid
            center: tuple = (round(wgs84_center.x, 6), round(wgs84_center.y, 6))

            # Parcel IDs
            cluster_bsms = cluster_gdf["bsm"].tolist()
            parcel_ids = [b for b in cluster_bsms if b]

            # Dominant land use
            dominant = cluster_gdf["dlbm"].mode().iloc[0] if len(cluster_gdf) > 0 else ""

            # Try to match annotation village name
            name = f"VillageGroup_{i + 1}"
            for ann_v in annotation_villages:
                ann_idx = annotation_villages.index(ann_v)
                if ann_idx in used_indices:
                    continue
                ann_lon, ann_lat = ann_v.center
                dist = ((center[0] - ann_lon) ** 2 + (center[1] - ann_lat) ** 2) ** 0.5
                if dist < 0.003:  # ~300m at 24N
                    name = ann_v.name
                    center = ann_v.center  # Use annotation's precise coordinate
                    used_indices.add(ann_idx)
                    break

            # Adjacent non-residential zones (simplified)
            adjacent_zones: List[str] = []
            try:
                from app.data.encodings.code_sets import get_zone_type_for_dlbm
                non_res = gdf[~gdf["dlbm"].isin(_RESIDENTIAL_DLBMS)]
                if not non_res.empty:
                    non_res_metric = project_to_metric(non_res)
                    if non_res_metric is not None and not non_res_metric.empty:
                        nearby = non_res_metric[
                            non_res_metric.geometry.distance(component.boundary) < 100
                        ]
                        if not nearby.empty:
                            adjacent_zones = list(set(
                                get_zone_type_for_dlbm(str(d).strip())
                                for d in nearby["dlbm"].values
                            ))[:5]
            except Exception:
                pass

            anchors.append(ResidentialClusterAnchor(
                name=name,
                center=center,
                parcel_ids=parcel_ids[:20],
                dominant_landuse=dominant,
                adjacent_to=adjacent_zones,
            ))

        # Append unmatched annotation villages
        for ann_v in annotation_villages:
            ann_idx = annotation_villages.index(ann_v)
            if ann_idx in used_indices:
                continue
            # Find nearby parcels
            nearby_ids = _find_parcels_near_point(
                [p for p in parcels if str(p.dlbm).strip() in _RESIDENTIAL_DLBMS],
                ann_v.center,
                radius_m=200,
            )
            anchors.append(ResidentialClusterAnchor(
                name=ann_v.name,
                center=ann_v.center,
                parcel_ids=nearby_ids[:20],
                dominant_landuse="居住用地",
                adjacent_to=[],
            ))

        logger.info(
            "[ContextBlocks] Residential clusters: %d clusters + %d annotation-only",
            len([a for a in anchors if a.name.startswith("VillageGroup_")]),
            len([a for a in anchors if not a.name.startswith("VillageGroup_")]),
        )

        return ContextBlock(
            block_type=ContextBlockType.RESIDENTIAL_CLUSTERS,
            title="居民点",
            data={"villages": [
                {
                    "name": a.name,
                    "center": list(a.center),
                    "parcel_count": len(a.parcel_ids),
                    "dominant_landuse": a.dominant_landuse,
                    "adjacent_to": a.adjacent_to,
                }
                for a in anchors
            ]},
            units=anchors,
            source="VillageBundle.polygons.landuse_current + annotations",
            priority=20,
        )

    except Exception as e:
        logger.warning("[ContextBlocks] Residential cluster clustering failed: %s", e)
        return ContextBlock(
            block_type=ContextBlockType.RESIDENTIAL_CLUSTERS,
            title="居民点",
            data={"villages": [], "note": f"聚类失败: {e}"},
            source="VillageBundle.polygons.landuse_current",
            priority=20,
            confidence=0.0,
        )


def _build_spatial_relations_block(bundle: VillageBundle) -> Optional[ContextBlock]:
    """Build spatial relations block from residential cluster anchors (居民点).

    Must run AFTER _build_residential_clusters to get village anchors.
    Since generators are independent, we re-cluster internally.
    """
    # Get residential clusters by running the clustering (lightweight if already cached)
    villages_block = _build_residential_clusters(bundle)
    villages_data = villages_block.data.get("villages", [])
    if len(villages_data) < 2:
        return None

    # Convert dicts back to ResidentialClusterAnchor for relation computation
    anchors = [
        ResidentialClusterAnchor(
            name=v["name"],
            center=(v["center"][0], v["center"][1]),
            parcel_ids=[],  # not needed for relations
            dominant_landuse=v.get("dominant_landuse", ""),
            adjacent_to=v.get("adjacent_to", []),
        )
        for v in villages_data
    ]

    relations = _compute_spatial_relations(anchors)
    if not relations:
        return None

    return ContextBlock(
        block_type=ContextBlockType.SPATIAL_RELATIONS,
        title="空间关系",
        data={"relations": [
            {
                "subject": r.subject,
                "relation": r.relation,
                "object": r.object,
                "confidence": r.confidence,
            }
            for r in relations
        ]},
        source="residential_clusters -> _compute_spatial_relations",
        priority=30,
    )


def _build_constraints(bundle: VillageBundle) -> ContextBlock:
    """Build constraint summary block from protection/control polygon layers.

    Uses typed polygon lists directly — no raw GeoJSON dict traversal.
    """
    from app.utils.area_engine import calculate_area_ha
    from shapely.geometry import shape

    pg = bundle.polygons

    groups = [
        (pg.farmland_protection, "永久基本农田", "禁止建设"),
        (pg.ecological_redline, "生态保护红线", "禁止建设"),
        (pg.historical_protection, "历史文化保护", "限制建设"),
        (pg.cultivated_land_target, "耕地保护目标", "限制建设"),
        (pg.hazard_control_lines, "灾害防控", "限制建设"),
        (pg.flood_control_lines, "洪涝防控", "限制建设"),
        (pg.nature_reserves, "自然保护区", "禁止建设"),
    ]

    zones: List[Dict[str, Any]] = []
    for features, label, rule in groups:
        if not features:
            continue
        try:
            total = sum(calculate_area_ha(shape(f.geometry)) for f in features)
            zones.append({
                "type": label,
                "rule": rule,
                "area_ha": round(total, 2),
                "feature_count": len(features),
            })
        except Exception as e:
            logger.debug("[ContextBlocks] Constraint area calc failed for %s: %s", label, e)
            zones.append({
                "type": label,
                "rule": rule,
                "area_ha": 0.0,
                "feature_count": len(features),
                "note": "面积计算失败",
            })

    constraint_units = [
        ConstraintZoneAnchor(name=z["type"], zone_type=z["type"], rule=z["rule"],
                             area_ha=z["area_ha"], source="VillageBundle.polygons.constraint_polygons")
        for z in zones
    ]

    return ContextBlock(
        block_type=ContextBlockType.CONSTRAINTS,
        title="保护与约束边界",
        data={"zones": zones} if zones else {"zones": [], "note": "无约束数据"},
        units=constraint_units,
        source="VillageBundle.polygons (constraint_polygons)",
        priority=15,
    )


def _build_facilities(bundle: VillageBundle) -> ContextBlock:
    """Build facility anchors block from typed annotation/ facility features.

    Produces typed FacilityAnchor instances in block.units for isinstance dispatch.
    """
    anchors: List[Dict[str, Any]] = []
    units: List[FacilityAnchor] = []

    # Current facilities (typed FacilityAnchor data)
    for f in bundle.points.get("facilities_current"):
        name = f.facility_name
        ftype = f.facility_type
        geom = f.geometry
        center = [0.0, 0.0]
        if geom and isinstance(geom, dict):
            coords = geom.get("coordinates", [0, 0])
            if coords and len(coords) >= 2:
                center = [round(float(coords[0]), 6), round(float(coords[1]), 6)]
        if name:
            anchors.append({"name": name, "facility_type": ftype, "category": "现状设施点", "center": center})
            units.append(FacilityAnchor(name=name, facility_type=ftype, category="现状设施点",
                                        center=(center[0], center[1]), source="VillageBundle.points.facilities_current"))

    # Annotation-based facility extraction
    for a in bundle.points.get("annotations_current"):
        category = a.category
        if category != "现状设施点":
            continue
        text = a.text
        if not text:
            continue
        facility_type = ANNOTATION_LABEL_TYPE_MAP.get(text, "公共服务")
        geom = a.geometry
        center = [0.0, 0.0]
        if geom and isinstance(geom, dict):
            coords = geom.get("coordinates", [0, 0])
            if coords and len(coords) >= 2:
                center = [round(float(coords[0]), 6), round(float(coords[1]), 6)]
        anchors.append({"name": text, "facility_type": facility_type, "category": category, "center": center})
        units.append(FacilityAnchor(name=text, facility_type=facility_type, category=category,
                                    center=(center[0], center[1]), source="annotations_current"))

    if anchors:
        logger.info("[ContextBlocks] Extracted %d facility anchors", len(anchors))

    return ContextBlock(
        block_type=ContextBlockType.FACILITIES,
        title="设施锚点",
        data={"anchors": anchors} if anchors else {"anchors": [], "note": "无设施数据"},
        units=units,
        source="VillageBundle.points (facilities + annotations)",
        priority=25,
    )


def _build_terrain(bundle: VillageBundle) -> Optional[ContextBlock]:
    """Build terrain profile block from raster data (P2 reserved).

    Returns None when no DEM/elevation data is available.
    """
    rasters = bundle.rasters
    has_data = any([
        rasters.dem is not None,
        rasters.slope is not None,
        rasters.aspect is not None,
        rasters.suitability is not None,
    ])
    if not has_data:
        return None

    data: Dict[str, Any] = {}
    if rasters.slope is not None:
        data["slope"] = getattr(rasters.slope, "path", "available")
    if rasters.aspect is not None:
        data["aspect"] = getattr(rasters.aspect, "path", "available")
    if rasters.suitability is not None:
        data["suitability"] = getattr(rasters.suitability, "path", "available")
    if rasters.dem is not None:
        data["dem"] = getattr(rasters.dem, "path", "available")

    return ContextBlock(
        block_type=ContextBlockType.TERRAIN,
        title="地形数据",
        data=data if data else {"note": "栅格数据已加载但无可提取剖面"},
        source="VillageBundle.rasters",
        priority=40,
    )


def _build_zone_adjacency_block(bundle: VillageBundle) -> ContextBlock:
    """Build zone adjacency block from typed land-use parcels.

    Uses typed CurrentLandUseParcel list with p.dlbm + shape(p.geometry).
    """
    parcels = bundle.polygons.get("landuse_current")
    if not parcels:
        return ContextBlock(
            block_type=ContextBlockType.ZONE_ADJACENCY,
            title="分区邻接",
            data={"adjacency": {}, "note": "无现状用地数据"},
            source="VillageBundle.polygons.landuse_current",
            priority=35,
        )

    adjacency = _compute_zone_adjacency(parcels)
    return ContextBlock(
        block_type=ContextBlockType.ZONE_ADJACENCY,
        title="分区邻接",
        data={"adjacency": adjacency} if adjacency else {"adjacency": {}, "note": "无邻接数据"},
        source="VillageBundle.polygons.landuse_current → _compute_zone_adjacency",
        priority=35,
    )


# ── Annotation extraction helpers ──────────────────────────────────────


def _extract_annotation_villages_from_typed(
    annotations: List[Any],
) -> List[ResidentialClusterAnchor]:
    """Extract village name anchors from typed CurrentAnnotation list.

    Uses a.category and a.text (direct attribute access) instead of
    hardcoded Chinese property keys.
    """
    anchors: List[ResidentialClusterAnchor] = []
    for a in annotations:
        category = a.category
        if category != "村名":
            continue
        text = a.text
        if not text:
            continue
        geom = a.geometry
        if geom and isinstance(geom, dict):
            coords = geom.get("coordinates", [0, 0])
            if coords and len(coords) >= 2:
                center = (round(float(coords[0]), 6), round(float(coords[1]), 6))
                anchors.append(ResidentialClusterAnchor(
                    name=text,
                    center=center,
                ))
    if anchors:
        logger.info("[ContextBlocks] Extracted %d village name anchors from annotations", len(anchors))
    return anchors


def _load_place_aliases() -> Dict[str, str]:
    """Load place name aliases from YAML config."""
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
        logger.debug("[ContextBlocks] Place aliases not loaded: %s", e)
        return {}


__all__ = ["compute_context_blocks"]
