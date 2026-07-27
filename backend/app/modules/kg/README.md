# Planning Knowledge Graph (KG) 模块

> **定位**: 村庄规划系统的**空间语义引擎** — 只存有几何的空间实体及其关系
> **层级**: `Schema ← Data ← SpatialOps ← KG ← Agent`
> **依赖**: 仅依赖 `app.modules.schema`；不依赖 Data/Agent/Tools
> **Updated: 2026-07-26 (v4.7)** — EntityIdPolicy 统一标识、ThreeZone/ThreeLine 移除、约束验证改用 ConstraintIndex

---

## 一、核心原则

### 1.1 KG 只存"有几何的空间要素"

```
进 KG RDF 图:   Parcel, Road, WaterBody, Facility, Zone, ...
不进 KG:        ControlRule, PlanningIndicator, Constraint (数值),
                PlanIntent (语义), 编码体系分类树
```

非空间要素通过以下方式传递：

| 类型 | 去向 |
|------|------|
| `ControlRule` | `bundle.tables.control_rules` |
| `PlanningIndicator` | `bundle.tables.planning_indicators`（PARSE Agent 填充） |
| `Constraint` (数值约束) | `ContextBlock.CONSTRAINTS.data` |
| `PlanIntent` (语义容器) | `SpatialPlanningIntent` 对象本身 |
| 编码体系 (DLBM/GHYTBM/TUGUI/...) | Schema 层 `encodings/code_sets.py`，按需查询 |

**编码体系管理原则**：KG 只在地块属性中存储编码值（`pln:dlbm`、`pln:vne_code`、`pln:planning_zone`），不存储编码体系本身的分类树。分类树查询通过 Schema 层的 `encodings/` 模块按需返回，不走 KG RDF 图。

### 1.2 编码值的使用模式：事实 vs 推荐

KG 中存储的编码属性分为两类，消费者必须理解其语义差异：

| 类别 | 属性 | 来源 | 确定性 | 消费方式 |
|------|------|------|--------|---------|
| **事实型** | `pln:dlbm`, `pln:sddlbm`, `pln:dlbm_system`, `pln:current_zone_type` | 数据层 ingest 直接读取 + 编码体系确定性映射 | 确定 | 查询、筛选、聚合 |
| **推荐型** | `pln:planning_zone`, `pln:primary_zone`, `pln:vne_code` | 编码体系提供的推荐映射，LLM 可依据上下文修正 | 推荐 | 作为 LLM 参考，最终决定权在规划师 |

**事实型字段**（如 `current_zone_type`）：通过 `resolve_zone_type_for_dlbm()` 从 GB/T 21010/附录5 编码体系确定性派生。例如 DLBM `0101` → `current_zone_type = "农业用地"`。这是编码体系本身的分类树查找，不涉及 LLM 判断。

**推荐型字段**（如 `planning_zone`）：编码体系提供的"建议分区"（如 DLBM `0101` 耕地 → 建议 `planning_zone = "农田保护区"`），但实际规划中可能因上位规划调整、村民意愿、地块位置等因素改变。LLM 应：
1. 以 `planning_zone` 推荐值作为起点
2. 结合上下文（上位规划、邻接地块、居民点分布）判断是否需要修正
3. 最终 `SpatialPlanningIntent` 中的 `zone_targets` 覆盖推荐值

```python
# KG 内部：事实型与推荐型分开存储
# _add_parcels() 中:
zt = resolve_zone_type_for_dlbm(dlbm)  # 事实型: 编码体系确定性查找
self.g.add((pu, PLN.current_zone_type, Literal(zt)))

pz = getattr(p, "planning_zone", "") or ""  # 推荐型: 来自数据层 ingest 的推荐值
if pz:
    self.g.add((pu, PLN.planning_zone, Literal(pz)))
```

### 1.3 关系本身就是语义

KG 的 RDF 三元组不仅描述实体属性，更描述实体间的空间关系。**注解必须同时附着于实体和关系**，不能只存实体级注解：

```python
# 实体注解
EntityAnnotation(entity_uri, description, source_text_refs, intent_refs)

# 关系注解
RelationAnnotation(subject_uri, predicate, object_uri,
                   description, derived_from, quantitative_detail)
```

### 1.4 Intent 以虚拟实体进 KG（L3 易失层）

ZoneTarget、FacilityTarget、RoadTarget 作为 L3 临时虚拟实体进入 KG，有粗糙几何表示，参与空间关系计算。EXECUTE 通过 SPARQL 查询这些虚拟实体与现状实体之间的空间关系（冲突检测、候选地块筛选）。

### 1.5 PlanBlock 是 Agent 记忆，不进 KG

| 结构 | 本质 | 消费者 | 持久化 |
|------|------|--------|--------|
| **ContextBlock** | 现状空间认知卡片 | PARSE prompt | 不持久化 |
| **PlanBlock** | 增量变更操作记录 | 累积 → PlannedState | 可选会话日志 |
| **PlannedState** | 规划成果空间实体（聚合） | KG Layer 4 | 持久化 |

