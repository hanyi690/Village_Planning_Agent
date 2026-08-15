# KG 可扩展性与空间关系物化策略
## —— O(n) SRE+Topology 替换 O(n²) 全量物化

> 状态:提案(已定稿) | 日期:2026-07-29
> 关联:`KG_SPATIAL_COGNITION_DESIGN.md`(§五 8 关系)、`spatial_ops/bridge.py`(关系计算实现)
> 关键变更:引入 SRE+Topology 模式,`nearby` 从"不物化+双击查询"升级为"物化 cell 索引+SPARQL graph pattern 候选+spatial_ops 精筛"。**不全量物化 pairwise 关系。**

---

## 0. 结论先行

**"所有几何图层入库"不会崩(实体 O(n),~30 triples/实体,村庄级安全)。"每对 parcel 算 nearby"会崩(O(n²))——本方案严格禁止全量物化 pairwise 关系。** 取而代之的是**三模式物化策略**:直接物化(O(n×avg_neighbors))用于有界关系(touches/located_in);**SRE+Topology(O(n))** 用于近邻查询(nearby);按需查询(O(0)存储)用于距离/buffer 临时运算。`nearby` 不进 KG,但 KG 物化 parcel→cell 的 SRE 索引,O(1) SPARQL 出候选,spatial_ops R-tree 做精筛。

---

## 1. 现状量化(金田村,中等村庄)

来源:`KG_SPATIAL_COGNITION_DESIGN.md` §十一/§十三 + `bridge.py` 实查

| 项 | 数量 | 备注 |
|---|---|---|
| 入库实体 | ~1318(660 parcel + 131 road + 48 water + 60 facility + 88+5+3+139 各类 zone + 40 hazard + 144 admin) | 几何图层全入库,实体数 O(n),可控 |
| 三元组 | 39,566 | ~30 triples/实体,主要是属性+语义层 |
| KG 构建 | ~50s,缓存 1.2MB | RDFLib 内存图 |
| 物化的 L2 关系 | located_in 1385 + intersects + contains | O(n×avg_neighbors),有界 |
| **未物化**的 nearby | `parcels_within_distance(bsm, 200m)` per-BSM 按需 | 现状正确,但查询是 per-BSM R-tree(O(log n)),批量场景需优化 |

**大村庄/镇域规模参考**:

| 规模 | parcel | 实体 | 三元组 | 构建 | RDFLib SPARQL |
|---|---|---|---|---|---|
| 金田(现) | 660 | 1318 | 39k | 50s | <100ms ✅ |
| 大村 | 3000 | 6000 | 180k | ~4min | 200-500ms ⚠️ |
| 镇域 | 6600 | 13000 | 390k | ~8min | 1-3s ⚠️⚠️ |
| 县域 | 50000 | 100000 | 3M | 不适用 | 不可用 ❌ |

RDFLib 内存图在 50 万 triple 以下可用,百万级需 triplestore。**村庄级安全,镇域边界,县域必须换引擎或分图。**

---

## 2. 关系物化三模式(替换旧"物化 vs 不物化"二分)

| 模式 | 机制 | 三元组增长 | 适用 |
|---|---|---|---|
| **直接物化** | feature↔feature 三元组,建在 L2 | O(n×avg_neighbors) | touches/located_in(1:1)/contains/intersects/connected_via_road/derived_from/serves |
| **SRE+Topology**(新增) | feature→cell(S2 L13 或 admin_area)三元组;查询时两 feature 共享 cell→候选集;spatial_ops 精筛 | **O(n)** | nearby(替换 per-BSM R-tree 模式) |
| **按需查询** | 不进 KG,spatial_ops R-tree + GeoSPARQL-Jena TTL 缓存(可选) | 0 | 距离/buffer 临时查询、任意半径 |

**核心变化**:旧版将 nearby 归为"按需查询",每查 per-BSM R-tree(O(log n))。新版用 SRE 物化 O(n) cell 索引,查询改为"SPARQL graph pattern(O(1))→候选→spatial_ops 精筛",批量 nearby 场景性能显著提升。

### 2.1 SRE+Topology 原理

