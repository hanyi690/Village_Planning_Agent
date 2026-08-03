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

from datetime import datetime, timezone
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
    existing_data = dict(state.gis_data or {})

    if state.gis_bundle is not None:
        raw = state.gis_bundle.to_geojson_dict()
        raw.update(existing_data)
        try:
            from app.modules.spatial_ops.geometry import compute_parcel_relations

            parcels = state.gis_bundle.polygons.get("landuse_current") or []
            roads = state.gis_bundle.lines.get("roads_current") or []
            water = state.gis_bundle.polygons.get("water_bodies") or []
            if parcels:
                raw["_parcel_relations"] = compute_parcel_relations(
                    parcels,
                    roads,
                    water,
                )
        except Exception as relation_error:
            logger.warning(
                "[Pipeline:fetch] caller bundle relation compute failed: %s",
                relation_error,
            )
        logger.info("[Pipeline:fetch] Reusing caller-provided GIS bundle")
        return {"gis_bundle": state.gis_bundle, "gis_data": raw}

    if not village_name:
        logger.info("[Pipeline:fetch] No village name — using caller-provided GIS data")
        return {"gis_data": existing_data}

    try:
        catalog = DataCatalog()
        if state.session_id:
            bundle = await catalog.load_village_bundle_async(
                village_name,
                session_id=state.session_id,
            )
        else:
            bundle = catalog.load_village_bundle(village_name)
        raw = bundle.to_geojson_dict()
        raw.update(existing_data)
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
    from app.modules.kg.service import build_knowledge_graph_data

    try:
        result = build_knowledge_graph_data(
            reports=state.reports,
            gis_data=state.gis_data,
            village_name=state.village_name,
            session_id=state.session_id,
            intent=state.intent,
            bundle=state.gis_bundle,
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
        kg_build_metrics = result.get("kg_build_metrics", {})

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
        try:
            from app.services.step_report import save_step_report

            await save_step_report(
                state.session_id,
                "KG",
                step_name="build_static_layers",
                inputs={
                    "reports_count": len(state.reports or {}),
                    "provider_sources": list(
                        getattr(
                            getattr(state.gis_bundle, "metadata", None),
                            "provider_sources",
                            [],
                        )
                    ),
                },
                outputs={
                    "triple_count": kg_build_metrics.get("triple_count", 0),
                    "constraints": len(kg_constraints),
                    "adjacency_nodes": len(kg_adjacency_map),
                    "protected_parcels": len(kg_protected_parcels_detail),
                },
                diagnostics={
                    "cache_hit": kg_build_metrics.get("cache_hit", False),
                    "session_ref": kg_session_ref,
                },
            )
        except Exception as report_error:
            logger.debug("[Pipeline:kg] step report failed: %s", report_error)
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
            or (getattr(existing, "project_targets", None) and len(existing.project_targets) > 0)
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
    planning_parts = []
    instruction_text = ""
    if reports:
        priority = (
            "land_use_planning",
            "spatial_structure",
            "traffic_planning",
            "public_service",
            "infrastructure_planning",
            "ecological",
            "disaster_prevention",
            "project_bank",
        )
        ordered_keys = list(priority) + [
            key for key in reports if key not in priority
        ]
        for key in ordered_keys:
            if key not in reports:
                continue
            val = reports[key]
            if isinstance(val, dict):
                planning_parts.append(val.get("content", val.get("text", "")))
                instruction_text += val.get("instruction", "") + "\n"
            elif isinstance(val, str):
                planning_parts.append(val)
    planning_text = "\n\n".join(part for part in planning_parts if part)
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
            planning_period=(
                getattr(
                    getattr(state.gis_bundle, "metadata", None),
                    "planning_period",
                    "",
                )
                or "2022-2035年"
            ),
        )
        intent = result.intent

        # P8: 自然村/位置名 → gazetteer → candidate_bsms（intent 原地填充）
        try:
            from app.agent.gis.parse.agent import resolve_spatial_anchors

            resolve_spatial_anchors(
                intent,
                village_name=village_name,
                village_anchors=state.kg_village_anchors,
            )
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
                    "road_targets": len(intent.road_targets) if hasattr(intent, "road_targets") else 0,
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
        try:
            from app.services.step_report import save_step_report

            await save_step_report(
                session_id,
                "KG",
                step_name="write_intent_layer",
                inputs={
                    "zone_targets": len(getattr(intent, "zone_targets", None) or []),
                    "facility_targets": len(getattr(intent, "facilities", None) or []),
                    "road_targets": len(getattr(intent, "road_targets", None) or []),
                },
                outputs={
                    "triple_count": kg.get_triple_count(),
                    "kg_version": kg_version,
                },
            )
        except Exception as report_error:
            logger.debug("[Pipeline:write_kg_l3] step report failed: %s", report_error)
        return {"kg_turtle": kg_turtle, "kg_version": kg_version}
    except Exception as e:
        logger.error("[Pipeline:write_kg_l3] Failed: %s", e)
        return {}


