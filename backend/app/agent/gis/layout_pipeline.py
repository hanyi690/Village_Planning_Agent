"""GIS LAYOUT pipeline — unified StateGraph with deterministic skeleton + ReAct adaptivity.

Architecture (LangGraph best practices):
  - Single StateGraph with GISPipelineState (Pydantic BaseModel)
  - Deterministic skeleton: parse → fetch → KG → conflicts → allocate → validate → export → render
  - ReAct subgraph in allocate_and_generate for adaptive strategy decisions
  - Worker-Evaluator retry loop: validate → fail? → feedback → retry (max 3 rounds)

References:
  [1] LangGraph StateGraph with Pydantic BaseModel state
  [2] LangGraph Worker-Evaluator pattern with Command routing
  [3] LangGraph subgraph state mapping pattern
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import StateGraph, END, START
from langgraph.types import Command

from .state import GISPipelineState, GISPipelineInput, GISPipelineOutput
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Node implementations ──────────────────────────────────────────────


async def _parse_intent_node(state: GISPipelineState) -> dict:
    """Parse planning text via PARSE Agent subgraph.

    Runs the spatially-aware PARSE Agent:
      classify_sections -> extract_* -> validate_and_merge

    Outputs:
      - intent: legacy format (for backward compatibility during transition)
      - intent_json: legacy format
      - operation_sequence: List[SpatialOperation] with spatial anchors
      - constraint_set: List[SpatialConstraint] with spatial rules
      - planning_intent: SpatialPlanningIntent with zone targets
      - spatial_context: SpatialContext summary
    """
    from app.agent.gis.parse.agent import build_parse_agent_graph
    from app.agent.gis.parse.state import ParseAgentState, SpatialContext, SpatialPlanningIntent
    from app.modules.gis.spatial_context import compute_spatial_context

    reports = state.reports or {}
    village_name = state.village_name
    gis_data = state.gis_data

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
        # Compute spatial context from GIS data
        spatial_context = compute_spatial_context(gis_data or {})

        # Build and run PARSE Agent subgraph
        graph = build_parse_agent_graph()
        input_state = ParseAgentState(
            planning_text=planning_text[:12000],  # Token limit
            village_name=village_name,
            spatial_context=spatial_context,
        )

        result = await graph.ainvoke(input_state.model_dump())

        # Extract PARSE outputs — all typed (Phase 4: no bridge, no dict conversion)
        operation_sequence = result.get("operation_sequence", [])
        constraint_set = result.get("constraint_set", [])
        planning_intent = result.get("planning_intent", SpatialPlanningIntent())
        validation_errors = result.get("validation_errors", [])

        zone_count = len(planning_intent.zone_targets) if hasattr(planning_intent, 'zone_targets') else 0

        # Extract facility anchors from spatial_context for downstream consumption
        facility_anchors = None
        if hasattr(spatial_context, 'facility_anchors') and spatial_context.facility_anchors:
            facility_anchors = [fa.model_dump() for fa in spatial_context.facility_anchors]

        logger.info(
            "[Pipeline:parse] Parsed: %d ops, %d constraints, %d zones",
            len(operation_sequence), len(constraint_set), zone_count,
        )
        if validation_errors:
            logger.warning("[Pipeline:parse] Validation errors: %s", validation_errors[:3])

        return {
            "intent": planning_intent,       # typed SpatialPlanningIntent — no bridge
            "intent_json": planning_intent,
            "operation_sequence": operation_sequence,
            "constraint_set": constraint_set,
            "planning_intent": planning_intent,
            "spatial_context": spatial_context.model_dump(),
            "facility_anchors": facility_anchors,
        }
    except Exception as e:
        logger.warning("[Pipeline:parse] Parse failed: %s — continuing with empty intent", e)
        return {"intent": SpatialPlanningIntent(), "intent_json": SpatialPlanningIntent()}


async def _fetch_gis_data_node(state: GISPipelineState) -> dict:
    """Fetch GIS data from providers (Tianditu/OSM/Amap)."""
    from app.tools.gis.data import fetch_gis_data

    village_name = state.village_name

    if not village_name:
        logger.info("[Pipeline:fetch] No village name — skipping data fetch")
        return {}

    try:
        result = await fetch_gis_data.ainvoke({"village_name": village_name})
        logger.info("[Pipeline:fetch] GIS data fetched for: %s", village_name)
        return {"gis_data": result if isinstance(result, dict) else {}}
    except Exception as e:
        logger.warning("[Pipeline:fetch] Fetch failed: %s", e)
        return {}


async def _build_kg_node(state: GISPipelineState) -> dict:
    """Build knowledge graph from intent + GIS data.

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


