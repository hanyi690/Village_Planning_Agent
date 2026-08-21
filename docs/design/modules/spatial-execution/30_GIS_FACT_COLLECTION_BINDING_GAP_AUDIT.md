# GIS 事实、L1 事实与规划目标绑定差距审计

> 状态：`CURRENT`
>
> 日期：2026-08-18
>
> 本文纠正此前“文本中 275 条道路与 GIS 中 131 个 feature 数量不一致，因此不能绑定”的错误判断。
> 275 并不是权威交通事实，而是当前 KG ontology/type 复用和裸 RDF 类型计数共同制造的污染值。
> 本文优先级高于 06、28、29 和旧实施计划中与该结论冲突的段落。

## 1. 结论

当前问题不是“人类道路数量无法绑定 GIS feature”，而是三层边界同时有错：

1. L1 把 KG 内部节点数误写成现实道路条数；
2. L3 把污染后的 L1 字符串继续扩写成规划 claim；
3. GROUND、SELECT 和 EXECUTE 没有表达“一个目标绑定一组 source features”的集合语义。

正确边界是：

- 原始现状报告、版本化 GIS source layer 和规范化后的 canonical KG 共同构成 L1 事实底座；
- KG 的目标就是提供准确、可查询、可关联的权威证据；当前问题不是 KG 不应被信任，而是这版 KG 尚未正确区分实体语义。重建后的 KG 必须保留正确类型、semantic group、source feature identity 和 snapshot digest，并与 GIS snapshot 双向校验；
- KG 中派生节点、复用类型和裸实体计数不是新的现实事实；
- L1 负责保存可追溯事实，不负责提出规划目标；
- L3 负责基于 L1 facts 提出目标，不得反向改写事实；
- GROUND 负责把目标绑定到权威 source feature、候选 geometry、网络和约束；
- SELECT 负责选择方案或确认 required feature set；
- EXECUTE 只物化已选择的操作和几何。

## 2. 权威交通事实

现状报告中的交通事实位于
`docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md:33-38`：

- 对外交通主要依靠乡道和村道，122 乡道是主要对外通道；现状出行不便；
- 内部村道沿 122 乡道呈梳状、南北向分布；122 乡道是唯一东西向道路，东西联系不足；
- 道路基本简单硬化，但仍有砂石路、机耕路；道路较窄，多数不足 8 米；
- 交通设施共 4 处：1 处停车场、3 处公交站点；仅 1 处候车亭。

法定规划文本进一步给出目标值，见
`docs/平远县泗水镇金田村村庄规划（2022-2035年）文本.md:370-378`：

- 122 乡道宽度控制为 8 米；
- 村内道路应全硬底化；
- 村庄主路宽度不小于 6 米；
- 村庄支路宽度不小于 4 米；
- 巷道宽度不小于 2 米。

这些事实和目标比“275 条现状道路”更适合生成合理的道路规划图层：现状 GIS 提供线位，报告提供问题，规划文本提供改造标准。

## 3. 275 的真实来源

### 3.1 当前 L1 artifact 中存在自相矛盾的统计

主运行的 `L1Snapshot` artifact
`.run-tmp/blobs/sha256/0f1d8fb7e95fd424843087a48034b21fcc07d6e07ea949f2359f286c76e8e0b7`
同时记录：

- `KG图层 transport: 131 个 line`；
- `KG图层 admin: 145 个 ...，其中行政界线 144`；
- `KG实体统计: 道路 275 个`；
- L1 报告随后把 275 写成“现状道路 275 条”。

`131 + 144 = 275`。这与代码中的类型错误完全吻合。

### 3.2 KG 已有三维分层，但裸类型查询丢掉了这层语义

当前 KG 并非完全没有区分道路、行政边界和地形要素。现有导入注册表和 enrichment 已经保存：

- `gis_type_ref`：如 `current_road`、`admin_boundary_line`、`contour_line`；
- `geometry_kind`：如 `line`、`point`、`polygon`；
- `semantic_group`：如 `transport`、`admin`、`terrain`；
- `GisLayerSet`：按 semantic group 汇总并链接成员。

