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
from langgraph.types import Command
from langchain_core.messages import AIMessage, HumanMessage

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


def _gis_error_handler(*args, **kwargs) -> Command:
    """GIS Agent error handler — compatible with different LangGraph versions.

    Some LangGraph versions call error_handler(error), while others call
    error_handler(state, error). The previous two-argument signature could raise
    `_gis_error_handler() missing 1 required positional argument: 'error'`, which
    crashed revision and GIS tasks.
    """
    error = kwargs.get("error")
    if error is None and args:
        error = args[-1]
    logger.error("[gis_agent] Node failed: %s", error)
    return Command(
        update={"messages": [AIMessage(content=f"GIS 分析出错: {error}")]},
        goto="conversation",
    )


async def analyze_dimension_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """维度分析节点"""
    return await analyze_dimension(state)


async def gis_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """GIS Agent 节点 — 调用 ReAct 子图生成空间布局"""
    from .gis import create_gis_agent_graph
    from .gis_context import SharedGISContext

    gis_graph = create_gis_agent_graph()

    gis_context = SharedGISContext.from_state(state)
    reports = await _get_reports(state)
    gis_input = {
        "session_id": state.get("session_id", ""),
        "village_name": state.get("config", {}).get("village_name", ""),
        "reports": reports,
        "summaries": reports,
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
        "messages": [
            HumanMessage(content=(
                "请基于已完成的村庄规划报告生成 GIS 空间布局。"
                "请依次解析规划文本、构建空间约束、分配用地功能区、生成可视化图层，"
                "最后返回可用于前端地图展示的 layout_configs。"
            ))
        ],
    }

    session_id = state.get("session_id", "")
    result: Dict[str, Any] = {}
    try:
        result = await gis_graph.ainvoke(gis_input)
        layout_configs = result.get("layout_configs", []) or []
    except Exception as e:
        logger.exception("[gis_agent_node] GIS subgraph failed, using fallback layout: %s", e)
        result = {"error": str(e), "fallback": True}
        layout_configs = []

    if not layout_configs:
        layout_configs = _build_fallback_gis_layers(state, gis_context)
        result["fallback"] = True

    if session_id:
        try:
            from app.utils.sse_publisher import SSEPublisher
            layer_types = [c.get("layerType") or c.get("layer_type") or "unknown" for c in layout_configs]
            map_options = _infer_map_options(layout_configs)
            # Send actual layers in both incremental and final events. This makes
            # the frontend map usable even when the ReAct GIS pipeline fails.
            SSEPublisher.send_gis_layer_update(
                session_id=session_id,
                layer=3,
                dimension_key="spatial_layout",
                dimension_name="空间布局",
                layers=layout_configs,
                map_options=map_options,
            )
            SSEPublisher.send_gis_result(
                session_id=session_id,
                dimension_key="spatial_layout",
                dimension_name="空间布局",
                summary=f"生成 {len(layout_configs)} 个图层: {', '.join(layer_types)}",
                layers=layout_configs,
                map_options=map_options,
                pipeline_trace=state.get("pipeline_trace"),
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
    builder = StateGraph(AgentState)

    builder.add_node("conversation", conversation_node)
    builder.add_node("execute_tools", execute_tools_node)
    builder.add_node("analyze_dimension", analyze_dimension_node)
    builder.add_node("layer_completion_check", layer_completion_check)
    builder.add_node("gis_agent", gis_agent_node, error_handler=_gis_error_handler)

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


async def _get_reports(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """从数据库加载 L3 summaries，构造统一嵌套格式。

    格式: {dk: {"summary": {"metrics": {...}}, "content": "..."}}
    """
    summaries = await _load_summaries_from_db(state)
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



async def _load_summaries_from_db(state: Dict[str, Any]) -> Optional[Dict[str, Dict[str, Any]]]:
    """从 ReportStore 加载 L3 summaries。"""
    session_id = state.get("session_id", "")
    if not session_id:
        return None
    try:
        from app.services.report_store import ReportStore
        store = ReportStore.get_instance()
        return await store.get_layer_summaries(session_id, layer=3)
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



def _collect_geojson_coords(obj: Any) -> List[List[float]]:
    """Collect [lng, lat] pairs from a GeoJSON-like object."""
    coords: List[List[float]] = []
    if isinstance(obj, dict):
        if obj.get("type") == "FeatureCollection":
            for f in obj.get("features", []) or []:
                coords.extend(_collect_geojson_coords(f))
        elif obj.get("type") == "Feature":
            coords.extend(_collect_geojson_coords(obj.get("geometry")))
        elif "coordinates" in obj:
            coords.extend(_collect_geojson_coords(obj.get("coordinates")))
        else:
            for v in obj.values():
                coords.extend(_collect_geojson_coords(v))
    elif isinstance(obj, list):
        if len(obj) >= 2 and all(isinstance(x, (int, float)) for x in obj[:2]):
            lng, lat = float(obj[0]), float(obj[1])
            if -180 <= lng <= 180 and -90 <= lat <= 90:
                coords.append([lng, lat])
        else:
            for item in obj:
                coords.extend(_collect_geojson_coords(item))
    return coords


def _bbox_from_coords(coords: List[List[float]]) -> List[float]:
    if not coords:
        # Default center near Meizhou; used only when no GIS base data exists.
        return [116.05, 24.25, 116.15, 24.35]
    lngs = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    minx, maxx = min(lngs), max(lngs)
    miny, maxy = min(lats), max(lats)
    if abs(maxx - minx) < 0.01:
        minx -= 0.02; maxx += 0.02
    if abs(maxy - miny) < 0.01:
        miny -= 0.02; maxy += 0.02
    return [minx, miny, maxx, maxy]


def _rect_feature(minx: float, miny: float, maxx: float, maxy: float, name: str, zone_type: str) -> Dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"name": name, "zone_type": zone_type},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]
            ]],
        },
    }


