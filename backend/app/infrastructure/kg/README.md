# Planning Knowledge Graph (KG) 模块

> 村庄规划系统的**空间语义引擎**
> **层级**: `Schema ← Data ← SpatialOps ← KG ← Agent`
> **v5.0** - KGBuilder composition + GeoSPARQL alignment + SemanticMemoryStore for relation attributes

---

## 一、架构设计

### 1.1 核心原则

1. **KG 只存空间实体及其关系**。几何计算由 `spatial_ops` 完成，KG 只存结果。
2. **RDF 图存纯关系，量化细节存 SemanticMemoryStore**。三元组本身不携带 `shared_boundary_length` 等数值属性。
3. **GeoSPARQL 空间谓词**。邻接/包含/相交关系用 `geo:sfTouches`/`sfWithin`/`sfIntersects`。
4. **四层结构**：L1 现状实体 → L2 空间关系 → L3 意图虚拟实体 → L4 规划成果。

### 1.2 组件关系

```
VillageBundle
  │
  ├── compute_parcel_relations()  →  ParcelRelations  ──→ KGBuilder.build(L2)
  ├── build_constraint_index()    →  ConstraintIndex   ──→ KGBuilder.build(L1 约束检查)
  ├── compute_cross_layer_relations() ──→ cross_type_relations ──→ KGBuilder.build(L2 跨类型)
  │
  └── KGBuilder.build(village_name, bundle,
                      parcel_relations=...,
                      constraint_index=...,
                      intent=...,          # optional → L3
                      planned_state=...)   # optional → L4
```

### 1.3 数据边界

| 模块 | 职责 |
| --- | --- |
| `spatial_ops` | 几何运算 / 空间索引 / 关系计算 / 聚类 |
| `KG` | BSM 标识 / 空间关系 / 语义层 / 图层组 / L3 意图 / L4 成果 |
| `SemanticMemoryStore` | 关系量化属性（shared_boundary_m, centroid_distance_m 等） |

---

## 二、PlanningKG 和 KGBuilder

### 2.1 PlanningKG（数据容器）

```python
class PlanningKG:
    g: Graph                          # RDF 图
    memory: SemanticMemoryStore       # 关系量化属性
    _parcel_count: int
    _constraint_index: ConstraintIndex

    # 查询方法
    def query(self, sparql) -> List[Dict]: ...
    def get_triple_count(self) -> int: ...
    def to_turtle(self) -> str: ...
    def get_adjacency_map(self) -> Dict[str, set]: ...
    def clone_static_layer(self) -> "PlanningKG": ...
```

### 2.2 KGBuilder（构建器）

```python
class KGBuilder:
    def __init__(self, village_name: str): ...
    def build_from_bundle(self, bundle, parcel_relations=None, intent=None,
                          planned_state=None, constraint_index=None,
                          water_overlap=None, cross_type_relations=None) -> PlanningKG: ...
    @classmethod
    def build(cls, village_name: str, bundle, **kwargs) -> PlanningKG: ...
```

**使用方式**：
```python
from app.modules.kg.builder import KGBuilder

kg = KGBuilder.build(
    "jintian", bundle,
    parcel_relations=relations,
    constraint_index=constraint_index,
)
```

---

## 三、四层结构

### 3.1 Layer 1：现状实体

实体类型和标识键：

| 实体 | RDF 类型 | 标识 |
| --- | --- | --- |
| `Parcel` | `pln:Parcel` | `pln:bsm` literal |
| `Road` | `pln:Road` | `pln:bsm` literal |
| `WaterBody` | `pln:WaterBody` | `pln:bsm` literal |
| `Facility` | `pln:Facility` | `pln:bsm` literal |
| `Zone` | `pln:Zone` | `pln:bsm` literal |
| `ResidentialCluster` | `pln:ResidentialCluster` | `pln:name` |
| `AdministrativeVillage` | `pln:AdministrativeVillage` | singleton `pln:village` |

**属性存储**：
- 事实型：`pln:dlbm`, `pln:sddlbm`（确定性）
- 推荐型：`pln:planning_zone`, `pln:primary_zone`（来自编码体系）
- 几何：`geo:hasCentroid` + `geo:asWKT "POINT(...)"`（质心）
- 包围盒：`geo:hasBoundingBox` + `geo:asWKT "POLYGON((...))"`

### 3.2 Layer 2：空间关系

| 关系 | 方向 | 量化属性 |
| --- | --- | --- |
| `geo:sfTouches` | 双向 | `shared_boundary_m` → SemanticMemoryStore |
| `pln:nearby` | 双向 | `centroid_distance_m` → SemanticMemoryStore |
| `pln:connected_via_road` | 双向 | `road_segment_m`, `via_road` → SemanticMemoryStore |
| `geo:sfWithin` | 单向 | — |
| `geo:sfIntersects` | 单向 | `overlap_pct` → SemanticMemoryStore |
| `geo:sfContains` | 单向 | — |

### 3.3 Layer 3：意图虚拟实体（易失）

通过 `build_intent_layer(kg, intent)` 写入，会话结束时 `clear_intent_layer(kg)` 清除。

| 实体 | 锚定属性 |
| --- | --- |
| `ZoneTarget` | `candidate_bsm`, `excluded_bsm`, `candidate_bbox`, `spatial_hint` |
| `FacilityTarget` | `candidate_bsm`, `anchor_point`, `spatial_hint` |
| `AxisTarget` | `start_anchor`, `end_anchor`, `corridor_bsms` |
| `RoadTarget` | `start_anchor`, `end_anchor`, `path_bsms` |

