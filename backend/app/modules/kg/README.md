# Planning Knowledge Graph (KG) 模块

> 规划知识图谱：村庄规划系统的**语义与空间桥接层**。
> 向上消费 Schema 类型化空间要素 + PARSE 解析结果，向下为 LAYOUT 布局执行提供约束、邻接与空间关系查询。

---

## 一、模块定位

KG 是独立于 GIS 子包的桥接模块（位于 `app/modules/kg/`，非 `app/modules/gis/`）。
其职责是**将空间数据与规划语义统一编码为 RDF 三元组**，使下游 Agent 能通过 SPARQL 查询获取：

- 空间要素实体（地块 / 设施 / 道路 / 水体 / 保护边界 ...）
- 空间关系（邻接 `adjacent_to`、包含 `within_zone`、定位 `located_in` ...）
- 规划约束（建设用地上限、耕地下限、生态红线 ...）
- 规划意图（分区目标、设施布局、发展轴线 ...）

### 系统位置（PARSE ↔ KG ↔ LAYOUT）

```
                    ┌─────────────────────────────────────┐
                    │           app/modules/gis/schema     │
                    │  SpatialFeature 全类型化模型 (Group A~E) │
                    │  UnifiedSpatialIntent / SpatialContext │
                    └───────────┬──────────────┬───────────┘
                                │ typed models  │ typed models
                    ┌───────────▼──────────┐   │
  L3 报告/规划文本 ──►│   PARSE Agent        │   │
                    │  compute_spatial_     │   │
                    │  context() -> 关系    │   │
                    │  parse -> intent /    │   │
                    │  operations /         │   │
                    │  constraints          │   │
                    └───────────┬───────────┘   │
                                │               │
                     typed     │  写入          │
                  ┌─────────────▼───────────────▼────────┐
                  │            KG 模块 (本模块)            │
                  │  PlanningKG (RDFLib Graph)            │
                  │  Layer1 静态 / Layer2 语义 / Layer3 易失 │
                  └─────────────┬─────────────────────────┘
                                │ SPARQL 查询 / 预计算结果
                    ┌───────────▼───────────┐
                    │   LAYOUT Pipeline     │
                    │  MIP Allocator        │
                    │  ZoneGenerator        │
                    │  FacilityPlacer       │
                    └───────────────────────┘
```

**设计意图**：KG 是 PARSE 与 LAYOUT 之间的**唯一语义中间态**——PARSE 把理解到的空间关系与意图约束写入 KG，LAYOUT 从 KG 读取约束与邻接执行布局。这使得 LAYOUT 不必直接处理原始 GeoJSON 或自然语言。

---

## 二、设计原则

| 原则 | 含义 | 当前符合度 |
|------|------|-----------|
| **Schema-First** | KG 只通过 `app.modules.gis.schema` 的类型化模型读取空间要素，不直接解析 GeoJSON dict | ⚠️ 部分（见 §五） |
| **单向依赖** | KG 仅依赖 schema 层，不依赖 GIS 工具层（`tools/gis/_generation`、`_analytics`） | ❌ 违反（见 §五） |
| **三层分离** | 静态层缓存复用、语义层按意图重建、易失层闭环迭代 | ✅ 已实现 |
| **PARSE 结果落库** | PARSE 计算的空间关系、执行操作、约束集应持久化到 KG | ❌ 缺失（见 §五） |
| **LAYOUT 查询驱动** | LAYOUT 通过 SPARQL 模板获取约束与邻接，而非直接读 GeoJSON | ✅ 基本实现 |

---

## 三、模块结构

```
backend/app/modules/kg/
├── __init__.py      # 公开 API 导出
├── ontology.py      # 本体定义：23 实体类型 + 14 关系类型 + 规则常量
├── builder.py       # PlanningKG 构建器：GeoJSON/Intent/Reports -> RDF 三元组
├── query.py         # 28 个 SPARQL 查询模板 + query_kg() 工具接口
└── manager.py       # KGManager：三层缓存 + 会话管理 + 查询缓存
```