因此，当前缺陷更准确地说是：业务 RDF class 仍被复用，而部分消费者只看 `rdf:type`，没有把已有
三维分层作为查询不变量。最小修复应优先复用并强制约束
`(gis_type_ref, semantic_group, geometry_kind, source snapshot)`；是否再增加更细 RDF subclass，属于
ontology 清晰化和兼容迁移，不应成为修复 275 的前置条件。

代码证据：

- `backend/app/infrastructure/kg/builder/layer1_core.py:550-585`：真实 current road 写为
  `EntityTypes.Road + semantic_group=transport`；
- `backend/app/infrastructure/kg/builder/layer1_extended.py:186-201`：行政界线也被写为
  `EntityTypes.Road + semantic_group=admin`；
- `backend/app/infrastructure/kg/builder/layer1_extended.py:97-117`：等高线也被写为
  `EntityTypes.Road + semantic_group=terrain`；
- `backend/app/infrastructure/kg/builder/layer1_extended.py:119-141`：高程点被写为
  `EntityTypes.Facility + semantic_group=terrain`。

因此 `Road` 和 `Facility` 的裸 RDF 类型计数不是业务道路数或设施数，但按现有
`semantic_group/gis_type_ref` 查询本来可以正确区分这些 feature。

### 3.3 cognition 和 retriever 把内部节点数包装成了事实

- `backend/app/infrastructure/kg/queries/cognition.py:198-211` 按所有 `rdf:type` 裸计数，并直接格式化为
  “N 条道路”；
- `backend/app/infrastructure/kg/queries/semantic.py:388-444` 有同样问题；
- `backend/app/evidence/retrieval/retrievers/kg_retriever.py:102-110` 又把裸计数包装成
  `EvidenceFact(statement="KG实体统计: 道路 N 个")`；
- `backend/app/domain/assessment/aggregate.py:213-240` 将这些 KG statements 无条件提升到
  `L1Snapshot.facts`；
- `backend/app/contracts/domain/l1_contracts.py:45-75` 的 L1 fact 仍是 `list[str]`，没有逐 fact 的
  source locator、支持方式、实体范围或可比计数口径；
- `backend/app/domain/assessment/gate.py:34-51` 只有上游主动产生 `fact_contradiction` issue 才会阻断，
  本次 `131` 与 `275` 并没有被结构化为可检测矛盾。

这条链路把一个 KG 建模诊断错误升级成了 L1 事实。

### 3.4 L3 只是继续消费污染后的事实

L3 缓存中的 JTC-014 写成“275 条现状道路”，其 evidence refs 只有
`275条道路` 和 `KG空间实体统计`，没有原始 source span，也没有任何 source feature refs。

因此：

- JTC-014 是规划 claim，不是事实；
- 该 claim 的定量前提没有权威证据支持；
- 当前 claim 还混合了“保留现状路网”“完善连通”“建设消防通道”多个操作；
- 它不能原样进入 TARGET_PROJECTION。

## 4. 必须分开的五种数量

| 数量 | 当前金田样例 | 语义 | 是否可直接比较 |
|---|---:|---|---|
| 报告业务数量 | 交通设施 4 处、公交站点 3 处 | 人类/法定文本的对象或指标口径 | 只与相同定义、相同时点的调查比较 |
| GIS source feature count | roads_current 131 features | 文件/图层的记录粒度 | 不等于道路名称数、路段数或拓扑边数 |
| KG canonical source-feature count | 应与 131 source IDs 对齐 | GIS feature 在 base KG 中的投影 | 可与同 snapshot GIS feature count 校验 |
| 网络拓扑 edge count | 由 noding/splitting 后生成 | GIS 算法使用的计算图粒度 | 不等于 source feature count |
| planning output feature count | 由场景操作生成 | 最终保留、拓宽、硬化或新建图层记录数 | 由物化策略决定，不等于以上任一数量 |

只有“GIS source feature count”和“同 snapshot 的 canonical source-feature count”要求一一对齐。
其他数量必须携带 counting basis，不能用相等判断做 binding gate。

## 5. 当前为什么仍然不能产出合理道路规划层

即使先修掉 275，当前代码仍有以下真实缺口。

### 5.1 L1 fact contract 无法证明事实

`L1Snapshot.facts` 曾是字符串列表。原文事实、GIS 观测、KG 投影、
模型摘要和派生指标在同一容器内，L2/L3 无法判断哪一项可作为硬事实。

### 5.2 L3 claim 没有强制绑定 source fact ID

