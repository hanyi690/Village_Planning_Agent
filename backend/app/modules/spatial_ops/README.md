# Spatial Ops - 空间计算唯一层

> **定位**: 系统中**所有**空间计算的唯一发生地。BBox、距离、面积、方向、邻接、过滤、约束编译、地块几何操作、道路规划、用地平衡——凡是涉及几何运算的，只在此模块内实现。
> **依赖**: `Schema` (类型契约 + encodings) + `app.utils` (geojson/area/crs/geo 工具)
> **不依赖**: Agent / KG / Tools / Parsing（反向依赖禁止）
> **状态**: 全部职责已实现 | **Updated: 2026-08-02**

`bundle_binder.py` 提供确定性语义实体到 session GIS Bundle 的绑定：仅在 BSM 唯一命中时确认几何，歧义候选保持待确认状态。它与 `grounding.py` 的方向/邻近接地能力配合使用，不承担报告解析或 KG 写入。

---

## 一、核心原则

**所有空间计算只在 `spatial_ops/` 内发生。**

| 层 | 允许做什么 | 禁止做什么 |
|---|---|---|
| PARSE Agent | 调用 `spatial_ops` 函数获取空间锚定 | 内联计算 BBox / 距离 / 面积 |
| EXECUTE Agent | 调用 `spatial_ops` 函数做空间验证 | 内联做几何运算 |
| KG | 存储和查询空间锚定（BSM 列表、BBox 字面量、WKT 质心） | 计算 BBox / 过滤地块 / 算距离 |
| Parsing | 文本提取（regex / markdown / LLM） | 任何空间计算 |
| Schema | 类型契约定义 | 任何计算 |

违反此原则的代码（如 PARSE Agent 内联计算 BBox、KG 内调用 shapely）都是架构缺陷。

---

## 二、职责总览（A–G）

| 职责 | 模块 | 消费者 | 本质 |
|---|---|---|---|
| A: KG 输入计算 | `context.py` + `geometry.py` + `relations.py` | KG builder | bundle → spatial cognition → KG entities |
| B: PARSE 空间接地 | `grounding.py` | PARSE agent | text → BBox/BSM candidates → ZoneSpatialAnchor |
| C: EXECUTE 空间桥接 | `bridge.py` | EXECUTE agent | KG BSM → bundle geometry → spatial verification |
| D: 约束编译 | `constraint_compiler.py` | MIP solver / EXECUTE | 多源约束 → 统一 CompilationReport + 冲突仲裁 |
| E: 地块操作 | `parcel_ops.py` | EXECUTE agent | 几何操作: reclassify/modify/merge/split/create |
| F: 道路规划 | `road_planner.py` | EXECUTE agent | RoadTarget + 现状道路 → PlannedRoad 网络 |
| G: 用地平衡表 | `land_balance.py` | 导出层 | L1 vs L4 对比 → LandBalanceTable + DeliveryGate |

---

## 三、模块结构

```
backend/app/modules/spatial_ops/
├── __init__.py               # 公开 API 桶（含 compute_spatial_context 兼容别名）
├── context.py                # 职责 A: compute_context_blocks（8 种空间认知卡片）
├── geometry.py               # 职责 A: 质心/面积/近邻/地块关系（ParcelRelations 三层）
├── relations.py              # 职责 A: 空间关系（方向、邻接）
├── grounding.py              # 职责 B: 空间接地 -- PARSE 专用（已实现）
├── bridge.py                 # 职责 C: 空间桥接 -- EXECUTE 专用（SpatialIndex/ConstraintIndex）
├── constraint_compiler.py    # 职责 D: 约束编译 -- 6 源编译 + 冲突仲裁
├── parcel_ops.py             # 职责 E: 地块几何操作 -- split/merge/modify/reclassify/create
├── road_planner.py           # 职责 F: 道路网络规划 -- RoadTarget → PlannedRoad
└── land_balance.py           # 职责 G: 用地平衡表 -- L1 vs L4 对比 + DeliveryGate
```

---

## 四、职责 A: ContextBlock 计算（context.py）

### 入口

```python
from app.modules.spatial_ops import compute_context_blocks

# 兼容别名（旧名）：compute_spatial_context == compute_context_blocks
blocks = compute_context_blocks(
    bundle,                                   # VillageBundle
    requested=None,                           # Optional[List[ContextBlockType]]，None=全部
    max_token_budget=1500,                    # CJK 感知 token 预算
) -> List[ContextBlock]
```

### 8 种空间认知卡片（生成器注册表 `_GENERATORS`）

