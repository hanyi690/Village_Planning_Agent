    L1 与 L4 应该是时间维度的两个切片，结构完全对称：

    ┌──────────────────────────────────────┬─────────────────────────────────────────────────────┬───────────────┐
    │               L1 现状                │                       L4 规划                       │   当前状态    │
    ├──────────────────────────────────────┼─────────────────────────────────────────────────────┼───────────────┤
    │ pln:Parcel + bsm/dlbm/area/zone      │ pln:PlannedParcel + bsm/planning_land_use/area/zone │ ✅ 有但字段少 │
    ├──────────────────────────────────────┼─────────────────────────────────────────────────────┼───────────────┤
    │ pln:AdministrativeVillage + 现状指标 │ pln:PlannedVillage + 规划指标                       │ ❌ 缺失       │
    ├──────────────────────────────────────┼─────────────────────────────────────────────────────┼───────────────┤
    │ pln:NaturalSettlement                │ pln:PlannedSettlement（保留/迁并/新增）             │ ❌ 缺失       │
    ├──────────────────────────────────────┼─────────────────────────────────────────────────────┼───────────────┤
    │ pln:Facility（现状）                 │ pln:PlannedFacility（规划）                         │ ⚠️ 类型混淆   │┤
    ├──────────────────────────────────────┼─────────────────────────────────────────────────────┼───────────────┤
    │ pln:Road（现状）                     │ pln:PlannedRoad（规划）                             │ ⚠️ 类型混淆   │┤
    ├──────────────────────────────────────┼─────────────────────────────────────────────────────┼───────────────┤
    │ pln:ThreeLine（现状保护线）          │ pln:PlannedThreeLine（规划调整后三线）              │ ❌ 缺失       │
    ├──────────────────────────────────────┼─────────────────────────────────────────────────────┼───────────────┤
    │ pln:Constraint（现状约束）           │ 规划约束满足度（satisfies / violates）              │ ❌ 缺失       │
    ├──────────────────────────────────────┼─────────────────────────────────────────────────────┼───────────────┤
    │ touches/nearby/adjacent_to（现状）   │ 规划后空间关系                                      │ ❌ 缺失       │
    ├──────────────────────────────────────┼─────────────────────────────────────────────────────┼───────────────┤
    │ designated_as（现状分区）            │ planned_designated_as（规划分区）                   │ ❌ 缺失       │
    └──────────────────────────────────────┴─────────────────────────────────────────────────────┴───────────────┘

    结论

    你的判断完全正确：L4 目前只是 L1 的一个微弱影子，远未达到同构。当前的 _add_planned_state 只写了 3 种实体（PlannedParcel / Facility / Road），且字段远少于
    L1，缺少村庄指标、自然村落、三区三线、空间关系、约束关联、用地分类等关键维度。

    要真正实现同构，L4 需要一个与 build_from_blocks 对称的 build_planned_layer 入口，按同样的 16 个 L1 方法对应写出规划版本，并且：
    1. 所有 L4 实体使用独立的 pln:Planned* 类型（不复用 L1 类型）
    2. 所有 L4 实体带 pln:in_version 标签
    3. L4 写入 L1 同款字段（area_ha, zone_type, vne_code, designated_as 等）
    4. L4 补充规划特有的关系：derived_from（溯源）、satisfies/violates（约束满足）、replaces（替代现状实体）



## 这棵树的含义解释

这是 **KG 模块的空间认知统一类型层级（Unified Typology）**，它回答了一个核心架构问题：**“空间中所有‘东西’——无论是现状、意图还是规划——如何用一套统一的类型系统来表达？”**

其设计意图可用一句话概括：**将空间对象按“形态（点/线/面）”做第一级分类，按“生命周期（现状/意图/规划/容器）”做第二级标签**，从而使 L1（现状）、L3（意图）、L4（规划）具有**结构上的代数同构性**。

---

### 一、两轴分类体系