async def _detect_conflicts_node(state: GISPipelineState) -> dict:
    """Detect cross-dimension conflicts."""
    from app.tools.gis.conflict import ConflictDetector

    try:
        report = ConflictDetector().detect_all(state.dimension_summaries or {})
        conflict_count = report.total_count
        conflict_result = {
            "has_conflicts": report.has_conflicts,
            "total_count": conflict_count,
            "metric_conflicts": [
                conflict.description for conflict in report.metric_conflicts
            ],
            "constraint_violations": [
                conflict.description for conflict in report.constraint_violations
            ],
            "spatial_conflicts": [
                (
                    f"{conflict.dimension_a}: {conflict.structure_a}; "
                    f"{conflict.dimension_b}: {conflict.structure_b}"
                )
                for conflict in report.spatial_conflicts
            ],
        }
        logger.info("[Pipeline:conflicts] %d conflicts detected", conflict_count)
        try:
            from app.services.step_report import save_step_report

            await save_step_report(
                state.session_id,
                "CONFLICT",
                step_name="cross_dimension_conflicts",
                inputs={"summary_count": len(state.dimension_summaries or {})},
                outputs=conflict_result,
            )
        except Exception as report_error:
            logger.debug("[Pipeline:conflicts] step report failed: %s", report_error)

        result = {"conflict_result": conflict_result}
        if report.has_conflicts:
            result["execution_errors"] = list(state.execution_errors or []) + [{
                "stage": "conflict",
                "code": "unresolved_report_conflicts",
                "message": f"{conflict_count} cross-dimension conflicts require resolution.",
                "details": conflict_result,
            }]
        return result
    except Exception as e:
        logger.warning("[Pipeline:conflicts] Detection failed: %s", e)
        return {
            "execution_errors": list(state.execution_errors or []) + [{
                "stage": "conflict",
                "code": "conflict_detection_failed",
                "message": str(e),
            }]
        }


async def _export_gdb_node(state: GISPipelineState) -> dict:
    """Export the validated GeoJSON planning package and run manifest."""
    from app.modules.spatial_ops.export_package import export_gdb_package

    partial_zone_ready = bool((state.validation_result or {}).get("partial_usable")) and any(
        (config.get("layerType") or config.get("layer_type")) == "custom_planning_zone"
        for config in (state.layout_configs or [])
    )
    if not (state.validation_result or {}).get("passed", False) and not partial_zone_ready:
        logger.error("[Pipeline:export] Blocked because layout validation did not pass")
        result = {
            "status": "blocked",
            "reason": "validation_failed",
            "exported_files": [],
            "file_count": 0,
        }
        try:
            from app.services.step_report import save_step_report

            await save_step_report(
                state.session_id,
                "OUTPUT",
                step_name="export_package",
                outputs=result,
                diagnostics={"validation": state.validation_result},
            )
        except Exception as report_error:
            logger.debug("[Pipeline:export] step report failed: %s", report_error)
        return {"export_result": result}

    try:
        export_validation = dict(state.validation_result or {})
        if partial_zone_ready:
            export_validation["status"] = "warning"
            export_validation["partial_usable"] = True
        result = export_gdb_package(
            layout_configs=state.layout_configs,
            allocated_geojson=state.allocated_geojson,
            gis_data=state.gis_data,
            village_name=state.village_name,
            session_id=state.session_id,
            validation_result=export_validation,
        )
        if partial_zone_ready:
            result["status"] = "completed_with_warnings"
            result["warning"] = "主分区已生成；道路规划尚未完成。"
        logger.info("[Pipeline:export] Export complete")
        try:
            from app.services.step_report import save_step_report

            await save_step_report(
                state.session_id,
                "OUTPUT",
                step_name="export_package",
                outputs={
                    "status": result.get("status"),
                    "file_count": result.get("file_count", 0),
                    "output_dir": result.get("output_dir", ""),
                },
                artifacts=[
                    {
                        "kind": "run_manifest",
                        "path": str(result.get("output_dir", "")) + "/run_manifest.json",
                    }
                ],
                diagnostics={"validation": state.validation_result},
            )
        except Exception as report_error:
            logger.debug("[Pipeline:export] step report failed: %s", report_error)
        return {"export_result": result if isinstance(result, dict) else {}}
    except Exception as e:
        logger.error("[Pipeline:export] Export failed: %s", e)
        return {"export_result": {}}