### 1.6 零 shapely/geopandas 依赖

所有几何计算由 `spatial_ops` 完成，KG 只消费结构化数据。

---

## 二、四层架构

| 层 | 内容 | 生命周期 | 写入者 | 消费者 |
|----|------|---------|--------|--------|
| Layer 1 | 现状空间实体 + 属性编码 | 持久（数据更新时重建） | Data Layer → bundle 直连 | SPARQL 查询、PARSE、EXECUTE |
| Layer 2 | 空间关系 | 持久 | `spatial_ops` 计算 | SPARQL 查询、EXECUTE |
| Layer 3 | 意图虚拟实体（粗糙几何 + 空间关系） | 会话易失 | PARSE → `build_intent_layer` | EXECUTE 空间推理 |
| Layer 4 | 规划成果实体（版本化增量） | 会话持久 | EXECUTE → PlannedState | 导出、对比、校验 |

### 2.1 系统位置

```
bundle (VillageBundle)
  │
  ├──→ compute_context_blocks() → ContextBlock[] → PARSE prompt (agent 记忆)
  │
  └──→ KG.build_from_bundle(bundle, relations, intent, planned_state)
         │
         ├── Layer 1: 现状实体 (bundle 形态分组直连)
         ├── Layer 2: 空间关系 (parcel_relations 参数)
         ├── Layer 3: 意图虚拟实体 (intent → 粗糙几何)
         └── Layer 4: 规划成果 (PlannedState → 版本化增量)
```

### 2.2 构建入口

```python
kg = PlanningKG(village_name="金田村委会")
kg.build_from_bundle(
    bundle=bundle,              # VillageBundle — 类型化形态视图
    parcel_relations=relations, # ParcelRelations — 三层空间关系（外部计算）
    intent=intent,              # SpatialPlanningIntent → L3 虚拟实体（可选）
    planned_state=planned,      # PlannedState → L4 规划成果（可选）
)
```

**注意**：KG builder 直接从 `bundle.polygons.landuse_current`、`bundle.lines.roads_current` 等形态分组读取，不依赖 ContextBlock。ContextBlock 只作为 PARSE 的 prompt 上下文。

### 2.3 Layer 1: 现状实体

| 实体类型 | 数据来源 | 方法 | 标识键 |
|---------|---------|------|--------|
| `pln:AdministrativeVillage` | `bundle.metadata` | `_add_village_entity` | singleton (`pln:village`) |
| `pln:Parcel` | `bundle.polygons.landuse_current` | `_add_parcels` | `PLN.bsm` literal ✅ |
| `pln:Road` | `bundle.lines.roads_current` | `add_roads` | `PLN.bsm` literal ✅ |
| `pln:WaterBody` | `bundle.polygons.water_bodies` | `_add_water_bodies` | `PLN.bsm` literal ✅ |
| `pln:Facility` | `bundle.points.facilities_current` | `_add_facilities_from_typed` | `PLN.bsm` literal ✅ |
| `pln:ResidentialCluster` | `bundle.polygons.landuse_current` 注记 | `_add_residential_clusters_from_typed` | `PLN.name` ⚠️ |
| `pln:Zone` | `bundle.polygons.land_use_zones` / `construction_ctrl_zones` | `_add_planning_elements_from_typed` | `PLN.bsm` literal ✅ |
| `pln:ControlLine` | `bundle.polygons.hazard_control_lines` / `flood_control_lines` | `_add_control_lines_from_typed` | `PLN.bsm` literal ✅ |

**编码属性存储**：每个 `pln:Parcel` 实体存储以下属性：
- 事实型：`pln:dlbm`、`pln:sddlbm`、`pln:current_zone_type`（从 DLBM 确定性派生）
- 推荐型：`pln:planning_zone`、`pln:primary_zone`（来自数据层 ingest 的推荐值）
- 原始：`pln:dlmc`、`pln:ysdm`、`pln:dlbm_system`（忠实存储，不派生）
- 几何：`pln:area_sqm`、`pln:area_ha`、`pln:lon`、`pln:lat`（质心坐标）

### 2.4 Layer 2: 空间关系

由 `spatial_ops.compute_parcel_relations()` 计算，KG 通过 `_add_parcel_relations` 消费。

| 层次 | 关系 | 属性 | 对规划的意义 |
|------|------|------|------------|
| L1: 拓扑邻接 | `:touches` | `:shared_boundary_length` | 地块合并/拆分、连片开发 |
| L2: 近邻关系 | `:nearby` | `:centroid_distance` | 设施选址、公共服务覆盖 |
| L3: 连通关系 | `:connected_via_road` | `:road_segment_length` | 交通可达性 |

### 2.5 Layer 3: 意图虚拟实体（易失）

`SpatialPlanningIntent` 的 `zone_targets`、`facilities`、`development_axes` 被转换为有粗糙几何的临时空间实体，参与空间关系计算：

