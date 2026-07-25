
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
| Layer 3 | PARSE 意图（SpatialPlanningIntent） | 单次规划会话           | PARSE Agent →`_add_structured_intent` | EXECUTE、约束冲突检测               |
| Layer 4 | EXECUTE 规划方案（版本化）              | 会话持久（可多版并存） | EXECUTE Agent →`_add_planned_state`   | 指标校核、多版对比、导出            |

### 2.1 构建入口

```python
kg = PlanningKG(village_name="金田村委会")
kg.build_from_blocks(
    blocks=blocks,              # List[ContextBlock] — 空间认知卡片
    bundle=bundle,              # VillageBundle — 类型化形态视图
    parcel_relations=relations, # ParcelRelations — 三层空间关系（外部计算）
    intent=intent,              # SpatialPlanningIntent — PARSE 意图（可选）
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
| `pln:WaterBody`         | DLBM 分类 + `bundle.polygons.water_bodies` | `_add_infrastructure_from_typed` + `_add_natural_features_from_typed` |
| `pln:ProtectedZone`     | CONSTRAINTS ContextBlock            | `_add_constraints_from_blocks`      |
| `pln:ControlLine`       | `bundle.points.hazard_points`     | `_add_control_lines_from_typed`     |
| `pln:LandUseCategory`   | VNE YAML                            | `_add_vne_categories`               |

### 2.3 Layer 2: 约束规则

- 从 CONSTRAINTS ContextBlock 提取保护面面积和规则
- 从 LANDUSE_DIST ContextBlock 提取用地分布约束值
- 约束值写入 `pln:Constraint` 实体，供 ConstraintCompiler 查询

### 2.4 Layer 3: 意图子图

`SpatialPlanningIntent` 直接消费，通过独立的 `zone_targets`、`facilities`、`development_axes` 列表分发。

语义字段（`natural_language_description`、`spatial_hint`、`reasoning_trace`）
存储在 `_semantic_store` JSON 附件中，不存为 RDF 三元组。

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

| SpatialCognitiveUnit 子类 | KG 层     | 来源                                     |
| ------------------------- | --------- | ---------------------------------------- |
| `NaturalVillageAnchor`  | Layer 1   | NATURAL_VILLAGES ContextBlock            |
| `FacilityAnchor`        | Layer 1   | FACILITIES ContextBlock                  |
| `RoadAnchor`            | Layer 1   | `bundle.lines.roads_current`           |
| `ConstraintZoneAnchor`  | Layer 1+2 | CONSTRAINTS ContextBlock                 |
| `ZoneTarget`            | Layer 3   | `SpatialPlanningIntent.zone_targets` |
| `FacilityTarget`        | Layer 3   | `SpatialPlanningIntent.facilities`    |
| `RoadTarget`            | Layer 3   | `SpatialPlanningIntent.development_axes` |
| `ParcelChange`          | Layer 4   | `PlanBlock.parcel_changes` (delta)     |
| `FacilityChange`        | Layer 4   | `PlanBlock.facility_changes` (delta)   |
| `RoadChange`            | Layer 4   | `PlanBlock.road_changes` (delta)       |
| `SettlementChange`      | Layer 4   | `PlanBlock.settlement_changes` (delta) |
| `ContextBlock`          | 跨层      | `spatial_ops.compute_context_blocks`   |

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
| `layer3.py`  | `_add_structured_intent`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | PARSE 意图子图 |
| `layer4.py`  | `_apply_plan_block`, `get_effective_land_use`, `get_effective_area_ha`, `get_plan_changes`, `get_split_parcels`, `get_merge_parcels`, `get_planned_parcels_in_zone`, `check_constraint_violations`, `compare_versions`                                                                                                                                                                                                                                                                                                                                | 规划状态       |
| `queries.py` | `query`, `get_constraints`, `get_adjacency_map`, `get_parcel_count`, `get_triple_count`, `serialize`, `to_turtle`, `from_turtle`, `get_parcels_within_distance_of_entity`, `get_adjacent_parcels_with_length`, `validate_intent`                                                                                                                                                                                                                                                                                                                  | 语义查询       |

---

## 六、数据加载到 KG 构建的完整流程

### 6.1 端到端示例

```python
from app.modules.data import DataCatalog
from app.modules.spatial_ops import compute_context_blocks
from app.modules.spatial_ops.geometry import compute_parcel_relations
from app.modules.kg import PlanningKG, get_kg_manager
from app.modules.schema.contracts.parse_contracts import (
    SpatialPlanningIntent, ZoneTarget, FacilityTarget, AxisTarget,
)
from app.modules.schema.contracts.context_contracts import (
    PlanBlock, ParcelChange, FacilityChange, RoadChange,
)