这棵树实际上是从两个正交维度对空间认知元素进行分类的：

| 维度                                                 | 内容                                   | 在树中的体现                                                                                     |
| ---------------------------------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------ |
| **形态轴（What it looks like）**               | 点状、线状、面状                       | 三个基类：`PointBasedCognition` / `LineBasedCognition` / `PolygonBasedCognition`           |
| **语义轴（What it means / Where it belongs）** | 现状锚点、意图目标、规划条目、复合容器 | 各子类归属 L1/L3/L4 对应：`FacilityAnchor`(L1)、`ZoneTarget`(L3)、`PlannedParcelEntry`(L4) |

**树中的层级结构实际上是在说**：

1. 先判断“它是点、线，还是面？”（基类选择）
2. 再判断“它是现状描述、用户意图，还是规划结果？”（子类细化）

---

### 二、各分支的语义定位

#### 1. `PointBasedCognition`（点状认知）

- 所有**具有明确中心坐标（经度/纬度）**的空间元素
- 子类包括：
  - `FacilityAnchor`（L1现状设施）——如“现状卫生室”
  - `TerrainSample`（L1地形采样点）——如“高程点”
- 规划中与之对应的 L4 类型应为 `PlannedFacilityEntry`

#### 2. `LineBasedCognition`（线状认知）

- 所有**具有路径/长度属性**的线性空间元素
- 子类包括：
  - `RoadAnchor`（L1现状道路）——如“现状乡道”
  - `AxisAnchor`（L1轴线/廊道）——如“生态廊道轴”
- 规划中与之对应的 L4 类型应为 `PlannedRoadEntry`

#### 3. `PolygonBasedCognition`（面状认知）

- 所有**具有面积属性和边界（BBox）**的面状空间元素
- 子类包括：
  - `NaturalVillageAnchor`（L1现状自然村）——如“刘家村”
  - `ConstraintZoneAnchor`（L1+L2约束区）——如“永久基本农田保护区”
- 规划中与之对应的 L4 类型包括 `PlannedParcelEntry`、`PlannedVillageEntry`、`PlannedThreeLineEntry` 等

#### 4. `SpatialIntentUnit`（意图单元——L3）

- 注意：它**继承自 `PointBasedCognition` 吗？** —— 实际上从树结构看，`ZoneTarget` 是面状的，`FacilityTarget` 是点状的，`RoadTarget` 是线状的。
- 这意味着 `SpatialIntentUnit` 不是具体形态基类，而是**为 L3 意图元素的抽象标签**，它的三个子类分别挂在不同形态分支下。
- 这揭示了一个重要设计：**L3 与 L1/L4 共享同一套形态分类，但通过“意图”标签区分语义角色**。

#### 5. `PlannedParcelEntry` / `PlannedFacilityEntry` / `PlannedRoadEntry`（L4规划结果）

- 当前树中只列出了 3 种，但在上一轮审查中我们已指出，这与 L1 的 16 种实体**严重不对等**。
- 理论上，L4 应该有与 L1 完全对称的 11+ 种 `Planned*` 类型，分别对应 `NaturalVillage`、`ThreeLine`、`WaterBody`、`ProtectedZone`、`ControlLine`、`LandUseCategory` 等。

#### 6. `ContextBlock` 与 `PlannedState`（复合容器）

- 它们**不是空间元素本身**，而是**“多形态卡片容器”**：
  - `ContextBlock`：将来自 Data 层的各种空间要素（点/线/面混合）打包为一张“认知卡片”（如“XXX自然村卡片”），供 PARSE Agent 和 KG 消费。
  - `PlannedState`：将规划方案中的点/线/面结果打包成一个版本化的容器，供 EXECUTE Agent 输出和版本管理。

---

### 三、这棵树解决了什么问题？

