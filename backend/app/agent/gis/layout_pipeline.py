"""GIS LAYOUT pipeline — unified StateGraph with deterministic skeleton + ReAct adaptivity.

Architecture (LangGraph best practices):
  - Single StateGraph with GISPipelineState (Pydantic BaseModel)
  - Deterministic skeleton: fetch → build_kg → parse → write_kg_l3 → execute → export → render
  - ReAct subgraph in execute for adaptive strategy decisions
  - Worker-Evaluator retry loop: validate → fail? → feedback → retry (max 3 rounds)

References:
  [1] LangGraph StateGraph with Pydantic BaseModel state
  [2] LangGraph Worker-Evaluator pattern with Command routing
  [3] LangGraph subgraph state mapping pattern
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import StateGraph, END, START

from .state import GISPipelineState, GISPipelineInput, GISPipelineOutput
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Node implementations ──────────────────────────────────────────────


async def _fetch_gis_data_node(state: GISPipelineState) -> dict:
    """Fetch GIS data via DataCatalog (schema-driven, single path)."""
    from app.modules.data.catalog.catalog import DataCatalog

    village_name = state.village_name

    if not village_name:
        logger.info("[Pipeline:fetch] No village name — skipping data fetch")
        return {}

    try:
        catalog = DataCatalog()
        bundle = catalog.load_village_bundle(village_name)
        raw = bundle.to_geojson_dict()
        logger.info(
            "[Pipeline:fetch] %d parcels, %d roads, %d annotations",
            bundle.parcel_count,
            len(bundle.lines.get("roads_current")) + len(bundle.lines.get("roads_planned")),
            len(bundle.points.get("annotations_current")) + len(bundle.points.get("annotations_planned")),
        )
        return {"gis_bundle": bundle, "gis_data": raw}
    except Exception as e:
        logger.warning("[Pipeline:fetch] Fetch failed: %s", e)
        return {"gis_data": {}}


async def _build_kg_node(state: GISPipelineState) -> dict:
    """Build Layer 1+2 KG from GIS bundle data.

    Uses KGManager for Layer 1 caching — same village + landuse skips
    expensive _add_spatial_relations rebuild.

    Pre-computes adjacency map, zone restrictions, parcel counts, and
    protected parcels for downstream tools.
    """
    from app.tools.gis.kg import build_knowledge_graph

    try:
        result = await build_knowledge_graph.ainvoke({})
        if not isinstance(result, dict):
            return {}

        kg_turtle = result.get("kg_turtle", "")
        kg_constraints = result.get("kg_constraints", [])
        kg_adjacency_map = result.get("kg_adjacency_map", {})
        kg_zone_restrictions = result.get("kg_zone_restrictions", {})
        kg_session_ref = result.get("kg_session_ref", "")
        kg_layer1_cache_key = result.get("kg_layer1_cache_key", "")
        kg_version = result.get("kg_version", 0)
        kg_parcel_count_by_zone = result.get("kg_parcel_count_by_zone", [])
        kg_protected_parcels = result.get("kg_protected_parcels", {})
        # Phase 5: expanded KG query results
        kg_protected_parcels_detail = result.get("kg_protected_parcels_detail", [])
        kg_three_zones = result.get("kg_three_zones", [])
        kg_three_lines = result.get("kg_three_lines", [])
        kg_village_anchors = result.get("kg_village_anchors", [])
        kg_vne_summary = result.get("kg_vne_summary", [])
        kg_count_by_planning_zone = result.get("kg_count_by_planning_zone", [])

        logger.info(
            "[Pipeline:kg] KG built: %d triples, %d constraints, %d adjacency, "
            "%d protected_detail, %d three_zones, %d three_lines, %d anchors, %d VNE",
            len(kg_turtle.split("\n")) if kg_turtle else 0,
            len(kg_constraints),
            len(kg_adjacency_map),
            len(kg_protected_parcels_detail),
            len(kg_three_zones),
            len(kg_three_lines),
            len(kg_village_anchors),
            len(kg_vne_summary),
        )
        return {
            "kg_turtle": kg_turtle,
            "kg_constraints": kg_constraints,
            "kg_adjacency_map": kg_adjacency_map,
            "kg_zone_restrictions": kg_zone_restrictions,
            "kg_session_ref": kg_session_ref,
            "kg_layer1_cache_key": kg_layer1_cache_key,
            "kg_version": kg_version,
            "kg_parcel_count_by_zone": kg_parcel_count_by_zone,
            "kg_protected_parcels": kg_protected_parcels,
            "kg_protected_parcels_detail": kg_protected_parcels_detail,
            "kg_three_zones": kg_three_zones,
            "kg_three_lines": kg_three_lines,
            "kg_village_anchors": kg_village_anchors,
            "kg_vne_summary": kg_vne_summary,
            "kg_count_by_planning_zone": kg_count_by_planning_zone,
        }
    except Exception as e:
        logger.error("[Pipeline:kg] KG build failed: %s", e)
        return {}


async def _parse_intent_node(state: GISPipelineState) -> dict:
    """Parse planning text via PARSE Agent subgraph.

    Runs after fetch_gis_data + build_kg so PARSE can query the live KG:
      classify_sections -> extract_* -> validate_and_merge

    Outputs:
      - intent / planning_intent: SpatialPlanningIntent with zone targets
      - operation_sequence: List[SpatialOperation] with spatial anchors
      - constraint_set: List[SpatialConstraint] with spatial rules
    """
    from app.agent.gis.parse.agent import build_parse_agent_graph, set_context_blocks, set_grounding_context
    from app.agent.gis.parse.state import ParseAgentState, SpatialPlanningIntent
    from app.modules.spatial_ops import compute_context_blocks, build_constraint_index

    reports = state.reports or {}
    village_name = state.village_name

    if not reports and not village_name:
        logger.info("[Pipeline:parse] No reports or village name — skipping parse")
        return {}

    # Extract planning text from reports
    planning_text = ""
    if reports:
        for key, val in reports.items():
            if isinstance(val, dict):
                planning_text += val.get("content", val.get("text", ""))
            elif isinstance(val, str):
                planning_text += val
    if not planning_text:
        planning_text = state.intent_json.get("planning_text", "")

    if not planning_text:
        logger.info("[Pipeline:parse] No planning text found — skipping parse")
        return {}

    try:
        # GIS bundle is already available (from fetch_gis_data node)
        bundle = state.gis_bundle
        context_blocks = compute_context_blocks(bundle) if bundle else []

        # Set global context blocks for Tier 0 place resolution
        set_context_blocks(context_blocks)

        # Set global grounding context for geometric spatial grounding
        constraint_index = build_constraint_index(bundle) if bundle else None
        set_grounding_context(bundle=bundle, constraint_index=constraint_index)

        # Build and run PARSE Agent subgraph
        graph = build_parse_agent_graph()
        input_state = ParseAgentState(
            planning_text=planning_text[:12000],  # Token limit
            village_name=village_name,
            context_blocks=context_blocks,
        )

        result = await graph.ainvoke(input_state.model_dump())

        # Extract PARSE outputs — all typed
        operation_sequence = result.get("operation_sequence", [])
        constraint_set = result.get("constraint_set", [])
        planning_intent = result.get("planning_intent", SpatialPlanningIntent())

        zone_count = len(planning_intent.zone_targets) if hasattr(planning_intent, 'zone_targets') else 0

        logger.info(
            "[Pipeline:parse] Parsed: %d ops, %d constraints, %d zones",
            len(operation_sequence), len(constraint_set), zone_count,
        )

        return {
            "intent": planning_intent,
            "intent_json": planning_intent,
            "operation_sequence": operation_sequence,
            "constraint_set": constraint_set,
            "planning_intent": planning_intent,
            "context_blocks": [
                {
                    "block_type": b.block_type.value,
                    "title": b.title,
                    "data": b.data,
                    "priority": b.priority,
                }
                for b in context_blocks
            ],
        }
    except Exception as e:
        logger.warning("[Pipeline:parse] Parse failed: %s — continuing with empty intent", e)
        return {"intent": SpatialPlanningIntent(), "intent_json": SpatialPlanningIntent()}


async def _write_kg_l3_node(state: GISPipelineState) -> dict:
    """Write Layer 3 intent entities (ZoneTarget, FacilityTarget, etc.) to KG.

    After PARSE produces the intent, write L3 virtual entities with
    spatial anchoring triples. Reads the session KG built by _build_kg_node.
    """
    from app.modules.kg.manager import get_kg_manager

    session_id = state.session_id
    intent = state.intent

    if not session_id or not intent:
        logger.info("[Pipeline:write_kg_l3] No session or intent — skipping")
        return {}

    try:
        manager = get_kg_manager()
        kg = manager.get_session_kg(session_id)
        if kg is None:
            logger.warning("[Pipeline:write_kg_l3] No KG for session %s", session_id)
            return {}

        from app.modules.kg.builder.layer3 import build_intent_layer
        build_intent_layer(kg, intent)
        kg_turtle = kg.to_turtle()
        kg_version = state.kg_version + 1
        manager.bump_version(session_id)

        logger.info("[Pipeline:write_kg_l3] L3 written: %d triples", len(kg_turtle.split("\n")) if kg_turtle else 0)
        return {"kg_turtle": kg_turtle, "kg_version": kg_version}
    except Exception as e:
        logger.error("[Pipeline:write_kg_l3] Failed: %s", e)
        return {}


async def _detect_conflicts_node(state: GISPipelineState) -> dict:
    """Detect cross-dimension conflicts."""
    from app.tools.gis.conflict import detect_conflicts

    try:
        result = await detect_conflicts.ainvoke({})
        conflict_count = 0
        if isinstance(result, dict):
            report = result.get("report", result)
            conflict_count = report.get("total_count", 0) if isinstance(report, dict) else 0

        logger.info("[Pipeline:conflicts] %d conflicts detected", conflict_count)
        return {}
    except Exception as e:
        logger.warning("[Pipeline:conflicts] Detection failed: %s", e)
        return {}


async def _export_gdb_node(state: GISPipelineState) -> dict:
    """Export 12-layer GeoPackage + land balance table."""
    from app.tools.gis.export import export_gdb

    try:
        result = await export_gdb.ainvoke({})
        logger.info("[Pipeline:export] Export complete")
        return {"export_result": result if isinstance(result, dict) else {}}
    except Exception as e:
        logger.error("[Pipeline:export] Export failed: %s", e)
        return {"export_result": {}}


async def _render_map_node(state: GISPipelineState) -> dict:
    """Render map layers for frontend MapLibre visualization."""
    from app.tools.gis.render import render_map

    try:
        result = await render_map.ainvoke({})
        logger.info("[Pipeline:render] Render complete")
        return {"render_result": result if isinstance(result, list) else []}
    except Exception as e:
        logger.error("[Pipeline:render] Render failed: %s", e)
        return {"render_result": []}


# ── EXECUTE node ──────────────────────────────────────────────────────


async def _execute_node(state: GISPipelineState) -> dict:
    """EXECUTE Agent node: runs the execute subgraph (allocate + generate + validate).

    Replaces the deprecated _allocate_generate_react_node + _validate_layout_node.
    Maps GISPipelineState -> ExecuteAgentState, invokes the execute subgraph
    (with internal Worker-Evaluator retry loop), maps results back.
    """
    from app.agent.gis.execute import build_execute_agent_graph, ExecuteAgentState

    try:
        exec_state = ExecuteAgentState(
            session_id=state.session_id,
            village_name=state.village_name,
            gis_data=state.gis_data,
            gis_bundle=state.gis_bundle,
            intent=state.intent,
            operation_sequence=state.operation_sequence,
            constraint_set=state.constraint_set,
            facility_anchors=state.facility_anchors,
            kg_turtle=state.kg_turtle,
            kg_constraints=state.kg_constraints,
            kg_adjacency_map=state.kg_adjacency_map,
            kg_session_ref=state.kg_session_ref,
            kg_three_lines=state.kg_three_lines,
            kg_protected_parcels_detail=state.kg_protected_parcels_detail,
            kg_vne_summary=state.kg_vne_summary,
            allocated_geojson=state.allocated_geojson,
            allocation_summary=state.allocation_summary,
            layout_configs=state.layout_configs,
            validation_result=state.validation_result,
            validation_round=state.validation_round,
            constraint_adjustments=state.constraint_adjustments,
            messages=list(state.messages),
        )

        execute_graph = build_execute_agent_graph()
        result = await execute_graph.ainvoke(exec_state.model_dump())

        logger.info(
            "[Pipeline:execute] done: %d layers, round=%d, passed=%s",
            len(result.get("layout_configs", [])),
            result.get("validation_round", 0),
            result.get("validation_result", {}).get("passed", True),
        )

        return {
            "allocated_geojson": result.get("allocated_geojson", {}),
            "allocation_summary": result.get("allocation_summary", {}),
            "layout_configs": result.get("layout_configs", []),
            "validation_result": result.get("validation_result", {}),
            "validation_round": result.get("validation_round", 0),
            "constraint_adjustments": result.get("constraint_adjustments", []),
        }
    except Exception as e:
        logger.error("[Pipeline:execute] failed: %s", e, exc_info=True)
        return {}


# ── Conditional routing (legacy - execute subgraph handles retry internally) ──


def _route_after_validation(state: GISPipelineState) -> Literal["pass", "retry"]:
    """Route after validation: pass → export, fail → retry (max 3 rounds)."""
    result = state.validation_result or {}
    round_num = state.validation_round

    if result.get("passed", False):
        return "pass"
    if round_num >= 3:
        logger.warning("[Pipeline] Validation exceeded %d rounds — using best result", round_num)
        return "pass"
    return "retry"


# ── Pipeline builder ──────────────────────────────────────────────────


def build_layout_pipeline():
    """Build the unified GIS LAYOUT pipeline StateGraph.

    Pipeline: fetch → build_kg → parse → write_kg_l3 → execute → export → render

    PARSE runs after fetch + build_kg so it can query the live KG for
    spatial grounding. L3 intent entities are written as a separate node
    after PARSE completes.

    The pipeline uses Pydantic BaseModel state (GISPipelineState) with
    input_schema (GISPipelineInput) and output_schema (GISPipelineOutput)
    following LangGraph best practices.

    Returns:
        Compiled StateGraph ready for .ainvoke() or .astream()
    """
    graph = StateGraph(
        GISPipelineState,
        input_schema=GISPipelineInput,
        output_schema=GISPipelineOutput,
    )

    # ── Data nodes ──
    graph.add_node("fetch_gis_data", _fetch_gis_data_node)
    graph.add_node("build_kg", _build_kg_node)

    # ── PARSE node ──
    graph.add_node("parse_intent", _parse_intent_node)
    graph.add_node("write_kg_l3", _write_kg_l3_node)

    # ── Deterministic skeleton ──
    graph.add_node("detect_conflicts", _detect_conflicts_node)

    # ── EXECUTE Agent subgraph ──
    graph.add_node("execute", _execute_node)

    # ── Post-processing ──
    graph.add_node("export_gdb", _export_gdb_node)
    graph.add_node("render_map", _render_map_node)

    # ── Edges (new order: fetch -> build_kg -> parse -> write_kg_l3 -> execute) ──
    graph.add_edge(START, "fetch_gis_data")
    graph.add_edge("fetch_gis_data", "build_kg")
    graph.add_edge("build_kg", "parse_intent")
    graph.add_edge("parse_intent", "write_kg_l3")
    graph.add_edge("write_kg_l3", "detect_conflicts")
    graph.add_edge("detect_conflicts", "execute")
    graph.add_edge("execute", "export_gdb")
    graph.add_edge("export_gdb", "render_map")
    graph.add_edge("render_map", END)

    compiled = graph.compile()
    logger.info("[Pipeline] Unified pipeline compiled: 9 nodes (fetch -> build_kg -> parse -> write_kg_l3 -> execute)")
    return compiled


__all__ = ["build_layout_pipeline"]
