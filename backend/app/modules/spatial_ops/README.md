# Spatial Ops — 空间计算唯一层

> **定位**：系统中**所有**空间计算的唯一发生地。BBox、距离、面积、方向、邻接、过滤、约束索引、地块几何操作、道路规划、用地平衡——凡是涉及几何运算的，只在此模块内实现。
> **依赖**：`app.modules.schema`（类型契约 + encodings）+ `app.utils`（geojson / area / crs / geo 工具）
> **不依赖**：Agent / Services / Api / Tools（反向依赖禁止）
> **Updated: 2026-08-05**（Batch B 子包重组：扁平模块全部迁移为子包规范路径）

---

## 职责边界

**负责**：空间计算领域能力 —— 空间认知卡片（ContextBlock）、几何/关系/细分/发展轴、空间索引桥接（SpatialIndex / ConstraintIndex）、PARSE 空间接地与确定性绑定、候选评分 + MCLP 设施选址、地块几何操作、用地平衡表、前端图层契约 + 会话导出包、词汇驱动分区、跨维度冲突检测、PuLP MIP 分区分配、确定性 staged 道路规划。

**不负责**：
- 不解析自然语言（那是 `parsing/` 与 PARSE agent）
- 不决定规划策略（那是 agent 编排层）
- 不存储/查询知识图谱（那是 `kg/`）
- 不定义类型契约（那是 `schema/`）

### 子包职责一览

| 子包 | 文件 | 职责 |
|---|---|---|
| `geometry/` | geometry.py + relations.py + subdivision.py + axis_builder.py | 无状态几何助手 / 三层地块关系 / footprint OBB 递归细分 / 发展轴生成 |
| `index/` | bridge.py | SpatialIndex + ConstraintIndex 空间索引桥接（KG BSM → bundle 几何） |
| `grounding/` | grounding.py + resolver.py + bundle_binder.py | PARSE 空间接地分派 / SpatialResolver 统一入口 / 确定性 BSM 绑定 |
| `context/` | context.py | `compute_context_blocks`（8 种空间认知卡片，CJK 感知 token 预算） |
| `selection/` | selection.py + facility_location.py | 候选评分放置 + MCLP 设施选址 |
| `parcel_ops/` | parcel_ops.py | 地块几何操作（reclassify / modify / merge / split / create / apply） |
| `land_balance/` | land_balance.py | L1 vs L4 用地平衡表 + DeliveryGate |
| `output/` | map_layers.py + export_package.py | 前端图层契约 + 校验后的会话导出包 |
| `zoning/` | custom_planning.py + vocab_rules.py + vocab_context.py + custom_zone_generator.py | 词汇驱动自定义功能区（TypingRule DSL + 多因子上下文） |
| `conflict/` | detector.py + resolver.py | 跨维度指标/约束/空间冲突检测与消解 |
| `allocation/` | zone_allocator_adapter.py | PuLP MIP 全局地块→分区分配（实现 `ZoneAllocatorPort`） |
| `road/` | 6-stage staged 道路规划管线 | 网络构建→规划节点→地形路由→校验→KG 重试（见 `road/README.md`） |

### 子包结构（Batch B 重组后）

```
spatial_ops/
├── geometry/        # geometry.py + relations.py + subdivision.py + axis_builder.py
├── index/           # bridge.py (SpatialIndex, ConstraintIndex)
├── grounding/       # grounding.py + resolver.py + bundle_binder.py
├── context/         # context.py (ContextBlock cognition cards)
├── selection/       # selection.py + facility_location.py (MCLP)
├── parcel_ops/      # parcel_ops.py (parcel geometry mutation)
├── land_balance/    # land_balance.py
├── output/          # map_layers.py + export_package.py
├── zoning/          # custom_planning.py + vocab_rules.py + vocab_context.py + custom_zone_generator.py
├── conflict/        # detector.py + resolver.py
├── allocation/      # zone_allocator_adapter.py (PuLP MIP)
└── road/            # 6-stage staged road planner
```