| 文件 | 核心导出 | 职责 |
|------|---------|------|
| `ontology.py` | `PLN`, `GEO`, `EntityTypes`, `Relations`, `FACILITY_TYPES`, `REGULATION_TYPES` | 命名空间 + 实体/关系 URI + 规则映射表 |
| `builder.py` | `PlanningKG`, `KGInputParcels` | RDF 图构建（三层 build + Phase 1~4 增强入库） |
| `query.py` | `QUERY_TEMPLATES`, `query_kg()`, `TOOL_META` | SPARQL 模板字典 + 参数化查询接口 |
| `manager.py` | `KGManager`, `CacheKey`, `compute_layer1_cache_key`, `get_kg_manager` | 进程级单例缓存 + LRU + 版本失效 |

---

## 四、本体设计（ontology.py）

### 实体类型（23 类）

| 阶段 | 实体 | 说明 |
|------|------|------|
| Phase 0 | `Parcel`, `Zone`, `Constraint`, `Indicator` | 基础四要素 |
| Phase 1 | `Project`, `Village`, `Regulation`, `LandUsePlan`, `Facility`, `Axis`, `Road`, `WaterBody`, `BuildingGroup` | 规划语义扩展 |
| Phase 2 | `LandConservationPlan`, `ReforestationPlan`, `GridRegulation` | 整治规划（对标 DB35/T 2061-2022） |
| Phase 3 | `ControlRule`, `LandUseCategory`, `PlanningIndicator`, `ThreeZone`, `ThreeLine` | 专业范式对齐（三区三线 / VNE / 管制规则） |
| Phase 6 | `AdministrativeVillage`, `NaturalSettlement` | 村庄层级（行政村 vs 自然村） |

### 关系类型（14 类）

- 空间：`adjacent_to`, `within_zone`, `located_in`, `designated_as`, `connects`
- 管制：`constrained_by`, `protects`, `delineates`, `controls_use`
- 语义：`achieves`, `conflicts_with`, `derived_from`, `serves`, `conducted_from`

---

## 五、当前实现审视（关键差距）

> 以下对照"桥接层应具备的形态"审视现有代码，标注差距与影响。

### 差距 1：KG 仍直接读取 GeoJSON dict，未走 Schema 类型化路径

**现状**：
- `builder.py` 存在两套并行入口：
  - 原始 dict 路径：`_add_parcels(geojson)`、`_add_spatial_relations(geojson)`、`_add_spatial_infrastructure(landuse_geojson)`、`_add_designated_as_relations(landuse_geojson)`、`add_protection_zones(gis_data)`、`add_control_lines(gis_data)`、`add_planning_elements(gis_data)`、`add_natural_features(gis_data)` —— 全部直接 `props.get("BSM")`、`ft.get("geometry")`
  - 类型化路径：`_add_parcels_typed(parcels)`、`KGInputParcels.from_geojson()`、`add_annotations(annotations)`、`add_roads(roads)` —— 接收 `CurrentLandUseParcel` / `CurrentAnnotation` / `CurrentRoad` 等 schema 模型

- **生产管线走的是原始 dict 路径**：
  - `tools/gis/kg.py` 的 `build_knowledge_graph` → `manager.get_or_build_layer1(village_name, landuse_geojson, gis_data)` → `_build_static(landuse_geojson=..., gis_data=...)`
  - `tools/gis/parse.py` 的 `parse_planning_text` → 同上
  - 类型化路径仅在 `scripts/run_parse_pipeline.py:498`（`parcels=typed_parcels` + `add_annotations` + `add_roads`）和测试脚本中调用，**生产工具链未使用**

**影响**：
- 编码体系校验（ingestion 层的 `_EncodingValidator`）被绕过，DLBM 体系归属（appendix5 / tugui）不进入 KG
- 字段语义靠 `props.get("DLMJ", props.get("SHAPE_Area", ...))` 这种 fallback 猜测，脆弱
- 违反 Schema-First 原则，KG 与 GeoJSON 字段名强耦合

**应做**：所有 `_add_*` / `add_*` 方法签名改为接收 `List[SpatialFeature]` 或具体子类，`gis_data` dict 在进入 KG 前先经 `ingest_feature()` / `ingest_current_landuse()` 转为类型化对象。

---

### 差距 2：PARSE 计算的空间关系未写入 KG

**现状**：
- `spatial_context.py:compute_spatial_context()` 会产出 `List[SpatialRelation]`（村组间 `east_of` / `adjacent_to` / `contains` / `near` / `along` / `between`），这是 PARSE 对空间要素初始化计算出的语义关系
- 但这些关系**只注入 LLM prompt，从未写入 KG**
- KG 中的 `adjacent_to` 仅来自 `_add_spatial_relations()` 的几何 sjoin（地块级别，O(n²)），**没有村组/设施级别的语义关系**