```python
kg.build_intent_layer(intent)
# 在 KG 中创建:
#   pln:Intent/zone_target_1  (ZoneTarget, 粗糙几何 ≈ bbox)
#   pln:Intent/facility_1     (FacilityTarget, 点 + 缓冲区)
#   pln:Intent/road_1         (RoadTarget, 线 + 缓冲区)
```

**生命周期**：当前规划会话结束时清除（`kg.clear_intent_layer()`）。

### 2.6 Layer 4: 规划成果（版本化增量）

`PlannedState` 是增量变更的累积视图，和 `VillageBundle` 形态对齐：

```python
@dataclass
class PlannedState:
    version: str = "current"
    polygons: List[PlannedParcelEntry]   # 规划地块（面）
    points: List[PlannedFacilityEntry]   # 规划设施点（点）
    lines: List[PlannedRoadEntry]        # 规划道路（线）
    source: str = ""
```

每个 Entry 继承自 `SpatialCognitiveUnit` 形态基类，天然有几何和 URI。L4 进入 KG 时和 L1 一样处理，只是加版本标签。**稀疏写入**：未变更的地块不写入 L4 三元组，查询时回退到 L1。

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

    @staticmethod
    def attach_bsm(graph, uri, bsm):
        # graph.add((uri, PLN.bsm, Literal(bsm)))
```

#### 实现状态

| 层 | 实体 | URI 方案 | `PLN.bsm` literal | 可追溯 |
|----|------|---------|-------------------|--------|
| L1 | Parcel | `EntityIdPolicy.uri_with_seq("parcel", bsm, seq)` | ✅ | ✅ |
| L1 | Road | `EntityIdPolicy.uri("road", bsm)` + fallback | ✅ | ✅ |
| L1 | WaterBody | `EntityIdPolicy.uri("water", bsm)` + fallback | ✅ | ✅ |
| L1 | Facility | `EntityIdPolicy.uri("facility", bsm)` + fallback | ✅ | ✅ |
| L1 | ResidentialCluster | `EntityIdPolicy.fallback_uri("village_ann", name, seq)` | ⚠️ 按名 | ⚠️ |
| L1 | ControlLine | `EntityIdPolicy.uri/fallback` per type | ✅ | ✅ |
| L1 | Zone (TDYT/jsydgzq) | `EntityIdPolicy.uri/fallback` | ✅ | ✅ |
| L3 | ZoneTarget | `EntityIdPolicy.uri("zone_target", target_id)` | `PLN.target_id` | ✅ |
| L3 | FacilityTarget | `EntityIdPolicy.uri("facility_target", target_id)` | `PLN.target_id` | ✅ |
| L3 | AxisTarget | `EntityIdPolicy.uri("axis_target", target_id)` | `PLN.target_id` | ✅ |
| L4 | PlannedParcel | `EntityIdPolicy.uri("planned_parcel", bsm, version)` | ✅ | ✅ `derived_from` -> L1 |
| L4 | PlannedZone | `EntityIdPolicy.uri("planned_zone", zone_id, version)` | `PLN.zone_type` | ✅ `derived_from_target` -> L3 |
| L4 | PlannedFacility | `EntityIdPolicy.uri("planned_facility", fac_id, version)` | `PLN.name` | ✅ `derived_from_target` -> L3 |
| L4 | PlannedRoad | `EntityIdPolicy.uri("planned_road", road_id, version)` | `PLN.name` | ✅ `derived_from_target` -> L3 |
| L4 | PlannedAxis | `EntityIdPolicy.uri("planned_axis", axis_id, version)` | `PLN.name` | ✅ `derived_from_target` -> L3 |

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

| 形态 | 实体 | 说明 | 编码属性 |
|------|------|------|---------|
| 面 | `Parcel` | 现状地类图斑 | `dlbm`(事实), `current_zone_type`(事实), `planning_zone`(推荐), `primary_zone`(推荐), `vne_code`(推荐) |
| 面 | `WaterBody` | 水域 | — |
| 面 | `Zone` | 规划分区（TDYT/JSYDGZQ） | — |
| 面 | `AdministrativeVillage` | 行政村（singleton） | — |
| 面 | `ResidentialCluster` | 居民点 | — |
| 点 | `Facility` | 现状设施点 | `facility_type` |
| 线 | `Road` | 现状道路 | `road_level` |
| 面 | `ControlLine` | 控制线（灾害/洪涝/有条件建设） | — |

### 3.2 意图虚拟实体（Layer 3，易失）

| 形态 | 实体 | 说明 |
|------|------|------|
| 面 | `ZoneTarget` | 分区目标（粗糙几何 ≈ bbox） |
| 点 | `FacilityTarget` | 设施目标（点 + 缓冲区） |
| 线 | `RoadTarget` | 道路目标（线 + 缓冲区） |
| 线 | `AxisTarget` | 发展轴线 |

### 3.3 规划成果实体（Layer 4，版本化）

| 形态 | 实体 | 说明 |
|------|------|------|
| 面 | `PlannedParcel` | 规划地块（精确几何，版本标签） |
| 点 | `PlannedFacility` | 规划设施点 |
| 线 | `PlannedRoad` | 规划道路 |

---

## 四、关系类型

### 4.1 空间拓扑关系

| 关系 | 方向 | 属性 | 说明 |
|------|------|------|------|
| `touches` | 双向 | `shared_boundary_length` | 拓扑邻接（取代 `adjacent_to`） |
| `nearby` | 双向 | `centroid_distance` | 近邻关系（≤ 200m） |
| `connected_via_road` | 双向 | `road_segment_length`, `via_road` | 路网连通 |
| `within_zone` | 单向 | — | 包含于分区 |
| `located_in` | 单向 | — | 位于（行政村→居民点→地块） |
| `delineates` | 单向 | — | 划定 |

### 4.2 规划语义关系

| 关系 | 方向 | 说明 |
|------|------|------|
| `designated_as` | 单向 | 地块被指定为某分区 |
| `derived_from` | 单向 | 规划地块源于现状地块 |
| `serves` | 单向 | 设施服务于某区域 |
| `connects` | 单向 | 村庄连接道路 |

### 4.3 已删除的关系

| 关系 | 理由 | 去向 |
|------|------|------|
| `constrained_by` | 约束是 ContextBlock 数值，不是实体间关系 | ContextBlock.CONSTRAINTS.data |
| `achieves` | 指标达标由 bundle.tables 体现 | `bundle.tables.planning_indicators` |
| `conflicts_with` | 冲突检测结果，运行时计算 | 不持久化 |
| `conducted_from` | 上位传导在指标表字段中 | `bundle.tables.planning_indicators` |
| `controls_use` | ControlRule 字段 | `bundle.tables.control_rules` |
| `protects` | ThreeLine 的属性字段，非关系 | 改为属性 |
| `adjacent_to` | 已废弃 | 由 `touches` 替代 |
| `location_constraint` | 属性非关系 | L3 虚拟实体的 LocationConstraint 字段 |

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
    entity_annotations: Dict[str, EntityAnnotation]
    relation_annotations: Dict[str, RelationAnnotation]

    def get_entity_semantics(self, uri: str) -> Dict:
        """返回实体属性 + 人类可读注解 + 参与的语义关系"""

    def get_relation_semantics(self, subject, predicate, object) -> Dict:
        """返回关系本身 + 注解 + 量化细节"""
```

