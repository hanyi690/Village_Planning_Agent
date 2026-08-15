ope

# EXECUTE 阶段 KG 利用设计

## —— 承接 PARSE 空间接地,激活 execute_queries 预留命名空间

> 状态:提案(待评审) | 日期:2026-07-29
> 关联:`PARSE_SPATIAL_GROUNDING_DESIGN.md`(上一环:NL→spec→候选BSM→精确BSM)、`KG_SPATIAL_COGNITION_DESIGN.md`(§十 execute_queries 标注"预留")、`ZONING_CUSTOM_FUNCTIONAL_GENERATION.md`(EXECUTE 侧生成样例)
> 触发:用户问"那规划阶段应该怎么利用呢?"——PARSE 利用了 KG+grounding 解析"在哪",EXECUTE 怎么利用

---

## 0. PARSE vs EXECUTE:利用方式根本不同

| 维度             | PARSE(上一环)                                         | EXECUTE(本环)                                                                            |
| ---------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| 解决的问题       | **"在哪"**——NL 空间引用 → 锚定 BSM           | **"在那放什么、怎么生成与校核"**——intent → L4 规划成果                          |
| 输入             | 自然语言描述                                          | 已类型化的 ZoneTarget/FacilityTarget/AxisTarget/RoadTarget + PARSE 的 ResolvedSpatialRef |
| KG 用法          | **引用解析 + 候选过滤**(属性+L2 关系出候选 BSM) | **生成期上下文 + 冲突校核 + L4 写入**(对正在改的图斑查邻接/约束/服务/面积)         |
| spatial_ops 用法 | 几何精化(半平面/缓冲)                                 | 生成运算(分配/落位/平衡)+ 精确冲突检测                                                   |
| 写 KG            | L3 意图虚拟实体(粗糙几何)                             | **L4 版本化增量**(PlannedParcel/Zone/Facility/Road/Axis)                           |
| 命名空间         | parse_queries(可用)                                   | **execute_queries(预留,未接线)** ← 本环要激活                                     |

**核心论点:EXECUTE 不重复 PARSE 的引用解析,而是消费其产物(锚定 BSM = 规划画布);EXECUTE 自己的 KG 利用是"生成期上下文查询 + 冲突校核 + L4 回写",这三件事当前是预留态(`execute_queries` 3 个 stub 全 `reserved`/`exists_not_wired`),本设计把它们激活。**

---

## 1. 承接:ResolvedSpatialRef → EXECUTE 的规划画布

PARSE 产出的 `ResolvedSpatialRef {final_bsms, bbox, reference_geometry, confidence, provenance}` 不是终点,是 EXECUTE 的**输入起点**:

```
PARSE: NL → spec → KG候选 → 精化 → ResolvedSpatialRef.final_bsms  (锚定图斑集)
                                        │
                                        ▼
EXECUTE: final_bsms = 规划画布(候选地块池)
         ├─ allocate_zones(intent.zone_targets, final_bsms)   → 选图斑满足面积比例
         ├─ facility_placer(intent.facility_targets, final_bsms) → 在画布内落点
         ├─ custom_zoning(intent.custom_zones, final_bsms)    → 功能分区(ZONING 方案)
         └─ road/axis(intent.linear_targets, final_bsms)      → 线性走廊
                                        │
                                        ▼
         L4 Planned* 实体 + derived_from → final_bsms(溯源回 spec)
```

**关键:final_bsms 把 PARSE 的"语义定位"转成 EXECUTE 的"几何工作集"**——EXECUTE 的所有生成器不再对全量 660 图斑操作,只对锚定子集操作。这同时是性能优化(660→N)和语义正确性保证(只在用户指定范围内规划)。

`ExecuteAgentState` 现有字段 `kg_adjacency_map / kg_constraints / kg_three_lines / kg_protected_parcels_detail / kg_vne_summary` 是 KG 的只读视图;本设计补一个 `resolved_spatial_refs: Dict[target_id, ResolvedSpatialRef]` 字段,把 PARSE 产物显式传过 subgraph 边界(现 subgraph 边界靠 state mapping,需在 mapping 里加这一项)。

---

## 2. 激活 execute_queries 命名空间(从预留到可用)

现状(`kg/queries/__init__.py` L109-135):3 个 stub——`get_candidate_parcels_for_layout`(reserved)、`check_conflicts`(exists_not_wired)、`get_constraint_coverage`(exists_not_wired)。激活为 6 个查询模式:

| 查询                                 | 用途                                                                                                                 | 实现                                              | 写 KG        |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ------------ |
| `get_parcel_context(bsm)`          | **生成期上下文**:该图斑的邻接(touches)、约束重叠、服务设施、道路接入、所属分区——生成器改一个图斑前一次性取全 | SPARQL 聚合 L1+L2                                 | 否           |
| `get_area_by_type(filter)`         | **用地平衡/结构调整表**:按 dlbm/zone_type 聚合面积,规划前后对比                                                | SPARQL GROUP BY                                   | 否           |
| `get_conflict_set(bsms_or_bbox)`   | **冲突校核**:指定图斑集/范围内违反 L1 约束的图斑——validate 节点用                                            | 复用`check_constraint_violations()` + bbox 粗筛 | 否           |
| `get_adjacency_chain(bsm, depth)`  | **扩张/裁剪**:多跳邻接,用于"把这片周边也划入"                                                                  | SPARQL property path 1-3 跳                       | 否           |
| `get_l4_diff(version)`             | **版本对比**:L4 vs L1 增量,导出/校验/回滚                                                                      | SPARQL 对比 L4 derived_from 链                    | 否           |
| `write_l4_entities(planned_state)` | **L4 回写**:PlannedParcel/Zone/Facility/Road/Axis + derived_from                                               | 调`builder._apply_planned_state`(现成)          | **是** |

前 5 个是读查询(挂 execute_queries,structured 返回,符合 §十"中粒度/structured");第 6 个是写(唯一写 KG 的 execute 查询)。

**两段式在 EXECUTE 的体现**(同 PARSE 的 KG候选→spatial_ops 精化范式):

- `get_parcel_context` 的"邻接"先用 KG L2 `touches` 关系(缓存,快)→ 若需精确共边长度再 spatial_ops(shapely);
- `get_conflict_set` 先 KG `located_in/intersects` L2 关系粗筛 → spatial_ops DE-9IM 精确算重叠面积(validator 要面积阈值,如广东"复垦区面积不增加容差 400㎡");
- `get_area_by_type` 纯 KG 聚合(免几何)。

---

## 3. L4 写入与 provenance 回溯

L4 实体(PlannedParcel 等)必须带 `pln:derived_from → L1 Parcel BSM`,把"可回溯"从文档层落到**规划成果级**(与 v3 §6.3 编码 provenance、ZONING 方案 §6.1 分区 provenance 同源):

```
pln:PlannedParcel_P001_v1 a pln:PlannedParcel ;
  pln:derived_from pln:Parcel_<bsm> ;          # 溯源到 L1 现状图斑
  pln:planned_dlbm "0101" ;                     # 规划地类
  pln:source_spec "directional:east_of_village" ;  # 溯源到 PARSE spec
  pln:decided_by "rule" ;                       # rule|llm|human
  pln:operation "reclassify" ;                  # reclassify|merge|split|new|demolish
  pln:area_change_ha -2.3 .
```

- `_apply_planned_state`(base.py L166,现成)扩展写这些 provenance 谓词;
- `get_l4_diff` 据此算"规划前后 dlbm 面积变化表"(金田村文本表 3-2 那种结构),直接喂规划文本生成模块(planning_text/);
- 版本化:L4 URI 带 `_v{version}`(EntityIdPolicy 已定),`get_l4_diff(version)` 支持方案比选。

---

## 4. Validation Loop:KG/spatial_ops 的密集消费者

ExecuteAgentState 有 `validation_result / validation_round / constraint_adjustments`——Worker-Evaluator 循环是 EXECUTE 利用 KG+spatial_ops 最重的地方:

```
生成器产出 L4 候选
   ▼
[validate] get_conflict_set(候选 BSMs)        ← KG L2 关系粗筛
   │          ↓ 命中冲突的图斑
   │          spatial_ops 精确算重叠面积/类型  ← 几何权威
   ▼
冲突 → constraint_adjustments(改哪、怎么改)
   ▼
[re-generate] get_parcel_context(调整图斑)    ← KG 上下文,决定换哪块
   ▼
循环至 validation_round 达上限或零冲突
```

- **KG 角色**:快速回答"这批图斑碰没碰红线/基本农田/历史文化线"(L2 `intersects`/`located_in` 缓存);
- **spatial_ops 角色**:精确算"碰了多少㎡、是否超容差"(广东 8 条衔接约束的容差:复垦 400㎡、允许建设区 1 公顷等);
- **两段式**:KG 粗筛命中的才进 spatial_ops 精算,避免对全量 L4 候选做几何运算。

这把 `check_conflicts`(exists_not_wired)和 `get_constraint_coverage`(exists_not_wired)两个 stub 真正接进 validate 节点。

---

## 5. 与既有生成的衔接