| ContextBlockType | 生成器 | priority | 内容 |
|---|---|---|---|
| `VILLAGE_META` | `_build_village_meta` | 5 | 地块数、总面积、建设边界面积、村中心坐标 |
| `LANDUSE_DIST` | `_build_landuse_dist` | 10 | 按 dlbm 分组的面积分布（DLBM_TO_DLMC 名称增强） |
| `CONSTRAINTS` | `_build_constraints` | 15 | 保护边界摘要（永久基本农田/生态红线/历史文化等） |
| `RESIDENTIAL_CLUSTERS` | `_build_residential_clusters` | 20 | 居民点锚点（150m 缓冲 + unary_union 聚类 + 注记命名合并） |
| `FACILITIES` | `_build_facilities` | 25 | 设施精确锚点（来自 typed 设施/注记要素） |
| `SPATIAL_RELATIONS` | `_build_spatial_relations_block` | 30 | 村组间语义关系 |
| `ZONE_ADJACENCY` | `_build_zone_adjacency_block` | 35 | 分区邻接矩阵 |
| `TERRAIN` | `_build_terrain` | 40 | 地形剖面（无 DEM 数据时返回 None） |

- 按 `b.priority` 排序，然后按 **CJK 感知 token 预算** 截断（CJK 字符计 1 token，非 CJK 计 1/4）。
- 地名别名从 `data/gis/place_aliases.yaml` 加载（`_load_place_aliases`）。

---

## 五、职责 A: 几何与关系（geometry.py + relations.py）

### 无状态几何助手（geometry.py）

```python
_compute_centroid(boundary_geojson) -> Optional[Tuple[float, float]]
_compute_total_area(geojson) -> float                       # 公顷
_find_parcels_near_point(parcels, center, radius_m=200) -> List[str]
point_in_polygon(point: Tuple[float,float], geometry) -> bool   # 纯 Python 射线法（零依赖）
village_boundary_geometry(bundle) -> Optional[Dict]         # admin_areas[0] 或 planning_scope[0]
```

### 三层地块关系（geometry.py）

```python
@dataclass TouchRelation:      bsm_a, bsm_b, dlbm_a, dlbm_b, shared_boundary_length_m   # L1 拓扑邻接
@dataclass NearbyRelation:     bsm_a, bsm_b, dlbm_a, dlbm_b, centroid_distance_m        # L2 近邻
@dataclass ConnectedRelation:  bsm_a, bsm_b, road_bsm, road_length_m                    # L3 路网连通

compute_parcel_relations(parcels, roads=None, water_bodies=None) -> ParcelRelations
#   L1: R-tree sindex + touches()，共享边长 = intersection().length
#   L2: 面积加权质心阈值 min(500, max(200, (sqrt(Ai)+sqrt(Aj))*2))
#   L3: 同路跨越 (crosses/intersects)，road_length_m = 裁剪后的交线长度
```

`ParcelRelations` 结构：`touches / nearby / connected / parcel_road_intersects / parcel_water_touches`。由 KG builder 消费（`layer2.py:add_parcel_relations`），KG 侧零几何计算。

### 关系计算（relations.py）

```python
_compute_spatial_relations(residential_clusters) -> List[SpatialRelation]   # 质心角度方向 + contains
_compute_zone_adjacency(parcels) -> Dict[str, List[str]]                    # zone_type 邻接
```

---

## 六、职责 B: PARSE 空间接地（grounding.py）✅ 已实现

将自然语言空间描述（如"村北""靠近刘村"）接地为空间锚定：方向 → BBox → 候选地块 → 排除约束 → 邻近加权。

### 数据类

```python
@dataclass
class ZoneSpatialAnchor:
    candidate_bsms: List[str]                # BBox/语义选定后的候选地块 BSM
    candidate_bbox: Optional[Tuple[float, float, float, float]]
    excluded_bsms: List[str]                 # 与约束多边形重叠的排除 BSM
    proximity_weights: Dict[str, float]      # 邻近度 0.0-1.0
```

### API（`__init__.py` 已全部导出）

```python
# 方向接地：支持 8 方位（中英文），BBox 从 center 向方向偏移 radius_m
resolve_directional_bbox(center, direction, radius_m=1000) -> Optional[Tuple[4]]

# 地块过滤（按质心）
query_parcels_in_bbox(parcels, bbox) -> List[str]
query_parcels_near_entity(parcels, entity_center, max_distance_m=500) -> List[str]
query_excluded_parcels(constraint_index, parcels, zone_type="") -> List[str]
#   ⚠️ 注意：第一参数是 ConstraintIndex（来自 spatial_ops.bridge），不是 context_blocks
#   对每个地块调 constraint_index.parcel_in_constraint(bsm)，zone_type 空=检查全部约束

# 邻近度评分（MIP 目标函数用）：weight = max(0, 1 - dist/max)
compute_proximity_weights(parcels, reference_center, max_distance_m=500) -> Dict[str, float]

# 面积计算
compute_target_area(area_ratio, total_area_ha) -> float

# 组合接口（PARSE format_targets 后唯一入口）
ground_zone_spatial_preference(
    preference_desc, place_mappings, constraint_index, bundle, preselected_bsms=None
) -> ZoneSpatialAnchor
#   preselected_bsms 非空 → 跳过 BBox 候选搜索，直接对 LLM 选定 BSM 做排除+加权
#   内部：提取方向关键词 → 地名匹配 center →（无地名则村庄整体质心）→ BBox → 候选 → 排除 → 加权
```