### 5.4 与 RDF 图的协同

```
KG RDF 图 (结构化):              SemanticMemoryStore (语义注解):
  (:刘村, :north_of, :八社村)     "刘村位于八社村北侧，两村相距约 1.2km"
  (:刘村, :touches, :P001)       "刘村南侧地块 P001 与基本农田相邻"
```

当 LLM 查询时，两者合成返回复合结果：

```json
{
  "entity": {"uri": "pln:ResidentialCluster/刘村", "parcel_count": 45},
  "relations": [
    {
      "predicate": "north_of",
      "object": "八社村",
      "description": "刘村位于八社村北侧，两村相距约 1.2km，通过 X203 县道相连",
      "distance_m": 1200
    }
  ]
}
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
│  ├── parcel_relations    → Layer 2 (空间关系)              │
│  ├── intent              → Layer 3 (虚拟实体, 易失)        │
│  └── planned_state       → Layer 4 (规划成果, 版本化)      │
└──────────────────────────────────────────────────────────┘
        ▲                        │
        │                        ▼
┌───────────────────┐  ┌──────────────────┐
│ PARSE Agent       │  │ EXECUTE Agent    │
│ 消费: query_kg,   │  │ 消费: SPARQL,    │
│      TOOL_META,   │  │      get_adj_map,│
│      semantic.py  │  │      validate    │
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
from app.modules.kg.queries.tools import query_kg, TOOL_META

# LLM 可调用的查询工具
result = query_kg(knowledge_graph, "parcels_by_planning_zone",
                  planning_zone="村庄建设区")
# 返回: [{"bsm": "001", "dlbm": "0701", "area_ha": 0.5}, ...]

# 30+ 预定义模板
TOOL_META = [
    {"name": "parcels_by_dlbm", "description": "按 DLBM 编码查询地块"},
    {"name": "count_by_planning_zone", "description": "按规划分区统计地块数"},
    {"name": "count_by_vne", "description": "按 VNE 编码统计地块"},
    {"name": "get_parcel_adjacent", "description": "查询地块邻接关系"},
    # ...
]
```

**渠道 2：语义查询（LLM 友好）**