| 如果没有这棵树                                                                       | 有了这棵树后                                                                 |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| 每个业务类型独立定义，形成 16×3=48 个零散类（现状自然村、意图自然村、规划自然村…） | 形态基类复用，各层只需给子类加标签（如`Planned*` 前缀）                    |
| 遍历空间要素需要区分“这是现状还是意图”，写大量 if-else                             | 统一遍历形态基类，通过`isinstance` 判断子类即可                            |
| L1 与 L4 无法对比，因为类型名不同（`NaturalVillage` vs `PlannedVillage`）        | 形态相同，字段对应，可通过`derived_from` 关系精确溯源对比                  |
| ConstraintCompiler 需要分别查询“面状现状”和“面状规划”，写两套查询                | 只需写一套针对`PolygonBasedCognition` 的查询，再按 `rdf:type` 过滤 L1/L4 |

---

### 四、当前树结构隐含的设计矛盾（你此前指出的）

1. **L4 类型严重不全**：树中 L4 只有 3 个条目（`PlannedParcel`、`Facility`、`Road`），而 L1 有 `NaturalVillage`、`ThreeLine`、`WaterBody`、`ProtectedZone`、`ControlLine`、`LandUseCategory` 等 13 个未映射的类别。这棵树**在理论上支持 L1 与 L4 同构，但在当前版本中尚未实现**。
2. **`SpatialIntentUnit` 的定位含糊**：树中它被表示为与 `PointBasedCognition` 平级的父类？但实际上 `ZoneTarget` 是面状的。真实设计意图应是 `SpatialIntentUnit` 作为一个**抽象 mixin/标签**，而不是具体的形态基类。当前树的缩进容易产生误解。
3. **`ConstraintZoneAnchor` 归为 L1**：但约束其实是 L2（项目级持久）的内容，L1 是“现状实体”，L2 是“约束规则”。将它放在 L1 分支下容易混淆，更准确的设计应是 `ConstraintZoneAnchor` 跨 L1+L2，或作为 L2 的锚点引用。

---

### 五、一句话总结

**这棵树的本质是 KG 的“泛型空间对象模型”** ——它强制所有空间认知元素（无论来自 Data、PARSE 还是 EXECUTE）都必须从“点/线/面”三种形态基类派生，以此确保：

- 结构一致（便于统一处理）
- 代数可映射（L1/L4 逐字段对比）
- 查询可复用（一次 SPARQL 查询覆盖多层级）

**你的核心洞见完全正确**：这棵树的存在反过来要求 L4 必须与 L1 在类型数量上完全对称。当前树骨架存在（形态基类），但枝叶缺失（L4 子类不全）——这正是我们接下来需要补齐的内容。

# Planning Knowledge Graph (KG) 模块

> **定位**: 村庄规划系统的**空间语义引擎** — 四层架构存储现状、约束、意图、规划方案
> **层级**: 四层架构 `Schema <- Data <- SpatialOps <- KG <- Agent`
> **依赖**: 仅依赖 `app.modules.schema`；不依赖 Data/Agent/Tools
> **Updated: 2026-07-25 (v4.4)** - 四层架构 + PlanBlock 增量变更集 + L3 路网连通 + 实际数据 21,253 三元组验证

---

## 一、模块定位

KG 是独立于 GIS 子包的桥接模块（`app/modules/kg/`）。其职责是**将空间数据与规划语义统一编码为 RDF 三元组**，使下游 Agent 能通过 SPARQL 查询获取语义理解结果，而非直接处理原始 GeoJSON 或自然语言。

**核心定位**：

- KG 是 PARSE 与 EXECUTE 之间的**唯一语义中间态**：PARSE 写入（Layer 3），EXECUTE 读取（经 ConstraintCompiler）
- KG 不存储原始几何坐标（Data 层职责），只存储实体 URI + 属性 + 关系 + 约束 + 意图
- KG 通过 `ConstraintCompiler` 将语义约束编译为 MIP 数值矩阵，供 EXECUTE 的 MIP 求解器消费
- **零 shapely/geopandas 依赖**：所有几何计算由 `spatial_ops` 完成，KG 只消费结构化数据