> 旧扁平模块路径（`spatial_ops.bridge` / `.bundle_binder` / `.resolver` / `.relations` / `.subdivision` / `.facility_location` / `.map_layers` / `.export_package` / `.custom_planning`）已移除，统一使用子包规范路径（如 `spatial_ops.index.bridge`）；子包同名路径（`spatial_ops.geometry` / `.selection` / `.parcel_ops` 等）由子包 `__init__.py` 再导出覆盖。

---

## 输入/输出契约

**输入**：`VillageBundle`（`app.modules.schema.types.canonical`）+ `ConstraintIndex` + 契约（`app.modules.schema.contracts.*`）。

**输出契约**：

| 输出 | 契约（`schema/contracts/`） | 消费者 |
|---|---|---|
| `ContextBlock` 卡片 | `context_contracts.py` | KG builder / PARSE agent |
| `ZoneSpatialAnchor` | grounding（spatial_ops 内部） | PARSE format_targets |
| `ParcelRelations` / `SpatialRelation` | — | KG builder `layer2.py` |
| `LandBalanceTable` / `DeliveryGate` | `land_balance_contracts.py` | 导出层 |
| 地块操作结果 / PlannedState 输入 | `parcel_change_contracts.py` | EXECUTE |
| `ZoneAllocationSolution` | `execution_plan_contracts.py` | EXECUTE zone worker |
| 前端图层 / 导出包 | `output/map_layers.py` | API / 渲染 |

**规范公开 API**（`app.modules.spatial_ops.__init__` 桶导出，含兼容别名）：

```python
from app.modules.spatial_ops import (
    compute_context_blocks,          # == compute_spatial_context（旧名兼容别名）
    build_spatial_index, SpatialIndex, OverlapResult,
    build_constraint_index, ConstraintIndex, ConstraintOverlap,
    DeterministicBundleBinder, bind_exploration_to_bundle,
    ZoneSpatialAnchor, resolve_directional_bbox,
    query_parcels_in_bbox, query_parcels_near_entity,
    query_excluded_parcels, compute_proximity_weights,
    compute_target_area, ground_zone_spatial_preference,
    reclassify_parcel, modify_parcel, merge_parcels,
    split_parcel_by_geometry, create_parcel, apply_operations,
    compute_land_balance, check_delivery_gate,
)
```

---

## 依赖方向

- **内部**：`app.modules.schema`（`contracts.*`、`types.canonical.VillageBundle`、`encodings.code_sets` 的 `get_planning_zone_from_landuse` / `normalize_landuse` / `GHYTBM_TO_VNE`、`DLBM_TO_DLMC` / `get_dlbms_for_zone_type`）；`app.modules.ports`（实现 `ZoneAllocatorPort`）；`app.utils`（logger / geojson_utils / area_engine / crs_engine / geo_utils）
- **外部**：`geopandas>=0.14.0`、`shapely>=2.0.0`、`pyyaml`（`_load_place_aliases`）
- ⚠️ geopandas / shapely 在函数内**惰性导入**并有 `ImportError` 守卫——缺库时相关函数返回空结果而不是崩溃。

---

## 禁止行为

- **禁止导入** `app.agent` / `app.services` / `app.api` / `app.tools`（领域层向上依赖即架构缺陷）
- **不做 LLM 调用** / 不解析自然语言 / 不做文本提取
- 不把空间计算泄漏到 `kg/`、`parsing/`、`agent/`、`tools/` ——"所有空间计算只在 spatial_ops"是全局原则
- **边界**：空间算法只由本模块和 DELIVER 适配器调用；旧 GIS dev pipeline 已删除，避免工具层重新读取原始 GIS 或生成第二份交付结果。
- 不在 `__init__.py` 中追加新的扁平模块路径——新能力应落在对应子包下并通过子包 `__init__.py` 导出

---

## 相关文档

- `road/README.md` — 6-stage staged 道路规划管线详述
- `docs/design/01_LAYERED_ARCHITECTURE.md` — 分层架构（Spatial Query 层定位）
- `modules/kg/README.md` — KG 模块（消费 ParcelRelations / ContextBlock）
- `modules/schema/contracts/parse_contracts.py` — PARSE 契约（含空间锚定字段）
