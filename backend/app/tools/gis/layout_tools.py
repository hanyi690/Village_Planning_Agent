"""GIS layout planning tools - KG-driven spatial layout generation.

Uses LangGraph 1.x InjectedState for large data injection (invisible to LLM)
and Command for state write-back. LLM-visible content is delivered via
ToolMessage inside Command.update["messages"].

LangGraph 1.2 Command API note:
  Command(update={...state_fields..., "messages": [ToolMessage(...)]})
  - update: state write-back (merged into graph state)
  - messages: MUST contain a ToolMessage with matching tool_call_id
  - No `result=` parameter exists; ToolMessage.content is the LLM-visible payload
"""

import json
from typing import Dict, Any, List, Optional, Annotated
from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger
from app.services.modules.gis.layout.planning_intent import (
    UnifiedSpatialIntent, ZoneIntent, FacilityIntent,
    AxisIntent, ConstraintIntent, Direction, Density,
)

logger = get_logger(__name__)


def _make_result(success: bool, data: Any = None, error: str = "") -> Dict[str, Any]:
    """Build tool result payload (dict, will be JSON-serialized into ToolMessage)."""
    payload: Dict[str, Any] = {"success": success}
    if data is not None:
        payload["data"] = data
    if error:
        payload["error"] = error
    return payload


def _to_tool_message(result: Dict[str, Any], tool_call_id: str) -> ToolMessage:
    """Wrap result dict into a ToolMessage for LLM visibility."""
    return ToolMessage(
        content=json.dumps(result, ensure_ascii=False, default=str),
        tool_call_id=tool_call_id,
    )


def _safe_enum(enum_cls, value, default=None):
    """Safely convert string to Enum, falling back to default on invalid values."""
    try:
        return enum_cls(value)
    except (ValueError, KeyError):
        fallback = default or list(enum_cls)[0]
        logger.warning("Invalid %s value: %r, using %s", enum_cls.__name__, value, fallback)
        return fallback