`PlanningClaim.evidence_refs` 允许自由字符串。类似 `KG空间实体统计` 的标签可以通过 schema，
但它既不是 artifact ref，也不是 fact ID，更不是 source span。

### 5.3 source binding 把数量相等当作兜底条件

`backend/app/evidence/identity/source_feature_binding.py:104-167` 当前支持：

- 显式 source feature IDs；或
- 声明数量恰好等于 source feature 数量时绑定全部 feature。

第二条规则应删除。广域“保留现状道路网络”应由 typed scope 绑定当前 `roads_current` collection；
命名道路、问题路段和部分改造应由明确 source IDs、道路属性或人工审计的 feature set 绑定。

### 5.4 GROUND 把 feature set 拆成互斥 alternatives

GROUND 已能把多个 source-backed line WKT 逐个生成 exact candidates，但
`GroundedCandidateDomain` 没有 `all_members / choose_one / choose_subset` 基数语义。

当前已补齐 `ScenarioTargetSelection.selection_mode` 和 `candidate_ids`；多成员集合在
SELECT/EXECUTE 中保留并按成员展开，不能被压成一个代表候选。

### 5.5 SELECT 的选择必须使用 typed member set

`PlanningScenario` 现在只保留 `ScenarioTargetSelection`。`choose_one`、`all_members` 和
`choose_subset` 都通过 `candidate_ids` 表达，ScenarioSolver 对候选域做笛卡尔积后保留完整
成员集；没有单值 selection compatibility view。因此 131 条现状线可以作为一个显式
`all_members` 选择进入后续计划。

### 5.6 EXECUTE 按 typed member set 展开 candidate binding

`WorkerTask.candidate_id`、`TaskExecutionResult.candidate_id` 和 plan builder 的
单 candidate binding 只表示一个实际 worker task。计划 builder 同时携带完整 `candidate_ids`，
多成员选择被展开成稳定的 `:member:N` worker tasks；没有 candidate geometry 时显式 deferred。

### 5.7 现状、改造和新建的约束语义没有彻底分开

- `preserve_existing`：引用现状 geometry，不应因穿越基本农田而被当作违法新建；
- `harden/repair`：通常沿现状线位操作，应校验 source binding、施工范围和属性变化；
- `widen`：需要对现状中心线生成有宽度的影响范围，再检查退界、占地和控制线；
- `new_corridor`：需要端点、网络缺口、候选走廊和路由，不得复用现状 source line 冒充新建线。

当前 GROUND hard-constraint 和道路 worker 尚未把这四类操作完整区分。

### 5.8 现有设施和 Evidence 能力存在，但没有汇合成同一条生产链

`annotation.geojson` 当前有 34 个 Point，其中 30 个是 `现状设施点`；标签中包含 3 个“站”和
1 个“停”，可以与报告中的 3 个公交站点、1 个停车场相互校验。现有代码也已经具备：

- annotation → typed CurrentFacility；
- source feature identity 和 snapshot digest；
- Facility KG entity + authoritative Point WKT；
- PlaceEvidenceIndex、EvidenceObservation、GroundedEntityBinding；
- 多 source geometry exact GROUND；
- facility worker 到 RenderLayers 的 source/candidate lineage。

但生产接线仍有断口：

- source semantic identity 目前只特殊映射“站→公交站”“祠→祠堂”，没有“停→停车场”；
- facility binder 只支持公交站和祠堂，并继续要求声明数量等于匹配 feature 数；
- bundle retriever 的 facility scope 与实际 `annotations_current` key 不完全一致，并且只返回分组统计；
- report retriever 读取生成后的 L1/L2/L3 报告摘要，不返回原始报告 span；
- KG retriever 能返回 layer cards，但仍附带裸 entity counts；
- EvidenceBundle 没有被编译成 TARGET_PROJECTION 可消费的 source-feature set binding；
- 网络和设施服务 evaluator 已有模块与 focused tests，但 PlanningContext 未生产化承载
  NetworkGraphSnapshot/DemandSnapshot，真实 SELECT 通常无法完成服务覆盖求值。

所以后续应复用并补齐这些模块，而不是另建一套设施或检索系统。

## 6. 重新定义 GROUND、SELECT、EXECUTE

