# Planning Knowledge Graph (KG) 模块

> **定位**: 村庄规划系统的**空间语义引擎** - 只存有几何的空间实体及其关系
> **层级**: `Schema ← Data ← SpatialOps ← KG ← Agent`
> **依赖**: 仅依赖 `app.modules.schema`；不依赖 Data/Agent/Tools
> **Updated: 2026-07-29 (v4.9)** - GeoSPARQL 谓词对齐 + spatial_ref.py 候选 BSM 查询 + L4 provenance 链 + 金标准回归保护

---

## 零、v4.8.1 变更摘要（交叉类型空间关系 + 扩展几何组）

### v4.8.1 新增能力

| 能力                                    | 说明                                                                                                                                                                                   | 文件                                        |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| **交叉类型关系**                  | `geo:sfWithin`(点/线在多边形内) + `geo:sfIntersects`(线穿面/面叠面) + `geo:sfContains`(面包面)，由 spatial_ops 预计算注入                                                        | `layer1.py:_add_cross_type_relations`     |
| **保护多边形实体**                | 永久基本农田/生态红线/历史文化保护线/耕地保护目标/城镇开发边界/村庄建设边界/自然保护区 →`pln:Zone`                                                                                  | `layer1.py:_add_protection_polygons`      |
| **建筑物实体**                    | `bundle.points.buildings` → `pln:Facility` (几何形态为点)                                                                                                                         | `layer1.py:_add_buildings`                |
| **地形实体**                      | 等高线(`pln:Road` 形态) + 高程点(`pln:Facility` 形态)                                                                                                                              | `layer1.py:_add_terrain_entities`         |
| **边界实体**                      | 行政区面/规划范围面/行政界线线                                                                                                                                                         | `layer1.py:_add_boundaries`               |
| **自然资源分区**                  | 土壤类型/土壤侵蚀/流域/水文地质分区 →`pln:Zone`                                                                                                                                     | `layer1.py:_add_natural_resource_zones`   |
| **回退启发式**                    | 当 spatial_ops 未预计算时，用质心邻近法计算`located_in`                                                                                                                              | `layer1.py:_compute_cross_type_heuristic` |
| **本体清理**                      | 关系 15→8：合并`within→geo:sfWithin`, `crosses+overlaps→geo:sfIntersects`, `bounds→geo:sfContains`；v4.9 GeoSPARQL 对齐为 `geo:sfTouches/sfWithin/sfIntersects/sfContains` | `ontology.py`                             |
| **GIS_LAYER_GROUP_REGISTRY 移除** | 硬编码字典 →`gis_layer_registry.yaml` 运行时动态读取                                                                                                                                | `ontology.py:get_gis_layer_group_info`    |

### v4.8（上一版本）能力

| 能力                               | 说明                                                                                                                                          | 文件                                                    |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| **三维度谓词**               | 每个 L1 实体携带`gis_type_ref`/`geometry_kind`/`semantic_group`/`has_semantic_label`                                                  | `ontology.py`, `layer1.py`                          |
| **GisLayerSet 虚拟实体**     | 按语义组聚合实体，支持图层卡级查询（无需遍历 660 地块）                                                                                       | `ontology.py`, `layer1.py:_add_gis_layer_groups`    |
| **语义层谓词**               | `taxonomic_parent`(分类层级) + `legal_constraint`(法律约束) + `allowed_operations`(允许操作)                                            | `ontology.py`, `layer1.py:_add_semantic_enrichment` |
| **DualPayload 双返回**       | 所有认知查询返回`(semantic, structured)` 二元组                                                                                             | `queries/contracts.py`                                |
| **TokenBudget CJK 感知**     | CJK 1char≈1token / ASCII 4char≈1token，软/硬限制，部分包含                                                                                  | `queries/contracts.py`                                |
| **TopKSampler 混合规则抽样** | 分层+空间网格+异常值，不用嵌入向量                                                                                                            | `queries/contracts.py`                                |
| **get_village_cognition**    | 三层认知摘要（村概览/图层卡/约束简报）                                                                                                        | `queries/cognition.py`                                |
| **get_entity_semantics**     | 实体语义层查询（分类/约束/操作/编码桥接）                                                                                                     | `queries/semantic.py`                                 |
| **四命名空间查询 API**       | `analysis_queries`/`parse_queries`(含 `resolve_candidates`/`get_parcels_near_point`)/`execute_queries`(部分可用)/`shared_queries` | `queries/__init__.py`                                 |

### 数据边界声明（硬约束）

```
spatial_ops（几何权威）:
  全几何运算 / 空间索引 / 几何变更 / 约束面交集 / 聚类方向邻近
  无状态函数，输入 bundle，输出结构化结果

KG（语义权威）:
  BSM+派生属性 / 空间关系 / 语义层 / 图层组虚拟实体 / L3意图 / L4成果
  KG 绝不存全几何（VKG 决策），仅存几何元数据 `geometry_kind`（"polygon"|"line"|"point"）

ContextBlock（组合输出）:
  几何部分 ← spatial_ops 计算
  语义聚合部分 ← KG 查询
  二者组合，不重复，不跨边界
```

### 四命名空间定位

| 命名空间             | 消费者               | 粒度                       | 返回偏好           | 写KG   | 状态               |
| -------------------- | -------------------- | -------------------------- | ------------------ | ------ | ------------------ |
| `analysis_queries` | analysis（报告生成） | 粗（图层组/村/分区级）     | semantic_payload   | 否     | 可用               |
| `parse_queries`    | PARSE（意图编译）    | 细（单地块/邻接/候选集）   | structured_payload | 是(L3) | 可用               |
| `execute_queries`  | EXECUTE（执行落地）  | 中（L4读写/约束验证/冲突） | structured_payload | 是(L4) | **部分可用** |
| `shared_queries`   | 跨阶段               | -                          | -                  | 否     | 可用               |

---

## 一、核心原则

### 1.1 KG 只存"有几何的空间要素"

```
进 KG RDF 图: Parcel, Road, WaterBody, Facility, Zone, ControlLine,
              Building, ProtectionPolygon, TerrainEntity, Boundary,
              NaturalResourceZone, LayerGroup, ...
不进 KG:      ControlRule, PlanningIndicator, Constraint (数值),
              PlanIntent (语义), 编码体系分类树
```

非空间要素通过以下方式传递：

| 类型                             | 去向                                                      |
| -------------------------------- | --------------------------------------------------------- |
| `ControlRule`                  | `bundle.tables.control_rules`                           |
| `PlanningIndicator`            | `bundle.tables.planning_indicators`（PARSE Agent 填充） |
| `Constraint` (数值约束)        | `ContextBlock.CONSTRAINTS.data`                         |
| `PlanIntent` (语义容器)        | `SpatialPlanningIntent` 对象本身                        |
| 编码体系 (DLBM/GHYTBM/TUGUI/...) | Schema 层`encodings/code_sets.py`，按需查询             |

**编码体系管理原则**：KG 只在地块属性中存储编码值（`pln:dlbm`、`pln:vne_code`、`pln:planning_zone`），不存储编码体系本身的分类树。分类树查询通过 Schema 层的 `encodings/` 模块按需返回，不走 KG RDF 图。

### 1.2 编码值的使用模式：事实 vs 推荐

KG 中存储的编码属性分为两类，消费者必须理解其语义差异：

| 类别             | 属性                                                                         | 来源                                         | 确定性 | 消费方式                          |
| ---------------- | ---------------------------------------------------------------------------- | -------------------------------------------- | ------ | --------------------------------- |
| **事实型** | `pln:dlbm`, `pln:sddlbm`, `pln:dlbm_system`, `pln:current_zone_type` | 数据层 ingest 直接读取 + 编码体系确定性映射  | 确定   | 查询、筛选、聚合                  |
| **推荐型** | `pln:planning_zone`, `pln:primary_zone`, `pln:vne_code`                | 编码体系提供的推荐映射，LLM 可依据上下文修正 | 推荐   | 作为 LLM 参考，最终决定权在规划师 |

