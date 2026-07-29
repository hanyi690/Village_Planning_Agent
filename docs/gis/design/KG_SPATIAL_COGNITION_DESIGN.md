# KG 空间认知设计文档 v4.8.1

> 最后更新: 2026-07-27
> 状态: **P0 + P1-13/14/9 完成，v4.9 GeoSPARQL 对齐完成**，P1-16/17/18 (PARSE) 待后续

---

## 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v4.8 | 2026-07-27 | 初始：三维度谓词+LayerGroup+语义层+DualPayload+四命名空间 |
| v4.8.1 | 2026-07-27 | 精简：关系 15→8（within→located_in, crosses+overlaps→intersects, bounds→contains），LAYER_GROUP_REGISTRY 删除（YAML 动态读取），谓词归类 SemanticPredicates 类 |
| v4.8.1a | 2026-07-27 | P1-13: analysis 修 3 bug（DataPipeline/工具名/L3闭环），P1-14: _optimize_semantics（KG 查询补充+候选集标注），P1-9: ContextBlock 4 修复（CJK token/explore注入/ConstraintZoneAnchor/聚类缓存） |

---

## 一、定位

PlanningKG 是村庄规划系统的**空间语义引擎**，为 LLM 提供两种类型的能力：

1. **语义化认知**：三层认知摘要（村概览/图层卡/约束简报），供 analysis/PARSE 消费
2. **结构化数据**：BSM 列表/bbox/geometry_kind 索引，供 EXECUTE 工具消费

---

## 二、数据边界（硬约束）

```
spatial_ops（几何权威）:
  全几何运算 / 空间索引 / 几何变更 / 约束面交集 / 聚类方向邻近
  无状态函数，输入 bundle，输出结构化结果

KG（语义权威）:
  BSM+派生属性 / 空间关系 / 语义层 / 图层组虚拟实体 / L3意图 / L4成果
  绝不存全几何，仅存 WKT（L4 显式设置时）

ContextBlock（组合输出）:
  几何部分 ← spatial_ops 计算
  语义聚合部分 ← KG 查询
  二者组合，不重复，不跨边界
```

---

## 三、四层架构

| 层 | 内容                                 | 生命周期 | 写入者           | 消费者                 |
| -- | ------------------------------------ | -------- | ---------------- | ---------------------- |
| L1 | 现状空间实体 + 三维度谓词 + 属性编码 | 持久     | bundle 直连      | SPARQL、PARSE、EXECUTE |
| L2 | 空间关系（parcel-parcel + 跨类型）   | 持久     | spatial_ops 计算 | SPARQL、EXECUTE        |
| L3 | 意图虚拟实体（粗糙几何）             | 会话易失 | PARSE            | EXECUTE                |
| L4 | 规划成果（版本化增量）               | 会话持久 | EXECUTE          | 导出、对比、校验       |

---

## 四、实体类型（18 个）

| 层 | 类型                                                                  | 说明                     |
| -- | --------------------------------------------------------------------- | ------------------------ |
| L1 | Parcel, Zone, Village, Facility, Road, WaterBody                      | 空间实体                 |
| L1 | AdministrativeVillage, ResidentialCluster                             | 管理/聚落实体            |
| L1 | GisLayerSet                                                           | 虚拟聚合节点（不含几何） |
| L3 | ZoneTarget, FacilityTarget, AxisTarget, RoadTarget                    | 意图虚拟实体             |
| L4 | PlannedParcel, PlannedZone, PlannedFacility, PlannedRoad, PlannedAxis | 规划成果                 |

---

## 五、关系（8 个，v4.9 GeoSPARQL 对齐）

| 关系 (谓词 URI)                 | 语义     | 说明                                                 |
| ------------------------------ | -------- | ---------------------------------------------------- |
| `geo:sfTouches`              | 拓扑邻接 | parcel-parcel 共享边界（v4.9: 原 `touches`）        |
| `pln:nearby`                 | 近邻关系 | 质心距离≤200m                                       |
| `pln:connected_via_road`     | 道路连通 | 同一道路穿越两个地块                                 |
| `geo:sfWithin`               | 空间包含 | 点/线位于面内（v4.9: 原 `located_in`，facility-in-parcel） |
| `geo:sfIntersects`           | 空间相交 | 线穿面/面叠面（v4.9: 原 `intersects`，合并 crosses+overlaps） |
| `geo:sfContains`             | 面包含   | 大面包含小面（v4.9: 原 `contains`，boundary-contains-parcel） |
| `pln:derived_from`           | 规划溯源 | L4->L1 变更链                                        |
| `pln:serves`                 | 服务关系 | 设施->居民                                           |