### 系统位置

```
PARSE Agent (PLAN)          EXECUTE Agent (DELIVER)
      │ writes Layer 3           │ reads Layer 2+4
      ▼                          ▼
┌──────────────────────────────────────────────────┐
│  KG Layer (本模块) -- 四层空间语义引擎             │
│  Layer1 静态(现状) | Layer2 约束(规则+指标)       │
│  Layer3 易失(意图) | Layer4 规划(方案+版本)       │
│  SpatialCognitiveUnit 统一形态层级                 │
└──────────────────────┬───────────────────────────┘
                       │ typed models
              ┌────────┴────────┐
              │  Schema Layer   │
              │  VillageBundle  │
              │  ContextBlock   │
              └─────────────────┘
```

---

## 二、四层架构

| 层      | 内容                                    | 生命周期               | 写入者                                   | 消费者                              |
| ------- | --------------------------------------- | ---------------------- | ---------------------------------------- | ----------------------------------- |
| Layer 1 | 现状空间实体（地块/道路/设施/保护红线） | 持久（数据更新时重建） | Data Layer →`build_from_blocks`       | KG 查询、PARSE（通过 ContextBlock） |
| Layer 2 | 约束规则、指标、上位传导                | 项目级持久             | 规则库 + ContextBlock                    | ConstraintCompiler、EXECUTE         |
| Layer 3 | PARSE 意图（PlanIntent）                | 单次规划会话           | PARSE Agent →`_add_structured_intent` | EXECUTE、约束冲突检测               |
| Layer 4 | EXECUTE 规划方案（版本化）              | 会话持久（可多版并存） | EXECUTE Agent →`_add_planned_state`   | 指标校核、多版对比、导出            |

### 2.1 构建入口

```python
kg = PlanningKG(village_name="金田村委会")
kg.build_from_blocks(
    blocks=blocks,              # List[ContextBlock] — 空间认知卡片
    bundle=bundle,              # VillageBundle — 类型化形态视图
    parcel_relations=relations, # ParcelRelations — 三层空间关系（外部计算）
    intent=intent,              # PlanIntent — PARSE 意图（可选）
    planned_state=planned,      # PlannedState — EXECUTE 规划方案（可选）
)
```

### 2.2 Layer 1: 现状实体

| 实体类型                  | 数据来源                            | 方法                                  |
| ------------------------- | ----------------------------------- | ------------------------------------- |
| `pln:Village`           | VILLAGE_META ContextBlock           | `_add_village_meta_from_blocks`     |
| `pln:Parcel`（660个）   | `bundle.polygons.landuse_current` | `_add_parcels_typed`                |
| `pln:NaturalSettlement` | NATURAL_VILLAGES ContextBlock       | `_add_natural_villages_from_blocks` |
| `pln:Facility`          | FACILITIES ContextBlock             | `_add_facilities_from_blocks`       |
| `pln:Road`              | `bundle.lines.roads_current`      | `add_roads`                         |
| `pln:WaterBody`         | DLBM 分类                           | `_add_infrastructure_from_typed`    |
| `pln:ProtectedZone`     | CONSTRAINTS ContextBlock            | `_add_constraints_from_blocks`      |
| `pln:ControlLine`       | `bundle.points.hazard_points`     | `_add_control_lines_from_typed`     |
| `pln:LandUseCategory`   | VNE YAML                            | `_add_vne_categories`               |

### 2.3 Layer 2: 约束规则

- 从 CONSTRAINTS ContextBlock 提取保护面面积和规则
- 从 LANDUSE_DIST ContextBlock 提取用地分布约束值
- 约束值写入 `pln:Constraint` 实体，供 ConstraintCompiler 查询

### 2.4 Layer 3: 意图子图