### 1.3 关系本身就是语义

KG 的 RDF 三元组不仅描述实体属性，更描述实体间的空间关系。**注解必须同时附着于实体和关系**，不能只存实体级注解：

```python
EntityAnnotation(entity_uri, description, source_text_refs, intent_refs)
RelationAnnotation(subject_uri, predicate, object_uri,
                   description, derived_from, quantitative_detail)
```

### 1.4 Intent 以虚拟实体进 KG（L3 易失层）

ZoneTarget、FacilityTarget、RoadTarget、AxisTarget 作为 L3 临时虚拟实体进入 KG，携带结构化锚定属性（`candidate_bsm`、`excluded_bsm`、`candidate_bbox`、`spatial_hint`、`anchor_point`），不存储粗糙几何。EXECUTE 通过 SPARQL 查询这些虚拟实体与现状实体之间的空间关系（冲突检测、候选地块筛选）。

### 1.5 PlanBlock 是 Agent 记忆，不进 KG

| 结构                   | 本质                     | 消费者               | 持久化       |
| ---------------------- | ------------------------ | -------------------- | ------------ |
| **ContextBlock** | 现状空间认知卡片         | PARSE prompt         | 不持久化     |
| **PlanBlock**    | 增量变更操作记录         | 累积 → PlannedState | 可选会话日志 |
| **PlannedState** | 规划成果空间实体（聚合） | KG Layer 4           | 持久化       |

### 1.6 零 shapely/geopandas 依赖

所有几何计算由 `spatial_ops` 完成，KG 只消费结构化数据。KG 内部对交叉类型关系使用质心启发式回退（`_compute_cross_type_heuristic`），仅当 external `cross_type_relations` 未提供时使用。

### 1.7 三维度标注 + 图层组虚拟实体（v4.8）

每个 L1 空间实体显式携带三个语义维度谓词，支持按图层/几何/语义组检索：

```python
pln:gis_type_ref     <- gis_layer_registry.yaml key (如 "landuse_current", "road", "water")
pln:geometry_kind     <- "polygon" | "line" | "point"
pln:semantic_group    <- group 字段 (如 "current_landuse", "transport", "protection")
pln:has_semantic_label <- 从 dlbm 派生的中文名 (如 0101 -> "水田")
```

图层组虚拟实体（`pln:GisLayerSet`）聚合同组实体，支持图层卡级查询：

```turtle
pln:GisLayerSet_current_landuse a pln:GisLayerSet ;
  pln:semantic_group "current_landuse" ;
  pln:geometry_kind "polygon" ;
  pln:gis_description "基期现状地类" ;
  pln:gis_description_enriched "基期现状地类 - 660个实体，主要: 耕地(175), 宅基地(132), 商品林(115)" ;
  pln:entity_count 660 ;
  pln:dominant_label "耕地" ;
  pln:contains_entity pln:parcel_BSM1, pln:parcel_BSM2, ... .
```

GisLayerSet 元数据不再硬编码（v4.8.1 移除 `GIS_LAYER_GROUP_REGISTRY`），改为从 `gis_layer_registry.yaml` 动态读取。

### 1.8 语义层：分类/约束/操作（v4.8）

实体类型级语义层谓词，从 `encodings/dicts/rules/*.yaml` 自动派生 + 手工补充：

| 谓词                       | 来源                                                             | 示例                                 |
| -------------------------- | ---------------------------------------------------------------- | ------------------------------------ |
| `pln:taxonomic_parent`   | appendix5 zone_type 自动派生                                     | 水田 -> 耕地 -> 农业用地             |
| `pln:legal_constraint`   | construction_zone_codes + planning_zone_to_control_code 自动派生 | 农田保护区 -> forbid_construction    |
| `pln:allowed_operations` | allowed_operations.yaml 手工补充                                 | 宅基地 -> [split, merge, reclassify] |

查询入口：`get_entity_semantics(kg, entity_label="水田")` 返回完整语义信息。

### 1.9 DualPayload 双返回 + Token 预算（v4.8）

所有认知查询返回 `DualPayload`：

```python
@dataclass
class DualPayload:
    semantic: Dict       # 三层认知摘要（LLM 可读）
    structured: Dict     # BSM 列表/bbox/geometry_kind 索引（工具可消费）
    token_estimate: int  # CJK 感知估算 (CJK 1char≈1token / ASCII 4char≈1token)
    truncated: bool      # 是否因预算截断
    next_cursor: str     # 分页游标
```

三层认知摘要结构：

- `context_block`：村域概览（2-3 句定位+面积+空间格局）
- `layer_cards[]`：图层组卡片（几何类型/数量/主导标签/分布）
- `constraint_block`：邻接总数/跨图层叠加/约束覆盖率

TopK 混合规则抽样（不用嵌入向量）：

1. 按语义标签分层抽样（每组面积 Top 1-3）
2. 3×3 网格空间覆盖抽样（每格面积最大 1 个）
3. 异常值抽取（最大/最小各 1-2）

### 1.10 交叉类型空间关系（v4.8.1）

KG 支持三种跨类型空间关系，由 `spatial_ops` 预计算后注入，或由 KG 内部质心启发式回退：

| 关系                 | 语义                   | 示例                                      |
| -------------------- | ---------------------- | ----------------------------------------- |
| `geo:sfWithin`     | 点/线实体在多边形内部  | facility → parcel, building → parcel    |
| `geo:sfIntersects` | 线穿面 / 面叠面        | road → parcel, parcel → protection_zone |
| `geo:sfContains`   | 多边形包含另一个多边形 | boundary → parcel                        |

`overlap_pct` 属性附加在 `geo:sfIntersects` 关系上，记录重叠百分比。

---

## 二、四层架构

| 层      | 内容                                                        | 生命周期               | 写入者                         | 消费者                      |
| ------- | ----------------------------------------------------------- | ---------------------- | ------------------------------ | --------------------------- |
| Layer 1 | 现状空间实体 + 属性编码 + 三维度谓词 + GisLayerSet + 语义层 | 持久（数据更新时重建） | Data Layer → bundle 直连      | SPARQL 查询、PARSE、EXECUTE |
| Layer 2 | 空间关系（含交叉类型）                                      | 持久                   | `spatial_ops` 计算           | SPARQL 查询、EXECUTE        |
| Layer 3 | 意图虚拟实体（结构化锚定属性）                              | 会话易失               | PARSE →`build_intent_layer` | EXECUTE 空间推理            |
| Layer 4 | 规划成果实体（版本化增量）                                  | 会话持久               | EXECUTE → PlannedState        | 导出、对比、校验            |

### 2.1 系统位置

```
bundle (VillageBundle)
  │
  ├──→ compute_context_blocks() → ContextBlock[] → PARSE prompt (agent 记忆)
  │
  └──→ KG.build_from_bundle(bundle, relations, intent, planned_state,
  │          constraint_index, water_overlap, cross_type_relations)
         │
         ├── Layer 1: 现状实体 (bundle 形态分组直连) + 三维度 + LayerGroup
         ├── Layer 1b: 扩展几何组（保护多边形/建筑/地形/边界/自然资源）
         ├── Layer 2: 空间关系 (parcel_relations + cross_type_relations)
         ├── (v4.8) LayerGroup 虚拟实体 + 语义层写入
         ├── Layer 3: 意图虚拟实体 (intent → 结构化锚定)
         └── Layer 4: 规划成果 (PlannedState → 版本化增量)
```

### 2.2 构建入口