async def _allocate_generate_react_node(state: GISPipelineState) -> dict:
    """ReAct subgraph: LLM adaptively decides allocation strategy and layout params.

    Within the deterministic skeleton, this node gives LLM flexibility to:
      - Query KG constraints and decide allocation targets
      - Adjust strategy based on validation feedback from prior rounds
      - Cannot skip KG or skip VALIDATE (skeleton guarantees this)
    """
    from .agent import create_layout_agent_graph

    validation_result = state.get("validation_result", {})
    validation_feedback = ""

    if validation_result and not validation_result.get("passed", True):
        violations = validation_result.get("violations", [])
        violation_summary = str(violations[:3]) if violations else "unknown"
        validation_feedback = (
            f"上轮验证发现 {len(violations)} 个违规，请调整分配策略。\n"
            f"违规详情：{violation_summary}"
        )

    messages = list(state.get("messages", []))
    if validation_feedback:
        messages.append(HumanMessage(content=validation_feedback))

    try:
        layout_agent = create_layout_agent_graph()
        result = await layout_agent.ainvoke({
            "session_id": state.session_id,
            "village_name": state.village_name,
            "gis_data": state.gis_data,
            "intent": state.intent,
            "kg_turtle": state.kg_turtle,
            "kg_constraints": state.kg_constraints,
            "layout_configs": state.layout_configs,
            "allocated_geojson": state.allocated_geojson,
            "allocation_summary": state.allocation_summary,
            "messages": messages,
        })

        return {
            "allocated_geojson": result.get("allocated_geojson", {}),
            "allocation_summary": result.get("allocation_summary", {}),
            "layout_configs": result.get("layout_configs", []),
            "messages": result.get("messages", []),
        }
    except Exception as e:
        logger.error("[Pipeline:allocate_generate] ReAct subgraph failed: %s", e)
        return {}


async def _validate_layout_node(state: GISPipelineState) -> dict:
    """Evaluator gate: validate layout, decide retry or pass."""
    from app.tools.gis.validate import validate_layout

    try:
        result = await validate_layout.ainvoke({})
        passed = False
        violations = []
        if isinstance(result, dict):
            passed = result.get("is_valid", result.get("passed", False))
            violations = result.get("violations", [])

        round_num = state.validation_round + 1

        logger.info(
            "[Pipeline:validate] Round %d: %s (%d violations)",
            round_num, "PASS" if passed else "FAIL", len(violations),
        )

        return {
            "validation_result": {
                "passed": passed,
                "violations": violations if not passed else [],
            },
            "validation_round": round_num,
        }
    except Exception as e:
        logger.error("[Pipeline:validate] Validation failed: %s", e)
        return {"validation_result": {"passed": True, "violations": []}, "validation_round": state.validation_round + 1}


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


# ── Conditional routing ───────────────────────────────────────────────


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

    Pipeline: parse → fetch → KG → conflicts → allocate+generate → validate → export → render

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

    # ── Input nodes ──
    graph.add_node("parse_intent", _parse_intent_node)
    graph.add_node("fetch_gis_data", _fetch_gis_data_node)

    # ── Deterministic skeleton ──
    graph.add_node("build_kg", _build_kg_node)
    graph.add_node("detect_conflicts", _detect_conflicts_node)

    # ── Adaptive ReAct subgraph ──
    graph.add_node("allocate_and_generate", _allocate_generate_react_node)

    # ── Evaluator gate ──
    graph.add_node("validate_layout", _validate_layout_node)

    # ── Post-processing ──
    graph.add_node("export_gdb", _export_gdb_node)
    graph.add_node("render_map", _render_map_node)

    # ── Edges ──
    graph.add_edge(START, "parse_intent")
    graph.add_edge("parse_intent", "fetch_gis_data")
    graph.add_edge("fetch_gis_data", "build_kg")
    graph.add_edge("build_kg", "detect_conflicts")
    graph.add_edge("detect_conflicts", "allocate_and_generate")
    graph.add_edge("allocate_and_generate", "validate_layout")

    # Worker-Evaluator conditional edge
    graph.add_conditional_edges(
        "validate_layout",
        _route_after_validation,
        {
            "retry": "allocate_and_generate",
            "pass": "export_gdb",
        },
    )

    graph.add_edge("export_gdb", "render_map")
    graph.add_edge("render_map", END)

    compiled = graph.compile()
    logger.info("[Pipeline] Unified LAYOUT pipeline compiled: 9 nodes, 1 conditional edge")
    return compiled


__all__ = ["build_layout_pipeline"]
