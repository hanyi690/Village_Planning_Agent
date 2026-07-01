"""村庄规划主图（4节点 + GIS Agent 子图）

节点：
1. conversation: 中央路由（大脑）
2. execute_tools: 工具执行
3. analyze_dimension: 维度分析
4. gis_agent: GIS 空间布局 ReAct Agent

图构建以纯函数形式提供 — `create_unified_planning_graph` 每次返回新图，
缓存由 `PlanningRuntimeService._graph` 单例负责。
"""

from typing import Dict, Any, List, Optional
from langgraph.graph import StateGraph, END, START
from langchain_core.messages import AIMessage

from .state import AgentState, PlanningPhase, create_initial_state, get_layer_dimensions
from .context import PlanningContext
from .routing import after_conversation, after_analysis
from .conversation import conversation_node
from .tools import execute_tools_node
from .analysis import analyze_dimension, DIMENSION_NAMES
from .completion import layer_completion_check

from ..utils.logger import get_logger
logger = get_logger(__name__)


async def analyze_dimension_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """维度分析节点"""
    return await analyze_dimension(state)


async def gis_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """GIS Agent 节点 — 调用 ReAct 子图生成空间布局"""
    from .gis import create_gis_agent_graph
    from .gis_context import SharedGISContext

    gis_graph = create_gis_agent_graph()

    gis_context = SharedGISContext.from_state(state)
    gis_input = {
        "session_id": state.get("session_id", ""),
        "village_name": state.get("config", {}).get("village_name", ""),
        "reports": _get_reports(state),
        "summaries": _get_summaries(state),
        "gis_data": {
            "boundary_geojson": gis_context.get_data_by_type("boundary"),
            "landuse_current_geojson": gis_context.get_data_by_type("landuse_current"),
            "protection_zones": gis_context.get_protection_zones(),
            "road_geojson": gis_context.get_data_by_type("road"),
            "hazard_points_geojson": gis_context.get_data_by_type("geological_hazard_points"),
            "construction_zone_geojson": gis_context.get_data_by_type("construction_zone"),
        },
        "kg_turtle": "",
        "kg_constraints": [],
        "layout_configs": [],
        "allocated_geojson": {},
        "allocation_summary": {},
        "messages": [],
    }

    result = await gis_graph.ainvoke(gis_input)

    layout_configs = result.get("layout_configs", [])

    # Publish GIS layout result via SSE
    # NOTE: Individual layers were already pushed via gis_layer_update events
    # from SpatialLayoutEngine._emit_layer_update(). This gis_result event
    # only sends a lightweight summary (no layers data) to avoid redundant
    # transfer of large GeoJSON payloads.
    session_id = state.get("session_id", "")
    if layout_configs and session_id:
        try:
            from app.utils.sse_publisher import SSEPublisher
            layer_types = [c.get("layerType", "unknown") for c in layout_configs]
            SSEPublisher.send_gis_result(
                session_id=session_id,
                dimension_key="spatial_layout",
                dimension_name="空间布局",
                summary=f"生成 {len(layout_configs)} 个图层: {', '.join(layer_types)}",
                layers=[],  # Empty: layers already sent via gis_layer_update
            )
        except Exception as e:
            logger.warning(f"[gis_agent_node] SSE publish failed: {e}")

    return {
        "messages": [AIMessage(content=_format_gis_result(result, layout_configs))],
        "gis_layout_configs": layout_configs,
    }


def create_unified_planning_graph(checkpointer=None) -> StateGraph:
    """创建统一规划图（5 节点）— 纯函数，每次返回新图。

    缓存责任由调用方承担（`PlanningRuntimeService._graph` 单例）。
    """
    logger.info("[图构建] 构建 5 节点图")
    builder = StateGraph(AgentState, context_schema=PlanningContext)

    builder.add_node("conversation", conversation_node)
    builder.add_node("execute_tools", execute_tools_node)
    builder.add_node("analyze_dimension", analyze_dimension_node)
    builder.add_node("layer_completion_check", layer_completion_check)
    builder.add_node("gis_agent", gis_agent_node)

    builder.add_edge(START, "conversation")
    builder.add_conditional_edges("conversation", after_conversation,
        {"execute_tools": "execute_tools", "analyze_dimension": "analyze_dimension",
         "gis_agent": "gis_agent", END: END})
    builder.add_edge("execute_tools", "conversation")
    builder.add_edge("gis_agent", "conversation")
    builder.add_edge("analyze_dimension", "layer_completion_check")
    builder.add_conditional_edges("layer_completion_check", after_analysis,
        {"analyze_dimension": "analyze_dimension", "conversation": "conversation", END: END})

    return builder.compile(checkpointer=checkpointer)


__all__ = [
    "AgentState", "PlanningPhase",
    "create_unified_planning_graph",
    "gis_agent_node",
]


def _get_reports(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """从数据库加载 L3 summaries，构造统一嵌套格式。

    格式: {dk: {"summary": {"metrics": {...}}, "content": "..."}}
    """
    summaries = _load_summaries_from_db(state)
    if not summaries:
        return _get_reports_fallback(state)

    reports = {}
    for dk, parsed in summaries.items():
        reports[dk] = {
            "summary": {
                "metrics": parsed.get("metrics", {}),
                "key_points": parsed.get("key_points", []),
                "text_summary": parsed.get("text_summary", ""),
            },
            "content": parsed.get("text_summary", ""),
        }
    return reports


def _get_summaries(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """同 _get_reports — 统一嵌套格式后两者等价。"""
    return _get_reports(state)


def _load_summaries_from_db(state: Dict[str, Any]) -> Optional[Dict[str, Dict[str, Any]]]:
    """从 ReportStore 加载 L3 summaries。"""
    session_id = state.get("session_id", "")
    if not session_id:
        return None
    try:
        from app.services.report_store import ReportStore
        return ReportStore().get_layer_summaries(session_id, layer=3)
    except Exception:
        return None


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
    layer_types = [c.get("layerType", "unknown") for c in layout_configs]
    return f"GIS 布局生成完成：{len(layout_configs)} 个图层 ({', '.join(layer_types)})"
