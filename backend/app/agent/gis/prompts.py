"""GIS Agent prompts - system prompt and spatial layout parsing prompts."""

GIS_AGENT_SYSTEM_PROMPT = """你是村庄空间布局规划助手。根据规划报告和 GIS 数据生成空间布局。

工作流程：
1. build_knowledge_graph(): 构建知识图谱（必须首先调用，且只调一次）。数据自动注入，无需传参。
2. query_knowledge_graph(template_name, ...): 查询约束（建设用地规模、耕地保有量、生态红线）
3. detect_conflicts(): 检测维度间冲突。摘要数据自动注入，无需传参。
4. allocate_zones(targets, constraints, mode): 分配功能分区（永久基本农田/建设区/生态区/一般农地）。用地数据自动注入。
5. generate_layout(intent): 生成多图层布局。GIS 数据自动注入，只需提供规划意图。
6. validate_layout(layout_configs, constraints): 验证结果（不满足则回到步骤 4 调整）

规则：
- 先构建 KG 才能查询约束
- 约束优先级：农田保护 > 生态保护 > 建设发展
- validate_layout 失败必须根据 violations 调整 targets，而非忽略
- 最多重试 3 次；如果 3 次仍失败，返回最佳结果并标注未满足的约束
- 每步输出关键数字（面积、比例、冲突数）
"""

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
{{
  "zones": [
    {{
      "zone_id": "Z01",
      "land_use": "居住用地",
      "area_ratio": 0.35,
      "location_bias": {{
        "direction": "center",
        "reference_feature": "靠近村委会"
      }},
      "adjacency": {{
        "adjacent_to": ["公共服务用地"],
        "avoid_adjacent_to": ["产业用地"]
      }},
      "density": "medium"
    }}
  ],
  "facilities": [
    {{
      "facility_id": "F01",
      "facility_type": "村委会",
      "status": "现状保留",
      "location_hint": "村庄中心位置",
      "service_radius": 500
    }}
  ],
  "axes": [
    {{
      "axis_id": "A01",
      "axis_type": "primary",
      "direction": "east-west",
      "reference_feature": "沿东西向主干道"
    }}
  ],
  "rationale": "规划布局总体说明...",
  "development_axes": ["沿东西向主干道发展"]
}}
```

**用地类型选项** (land_use): 居住用地, 产业用地, 公共服务用地, 生态绿地, 交通用地, 水域, 农业用地, 商业用地

**位置偏向选项** (location_bias.direction): center, north, south, east, west, northeast, northwest, southeast, southwest, edge

**设施状态选项** (status): 现状保留, 规划新建, 规划改扩建, 规划迁建

**发展轴类型选项** (axis_type): primary, secondary, corridor, connector

**约束规则**:
1. `area_ratio` 总和必须接近 1.0（误差不超过 5%）
2. `zones` 至少包含 3 个地块
3. 每个地块的 `land_use` 必须是有效用地类型
4. `facilities` 中的 `location_hint` 应清晰描述位置

请输出结构化规划方案 JSON:
"""

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
{{
  "zones": [
    {{"zone_id": "...", "land_use": "...", "area_ratio": ...}}
  ]
}}
```
"""

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
{{
  "coordinates": [lon, lat],
  "confidence": "high/medium/low",
  "reason": "位置选择原因"
}}
```
"""


def format_parse_prompt(
    planning_text: str,
    village_name: str,
    total_area: str = "未知",
    current_land_use: str = "未知",
) -> str:
    return SPATIAL_LAYOUT_PARSE_PROMPT.format(
        planning_text=planning_text,
        village_name=village_name,
        total_area=total_area,
        current_land_use=current_land_use,
    )


def format_zone_adjustment_prompt(zones: list, current_sum: float) -> str:
    zones_str = "\n".join([
        f"- {z.get('zone_id')}: {z.get('land_use')} ({z.get('area_ratio')})"
        for z in zones
    ])
    return ZONE_AREA_ADJUSTMENT_PROMPT.format(
        current_zones=zones_str,
        current_sum=current_sum,
    )


def format_facility_location_prompt(
    facility_type: str,
    location_hint: str,
    village_center: tuple,
    road_network: str = "无数据",
    existing_facilities: str = "无数据",
    planned_zones: str = "无数据",
) -> str:
    return FACILITY_LOCATION_RESOLUTION_PROMPT.format(
        facility_type=facility_type,
        location_hint=location_hint,
        village_center=village_center,
        road_network=road_network,
        existing_facilities=existing_facilities,
        planned_zones=planned_zones,
    )
