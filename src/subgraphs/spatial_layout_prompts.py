"""
Spatial Layout Prompts

Prompts for parsing planning text into structured JSON using Flash LLM.
Part of the new GIS visualization architecture.

Reference: GIS Planning Visualization Architecture Refactoring Plan
"""

from typing import Dict, Any


# ==========================================
# Main Parsing Prompt
# ==========================================

SPATIAL_LAYOUT_PARSE_PROMPT = """
你是乡村规划专家中的**空间结构解析助手**。

**任务**: 将规划文本解析为结构化 JSON 数据，用于 GIS 空间布局生成。

**规划文本**:
{planning_text}

**项目概况**:
- 村庄名称: {village_name}
- 总面积: {total_area} km2
- 现状用地结构: {current_land_use}

**输出格式** (严格 JSON):
```json
{
  "zones": [
    {
      "zone_id": "Z01",
      "land_use": "居住用地",
      "area_ratio": 0.35,
      "location_bias": {
        "direction": "center",
        "reference_feature": "靠近村委会"
      },
      "adjacency": {
        "adjacent_to": ["公共服务用地"],
        "avoid_adjacent_to": ["产业用地"]
      },
      "density": "medium"
    }
  ],
  "facilities": [
    {
      "facility_id": "F01",
      "facility_type": "村委会",
      "status": "现状保留",
      "location_hint": "村庄中心位置",
      "service_radius": 500
    }
  ],
  "axes": [
    {
      "axis_id": "A01",
      "axis_type": "primary",
      "direction": "east-west",
      "reference_feature": "沿东西向主干道"
    }
  ],
  "rationale": "规划布局总体说明...",
  "development_axes": ["沿东西向主干道发展"]
}
```

**用地类型选项** (land_use):
- 居住用地: 住宅、宅基地等
- 产业用地: 工业、农业生产设施等
- 公共服务用地: 村委会、学校、医疗站等
- 生态绿地: 公园、绿地、防护林等
- 交通用地: 道路、停车场等
- 水域: 河流、水库、池塘等
- 农业用地: 耕地、园地、林地等
- 商业用地: 商店、市场等

**位置偏向选项** (location_bias.direction):
- center: 村庄中心区域
- north/south/east/west: 四个基本方位
- northeast/northwest/southeast/southwest: 四个角方位
- edge: 村庄边缘区域

**设施状态选项** (status):
- 现状保留: 已有设施，保留不动
- 规划新建: 规划新增设施
- 规划改扩建: 已有设施，规划扩建
- 规划迁建: 已有设施，规划搬迁

**发展轴类型选项** (axis_type):
- primary: 主要发展轴
- secondary: 次要发展轴
- corridor: 发展走廊
- connector: 连接线

**约束规则**:
1. `area_ratio` 总和必须接近 1.0（误差不超过 5%）
2. `zones` 至少包含 3 个地块
3. 每个地块的 `land_use` 必须是有效用地类型
4. `facilities` 中的 `location_hint` 应清晰描述位置

**解析要点**:
- 提取规划文本中的用地分类、面积比例信息
- 根据描述推断位置偏向（如"东部"对应 east）
- 识别公共服务设施及其位置描述
- 提取发展轴线描述

请输出结构化规划方案 JSON:
"""


# ==========================================
# Zone Area Adjustment Prompt
# ==========================================

ZONE_AREA_ADJUSTMENT_PROMPT = """
调整以下地块面积比例，使其总和精确为 1.0:

当前地块:
{current_zones}

当前总和: {current_sum}

调整规则:
1. 保持各地块相对大小顺序不变
2. 微调各地块的 area_ratio 使总和为 1.0
3. 优先调整最大的地块

输出调整后的 JSON (仅包含 zones 数组):
```json
{
  "zones": [
    {"zone_id": "...", "land_use": "...", "area_ratio": ...}
  ]
}
```
"""


# ==========================================
# Facility Location Resolution Prompt
# ==========================================

FACILITY_LOCATION_RESOLUTION_PROMPT = """
根据以下信息确定设施的具体坐标:

设施信息:
- 设施类型: {facility_type}
- 位置提示: {location_hint}
- 村庄中心: {village_center}

可用参考数据:
- 道路网络: {road_network}
- 已有设施: {existing_facilities}
- 规划地块: {planned_zones}

请输出设施的推荐坐标 (lon, lat):
```json
{
  "coordinates": [lon, lat],
  "confidence": "high/medium/low",
  "reason": "位置选择原因"
}
```
"""


# ==========================================
# Prompt Formatting Functions
# ==========================================

def format_parse_prompt(
    planning_text: str,
    village_name: str,
    total_area: str = "未知",
    current_land_use: str = "未知"
) -> str:
    """
    Format the main parsing prompt with given parameters.

    Args:
        planning_text: The planning text to parse
        village_name: Village name
        total_area: Total area in km2
        current_land_use: Current land use structure description

    Returns:
        Formatted prompt string
    """
    return SPATIAL_LAYOUT_PARSE_PROMPT.format(
        planning_text=planning_text,
        village_name=village_name,
        total_area=total_area,
        current_land_use=current_land_use
    )


def format_zone_adjustment_prompt(
    zones: list,
    current_sum: float
) -> str:
    """
    Format zone area adjustment prompt.

    Args:
        zones: List of zone definitions
        current_sum: Current sum of area ratios

    Returns:
        Formatted prompt string
    """
    zones_str = "\n".join([
        f"- {z.get('zone_id')}: {z.get('land_use')} ({z.get('area_ratio')})"
        for z in zones
    ])
    return ZONE_AREA_ADJUSTMENT_PROMPT.format(
        current_zones=zones_str,
        current_sum=current_sum
    )


def format_facility_location_prompt(
    facility_type: str,
    location_hint: str,
    village_center: tuple,
    road_network: str = "无数据",
    existing_facilities: str = "无数据",
    planned_zones: str = "无数据"
) -> str:
    """
    Format facility location resolution prompt.

    Args:
        facility_type: Type of facility
        location_hint: Location hint description
        village_center: Village center coordinates (lon, lat)
        road_network: Road network description
        existing_facilities: Existing facilities description
        planned_zones: Planned zones description

    Returns:
        Formatted prompt string
    """
    return FACILITY_LOCATION_RESOLUTION_PROMPT.format(
        facility_type=facility_type,
        location_hint=location_hint,
        village_center=village_center,
        road_network=road_network,
        existing_facilities=existing_facilities,
        planned_zones=planned_zones
    )


# ==========================================
# Zone Type Colors - Import from planning_schema
# ==========================================

# Avoid duplicate definition - import from planning_schema
from ..tools.core.planning_schema import (
    ZONE_TYPE_COLORS as ZONE_TYPE_COLORS,
    FACILITY_STATUS_COLORS as FACILITY_STATUS_COLORS,
)

# Axis colors (unique to this module)
AXIS_TYPE_COLORS = {
    "primary": "#FF0000",
    "secondary": "#00AA00",
    "corridor": "#0000FF",
    "connector": "#888888",
}


__all__ = [
    "SPATIAL_LAYOUT_PARSE_PROMPT",
    "ZONE_AREA_ADJUSTMENT_PROMPT",
    "FACILITY_LOCATION_RESOLUTION_PROMPT",
    "format_parse_prompt",
    "format_zone_adjustment_prompt",
    "format_facility_location_prompt",
    "ZONE_TYPE_COLORS",
    "AXIS_TYPE_COLORS",
    "FACILITY_STATUS_COLORS",
]