| 生成类型                               | KG/spatial_ops 利用方式                                                                                                          |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **常规用地分区**(zone_generator) | `get_area_by_type` 算现状结构 → intent area_targets → MIP 分配 → L4 PlannedZone + derived_from                              |
| **自定义功能分区**(ZONING 方案)  | L1 KG(parcels+约束面+道路+资源点)作 typing_rules 输入 → CustomZoningGenerator → L4 FunctionalZone(phase L3/L4,见 ZONING §6.1) |
| **设施落位**(facility_placer)    | `get_parcel_context` 查服务半径内居民点(serves 关系)+ 约束排除 → 落点 → L4 PlannedFacility                                   |
| **道路/轴**(axis_builder)        | `get_adjacency_chain` 找走廊图斑 → spatial_ops 路径 → L4 PlannedRoad/Axis                                                    |
| **用地平衡**(land_balance)       | `get_area_by_type` 规划前后对比 + `get_l4_diff` → 结构调整表 + 占补平衡校核                                                 |

**共性**:每个生成器都是"KG 上下文查询 → spatial_ops 几何运算 → L4 回写带 provenance → validate 用 KG+spatial_ops 校核"的闭环。execute_queries 命名空间是这个闭环的查询总线。

---

## 6. 落地清单与验收

### 6.1 改动(激活预留 + 承接 PARSE 产物)

| # | 文件                                           | 改动                                                                                         | 估算   |
| - | ---------------------------------------------- | -------------------------------------------------------------------------------------------- | ------ |
| 1 | `kg/queries/execute_queries.py`(新)          | 6 个查询模式实现(前5读+1写)                                                                  | ~250行 |
| 2 | `kg/queries/__init__.py`(改)                 | execute_queries stub 替换为真实 func,`exists_not_wired`→`available`                     | ~30行  |
| 3 | `agent/gis/execute/state.py`(改)             | ExecuteAgentState 加`resolved_spatial_refs` 字段                                           | ~10行  |
| 4 | `agent/gis/graph.py` 或 subgraph mapping(改) | PARSE→EXECUTE 边界传 resolved_spatial_refs                                                  | ~20行  |
| 5 | `kg/builder/base.py`(改)                     | `_apply_planned_state` 扩写 provenance 谓词(derived_from/source_spec/decided_by/operation) | ~60行  |
| 6 | `agent/gis/execute/`validate 节点(改)        | 接`get_conflict_set` + spatial_ops 精算,替现状启发式                                       | ~80行  |

### 6.2 验收(金田村可测)

| 用例               | 期望                                                                                                                      |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| "东边林地改居住"   | PARSE 锚定东边林地 BSM → EXECUTE`get_parcel_context` 取邻接/约束 → reclassify → L4 PlannedParcel derived_from 原 BSM |
| 用地平衡表         | `get_area_by_type` 规划前后对比 = 金田村表 3-2 结构(农业83.33%→…/建设1.28%→…/生态15.39%→…)                        |
| 冲突校核           | `get_conflict_set` 命中红线内建设图斑 → spatial_ops 算重叠面积 → 进 constraint_adjustments → 重生成零冲突            |
| 方案比选           | `get_l4_diff(v1)` vs `get_l4_diff(v2)` 输出两版 dlbm 面积差异                                                         |
| 自定义分区(ZONING) | CustomZoningGenerator 产 L4 FunctionalZone,derived_from 锚定 BSM,typed_by 词汇条目                                        |
| provenance 链      | SPARQL 可查:PlannedParcel → derived_from → Parcel → 该 Parcel 来自哪个 PARSE spec(directional:east_of_village)         |

### 6.3 与既有定案衔接

- **KG/spatial_ops 边界**(设计文档§二):**不变**,execute_queries 严格"语义+缓存关系"出候选、spatial_ops 出精确几何;
- **L4 版本化**(§三表):`_v{version}` URI + `get_l4_diff` 兑现版本对比;
- **derived_from 关系**(§五 8 关系之一):本设计首次大规模使用,把 L4→L1 溯源链填实;
- **execute_queries 命名空间**(§十"预留"):本设计激活,4 命名空间全部 available;
- **PARSE 空间接地**(上一环):resolved_spatial_refs 字段把两环串成"NL→BSM→L4"完整链路。

## 7. 一句话总结

规划阶段不重复 PARSE 的"在哪"解析,而是把 PARSE 锚定的 BSM 当**规划画布**;EXECUTE 自己的 KG 利用是三件事——**生成期上下文查询(get_parcel_context/area_by_type/adjacency_chain)、冲突校核(get_conflict_set 配 spatial_ops 精算)、L4 回写带 provenance(derived_from 回溯到 spec)**。这激活了 execute_queries 预留命名空间,把 NL→spec→BSM→L4→derived_from 串成完整可回溯链路,validate 循环则是 KG+spatial_ops 两段式的密集消费者。