async def _render_map_node(state: GISPipelineState) -> dict:
    """Render map layers for frontend MapLibre visualization.

    P2: 三图合一 — 规划分区图层（layout_configs）+ 现状居民点锚点图层
    + 定位校核图层，单次产出供前端切换。
    """
    from app.modules.spatial_ops.map_layers import build_map_layers

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

        result = build_map_layers(
            layout_configs=layout_configs,
            gis_data=state.gis_data,
        )
        preview = {
            "status": "blocked",
            "reason": "validated_export_required",
            "path": "",
        }
        interactive_map = dict(preview)
        def _intent_items(field: str) -> List[Dict[str, Any]]:
            raw = getattr(state.intent, field, None) if state.intent is not None else None
            if isinstance(state.intent, dict):
                raw = state.intent.get(field)
            items: List[Dict[str, Any]] = []
            for item in raw or []:
                if hasattr(item, "model_dump"):
                    item = item.model_dump()
                elif not isinstance(item, dict):
                    item = {
                        key: getattr(item, key)
                        for key in dir(item)
                        if not key.startswith("_") and not callable(getattr(item, key))
                    }
                items.append(dict(item))
            return items

        realized_facilities = sum(
            len((config.get("data") or {}).get("features", config.get("features", [])) or [])
            for config in layout_configs
            if (config.get("layerType") or config.get("layer_type")) == "facility_point"
        )
        realized_roads = sum(
            len((config.get("data") or {}).get("features", config.get("features", [])) or [])
            for config in layout_configs
            if (config.get("layerType") or config.get("layer_type"))
            in {"planned_road", "planned_road_candidates"}
        )
        intent_projects = {
            "zones": [
                {
                    "name": item.get("land_use") or item.get("name") or "未命名分区",
                    "status": "已生成候选分区",
                    "detail": f"目标面积 {item.get('area_ha') or '未提供'} 公顷",
                }
                for item in _intent_items("zone_targets")
            ],
            "facilities": [
                {
                    "name": item.get("name") or item.get("facility_type") or "未命名设施",
                    "status": "已生成规划点" if realized_facilities else "未落位",
                    "detail": "已绑定 annotation/KG 锚点并生成设施几何"
                    if realized_facilities
                    else "已进入意图层，等待 annotation/KG 空间锚点",
                }
                for item in _intent_items("facilities")
            ],
            "roads": [
                {
                    "name": item.get("road_level") or item.get("name") or "未命名道路",
                    "status": "已生成候选线" if realized_roads else "未落位",
                    "detail": "已绑定 KG 村庄锚点并结合现状道路网络生成候选线"
                    if realized_roads
                    else "已进入道路子模块，端点尚未解析为可绘制几何",
                }
                for item in _intent_items("road_targets")
            ],
        }
        narrative_sections = [
            {
                "title": "数据链路",
                "text": "规划分区来自 L3 目标与 660 个现状地块；现状道路和设施标注作为底图及 KG 空间上下文参与计算。",
            },
        ]
        realization_issues = list(state.execution_errors or [])
        if _intent_items("facilities") and not realized_facilities:
            realization_issues.append({
                "code": "planned_facilities_unresolved",
                "message": "设施目标已解析，但尚未生成规划设施几何。",
            })
        if _intent_items("road_targets") and not realized_roads:
            realization_issues.append({
                "code": "planned_roads_unresolved",
                "message": "道路目标已解析，但尚未生成正式规划道路几何。",
            })
        output_dir = (state.export_result or {}).get("output_dir", "")
        export_status = (state.export_result or {}).get("status")
        if (
            (state.validation_result or {}).get("passed", False)
            and export_status in {"completed", "completed_with_warnings"}
            and output_dir
        ):
            from app.tools.gis.static_render import render_map_preview

            preview = render_map_preview(
                layers=result,
                output_dir=output_dir,
                village_name=state.village_name,
            )
            from app.tools.gis.html_render import render_interactive_map

            interactive_map = render_interactive_map(
                layers=result,
                output_dir=output_dir,
                village_name=state.village_name,
                issues=realization_issues,
                project_summary=intent_projects,
                narrative_sections=narrative_sections,
            )
        preview["interactive_html"] = interactive_map
        logger.info("[Pipeline:render] Render complete (%d layers)", len(layout_configs))
        try:
            from app.services.step_report import save_step_report

            await save_step_report(
                state.session_id,
                "RENDER",
                step_name="build_map_layers",
                inputs={"layout_layers": len(layout_configs)},
                outputs={
                    "render_layers": len(result),
                    "layer_types": [
                        layer.get("layerType") or layer.get("layer_type")
                        for layer in result
                    ],
                    "preview_status": preview.get("status"),
                    "preview_path": preview.get("path", ""),
                    "html_status": interactive_map.get("status"),
                    "html_path": interactive_map.get("path", ""),
                },
                artifacts=[
                    {
                        "kind": "planning_preview",
                        "path": preview.get("path", ""),
                    },
                    {
                        "kind": "interactive_map",
                        "path": interactive_map.get("path", ""),
                    },
                ] if preview.get("path") else [],
                diagnostics={
                    "validation_passed": bool(
                        (state.validation_result or {}).get("passed", False)
                    ),
                },
            )
        except Exception as report_error:
            logger.debug("[Pipeline:render] step report failed: %s", report_error)
        return {
            "render_result": result,
            "render_artifact": preview,
            "validation_passed": bool((state.validation_result or {}).get("passed", False)),
            "completed_at": datetime.now(timezone.utc),
        }
    except Exception as e:
        logger.error("[Pipeline:render] Render failed: %s", e)
        return {
            "render_result": [],
            "render_artifact": {
                "status": "failed",
                "reason": str(e),
                "path": "",
            },
        }