```text
L1 FACT
  原始报告事实 + GIS source features + 可审计 KG projection
  每项带 fact_id/source_ref/source_span/snapshot/semantic_group

L3 GOAL
  引用 L1 fact_id，提出 preserve / harden / widen / new_corridor / facility_new
  不产生坐标，不把 KG 节点数写成事实

TARGET_PROJECTION
  把一个混合 claim 拆成单一 operation targets
  编译 source collection binding、explicit subset binding 或 network demand

GROUND
  resolved factual set: 现状 source feature 集合
  candidate alternatives: 新建设施点、地块、走廊、路径
  constraint factors: 按 operation 编译

SELECT
  required set 全部保留
  choose-one alternatives 选择一个
  choose-subset 按容量/缺口/成本选择子集
  同时求解关系和网络

EXECUTE
  对 required/selected members 执行 typed operation
  输出每个 final feature 的 source_feature_id、operation、target、scenario 和 relation lineage
```

关键点：事实集合不是“候选方案”。保留全部现状路网时，131 个 source features 是一个 required
feature set；新建东西向联系时，多条候选路线才是 alternatives。

## 7. 合理的金田道路规划图层应该是什么

第一版合理成果至少应分成以下图层，而不是输出一个混杂 road layer：

1. `current_road_reference`：131 个 source-backed line features，只作现状底图；
2. `planned_road_preserve`：被规划确认保留的现状道路集合，geometry 可与 source 相同，但带规划操作 lineage；
3. `planned_road_harden_or_repair`：由现状报告中的砂石路、机耕路问题和可用属性/人工审计绑定的问题路段；
4. `planned_road_widen`：122 乡道及其他不足标准的已绑定道路，带目标宽度和影响范围；
5. `planned_new_connection`：为补足东西向联系或消防通达而经过网络分析生成的新走廊；
6. `planned_transport_facility`：停车场、公交站点和候车亭的保留、改造、新增点位；
7. `road_fact_conflicts`：无法对齐的文本、GIS、KG 统计和缺失道路属性，作为审计层而非规划 geometry。

只有 1 是纯现状事实层；2-6 才是规划场景层。相同 geometry 的 preserve overlay 可以是合法规划表达，
但必须明确 `operation=preserve`，不能伪装成新建或几何变化。

## 8. 当前 demo 状态

- 历史 test3：GROUND 全部退化为 polygon/parcel_set，SELECT=0，EXECUTE 无 worker；图层为空；
- source-aware replay28：clone-only 分支已有 42 exact Point、16 final features 和非空 partial overlays，
  但 exact Line=0，154/170 targets deferred；
- 默认 live demo 尚未证明 fresh L1 修正后可完成道路 source binding、SELECT、EXECUTE 和 `/map-layers`；
- 因此当前状态仍是 `PARTIAL`，不能标为完整规划输出。

## 9. 文档差距

| 文档 | 仍有效内容 | 需要纠正内容 |
|---|---|---|
| 06 | 四阶段边界、几何必须参与场景求解 | 仍混用旧 SiteSelectionDecision 与新 PlanningScenario；缺 fact set/cardinality；部分 CURRENT 描述已过时 |
| Explore 23 | 统一 EvidenceBundle、query plan、sufficiency 方向正确 | 没有阻止裸 KG entity count 成为 L1 fact；source feature facts 仍不足；报告 span 与 GIS fact 冲突未成为 gate 输入 |
| 28 | GIS 几何权威、事实/目标/场景分层方向正确 | “131 条道路”仍把 feature count 写成人类道路数；未描述 source collection binding 和 required feature set |
| 29 | 空图层、fail-closed、source geometry 缺口审计仍有价值 | “当前用户可见产出为零”已被 clone-only replay28 部分更新；更重要的 L1 ontology/count 污染未被发现 |
| 旧 v2 plan | typed candidate、solver、lineage、replay 约束仍有效 | F3 和 ledger 中“275 vs 131 所以不绑定”的结论过时；必须先修 L1 fact producer |

## 10. 后续实施

详细、可独立分派的任务见：

`docs/superpowers/plans/2026-08-18-gis-fact-source-collection-binding.md`

实施顺序必须从 KG/L1 fact correctness 开始。只加 source-ID overlay、只改 GROUND，或直接把 131 个 IDs
塞进 JTC-014，都会保留错误事实和混合目标，不是完整修复。