```
物化: ?parcel pln:located_in_cell ?cell
      ?cell a pln:S2Cell ; pln:cell_level 13 ; pln:cell_id "xxx"

nearby 查询: "parcel A 的 200m 邻居"
  1. SPARQL: ?cell = A 的 located_in_cell; ?neighbor located_in_cell ?cell(or adjacent cell)
  2. spatial_ops: 精筛 ?neighbor 中 centroid 距离 ≤200m 的(排除 false-positive)
     复杂度: O(1) SPARQL + O(avg_cell_density ≈ 3-10 parcels) 精筛
```

S2 L13 cell 面积 ≈ 1.3km²,金田村 2352ha ≈ 23.5km² → 约 18 个 cells,每个 cell 平均 37 parcel。每 parcel 1-3 个 cells → **660 parcels × 1.5 cells = ~990 triples(O(n))**,而非 O(n²) 的 217k pairwise。

**村级优化**:金田村只有 1 个行政村 admin_area,直接物化 `?parcel pln:located_in ?admin_area`(已有,660 triples)。nearby 查询 = "同一 admin_area 内"→候选 660→spatial_ops R-tree 精筛。**村级用 admin_area 作 SRE 比 S2 L13 更省**(660 triples vs 990,且无需 cell 划分)。

### 2.2 SRE 级联选择(从细到粗)

| SRE 类型 | 适用 | 三元组/parcel | 筛选率 |
|---|---|---|---|
| admin_area(村级) | 单村 | 1 | 0%→100%(全候选) |
| S2 L13(~1.3km²) | 镇域/多村 | 1.5 | ~6%(18 个 cell 选 1) |
| S2 L11(~10km²) | 县域/粗筛 | 1.1 | ~1% |

构建时按 parcel 数自动选择:≤1000→admin_area;>1000→S2 L13。**村庄级 = admin_area,最省**。

---

## 3. 几何类型对物化矩阵(替换旧关系表)

按 geometry-type pair + 语义组定义,基于 YAML registry 13 个 group(~30 个 layer type)归并:

| 几何对 | 物化策略 | 复杂度 | 示例 |
|---|---|---|---|
| polygon↔polygon(同语义组) | 直接物化 **touches** | O(6n) | parcel↔parcel(current_landuse) |
| polygon↔polygon(跨语义组) | 直接物化 **intersects+contains**,带 overlap_pct | O(zones×parcels) | parcel↔farmland_protection |
| point↔polygon | 直接物化 **located_in**(严格 1:1 point-in-poly) | O(points) | facility↔parcel |
| line↔polygon | 直接物化 **intersects**(sjoin bbox 预筛) | O(稀疏) | road↔protection_zone |
| polygon↔polygon(任意距离/近邻) | **SRE+Topology** 物化 located_in_cell | **O(n)** | parcel↔parcel nearby(经 cell) |
| point↔point / line↔line 距离 | **不物化,按需** | O(n²) 存储不可接受 | facility↔facility 距离 |
| L4↔L1 溯源 | 直接物化 **derived_from**(delta-only) | O(L4 实体) | PlannedParcel↔Parcel |
| 设施↔居民点 | 直接物化 **serves** | O(facility×cluster) | facility↔cluster |

**关键规则**:
1. 语义组内同型做 touches;跨语义组同型做 intersects;距离类全部走 SRE 或 on-demand
2. **绝不裸 double-loop**——所有 pairwise 几何判定必须经 GeoPandas `sjoin`(libspatialindex R-tree)或显式 R-tree 预筛
3. SRE 是否用 admin_area vs S2 取决于村庄规模(§2.2)

---

## 4. SRE 选择与索引落地

### 4.1 SRE 候选:admin_area(村)>> S2 L13(镇域+)

- **村庄级(<1000 parcel)**:直接用 admin_area 作 SRE。金田村 1 个行政村 → 660 条 `located_in` 三元组(已有,无需新增)。nearby 候选 = 同一 admin_area 内全量(660),spatial_ops R-tree 精筛。
- **镇域(1000-5000 parcel)**:S2 L13(~1.3km²)。每 parcel 平均 1.5 个 cells → O(n) triples。nearby 候选 = SPARQL 共享 cell 的子集(约 37 parcels/cell)。
- **县域(>5000 parcel)**:S2 L11(~10km²)粗筛 + L13 精筛两级,或迁移 Jena triplestore。

### 4.2 物化三元组