### 扩展：设施与线状接地（`grounding.py` 定义，未在 `__init__.py` 导出）

```python
ground_facility_spatial_preference(location_hint, direction, place_mappings, bundle) -> ZoneSpatialAnchor
ground_linear_spatial_preference(start_anchor, end_anchor, place_mappings, bundle, connects_hints=None) -> ZoneSpatialAnchor
```

### 数据流

```
PARSE Agent format_targets 阶段
    │ LLM 产出 ZoneTarget(spatial_preference="村北靠近刘村") + 可选 preselected_bsms
    ▼
spatial_ops.grounding.ground_zone_spatial_preference(...)
    ├── 提取方向 "北" → resolve_directional_bbox(ref_center, "north")
    ├── 地名匹配 → query_parcels_in_bbox / query_parcels_near_entity
    ├── query_excluded_parcels(constraint_index, parcels)  # 排除基本农田/生态红线等
    └── compute_proximity_weights(...)
    ▼
ZoneTarget 填充: candidate_bsms / candidate_bbox / excluded_bsms / proximity_weights
```

> ⚠️ **集成现状**：`grounding.py` 函数全部实现并导出，但**无在应用内的直接消费者**——PARSE agent 实际走 `resolve_spatial_anchors`（用 `kg.gazetteer`）+ `format_bound_intent.py` 的自动填充路径。grounding 作为独立可用的空间接地库保留。

---

## 七、职责 C: EXECUTE 空间桥接（bridge.py）

### SpatialIndex — 运行时空间索引

```python
build_spatial_index(bundle) -> Optional[SpatialIndex]   # 读 bundle.polygons["landuse_current"] → GDF + R-tree

class SpatialIndex:
    get_parcel_geometry(bsm) -> Optional[Dict]                    # BSM → GeoJSON geometry (EPSG:4326)
    get_parcel_attrs(bsm) -> Dict                                 # {dlbm, area_sqm, zone_type, ...}
    has_parcel(bsm) -> bool
    parcels_intersecting(geometry) -> List[OverlapResult]         # R-tree 搜索，按 overlap 面积降序
    parcels_within_bbox(bbox) -> List[Dict]
    parcels_within_distance(bsm, distance_m=200) -> List[Dict]    # 排除自身
    get_all_bsms() -> List[str]
    parcel_count -> int

@dataclass OverlapResult:
    bsm, dlbm, overlap_area_sqm, overlap_pct, parcel_total_area_sqm, zone_type
```

### ConstraintIndex — 约束重叠检查

```python
build_constraint_index(bundle) -> Optional[ConstraintIndex]
#   索引 6 组约束面：farmland_protection / ecological_redline / historical_protection /
#   cultivated_land_target / urban_dev_boundary / village_dev_boundary
#   _CONSTRAINT_META 映射 constraint_type → (label, rule)

class ConstraintIndex:
    parcel_in_constraint(bsm) -> List[ConstraintOverlap]
    geometry_in_constraint(geometry) -> List[ConstraintOverlap]

@dataclass ConstraintOverlap:
    bsm, constraint_type, constraint_label, rule, overlap_area_sqm, overlap_pct, parcel_total_area_sqm
```

### 跨层关系

```python
compute_water_overlap(water_polygons, landuse_parcels, dlbm_filter="3100") -> Dict[str, list]
compute_cross_layer_relations(bundle) -> Dict[str, list]   # {"located_in": [...], "intersects": [...], "contains": [...]}
#   消费方：KG builder（builder.py:120 调用 compute_cross_layer_relations）
```

---

## 八、职责 D: 约束编译（constraint_compiler.py）

```python
class ConstraintCompiler:
    def __init__(self, bundle=None)
    def compile(
        self,
        parse_constraints: Optional[List[SpatialConstraint]] = None,
        bundle=None,
        rule_config=None,
        feedback_constraints: Optional[List[CompiledConstraint]] = None,
    ) -> CompilationReport
    def get_stats(self) -> Dict[str, int]
```

**6 个约束来源**（`_stats` 追踪各自数量）：
`parse_input`（PARSE 解析）/ `three_line_input`（三线）/ `vne_input`（VNE 分区）/ `protected_input`（保护区）/ `rule_yaml_input`（YAML 规则）/ `feedback_input`（人类反馈）。

**冲突仲裁**（`_resolve_conflicts`）：按 `scope:zone:field` 分组 → hard 优先于 soft → 同组取最严格边界（`<=` 取最小 / `>=` 取最大）→ 生成 `ConflictRecord` + 移除被覆盖项。

