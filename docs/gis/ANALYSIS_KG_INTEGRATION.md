# Analysis 语义优化 + KG 集成设计 v1.0

> 最后更新: 2026-07-27
> 依赖: KG v4.8.1+, SemanticPredicates, cognition queries

---

## 一、定位

analysis 是报告生成层（28 维度/3 层），消费 `analysis_queries`（粗粒度语义查询），不写 KG。
在 L1 维度生成报告前，通过 KG 查询补充 GIS 数据缺陷 + 候选集标注。

---

## 二、P1-13 修复（3 个 Bug）

| Bug | 修复 | 文件 |
|-----|------|------|
| `ToolRegistry.execute_tool` 不存在 | DataPipeline 改用 `tools.py` 的 `TOOL_REGISTRY` 直接调用 | `pipeline.py` |
| 工具名不匹配（`population_model_v1` vs `population_prediction`） | phases.yaml 统一为实际工具名；删除无实现的 `accessibility_analysis` 和 `gis_agent` | `phases.yaml` |
| L3 prompt 不传 `_landuse_metrics`/`intent_targets` | `_build_prompt` L3 分支传 `state.get("_landuse_metrics",{})` 和 `intent_targets` | `node.py` |

---

## 三、P1-14: _optimize_semantics

### 调用位置
`analyze_dimension` 中在 `DataPipeline.get_professional_data` 之后、`_build_prompt` 之前调用。
结果注入到 `professional_data_section` 尾部。

### 维度→KG 查询映射

| 维度 | 查询类型 | KG 查询 |
|------|---------|---------|
| land_use | land_distribution, zone_candidates | get_village_cognition(mode=layer_cards) + PLANNING_ZONE_NAMES |
| socio_economic | land_distribution | get_village_cognition |
| superior_planning | constraint_coverage, zone_candidates | get_constraint_coverage + 候选集提示 |
| natural_environment | constraint_coverage | get_constraint_coverage |
| ecological_green | constraint_coverage | get_constraint_coverage |
| traffic | road_network | get_village_cognition |
| public_services | facility_coverage | get_village_cognition |
| infrastructure | facility_coverage | get_village_cognition |
| architecture | constraint_coverage | get_constraint_coverage |
| location | village_overview | get_village_cognition |

### 候选集标注

对于 `zone_candidates` 查询类型，注入：
- 分区体系：生态保护区 > 生态控制区 > 农田保护区 > 一般农业区 > 村庄建设区 > 林业发展区
- 分区→主空间：{生态保护区: 生态空间, 农田保护区: 农业空间, ...}
- 提示：以上为编码推荐值，LLM 可依据上下文修正（非固定一对一映射）

---

## 四、分析维度与分析/解析的区分

| | analysis（报告生成） | parse（意图编译） |
|---|---|---|
| KG 消费 | analysis_queries（粗粒度） | parse_queries（细粒度） |
| 典型查询 | get_village_cognition, get_constraint_coverage | get_parcel_detail, get_parcel_neighbors |
| 写 KG | 否 | 是（L3 intent） |
| 语义层使用 | 间接（通过 cognition 查询） | 直接（get_entity_semantics） |