```python
from app.modules.kg.queries.semantic import (
    get_entity_context,          # 实体属性 + 注解
    get_entity_relations,        # 实体关系 + 描述
    get_parcel_semantic_context, # 地块语义上下文
    get_village_semantic_summary,# 村庄语义摘要
    get_parcels_by_planning_zone, # 按规划分区 + 编码推荐值
)

# 编码推荐值作为 LLM 参考
parcels = get_parcels_by_planning_zone(kg, "农田保护区")
# 返回: {"planning_zone": "农田保护区", "total_area_ha": 45.2,
#        "parcels": [{"bsm": "001", "dlbm": "0101", "area_ha": 0.5}, ...]}
# LLM 可据此判断: 该分区是否合理？是否需要调整？

# 三线覆盖语义查询（LLM 友好）
from app.modules.kg.queries.semantic import get_village_constraint_coverage
coverage = get_village_constraint_coverage(kg)
# 返回: [{"summary": "共 45 个地块与约束面重叠", "parcel_count": 45},
#        {"bsm": "001", "summary": "地块 001 与 永久基本农田(重叠35.0%) 重叠", ...}]
# LLM 可据此回答: "金田村有 45 个地块受三线管控，其中 12 个在永久基本农田范围内"
```

### 6.3 EXECUTE Agent 消费 KG

EXECUTE 通过 SPARQL 直查 KG，MIP 直接消费 flat dict 结果：

```python
# 查询接口
from app.modules.kg import PlanningKG

kg = PlanningKG("金田村委会")
kg.build_from_bundle(bundle=bundle, parcel_relations=relations, intent=intent)

# 空间关系查询
adj_map = kg.get_adjacency_map()                   # BSM → {neighbor_BSMs}
nearby = kg.get_parcels_within_distance_of_entity(entity_uri, 500)
connected = kg.get_connected_parcels(parcel_uri)

# 地块详情查询
parcels = kg.get_parcels_by_bsm_list(["001", "002"])  # 含 dlbm, area_ha, zone_type, planning_zone

# 约束验证
conflicts = kg.validate_intent(intent)  # 检查设施候选地块是否在保护区内

# 规划成果查询
changes = kg.get_plan_changes("v1", "v2")  # 版本间变更
effective = kg.get_effective_land_use("001")  # L4 回退 L1
```

### 6.4 Tools 层消费 KG

```python
from app.modules.kg import get_kg_manager, query_kg, TOOL_META

# KGManager 单例管理
manager = get_kg_manager()
kg = manager.get_or_build_kg(bundle, relations)  # 缓存 + 构建

# 通用 SPARQL 查询
result = query_kg(kg, "count_by_zone_type")

# 用于生成、导出、渲染
from app.modules.kg.queries.tools import TOOL_META
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

### 6.6 三线覆盖查询与 KG 查询接口

三线（永久基本农田/生态红线/历史保护范围等）是引用层，v4.7 从 KG 的 RDF 实体中移除，但**查询三线覆盖地块的接口在 KG 中实现**。KG 内部使用 `ConstraintIndex`（由 bundle 约束面构建的空间索引），对外暴露为 KG 查询方法，供 PARSE/EXECUTE/LLM 统一消费：

```
bundle.polygons.farmland_protection ──┐
bundle.polygons.ecological_redline  ──┤
bundle.polygons.historical_protection ─┤──→ ConstraintIndex ──→ KG.get_constraint_coverage()
bundle.polygons.hazard_control_lines ──┤                          │
bundle.polygons.flood_control_lines  ──┘                          ├── kg.get_constraint_coverage()  (structural)
                                                                   └── get_village_constraint_coverage(kg)  (LLM semantic)
```

**KG ↔ Bundle 交互**：bundle 提供现状数据（形态分组）和约束面（via ConstraintIndex），KG 消费两者。不存在 KG → bundle 的反向依赖，但 KG 通过 `_constraint_index` 持有 bundle 约束面的引用，实现查询时的双向数据关联。

```python
# 注入 ConstraintIndex
from app.modules.spatial_ops.bridge import build_constraint_index

ci = build_constraint_index(bundle)  # 从 bundle 约束面构建
kg.build_from_bundle(bundle, constraint_index=ci)

# ── 查询路径 A: 结构化查询 (queries.py) ──
# 用于 EXECUTE/MIP 等需要精确数值的场景
coverage = kg.get_constraint_coverage()
# 返回:
# [{"bsm": "441426...", "dlbm": "0101", "area_ha": 0.5,
#   "zone_type": "农业用地", "planning_zone": "农田保护区",
#   "constraints": [{"constraint_type": "farmland_protection",
#                    "overlap_pct": 0.35, "overlap_area_sqm": 1750, "rule": "禁止建设"}]},
#  ...]

# ── 查询路径 B: 语义查询 (semantic.py) ──
# 用于 PARSE/LLM 等需要自然语言理解的场景
from app.modules.kg.queries.semantic import get_village_constraint_coverage

result = get_village_constraint_coverage(kg)
# 返回:
# [{"summary": "共 45 个地块与约束面重叠", "parcel_count": 45, "constrained_bsms": [...]},
#  {"bsm": "441426...", "dlbm": "0101", "summary": "地块 441426... 与 永久基本农田(重叠35.0%) 重叠",
#   "constraints": [{"constraint_type": "farmland_protection", "overlap_pct": 0.35}], ...}]

