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

from typing import Literal, Optional

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


def _merge_explore_bsms(intent: Any, explore: Dict[str, Any]) -> int:
    """把 EXPLORE grounding 指令的候选 BSM 合并进 intent targets。

    EXPLORE 在 L3 完成后对空间描述做了 KG 拓扑接地，产出 candidate_bsms。
    这里把每个指令的候选 BSM 按维度聚合，合并到 ZoneTarget / FacilityTarget 的
    candidate_bsms（无对应 target 时跳过，不制造假实体）。

    Returns:
        合并的 BSM 总数。
    """
    instructions = (explore or {}).get("instructions") or []
    if not instructions:
        return 0

    merged_total = 0
    for instr in instructions:
        dim_key = str(instr.get("dimension_key") or "")
        bsms = list(dict.fromkeys(instr.get("candidate_bsms") or []))
        if not bsms or not dim_key:
            continue
        # 合并到 zone_targets（按 land_use 匹配维度名）
        for zt in (getattr(intent, "zone_targets", None) or []):
            existing = list(getattr(zt, "candidate_bsms", None) or [])
            added = [b for b in bsms if b not in existing]
            if added:
                zt.candidate_bsms = existing + added
                merged_total += len(added)
        # 合并到 facilities（按 type/语义匹配维度名）
        for ft in (getattr(intent, "facilities", None) or []):
            existing = list(getattr(ft, "candidate_bsms", None) or [])
            added = [b for b in bsms if b not in existing]
            if added:
                ft.candidate_bsms = existing + added
                merged_total += len(added)

    if merged_total:
        logger.info(
            "[Pipeline:parse] EXPLORE bsms merged: %d (from %d instructions)",
            merged_total, len(instructions),
        )
    return merged_total


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
        # P0: 计算 parcel 拓扑关系（sfTouches/nearby/connected + parcel-road/water），
        #     供 build_knowledge_graph 构建 KG L2 拓扑（grounding KG 拓扑查询的数据源）。
        try:
            from app.modules.spatial_ops.geometry import compute_parcel_relations

            parcels = bundle.polygons.get("landuse_current") or []
            roads = bundle.lines.get("roads_current") or []
            water = bundle.polygons.get("water_bodies") or []
            if parcels:
                relations = compute_parcel_relations(parcels, roads, water)
                raw["_parcel_relations"] = relations
                logger.info(
                    "[Pipeline:fetch] parcel relations: %d touches, %d nearby, "
                    "%d connected, %d road-intersects, %d water-touches",
                    len(relations.touches), len(relations.nearby),
                    len(relations.connected), len(relations.parcel_road_intersects),
                    len(relations.parcel_water_touches),
                )
        except Exception as rel_e:
            logger.warning("[Pipeline:fetch] parcel_relations compute failed: %s", rel_e)
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

        # P2: 合并 EXPLORE grounding 指令的候选 BSM 到 intent targets
        try:
            _merge_explore_bsms(intent, state.explore_instructions or {})
        except Exception as e:
            logger.warning("[Pipeline:parse] explore bsms merge failed: %s", e)

        # Extract PARSE outputs - all typed
        zone_count = len(intent.zone_targets) if hasattr(intent, 'zone_targets') else 0

        logger.info(
            "[Pipeline:parse] Parsed: %d zones, %d facilities, %d axes, %d roads",
            zone_count,
            len(intent.facilities) if hasattr(intent, 'facilities') else 0,
            len(intent.development_axes) if hasattr(intent, 'development_axes') else 0,
            len(intent.road_targets) if hasattr(intent, 'road_targets') else 0,
        )

        # P2: PARSE 步骤 Report（供 positioning-trace 定位）
        try:
            from app.services.step_report import save_step_report

            total_bsms = 0
            for zt in (getattr(intent, "zone_targets", None) or []):
                total_bsms += len(getattr(zt, "candidate_bsms", None) or [])
            await save_step_report(
                state.session_id, "PARSE",
                step_name="parse_intent",
                inputs={"reports_count": len(reports)},
                outputs={
                    "zone_targets": zone_count,
                    "facilities": len(intent.facilities) if hasattr(intent, "facilities") else 0,
                    "candidate_bsms_total": total_bsms,
                },
                diagnostics={
                    "explore_instructions": len((state.explore_instructions or {}).get("instructions", []) or []),
                },
            )
        except Exception as e:
            logger.debug("[Pipeline:parse] step report failed: %s", e)

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
    """Render map layers for frontend MapLibre visualization.

    P2: 三图合一 — 规划分区图层（layout_configs）+ 现状居民点锚点图层
    + 定位校核图层，单次产出供前端切换。
    """
    from app.tools.gis.render import render_map

    try:
        layout_configs = list(state.layout_configs or [])
        # P2: 追加现状居民点锚点图层（来自 gazetteer 多源坐标 + cluster）
        try:
            anchor_layer = _build_anchor_layer(state)
            if anchor_layer:
                layout_configs.append(anchor_layer)
        except Exception as e:
            logger.warning("[Pipeline:render] anchor layer failed: %s", e)
        # P2: 追加定位校核图层（EXPLORE grounding 指令的候选 BSM 标注）
        try:
            trace_layer = _build_trace_layer(state)
            if trace_layer:
                layout_configs.append(trace_layer)
        except Exception as e:
            logger.warning("[Pipeline:render] trace layer failed: %s", e)

        result = render_map.func(
            layout_configs=layout_configs,
            gis_data=state.gis_data,
        )
        logger.info("[Pipeline:render] Render complete (%d layers)", len(layout_configs))
        return {"render_result": result if isinstance(result, list) else []}
    except Exception as e:
        logger.error("[Pipeline:render] Render failed: %s", e)
        return {"render_result": []}