```python
kg = PlanningKG(village_name="金田村委会")
kg.build_from_bundle(
    bundle=bundle,                 # VillageBundle — 类型化形态视图
    parcel_relations=relations,    # ParcelRelations — 三层空间关系（外部计算）
    intent=intent,                 # SpatialPlanningIntent → L3 虚拟实体（可选）
    planned_state=planned,         # PlannedState → L4 规划成果（可选）
    constraint_index=ci,           # ConstraintIndex → 约束面空间索引（可选）
    water_overlap=wo,              # 水域重叠去重映射（可选）
    cross_type_relations=ctr,      # 交叉类型空间关系（可选，spatial_ops 预计算）
)
```

**注意**：KG builder 直接从 `bundle.polygons.landuse_current`、`bundle.lines.roads_current` 等形态分组读取，不依赖 ContextBlock。ContextBlock 只作为 PARSE 的 prompt 上下文。

### 2.3 Layer 1: 现状实体

| 实体类型                               | 数据来源                                                                                                                                | 方法                                     | 标识键                      |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- | --------------------------- |
| `pln:AdministrativeVillage`          | `bundle.metadata`                                                                                                                     | `_add_village_entity`                  | singleton (`pln:village`) |
| `pln:Parcel`                         | `bundle.polygons.landuse_current`                                                                                                     | `_add_parcels`                         | `PLN.bsm` literal ✅      |
| `pln:Road`                           | `bundle.lines.roads_current`                                                                                                          | `add_roads`                            | `PLN.bsm` literal ✅      |
| `pln:WaterBody`                      | `bundle.polygons.water_bodies`                                                                                                        | `_add_water_bodies`                    | `PLN.bsm` literal ✅      |
| `pln:Facility`                       | `bundle.points.facilities_current`                                                                                                    | `_add_facilities_from_typed`           | `PLN.bsm` literal ✅      |
| `pln:ResidentialCluster`             | 从`landuse_current` 按 DLBM 聚类衍生                                                                                                  | `_add_residential_clusters_from_typed` | `PLN.name` ⚠️           |
| `pln:Zone`                           | `bundle.polygons.land_use_zones` / `construction_ctrl_zones`                                                                        | `_add_planning_elements_from_typed`    | `PLN.bsm` literal ✅      |
| `pln:ControlLine`                    | `bundle.points.hazard_points` / `polygons.hazard_control_lines` / `polygons.flood_control_lines` / `polygons.construction_zone` | `_add_control_lines_from_typed`        | `PLN.bsm` 或 fallback     |
| `pln:PlaceRef`                       | annotations 中`category=村名` 的点                                                                                                    | `add_annotations`                      | `PLN.bsm` 或 fallback     |
| `pln:Zone` (保护)                    | `polygons.farmland_protection / ecological_redline / historical_protection / ...`                                                     | `_add_protection_polygons`             | `PLN.bsm` ✅              |
| `pln:Facility` (建筑)                | `bundle.points.buildings`                                                                                                             | `_add_buildings`                       | `PLN.bsm` ✅              |
| `pln:Road` (等高线)                  | `bundle.lines.contour_lines`                                                                                                          | `_add_terrain_entities`                | `PLN.bsm` ✅              |
| `pln:Facility` (高程点)              | `bundle.points.elevation_points`                                                                                                      | `_add_terrain_entities`                | `PLN.bsm` ✅              |
| `pln:AdministrativeVillage` (行政区) | `polygons.admin_areas` + `lines.admin_boundaries`                                                                                   | `_add_boundaries`                      | `PLN.bsm` ✅              |
| `pln:Zone` (规划范围)                | `polygons.planning_scope`                                                                                                             | `_add_boundaries`                      | `PLN.bsm` ✅              |
| `pln:Zone` (自然资源)                | `polygons.soil_types / soil_erosions / watersheds / hydrogeology_zones`                                                               | `_add_natural_resource_zones`          | `PLN.bsm` ✅              |
| `pln:GisLayerSet` (v4.8)             | 自动聚合（不直接对应 bundle 分组）                                                                                                      | `_add_gis_layer_groups`                | 无 BSM，虚拟实体            |

**编码属性存储**：每个 `pln:Parcel` 实体存储以下属性：

- 事实型：`pln:dlbm`、`pln:sddlbm`、`pln:current_zone_type`（从 DLBM 确定性派生）
- 推荐型：`pln:planning_zone`、`pln:primary_zone`（来自数据层 ingest 的推荐值）
- 原始：`pln:dlmc`、`pln:ysdm`、`pln:dlbm_system`（忠实存储，不派生）
- 几何：`pln:area_sqm`、`pln:area_ha`、`pln:lon`、`pln:lat`（质心坐标）

### 2.4 Layer 2: 空间关系

由 `spatial_ops.compute_parcel_relations()` 计算，KG 通过 `_add_parcel_relations` 消费。

| 层次         | 关系                       | 属性                       | 对规划的意义            |
| ------------ | -------------------------- | -------------------------- | ----------------------- |
| L1: 拓扑邻接 | `geo:sfTouches`          | `shared_boundary_length` | 地块合并/拆分、连片开发 |
| L2: 近邻关系 | `pln:nearby`             | `centroid_distance`      | 设施选址、公共服务覆盖  |
| L3: 连通关系 | `pln:connected_via_road` | `road_segment_length`    | 交通可达性              |

**交叉类型关系**（v4.8.1，由 `cross_type_relations` 参数注入）：

| 关系                 | 来源                           | 属性            | 说明                    |
| -------------------- | ------------------------------ | --------------- | ----------------------- |
| `geo:sfWithin`     | spatial_ops 预计算或质心启发式 | —              | 设施/建筑在哪个地块内   |
| `geo:sfIntersects` | spatial_ops 预计算             | `overlap_pct` | 道路穿地块/地块叠保护面 |
| `geo:sfContains`   | spatial_ops 预计算             | —              | 边界包含地块            |

### 2.5 Layer 3: 意图虚拟实体（易失）

`SpatialPlanningIntent` 的 `zone_targets`、`facilities`、`development_axes`、`road_targets` 被转换为有结构化锚定属性的临时实体，**不再存储几何 WKT**（v4.8.1）：

```python
kg.build_intent_layer(intent)
# 在 KG 中创建:
#   pln:zone_target_家园 (ZoneTarget, 含 candidate_bsm/excluded_bsm/candidate_bbox/spatial_hint)
#   pln:facility_target_展销中心 (FacilityTarget, 含 anchor_point/candidate_bsm)
#   pln:road_target_村道 (RoadTarget, 含 start_anchor/end_anchor/path_bsms)
#   pln:axis_target_村主干道 (AxisTarget, 含 start_anchor/end_anchor/corridor_bsms)

# 语义注解同时写入 SemanticMemoryStore:
# "规划目标: 将 15% 的土地用于 2121"
# "规划设施: 展销中心 (planned_new) 服务半径500m"
```

**生命周期**：当前规划会话结束时清除（`kg.clear_intent_layer()`）。

### 2.6 Layer 4: 规划成果（版本化增量）

`PlannedState` 是增量变更的累积视图，和 `VillageBundle` 形态对齐：

```python
@dataclass
class PlannedState:
    version: str = "current"
    parcels: List[PlannedParcelEntry]    # 规划地块（面，WKT geometry 可选）
    zones: List[PlannedZoneEntry]        # 规划分区（面，WKT geometry 可选）
    facilities: List[PlannedFacilityEntry] # 规划设施点（点）
    roads: List[PlannedRoadEntry]        # 规划道路（线）
    axes: List[PlannedAxisEntry]         # 规划发展轴线
    source: str = ""
```

每个 Entry 继承自 `SpatialCognitiveUnit` 形态基类，天然有几何和 URI。L4 进入 KG 时和 L1 一样处理，只是加版本标签。**稀疏写入**：未变更的地块不写入 L4 三元组，查询时回退到 L1。

**L4 → L3 追溯**：通过 `pln:derived_from_target` 三元组链接到 L3 意图实体（v4.7）。

**L4 溯源链**（v4.9）：

