# Planning Knowledge Graph (KG) 模块

> **定位**: 村庄规划系统的**空间语义引擎** — 只存有几何的空间实体及其关系
> **层级**: `Schema ← Data ← SpatialOps ← KG ← Agent`
> **依赖**: 仅依赖 `app.modules.schema`；不依赖 Data/Agent/Tools
> **Updated: 2026-07-26 (v4.6)** — 重构：只存空间实体，删除非空间类型，SemanticMemoryStore，L3 虚拟实体，L4 PlannedState

---

## 一、核心原则

### 1.1 KG 只存"有几何的空间要素"

```
进 KG RDF 图:   Parcel, Road, WaterBody, Facility, Zone, ThreeLine, ...
不进 KG:        ControlRule, PlanningIndicator, Constraint (数值),
                PlanIntent (语义), LandUseCategory (编码体系)
```

非空间要素通过以下方式传递：

| 类型 | 去向 |
|------|------|
| `ControlRule` | `bundle.tables.control_rules` |
| `PlanningIndicator` | `bundle.tables.planning_indicators`（PARSE Agent 填充） |
| `Constraint` (数值约束) | `ContextBlock.CONSTRAINTS.data` |
| `PlanIntent` (语义容器) | `SpatialPlanningIntent` 对象本身 |
| `LandUseCategory` (VNE 编码) | Schema 层 `encodings/dicts/`，按需查询 |
| 编码体系 (DLBM/GHYTBM/TUGUI/...) | Schema 层 `encodings/code_sets.py`，按需查询 |

**编码体系管理原则**：KG 只在地块属性中存储编码值（`pln:dlbm`、`pln:vne_code`、`pln:planning_zone`），
不存储编码体系本身的分类树。分类树查询通过 Schema 层的 `encodings/` 模块按需返回，不走 KG RDF 图。

### 1.2 关系本身就是语义

KG 的 RDF 三元组不仅描述实体属性，更描述实体间的空间关系。**注解必须同时附着于实体和关系**，不能只存实体级注解：

```python
# 实体注解
EntityAnnotation(entity_uri, description, source_text_refs, intent_refs)

# 关系注解 — 之前缺失的部分
RelationAnnotation(subject_uri, predicate, object_uri,
                   description, derived_from, quantitative_detail)
```

### 1.3 Intent 以虚拟实体进 KG（L3 易失层）

ZoneTarget、FacilityTarget、RoadTarget 作为 L3 临时虚拟实体进入 KG，有粗糙几何表示，参与空间关系计算。EXECUTE 通过 SPARQL 查询这些虚拟实体与现状实体之间的空间关系（冲突检测、候选地块筛选）。

### 1.4 PlanBlock 是 Agent 记忆，不进 KG

PlanBlock 和 ContextBlock 对称——都是 Agent 的"工作记忆"，不直接进入 KG：

| 结构 | 本质 | 消费者 | 持久化 |
|------|------|--------|--------|
| **ContextBlock** | 现状空间认知卡片 | PARSE prompt | 不持久化 |
| **PlanBlock** | 增量变更操作记录 | 累积 → PlannedState | 可选会话日志 |
| **PlannedState** | 规划成果空间实体（聚合） | KG Layer 4 | 持久化 |

### 1.5 零 shapely/geopandas 依赖

所有几何计算由 `spatial_ops` 完成，KG 只消费结构化数据。

---

## 二、四层架构

| 层 | 内容 | 生命周期 | 写入者 | 消费者 |
|----|------|---------|--------|--------|
| Layer 1 | 现状空间实体 + 编码体系 | 持久（数据更新时重建） | Data Layer → bundle 直连 | SPARQL 查询、PARSE |
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
| `pln:Road` | `bundle.lines.roads_current` | `add_roads` | BSM in URI fragment ⚠️ |
| `pln:WaterBody` | `bundle.polygons.water_bodies` | `_add_water_bodies` | BSM in URI fragment ⚠️ |
| `pln:Facility` | `bundle.points.facilities_current` + annotations | `_add_facilities_from_typed` + `add_annotations` | name+count ❌ |
| `pln:NaturalSettlement` | `bundle.polygons.landuse_current` 聚类 + annotation | `_add_natural_villages_from_typed` | name（间接经 parcel BSM）⚠️ |
| `pln:Zone` | `bundle.polygons.land_use_zones` | `_add_planning_elements_from_typed` | code/count ❌ |
| `pln:ControlLine` | `bundle.polygons.hazard_control_lines`, `flood_control_lines` | `_add_control_lines_from_typed` | count only ❌ |
| `pln:ThreeZone` | `bundle.polygons.three_zones` **应读 bundle**（当前读 schema rule_loader） | `_add_three_zone_three_line` | schema dict ❌ |
| `pln:ThreeLine` | 同上 | `_add_three_zone_three_line` | schema dict ❌ |