@tool
def build_knowledge_graph(
    reports: Annotated[Dict[str, Dict[str, Any]], InjectedState("reports")],
    gis_data: Annotated[Dict[str, Optional[Dict[str, Any]]], InjectedState("gis_data")],
    village_name: Annotated[str, InjectedState("village_name")],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """从规划报告+用地数据构建知识图谱。只需调用一次。
    构建后可使用 query_knowledge_graph 查询约束、指标和地块信息。

    Args: 无需参数，数据自动从状态注入。
    """
    from app.services.modules.gis.layout.kg import PlanningKG

    landuse_geojson = gis_data.get("landuse_current_geojson") if gis_data else None

    kg = PlanningKG(village_name=village_name)
    kg.build_from_reports(reports=reports, landuse_geojson=landuse_geojson)

    triple_count = kg.get_triple_count()
    constraints = kg.get_constraints()

    result = _make_result(True, {
        "village_name": village_name,
        "triple_count": triple_count,
        "constraint_count": len(constraints),
        "status": "knowledge_graph_built",
    })

    return Command(
        update={
            "kg_turtle": kg.to_turtle(),
            "kg_constraints": constraints,
            "messages": [_to_tool_message(result, tool_call_id)],
        },
    )


@tool
def query_knowledge_graph(
    template_name: str,
    field_name: str = "",
    dlbm: str = "",
    zone_type: str = "",
    kg_turtle: Annotated[str, InjectedState("kg_turtle")] = "",
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """查询知识图谱（约束/指标/地块/分区限制）。
    必须先调用 build_knowledge_graph 构建图谱。

    可用模板:
    - get_constraints: 获取所有约束
    - get_constraint_by_field: 按字段名查询约束（需 field_name）
    - get_parcels_by_dlbm: 按地类编码查询地块（需 dlbm）
    - get_parcels_by_zone_type: 按分区类型查询地块（需 zone_type）
    - count_by_zone_type: 统计各分区地块数和面积
    - get_zone_restrictions: 获取分区限制
    - get_indicators: 获取规划指标
    - check_protected_parcels: 检查受保护地块
    - get_adjacent_parcels: 获取相邻地块

    Args:
        template_name: SPARQL 查询模板名称
        field_name: 字段名（用于 get_constraint_by_field）
        dlbm: 地类编码（用于 get_parcels_by_dlbm）
        zone_type: 分区类型（用于 get_parcels_by_zone_type）
    """
    from app.services.modules.gis.layout.kg import PlanningKG
    from app.services.modules.gis.layout.kg.query import query_kg, QUERY_TEMPLATES

    if not kg_turtle:
        result = _make_result(False, error="KG 未构建，请先调用 build_knowledge_graph")
        return Command(update={"messages": [_to_tool_message(result, tool_call_id)]})

    if template_name not in QUERY_TEMPLATES:
        result = _make_result(
            False,
            error=f"未知模板: {template_name}",
            data={"available_templates": list(QUERY_TEMPLATES.keys())},
        )
        return Command(update={"messages": [_to_tool_message(result, tool_call_id)]})

    params = {}
    if field_name:
        params["field_name"] = field_name
    if dlbm:
        params["dlbm"] = dlbm
    if zone_type:
        params["zone_type"] = zone_type

    try:
        kg = PlanningKG.from_turtle(kg_turtle)
        results = query_kg(kg, template_name, **params)
        result = _make_result(True, {
            "template": template_name,
            "result_count": len(results),
            "results": results[:50],
        })
        return Command(update={"messages": [_to_tool_message(result, tool_call_id)]})
    except Exception as e:
        logger.error("query_knowledge_graph failed: %s", e)
        result = _make_result(False, error=str(e))
        return Command(update={"messages": [_to_tool_message(result, tool_call_id)]})


@tool
def detect_conflicts(
    summaries: Annotated[Dict[str, Dict[str, Any]], InjectedState("summaries")],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """检测跨维度指标冲突和约束违规。
    分析各维度摘要数据，检测土地使用、社会经济、产业、生态等维度间的冲突。

    Args: 无需参数，摘要数据自动从状态注入。
    """
    from app.services.modules.gis.layout.conflict_detector import ConflictDetector

    detector = ConflictDetector()
    report = detector.detect_all(summaries or {})

    result = _make_result(True, {
        "total_conflicts": report.total_count,
        "metric_conflicts": len(report.metric_conflicts),
        "constraint_violations": len(report.constraint_violations),
        "spatial_conflicts": len(report.spatial_conflicts),
        "summary": report.summary if hasattr(report, "summary") else "",
    })
    return Command(update={"messages": [_to_tool_message(result, tool_call_id)]})


@tool
def allocate_zones(
    targets: dict,
    constraints: list,
    mode: str = "greedy",
    gis_data: Annotated[Dict[str, Optional[Dict[str, Any]]], InjectedState("gis_data")] = None,
    kg_constraints: Annotated[List[Dict[str, Any]], InjectedState("kg_constraints")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """基于约束分配功能分区（永久基本农田/建设区/生态区/一般农地）。
    使用约束驱动分配器，确保分区满足知识图谱中的约束条件。

    Args:
        targets: 分区面积目标 {"永久基本农田保护区": 78.83, "村庄建设区": 30.50, ...}
        constraints: 约束列表（可使用 KG 缓存的约束，传入空列表则自动使用）
        mode: 分配模式 "greedy"(默认) 或 "mip"(混合整数规划)
    """
    from app.services.modules.gis.layout.optimizer import ConstraintDrivenAllocator

    landuse_geojson = (gis_data or {}).get("landuse_current_geojson", {})
    all_constraints = constraints if constraints else (kg_constraints or [])

    allocator = ConstraintDrivenAllocator()
    result_geojson = allocator.solve(
        landuse_geojson=landuse_geojson,
        targets=targets,
        constraints=all_constraints,
        mode=mode,
    )

    feature_count = len(result_geojson.get("features", []))
    changed = sum(1 for f in result_geojson.get("features", [])
                  if f.get("properties", {}).get("changed", False))

    result = _make_result(True, {
        "total_features": feature_count,
        "changed_features": changed,
        "change_rate": f"{changed / feature_count * 100:.1f}%" if feature_count > 0 else "0%",
    })
    return Command(update={"messages": [_to_tool_message(result, tool_call_id)]})


@tool
def generate_layout(
    intent: dict,
    gis_data: Annotated[Dict[str, Optional[Dict[str, Any]]], InjectedState("gis_data")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """生成多图层空间布局。
    图层类型: boundary, function_zone, planning_zone, sensitivity_zone, infrastructure, facility_point, development_axis

    Args:
        intent: 规划意图字典（zones, facilities, axes, constraints, metadata）
    """
    from app.services.modules.gis.layout.engine import SpatialLayoutEngine

    engine = SpatialLayoutEngine()
    spatial_intent = _dict_to_intent(intent)

    gd = gis_data or {}
    configs = engine.generate_layout(
        intent=spatial_intent,
        boundary_geojson=gd.get("boundary_geojson"),
        landuse_current_geojson=gd.get("landuse_current_geojson"),
        protection_zones=gd.get("protection_zones"),
        road_geojson=gd.get("road_geojson"),
        hazard_points_geojson=gd.get("hazard_points_geojson"),
    )

    layer_types = [c.get("layerType", "unknown") for c in configs]

    result = _make_result(True, {
        "layer_count": len(configs),
        "layer_types": layer_types,
    })
    return Command(
        update={
            "layout_configs": configs,
            "messages": [_to_tool_message(result, tool_call_id)],
        },
    )


@tool
def validate_layout(
    layout_configs: list,
    constraints: list,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """验证布局的分区面积约束和完整性。
    检查分区面积、完整性、重叠、保护地块和最小面积阈值。

    Args:
        layout_configs: GIS 图层配置列表
        constraints: 约束列表 [{"field": ..., "operator": ..., "value": ...}, ...]
    """
    from app.services.modules.gis.layout.validator import LayoutValidator

    validator = LayoutValidator()
    report = validator.validate(layout_configs, constraints)

    violation_data = []
    for v in report.violations[:10]:
        violation_data.append({
            "check": v.check,
            "severity": v.severity,
            "message": v.message,
            "details": v.details,
        })

    result = _make_result(report.status == "pass", {
        "status": report.status,
        "total_violations": report.total_violations,
        "violations": violation_data,
        "warnings": report.warnings[:5],
    })
    return Command(update={"messages": [_to_tool_message(result, tool_call_id)]})


def _dict_to_intent(intent_dict: dict) -> "UnifiedSpatialIntent":
    zones = []
    for z in intent_dict.get("zones", []):
        direction = z.get("direction", "center")
        if isinstance(direction, str):
            direction = _safe_enum(Direction, direction)
        density = z.get("density", "medium")
        if isinstance(density, str):
            density = _safe_enum(Density, density)
        zones.append(ZoneIntent(
            zone_id=z.get("zone_id", ""),
            land_use=z.get("land_use", ""),
            dlbm=z.get("dlbm", ""),
            area_ratio=z.get("area_ratio", 0.0),
            direction=direction,
            reference_feature=z.get("reference_feature", ""),
            adjacent_to=z.get("adjacent_to", []),
            avoid_adjacent_to=z.get("avoid_adjacent_to", []),
            density=density,
            preserve_existing=z.get("preserve_existing", True),
            dlbm_aliases=z.get("dlbm_aliases", []),
        ))

    return UnifiedSpatialIntent(
        zones=zones,
        metadata=intent_dict.get("metadata", {}),
    )