**影响**：
- LAYOUT 无法通过 SPARQL 查询"XX 村组东边的地块""设施 A 服务覆盖范围"
- PARSE 每次推理都要重新计算空间关系，无法复用
- KG 丢失了作为"空间关系存储"的核心价值

**应做**：新增 `add_spatial_relations(relations: List[SpatialRelation])`，将 PARSE 计算的语义关系三元组（subject, relation, object）持久化为 KG 三元组，subject/object 指向 `NaturalSettlement` / `Facility` / `Zone` 实体。

---

### 差距 3：PARSE 执行结果（operation_sequence / constraint_set）未入 KG

**现状**：
- PARSE 产出三样东西（`parse.py:99-113`）：
  - `operation_sequence: List[SpatialOperation]` —— 空间执行操作（带空间锚点）
  - `constraint_set: List[SpatialConstraint]` —— 空间约束规则
  - `planning_intent: SpatialPlanningIntent` —— 分区/设施/轴线目标
- 这三者通过 LangGraph state 直接注入 `generate_layout`，**只有 `planning_intent` 的 `constraints` 字段（`List[ConstraintIntent]`）经 `build_from_intent` 进入 KG**
- `operation_sequence` 完全不入 KG；`constraint_set`（ richer 的 `SpatialConstraint`）也不入 KG

**影响**：
- LAYOUT 执行的操作序列无法回溯查询（"为什么这个地块被划为建设区？"无法 SPARQL 追溯）
- 闭环迭代时，KG 的 Layer 3（`designated_as`）只反映 DLBM 静态映射，不反映 PARSE 实际意图的操作结果
- 约束来源断裂：KG 里的 Constraint 实体来自 YAML/报告/GIS 实测，唯独缺 PARSE 解析出的那部分

**应做**：
- 新增 `add_parse_results(operations: List[SpatialOperation], constraints: List[SpatialConstraint])`
- `SpatialOperation` → Operation 实体 + `derived_from` 关系链接到 Parcel/Zone
- `SpatialConstraint` → Constraint 实体（`source="parse"`），补齐现有 `source` 字段的 `intent` / `gis_measured` / `report` 之外的第四类来源

---

### 差距 4：KG 反向依赖 GIS 工具层（层级违反）

**现状**（`builder.py` 内的 import）：
- `builder.py:760` `from app.tools.gis._analytics.metrics_calculator import GISMetricsCalculator`
- `builder.py:926, 1008` `from app.tools.gis._generation.zone_generator import resolve_zone_type_for_dlbm`
- `builder.py:1579` `from app.tools.gis._generation.optimizer.mip_allocator import dlbm_to_planning_zone`

**影响**：
- KG 作为桥接层，却依赖下游 LAYOUT 工具（`_generation` / `_analytics`），形成 `KG → tools/gis → KG` 的潜在循环
- `dlbm_to_planning_zone` / `resolve_zone_type_for_dlbm` 这类编码→分区映射本应由 schema 层（`code_sets.py` 已有 `dlbm_to_planning_zone`）提供，KG 却绕道去工具层取
- `GISMetricsCalculator` 在 KG 内计算约束，意味着 KG 承担了本该在 ingestion/analytics 层完成的计算职责

**应做**：
- `dlbm_to_planning_zone` → 改用 `app.modules.gis.schema.dlbm_to_planning_zone`（已存在）
- `resolve_zone_type_for_dlbm` → 改用 schema 的 `get_zone_type_for_dlbm`
- `GISMetricsCalculator` 调用 → 上移到 ingestion 层，KG 只接收已算好的 metrics 类型化对象

---

### 差距 5：查询模板使用率低（12/28 未被调用）

参照 `docs/gis/schema对接kg，parse.md` 的统计：28 个模板中仅 6 个被 PARSE/LAYOUT 实际调用。
未使用的模板（如 `get_adjacent_parcels`、`get_project_indicators`、`get_regulation_impacts`、`get_terrain_profile` 等）属于预建但无消费者，需评估是补齐消费者还是删除。

---

## 六、三层缓存架构（manager.py）