> **标识键列说明**：✅ = 存储 `PLN.bsm` literal，可 SPARQL 查询；⚠️ = BSM 仅在 URI fragment，不可查询；❌ = 无稳定标识，见 §2.7 标识契约问题。

**注**：编码体系（DLBM、VNE、GHYTBM、TUGUI 等）不作为 KG 实体存储。地块的编码值
（`pln:dlbm`、`pln:vne_code`、`pln:planning_zone`）作为属性写入地块实体，
编码分类树通过 Schema 层 `encodings/` 模块按需查询。`_add_vne_categories` 方法已废弃。

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
# spatial_ops 计算这些虚拟实体与 L1 实体的空间关系
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

> **[v4.7] 已实现：统一 URI 方案 + BSM literal 绑定。**

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
| L1 | NaturalSettlement | `EntityIdPolicy.fallback_uri("village_ann", name, seq)` | ⚠️ 按名 | ⚠️ |
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

[v4.7] ThreeZone/ThreeLine 从 KG 实体中移除。它们是引用层（上级审批成果，不可修改），
不是规划对象。约束多边形（farmland_protection / ecological_redline / historical_protection）
通过 `spatial_ops.bridge.ConstraintIndex` 访问，在 `build_from_bundle` 时注入。

#### 重复 BSM 处理

实际数据中 BSM 可能不唯一（多部件图斑按地类拆分后共享 BSM）。
`EntityIdPolicy.uri_with_seq` 通过序号后缀消歧：`parcel_{bsm}_0`, `parcel_{bsm}_1`, ...
所有同 BSM 的子图斑共享 `PLN.bsm` literal，SPARQL 查询返回多条结果。

#### 约束验证

`check_constraint_violations` 和 `_is_in_protected_zone` 不再查询 KG 中空的 `within_zone` 关系，
改为通过注入的 `ConstraintIndex`（spatial_ops bridge）做空间 overlay 查询：

```python
kg.build_from_bundle(bundle, constraint_index=build_constraint_index(bundle))
violations = kg.check_constraint_violations("v1")  # 实际检测约束多边形重叠
```

---

## 三、实体类型

### 3.1 现状实体（Layer 1）

| 形态 | 实体 | 说明 |
|------|------|------|
| 面 | `Parcel` | 现状地类图斑 |
| 面 | `WaterBody` | 水域 |
| 面 | `Zone` | 规划分区 |
| ~~面~~ | ~~`ThreeZone`~~ | ~~三区~~ [v4.7] 移除，改为 ConstraintIndex |
| ~~面~~ | ~~`ThreeLine`~~ | ~~三线~~ [v4.7] 移除，改为 ConstraintIndex |
| 面 | `AdministrativeVillage` | 行政村 |
| 面 | `NaturalSettlement` | 自然村 |
| 点 | `Facility` | 现状设施点 |
| 线 | `Road` | 现状道路 |

**注**：编码体系（DLBM、VNE、GHYTBM、TUGUI 等）不作为 KG 实体存储。
地块的编码值（`pln:dlbm`、`pln:vne_code`、`pln:planning_zone`）作为属性写入地块实体，
编码分类树通过 Schema 层 `encodings/` 模块按需查询。

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
| `located_in` | 单向 | — | 位于（行政村→自然村→地块） |
| `delineates` | 单向 | — | 划定（三区三线划定分区） |

### 4.2 规划语义关系

| 关系 | 方向 | 说明 |
|------|------|------|
| `designated_as` | 单向 | 地块被指定为某分区 |
| `derived_from` | 单向 | 规划地块源于现状地块 |
| `serves` | 单向 | 设施服务于某区域 |

### 4.3 已删除的关系（不再属于 KG）

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
  "entity": {"uri": "pln:NaturalSettlement/刘村", "parcel_count": 45},
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

## 六、数据流