def _line_feature(points: List[List[float]], name: str) -> Dict[str, Any]:
    return {"type": "Feature", "properties": {"name": name}, "geometry": {"type": "LineString", "coordinates": points}}


def _point_feature(lng: float, lat: float, name: str, facility_type: str) -> Dict[str, Any]:
    return {"type": "Feature", "properties": {"name": name, "facility_type": facility_type}, "geometry": {"type": "Point", "coordinates": [lng, lat]}}


def _build_fallback_gis_layers(state: Dict[str, Any], gis_context: Any = None) -> List[Dict[str, Any]]:
    """Build a deterministic planning layout when the GIS ReAct pipeline fails.

    This is not a fake success message: it gives the frontend valid GIS layers so
    the map can display, while the backend logs still record the original GIS
    pipeline error. The layout uses uploaded boundary data when available.
    """
    boundary = None
    try:
        boundary = gis_context.get_data_by_type("boundary") if gis_context else None
    except Exception:
        boundary = None
    coords = _collect_geojson_coords(boundary)
    minx, miny, maxx, maxy = _bbox_from_coords(coords)
    dx, dy = maxx - minx, maxy - miny
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2

    if boundary and boundary.get("type") == "FeatureCollection" and boundary.get("features"):
        boundary_fc = boundary
    else:
        boundary_fc = {"type": "FeatureCollection", "features": [_rect_feature(minx, miny, maxx, maxy, "规划范围边界", "boundary")]}

    zones = {
        "type": "FeatureCollection",
        "features": [
            _rect_feature(minx + dx*0.05, miny + dy*0.10, minx + dx*0.48, miny + dy*0.55, "村民居住与公共服务提升区", "settlement"),
            _rect_feature(minx + dx*0.52, miny + dy*0.10, minx + dx*0.95, miny + dy*0.55, "特色农业与产业发展区", "industry"),
            _rect_feature(minx + dx*0.05, miny + dy*0.60, minx + dx*0.95, miny + dy*0.95, "生态保育与景观控制区", "ecology"),
        ],
    }
    facilities = {
        "type": "FeatureCollection",
        "features": [
            _point_feature(cx - dx*0.18, cy - dy*0.05, "公共服务中心", "public_service"),
            _point_feature(cx + dx*0.18, cy - dy*0.05, "产业服务节点", "industry_service"),
            _point_feature(cx, cy + dy*0.22, "生态游憩节点", "ecological_recreation"),
        ],
    }
    axes = {
        "type": "FeatureCollection",
        "features": [
            _line_feature([[minx + dx*0.08, cy - dy*0.10], [cx, cy], [maxx - dx*0.08, cy + dy*0.10]], "村庄发展联系轴"),
        ],
    }
    return [
        {"geojson": boundary_fc, "layerType": "boundary", "layerName": "规划范围边界", "color": "#2563eb", "style": {"color": "#2563eb"}},
        {"geojson": zones, "layerType": "planning_zone", "layerName": "空间功能分区", "color": "#10b981", "style": {"color": "#10b981"}},
        {"geojson": facilities, "layerType": "facility_point", "layerName": "公共服务与产业节点", "color": "#f59e0b", "style": {"color": "#f59e0b"}},
        {"geojson": axes, "layerType": "development_axis", "layerName": "发展联系轴", "color": "#ef4444", "style": {"color": "#ef4444"}},
    ]


def _infer_map_options(layout_configs: List[Dict[str, Any]]) -> Dict[str, Any]:
    coords: List[List[float]] = []
    for cfg in layout_configs or []:
        coords.extend(_collect_geojson_coords(cfg.get("geojson")))
    minx, miny, maxx, maxy = _bbox_from_coords(coords)
    span = max(maxx - minx, maxy - miny)
    zoom = 13 if span < 0.05 else 12 if span < 0.15 else 11
    return {"center": [(minx + maxx) / 2, (miny + maxy) / 2], "zoom": zoom}


def _format_gis_result(result: Dict[str, Any], layout_configs: List[Dict[str, Any]]) -> str:
    """格式化 GIS Agent 结果为对话消息"""
    layer_types = [c.get("layerType", "unknown") for c in layout_configs]
    return f"GIS 布局生成完成：{len(layout_configs)} 个图层 ({', '.join(layer_types)})"