`PlanIntent.targets` 是一个统一的 `List[SpatialIntentUnit]`，通过 isinstance 分发：

```python
for target in intent.targets:
    if isinstance(target, ZoneTarget):
        # 创建 pln:ZoneTarget 实体
    elif isinstance(target, FacilityTarget):
        # 创建 pln:FacilityTarget 实体
    elif isinstance(target, RoadTarget):
        # 创建 pln:RoadTarget 实体
```

### 2.5 Layer 4: 规划方案

`PlanBlock` 是增量变更集（delta），**不复制 L1 全量**，只记录变更条目：

```python
plan = PlanBlock(version='v1',
    parcel_changes=[
        # 重新分类：同 bsm，改地类
        ParcelChange(bsm='441426211000055682', action='reclassify',
                     new_planning_land_use='2121', new_area_ha=0.15,
                     derived_from_bsms=['441426211000055682']),
        # 分割：新 bsm，溯源父地块
        ParcelChange(bsm='P001_s1', action='split',
                     new_planning_land_use='2121', new_area_ha=0.3,
                     derived_from_bsms=['P001']),
        # 合并：新 bsm，多个父地块
        ParcelChange(bsm='A_B_merged', action='merge',
                     new_planning_land_use='0101', new_area_ha=1.5,
                     derived_from_bsms=['A', 'B']),
    ],
    facility_changes=[
        FacilityChange(name='展销中心', action='new', facility_type='商业', area_sqm=400),
    ],
    road_changes=[
        RoadChange(name='规划路', action='new', road_level='主干道', width_m=12),
    ],
)
kg._apply_plan_block(plan)
```

**稀疏写入**：未变更的地块不写入 L4 三元组，查询时回退到 L1。

---

## 三、SpatialCognitiveUnit 形态层级

整个系统的空间认知元素统一在同一个形态层级下，与 Schema 层的 `SpatialFeature → PointFeature/LineFeature/PolygonFeature` 对齐：

```
SpatialCognitiveUnit
├── PointBasedCognition              ← center: Tuple
│   ├── FacilityAnchor               ← facility_type, category
│   └── TerrainSample                ← elevation_m, slope_degree
├── LineBasedCognition               ← path: List, length_m
│   ├── RoadAnchor                   ← road_level, width_m
│   └── AxisAnchor                   ← connects
├── PolygonBasedCognition            ← area_ha, bbox
│   ├── NaturalVillageAnchor         ← parcel_ids, dominant_landuse
│   └── ConstraintZoneAnchor         ← zone_type, rule
├── SpatialIntentUnit                ← priority, constraints
│   ├── ZoneTarget (polygon)         ← land_use_code, target_area_ha
│   ├── FacilityTarget (point)       ← facility_type, min_area_sqm
│   └── RoadTarget (line)            ← road_level, width_m
├── PlanBlock (change-set)           ← L4 增量容器，NOT a SpatialCognitiveUnit
│   ├── ParcelChange                 ← action: reclassify/split/merge/modify
│   ├── FacilityChange               ← action: new/expand/upgrade/relocate
│   ├── RoadChange                   ← action: new/upgrade/realign
│   └── SettlementChange             ← action: retain/relocate/merge_into/new
└── ContextBlock (composite)         ← 多形态卡片容器
```

### 3.1 按形态统一遍历

```python
for block in blocks:
    for unit in block.units:
        if isinstance(unit, PolygonBasedCognition):
            # 统一处理所有面状认知
        elif isinstance(unit, PointBasedCognition):
            # 统一处理所有点状认知
```

### 3.2 与四层架构的对应