```
┌───────────┐     ┌──────────────┐     ┌─────────────────┐
│ Data Layer│────→│ Spatial Ops  │────→│ ContextBlock[] │ → PARSE prompt (agent 记忆)
│ (Bundle)  │     │ (关系计算)   │     │ (不持久化)      │
└───────────┘     └──────┬───────┘     └─────────────────┘
        │                │
        ▼                ▼
┌───────────┐
│ KG Builder│ ← 直接从 bundle 形态分组 + parcel_relations 构建 Layer 1-2
│           │ ← intent → Layer 3 虚拟实体（易失）
│           │ ← planned_state → Layer 4 规划成果（版本化）
└───────────┘
        ▲
        │
┌───────────┐     ┌──────────────┐     ┌─────────────────┐
│ PARSE     │────→│ EXECUTE      │────→│ PlanBlock[]     │ → 累积 → PlannedState
│ (产出     │     │ (求解)       │     │ (agent 记忆)    │              │
│  Intent)  │     │              │     └─────────────────┘              │
└───────────┘     └──────────────┘                        ┌─────────────▼──┐
                                                            │ KG Layer 4    │
                                                            │ (持久化)       │
                                                            └────────────────┘
```

**关键分离**：

- **ContextBlock** 和 **PlanBlock** 都是 Agent 的临时"工作记忆"，不进入 KG
- **KG** 只存储有几何的空间实体（现状 L1、意图虚拟实体 L3、规划成果 L4）
- **bundle.tables** 存储非空间数据（ControlRule、PlanningIndicator）

---

## 七、模块结构

```
backend/app/modules/kg/
├── __init__.py               # 公开 API 导出
├── README.md                 # 本文档
├── ontology.py               # 本体定义: 实体类型 + 关系类型
├── manager.py                # KGManager: 缓存 + 会话管理
├── memory.py                 # [v4.6] SemanticMemoryStore: 实体+关系注解
├── builder/                  # 四层构建器子包
│   ├── __init__.py           # 导出 PlanningKG, KGInputParcels, Mixin 类
│   ├── base.py               # PlanningKG 骨架: __init__ + build_from_bundle
│   │                          # + clone_static_layer + print_summary
│   ├── layer1.py             # Layer 1: 现状实体（从 bundle 形态分组直连）
│   ├── layer2.py             # Layer 2: 空间关系（从 parcel_relations 注入）
│   ├── layer3.py             # Layer 3: 意图虚拟实体（intent → 粗糙几何）
│   ├── layer4.py             # Layer 4: 规划成果（PlannedState → 版本化增量）
│   ├── queries.py            # 语义查询接口
│   └── mixins.py             # [v4.6] Mixin 类（替代 monkey-patching）
└── queries/
    ├── __init__.py            # 导出 SPARQL 模板 + SemanticMemoryStore 查询
    └── tools.py               # SPARQL 模板注册表 (30+ 模板，参数化查询)
```

### 7.1 方法分配机制

每个 layer 文件定义模块级函数，通过 `mixins.py` 中的 Mixin 类继承到 `PlanningKG`：

```python
class PlanningKG(Layer1Mixin, Layer2Mixin, Layer3Mixin, Layer4Mixin, QueryMixin):
    ...
```

### 7.2 各层方法清单

| 文件 | 方法 | 职责 |
|------|------|------|
| `layer1.py` | `_add_village_entity`, `_add_parcels_typed`, `_add_infrastructure_from_typed`, `add_roads`, `_add_control_lines_from_typed`, `_add_planning_elements_from_typed`, `_add_natural_features_from_typed`, `_add_designated_as_from_typed`, `_add_vne_categories`, `_add_three_zone_three_line`, `add_annotations`, `add_terrain` | 现状实体构建 |
| `layer2.py` | `_add_parcel_relations` | 空间关系注入 |
| `layer3.py` | `build_intent_layer`, `clear_intent_layer` | 意图虚拟实体 |
| `layer4.py` | `_apply_planned_state`, `get_effective_land_use`, `get_effective_area_ha`, `get_plan_changes`, `check_constraint_violations`, `compare_versions` | 规划成果 |
| `queries.py` | `query`, `get_adjacency_map`, `get_parcel_count`, `get_triple_count`, `serialize`, `to_turtle`, `from_turtle`, `get_parcels_within_distance_of_entity`, `get_adjacent_parcels_with_length`, `get_connected_parcels`, `get_parcels_by_bsm_list` | 语义查询 |

---

## 八、端到端示例

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
entity_info = memory.get_entity_semantics("pln:NaturalSettlement/刘村")
relation_info = memory.get_relation_semantics("pln:NaturalSettlement/刘村",
                                               "pln:north_of",
                                               "pln:NaturalSettlement/八社村")