```python
# PlannedParcelEntry 完整 provenance 字段 (EXECUTE_KG_UTILIZATION_DESIGN §3)
pln:derived_from          # → L1 Parcel BSM
pln:derived_from_target   # → L3 target URI
pln:source_spec           # PARSE spec 字符串 (e.g. "directional:east_of_village")
pln:decided_by            # "rule" | "llm" | "human"
pln:operation             # "reclassify" | "merge" | "split" | "new" | "demolish"
pln:area_change_ha        # 有符号面积变化 (e.g. -2.3)
```

### 2.7 实体标识契约 (EntityIdPolicy)

#### 统一策略

所有 KG 实体的 URI 生成与 BSM 绑定由 `EntityIdPolicy`（`ontology.py`）统一管理：

```python
class EntityIdPolicy:
    @staticmethod
    def uri(entity_type, bsm, version="") -> URIRef:
        # L1: PLN[f"{entity_type}_{bsm}"]
        # L4: PLN[f"{entity_type}_{bsm}_{version}"]

    @staticmethod
    def uri_with_seq(entity_type, bsm, seq, version="") -> URIRef:
        # For duplicate BSMs: PLN[f"{entity_type}_{bsm}_{seq}"]

    @staticmethod
    def fallback_uri(entity_type, ysdm, seq) -> URIRef:
        # BSM missing: PLN[f"{entity_type}_{ysdm}_{seq}"]
```

#### 实现状态

| 层 | 实体                | URI 方案                                                                   | `PLN.bsm` literal | 可追溯                          |
| -- | ------------------- | -------------------------------------------------------------------------- | ------------------- | ------------------------------- |
| L1 | Parcel              | `uri_with_seq("parcel", bsm, seq)`                                       | ✅                  | ✅                              |
| L1 | Road                | `uri("road", bsm)` + fallback                                            | ✅                  | ✅                              |
| L1 | WaterBody           | `uri("water"/"water_line", bsm)` + fallback                              | ✅                  | ✅                              |
| L1 | Facility            | `uri("facility", bsm)` + fallback                                        | ✅                  | ✅                              |
| L1 | ResidentialCluster  | `fallback_uri("settlement", name, seq)`                                  | ⚠️ 按名           | ⚠️                            |
| L1 | ControlLine         | `uri/fallback` per type (hazard/hazard_line/flood_line/zone_conditional) | ✅                  | ✅                              |
| L1 | Zone (TDYT/jsydgzq) | `uri/fallback`                                                           | ✅                  | ✅                              |
| L1 | Zone (保护多边形)   | `uri(attr_name, bsm)`                                                    | ✅                  | ✅                              |
| L1 | Facility (建筑)     | `uri("building", bsm)` + fallback                                        | ✅                  | ✅                              |
| L1 | Road (等高线)       | `uri("contour", bsm)` + fallback                                         | ✅                  | ✅                              |
| L1 | Facility (高程点)   | `uri("elevpt", bsm)` + fallback                                          | ✅                  | ✅                              |
| L1 | PlaceRef (村名注记) | `uri("village_ann", bsm)` + fallback                                     | ✅                  | ✅                              |
| L1 | Zone (自然资源)     | `uri(attr_name, bsm)` + fallback                                         | ✅                  | ✅                              |
| L3 | ZoneTarget          | `uri("zone_target", target_id)`                                          | `PLN.target_id`   | ✅                              |
| L3 | FacilityTarget      | `uri("facility_target", target_id)`                                      | `PLN.target_id`   | ✅                              |
| L3 | AxisTarget          | `uri("axis_target", target_id)`                                          | `PLN.target_id`   | ✅                              |
| L3 | RoadTarget          | `uri("road_target", target_id)`                                          | `PLN.target_id`   | ✅                              |
| L4 | PlannedParcel       | `uri("planned_parcel", bsm, version)`                                    | ✅                  | ✅`derived_from` → L1        |
| L4 | PlannedZone         | `uri("planned_zone", zone_id, version)`                                  | `PLN.zone_type`   | ✅`derived_from_target` → L3 |
| L4 | PlannedFacility     | `uri("planned_facility", fac_id, version)`                               | `PLN.name`        | ✅`derived_from_target` → L3 |
| L4 | PlannedRoad         | `uri("planned_road", road_id, version)`                                  | `PLN.name`        | ✅`derived_from_target` → L3 |
| L4 | PlannedAxis         | `uri("planned_axis", axis_id, version)`                                  | `PLN.name`        | ✅`derived_from_target` → L3 |

#### ThreeZone/ThreeLine 移除

[v4.7] ThreeZone/ThreeLine 从 KG 实体中移除。它们是引用层（上级审批成果，不可修改），不是规划对象。约束多边形通过 `spatial_ops.bridge.ConstraintIndex` 访问，在 `build_from_bundle` 时注入。

#### 重复 BSM 处理

实际数据中 BSM 可能不唯一（多部件图斑按地类拆分后共享 BSM）。`EntityIdPolicy.uri_with_seq` 通过序号后缀消歧：`parcel_{bsm}_0`, `parcel_{bsm}_1`, ... 所有同 BSM 的子图斑共享 `PLN.bsm` literal，SPARQL 查询返回多条结果。

#### 约束验证

`check_constraint_violations` 和 `_is_in_protected_zone` 不再查询 KG 中空的 `within_zone` 关系，改为通过注入的 `ConstraintIndex`（spatial_ops bridge）做空间 overlay 查询：

```python
kg.build_from_bundle(bundle, constraint_index=build_constraint_index(bundle))
violations = kg.check_constraint_violations("v1")  # 实际检测约束多边形重叠
```

---

## 三、实体类型

### 3.1 现状实体（Layer 1）

| 形态     | 实体                      | RDF 类型                      | 编码属性                                                                                                         |
| -------- | ------------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| 面       | `Parcel`                | `pln:Parcel`                | `dlbm`(事实), `current_zone_type`(事实), `planning_zone`(推荐), `primary_zone`(推荐), `vne_code`(推荐) |
| 面       | `WaterBody`             | `pln:WaterBody`             | `water_type`                                                                                                   |
| 面       | `Zone`                  | `pln:Zone`                  | — (规划分区/保护多边形/自然资源)                                                                                |
| 面       | `AdministrativeVillage` | `pln:AdministrativeVillage` | —                                                                                                               |
| 面       | `ResidentialCluster`    | `pln:ResidentialCluster`    | —                                                                                                               |
| 线       | `Road`                  | `pln:Road`                  | `road_level`                                                                                                   |
| 点       | `Facility`              | `pln:Facility`              | `facility_type` (含注记派生)                                                                                   |
| 点/面/线 | `ControlLine`           | `pln:ControlLine`           | `source` (hazard/flood/construction)                                                                           |
| 点       | `PlaceRef`              | `pln:PlaceRef`              | —（村名注记，仅供可视化参考）                                                                                   |
| —       | `GisLayerSet`           | `pln:GisLayerSet`           | 虚拟实体，无 BSM                                                                                                 |

### 3.2 意图虚拟实体（Layer 3，易失）

| 形态 | 实体               | RDF 类型               | 结构化锚定属性                                                            |
| ---- | ------------------ | ---------------------- | ------------------------------------------------------------------------- |
| —   | `ZoneTarget`     | `pln:ZoneTarget`     | `candidate_bsm`, `excluded_bsm`, `candidate_bbox`, `spatial_hint` |
| —   | `FacilityTarget` | `pln:FacilityTarget` | `candidate_bsm`, `anchor_point`, `spatial_hint`                     |
| —   | `AxisTarget`     | `pln:AxisTarget`     | `start_anchor`, `end_anchor`, `corridor_bsms`                       |
| —   | `RoadTarget`     | `pln:RoadTarget`     | `start_anchor`, `end_anchor`, `path_bsms`, `spatial_hint`         |

**注意**：L3 实体不再存储粗糙几何（bbox/缓冲区），改为纯结构化锚定属性。空间推理由 EXECUTE 通过 SPARQL 查询 `candidate_bsm` 等锚定信息完成。