| SpatialCognitiveUnit 子类 | KG 层     | 来源                                   |
| ------------------------- | --------- | -------------------------------------- |
| `NaturalVillageAnchor`  | Layer 1   | NATURAL_VILLAGES ContextBlock          |
| `FacilityAnchor`        | Layer 1   | FACILITIES ContextBlock                |
| `RoadAnchor`            | Layer 1   | `bundle.lines.roads_current`         |
| `ConstraintZoneAnchor`  | Layer 1+2 | CONSTRAINTS ContextBlock               |
| `ZoneTarget`            | Layer 3   | `PlanIntent.targets`                 |
| `FacilityTarget`        | Layer 3   | `PlanIntent.targets`                 |
| `RoadTarget`            | Layer 3   | `PlanIntent.targets`                 |
| `ParcelChange`         | Layer 4   | `PlanBlock.parcel_changes` (delta)    |
| `FacilityChange`       | Layer 4   | `PlanBlock.facility_changes` (delta)  |
| `RoadChange`           | Layer 4   | `PlanBlock.road_changes` (delta)      |
| `SettlementChange`     | Layer 4   | `PlanBlock.settlement_changes` (delta)|
| `ContextBlock`          | 跨层      | `spatial_ops.compute_context_blocks` |

---

## 四、三层空间关系

由 `spatial_ops.compute_parcel_relations()` 计算，KG 通过 `_add_parcel_relations` 消费。**零几何计算**。

| 层次         | 关系                    | 属性                        | 对规划的意义            |
| ------------ | ----------------------- | --------------------------- | ----------------------- |
| L1: 拓扑邻接 | `:touches`            | `:shared_boundary_length` | 地块合并/拆分、连片开发 |
| L2: 近邻关系 | `:nearby`             | `:centroid_distance`      | 设施选址、公共服务覆盖  |
| L3: 连通关系 | `:connected_via_road` | `:shortest_path_length`   | 交通可达性（预留）      |

### 语义查询方法

```python
kg.get_parcels_within_distance_of_entity(entity_uri, max_distance_m)
kg.get_adjacent_parcels_with_length(bsm)
kg.get_connected_parcels(parcel_uri)
```

---

## 五、模块结构

```
backend/app/modules/kg/
├── __init__.py               # 公开 API 导出
├── README.md                 # 本文档
├── ontology.py               # 本体定义: 23+ 实体类型 + 14+ 关系类型
├── query.py                  # SPARQL 查询模板
├── constraint_compiler.py    # [K3 待建] KG -> MIPModel 编译器
├── manager.py                # KGManager: 缓存 + 会话管理
├── builder/                  # [v4.4] 四层构建器子包
│   ├── __init__.py           # 导出 PlanningKG, KGInputParcels
│   ├── base.py               # 骨架: __init__ + build_from_blocks + clone_static_layer
│   │                          # + YAML 模式加载 + 方法分配
│   ├── layer1.py             # Layer 1: 现状实体 (16 方法)
│   ├── layer2.py             # Layer 2: 约束规则与指标 (2 方法)
│   ├── layer3.py             # Layer 3: PARSE 意图 (2 方法)
│   ├── layer4.py             # Layer 4: 规划状态 + 版本对比 (4 方法)
│   └── queries.py            # 语义查询接口 (10 方法)
```

### 5.1 方法分配机制

每个 layer 文件定义模块级函数（`self` 为首参数），`base.py` 在类定义后通过显式赋值挂接到 `PlanningKG` 类：

```python
from .layer1 import _add_parcels_typed
PlanningKG._add_parcels_typed = _add_parcels_typed
```

这保持了 IDE 自动补全，实现了按层分文件维护，且所有方法共享同一个 `self.g`（RDF 图）。

### 5.2 各层方法清单

