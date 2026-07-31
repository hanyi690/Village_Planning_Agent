# Agent A (BLIND KG) — 58 项空间事实 KG 查询

## 角色约束（严格遵守）

- **只能使用 `kg_tool_cli` CLI 工具**，通过 Bash 调用
- **禁止**: Read / Glob / Grep / WebFetch / exa_web_search / 任何文件访问
- **唯一信息来源**: 金田村 Knowledge Graph（32k RDF 三元组，660 地块）

## 工具调用方式

```bash
cd F:\project\Village_Planning_Agent\backend
python -m scripts.kg_validation.kg_tool_cli <tool_name> [args...]
```

每次调用返回 JSON，包含 `result`、`tool`、`elapsed_ms` 字段。
长列表自动截断到 10 项 + `total_count`。

## 36 个 KG 查询工具

### OVERVIEW（先用这些了解全貌）
```
get_village_cognition                    → 村庄三层认知（context_block + layer_cards + constraint_block）
get_village_semantic_summary             → 实体数量、关系数量、规划分区分布
get_layer_group_semantics [group]        → 图层组详情，group=None 返回全部
get_village_constraint_coverage          → 约束覆盖（灾差点、耕地红线等）
```

### ENTITY_DETAIL（查单个实体）
```
get_entity_context <entity_uri>          → 实体属性 + 关系描述
get_entity_relations <entity_uri>        → 实体的所有关系列表
get_entity_semantics <中文标签>          → 按中文标签查实体（如"水田"、"园地"）
get_parcel_semantic_context <bsm>        → 地块语义上下文
get_entity_by_bsm <bsm> [entity_type]    → 按 bsm 跨层查找实体
```

### LIST_SEMANTIC（批量语义描述）
```
get_parcels_semantic_list                → 所有地块中文描述（截断到5条）
get_parcel_detail_semantic <bsm>         → 单地块自然语言详情
get_parcel_neighbors_semantic <bsm>      → 邻居地块 + 共享边长
get_facilities_semantic_list             → 所有设施点（截断到10条）
get_road_network_semantic                → 所有道路语义描述
get_designated_zones_semantic            → 保护区/管控区语义
```

### SPARQL（结构化查询）
```
query_kg <template_name>                 → SPARQL 模板查询
  可用模板: get_village_parcels, count_by_zone_type, count_by_vne,
            count_by_planning_zone, get_village_anchors, get_water_bodies,
            get_facility_locations, get_road_network, get_parcels_by_dlbm,
            get_parcels_by_zone_type, get_adjacent_parcels, get_zone_restrictions,
            check_protected_parcels, get_designated_zones, get_parcels_near_point,
            count_entity_types, get_terrain_profile, get_parcels_by_slope,
            get_parcels_by_aspect, get_facilities_by_type, get_facility_serve_areas,
            get_water_bodies, get_adjacent_parcels_with_length,
            get_parcels_within_distance_of_entity
```

### RAW_GRAPH（直接 RDF 查询）
```
kg_query <sparql_string>                 → 直接执行 SPARQL，返回 JSON
kg_predicate_objects <entity_uri>        → 实体的所有 predicate-object 对
kg_triples [s] [p] [o]                   → 三元组查询（None 表示通配）
kg_to_turtle                             → 整个图转 Turtle（截断前2000字符）
```

### INSTANCE（实例级别）
```
get_parcel_count                         → 地块总数
get_triple_count                         → 三元组总数
get_adjacency_map                        → 邻接图（截断到20条）
```

### TOPOLOGY（空间拓扑）
```
get_parcels_within_distance_of_entity <entity_uri> [max_dist_m]
get_adjacent_parcels_with_length <bsm>
get_connected_parcels <parcel_uri>
get_parcels_by_bsm_list <bsm1,bsm2,...>
```

### L4 PLANNING（规划状态）
```
get_effective_land_use <bsm> [version]   → version: current / planned
get_effective_area_ha <bsm> [version]
get_plan_changes [version]               → version: current / planned
get_planned_parcels_in_zone <zone_type> [version]
check_constraint_violations [version]
compare_versions <version_a> <version_b>
```

## 58 项空间事实（逐项查询并写入 answers.json）

你必须**为每一项**调用至少 1 个 KG 工具（最多 5 个），将答案填入 JSON。

