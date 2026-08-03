"""Application service for constructing the session planning knowledge graph.

Uses KGManager for process-level Layer 1 caching and session management.
No global _kg_instance — KG instances managed via KGManager side-channel.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


def build_knowledge_graph_data(
    reports: Dict[str, Dict[str, Any]],
    gis_data: Dict[str, Optional[Dict[str, Any]]],
    village_name: str,
    session_id: str,
    intent: Optional[Any] = None,
    bundle: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build knowledge graph from planning intent + land use data. Call once.

    Data auto-injected from state — no arguments needed.

    Layer 1 (static: parcels, adjacency, VNE, infrastructure) is cached
    process-wide by KGManager — repeated builds for the same village skip
    the expensive _add_spatial_relations step.
    """
    from app.modules.kg.manager import get_kg_manager, compute_layer1_cache_key
    from app.modules.kg import PlanningKG
    from app.modules.kg.queries import query_kg

    # [v4.4] Prefer bundle+blocks path, fallback to legacy
    gis_payload = dict(gis_data or {})
    bundle = bundle or gis_payload.pop("_bundle", None)
    gis_payload.pop("_context_blocks", None)
    parcel_relations = gis_payload.pop("_parcel_relations", None)

    manager = get_kg_manager()

    if bundle is None:
        from app.modules.data.catalog.catalog import _merge_geojson_into_bundle
        from app.modules.schema.types.canonical import VillageBundle, VillageMetadata

        bundle = VillageBundle(
            village_name=village_name,
            metadata=VillageMetadata(village_name=village_name),
        )
        raw_layer_map = {
            "boundary_geojson": "boundary",
            "landuse_current_geojson": "landuse_current",
            "road_geojson": "current_road",
            "water_geojson": "water",
            "annotation_geojson": "current_annotation",
            "farmland_protection_geojson": "farmland_protection",
            "ecological_protection_geojson": "ecological_protection",
            "historical_protection_geojson": "historical_protection",
            "construction_zone_geojson": "conditional_construction_zone",
        }
        merged = 0
        for data_key, layer_type in raw_layer_map.items():
            geojson = gis_payload.get(data_key)
            if isinstance(geojson, dict):
                merged += _merge_geojson_into_bundle(bundle, layer_type, geojson)
        if not merged:
            raise ValueError("KG build requires a typed GIS bundle or GIS input layers")

    # Compute cache key for state reporting (typed parcels only)
    typed_parcels = bundle.polygons.get("landuse_current") if bundle else None
    cache_key = compute_layer1_cache_key(village_name, typed_parcels)
    cache_key_str = str(cache_key) if cache_key else ""

    kg, cache_hit = manager.get_or_build_layer1(
        village_name=village_name,
        bundle=bundle,
        parcel_relations=parcel_relations,
    )

    if cache_hit:
        logger.info("[KG] Layer 1 cache HIT")
    else:
        logger.info("[KG] Layer 1 built fresh")

    # Phase 4: Add spatial elements (protection zones with within_zone, control lines, etc.)
    # These establish spatial containment relations needed for downstream queries
    # (get_protected_parcels_detail, get_three_lines with area targets, etc.)
    try:
        kg.add_protection_zones(gis_payload)
    except Exception:
        pass
    try:
        kg.add_control_lines(gis_payload)
    except Exception:
        pass
    try:
        kg.add_planning_elements(gis_payload)
    except Exception:
        pass
    try:
        kg.add_natural_features(gis_payload)
    except Exception:
        pass

    # Register session KG
    manager.register_session(session_id, kg)

    # Pre-compute downstream-queryable results
    turtle = kg.to_turtle()
    constraints = kg.get_constraints()

    kg_adjacency_map: Dict[str, Any] = {}
    kg_zone_restrictions: Dict[str, Any] = {}
    kg_parcel_count_by_zone: List[Dict[str, Any]] = []
    kg_protected_parcels: Dict[str, Any] = {}

    try:
        adj = kg.get_adjacency_map()
        kg_adjacency_map = {k: list(v) for k, v in adj.items()} if adj else {}
    except Exception:
        pass
    try:
        restrictions = query_kg(kg, "get_zone_restrictions")
        kg_zone_restrictions = {"results": restrictions} if restrictions else {}
    except Exception:
        pass
    try:
        kg_parcel_count_by_zone = query_kg(kg, "count_by_zone_type")
    except Exception:
        pass
    try:
        kg_protected_parcels = {"results": query_kg(kg, "check_protected_parcels")}
    except Exception:
        pass

    # Phase 5: expanded queries — 三区三线 / VNE / 村锚点 / 保护详情
    kg_constraint_coverage: List[Dict[str, Any]] = []
    kg_village_anchors: List[Dict[str, Any]] = []
    kg_vne_summary: List[Dict[str, Any]] = []
    kg_count_by_planning_zone: List[Dict[str, Any]] = []

    try:
        from app.modules.kg.queries.sparql import get_constraint_coverage
        kg_constraint_coverage = get_constraint_coverage(kg)
    except Exception:
        pass
    try:
        kg_village_anchors = query_kg(kg, "get_village_anchors")
        # v5.0 谓词迁移：geo:hasCentroid + geo:asWKT "POINT(lon lat)"，
        # 解析 WKT 附加 lon/lat 供下游消费。
        for _a in kg_village_anchors:
            _wkt = _a.get("wkt") or ""
            _m = re.findall(r"[-+]?\d*\.?\d+", _wkt)
            if len(_m) >= 2:
                _a["lon"] = _m[0]
                _a["lat"] = _m[1]
    except Exception:
        pass
    try:
        kg_vne_summary = query_kg(kg, "count_by_vne")
    except Exception:
        pass
    try:
        kg_count_by_planning_zone = query_kg(kg, "count_by_planning_zone")
    except Exception:
        pass

    logger.info(
        "[KG] Expanded queries: %d parcels with constraint coverage, "
        "%d village anchors, %d VNE classes",
        len(kg_constraint_coverage), len(kg_village_anchors), len(kg_vne_summary),
    )

    return {
        "kg_turtle": turtle,
        "kg_constraints": constraints,
        "kg_adjacency_map": kg_adjacency_map,
        "kg_zone_restrictions": kg_zone_restrictions,
        "kg_session_ref": session_id,
        "kg_layer1_cache_key": cache_key_str,
        "kg_version": 1,
        "kg_parcel_count_by_zone": kg_parcel_count_by_zone,
        "kg_protected_parcels": kg_protected_parcels,
        "kg_protected_parcels_detail": kg_constraint_coverage,
        "kg_three_zones": [],
        "kg_three_lines": [],
        "kg_village_anchors": kg_village_anchors,
        "kg_vne_summary": kg_vne_summary,
        "kg_count_by_planning_zone": kg_count_by_planning_zone,
        "kg_build_metrics": {
            "triple_count": kg.get_triple_count(),
            "constraint_count": len(constraints),
            "cache_hit": cache_hit,
            "expanded_queries": {
                "constraint_coverage": len(kg_constraint_coverage),
                "village_anchors": len(kg_village_anchors),
                "vne_classes": len(kg_vne_summary),
            },
        },
    }


__all__ = ["build_knowledge_graph_data"]
