"""村庄规划主图（5节点 + GIS Agent 子图）

节点：
1. conversation: 中央路由（大脑）
2. execute_tools: 工具执行
3. analyze_dimension: 维度分析
4. layer_completion_check: 层级完成检测 + interrupt 审批
5. gis_agent: GIS 空间布局 ReAct Agent

图构建以纯函数形式提供 — `create_unified_planning_graph` 每次返回新图，
缓存由 `PlanningRuntimeService._graph` 单例负责。
"""

from typing import Dict, Any, List, Literal, Optional
from langgraph.graph import StateGraph, END, START
from langgraph.errors import NodeError
from langgraph.types import Command
from langchain_core.messages import AIMessage

from .state import AgentState, PlanningPhase, create_initial_state, get_layer_dimensions
from .routing import after_conversation, after_analysis
from .conversation import conversation_node
from .tools import execute_tools_node
from .analysis import analyze_dimension, DIMENSION_NAMES
from .completion import layer_completion_check

from ..utils.logger import get_logger
logger = get_logger(__name__)


# TimeoutPolicy + error_handler for node-level fault tolerance (LangGraph v1.2)
try:
    from langgraph.types import RetryPolicy
    _HAS_RETRY_POLICY = True
except ImportError:
    _HAS_RETRY_POLICY = False


def _gis_error_handler(state: Dict[str, Any], error: NodeError) -> Command:
    """GIS Agent error handler — return error message to conversation instead of crashing."""
    logger.error("[gis_agent] Node %s failed: %s", error.node, error.error)
    return Command(
        update={"messages": [AIMessage(content=f"GIS 分析出错: {error.error}")]},
        goto=END,
    )


async def analyze_dimension_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """维度分析节点"""
    return await analyze_dimension(state)


async def explore_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """EXPLORE 桥接节点 — L3 完成后读 L1/L2/L3 + KG 认知，产出空间定位指令."""
    from .explore.node import explore_node as _explore_node

    return await _explore_node(state)


async def gis_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """GIS Agent node — LAYOUT hybrid pipeline.

    Step 1: 收集 L1+L3 report instruction 段 + EXPLORE 产出。
    Step 2: LAYOUT Pipeline (deterministic skeleton + ReAct subgraph + Evaluator Gate)
            generates spatial layout with guaranteed step ordering and validation retry.
    """
    from .gis.layout_pipeline import build_layout_pipeline
    from app.services.session_bundle import build_session_bundle

    session_id = state.get("session_id", "")
    village_name = state.get("config", {}).get("village_name", "")

    # ── Load GIS data via DataCatalog (schema-driven, single path) ──
    gis_bundle = await build_session_bundle(session_id, village_name)
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

    # ── Step 2: LAYOUT Pipeline (hybrid: deterministic skeleton + ReAct subgraph) ──
    pipeline = build_layout_pipeline()
    layout_result = await pipeline.ainvoke({
        "session_id": session_id,
        "village_name": village_name,
        "gis_data": gis_data,
        "gis_bundle": gis_bundle,
        "reports": reports,
        "intent": None,
        "intent_json": {},
        "explore_instructions": explore_instructions,
        "report_summary_index": report_summary_index,
        "dimension_summaries": summaries,
        "kg_turtle": "",
        "kg_constraints": [],
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

    if layout_configs and session_id:
        try:
            from app.utils.sse_publisher import SSEPublisher
            layer_types = [
                c.get("layerType") or c.get("layer_type") or "unknown"
                for c in layout_configs
            ]
            SSEPublisher.send_gis_result(
                session_id=session_id,
                dimension_key="spatial_layout",
                dimension_name="空间布局",
                summary=f"生成 {len(layout_configs)} 个图层: {', '.join(layer_types)}",
                layers=layout_configs,  # Full layers as fallback for missed gis_layer_update events
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


def create_unified_planning_graph(checkpointer=None) -> StateGraph:
    """创建统一规划图（6 节点）— 纯函数，每次返回新图。

    缓存责任由调用方承担（`PlanningRuntimeService._graph` 单例）。
    """
    logger.info("[图构建] 构建 6 节点图")
    builder = StateGraph(AgentState)

    builder.add_node("conversation", conversation_node)
    builder.add_node("execute_tools", execute_tools_node)
    builder.add_node("analyze_dimension", analyze_dimension_node)
    builder.add_node("layer_completion_check", layer_completion_check)
    builder.add_node("explore", explore_node)
    builder.add_node("gis_agent", gis_agent_node, error_handler=_gis_error_handler)

    builder.add_edge(START, "conversation")
    builder.add_conditional_edges("conversation", after_conversation,
        {"execute_tools": "execute_tools", "analyze_dimension": "analyze_dimension",
         "gis_agent": "gis_agent", END: END})
    builder.add_edge("execute_tools", "conversation")
    builder.add_edge("gis_agent", "conversation")
    builder.add_edge("analyze_dimension", "layer_completion_check")
    builder.add_edge("explore", "gis_agent")
    builder.add_conditional_edges("layer_completion_check", after_analysis,
        {"analyze_dimension": "analyze_dimension", "explore": "explore",
         "conversation": "conversation", END: END})

    return builder.compile(checkpointer=checkpointer)


__all__ = [
    "AgentState", "PlanningPhase",
    "create_unified_planning_graph",
    "gis_agent_node",
]


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