> **v4.9 命名变更**：`Relations` 类（`ontology.py:164-196`）将 4 个空间谓词
> 对齐到 GeoSPARQL 标准 URI。消费者写 SPARQL 时须用 `geo:sfTouches` 而非
> `pln:touches`。`ontology.py` docstring 与 `deep_cognition.py` 已同步（见 Task 3）。

---

## 六、三维度谓词（SemanticPredicates 类）

每个 L1 实体在构建时携带：

```
pln:layer_type        ← layer_registry.yaml key (如 "landuse_current")
pln:geometry_kind     ← "polygon" | "line" | "point"
pln:semantic_group    ← 语义分组 (如 "current_landuse", "transport")
pln:has_semantic_label ← 从 DLBM 派生的中文标签 (如 0101→"水田")
```

---

## 七、语义层（实体类型级）

从 `encodings/dicts/rules/*.yaml` 自动派生：

| 谓词                       | 来源                                                    | 示例                             |
| -------------------------- | ------------------------------------------------------- | -------------------------------- |
| `pln:taxonomic_parent`   | appendix5 zone_type                                     | 水田→耕地→农业用地             |
| `pln:legal_constraint`   | construction_zone_codes + planning_zone_to_control_code | 农田保护区→forbid_construction  |
| `pln:allowed_operations` | allowed_operations.yaml（手工）                         | 宅基地→[split,merge,reclassify] |

查询入口：`get_entity_semantics(kg, entity_label="水田")`

---

## 八、GisLayerSet 虚拟实体

```
pln:LayerGroup_current_landuse a pln:LayerGroup ;
  pln:semantic_group "current_landuse" ;
  pln:geometry_kind "polygon" ;
  pln:layer_description "基期现状地类" ;
  pln:layer_description_enriched "..." ;
  pln:layer_entity_count 660 ;
  pln:dominant_label "耕地" ;
  pln:contains_entity pln:Parcel_P001, ... .

图层组元数据从 layer_registry.yaml 动态读取（不硬编码）。
```

---

## 九、DualPayload 双返回

所有认知查询返回 `DualPayload(semantic, structured, token_estimate, truncated, next_cursor)`：

- **semantic**：三层认知摘要
  - `context_block`：村域概览（2-3句定位+面积+空间格局）
  - `layer_cards[]`：图层组卡片（几何类型/数量/主导标签/分布）
  - `constraint_block`：邻接总数/跨图层叠加/约束覆盖率
- **structured**：BSM 列表/bbox/geometry_kind 索引/代表 BSM/分页游标
- **Token 预算**：CJK 感知（len/1.5），软限 4000/硬限 6000
- **TopK**：混合规则抽样（分层+空间网格+异常值），不用嵌入向量

---

## 十、四命名空间查询 API

| 命名空间             | 消费者   | 粒度 | 返回偏好   | 写 KG  | 状态           |
| -------------------- | -------- | ---- | ---------- | ------ | -------------- |
| `analysis_queries` | analysis | 粗   | semantic   | 否     | 可用           |
| `parse_queries`    | PARSE    | 细   | structured | 是(L3) | 可用           |
| `execute_queries`  | EXECUTE  | 中   | structured | 是(L4) | **预留** |
| `shared_queries`   | 跨阶段   | -    | -          | 否     | 可用           |

---

## 十一、Bundle 几何覆盖（v4.8.1 补全）

