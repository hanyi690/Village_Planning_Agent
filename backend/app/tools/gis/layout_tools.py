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
import re
from typing import Dict, Any, List, Optional, Tuple, Annotated
from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger
from app.services.modules.gis.layout.planning_intent import (
    UnifiedSpatialIntent, ZoneIntent, FacilityIntent,
    AxisIntent, ConstraintIntent, Direction, Density,
)
from app.services.modules.gis.utils.geo_utils import safe_unary_union

logger = get_logger(__name__)

_LLM_REQUEST_TIMEOUT = 120

SPATIAL_DIMS = [
    "spatial_structure",
    "land_use_planning",
    "settlement_planning",
    "public_service",
    "ecological",
    "traffic_planning",
    "infrastructure_planning",
    "industry",
    "heritage",
    "disaster_prevention",
    "landscape",
    "population",
    "natural_environment",
]


def _make_result(success: bool, data: Any = None, error: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"success": success}
    if data is not None:
        payload["data"] = data
    if error:
        payload["error"] = error
    return payload


def _to_tool_message(result: Dict[str, Any], tool_call_id: str) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(result, ensure_ascii=False, default=str),
        tool_call_id=tool_call_id,
    )


def _safe_enum(enum_cls, value, default=None):
    try:
        return enum_cls(value)
    except (ValueError, KeyError):
        fallback = default or list(enum_cls)[0]
        logger.warning("Invalid %s value: %r, using %s", enum_cls.__name__, value, fallback)
        return fallback


def _prepare_parse_context(
    reports: Dict[str, Dict[str, Any]],
) -> Tuple[str, str]:
    """Build planning context text from reports for structured parse.

    Returns (planning_context, error_message).
    """
    from app.services.modules.parsing.prompts import build_planning_context

    context = build_planning_context(reports)
    if not context:
        return "", "无可用规划报告文本"
    return context, ""