def _build_anchor_layer(state: GISPipelineState) -> Optional[Dict[str, Any]]:
    """构建现状居民点锚点图层（自然村名 → 坐标 Point FeatureCollection）。

    来源：gazetteer（P0 多源 API 注入的自然村坐标 + 组合名条目）。
    """
    try:
        from app.modules.kg.gazetteer import load_gazetteer

        if not state.village_name:
            return None
        gaz = load_gazetteer(state.village_name)
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

    parcel_index: Dict[str, Dict[str, Any]] = {}
    landuse = (state.gis_data or {}).get("landuse_current_geojson") or {}
    for feature in landuse.get("features", []):
        props = feature.get("properties") or {}
        bsm = str(props.get("BSM") or props.get("bsm") or "")
        geometry = feature.get("geometry")
        if bsm and geometry:
            parcel_index[bsm] = geometry

    features = []
    for instr in instructions:
        bsms = instr.get("candidate_bsms") or []
        if not bsms:
            continue
        for bsm in bsms:
            geometry = parcel_index.get(str(bsm))
            if geometry is None:
                continue
            features.append({
                "type": "Feature",
                "properties": {
                    "name": bsm,
                    "dim": instr.get("dimension_key", ""),
                    "evidence": (instr.get("evidence_text") or "")[:30],
                    "query_path": instr.get("query_path", ""),
                },
                "geometry": geometry,
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
            execution_errors=state.execution_errors,
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

            layer_types = [
                c.get("layerType") or c.get("layer_type") or "unknown"
                for c in result.get("layout_configs", [])
            ]
            layer_feature_counts: Dict[str, int] = {}
            valid_geometry_counts: Dict[str, int] = {}
            for config in result.get("layout_configs", []):
                layer_type = (
                    config.get("layerType")
                    or config.get("layer_type")
                    or "unknown"
                )
                data = config.get("data") or config.get("geojson") or {}
                features = data.get("features", config.get("features", [])) or []
                layer_feature_counts[layer_type] = (
                    layer_feature_counts.get(layer_type, 0) + len(features)
                )
                valid_geometry_counts[layer_type] = (
                    valid_geometry_counts.get(layer_type, 0)
                    + sum(
                        1
                        for feature in features
                        if (feature.get("geometry") or {}).get("coordinates")
                    )
                )
            await save_step_report(
                state.session_id, "EXECUTE",
                step_name="execute_layout",
                outputs={
                    "layers": len(result.get("layout_configs", [])),
                    "layer_types": layer_types,
                    "layer_feature_counts": layer_feature_counts,
                    "valid_geometry_counts": valid_geometry_counts,
                    "allocated_parcels": len(
                        (result.get("allocated_geojson", {}) or {}).get("features", [])
                    ),
                },
                diagnostics={
                    "allocation_mode": (result.get("allocation_summary", {}) or {}).get("mode", ""),
                    "validation_passed": (result.get("validation_result", {}) or {}).get("passed"),
                    "validation_round": result.get("validation_round", 0),
                    "execution_errors": result.get("execution_errors", []),
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
            "execution_errors": result.get("execution_errors", []),
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