```

---

## 九、实际数据验证 (jintian)

### 9.1 KG 统计（使用 `data/gis/jintian/` 真实数据）

| 指标 | 值 |
|------|-----|
| 总三元组 | ~21,000 |
| 地块 (Parcel) | 660 |
| 道路 (Road) | 131 |
| 设施 (Facility) | 44 |
| 自然村落 (NaturalSettlement) | 19 |
| 水域 (WaterBody) | 44 |
| 分区 (Zone) | 139 |
| 三区 (ThreeZone) | 3 |
| 三线 (ThreeLine) | 6 |

### 9.2 三层空间关系

| 层 | 关系 | 三元组数 | 计算来源 |
|----|------|---------|---------|
| L1 | `pln:touches` | 1,549 | `compute_parcel_relations` (shapely `geom.touches()`) |
| L2 | `pln:nearby` | 4,195 | `compute_parcel_relations` (质心距离 ≤ 200m) |
| L3 | `pln:connected_via_road` | 207 | `compute_parcel_relations(parcels, roads=...)` (道路穿过) |

### 9.3 测试

```bash
cd backend
python -m pytest tests/integration/test_kg_jintian_e2e.py tests/unit/test_kg_no_reverse_deps.py -v
```

---

## 十、与设计文档的差异

| 文档 | 需要更新 |
|------|---------|
| `docs/gis/00_SYSTEM_DESIGN.md` | 整体架构图、四层定义、数据流、删除 ConstraintCompiler 引用 |
| `docs/gis/reference/OPTIMIZATION_TASKS.md` | 删除 ConstraintCompiler 任务 |

---

## 十一、变化记录

| 版本 | 变更 |
|------|------|
| v4.7 | **EntityIdPolicy 统一标识契约** - 14 个 builder 统一 URI 方案，所有 L1/L4 实体存 `PLN.bsm` literal |
| v4.7 | **ThreeZone/ThreeLine 从 KG 移除** - 改为 `ConstraintIndex`（spatial_ops bridge）注入，约束多边形不再作为 KG 实体 |
| v4.7 | **L4->L3 链接实现** - `derived_from_target` 三元组写入，L4 实体可追溯至 L3 意图 |
| v4.7 | **get_adjacency_map 修复** - 从 URI 前缀解析改为 BSM literal 查询，返回纯 BSM |
| v4.7 | **约束验证修复** - `check_constraint_violations` / `_is_in_protected_zone` 改用 `ConstraintIndex` 空间 overlay |
| v4.7 | **重复 BSM 处理** - `uri_with_seq` 序号后缀消歧，处理多部件图斑共享 BSM 的数据质量问题 |
| v4.6.1 | **文档修正** - §2.3 方法名表更新（删除 `_add_parcels_typed`/`_add_infrastructure_from_typed`/`_add_constraints_from_typed` 等已废弃方法名） |
| v4.6.1 | **新增 §2.7 实体标识与 bundle 锚定契约** - 文档化 URI 方案碎片化、ThreeZone 脱离 bundle、L4->L3 链接未实现等已知缺口 |
| v4.6 | **重构：只存空间实体** — 删除 `ControlRule`, `PlanningIndicator`, `Constraint`, `PlanIntent` 从 EntityTypes |
| v4.6 | **删除关系** — `constrained_by`, `achieves`, `conflicts_with`, `conducted_from`, `controls_use`, `protects`, `adjacent_to`, `location_constraint` |
| v4.6 | **删除死代码** — `queries/llm.py` 整个文件, `_semantic_store` 字段 |
| v4.6 | **新增 SemanticMemoryStore** — 实体+关系注解，SQLite/JSON 持久化 |
| v4.6 | **新增 L3 虚拟实体构建器** — Intent → 粗糙几何 + 空间关系 |
| v4.6 | **新增 L4 PlannedState** — 增量聚合视图，形态对齐 bundle |
| v4.6 | **变更 KG builder** — 从 bundle 形态分组直连，不再依赖 ContextBlock |
| v4.6 | **变更方法分配** — 从 monkey-patching → Mixin 类继承 |
| v4.6 | **SPARQL 参数化** — `initBindings` 替代 `str.replace`，消除注入风险 |
| v4.6 | **缓存键确定性** — `hashlib.md5` 替代 `hash(frozenset(...))` |
| v4.5 | 统一 Intent 类型，本体清理，删除 6 个未用实体类型 |
| v4.4 | 引入 SpatialCognitiveUnit 形态层级，四层架构，PlanBlock 增量变更集 |