### 3.3 规划成果实体（Layer 4，版本化）

| 形态 | 实体                | RDF 类型                | 版本标签                               |
| ---- | ------------------- | ----------------------- | -------------------------------------- |
| 面   | `PlannedParcel`   | `pln:PlannedParcel`   | `in_version` + 可选 WKT `geometry` |
| 面   | `PlannedZone`     | `pln:PlannedZone`     | `in_version` + 可选 WKT `geometry` |
| 点   | `PlannedFacility` | `pln:PlannedFacility` | `in_version`                         |
| 线   | `PlannedRoad`     | `pln:PlannedRoad`     | `in_version`                         |
| 线   | `PlannedAxis`     | `pln:PlannedAxis`     | `in_version`                         |

---

## 四、关系类型

### 4.1 空间拓扑关系（v4.9 GeoSPARQL 对齐）

| 关系 (URI)                 | 方向 | 属性                                  | 说明                                                        |
| -------------------------- | ---- | ------------------------------------- | ----------------------------------------------------------- |
| `geo:sfTouches`          | 双向 | `shared_boundary_length`            | 拓扑邻接（取代`adjacent_to`）                             |
| `pln:nearby`             | 双向 | `centroid_distance`                 | 近邻关系（≤ 200m）                                         |
| `pln:connected_via_road` | 双向 | `road_segment_length`, `via_road` | 路网连通                                                    |
| `geo:sfWithin`           | 单向 | —                                    | 包含关系（点/线在多边形内，取代旧`within_zone`）          |
| `geo:sfIntersects`       | 单向 | `overlap_pct`                       | 交叉关系（线穿面/面叠面，合并旧`crosses` + `overlaps`） |
| `geo:sfContains`         | 单向 | —                                    | 包含关系（面包面，取代旧`bounds`）                        |

### 4.2 规划语义关系

| 关系             | 方向 | 说明                                  |
| ---------------- | ---- | ------------------------------------- |
| `derived_from` | 单向 | 规划实体源于现状实体（L4 → L1 追溯） |
| `serves`       | 单向 | 设施服务于某区域                      |

### 4.3 向后兼容（不在 active set）

| 关系                       | 说明                           |
| -------------------------- | ------------------------------ |
| `within_zone`            | 被`geo:sfWithin` 取代        |
| `touches` (pln: 前缀)    | v4.9 改为`geo:sfTouches`     |
| `located_in` (pln: 前缀) | v4.9 改为`geo:sfWithin`      |
| `intersects` (pln: 前缀) | v4.9 改为`geo:sfIntersects`  |
| `contains` (pln: 前缀)   | v4.9 改为`geo:sfContains`    |
| `designated_as`          | 未在构建器中使用               |
| `connects`               | 仅用于`village → road` 链接 |
| `delineates`             | 未在构建器中使用               |

### 4.4 已删除的关系

| 关系                    | 理由                                     | 去向                                  |
| ----------------------- | ---------------------------------------- | ------------------------------------- |
| `constrained_by`      | 约束是 ContextBlock 数值，不是实体间关系 | ContextBlock.CONSTRAINTS.data         |
| `achieves`            | 指标达标由 bundle.tables 体现            | `bundle.tables.planning_indicators` |
| `conflicts_with`      | 冲突检测结果，运行时计算                 | 不持久化                              |
| `conducted_from`      | 上位传导在指标表字段中                   | `bundle.tables.planning_indicators` |
| `controls_use`        | ControlRule 字段                         | `bundle.tables.control_rules`       |
| `protects`            | ThreeLine 的属性字段，非关系             | 改为属性                              |
| `adjacent_to`         | 已废弃                                   | 由`geo:sfTouches` 替代              |
| `location_constraint` | 属性非关系                               | L3 虚拟实体的 LocationConstraint 字段 |
| `crosses`             | v4.8.1 合并                              | 由`geo:sfIntersects` 替代           |
| `overlaps`            | v4.8.1 合并                              | 由`geo:sfIntersects` 替代           |
| `bounds`              | v4.8.1 合并                              | 由`geo:sfContains` 替代             |
| `within`              | v4.8.1 合并                              | 由`geo:sfWithin` 替代               |

---

## 五、SemanticMemoryStore

语义注解不存储在 RDF 图中，而是通过 `SemanticMemoryStore` 管理。注解同时附着于实体和关系：

### 5.1 实体注解

```python
@dataclass
class EntityAnnotation:
    entity_uri: str
    entity_type: str
    description: str              # 人类可读说明
    source_text_refs: List[str]   # 溯源文本
    intent_refs: List[str]        # 意图关联
```

### 5.2 关系注解

```python
@dataclass
class RelationAnnotation:
    subject_uri: str
    predicate: str
    object_uri: str
    description: str              # 人类可读的关系解释
    derived_from: str             # "spatial_ops_computed" | "llm_inferred" | "rule_derived"
    quantitative_detail: Dict[str, Any]  # {"distance_m": 1200, "shared_boundary_m": 45.2}
```

### 5.3 查询接口

```python
class SemanticMemoryStore:
    def get_entity_semantics(self, uri: str) -> Dict:
        """返回实体属性 + 人类可读注解 + 参与的语义关系"""

    def get_relation_semantics(self, subject, predicate, object) -> Dict:
        """返回关系本身 + 注解 + 量化细节"""
```

### 5.4 写时读注解（Write-on-Read）

`semantic.py` 中的所有查询函数自动填充 `SemanticMemoryStore`：当查询一个尚无注解的实体或关系时，自动从 RDF 属性生成描述并存储（`_ensure_entity_annotation` / `_ensure_relation_annotation`），后续查询直接返回。

```python
# 首次调用自动生成注解
result = get_entity_context(kg, "pln:ResidentialCluster/刘村")
# → 注解："居民点 刘村" 自动写入 memory

# 后续调用直接使用已有注解
result = get_entity_context(kg, "pln:ResidentialCluster/刘村")
```

---

## 六、数据流与消费关系

### 6.1 数据流总图

```
┌───────────┐     ┌──────────────┐     ┌─────────────────┐
│ Data Layer│────→│ Spatial Ops  │────→│ ContextBlock[] │ → PARSE prompt
│ (Bundle)  │     │ (关系计算)   │     │ (agent 记忆)    │
└───────────┘     └──────┬───────┘     └─────────────────┘
        │                │
        ▼                ▼
┌──────────────────────────────────────────────────────────┐
│ KG Builder (PlanningKG.build_from_bundle)                  │
│  ├── bundle 形态分组直连 → Layer 1 (现状实体 + 编码属性)   │
│  │   └── 扩展几何组：保护多边形/建筑/地形/边界/自然资源    │
│  ├── parcel_relations   → Layer 2 (parcel 间空间关系)      │
│  ├── cross_type_relations → located_in/intersects/contains │
│  ├── (v4.8) 三维度 + LayerGroup + 语义层写入               │
│  ├── intent             → Layer 3 (虚拟实体, 易失)         │
│  └── planned_state      → Layer 4 (规划成果, 版本化)       │
└──────────────────────────────────────────────────────────┘
        ▲                        │
        │                        ▼
┌───────────────────┐  ┌──────────────────┐
│ PARSE Agent       │  │ EXECUTE Agent    │
│ 消费: query_kg,   │  │ 消费: SPARQL,    │
│      TOOL_META,   │  │      get_adj_map,│
│      semantic.py  │  │      validate,   │
│      cognition.py │  │      constraints │
└───────────────────┘  └──────────────────┘
        │                        │
        ▼                        ▼
┌──────────────────────────────────────────────────────────┐
│ Tools Layer (tools/gis/)                                  │
│ 消费: get_kg_manager, query_kg, TOOL_META                 │
│ 用途: 生成、导出、渲染、校验                                │
└──────────────────────────────────────────────────────────┘
```

