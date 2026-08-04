"""GIS agent entry. Migrated from agent/graph.py per docs/architecture/agent-graph.md §5."""

from typing import Dict, Any, List, Literal, Optional
from langgraph.graph import END
from langgraph.errors import NodeError
from langgraph.types import Command
from langchain_core.messages import AIMessage

from app.utils.logger import get_logger
logger = get_logger(__name__)


def _gis_error_handler(state: Dict[str, Any], error: NodeError) -> Command:
    """GIS Agent error handler — return error message to conversation instead of crashing."""
    logger.error("[gis_agent] Node %s failed: %s", error.node, error.error)
    return Command(
        update={"messages": [AIMessage(content=f"GIS 分析出错: {error.error}")]},
        goto=END,
    )


async def gis_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """GIS Agent node — LAYOUT hybrid pipeline.

    Step 1: 收集 L1+L3 report instruction 段 + EXPLORE 产出。
    Step 2: LAYOUT Pipeline (deterministic skeleton + ReAct subgraph + Evaluator Gate)
            generates spatial layout with guaranteed step ordering and validation retry.
    """
    from app.agent.execute.layout_pipeline import build_layout_pipeline

    session_id = state.get("session_id", "")
    village_name = state.get("config", {}).get("village_name", "")

    # ── 单一路径：SessionPlanningContext 组装 bundle/KG/gazetteer/anchors/reports ──
    # 消除 gis_agent_node / ensure_session_kg / layout_pipeline._fetch/_build_kg 的重复构建。
    from app.services.context import build_planning_context

    context = await build_planning_context(
        session_id, village_name, include_reports=True
    )
    village_name = context.village_name or village_name
    gis_bundle = context.bundle
    gazetteer = context.gazetteer
    kg_session_ref = context.kg_session_ref

    user_uploaded = state.get("user_uploaded_data", {})
    has_uploaded_sources = any(
        source.startswith("upload:")
        for source in gis_bundle.metadata.provider_sources
    )
    if user_uploaded and not has_uploaded_sources:
        from app.modules.data.catalog.catalog import _merge_geojson_into_bundle
        from app.modules.schema.types.canonical import VillageBundle

        metadata = gis_bundle.metadata.model_copy(
            update={"provider_sources": []},
            deep=True,
        )
        gis_bundle = VillageBundle(
            village_name=village_name,
            metadata=metadata,
        )

        for layer_key, geojson in user_uploaded.items():
            _merge_geojson_into_bundle(gis_bundle, layer_key, geojson)
    gis_data = gis_bundle.to_geojson_dict()

    reports, summaries = await _get_reports_and_summaries(state)
    if context.reports:
        reports.update(context.reports)
    if context.report_summary_index:
        summaries.update(context.report_summary_index)

    # ── Step 1: 收集 L1+L3 instruction 段（P8 结构化定位表）─ EXPLORE 产出 ──
    # 消除双重 parse：不再独立调用 create_parse_agent_graph，统一由
    # layout_pipeline._parse_intent_node 消费 reports + explore_instructions。
    explore_instructions = state.get("explore_instructions", {}) or {}
    report_summary_index = state.get("report_summary_index", {}) or {}
    try:
        from app.services.report_store import ReportStore

        store = ReportStore.get_instance()
        for layer in (1, 3):
            layer_reports = await store.get_layer_reports_with_sources(session_id, layer)
            if layer_reports:
                for dk, rec in layer_reports.items():
                    content = (rec or {}).get("content") or ""
                    if content:
                        reports.setdefault(dk, {})["content"] = content
    except Exception as e:
        logger.warning("[gis_agent_node] L1/L3 report read failed: %s", e)

    # ── EXPLORE -> deterministic Bundle Binder -> typed PARSE intent ──
    external_intent = None
    try:
        from app.agent.explore.contracts import ExplorationInstructionCollection
        from app.agent.ground.format_bound_intent import format_bound_spatial_intent
        from app.agent.select.parse_agent import parse
        from app.modules.spatial_ops.bundle_binder import bind_exploration_to_bundle

        planning_text = "\n\n".join(
            str(record.get("content") or "")
            for record in reports.values()
            if isinstance(record, dict) and record.get("content")
        )
        fallback_intent = parse(
            planning_text=planning_text,
            village_name=village_name,
        ).intent if planning_text else None

        vocabulary_name = ""
        if planning_text:
            from app.agent.execute.vocab_extractor import (
                extract_vocabulary_deterministic,
            )
            from app.modules.schema.encodings.dicts.vocabularies.loader import (
                register_vocabulary,
            )

            vocabulary = extract_vocabulary_deterministic({
                key: str(value.get("content") or "")
                for key, value in reports.items()
                if isinstance(value, dict)
            })
            if vocabulary.categories:
                register_vocabulary(vocabulary.name, vocabulary)
                vocabulary_name = vocabulary.name

        collection = ExplorationInstructionCollection.model_validate(
            {
                key: value
                for key, value in explore_instructions.items()
                if key in {
                    "schema_version",
                    "session_id",
                    "village_name",
                    "instructions",
                    "kg_session_ref",
                }
            }
        )
        bound_entities = bind_exploration_to_bundle(
            collection, gis_bundle, gazetteer=gazetteer
        )
        external_intent = format_bound_spatial_intent(
            village_name=village_name,
            bound_entities=bound_entities,
            fallback_intent=fallback_intent,
            vocabulary_name=vocabulary_name,
        )
        external_intent.vocabulary_name = vocabulary_name
        logger.info(
            "[gis_agent_node] bound intent: projects=%d zones=%d facilities=%d roads=%d",
            len(external_intent.project_targets),
            len(external_intent.zone_targets),
            len(external_intent.facilities),
            len(external_intent.road_targets),
        )
    except Exception as e:
        logger.warning("[gis_agent_node] Explore/Bundle binding failed: %s", e)

    # ── Step 2: LAYOUT Pipeline (hybrid: deterministic skeleton + ReAct subgraph) ──
    pipeline = build_layout_pipeline()
    layout_result = await pipeline.ainvoke({
        "session_id": session_id,
        "village_name": village_name,
        "gis_data": gis_data,
        "gis_bundle": gis_bundle,
        "reports": reports,
        "intent": external_intent,
        "intent_json": {},
        "explore_instructions": explore_instructions,
        "report_summary_index": report_summary_index,
        "dimension_summaries": summaries,
        "kg_turtle": "",
        "kg_constraints": [],
        "kg_session_ref": kg_session_ref or "",
        "layout_configs": [],
        "allocated_geojson": {},
        "allocation_summary": {},
        "validation_result": {},
        "validation_round": 0,
        "export_result": {},
        "render_result": [],
        "render_artifact": {},
        "execution_errors": [],
        "conflict_result": {},
        "messages": [],
    })

    # ── Step 3: SSE + return ──
    layout_configs = layout_result.get("layout_configs", [])

    render_layers = layout_result.get("render_result", [])

    if render_layers and session_id:
        try:
            from app.utils.sse_publisher import SSEPublisher
            layer_types = [
                c.get("layerType") or c.get("layer_type") or "unknown"
                for c in render_layers
            ]
            SSEPublisher.send_gis_result(
                session_id=session_id,
                dimension_key="spatial_layout",
                dimension_name="空间布局",
                summary=f"生成 {len(render_layers)} 个图层: {', '.join(layer_types)}",
                layers=render_layers,
                pipeline_trace=state.get("pipeline_trace"),
            )
        except Exception as e:
            logger.warning(f"[gis_agent_node] SSE publish failed: %s", e)

    return {
        "messages": [AIMessage(content=_format_gis_result(layout_result, layout_configs))],
        "gis_layout_configs": layout_configs,
        "gis_export_result": layout_result.get("export_result", {}),
        "gis_render_result": layout_result.get("render_result", []),
        "gis_render_artifact": layout_result.get("render_artifact", {}),
        "gis_validation_result": layout_result.get("validation_result", {}),
        "gis_execution_errors": layout_result.get("execution_errors", []),
        "gis_conflict_result": layout_result.get("conflict_result", {}),
    }