# ── 查询路径 C: 单地块检查 (validate_intent 内部使用) ──
violations = kg.validate_intent(intent)  # 设施候选地块是否在保护区内
```

### 6.7 预留 SPARQL 模板说明

以下 SPARQL 模板定义在 `queries/tools.py` 中，但对应实体已从 KG 移除或尚未实现，其功能已被上述 KG 查询方法替代：

| 模板 | 状态 | 替代方案 |
|------|------|---------|
| `get_three_lines` | 废弃 | `kg.get_constraint_coverage()` 或 `get_village_constraint_coverage(kg)` |
| `get_three_zones` | 废弃 | 直接用 `count_by_planning_zone` 模板 |
| `get_protected_parcels_detail` | 废弃 | `kg.get_constraint_coverage()` |
| `get_indicators` | 废弃 | `bundle.tables.planning_indicators` |
| `get_parcels_by_slope` | 预留 | 地块级 `slope_class` 未存储 | 仅村庄级坡度聚合，地块级待 Wave 2 |
| `get_parcels_by_aspect` | 预留 | 地块级 `aspect_class` 未存储 | 同上 |
| `get_designated_zones` | 预留 | `designated_as` 关系未写入 | 待 Wave 1 constraint_compiler 接入 |
| `check_protected_parcels` | 预留 | 硬编码中文过滤条件 | 待 `vocabulary.py` 受控词表规范化 |

**三线覆盖率查询的正确路径**：不查 KG，用 `ConstraintIndex`：

```python
from app.modules.spatial_ops.bridge import build_constraint_index

constraint_index = build_constraint_index(bundle)
kg.build_from_bundle(bundle, constraint_index=constraint_index)

violations = kg.check_constraint_violations("v1")
# 返回: [{"bsm": "001", "protected_zone": "farmland_protection", "overlap_pct": 0.35}]

# 或直接查:
overlaps = constraint_index.parcel_in_constraint("001")
```

---

## 七、跨模块交互设计（v5.0+）

KG 与 spatial_ops、constraint_compiler、parcel_ops、road_planner、land_balance 的交互是架构设计的核心。

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
  └──→ KG.build_from_bundle(bundle, parcel_relations, constraint_index, intent, planned_state)
```

### 7.2 Wave 1 交互：契约统一（进行中）

| 模块 | 与 KG 的交互 | 说明 |
|------|-------------|------|
| `schema/encodings/vocabulary.py` | KG 消费 `PlanningZone`/`LanduseClass` 枚举验证查询参数 | `semantic.py:get_parcels_by_planning_zone()` 已使用 |
| `schema/contracts/parse_contracts.py` | `ZoneTarget.land_use` 改为 `LanduseClass` 枚举 | Layer3 构建时验证枚举值合法性 |
| `schema/contracts/constraint_contracts.py` | `CompiledConstraint`/`CompilationReport`/`ConflictRecord` | 约束编译结果，KG 通过 `constraint_index` 间接消费 |
| `spatial_ops/constraint_compiler.py` | 6 源编译 + 冲突仲裁，产出 `CompiledConstraint[]` | 编译结果通过 `ConstraintIndex` 注入 KG |

### 7.3 Wave 2 交互：执行能力（规划中）

| 模块 | 与 KG 的交互 | 说明 |
|------|-------------|------|
| `spatial_ops/parcel_ops.py` | 6 种几何操作 | 操作结果写入 `PlannedState` → KG Layer 4 |
| `spatial_ops/road_planner.py` | 道路网络生成器 | 产出 `PlannedRoadEntry` → KG Layer 4 |
| `agent/gis/execute/agent.py` | `_execute_road_node` 真实实现 | 消费 KG Layer 3 RoadTarget + Layer 1 Road |

```
KG Layer 3 (Intent)     KG Layer 1 (现状)         KG Layer 4 (规划成果)
  │                        │                        ▲
  │                        │                        │
  ▼                        ▼                        │
spatial_ops.parcel_ops ──→ PlannedState ────────────┘
spatial_ops.road_planner ──→ PlannedState ──────────┘
```

### 7.4 Wave 3 交互：闭环交付（规划中）

| 模块 | 与 KG 的交互 | 说明 |
|------|-------------|------|
| `schema/contracts/delivery_contracts.py` | `DeliveryGate`/`TargetPatch`/`LandBalanceTable` | 汇交成果数据契约，KG Layer 4 读取验证 |
| `spatial_ops/land_balance.py` | `compute_land_balance()` + `check_delivery_gate()` | 消费 KG Layer 4 的 `PlannedParcel` 面积聚合 |

```
KG Layer 4 (版本化规划成果)
  │
  ├──→ spatial_ops.land_balance.compute_land_balance()
  │       └──→ LandBalanceTable (用地平衡表)
  │
  └──→ spatial_ops.land_balance.check_delivery_gate()
          └──→ DeliveryGate 验证结果
```

### 7.5 交互分类总结

