"""build_kg / query_kg tools — RDF knowledge graph construction and SPARQL query.

Uses KGManager for process-level Layer 1 caching and session management.
No global _kg_instance — KG instances managed via KGManager side-channel.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger
from app.tools.helpers import make_result, to_tool_message

logger = get_logger(__name__)


@tool
def build_knowledge_graph(
    reports: Annotated[Dict[str, Dict[str, Any]], InjectedState("reports")],
    gis_data: Annotated[Dict[str, Optional[Dict[str, Any]]], InjectedState("gis_data")],
    village_name: Annotated[str, InjectedState("village_name")],
    session_id: Annotated[str, InjectedState("session_id")],
    intent: Annotated[Optional[Dict[str, Any]], InjectedState("intent")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
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
    bundle = gis_data.pop("_bundle", None) if gis_data else None
    blocks = gis_data.pop("_context_blocks", None) if gis_data else None
    parcel_relations = gis_data.pop("_parcel_relations", None) if gis_data else None

    manager = get_kg_manager()
    landuse_geojson = gis_data.get("landuse_current_geojson") if gis_data else None

    if bundle is not None and blocks is not None:
        kg, cache_hit = manager.get_or_build_layer1(
            village_name=village_name,
            bundle=bundle,
            context_blocks=blocks,
            parcel_relations=parcel_relations,
        )
    else:
        # Legacy fallback (will be removed)
        cache_key = compute_layer1_cache_key(village_name, landuse_geojson)
        cache_key_str = str(cache_key) if cache_key else ""
        kg, cache_hit = manager.get_or_build_layer1(
            village_name=village_name,
            landuse_geojson=landuse_geojson,
            gis_data=gis_data,
        )

    if cache_hit:
        logger.info("[KG] Layer 1 cache HIT")
    else:
        logger.info("[KG] Layer 1 built fresh")

    # Phase 4: Add spatial elements (protection zones with within_zone, control lines, etc.)
    # These establish spatial containment relations needed for downstream queries
    # (get_protected_parcels_detail, get_three_lines with area targets, etc.)
    try:
        kg.add_protection_zones(gis_data)
    except Exception:
        pass
    try:
        kg.add_control_lines(gis_data)
    except Exception:
        pass
    try:
        kg.add_planning_elements(gis_data)
    except Exception:
        pass
    try:
        kg.add_natural_features(gis_data)
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
        adj = kg.get_adjacency_map() if hasattr(kg, "get_adjacency_map") else {}
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
        kg_constraint_coverage = kg.get_constraint_coverage()
    except Exception:
        pass
    try:
        kg_village_anchors = query_kg(kg, "get_village_anchors")
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

    return Command(update={
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
        "messages": [to_tool_message(make_result(True, data={
            "triple_count": kg.get_triple_count(),
            "constraint_count": len(constraints),
            "cache_hit": cache_hit,
            "expanded_queries": {
                "constraint_coverage": len(kg_constraint_coverage),
                "village_anchors": len(kg_village_anchors),
                "vne_classes": len(kg_vne_summary),
            },
        }), tool_call_id)],
    })


@tool
def query_knowledge_graph(
    template_name: str,
    session_id: Annotated[str, InjectedState("session_id")],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
    **params,
) -> Command:
    """Query the knowledge graph using a SPARQL template.

    Available templates: get_constraint_by_field, get_zones_by_type,
    get_parcels_in_zone, get_area_summary.

    Args:
        template_name: Query template to use.
        **params: Template-specific parameters (e.g. field_name, zone_type).
    """
    from app.modules.kg.manager import get_kg_manager

    manager = get_kg_manager()
    kg = manager.get_session_kg(session_id)

    if kg is None:
        return Command(update={
            "messages": [to_tool_message(
                make_result(False, error="KG not built — call build_knowledge_graph first"),
                tool_call_id,
            )],
        })

    # Use session-scoped query cache
    query_result = manager.query_with_cache(
        session_id, kg, template_name, **params
    )
    result = make_result(True, data={
        "template": template_name,
        "params": params,
        "results": query_result,
    })
    return Command(update={
        "messages": [to_tool_message(result, tool_call_id)],
    })