```
# admin_area 方案(村庄级)
?parcel pln:located_in ?admin_area   # 已有,复用
?admin_area a pln:AdministrativeVillage

# S2 L13 方案(镇域+)
?parcel pln:located_in_cell ?cell
?cell a pln:S2Cell ; pln:cell_level 13 ; pln:cell_id "4d7c1a3"
```

S2 cell adjacency(8-邻居)经 `s2sphere` 库预计算,加载为 SPARQL property path:
```
?neighbor located_in_cell ?c2 . ?c2 pln:adjacent_cell ?cell .
```

### 4.3 索引

- 现有 `SpatialIndex`(bridge.py)加 `parcels_in_cell(cell_id)`→BSM 列表
- 复用 GeoPandas `sindex` 按 cell bbox 查,无额外依赖
- L4 delta-only:SRE 关系随 parcel 变更增量更新(`derived_from` 涉及的新 Parcel 重算 cell),不重算全量

### 4.4 大多边形 simplify + ST_Dump

部分保护面(生态红线等)为大多边形(含多环),物化前:
- Douglas-Peucker simplify(容差 5m,金田村 1:2000 底图)降顶点数
- ST_Dump 拆 MultiPolygon → 单 Polygon,每片独立入 KG(避免单实体含几百个孔)

---

## 5. 落地清单

| # | 改动 | 文件 | 说明 |
|---|---|---|---|
| 1 | 审计 located_in 严格 1:1 point-in-poly(1385→~60) | bridge.py L658 | 当前疑似按服务半径多对多,修 strict 1:1 |
| 2 | 引入 SRE+Topology:物化 parcel→cell/admin 三元组(村庄级用 admin_area,已有) | kg/builder/layer1.py 新增 `_add_sre_relations` | 仅在非 admin_area 模式时新增 cell triples |
| 3 | nearby 改为两阶段:SPARQL 候选(cell 共享)+ spatial_ops 精筛 | spatial_ops/bridge.py `parcels_within_distance` 改写 | 查询入口不变,底层从 per-BSM R-tree 改 SPARQL+R-tree |
| 4 | 几何类型对物化矩阵文档化 + 强制 sjoin 消除裸 double-loop | bridge.py L690 + 本文档 §3 | 所有 pairwise 经 sjoin/rtree,静态检查禁止裸双循环 |
| 5 | L4 delta-only SRE 增量 | kg/builder/layer4.py | derived_from parcel 重算 cell,其余复用 L1 基线 |
| 6 | 大多边形 simplify + ST_Dump | spatial_ops/geometry.py 工具函数 | DG 5m 容差+s2sphere dump |

**不在本期做的**:不实现 SRE+Topology 代码(仅策略设计,代码后续 task);L4 builder 不动(仅文档策略)。

---

## 6. 图层系统考量

YAML registry 13 个 group 中,物化关系的覆盖范围:

| 图层组 | 跨组关系物化? | 原因 |
|---|---|---|
| current_landuse(parcel) | ✅ | 所有关系核心,必须物化 |
| protection(zones:农田/生态/历史/边界/灾害) | ✅ | 约束面,与 parcel 的 intersects 是 validator 输入 |
| facility(points) | ✅ | located_in(1:1)+serves |
| transport(roads) | ✅ | intersects 保护面 + connected_via_road |
| planned_output(L4) | ✅ derived_from 仅 | delta-only,不重算 L2 |
| natural_resource(soil/watershed/hydrogeology) | ❌ 按需 | 与规划决策无直接因果,物化价值低 |
| terrain(contour/elevation) | ❌ 按需 | 几何量大,仅在分析时用 |
| water | ✅ intersects parcel | 水系与地块关系参与洪涝/生态分析 |
| admin | ✅ | 已作 SRE |

**默认不物化**的图层按需查询,不产生额外三元组。新增图层时按 §3 几何对矩阵决定物化策略,不自动全部入关系。

---

## 7. 一句话总结

"不全量建立空间关系"——对。O(n) 的直接物化(touches/located_in/contains/intersects)保留;O(n²) 的 nearby/距离类走 **SRE+Topology(O(n) cell 索引 + O(1) SPARQL 候选 + R-tree 精筛)**,**绝不禁 pairwise,但物化代价从 O(n²)→O(n)**。村庄级直接复用已有 admin_area 作 SRE(零额外三元组);镇域+换 S2 L13;县域换引擎。几何对矩阵确保每对 layer type 有明确物化策略,不自动全员入关系。