| 层 | 内容 | 缓存键 | 生命周期 |
|----|------|--------|---------|
| **Layer 1 静态** | 地块、邻接、VNE、基础设施、GIS 约束 | `village_name + landuse_hash(SHA256)` | 进程级 LRU(50)，同村同数据命中 |
| **Layer 2 语义** | 约束、指标、分区、规制（来自 intent/reports） | 无（按意图重建） | 每次 PARSE 输出重建 |
| **Layer 3 易失** | `designated_as` 关系、分区指派 | 无 | 闭环迭代时变更，`bump_version` 失效查询缓存 |

- `get_or_build_layer1()`：Layer 1 命中时 `clone_static_layer()` 复制三元组，避免 O(n²) 邻接重算
- `query_with_cache()`：SPARQL 结果按 `session_id + template + params` 缓存，版本号失效
- 线程安全：单例创建锁，缓存操作依赖 GIL

---

## 七、对外 API

### 构建入口

```python
from app.modules.kg import PlanningKG, get_kg_manager

# 生产路径（带缓存）
manager = get_kg_manager()
kg, cache_hit = manager.get_or_build_layer1(village_name, landuse_geojson, gis_data)
kg._build_semantic(intent=intent, zone_areas=zone_areas)   # Layer 2
kg._build_volatile(landuse_geojson=landuse_geojson)        # Layer 3
kg.add_protection_zones(gis_data)                          # Phase 4 增强
kg.add_control_lines(gis_data)
kg.add_planning_elements(gis_data)
kg.add_natural_features(gis_data)

# 便捷路径（scripts 用）
kg = manager.get_or_build_kg(village_name, landuse_geojson, gis_data,
                              intent=intent, session_id=sid)
```

### 查询入口

```python
from app.modules.kg import query_kg, QUERY_TEMPLATES

results = query_kg(kg, "get_constraint_by_field", field_name="construction")
results = query_kg(kg, "get_parcel_neighbors", bsm="12345_0101_5600")
results = query_kg(kg, "count_by_vne")
```

### 持久化

```python
kg.to_turtle()                  # 序列化为 Turtle 字符串（state 持久化用）
PlanningKG.from_turtle(t, ...)  # 从 Turtle 重建
kg.serialize("kg.ttl")          # 写文件（调试用）
```

---

## 八、改进路线（建议优先级）

### P0：消除原始 GeoJSON 读取（差距 1 + 4）

1. `_build_static` 签名改为接收 `List[CurrentLandUseParcel]` + `List[SpatialFeature]`，移除 `landuse_geojson` 参数
2. `add_protection_zones` / `add_control_lines` / `add_planning_elements` / `add_natural_features` 改为接收类型化要素列表，由调用方通过 `ingest_feature()` 预先转换
3. 替换 `tools.gis._generation` / `_analytics` import 为 schema 层函数
4. `tools/gis/kg.py` 与 `tools/gis/parse.py` 在调用 `get_or_build_layer1` 前先 ingestion

### P1：PARSE 空间关系落库（差距 2）

5. 新增 `PlanningKG.add_spatial_relations(relations: List[SpatialRelation])`
6. `parse_planning_text` 在 KG 构建后调用，把 `spatial_context.spatial_relations` 写入
7. 新增查询模板 `get_village_relations`（按村名查语义关系）

### P1：PARSE 执行结果落库（差距 3）

8. 新增 `PlanningKG.add_parse_results(operations, constraints)`
9. `build_knowledge_graph` 工具接收 `operation_sequence` / `constraint_set` 并写入
10. 新增查询模板 `get_operations_by_parcel`（追溯地块操作来源）

### P2：查询模板治理（差距 5）

11. 核查 12 个未使用模板，补齐消费者或标记废弃
12. `get_adjacent_parcels` 等 P0 模板接入 LAYOUT MIP 的邻接图构建

---

## 九、相关文档

- `docs/gis/schema对接kg，parse.md` —— Schema→KG 入库覆盖率审计 + 优化方案（本文差距 1/5 的来源）
- `docs/gis/01_DESIGN_GOALS.md` —— §6 Schema-First / 注入层强制原则
- `backend/app/modules/data/ingest.py` —— 类型化摄入端口（KG 应走的入口，从 schema 迁入）
- `backend/app/modules/gis/spatial_context.py` —— PARSE 空间关系计算（KG 应接收的输入）
- `backend/app/agent/gis/parse/state.py` —— `SpatialPlanningIntent` / `SpatialOperation` / `SpatialConstraint` 定义