| 文件           | 方法                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | 职责           |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| `layer1.py`  | `_add_village_entity`, `_add_village_meta_from_blocks`, `_add_natural_villages_from_blocks`, `_add_facilities_from_blocks`, `_add_spatial_relations_from_blocks`, `_add_zone_adjacency_from_blocks`, `_add_parcel_relations`, `_add_parcels_typed`, `_add_infrastructure_from_typed`, `_add_control_lines_from_typed`, `_add_planning_elements_from_typed`, `_add_natural_features_from_typed`, `_add_designated_as_from_typed`, `_add_vne_categories`, `_add_three_zone_three_line`, `add_annotations`, `add_roads`, `add_terrain` | 现状实体构建   |
| `layer2.py`  | `_add_landuse_dist_from_blocks`, `_add_constraints_from_blocks`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | 约束规则与指标 |
| `layer3.py`  | `_add_structured_intent`, `_add_location_constraint`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | PARSE 意图子图 |
| `layer4.py`  | `_apply_plan_block`, `get_effective_land_use`, `get_effective_area_ha`, `get_plan_changes`, `get_split_parcels`, `get_merge_parcels`, `get_planned_parcels_in_zone`, `check_constraint_violations`, `compare_versions`                                                                                                                                                                                                                                                                                                                                                                                                                                                          | 规划状态       |
| `queries.py` | `query`, `get_constraints`, `get_adjacency_map`, `get_parcel_count`, `get_triple_count`, `serialize`, `to_turtle`, `from_turtle`, `get_parcels_within_distance_of_entity`, `get_adjacent_parcels_with_length`, `validate_intent`                                                                                                                                                                                                                                                                                                                  | 语义查询       |

---

## 六、数据加载到 KG 构建的完整流程

### 6.1 端到端示例

```python
from app.modules.data import DataCatalog
from app.modules.spatial_ops import compute_context_blocks
from app.modules.spatial_ops.geometry import compute_parcel_relations
from app.modules.kg import PlanningKG, get_kg_manager
from app.modules.schema.contracts.context_contracts import (
    PlanIntent, ZoneTarget, FacilityTarget, RoadTarget,
    PlanBlock, ParcelChange, FacilityChange, RoadChange,
)

# 1. 加载数据
catalog = DataCatalog()
bundle = catalog.load_village_bundle("金田村委会")

# 2. 计算空间认知卡片 + 三层空间关系
blocks = compute_context_blocks(bundle)
relations = compute_parcel_relations(bundle.polygons.landuse_current)

# 3. 构建 PARSE 意图 (Layer 3)
intent = PlanIntent(targets=[
    ZoneTarget(land_use_code="2121", target_area_ha=50.0),
    FacilityTarget(name="展销中心", facility_type="商业", min_area_sqm=400),
])

# 4. 构建规划方案 (Layer 4)
planned = PlanBlock(version="v1",
    parcel_changes=[
        ParcelChange(bsm="441426211000055682", action="reclassify",
                     new_planning_land_use="2121", new_area_ha=0.15,
                     derived_from_bsms=["441426211000055682"]),
    ],
    facility_changes=[
        FacilityChange(name="展销中心", action="new", facility_type="商业", area_sqm=400),
    ],
    road_changes=[
        RoadChange(name="规划路", action="new", road_level="主干道", width_m=12),
    ],
)

# 5. 构建 KG (四层一次性写入)
kg = PlanningKG("金田村委会")
kg.build_from_blocks(
    blocks=blocks, bundle=bundle, parcel_relations=relations,
    intent=intent, plan_block=planned,
)

# 6. 查询 Layer 1: 现状实体
parcel_count = kg.get_parcel_count()                    # 660
constraints = kg.get_constraints()                      # 3 条约束

# 7. 查询 Layer 2: 约束规则
r = kg.query("PREFIX pln: <http://village-planning.org/ontology#> "
             "SELECT ?id ?field ?op ?value WHERE { "
             "?c a pln:Constraint ; pln:constraint_id ?id ; "
             "pln:field ?field ; pln:operator ?op ; pln:value ?value . }")

# 8. 查询 Layer 3: 意图子图
zone_targets = kg.query("PREFIX pln: <http://village-planning.org/ontology#> "
                         "SELECT ?code ?area WHERE { "
                         "?z a pln:ZoneTarget ; pln:land_use_code ?code ; "
                         "pln:target_area_ha ?area . }")

# 9. 查询 Layer 4: 规划方案
violations = kg.check_constraint_violations("v1")       # 冲突检测
diff = kg.compare_versions("v1", "v2")                   # 多版对比

# 10. 语义查询
nearby = kg.get_parcels_within_distance_of_entity(
    "http://village-planning.org/ontology#village_ann_刘村", 500)
adjacent = kg.get_adjacent_parcels_with_length("441426211000055682")
```