# 1. 加载数据
catalog = DataCatalog()
bundle = catalog.load_village_bundle("金田村委会")

# 2. 计算空间认知卡片 + 三层空间关系
blocks = compute_context_blocks(bundle)
relations = compute_parcel_relations(bundle.polygons.landuse_current)

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

# 8. 查询 Layer 3: 意图子图（结构数据 + 语义附件）
zone_targets = kg.query("PREFIX pln: <http://village-planning.org/ontology#> "
                         "SELECT ?code ?area WHERE { "
                         "?z a pln:ZoneTarget ; pln:land_use_code ?code ; "
                         "pln:target_area_ha ?area . }")
semantic = kg._semantic_store  # JSON 附件，不存为 RDF 三元组

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

| 指标                         | 值                                         |
| ---------------------------- | ------------------------------------------ |
| 总三元组                     | 21,077                                     |
| 地块 (Parcel)                | 660                                        |
| 道路 (Road)                  | 131 (from road.geojson via `add_roads`) |
| 设施 (Facility)              | 44                                         |
| 自然村落 (NaturalSettlement) | 19                                         |
| 水域 (WaterBody)             | 44                                         |
| 分区 (Zone)                  | 139                                        |
| VNE 分类 (LandUseCategory)   | 28                                         |
| 三区 (ThreeZone)             | 3                                          |
| 三线 (ThreeLine)             | 6                                          |
| 约束 (Constraint)            | 3                                          |

### 7.2 三层空间关系

| 层 | 关系                       | 三元组数 | 计算来源                                                    |
| -- | -------------------------- | -------- | ----------------------------------------------------------- |
| L1 | `pln:touches`            | 1,549    | `compute_parcel_relations` (shapely `geom.touches()`)   |
| L2 | `pln:nearby`             | 4,195    | `compute_parcel_relations` (质心距离 ≤ 200m)             |
| L3 | `pln:connected_via_road` | 207      | `compute_parcel_relations(parcels, roads=...)` (道路穿过) |

### 7.3 PlanBlock 增量写入对比

| 方案                       | 三元组增量    | 说明                                 |
| -------------------------- | ------------- | ------------------------------------ |
| 旧 PlannedState (全量镜像) | ~6,600 (+31%) | 660 地块 × 5 字段 × 2 (type+value) |
| 新 PlanBlock (增量 delta)  | 37 (+0.17%)   | 3 变更条目 × ~12 字段               |

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

| 版本 | 变更                                                                       |
| ---- | -------------------------------------------------------------------------- |
| v4.5 | 统一 Intent 类型：删除 `PlanIntent`（context_contracts），KG 直接消费 `SpatialPlanningIntent`（parse_contracts） |
| v4.5 | 语义字段：`natural_language_description`、`spatial_hint`、`reasoning_trace` 存为 JSON 附件，不存为 RDF 三元组 |
| v4.5 | 本体清理：移除 6 个未用实体类型，合并 `Indicator`→`PlanningIndicator`，`adjacent_to` 标记 @deprecated |
| v4.4 | 引入 SpatialCognitiveUnit 形态层级，统一认知锚点/意图/规划状态的类型体系   |
| v4.4 | `build_from_blocks` 单入口，四层显式写入                                 |
| v4.4 | `PlanBlock` 增量变更集设计，稀疏写入，L1+L4 merge 查询                   |
| v4.4 | L3 路网连通（`compute_parcel_relations` 接受 roads 参数）                |
| v4.4 | 删除 21 个旧方法，零 shapely/geopandas 依赖                                |
| v4.3 | 项目级`ProjectKG` + ConstraintCompiler + 对接 `ProjectDataView`        |
| v4.2 | GISDataBundle 形态重组，Schema 提升                                        |
| v4.1 | 三层模型分离，Layer1 缓存                                                  |