def _build_anchor_layer(state: GISPipelineState) -> Optional[Dict[str, Any]]:
    """构建现状居民点锚点图层（自然村名 → 坐标 Point FeatureCollection）。

    来源：gazetteer（P0 多源 API 注入的自然村坐标 + 组合名条目）。
    """
    try:
        from app.modules.kg.gazetteer import load_gazetteer

        gaz = load_gazetteer(state.village_name or "jintian")
        if not getattr(gaz, "entries", None):
            return None
        features = []
        for e in gaz.entries:
            centroid = getattr(e, "centroid", None)
            name = getattr(e, "name", "") or ""
            if not centroid or len(centroid) < 2 or not name:
                continue
            features.append({
                "type": "Feature",
                "properties": {"name": name, "source": getattr(e, "source", "")},
                "geometry": {"type": "Point", "coordinates": [centroid[0], centroid[1]]},
            })
        if not features:
            return None
        return {
            "layerType": "position_anchor",
            "layer_name": "现状居民点锚点",
            "data": {"type": "FeatureCollection", "features": features},
            "color": "#e11d48",
        }
    except Exception as e:
        logger.debug("[Pipeline:render] anchor layer build failed: %s", e)
        return None


def _build_trace_layer(state: GISPipelineState) -> Optional[Dict[str, Any]]:
    """构建定位校核图层（EXPLORE grounding 指令的候选 BSM → 点/面标注）。

    反映 L3 空间描述经 KG 拓扑接地后的候选地块分布，供前端核对
    "文本说 X 处" vs "几何落在哪"。
    """
    explore = state.explore_instructions or {}
    instructions = explore.get("instructions") or []
    if not instructions:
        return None
    features = []
    for instr in instructions:
        bsms = instr.get("candidate_bsms") or []
        if not bsms:
            continue
        for bsm in bsms:
            features.append({
                "type": "Feature",
                "properties": {
                    "name": bsm,
                    "dim": instr.get("dimension_key", ""),
                    "evidence": (instr.get("evidence_text") or "")[:30],
                    "query_path": instr.get("query_path", ""),
                },
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            })
    if not features:
        return None
    return {
        "layerType": "position_trace",
        "layer_name": "定位校核",
        "data": {"type": "FeatureCollection", "features": features},
        "color": "#7c3aed",
        "style": {"fill-opacity": 0.3},
    }


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

        # P2: EXECUTE 步骤 Report（供 positioning-trace 定位）
        try:
            from app.services.step_report import save_step_report

            layer_types = [c.get("layerType", "unknown") for c in result.get("layout_configs", [])]
            await save_step_report(
                state.session_id, "EXECUTE",
                step_name="execute_layout",
                outputs={
                    "layers": len(result.get("layout_configs", [])),
                    "layer_types": layer_types,
                    "allocated_parcels": len(
                        (result.get("allocated_geojson", {}) or {}).get("features", [])
                    ),
                },
                diagnostics={
                    "allocation_mode": (result.get("allocation_summary", {}) or {}).get("mode", ""),
                    "validation_passed": (result.get("validation_result", {}) or {}).get("passed"),
                    "validation_round": result.get("validation_round", 0),
                },
            )
        except Exception as e:
            logger.debug("[Pipeline:execute] step report failed: %s", e)

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