### 6.2 PARSE Agent 消费 KG

PARSE 通过两个渠道消费 KG：

**渠道 1：SPARQL 工具调用（Think 阶段）**

```python
from app.modules.kg.queries.sparql import query_kg, TOOL_META

# LLM 可调用的查询工具
result = query_kg(knowledge_graph, "parcels_by_planning_zone",
                  planning_zone="村庄建设区")
# 返回: [{"bsm": "001", "dlbm": "0701", "area_ha": 0.5}, ...]

# 30+ 预定义模板（部分返回语义描述，部分返回结构化结果）
TOOL_META = [
    {"name": "get_village_parcels", "description": "All parcels with LLM-readable descriptions"},
    {"name": "get_parcel_detail", "description": "单地块详情（属性+关系+注解）"},
    {"name": "get_parcel_neighbors", "description": "地块邻接关系（语义）"},
    {"name": "get_facility_locations", "description": "所有设施（语义描述）"},
    # ...
]
```

**渠道 2：语义查询（LLM 友好）**

```python
from app.modules.kg.queries.semantic import (
    get_entity_context,           # 实体属性 + 注解
    get_entity_relations,         # 实体关系 + 描述
    get_parcel_semantic_context,  # 地块语义上下文
    get_village_semantic_summary, # 村庄语义摘要
    get_parcels_by_planning_zone, # 按规划分区 + 编码推荐值
    get_entity_semantics,         # (v4.8) 语义层：分类/约束/操作/编码桥接
)
```

**渠道 3：认知查询（v4.8）**

```python
from app.modules.kg.queries.cognition import get_village_cognition
payload = get_village_cognition(kg, "金田村委会")
# payload.semantic = {context_block, layer_cards[], constraint_block}
# payload.structured = {layer_group_bsms, bbox, representative_bsms}
```

### 6.3 EXECUTE Agent 消费 KG

EXECUTE 通过 SPARQL 直查 KG，MIP 直接消费 flat dict 结果：

```python
from app.modules.kg import PlanningKG

kg = PlanningKG("金田村委会")
kg.build_from_bundle(bundle=bundle, parcel_relations=relations, intent=intent)

# 空间关系查询
adj_map = kg.get_adjacency_map()                   # BSM → {neighbor_BSMs}
nearby = kg.get_parcels_within_distance_of_entity(entity_uri, 500)
connected = kg.get_connected_parcels(parcel_uri)

# 地块详情查询
parcels = kg.get_parcels_by_bsm_list(["001", "002"])

# 约束验证
violations = kg.check_constraint_violations("v1")  # L4 vs ConstraintIndex
conflicts = kg.validate_intent(intent)              # 设施候选地块是否在保护区内

# 规划成果查询
changes = kg.get_plan_changes("v1")
effective = kg.get_effective_land_use("001")        # L4 回退 L1
merged = kg.get_effective_area_ha("001")            # L4 回退 L1
```

### 6.4 Tools 层消费 KG

```python
from app.modules.kg import get_kg_manager, query_kg, TOOL_META

# KGManager 单例管理
manager = get_kg_manager()
kg = manager.get_or_build_kg(bundle, relations)      # 缓存 + 构建

# 通用 SPARQL 查询
result = query_kg(kg, "count_by_zone_type")

# 用于生成、导出、渲染
from app.modules.kg.queries.sparql import TOOL_META
# TOOL_META 包含 30+ 预定义 SPARQL 模板，供 LangGraph @tool 包装
```

### 6.5 编码体系消费模式总结

```
Schema 层 encodings/  ──→  KG 存储事实值 (dlbm, current_zone_type)
                        ──→  KG 存储推荐值 (planning_zone, primary_zone)
                                │
                                ▼
                        PARSE Agent 查询 KG 推荐值
                                │
                                ├── 以推荐值为起点
                                ├── 结合上下文 (上位规划/邻接地块/村民意愿) 判断
                                └── 产出 SpatialPlanningIntent 覆盖推荐值
                                │
                                ▼
                        EXECUTE Agent 按 intent 执行
```

### 6.6 三线覆盖查询

三线（永久基本农田/生态红线/历史保护范围等）是引用层，v4.7 从 KG 的 RDF 实体中移除，但**查询三线覆盖地块的接口在 KG 中实现**。KG 内部使用 `ConstraintIndex`（由 bundle 约束面构建的空间索引），对外暴露为 KG 查询方法：

```
bundle.polygons.farmland_protection ──┐
bundle.polygons.ecological_redline  ──┤
bundle.polygons.historical_protection ─┤──→ ConstraintIndex ──→ KG 查询方法
bundle.polygons.hazard_control_lines ──┤          │
bundle.polygons.flood_control_lines  ──┘          ├── kg.get_constraint_coverage() (structural)
                                                  └── get_village_constraint_coverage(kg) (LLM semantic)
```

```python
# 注入 ConstraintIndex
from app.modules.spatial_ops.bridge import build_constraint_index
ci = build_constraint_index(bundle)
kg.build_from_bundle(bundle, constraint_index=ci)

# 结构化查询（for EXECUTE/MIP）
coverage = kg.get_constraint_coverage()

# 语义查询（for PARSE/LLM）
from app.modules.kg.queries.semantic import get_village_constraint_coverage
result = get_village_constraint_coverage(kg)

# 单地块检查
violations = kg.validate_intent(intent)
```

### 6.7 预留 SPARQL 模板说明

以下 SPARQL 模板定义在 `queries/sparql.py` 中，但对应实体已从 KG 移除或尚未实现：

| 模板                             | 状态 | 替代方案                                                                    |
| -------------------------------- | ---- | --------------------------------------------------------------------------- |
| `get_three_lines`              | 废弃 | `kg.get_constraint_coverage()` 或 `get_village_constraint_coverage(kg)` |
| `get_three_zones`              | 废弃 | 直接用`count_by_planning_zone` 模板                                       |
| `get_protected_parcels_detail` | 废弃 | `kg.get_constraint_coverage()`                                            |
| `get_indicators`               | 废弃 | `bundle.tables.planning_indicators`                                       |
| `get_parcels_by_slope`         | 预留 | 地块级`slope_class` 未存储                                                |
| `get_parcels_by_aspect`        | 预留 | 地块级`aspect_class` 未存储                                               |
| `get_designated_zones`         | 预留 | `designated_as` 关系未写入                                                |
| `check_protected_parcels`      | 预留 | 硬编码中文过滤条件                                                          |

三线覆盖率查询的正确路径：不查 KG，用 `ConstraintIndex`。

---

## 七、跨模块交互设计

### 7.1 当前交互（已实现）

```
VillageBundle
  │
  ├──→ spatial_ops.geometry.compute_parcel_relations()
  │       └──→ ParcelRelations → KG._add_parcel_relations() → Layer 2
  │
  ├──→ spatial_ops.bridge.build_constraint_index()
  │       └──→ ConstraintIndex → KG._constraint_index → check_constraint_violations()
  │
  ├──→ spatial_ops.bridge.compute_water_overlap()
  │       └──→ water_overlap → KG._add_water_bodies() → 去重
  │
  ├──→ spatial_ops.compute_cross_type_relations() [v4.8.1]
  │       └──→ cross_type_relations → KG._add_cross_type_relations() → located_in/intersects/contains
  │
  └──→ KG.build_from_bundle(bundle, parcel_relations, constraint_index,
                             water_overlap, cross_type_relations, intent, planned_state)
```

### 7.2 Wave 1 交互：契约统一

| 模块                                    | 与 KG 的交互                                                                                    | 说明                                                                    |
| --------------------------------------- | ----------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `schema/encodings/vocabulary.py`      | KG 消费`PlanningZone`/`LanduseClass` 枚举验证查询参数                                       | `semantic.py:get_parcels_by_planning_zone()` 已使用                   |
| `schema/contracts/parse_contracts.py` | `ZoneTarget.land_use` 改为 `LanduseClass` 枚举                                              | Layer3 构建时验证枚举值合法性                                           |
| `schema/encodings/code_sets.py`       | 语义层推导：`resolve_zone_type_for_dlbm`, `DLBM_TO_DLMC`, `PLANNING_ZONE_TO_CONTROL_CODE` | `layer1.py: _derive_semantic_label/taxonomic_parent/legal_constraint` |