```json
{
  "fact_id": "F01",
  "question": "村庄总用地面积",
  "agent_A_answer": "从 KG 工具得到的真实答案（数值或描述）",
  "tools_used": ["get_village_semantic_summary"],
  "confidence": "high/medium/low",
  "gap_note": "如工具返回不足，在此说明"
}
```

| fact_id | 问题 | 场景 | 预期值 | kg_query_hint |
|---------|------|------|--------|---------------|
| F01 | 村庄总用地面积 | area_ha | 2352.89 公顷 | SUM(Parcel.area_ha) |
| F02 | 农业用地面积及占比 | percentage | 1960.70 公顷 (83.33%) | dlbm 01/02/03 类 SUM |
| F03 | 建设用地面积及占比 | percentage | 30.17 公顷 (1.28%) | dlbm 07/12 类 SUM |
| F04 | 生态用地面积及占比 | percentage | 362.02 公顷 (15.39%) | dlbm 03/11 + 水体 SUM |
| F05 | 耕地面积（水田） | area_ha | 85.2 公顷 | dlbm=0101 SUM |
| F06 | 林地面积占比 | percentage | 90% (2193.3 公顷) | dlbm 0301-0307 SUM |
| F07 | 水域面积及占比 | percentage | 35.99 公顷 (1.53%) | dlbm 11xx SUM |
| F08 | 现状建筑数量 | count | 583 处 | count by dlbm=07 |
| F09 | 12 个自然村完整名单 | name_set | 园寨、田坑、社前、分水、清明、塘笃、长塘、炉池、肩丰、营仔、新山、黄竹 | get_village_anchors + annotation |
| F10 | 园寨是行政村，村委会所在地 | text_description | 园寨是行政村，村委会所在地 | entity_relations AdministrativeVillage |
| F11 | 主要建筑集中区 | text_description | 主要建筑集中于园寨和马头段 | parcels_by_dlbm(0702) bbox |
| F12 | 122 乡道东西方向 | text_description | 122乡道是村中唯一的东西方向道路 | road network orientation |
| F13 | 村道硬化总长度 | text_description | 村道硬化总长度16km | road network length SUM |
| F14 | 供水管道长度 | distance_m | 6000 米 | pipeline length SUM |
| F15 | 公交站点数量及分布 | count | 3 处，村庄西南部 | facility type=公交站点 |
| F16 | 村委会设置 | text_description | 村委会设在园寨村，含公共文化服务中心、卫生站、小学、幼儿园 | facility near 园寨 |
| F17 | 停车场位置面积 | text_description | 停车场1处，位于园寨，面积100平方米 | facility type=停车场 |
| F18 | 文化广场数量 | count | 2 个 | facility type=文化广场 |
| F19 | 篮球场数量 | count | 1 个 | facility type=篮球场 |
| F20 | 祠堂数量及位置 | count | 3座，社前、黄竹、田坑 | annotation label=祠堂 |
| F21 | 变压器数量及分布 | count | 9个，营仔、社前、田坑、塘笃、黄竹 | facility type=变压器 |
| F22 | 金田河走向 | direction | 西南至东北，汇入石窟河 | water body bbox orientation |
| F23 | 水电站数量 | count | 3 个 | facility type=水电站 near water |
| F24 | 崩塌/滑坡隐患点数量 | count | 崩塌5处+滑坡35处 | constraint coverage by type |
| F25 | 千年古檀树位置 | text_description | 千年古檀树在营仔，直径2.8米，树龄1200年 | annotation name=古檀 |
| F26 | 蕈树位置/树龄 | text_description | 蕈树树龄550年 | annotation name=蕈树 |
| F27 | 南粤古驿道位置 | text_description | 南粤古驿道在炉池村 | annotation name=古驿道 |
| F28 | 茶亭遗址 | name_set | 炉池、茶亭、盐米古道 | annotation name=茶亭 |
| F29 | 古檀林森林公园 | text_description | 古檀林主题森林公园在营子里 | annotation name=古檀林 |
| F30 | 人口数据 | text_description | 户籍人口1403人，常住人口约500人 | AdministrativeVillage attrs |
| F31 | 自然村户数 | text_description | 12个自然村总户数325户 | village attrs household_count |
| F32 | 发展目标 | text_description | 梅州市特色南药综合开发示范村 | ZoneTarget land_use |
| F33 | 形象定位 | text_description | 金山藏古檀，南药兴田庄 | ZoneTarget name |
| F34 | 空间格局 | text_description | 二心二轴四区 | ZoneTarget cluster count |
| F35 | 园寨村民中心位置 | direction | 金田中南部 | ZoneTarget spatial_hint=园寨 |
| F36 | 黄竹游客中心位置 | direction | 金田中东部 | ZoneTarget spatial_hint=黄竹 |
| F37 | 旅游休闲轴 | planning_project | 森林康养+休闲农业区域 | AxisTarget reference=旅游休闲 |
| F38 | 综合发展轴 | planning_project | 122乡道，南药产业聚集 | AxisTarget reference=122乡道 |
| F39 | 田园生活区位置 | text_description | 金田村中部，村民聚居区 | PlannedZone type=田园生活区 |
| F40 | 产业发展区位置 | direction | 东北部与西南部 | PlannedZone type=产业发展区 |
| F41 | 青山林海区位置 | direction | 西部与东部 | PlannedZone type=青山林海区 |
| F42 | 旅游观光区位置 | direction | 中部和北部 | PlannedZone type=旅游观光区 |
| F43 | 农业用地规划目标 | percentage | 1949.63 公顷 (82.83%) | PlannedParcel SUM by dlbm |
| F44 | 建设用地规划目标 | percentage | 34.03 公顷 (1.45%) | PlannedParcel SUM construction |
| F45 | 生态用地规划目标 | percentage | 369.23 公顷 (15.69%) | PlannedParcel SUM ecology |
| F46 | 宅基地现状面积 | area_ha | 13.72 公顷 | PlannedParcel dlbm=0702 current |
| F47 | 公服设施用地现状 | area_ha | 0.60 公顷 | PlannedParcel dlbm=0810 current |
| F48 | 近期建设内容 | planning_project | 8个方面（生态/农田/基建/公服/历史/产业等） | PlannedState 近期 |
| F49 | 近期河道修复 | distance_m | 1400m（园寨、黄竹） | PlannedParcel type=河道修复 |
| F50 | 近期高标农田位置 | name_set | 田坑、黄竹、肩丰、长塘 | PlannedParcel type=高标准农田 |
| F51 | 近期村道硬化长度 | text_description | 17.8km | PlannedRoad type=村道硬化 |
| F52 | 近期文化广场位置 | name_set | 炉池、肩丰、田坑 | PlannedFacility type=文化广场 |
| F53 | 远期河道修复 | distance_m | 700m（田坑） | PlannedState 远期 河道 |
| F54 | 远期森林步道 | direction | 田坑西部北部到黄竹，7.2km | PlannedRoad type=森林步道 |
| F55 | 远期林下种植园位置 | name_set | 新山、炉池、清明、肩丰 | PlannedState 远期 林下 |
| F56 | 远期养殖农场位置 | text_description | 长塘 | PlannedFacility type=养殖农场 |
| F57 | 调蓄池数量 | count | 3 处 | ControlLine type=调蓄池 |
| F58 | 微型消防站位置 | text_description | 黄竹 | PlannedFacility type=微型消防站 |

## 输出要求

1. 为**每一项**（F01-F58）执行 KG 查询并记录结果
2. 最终输出写入: `output/kg_validation/subagent_A_blind/answers.json`

```json
{
  "agent": "Agent A (BLIND KG)",
  "timestamp": "<ISO 时间>",
  "kg_triple_count": <来自 KG>,
  "kg_parcel_count": <来自 KG>,
  "results": [
    {
      "fact_id": "F01",
      "question": "村庄总用地面积",
      "agent_A_answer": "实际答案（数值或文本）",
      "tools_used": ["tool_name"],
      "confidence": "high/medium/low",
      "gap_note": ""
    },
    ...（共 58 项）
  ]
}
```

3. **每问题最多 5 次工具调用**，超出则记录 `gap_note` 并用已知信息推断
4. 如果工具返回 `{"error": ...}`，记 `confidence: low` + `gap_note: <error>`
5. **不要编造答案**：KG 没有的事实写 `agent_A_answer: null`