| 交互类型 | 方向 | 模块 | 接口 |
|---------|------|------|------|
| KG 消费外部数据 | 外部 → KG | `spatial_ops` → `parcel_relations` | `_add_parcel_relations()` |
| KG 消费外部数据 | 外部 → KG | `spatial_ops` → `constraint_index` | `check_constraint_violations()` |
| KG 消费外部数据 | 外部 → KG | `PlannedState` → L4 | `_apply_planned_state()` |
| 外部消费 KG 数据 | KG → 外部 | `query_kg()` / `get_adjacency_map()` | Tools/PARSE/EXECUTE |
| 外部消费 KG 数据 | KG → 外部 | `get_parcels_by_planning_zone()` | PARSE LLM 语义查询 |
| 外部消费 KG 数据 | KG → 外部 | `get_effective_land_use()` / `get_plan_changes()` | EXECUTE 版本管理 |

---

## 八、模块结构

```
backend/app/modules/kg/
├── __init__.py               # 公开 API 导出
├── README.md                 # 本文档
├── ontology.py               # 本体定义: 实体类型 + 关系类型 + EntityIdPolicy
├── manager.py                # KGManager: 缓存 + 会话管理
├── memory.py                 # [v4.6] SemanticMemoryStore: 实体+关系注解
├── builder/                  # 四层构建器子包
│   ├── __init__.py           # 导出 PlanningKG, KGInputParcels, Mixin 类
│   ├── base.py               # PlanningKG 骨架: __init__ + build_from_bundle
│   │                          # + clone_static_layer + print_summary
│   ├── layer1.py             # Layer 1: 现状实体（从 bundle 形态分组直连）
│   ├── layer2.py             # Layer 2: 空间关系（从 parcel_relations 注入）
│   ├── layer3.py             # Layer 3: 意图虚拟实体（intent -> 粗糙几何）
│   ├── layer4.py             # Layer 4: 规划成果（PlannedState -> 版本化增量）
│   └── mixins.py             # [v4.6] Mixin 类（替代 monkey-patching）
└── queries/
    ├── __init__.py            # 导出 SPARQL + 语义查询
    ├── sparql.py              # SPARQL 模板注册表 + query_kg() + KG 实例方法 (QueryMixin)
    └── semantic.py            # LLM 友好语义查询 + 写时读注解
```

### 8.1 方法分配机制

每个 layer 文件定义模块级函数，通过 `mixins.py` 中的 Mixin 类继承到 `PlanningKG`：

```python
class PlanningKG(Layer1Mixin, Layer2Mixin, Layer3Mixin, Layer4Mixin, QueryMixin):
    ...
```

### 8.2 各层方法清单

| 文件 | 方法 | 职责 |
|------|------|------|
| `layer1.py` | `_add_village_entity`, `_add_parcels`, `_add_water_bodies`, `_add_control_lines_from_typed`, `_add_planning_elements_from_typed`, `add_annotations`, `add_roads`, `add_terrain`, `_add_village_meta_from_bundle`, `_add_residential_clusters_from_typed`, `_add_facilities_from_typed`, `_add_parcel_relations` | 现状实体构建 + 空间关系 |
| `layer3.py` | `build_intent_layer`, `_add_structured_intent`, `clear_intent_layer` | 意图虚拟实体 |
| `layer4.py` | `_apply_planned_state`, `get_effective_land_use`, `get_effective_area_ha`, `get_plan_changes`, `get_planned_parcels_in_zone`, `check_constraint_violations`, `compare_versions` | 规划成果（[v5.0] PlannedParcelEntry/PlannedZoneEntry 新增 `geometry` WKT 字段） |
| `queries.py` | `query`, `get_adjacency_map`, `get_parcel_count`, `get_triple_count`, `serialize`, `to_turtle`, `from_turtle`, `get_parcels_within_distance_of_entity`, `get_adjacent_parcels_with_length`, `get_connected_parcels`, `get_parcels_by_bsm_list`, `validate_intent`, `_is_in_protected_zone` | 语义查询 |
| `queries/semantic.py` | `get_entity_context`, `get_entity_relations`, `get_parcel_semantic_context`, `get_village_semantic_summary`, `get_entity_by_bsm`, `get_parcels_by_planning_zone`, `get_l4_derived_from_l1` | [v5.0] LLM 语义查询 — 跨层实体查询、规划分区分布、L4→L1 追溯 |

---

## 九、端到端示例

