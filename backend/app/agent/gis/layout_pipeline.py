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


def _attach_custom_zone_targets(intent: Any, reports: Dict[str, Any], village_name: str = "") -> int:
    """P3-4: 项目/分区名 → L3 分区表词汇表类别 → CustomZoneTarget（接线现存能力）。

    vocab_extractor（L3 分区表 → session 词汇表，确定性）+ format_bound 的
    _match_category_code 原本无调用方；这里将 INSTRUCTION/表格提取的实体名
    匹配到词汇表类别，产出 custom_zone_targets 供 CustomZoningGenerator
    按类别规则选地；target_bsms 继承该实体已 gazetteer 解析的候选 BSM。
    返回新增 target 数。
    """
    from app.agent.gis.format_bound_intent import _match_category_code
    from app.agent.gis.vocab_extractor import extract_vocabulary_deterministic
    from app.modules.schema.contracts.custom_zone_contracts import CustomZoneTarget
    from app.modules.schema.encodings.dicts.vocabularies.loader import register_vocabulary

    reports_content = {
        k: (v.get("content", "") if isinstance(v, dict) else str(v))
        for k, v in (reports or {}).items()
    }
    vocab = extract_vocabulary_deterministic(reports_content)
    if not vocab.categories:
        return 0
    register_vocabulary(vocab.name, vocab)

    entity_bsms: Dict[str, List[str]] = {}
    for ft in (getattr(intent, "facilities", None) or []):
        if ft.type:
            entity_bsms[ft.type] = list(ft.candidate_bsms or [])
    for zt in (getattr(intent, "zone_targets", None) or []):
        if zt.land_use:
            entity_bsms[zt.land_use] = list(zt.candidate_bsms or [])

    existing_codes = {c.category_code for c in (getattr(intent, "custom_zone_targets", None) or [])}
    added = 0
    for name, bsms in entity_bsms.items():
        code = _match_category_code(name, vocab.name)
        if not code or code in existing_codes:
            continue
        existing_codes.add(code)
        intent.custom_zone_targets.append(CustomZoneTarget(
            vocabulary_name=vocab.name,
            category_code=code,
            target_bsms=bsms,
            decided_by="rule",
            confidence=0.7,
        ))
        added += 1
    if added:
        logger.info(
            "[Pipeline:parse] custom zone targets attached: %d (vocab=%s)",
            added, vocab.name,
        )
    return added


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
        # @tool 包装带 InjectedToolCallId — 直接调 .func（同步）并显式传 state 参数
        result = build_knowledge_graph.func(
            reports=state.reports,
            gis_data=state.gis_data,
            village_name=state.village_name,
            session_id=state.session_id,
            intent=state.intent,
        )
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

    v4 guard: an externally supplied intent (EXPLORE -> Binder -> format)
    with structured content is preserved — no double parse, no override.

    Outputs:
      - intent / planning_intent: SpatialPlanningIntent with zone targets
      - operation_sequence: List[SpatialOperation] with spatial anchors
      - constraint_set: List[SpatialConstraint] with spatial rules
    """
    from app.agent.gis.parse import parse_async, ParseResult
    from app.agent.gis.parse.state import SpatialPlanningIntent

    reports = state.reports or {}
    village_name = state.village_name

    # v4: 外部 intent（EXPLORE→Binder→format 产出）优先，跳过内部重 parse
    existing = state.intent
    if existing is not None:
        has_structured = (
            (getattr(existing, "zone_targets", None) and len(existing.zone_targets) > 0)
            or (getattr(existing, "custom_zone_targets", None) and len(existing.custom_zone_targets) > 0)
            or (getattr(existing, "facilities", None) and len(existing.facilities) > 0)
        )
        if has_structured:
            logger.info(
                "[Pipeline:parse] External intent preserved (%d zones, %d custom, %d facilities)",
                len(existing.zone_targets or []),
                len(existing.custom_zone_targets or []),
                len(existing.facilities or []),
            )
            return {
                "intent": existing,
                "intent_json": existing,
                "planning_intent": existing,
            }

    if not reports and not village_name:
        logger.info("[Pipeline:parse] No reports or village name — skipping parse")
        return {}

    # Extract planning text from reports
    planning_text = ""
    instruction_text = ""
    if reports:
        for key, val in reports.items():
            if isinstance(val, dict):
                planning_text += val.get("content", val.get("text", ""))
                instruction_text += val.get("instruction", "") + "\n"
            elif isinstance(val, str):
                planning_text += val
    if not planning_text:
        planning_text = state.intent_json.get("planning_text", "")

    if not planning_text:
        logger.info("[Pipeline:parse] No planning text found — skipping parse")
        return {}

    try:
        # P8: INSTRUCTION 段（文末结构化定位表格）优先保留 — 正文截断后补回
        if instruction_text:
            planning_text = planning_text[:9000] + "\n\n" + instruction_text[:4000]
        result: ParseResult = await parse_async(
            planning_text=planning_text[:13000],
            village_name=village_name,
            planning_period=state.config.get("planning_period", "2022-2035年"),
        )
        intent = result.intent

        # P8: 自然村/位置名 → gazetteer → candidate_bsms（intent 原地填充）
        try:
            from app.agent.gis.parse.agent import resolve_spatial_anchors

            resolve_spatial_anchors(intent, village_name=village_name)
        except Exception as e:
            logger.warning("[Pipeline:parse] spatial anchor resolution failed: %s", e)

        # P3-4: INSTRUCTION 项目/分区名 → L3 分区表词汇表类别 → CustomZoneTarget
        # （target_bsms 继承已 gazetteer 解析的候选 BSM，功能区落位生效）
        try:
            _attach_custom_zone_targets(intent, reports, village_name)
        except Exception as e:
            logger.warning("[Pipeline:parse] custom zone target attach failed: %s", e)

        # Extract PARSE outputs - all typed
        zone_count = len(intent.zone_targets) if hasattr(intent, 'zone_targets') else 0

        logger.info(
            "[Pipeline:parse] Parsed: %d zones, %d facilities, %d axes, %d roads",
            zone_count,
            len(intent.facilities) if hasattr(intent, 'facilities') else 0,
            len(intent.development_axes) if hasattr(intent, 'development_axes') else 0,
            len(intent.road_targets) if hasattr(intent, 'road_targets') else 0,
        )

        return {
            "intent": intent,
            "intent_json": intent,
            "operation_sequence": [],
            "constraint_set": [],
            "planning_intent": intent,
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
        result = await detect_conflicts.func(summaries={})
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
        result = await export_gdb.func(
            layout_configs=state.layout_configs,
            allocated_geojson=state.allocated_geojson,
            gis_data=state.gis_data,
            village_name=state.village_name,
        )
        logger.info("[Pipeline:export] Export complete")
        return {"export_result": result if isinstance(result, dict) else {}}
    except Exception as e:
        logger.error("[Pipeline:export] Export failed: %s", e)
        return {"export_result": {}}


async def _render_map_node(state: GISPipelineState) -> dict:
    """Render map layers for frontend MapLibre visualization."""
    from app.tools.gis.render import render_map

    try:
        result = render_map.func(
            layout_configs=state.layout_configs,
            gis_data=state.gis_data,
        )
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
        # model_dump 会把 gis_bundle/intent(Pydantic BaseModel) 递归转 dict —
        # dump 后重新放回对象，子图才能用 bundle.lines/polygons、intent.zone_targets 等
        exec_dict = exec_state.model_dump()
        exec_dict["gis_bundle"] = state.gis_bundle
        exec_dict["intent"] = state.intent
        result = await execute_graph.ainvoke(exec_dict)

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