---

## 八、模块结构

```
backend/app/modules/kg/
├── __init__.py               # 公开 API 导出
├── README.md                 # 本文档
├── ontology.py               # 本体定义: 实体类型 + 关系类型 + EntityIdPolicy + SemanticPredicates
├── manager.py                # KGManager: 三层缓存 + 会话管理 + 查询缓存（版本化失效）
├── memory.py                 # [v4.6] SemanticMemoryStore: 实体+关系注解 + 写时读
├── builder/                  # 四层构建器子包
│   ├── __init__.py           # 导出 PlanningKG, KGInputParcels, Mixin 类
│   ├── base.py               # PlanningKG 骨架: __init__ + build_from_bundle（编排器）
│   │                          # + clone_static_layer + print_summary
│   ├── layer1.py             # Layer 1: 现状实体 + 扩展几何组 + 三维度 + LayerGroup + 语义层
│   ├── layer2.py             # Layer 2: 空间关系（委托 layer1.py）
│   ├── layer3.py             # Layer 3: 意图虚拟实体（结构化锚定属性）
│   ├── layer4.py             # Layer 4: 规划成果（PlannedState → 版本化增量 + 查询方法）
│   └── mixins.py             # Mixin 类（替代 monkey-patching）
└── queries/
    ├── __init__.py            # 四命名空间 API + 导出所有查询函数
    ├── sparql.py              # SPARQL 模板注册表 + query_kg() + KG 实例方法 (QueryMixin)
    ├── spatial_ref.py            # [v4.9] resolve_candidates - KG 侧候选 BSM 解析（属性+L2 关系）
    ├── semantic.py            # LLM 友好语义查询 + 写时读注解 + 实体语义层查询
    ├── cognition.py           # [v4.8] 三层认知摘要（get_village_cognition + get_layer_group_semantics）
    ├── contracts.py           # [v4.8] DualPayload + TokenBudget + TopKSampler
    └── README.md              # [v4.9] 四命名空间 API 使用指南
```

### 8.1 方法分配机制

每个 layer 文件定义模块级函数，通过 `mixins.py` 中的 Mixin 类继承到 `PlanningKG`：

```python
class PlanningKG(Layer1Mixin, Layer2Mixin, Layer3Mixin, Layer4Mixin, QueryMixin):
    ...
```

### 8.2 各层方法清单

| 文件                   | 方法                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | 职责                          |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| `layer1.py`          | `_add_village_entity`, `_add_parcels`, `_add_water_bodies`, `_add_control_lines_from_typed`, `_add_planning_elements_from_typed`, `add_annotations`, `add_roads`, `add_terrain`, `_add_village_meta_from_bundle`, `_add_residential_clusters_from_typed`, `_add_facilities_from_typed`, `_add_facilities_from_annotations`, `_add_parcel_relations`, `_parcel_uri_by_bsm_dlbm`                                                                    | 现状实体构建 + 空间关系       |
| `layer1.py` (v4.8)   | `_add_gis_layer_groups`, `_add_semantic_enrichment`                                                                                                                                                                                                                                                                                                                                                                                                                       | 图层组虚拟实体 + 语义层写入   |
| `layer1.py` (v4.8.1) | `_add_protection_polygons`, `_add_buildings`, `_add_terrain_entities`, `_add_boundaries`, `_add_natural_resource_zones`, `_add_cross_type_relations`, `_compute_cross_type_heuristic`                                                                                                                                                                                                                                                                           | 扩展几何组 + 交叉类型关系     |
| `layer3.py`          | `build_intent_layer`, `clear_intent_layer`                                                                                                                                                                                                                                                                                                                                                                                                                                | 意图虚拟实体（结构化锚定）    |
| `layer4.py`          | `_apply_planned_state`, `get_effective_land_use`, `get_effective_area_ha`, `get_plan_changes`, `get_planned_parcels_in_zone`, `check_constraint_violations`, `compare_versions`                                                                                                                                                                                                                                                                                 | 规划成果（版本化增量 + 查询） |
| `sparql.py`          | `query`, `get_adjacency_map`, `get_parcel_count`, `get_triple_count`, `serialize`, `to_turtle`, `from_turtle`, `get_parcels_within_distance_of_entity`, `get_adjacent_parcels_with_length`, `get_connected_parcels`, `get_parcels_by_bsm_list`, `validate_intent`, `_is_in_protected_zone`, `get_constraint_coverage`                                                                                                                             | SPARQL 查询 + 实例方法        |
| `semantic.py`        | `get_entity_context`, `get_entity_relations`, `get_parcel_semantic_context`, `get_village_semantic_summary`, `get_entity_by_bsm`, `get_parcels_by_planning_zone`, `get_l4_derived_from_l1`, `get_village_constraint_coverage`, `get_entity_semantics`, `get_parcels_semantic_list`, `get_parcel_detail_semantic`, `get_parcel_neighbors_semantic`, `get_facilities_semantic_list`, `get_road_network_semantic`, `get_designated_zones_semantic` | LLM 语义查询 + 写时读注解     |
| `cognition.py`       | `get_village_cognition`, `get_layer_group_semantics`                                                                                                                                                                                                                                                                                                                                                                                                                      | (v4.8) 三层认知摘要           |

---

## 九、端到端示例

```python
from app.modules.data import DataCatalog
from app.modules.spatial_ops.geometry import compute_parcel_relations
from app.modules.spatial_ops.bridge import build_constraint_index
from app.modules.kg import PlanningKG, get_kg_manager
from app.modules.schema.contracts.parse_contracts import (
    SpatialPlanningIntent, ZoneTarget, FacilityTarget, AxisTarget, RoadTarget,
)

# 1. 加载数据
catalog = DataCatalog()
bundle = catalog.load_village_bundle("金田村委会")

# 2. 计算三层空间关系
relations = compute_parcel_relations(
    bundle.polygons.landuse_current,
    roads=bundle.lines.roads_current,
)

# 3. 构建约束索引
ci = build_constraint_index(bundle)

# 4. 构建 PARSE 意图 (Layer 3)
intent = SpatialPlanningIntent(
    village_name="金田村委会",
    zone_targets=[
        ZoneTarget(land_use="2121", area_ratio=0.15, candidate_bsms=["001", "002"]),
    ],
    facilities=[
        FacilityTarget(type="展销中心", status="planned_new", service_radius=500),
    ],
    development_axes=[
        AxisTarget(direction="南北", reference_feature="村主干道"),
    ],
    road_targets=[
        RoadTarget(road_level="村道", width_m=4.5, connects=["村主干道"]),
    ],
)

# 5. 构建 KG (Layer 1-4) + 约束索引
kg = PlanningKG("金田村委会")
kg.build_from_bundle(
    bundle=bundle,
    parcel_relations=relations,
    constraint_index=ci,
    intent=intent,                    # → L3 虚拟实体
    planned_state=None,               # → L4 规划成果（可选）
)

# 6. SPARQL 查询
parcel_count = kg.get_parcel_count()                      # 660
adjacent = kg.get_adjacent_parcels_with_length("BSM-001") # 邻接地块
nearby = kg.get_parcels_within_distance_of_entity(
    "http://village-planning.org/ontology#village_ann_刘村", 500)

# 7. 语义查询（v4.8 认知）
from app.modules.kg.queries.cognition import get_village_cognition
payload = get_village_cognition(kg, "金田村委会")
print(payload.semantic["context_block"]["overview"])  # "金田村委会，总面积..."
print(payload.semantic["layer_cards"])                 # [图层组卡片, ...]
print(payload.structured["representative_bsms"])       # [代表性 BSM, ...]

# 8. 语义层查询（v4.8）
from app.modules.kg.queries.semantic import get_entity_semantics
info = get_entity_semantics(kg, entity_label="水田")
# info.taxonomic_parent → "农业用地"
# info.legal_constraint → "forbid_construction"
# info.allowed_operations → []

# 9. 约束覆盖查询
from app.modules.kg.queries.semantic import get_village_constraint_coverage
coverage = get_village_constraint_coverage(kg)
# -> [{"summary": "共 45 个地块与约束面重叠", ...}]

# 10. SemanticMemoryStore 查询
from app.modules.kg.memory import get_semantic_memory
memory = get_semantic_memory()
entity_info = memory.get_entity_semantics("pln:ResidentialCluster/刘村")
relation_info = memory.get_relation_semantics("pln:ResidentialCluster/刘村",
                                               "pln:north_of",
                                               "pln:ResidentialCluster/八社村")

# 11. 工具调用
from app.modules.kg.queries.sparql import query_kg, TOOL_META
parcels = query_kg(kg, "get_village_parcels")
# -> [{"bsm": "...", "dlbm": "0101", "description": "P001: 水田(0101) 0.5ha 农田保护区"}, ...]
```