| 图层组                | 实体类型    | 数量(金田) | 是否进 KG              |
| --------------------- | ----------- | ---------- | ---------------------- |
| current_landuse       | Parcel      | 660        | ✅                     |
| road_current          | Road        | 131        | ✅                     |
| water                 | WaterBody   | 48         | ✅                     |
| facility_current      | Facility    | 60         | ✅                     |
| farmland_protection   | Zone        | 88         | ✅ v4.8.1 新增         |
| ecological_redline    | Zone        | 5          | ✅ v4.8.1 新增         |
| historical_protection | Zone        | 3          | ✅ v4.8.1 新增         |
| hazard_points         | ControlLine | 40         | ✅ v4.8.1 补三维度     |
| construction_zone     | Zone        | 139        | ✅ v4.8.1 补三维度     |
| admin_boundaries      | Road        | 144        | ✅ v4.8.1 新增         |
| contour_lines         | Road        | 0          | ✅ v4.8.1 新增(无数据) |
| buildings             | Facility    | 0          | ✅ v4.8.1 新增(无数据) |

---

## 十二、跨类型空间关系（v4.9 已实现）

| 关系                            | 实现方式                     | 金田村数量（金标准快照） |
| ------------------------------- | ---------------------------- | ----------------------- |
| facility `sfWithin` parcel    | `compute_cross_layer_relations` 质心邻近 | 含于 sfWithin 总数 932 |
| road `sfIntersects` parcel    | `compute_cross_layer_relations` 几何相交 | sfIntersects 总数 564  |
| parcel `sfIntersects` protection | `compute_cross_layer_relations` 几何相交 | 同上                   |
| boundary `sfContains` parcel  | `compute_cross_layer_relations` 几何包含 | sfContains = 0（金田数据未触发，已知缺口） |

> 跨类型关系由 `spatial_ops.bridge.compute_cross_layer_relations(bundle)` 预计算，
> `layer1.py:_add_cross_type_relations` 物化为 `sfWithin/sfIntersects/sfContains` 三元组。
> v4.8.1 标注的"待 spatial_ops 实现"已全部完成。

---

## 十三、验证结果

测试文件：`backend/tests/integration/test_village_cognition.py`（7 项断言），
`backend/tests/integration/test_kg_jintian_e2e.py`（L1/L3/L4 端到端），
`backend/tests/integration/test_golden_kg_snapshot.py`（金标准回归），
`backend/tests/unit/test_dualpayload_contract.py`（DualPayload 契约）。

```
金标准快照 (jintian_kg_snapshot.ttl):
  parcels: 660
  triples: 47226
  sfTouches: 643   (parcel-parcel 邻接)
  sfWithin:  932   (含 facility-in-parcel + parcel-in-village)
  sfIntersects: 564 (road-crosses-parcel + parcel-overlaps-protection)
  sfContains: 0    (boundary-contains-parcel，金田数据未触发)
  hasGeometry/asWKT: 0  (VKG 决策：无全几何)

KG 构建: 660 parcels, 47226 triples
KG 缓存: scripts/.kg_cache/jintian.ttl (<1s 加载)
```

> 注：v4.8.1 文档列出的 `scripts/test_village_cognition.py` 路径有误，实际测试
> 位于 `backend/tests/integration/test_village_cognition.py`（Task 7 新建）。
> "763 tokens" 为 v4.8.1 时点值，实际 token_estimate 随语义层扩展而变化，
> 测试用 `0 < token_estimate <= TokenBudget.HARD_LIMIT` 断言而非硬编码。

---

## 十四、关键文件索引

| 文件                                                             | 作用                                                 |
| ---------------------------------------------------------------- | ---------------------------------------------------- |
| `modules/kg/ontology.py`                                       | 本体定义（EntityTypes/Relations/SemanticPredicates） |
| `modules/kg/builder/base.py`                                   | build_from_bundle 编排器                             |
| `modules/kg/builder/layer1.py`                                 | L1 构建器 + 三维度谓词 + LayerGroup + 语义层         |
| `modules/kg/queries/contracts.py`                              | DualPayload + TokenBudget + TopKSampler              |
| `modules/kg/queries/cognition.py`                              | get_village_cognition（三层认知摘要）                |
| `modules/kg/queries/semantic.py`                               | get_entity_semantics（语义层查询）                   |
| `modules/kg/queries/__init__.py`                               | 四命名空间 API                                       |
| `modules/kg/queries/sparql.py`                                 | SPARQL 模板 + query_kg 分发器                        |
| `modules/schema/encodings/dicts/rules/allowed_operations.yaml` | 允许操作手工补充                                     |
| `scripts/query_kg.py`                                          | 独立 KG 查询脚本                                     |
| `scripts/test_village_cognition.py`                            | 端到端认知验证（7项测试）                            |