async def _get_reports_and_summaries(
    state: Dict[str, Any],
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """从 DB 加载 L3 GIS 输入报告和 L1/L2/L3 冲突检测摘要。

    reports: 嵌套格式 {dk: {"summary": {"metrics": ...}, "content": ...}}
    summaries: 扁平格式 {dk: {dimension_key, layer, metrics, key_points, text_summary}}
    """
    session_id = state.get("session_id", "")
    flat_summaries: Dict[str, Dict[str, Any]] = {}
    l3_summaries: Dict[str, Dict[str, Any]] = {}

    if session_id:
        try:
            from app.services.report_store import ReportStore
            store = ReportStore()
            for layer in (1, 2, 3):
                layer_summaries = await store.get_layer_summaries(
                    session_id,
                    layer=layer,
                ) or {}
                flat_summaries.update(layer_summaries)
                if layer == 3:
                    l3_summaries = layer_summaries
        except Exception:
            pass

    if not l3_summaries:
        return _get_reports_fallback(state), {}

    reports = {}
    for dk, parsed in l3_summaries.items():
        reports[dk] = {
            "summary": {
                "metrics": parsed.get("metrics", {}),
                "key_points": parsed.get("key_points", []),
                "text_summary": parsed.get("text_summary", ""),
            },
            "content": parsed.get("text_summary", ""),
        }
    return reports, flat_summaries


def _get_reports_fallback(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Fallback: 从 completed_dimensions 构造最小格式。"""
    completed = state.get("completed_dimensions", {})
    result = {}
    for layer_key, dims in completed.items():
        for dim_key in dims:
            result[dim_key] = {"status": "completed", "layer": layer_key}
    return result


def _format_gis_result(result: Dict[str, Any], layout_configs: List[Dict[str, Any]]) -> str:
    """格式化 GIS Agent 结果为对话消息"""
    validation = result.get("validation_result", {}) or {}
    if not validation.get("passed", False):
        reasons = result.get("execution_errors", []) or validation.get("violations", [])
        return (
            f"GIS 布局生成失败：校验未通过，正式成果未导出。"
            f"已生成 {len(layout_configs)} 个诊断图层；原因：{reasons}"
        )
    layer_types = [
        c.get("layerType") or c.get("layer_type") or "unknown"
        for c in layout_configs
    ]
    return f"GIS 布局生成完成：{len(layout_configs)} 个图层 ({', '.join(layer_types)})"


__all__ = ["gis_agent_node"]