---

## 十、实际数据验证 (jintian)

### 10.1 KG 金标准快照（`tests/integration/fixtures/golden/jintian_kg_snapshot.ttl`）

| 指标                        | 值     |
| --------------------------- | ------ |
| 总三元组                    | 47,226 |
| 地块 (Parcel)               | 660    |
| 道路 (Road)                 | 131    |
| 设施 (Facility)             | 30     |
| 居民点 (ResidentialCluster) | 19     |
| 分区 (Zone)                 | 96     |

### 10.2 GeoSPARQL 谓词分布（v4.9 硬断言回归保护）

| 谓词                                | 三元组数 | 说明                                             |
| ----------------------------------- | -------- | ------------------------------------------------ |
| `geo:sfTouches`                   | 3,382    | parcel-parcel 邻接（双向）                       |
| `pln:nearby`                      | 6,048    | 质心距离 ≤ 200m                                 |
| `pln:connected_via_road`          | 361      | 道路穿越连通                                     |
| `geo:sfWithin`                    | 1,190    | facility-in-parcel + parcel-in-village           |
| `geo:sfIntersects`                | 1,261    | road-crosses-parcel + parcel-overlaps-protection |
| `geo:sfContains`                  | 0        | boundary-contains-parcel（金田数据未触发）       |
| `geo:hasGeometry` / `geo:asWKT` | 0        | VKG 决策：无全几何                               |

### 10.3 测试

```bash
cd backend
python -m pytest tests/unit/test_dualpayload_contract.py tests/unit/test_spatial_ref_contracts.py -v
python -m pytest tests/integration/test_village_cognition.py tests/integration/test_spatial_ref_resolve.py tests/integration/test_l4_provenance.py -v
python -m pytest tests/integration/test_golden_kg_snapshot.py -v
```

---

## 十一、变化记录

| 版本   | 变更                                                                                                                                                                                                   |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| v4.9   | **GeoSPARQL 谓词对齐** — 4 个空间谓词改为 `geo:sfTouches`/`sfWithin`/`sfIntersects`/`sfContains`；`Relations` 类同步更新，旧名不在 active set                                         |
| v4.9   | **候选 BSM 查询** — `spatial_ref.py` 新增 `resolve_candidates(kg, spec) → CandidateSet`，支持属性过滤 + L2 关系查询，暴露在 `parse_queries`                                              |
| v4.9   | **L4 provenance 链** — `PlannedParcelEntry` 扩展 `source_spec`/`decided_by`/`operation`/`area_change_ha`，`_apply_planned_state` 写入全部 5 个溯源谓词                              |
| v4.9   | **金标准回归保护** — `test_golden_predicate_distribution` 硬断言 8 个谓词分布 + VKG 无几何不变量；`test_village_cognition` 7 项认知完整性断言                                               |
| v4.9   | **命名空间补全** — `get_parcels_near_point` 暴露在 `parse_queries`；`BINDING_MAP` 修复 `min_lon/max_lon` 映射                                                                           |
| v4.8.1 | **交叉类型空间关系** — `geo:sfWithin`/`geo:sfIntersects`/`geo:sfContains` 三种跨类型关系，由 spatial_ops 预计算注入或 KG 内部质心启发式回退                                               |
| v4.8.1 | **扩展几何组** — 新增 `_add_protection_polygons`(保护多边形)/`_add_buildings`(建筑)/`_add_terrain_entities`(地形)/`_add_boundaries`(边界)/`_add_natural_resource_zones`(自然资源分区) |
| v4.8.1 | **本体清理** — 关系 15→8：合并 `within→located_in`, `crosses+overlaps→intersects`, `bounds→contains`                                                                                  |
| v4.8.1 | **`GIS_LAYER_GROUP_REGISTRY` 移除** — 硬编码字典 → `gis_layer_registry.yaml` 运行时动态读取 (`get_gis_layer_group_info`)                                                                 |
| v4.8.1 | **L3 粗糙几何移除** — L3 意图实体不再存储粗糙几何 WKT，改为纯结构化锚定属性                                                                                                                     |
| v4.8.1 | **水体重叠去重** — `water_overlap` 参数注入，重复水体和 3100 码地块去重                                                                                                                       |
| v4.8   | **空间认知层** — 三维度谓词 + LayerGroup 虚拟实体 + 语义层谓词 + DualPayload + TokenBudget + TopKSampler                                                                                        |
| v4.8   | **四命名空间查询 API** — `analysis_queries`/`parse_queries`/`execute_queries`(预留)/`shared_queries`                                                                                    |
| v4.8   | **认知查询** — `get_village_cognition`(三层认知摘要) + `get_entity_semantics`(语义层查询)                                                                                                   |
| v4.8   | **语义列表查询** — SPARQL 模板自动语义分发 (`SEMANTIC_QUERIES` 注册表)                                                                                                                        |
| v4.7   | **EntityIdPolicy 统一标识契约** — 14 个 builder 统一 URI 方案，所有 L1/L4 实体存 `PLN.bsm` literal                                                                                            |
| v4.7   | **ThreeZone/ThreeLine 从 KG 移除** — 改为 `ConstraintIndex`（spatial_ops bridge）注入                                                                                                         |
| v4.7   | **L4→L3 链接实现** — `derived_from_target` 三元组写入，L4 实体可追溯至 L3 意图                                                                                                               |
| v4.7   | **get_adjacency_map 修复** — 从 URI 前缀解析改为 BSM literal 查询                                                                                                                               |
| v4.7   | **约束验证修复** — `check_constraint_violations` 改用 `ConstraintIndex` 空间 overlay                                                                                                        |
| v4.7   | **重复 BSM 处理** — `uri_with_seq` 序号后缀消歧                                                                                                                                               |
| v4.6   | **重构：只存空间实体** — 删除 `ControlRule`, `PlanningIndicator`, `Constraint`, `PlanIntent` 从 EntityTypes                                                                             |
| v4.6   | **删除关系** — 8 个关系类型从 KG 移除                                                                                                                                                           |
| v4.6   | **新增 SemanticMemoryStore** — 实体+关系注解                                                                                                                                                    |
| v4.6   | **新增 L3 虚拟实体构建器** — Intent → 粗糙几何 + 空间关系                                                                                                                                      |
| v4.6   | **新增 L4 PlannedState** — 增量聚合视图，形态对齐 bundle                                                                                                                                        |
| v4.6   | **变更 KG builder** — 从 bundle 形态分组直连，不再依赖 ContextBlock                                                                                                                             |
| v4.6   | **变更方法分配** — 从 monkey-patching → Mixin 类继承                                                                                                                                           |