---

## 七、实际数据验证 (jintian)

### 7.1 KG 统计

使用 `data/gis/jintian/` 真实数据构建 KG，统计如下：

| 指标 | 值 |
|------|-----|
| 总三元组 | 21,253 |
| 地块 (Parcel) | 660 |
| 道路 (Road) | 175 (131 from road.geojson + 44 from DLBM) |
| 设施 (Facility) | 44 |
| 自然村落 (NaturalSettlement) | 19 |
| 水域 (WaterBody) | 44 |
| 分区 (Zone) | 139 |
| VNE 分类 (LandUseCategory) | 28 |
| 三区 (ThreeZone) | 3 |
| 三线 (ThreeLine) | 6 |
| 约束 (Constraint) | 3 |

### 7.2 三层空间关系

| 层 | 关系 | 三元组数 | 计算来源 |
|----|------|---------|---------|
| L1 | `pln:touches` | 1,549 | `compute_parcel_relations` (shapely `geom.touches()`) |
| L2 | `pln:nearby` | 4,195 | `compute_parcel_relations` (质心距离 ≤ 200m) |
| L3 | `pln:connected_via_road` | 207 | `compute_parcel_relations(parcels, roads=...)` (道路穿过) |

### 7.3 PlanBlock 增量写入对比

| 方案 | 三元组增量 | 说明 |
|------|-----------|------|
| 旧 PlannedState (全量镜像) | ~6,600 (+31%) | 660 地块 × 5 字段 × 2 (type+value) |
| 新 PlanBlock (增量 delta) | 37 (+0.17%) | 3 变更条目 × ~12 字段 |

### 7.4 可视化产物

位于 `docs/gis/kg_visualization/`：
- `kg_architecture.svg` - 四层架构图（含实际实体计数）
- `kg_sample_subgraph.svg` - 样本子图（村庄+约束+地块+L4 delta）
- `kg_statistics.png` - 实体分布 + 关系分布柱状图
- `kg_dlbm_distribution.png` - DLBM 地类分布饼图

生成命令：
```bash
cd F:/project/Village_Planning_Agent
export PATH="$PATH:/c/Program Files/Graphviz/bin"
python backend/scripts/visualize_kg.py
```

### 7.5 测试

```bash
cd backend
python -m pytest tests/integration/test_kg_jintian_e2e.py tests/unit/test_kg_no_reverse_deps.py -v
# 73 passed in ~91s
```

---

## 八、变化记录

| 版本 | 变更                                                                        |
| ---- | --------------------------------------------------------------------------- |
| v4.4 | 引入 SpatialCognitiveUnit 形态层级，统一认知锚点/意图/规划状态的类型体系    |
| v4.4 | `build_from_blocks` 单入口，四层显式写入                                  |
| v4.4 | `PlanIntent.targets` 统一为 `List[SpatialIntentUnit]`，isinstance 分发  |
| v4.4 | `PlanBlock` 增量变更集设计，稀疏写入，L1+L4 merge 查询 |
| v4.4 | L3 路网连通（`compute_parcel_relations` 接受 roads 参数） |
| v4.4 | 删除 21 个旧方法，零 shapely/geopandas 依赖                                 |
| v4.3 | 项目级`ProjectKG` + ConstraintCompiler + 对接 `ProjectDataView`         |
| v4.2 | GISDataBundle 形态重组，Schema 提升                                         |
| v4.1 | 三层模型分离，Layer1 缓存                                                   |
