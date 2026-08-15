# KG 渲染结果 (Jintian 实际数据)

> 生成时间: 2026-07-25
> 数据源: `data/gis/jintian/` (金田村)
> 生成脚本: `backend/scripts/visualize_kg.py`（已随 dead-code 清理移除，本文档为历史快照）

---

## 一、KG 统计概览

| 指标 | 值 |
|------|-----|
| 总三元组数 | 21,253 |
| 地块数 (Parcel) | 660 |
| 道路数 (Road) | 175 |
| 设施数 (Facility) | 44 |
| 水域数 (WaterBody) | 44 |
| 自然村落数 (NaturalSettlement) | 19 |
| 分区数 (Zone) | 139 |
| VNE 分类数 (LandUseCategory) | 28 |
| 三区数 (ThreeZone) | 3 |
| 三线数 (ThreeLine) | 6 |
| 约束数 (Constraint) | 3 |
| L4 规划变更数 (PlannedParcel) | 3 (示例 PlanBlock) |

### 三层空间关系

| 层次 | 关系 | 三元组数 | 说明 |
|------|------|---------|------|
| L1 拓扑 | `pln:touches` | 1,549 | 共享边界的地块对 |
| L2 近邻 | `pln:nearby` | 4,195 | 质心距离 ≤ 200m 的地块对 |
| L3 路网 | `pln:connected_via_road` | 207 | 同一道路穿过的地块对 |

### 约束规则

| 约束 ID | 字段 | 操作符 | 值 | 来源 |
|---------|------|--------|-----|------|
| farmland_protection_protection | farmland_protection_area_ha | >= | 82.42 | context_block |
| ecological_protection_protection | ecological_protection_area_ha | >= | 371.77 | context_block |
| heritage_protection_protection | heritage_protection_area_ha | >= | 0.2 | context_block |

---

## 二、可视化文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `kg_architecture.svg` | Graphviz SVG | 四层架构图（L1 现状 + L2 约束 + L3 意图 + L4 PlanBlock），含实际实体计数 |
| `kg_sample_subgraph.svg` | Graphviz SVG | 样本子图：村庄 + 约束 + 5 个样本地块 + L4 增量变更 + derived_from 链接 |
| `kg_statistics.png` | matplotlib PNG | 左：实体分布柱状图；右：三层空间关系分布柱状图 |
| `kg_dlbm_distribution.png` | matplotlib PNG | Top 10 DLBM (地类编码) 分布饼图 |

---

## 三、数据流全景

```
data/gis/jintian/
├── current/
│   ├── boundary.geojson     ─┐
│   ├── landuse.geojson      ─┤  DataCatalog.load_village_bundle("jintian")
│   ├── road.geojson         ─┤  → VillageBundle (660 parcels, 131 roads, 34 annotations)
│   ├── annotation.geojson   ─┤
│   └── admin_boundary_line  ─┘
├── planned/
│   ├── landuse.geojson      ─┐
│   ├── road.geojson         ─┤  582 planned parcels, 170 planned roads
│   ├── farmland_protection  ─┤  88 farmland protection zones
│   ├── ecological_protection ┤  5 ecological redline zones
│   ├── historical_protection┤  3 heritage protection zones
│   ├── construction_zone    ─┤  139 construction zones
│   └── geological_hazard    ─┘  40 hazard points
└── project/
    └── ...

DataCatalog
    ↓ VillageBundle (typed)
`app/spatial/query/context.py::compute_context_blocks`
    → 8 ContextBlocks (VILLAGE_META, LANDUSE_DIST, NATURAL_VILLAGES, CONSTRAINTS, FACILITIES, ...)
`app/spatial/model/geometry.py::compute_parcel_relations`
    → ParcelRelations (1549 touches, 4195 nearby, 207 connected)
    ↓
PlanningKG.build_from_blocks(blocks, bundle, relations)
    → Layer 1: 660 parcels + 175 roads + 44 facilities + 19 settlements + ...
    → Layer 2: 3 constraints + 3 three_zones + 6 three_lines + 139 zones
    → Layer 3: (empty - no intent injected)
    → Layer 4: (empty - no plan_block injected)
    ↓
KG (21,216 triples) → clone_static_layer() → _apply_plan_block(PlanBlock)
    → Layer 4: 3 planned parcels (reclassify + split×2) + 1 facility + 1 road
    → 21,253 triples (delta: 37 triples for 3 changes)
```

---

## 四、PlanBlock 增量写入示例

```
                    KG Main (L1+L2 only)
                    21,216 triples
                    ┌──────────────────────────┐
                    │  Layer 1: 660 parcels    │
                    │  Layer 2: 3 constraints  │
                    │  Layer 3: (empty)        │
                    │  Layer 4: (empty)        │
                    └─────────────┬────────────┘
                                  │ clone_static_layer()
                                  ▼
                    KG Clone (L1+L2 copy)
                    ┌──────────────────────────┐
                    │  Layer 1: 660 parcels    │
                    │  Layer 2: 3 constraints  │
                    │  Layer 3: (empty)        │
                    │  Layer 4: (empty)        │
                    └─────────────┬────────────┘
                                  │ _apply_plan_block(PlanBlock v1)
                                  │   3 parcel_changes:
                                  │     reclassify (1 parcel)
                                  │     split (1→2, new bsms)
                                  │     merge (2→1, new bsm)
                                  ▼
                    KG with Plan (L1+L2+L4 delta)
                    ┌──────────────────────────┐
                    │  Layer 1: 660 parcels    │  ← unchanged
                    │  Layer 2: 3 constraints  │  ← unchanged
                    │  Layer 3: (empty)        │  ← unchanged
                    │  Layer 4: 3 PlannedParcel│  ← sparse (37 triples)
                    │    + derived_from links  │
                    └──────────────────────────┘
                    
                    Total: 21,253 triples (+37 = 0.17% growth)
                    
                    对比旧 PlannedState 全量镜像:
                    660 × 5 fields × 2 (type+value) = ~6,600 triples (+31% growth)
```

---

## 五、查询验证

### L1 查询：地块计数
```sparql
SELECT ?bsm ?dlbm ?area WHERE {
  ?p a pln:Parcel ; pln:bsm ?bsm ; pln:dlbm ?dlbm ; pln:area_ha ?area .
} LIMIT 5
```
结果：660 个地块，样例 BSM=441426211000049104, DLBM=3100, area=0.141ha

### L2 查询：约束规则
```sparql
SELECT ?id ?field ?op ?value WHERE {
  ?c a pln:Constraint ; pln:constraint_id ?id ;
     pln:field ?field ; pln:operator ?op ; pln:value ?value .
}
```
结果：3 条约束（farmland >= 82.42ha, ecological >= 371.77ha, heritage >= 0.2ha）

### L3 查询：路网连通
```python
kg.get_connected_parcels("http://village-planning.org/ontology#parcel_441426211000049104_3100_1411")
→ ["441426211000049105", "441426211000049106", ...]
```

### L4 查询：effective_land_use (L1+L4 merge)
```python
# 未变更地块：回退 L1
kg.get_effective_land_use("441426211000049104", "v1")
→ "3100"  # L1 dlbm

# 变更地块：返回 L4
kg.get_effective_land_use("441426211000055682", "v1")
→ "2121"  # L4 planning_land_use (reclassified)
```