```python
from app.modules.data import DataCatalog
from app.modules.spatial_ops.geometry import compute_parcel_relations
from app.modules.kg import PlanningKG, get_kg_manager
from app.modules.schema.contracts.parse_contracts import (
    SpatialPlanningIntent, ZoneTarget, FacilityTarget, AxisTarget,
)

# 1. 加载数据
catalog = DataCatalog()
bundle = catalog.load_village_bundle("金田村委会")

# 2. 计算三层空间关系
relations = compute_parcel_relations(
    bundle.polygons.landuse_current,
    roads=bundle.lines.roads_current,
)

# 3. 构建 PARSE 意图 (Layer 3)
intent = SpatialPlanningIntent(
    village_name="金田村委会",
    zone_targets=[
        ZoneTarget(land_use="2121", area_ratio=0.15),
    ],
    facilities=[
        FacilityTarget(type="展销中心", status="planned_new", service_radius=500),
    ],
    development_axes=[
        AxisTarget(direction="南北", reference_feature="村主干道"),
    ],
)

# 4. 构建 KG (Layer 1-4)
kg = PlanningKG("金田村委会")
kg.build_from_bundle(
    bundle=bundle,
    parcel_relations=relations,
    intent=intent,                    # → L3 虚拟实体
    planned_state=None,               # → L4 规划成果（可选）
)

# 5. 查询
parcel_count = kg.get_parcel_count()                      # 660
adjacent = kg.get_adjacent_parcels_with_length("BSM-001") # 邻接地块
nearby = kg.get_parcels_within_distance_of_entity(
    "http://village-planning.org/ontology#village_ann_刘村", 500)

# 6. SemanticMemoryStore 查询
from app.modules.kg.memory import get_semantic_memory
memory = get_semantic_memory()
entity_info = memory.get_entity_semantics("pln:ResidentialCluster/刘村")
relation_info = memory.get_relation_semantics("pln:ResidentialCluster/刘村",
                                               "pln:north_of",
                                               "pln:ResidentialCluster/八社村")

# 7. 编码推荐值查询
from app.modules.kg.queries.semantic import get_parcels_by_planning_zone
farmland_parcels = get_parcels_by_planning_zone(kg, "农田保护区")
# LLM 判断: 这些地块的 planning_zone 推荐值是否合理？
```

---

## 十、实际数据验证 (jintian)

### 10.1 KG 统计（使用 `data/gis/jintian/` 真实数据）

| 指标 | 值 |
|------|-----|
| 总三元组 | ~21,000 |
| 地块 (Parcel) | 660 |
| 道路 (Road) | 131 |
| 设施 (Facility) | 44 |
| 居民点落 (ResidentialCluster) | 19 |
| 水域 (WaterBody) | 44 |
| 分区 (Zone) | 139 |

### 10.2 三层空间关系

| 层 | 关系 | 三元组数 | 计算来源 |
|----|------|---------|---------|
| L1 | `pln:touches` | 1,549 | `compute_parcel_relations` (shapely `geom.touches()`) |
| L2 | `pln:nearby` | 4,195 | `compute_parcel_relations` (质心距离 ≤ 200m) |
| L3 | `pln:connected_via_road` | 207 | `compute_parcel_relations(parcels, roads=...)` (道路穿过) |

### 10.3 测试

```bash
cd backend
python -m pytest tests/integration/test_kg_jintian_e2e.py tests/unit/test_kg_no_reverse_deps.py -v
```

---

## 十一、变化记录

| 版本 | 变更 |
|------|------|
| v5.0 | **L4 几何字段** — `PlannedParcelEntry`/`PlannedZoneEntry` 新增 `geometry` WKT 字段，存入 `pln:geometry` 三元组 |
| v5.0 | **LLM 语义查询增强** — 新增 `get_entity_by_bsm()`/`get_parcels_by_planning_zone()`/`get_l4_derived_from_l1()`，`get_village_semantic_summary` 增加规划分区分布 |
| v4.7 | **EntityIdPolicy 统一标识契约** - 14 个 builder 统一 URI 方案，所有 L1/L4 实体存 `PLN.bsm` literal |
| v4.7 | **ThreeZone/ThreeLine 从 KG 移除** - 改为 `ConstraintIndex`（spatial_ops bridge）注入 |
| v4.7 | **L4->L3 链接实现** - `derived_from_target` 三元组写入，L4 实体可追溯至 L3 意图 |
| v4.7 | **get_adjacency_map 修复** - 从 URI 前缀解析改为 BSM literal 查询 |
| v4.7 | **约束验证修复** - `check_constraint_violations` 改用 `ConstraintIndex` 空间 overlay |
| v4.7 | **重复 BSM 处理** - `uri_with_seq` 序号后缀消歧 |
| v4.6 | **重构：只存空间实体** — 删除 `ControlRule`, `PlanningIndicator`, `Constraint`, `PlanIntent` 从 EntityTypes |
| v4.6 | **删除关系** — 8 个关系类型从 KG 移除 |
| v4.6 | **新增 SemanticMemoryStore** — 实体+关系注解 |
| v4.6 | **新增 L3 虚拟实体构建器** — Intent → 粗糙几何 + 空间关系 |
| v4.6 | **新增 L4 PlannedState** — 增量聚合视图，形态对齐 bundle |
| v4.6 | **变更 KG builder** — 从 bundle 形态分组直连，不再依赖 ContextBlock |
| v4.6 | **变更方法分配** — 从 monkey-patching → Mixin 类继承 |