---

## 九、职责 E: 地块几何操作（parcel_ops.py）

```python
reclassify_parcel(parcel, new_land_use_code, new_land_use_name="") -> Dict
    # -> {"bsm", "planning_land_use", "zone_type", "area_ha", "geometry"(JSON str),
    #     "derived_from_bsms", "derived_from_zone_target", "operation": "reclassify"}
modify_parcel(parcel, field_changes) -> Dict
merge_parcels(parcels, new_land_use_code="", new_bsm="") -> Optional[Dict]      # unary_union + buffer(0) 修复
split_parcel_by_ratio(parcel, ratio=0.5) -> List[Dict]                          # 沿长轴 bbox 切分
split_parcel_by_geometry(parcel, split_geometry) -> List[Dict]                  # shapely.ops.split
create_parcel(geometry, bsm, land_use_code="", area_ha=0.0) -> Dict
apply_operations(operations, current_parcels) -> Tuple[List[Dict], List[str]]   # EXECUTE 主入口
#   未变更地块按当前 DLBM 重分类并产生 warning
```

---

## 十、职责 F: 道路规划（road_planner.py）

```python
plan_roads(road_targets, current_roads, parcel_geometries=None) -> List[Dict[str, Any]]
#   preserve/upgrade/create 三种策略：
#   _find_matching_road  端点邻近启发式匹配既有道路
#   _generate_road_geometry  新道路生成为直线 LineString
```

消费方：EXECUTE agent `_execute_road_node`（`execute/agent.py`，`spatial_ops.road_planner` 为回退路径；主路径是 `app.services.modules.gis.road` 的 Stage 0-6）。

---

## 十一、职责 G: 用地平衡表（land_balance.py）

```python
compute_land_balance(current_parcels, planned_parcels, total_area_ha=0.0) -> LandBalanceTable
#   is_closed: |planned-current|/current ≤ 0.5%
#   3 类汇总：agriculture / construction / ecological

check_delivery_gate(
    current_parcels, planned_parcels,
    three_line_violations=0, protected_intrusions=0,
    changed_parcels_pct=0.0, zones_complete=True,
) -> DeliveryGate
```

辅助：`_get_attr` / `_code_to_name`（用 `DLBM_TO_DLMC` / `GHYTBM_TO_GHYTMC`）。

---

## 十二、依赖

- **内部**: `app.utils.logger`；`app.utils.geojson_utils.geojson_to_geodataframe`；`app.utils.area_engine.calculate_area_ha`；`app.utils.crs_engine`（project_to_metric / meters_to_degrees_*）；`app.utils.geo_utils`（haversine_distance / safe_unary_union）；`app.modules.schema.contracts.*`；`app.modules.schema.types.canonical.VillageBundle`；`app.modules.schema.encodings.code_sets`（get_planning_zone_from_landuse / normalize_landuse / GHYTBM_TO_VNE）；`app.modules.schema`（DLBM_TO_DLMC / get_dlbms_for_zone_type / get_zone_type_for_dlbm）
- **外部**: `geopandas>=0.14.0`、`shapely>=2.0.0`、`pyyaml`（`_load_place_aliases`）
- ⚠️ geopandas/shapely 在函数内**惰性导入**并有 `ImportError` 守卫——缺库时相关函数返回空结果而不是崩溃。

---

## 十三、测试覆盖

无独立 `test_spatial_ops/` 目录，覆盖分散在：
- `tests/unit/test_schema_promotion.py` — `test_spatial_ops_import` / `test_spatial_ops_submodules`
- `tests/unit/test_layer2_relations.py` — ParcelRelations 三数据类 + 喂给 KG `add_parcel_relations`
- `tests/unit/test_bridge_advisor.py` — `point_in_polygon` / `village_boundary_geometry`
- `tests/unit/test_parse_agent.py` — `_compute_centroid`
- 集成：`test_kg_jintian_e2e.py` / `test_village_cognition.py` / `test_spatial_ref_resolve.py` / `test_l4_provenance.py` / `test_golden_kg_snapshot.py` / `test_parse_agent_llm.py`

---

## 十四、相关文档

- `docs/_archive/gis-archive/00_SYSTEM_DESIGN_v4.8.md` - 系统总体设计（分层架构，已归档）
- `backend/app/agent/gis/parse/README.md` - PARSE Agent（grounding 的潜在消费者）
- `backend/app/agent/gis/execute/README.md` - EXECUTE Agent（bridge/parcel_ops/road_planner 的消费者）
- `backend/app/modules/kg/README.md` - KG 模块（消费 ParcelRelations / ContextBlock）
- `backend/app/modules/schema/contracts/parse_contracts.py` - PARSE 契约（含空间锚定字段）