async def _aparse_reports_to_intent(
    reports: Dict[str, Dict[str, Any]],
    village_name: str,
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Async: two-layer architecture — metric anchors + Instructor structured output.

    Layer 1: _extract_metric_anchors() — deterministic, zero LLM calls.
    Layer 2: structured_parse(IntentOutput) — Instructor + Pydantic schema + max_retries=3.
    Then: semantic validation + area_ratio normalization (if needed).
    """
    from app.services.modules.parsing.metric_anchors import extract_metric_anchors
    from app.services.modules.parsing.schemas import IntentOutput
    from app.services.modules.parsing.structured_output import structured_parse_with_correction
    from app.services.modules.parsing.prompts import format_structured_parse_prompt, format_anchors_text
    from app.services.modules.parsing.validator import semantic_validate, normalize_area_ratios

    # Layer 1: Extract metric anchors (GIS data > text metrics > regex)
    anchors = extract_metric_anchors(reports, gis_data=gis_data)

    # Build prompt
    planning_context, err = _prepare_parse_context(reports)
    if err:
        return _make_result(False, error=err)

    anchors_dict = anchors.to_anchor_dict()
    anchors_text = format_anchors_text(anchors_dict)

    prompt = format_structured_parse_prompt(
        village_name=village_name,
        anchors=anchors_text,
        planning_context=planning_context,
    )

    # Layer 2: Instructor structured parse with semantic validation
    try:
        intent_output: IntentOutput = await structured_parse_with_correction(
            content=prompt,
            output_schema=IntentOutput,
            anchors=anchors_dict,
            validate_fn=semantic_validate,
        )
    except Exception as e:
        logger.error("_aparse_reports_to_intent structured parse failed: %s", e)
        return _make_result(False, error=f"结构化解析失败: {e}")

    # Normalize area_ratios if needed (preserved from old _postprocess_llm_response)
    intent_output = normalize_area_ratios(intent_output)

    # Convert Pydantic -> dataclass
    intent = _output_to_intent(intent_output)
    zone_summary = ", ".join(f"{z.land_use}({z.area_ratio:.1%})" for z in intent.zones)

    return _make_result(True, {
        "zone_count": len(intent.zones),
        "facility_count": len(intent.facilities),
        "axis_count": len(intent.axes),
        "zones": zone_summary,
        "intent_json": intent_output.model_dump(),
        "anchor_confidence": anchors.confidence,
    })


def _parse_reports_to_intent(
    reports: Dict[str, Dict[str, Any]],
    village_name: str,
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Sync wrapper for _aparse_reports_to_intent (used by @tool)."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                _aparse_reports_to_intent(reports, village_name, gis_data),
            )
            return future.result(timeout=_LLM_REQUEST_TIMEOUT)
    else:
        return asyncio.run(_aparse_reports_to_intent(reports, village_name, gis_data))


@tool
def parse_planning_text(
    reports: Annotated[Dict[str, Dict[str, Any]], InjectedState("reports")],
    village_name: Annotated[str, InjectedState("village_name")],
    gis_data: Annotated[Optional[Dict[str, Any]], InjectedState("gis_data")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """从规划报告自动解析空间布局意图(UnifiedSpatialIntent)。
    解析后的 intent 可直接传给 generate_layout 生成地图图层。
    无需参数，报告数据和GIS数据自动从状态注入。

    解析内容：功能分区(zones)、设施布局(facilities)、发展轴(axes)、约束(constraints)。
    """
    result = _parse_reports_to_intent(reports=reports, village_name=village_name, gis_data=gis_data)
    return Command(update={"messages": [_to_tool_message(result, tool_call_id)]})


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
    kg.build_from_reports(reports=reports, landuse_geojson=landuse_geojson, gis_data=gis_data)

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
    kg_turtle: Annotated[str, InjectedState("kg_turtle")] = "",
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """基于约束分配功能分区（永久基本农田/建设区/生态区/一般农地）。
    使用约束驱动分配器，确保分区满足知识图谱中的约束条件。

    Args:
        targets: 分区面积目标 {"农田保护区": 78.83, "村庄建设区": 30.50, ...}
        constraints: 约束列表（可使用 KG 缓存的约束，传入空列表则自动使用）
        mode: 分配模式 "greedy"(默认) 或 "mip"(混合整数规划)
    """
    from app.services.modules.gis.layout.optimizer import ConstraintDrivenAllocator
    from app.services.modules.gis.layout.kg import PlanningKG

    landuse_geojson = (gis_data or {}).get("landuse_current_geojson", {})
    all_constraints = constraints if constraints else (kg_constraints or [])

    # Extract adjacency map from KG if available
    adjacency_map = None
    if kg_turtle:
        try:
            kg = PlanningKG.from_turtle(kg_turtle)
            adjacency_map = kg.get_adjacency_map()
        except Exception as e:
            logger.warning("Failed to extract adjacency from KG: %s", e)

    allocator = ConstraintDrivenAllocator(adjacency_map=adjacency_map)
    result_geojson = allocator.solve(
        landuse_geojson=landuse_geojson,
        targets=targets,
        constraints=all_constraints,
        mode=mode,
    )

    feature_count = len(result_geojson.get("features", []))
    changed = sum(1 for f in result_geojson.get("features", [])
                  if f.get("properties", {}).get("changed", False))

    summary_data = {
        "total_features": feature_count,
        "changed_features": changed,
        "change_rate": f"{changed / feature_count * 100:.1f}%" if feature_count > 0 else "0%",
    }
    result = _make_result(True, summary_data)
    return Command(update={
        "messages": [_to_tool_message(result, tool_call_id)],
        "allocated_geojson": result_geojson,
        "allocation_summary": summary_data,
    })


@tool
def generate_layout(
    intent: dict,
    gis_data: Annotated[Dict[str, Optional[Dict[str, Any]]], InjectedState("gis_data")] = None,
    kg_constraints: Annotated[List[Dict[str, Any]], InjectedState("kg_constraints")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """生成多图层空间布局。
    图层类型: boundary, function_zone, planning_zone, sensitivity_zone, infrastructure, facility_point, development_axis

    Args:
        intent: 规划意图字典（zones, facilities, axes, constraints, metadata）
    """
    from app.services.modules.gis.layout.engine import SpatialLayoutEngine

    engine = SpatialLayoutEngine()
    if kg_constraints:
        engine.set_kg_constraints(kg_constraints)
    spatial_intent = _dict_to_intent(intent)

    gd = gis_data or {}
    configs = engine.generate_layout(
        intent=spatial_intent,
        boundary_geojson=gd.get("boundary_geojson"),
        landuse_current_geojson=gd.get("landuse_current_geojson"),
        protection_zones=gd.get("protection_zones"),
        road_geojson=gd.get("road_geojson"),
        hazard_points_geojson=gd.get("hazard_points_geojson"),
        construction_zone_geojson=gd.get("construction_zone_geojson"),
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
    auto_retry: bool = True,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """验证布局的分区面积约束和完整性。
    检查分区面积、完整性、重叠、保护地块和最小面积阈值。
    验证失败时自动生成调整建议(retry_suggestion)，供 Agent 调整后重试。

    Args:
        layout_configs: GIS 图层配置列表
        constraints: 约束列表 [{"field": ..., "operator": ..., "value": ...}, ...]
        auto_retry: 是否生成重试建议（默认 True）
    """
    from app.services.modules.gis.layout.validator import LayoutValidator

    validator = LayoutValidator()

    if auto_retry:
        report = validator.validate_with_retry(
            layout_configs, constraints, max_retries=3
        )
        result_data = report.to_dict()
    else:
        report = validator.validate(layout_configs, constraints)
        result_data = report.to_dict()

    result = _make_result(result_data.get("passed", False), result_data)
    return Command(update={"messages": [_to_tool_message(result, tool_call_id)]})


@tool
def measure_divergence(
    current_geojson: str,
    planned_geojson: str,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """量化现状布局与规划布局的差异。
    计算面积差异、变更地块数、变更率和空间紧凑度。

    Args:
        current_geojson: 现状用地 GeoJSON (FeatureCollection JSON 字符串)
        planned_geojson: 规划布局 GeoJSON (FeatureCollection JSON 字符串)
    """
    try:
        import geopandas as gpd
        from shapely import from_geojson
    except ImportError:
        result = _make_result(False, error="geopandas/shapely not available")
        return Command(update={"messages": [_to_tool_message(result, tool_call_id)]})

    def _parse_geojson_area_and_types(geojson_str: str):
        """Parse GeoJSON, return (total_area_ha, zone_area_map, feature_count, shapely_geoms)."""
        try:
            data = json.loads(geojson_str)
        except (json.JSONDecodeError, TypeError):
            return 0.0, {}, 0, []

        features = data.get("features", [])
        zone_areas: Dict[str, float] = {}
        total_area = 0.0
        geoms = []

        for feat in features:
            props = feat.get("properties", {})
            g = feat.get("geometry", {})
            if not g or not g.get("coordinates"):
                continue

            zone_type = (
                props.get("assigned_zone", "")
                or props.get("zone_type", "")
                or props.get("land_use", "")
            )

            try:
                geom = from_geojson(json.dumps(g))
                if geom.is_empty:
                    continue
                geoms.append(geom)
                geom_3857 = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs("EPSG:3857")[0]
                area_ha = geom_3857.area / 10000
                total_area += area_ha
                if zone_type:
                    zone_areas[zone_type] = zone_areas.get(zone_type, 0) + area_ha
            except Exception:
                continue

        return total_area, zone_areas, len(features), geoms

    current_area, current_zones, current_count, _ = _parse_geojson_area_and_types(current_geojson)
    planned_area, planned_zones, planned_count, planned_geoms = _parse_geojson_area_and_types(planned_geojson)

    # Area difference
    area_diff_ha = abs(planned_area - current_area)

    # Per-zone differences
    all_zones = set(list(current_zones.keys()) + list(planned_zones.keys()))
    zone_diffs = {}
    changed_zones = 0
    for zt in all_zones:
        c_area = current_zones.get(zt, 0)
        p_area = planned_zones.get(zt, 0)
        diff = p_area - c_area
        zone_diffs[zt] = {
            "current_ha": round(c_area, 2),
            "planned_ha": round(p_area, 2),
            "diff_ha": round(diff, 2),
        }
        if abs(diff) > 0.5:
            changed_zones += 1

    # Change rate
    total_changed_area = sum(abs(zd["diff_ha"]) for zd in zone_diffs.values())
    change_rate = total_changed_area / max(current_area, 1) * 100

    # Compactness (Isoperimetric Quotient for planned layout)
    compactness = 0.0
    try:
        if planned_geoms:
            union_3857 = gpd.GeoSeries(
                [safe_unary_union(planned_geoms)], crs="EPSG:4326"
            ).to_crs("EPSG:3857")[0]
            area = union_3857.area
            perimeter = union_3857.length
            if perimeter > 0:
                compactness = 4 * 3.14159 * area / (perimeter ** 2)
    except Exception:
        pass

    result = _make_result(True, {
        "area_diff_ha": round(area_diff_ha, 2),
        "current_area_ha": round(current_area, 2),
        "planned_area_ha": round(planned_area, 2),
        "current_feature_count": current_count,
        "planned_feature_count": planned_count,
        "changed_zones": changed_zones,
        "change_rate_pct": round(change_rate, 1),
        "compactness_index": round(compactness, 4),
        "zone_diffs": zone_diffs,
    })
    return Command(update={"messages": [_to_tool_message(result, tool_call_id)]})


def _output_to_intent(output: Any) -> "UnifiedSpatialIntent":
    """Convert Pydantic IntentOutput to UnifiedSpatialIntent dataclass.

    Simpler than _dict_to_intent because schema guarantees valid values.
    """
    zones = [
        ZoneIntent(
            zone_id=z.zone_id,
            land_use=z.land_use,
            dlbm=z.dlbm,
            area_ratio=z.area_ratio,
            direction=_safe_enum(Direction, z.direction),
            reference_feature=z.reference_feature,
            adjacent_to=z.adjacent_to,
            avoid_adjacent_to=z.avoid_adjacent_to,
            density=_safe_enum(Density, z.density),
            preserve_existing=True,
            dlbm_aliases=[],
        )
        for z in output.zones
    ]

    facilities = [
        FacilityIntent(
            facility_id=f.facility_id,
            facility_type=f.facility_type,
            target_zone="",
            location_hint=f.location_hint,
            status=f.status,
        )
        for f in output.facilities
    ]

    axes = [
        AxisIntent(
            axis_id=a.axis_id,
            axis_type=a.axis_type,
            direction=_safe_enum(Direction, a.direction),
            connects=[],
            label=a.reference_feature,
        )
        for a in output.axes
    ]

    return UnifiedSpatialIntent(
        zones=zones,
        facilities=facilities,
        axes=axes,
        constraints=[],
        metadata=output.metadata,
    )


def _dict_to_intent(intent_dict: dict) -> "UnifiedSpatialIntent":
    zones = [_parse_zone(z) for z in intent_dict.get("zones", [])]
    facilities = [_parse_facility(f) for f in intent_dict.get("facilities", [])]
    axes = [_parse_axis(a) for a in intent_dict.get("axes", [])]
    constraints = [_parse_constraint(c) for c in intent_dict.get("constraints", [])]

    return UnifiedSpatialIntent(
        zones=zones,
        facilities=facilities,
        axes=axes,
        constraints=constraints,
        metadata=intent_dict.get("metadata", {}),
    )


def _parse_zone(z: dict) -> ZoneIntent:
    direction = z.get("direction", "center")
    if isinstance(direction, str):
        direction = _safe_enum(Direction, direction)
    elif isinstance(direction, dict):
        direction = _safe_enum(Direction, direction.get("direction", "center"))
    density = z.get("density", "medium")
    if isinstance(density, str):
        density = _safe_enum(Density, density)
    return ZoneIntent(
        zone_id=z.get("zone_id", ""),
        land_use=z.get("land_use", ""),
        dlbm=z.get("dlbm", ""),
        area_ratio=z.get("area_ratio", 0.0),
        direction=direction,
        reference_feature=z.get("reference_feature", z.get("location_bias", {}).get("reference_feature", "")),
        adjacent_to=z.get("adjacent_to", z.get("adjacency", {}).get("adjacent_to", [])),
        avoid_adjacent_to=z.get("avoid_adjacent_to", z.get("adjacency", {}).get("avoid_adjacent_to", [])),
        density=density,
        preserve_existing=z.get("preserve_existing", True),
        dlbm_aliases=z.get("dlbm_aliases", []),
    )


def _parse_facility(f: dict) -> FacilityIntent:
    return FacilityIntent(
        facility_id=f.get("facility_id", ""),
        facility_type=f.get("facility_type", ""),
        target_zone=f.get("target_zone", ""),
        location_hint=f.get("location_hint", ""),
        status=f.get("status", "existing"),
    )


def _parse_axis(a: dict) -> AxisIntent:
    direction = a.get("direction", "center")
    if isinstance(direction, str):
        direction = _safe_enum(Direction, direction)
    return AxisIntent(
        axis_id=a.get("axis_id", ""),
        axis_type=a.get("axis_type", "secondary"),
        direction=direction,
        connects=a.get("connects", []),
        label=a.get("label", ""),
    )


def _parse_constraint(c: dict) -> ConstraintIntent:
    return ConstraintIntent(
        constraint_id=c.get("constraint_id", ""),
        constraint_type=c.get("constraint_type", ""),
        geometry_ref=c.get("geometry_ref", ""),
        strict=c.get("strict", True),
    )