### 3.4 Layer 4：规划成果（版本化）

通过 `apply_planned_state(kg, planned_state)` 写入。

| 实体 | 版本标签 | 可追溯 |
| --- | --- | --- |
| `PlannedParcel` | `pln:in_version` | `pln:derived_from` → L1 |
| `PlannedZone` | `pln:in_version` | `pln:derived_from_target` → L3 |
| `PlannedFacility` | `pln:in_version` | `pln:derived_from_target` → L3 |
| `PlannedRoad` | `pln:in_version` | `pln:derived_from_target` → L3 |
| `PlannedAxis` | `pln:in_version` | `pln:derived_from_target` → L3 |

**稀疏写入**：未变更的地块不写入 L4，查询时回退到 L1。

---

## 四、GeoSPARQL 对齐（v5.0）

实体统一类型化为 `geo:Feature`。几何以 WKT 存储：

```python
# 质心 → geo:hasCentroid + geo:asWKT
add_centroid(kg.g, parcel_uri, centroid_lon, centroid_lat)
# → geo:hasCentroid → geo:asWKT "POINT(113.5 23.2)"

# 包围盒 → geo:hasBoundingBox + geo:asWKT
add_bbox(kg.g, parcel_uri, minx, miny, maxx, maxy)
# → geo:hasBoundingBox → geo:asWKT "POLYGON((minx miny, maxx miny, ...))"
```

WKT 格式/解析工具在 `builder/geo_helpers.py`：
```python
wkt_centroid(lon, lat) -> str          # "POINT(lon lat)"
wkt_bbox_polygon(bbox) -> str          # "POLYGON((minx miny, maxx miny, ...))"
parse_wkt_point(wkt) -> (lon, lat)
parse_wkt_bbox(wkt) -> (minx, miny, maxx, maxy)
```

---

## 五、SemanticMemoryStore（v5.0）

关系量化属性存 SemanticMemoryStore，不存 RDF 三元组：

```python
kg.memory.add_relation_annotation(RelationAnnotation(
    subject_uri=str(a),
    predicate=str(Relations.sfTouches),
    object_uri=str(b),
    description="",
    derived_from="spatial_ops_computed",
    quantitative_detail={"shared_boundary_m": 45.2},
))
```

查询时从 memory 取出：
```python
rel_ann = kg.memory.get_relation_annotation(subj, pred, obj)
length = rel_ann.quantitative_detail.get("shared_boundary_m")
```

---

## 六、@kg_builder 注册机制

新实体类型通过 `@kg_builder` 装饰器注册：

```python
@kg_builder("landuse_current", entity_type="Parcel", layer=1, order=10)
def _add_parcels(kg, features, *, gtype_ref, entry, ctx):
    for f in features:
        # 构建逻辑
        pass
    return {"count": len(features)}
```

`KGBuilder._build_entities()` 按 `layer` → `order` 顺序调用所有注册函数。

---

## 七、目录结构

```
backend/app/modules/kg/
├── __init__.py           # 公开 API
├── ontology.py           # 本体：EntityTypes, Relations, GeoPredicates, SemanticPredicates
├── memory.py             # SemanticMemoryStore
├── manager.py            # KGManager 单例（Layer 1 缓存）
├── builder/
│   ├── __init__.py       # 导出 PlanningKG, KGBuilder, kg_builder
│   ├── base.py           # PlanningKG 数据容器
│   ├── builder.py        # KGBuilder 编排器
│   ├── registry.py       # @kg_builder 装饰器, BuilderSpec, BuildContext
│   ├── enrichment.py     # add_gis_layer_groups, add_semantic_enrichment
│   ├── geo_helpers.py    # WKT centroid/bbox helpers
│   ├── layer1_core.py    # 12 个 L1 builders（parcels, roads, water, facilities...）
│   ├── layer1_extended.py # 6 个 L1 builders（protection, boundaries, terrain...）
│   ├── layer2.py         # add_parcel_relations, add_cross_type_relations
│   ├── layer3.py         # build_intent_layer, clear_intent_layer
│   └── layer4.py         # apply_planned_state, PlannedState dataclasses
└── queries/
    ├── __init__.py       # 导出所有查询函数 + 四命名空间 API
    ├── sparql.py         # 30+ SPARQL 模板, query_kg()
    ├── semantic.py       # LLM 友好语义查询
    ├── cognition.py      # get_village_cognition 三层认知摘要
    └── contracts.py      # DualPayload, TokenBudget, TopKSampler
```

---

## 八、使用示例

```python
from app.modules.kg.builder import KGBuilder
from app.modules.kg.builder.layer3 import build_intent_layer
from app.modules.kg.builder.layer4 import apply_planned_state
from app.modules.kg.queries.sparql import (
    check_constraint_violations, compare_versions,
    get_effective_land_use, get_plan_changes,
)

# 构建 KG（L1 + L2）
kg = KGBuilder.build(
    "jintian", bundle,
    parcel_relations=relations,
    constraint_index=constraint_index,
)

# L3 意图（易失）
build_intent_layer(kg, intent)

# L4 规划成果
apply_planned_state(kg, planned_state)

# 查询
violations = check_constraint_violations(kg, "v1")
diff = compare_versions(kg, "v1", "v2")
changes = get_plan_changes(kg, "v1")
effective = get_effective_land_use(kg, "BSM001", "v1")
```
