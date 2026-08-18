# 关系感知的空间规划生成：从 L1 证据接地到 GIS 场景物化

> 状态：TARGET / NORTH STAR
>
> 核验日期：2026-08-17
>
> 适用范围：L1 地点增强、设施 KG、PlaceEvidenceIndex、TARGET_PROJECTION、GROUND、
> SELECT、EXECUTE、VALIDATE、RECONCILE 与 DELIVER。
>
> 本文扩展 [06_TARGET_PROJECTION_EXECUTE.md](06_TARGET_PROJECTION_EXECUTE.md)。本文中的
> CURRENT 是从当前代码核实的事实，GAP 是当前缺口，TARGET 是后续重构目标，不代表已经实现。

> **2026-08-18 新鲜度纠正：** Wave 3 已补齐 source identity、canonical bundle/KG freshness、
> facility/road source binding 和 low-memory replay preflight；focused tests 通过。但真实演示
> 仍需重新构建 source-aware bundle/KG 并证明 exact point/line 进入 GROUND、SELECT 产生选择、
> EXECUTE 写出非 baseline feature。历史 parcel-union artifact 不能作为完成证据。

## 1. 决策摘要

空间规划生成不能继续采用“LLM 生成若干独立任务、分别找地块、最后拼成图层”的模型。
规划目标的几何、目标之间的关系、现状证据和求解过程必须一起保存，最终生成可以复核的
GIS 场景。

本设计的核心决定如下：

1. L1 提取出来的地名、设施和空间描述首先是带来源的 EvidenceObservation，不直接成为
   权威 KG 实体。经过实体解析后，才形成 GroundedEntityBinding。
2. 现有会话 KG、VillageBundle、GroundedAnchor、PlaceEvidenceIndex 和 RelationEvidence
   全部复用，但职责重新划分：KG 是事实与语义关系索引，Evidence 是来源和置信度，GIS
   是几何计算权威，规划图是期望状态，执行图是任务调度。
3. 地名解析由逐 mention 独立解析提升为候选生成加相关 mention 联合消歧。同一报告中的
   村名、设施、道路、水体和关系共同参与消歧；LLM 只能在确定性 Top-K 候选之间做闭集选择。
4. PlanningIntentGraph 表达规划目标关系，允许环；ConstraintFactorGraph 表达接地后的
   可计算约束；ExecutionDAG 才必须无环。
5. 几何是目标求解变量，不是最后渲染时补上的属性。点、线、面目标分别生成有来源的
   CandidateGeometry，并在联合场景中确定。
6. LLM 只选择闭集的 target_kind、asset_kind、operation_template、relation_template 和
   evidence_ref；不得生成 BSM、坐标、WKT、拓扑结论、GIS 指标或最终适宜性分数。
7. 设施 KG 的 serves、nearby 等粗关系只能用于候选召回和先验评分。最终设施服务必须使用
   真实道路网络、需求点、阻抗和容量计算。
8. 没有对应 worker 的目标要保留已接地结果，进入 deferred_unsupported_capability，不能
   降级成 road，也不能迫使 L1/L2/L3 重跑。
9. 会话 KG 的 Layer-1 基线按 GIS 指纹复用；L1 证据增强和规划场景以版本化 overlay 持久化，
   不能反复污染基线图。

### 1.1 `site_area` 与 `facility` 的唯一空间语义

`site_area` 不是“所有项目的定位点”，而是一个需要在地块上占用、改造或重分类的 site
intervention。它的执行输出只能是 `parcel` 或 `polygon`：GROUND 解析其范围/选址证据，
SELECT 选择承载地块，EXECUTE 的 site-area worker 生成项目 footprint。

`facility` 是可服务、可计数、可落到一个或多个空间锚点的功能节点，执行输出是 `point`。
它可以有 `footprint_area_m2`，但该面积是设施点位的实施副作用/容量属性，不改变其点位语义；
facility worker 可以据此在选定地块内生成设施占地变化，同时交付层保留设施点。

因此：

| 规划对象 | canonical category | 输出 | 典型例子 | 进入的 worker |
|---|---|---|---|---|
| 服务/功能节点 | `facility` | `point` | 综合服务中心、卫生站、候车亭、篮球场、应急点 | facility |
| 占地项目 | `site_area` | `parcel/polygon` | 产业园、农业园、明确范围的场地建设、土地整治范围 | site_area |
| 线性资产 | `road` + `asset_kind` | `line` | 道路、供水、污水、电力、通信、护岸、排水沟 | road/utility |
| 规划覆盖/保护关系 | `zone`/`protection`/`restoration` | `polygon` | 用地分区、保护范围、修复范围、功能覆盖 | zone/overlay |
| 管理或政策事项 | `action` | `action` | 制度、培训、巡查、运营机制 | action |

如果一条原始 claim 同时包含“停车场 + 候车亭”或“广场 + 配套设施”，它不是一个可以
直接执行的单一 site_area；必须拆成 parent relation 与多个 typed children，分别进入
facility/site_area/road。确定性编译器只依据已填的结构化参数做有限修复，不依据名称、宽度
或正则推测类别；无法唯一确定的部分转为可审计 action 或 deferred target。

## 2. 当前模型为什么不够

### 2.1 独立任务不能表达规划意图

“新增卫生室”“完善道路”“发展产业”“整治滨水空间”不是四个互不相关的任务。合理规划
至少要表达：

- 卫生室服务哪些聚落；
- 卫生室是否能由现状道路在规定阻抗内到达；
- 产业项目是否位于允许建设区并避让生态、洪涝和历史保护约束；
- 新道路连接哪些目标和现状网络节点；
- 滨水项目与河道的距离、可达性和生态缓冲是否同时满足；
- 多个项目是否竞争同一地块、容量或实施时序。

如果 dependencies 只是字符串，或在 TARGET_PROJECTION 后被丢弃，后续即使每个图斑单独
合法，组合起来仍可能不可实施。

### 2.2 地名解析不是字符串匹配

“村部”“老小学”“祠堂边”“金田河两岸”“入口道路”可能分别是：

- 有稳定 KG URI 和真实点、线、面几何的现状实体；
- 只有报告证据、没有精确几何的已报告实体；
- 行政村、自然村、聚落簇或模糊区域；
- 一个空间关系短语，而不是独立地点；
- 同名不同物，或同一实体的不同俗称。

将这些提及直接映射到整村 BSM，或仅凭同名、正则和文本 token 决定实体，会把粗作用域
误写成精确位置。错误会沿着 GROUND、SELECT、EXECUTE 一直放大。

### 2.3 KG 关系与规划约束不是同一种东西

KG 中“设施 A serves 聚落 B”是当前数据或规则产生的事实/派生关系；“规划设施 T 应服务
聚落 B”是期望状态；“场景 S 中 B 到 T 为 8.4 分钟”是满足度证据。三者不能使用同一个
未分层的三元组表达。

| 生命周期 | 含义 | 示例 |
|---|---|---|
| observed fact | 可追溯的当前事实 | 设施 A 的点位来自 facilities_current |
| derived relation | 根据当前几何计算的关系 | A 是 B 的最近设施候选 |
| desired relation | 规划希望成立的关系 | 新卫生室 T 应服务 B |
| satisfaction evidence | 场景中的计算结果 | 场景 S 中 B 到 T 的网络时间为 8.4 分钟 |

只有最后一类能证明规划关系在具体场景中实现。

## 3. 总体架构

    报告 / 用户目标 / 规则
                 |
                 v
       L1 EvidenceObservation
                 |
       候选生成 + 联合实体解析
                 |
       +---------+---------+
       |                   |
       v                   v
    事实底座            LLM 语义编译器
    Bundle + KG +        闭集选择，不造 GIS
    Evidence             |
       |                   |
       +---------+---------+
                 v
        PlanningIntentGraph
          目标关系图，可有环
                 |
          确定性关系编译
                 v
       ConstraintFactorGraph
        多目标约束因子图
                 |
       候选几何 + 联合场景求解
                 v
         PlanningScenario[]
                 |
       GIS / 网络 / 规则校验
                 v
     RelationSatisfaction + Findings
                 |
       选择、修复、物化、交付
                 v
             ExecutionDAG

### 3.1 现状事实底座

事实底座由以下内容组成：

- VillageBundle：真实点、线、面、栅格与属性，是几何权威；
- Session KG BaseFacts：稳定 URI、实体类型、名称、BSM 和图层语义；
- Session KG DerivedRelations：从当前 GIS 计算出的拓扑、邻近和统计关系；
- L1 EvidenceObservation：报告中的地点、设施、问题、需求和关系；
- GroundedAnchor：L1 observation 的接地快照；
- PlaceEvidenceIndex：名称、类型、几何、BSM、来源和关系证据的候选索引；
- ConstraintIndex、SuitabilitySurface、NetworkIndex：硬约束、适宜性和网络计算索引。

事实底座回答“现在有什么、来源是什么、能定位到什么粒度”，不回答“规划最终选择什么”。

### 3.2 三张图和一个场景账本

PlanningIntentGraph 的节点可以是 zone、facility、site_area、road、utility_line、axis、
landscape 或 preservation；边可以是 serve、connect、within、near、avoid、preserve、
part_of、depends_on、co_locate 和 mutually_exclusive。它允许关系环，并保留 source claim。

ConstraintFactorGraph 将意图编译成：

- 一元因子：目标必须位于允许建设区；
- 二元因子：设施到聚落的网络时间不超过阈值；
- 多元因子：多个设施共同覆盖需求并满足容量；
- 资源因子：多个项目不能使用同一排他地块；
- 网络因子：线性目标必须连接合法端点和相应 domain network；
- 时序因子：道路完成后，依赖项目才可实施。

ExecutionDAG 只负责 artifact 依赖、并行派发、worker 能力、checkpoint 和 resume。它不是
规划关系图，也不能为了满足 DAG 而删除真实规划关系。

每个 PlanningScenario 独立保存选中的几何、操作、实体映射、关系满足度、未满足约束、
指标、来源和与其他场景的差异。

## 4. 现有 KG 与 Evidence 的复用矩阵

| 现有能力 | CURRENT 事实 | TARGET 用法 | 不能承担的职责 |
|---|---|---|---|
| EntityIdPolicy | 可由实体类型与 BSM/target id 生成稳定 URI | 作为实体、目标和场景 feature 的标识基础 | 不能单独证明两个 mention 是同一实体 |
| EntityTypes | 已有 Parcel、Facility、Road、WaterBody、ResidentialCluster、PlaceRef 和多类 target/planned entity | 保留现状与计划词表，补齐 typed linear asset | 不能只靠 geometry_kind 判断资产语义 |
| GeoSPARQL 关系 | 已有 sfWithin、sfTouches、sfIntersects、sfContains | 表达经 GIS 验证的空间关系 | 未经计算不得由 LLM 断言 |
| PLN 关系 | 已有 nearby、connected_via_road、derived_from、serves、connects | 候选召回、现状导航和关系模板基础 | nearby/serves 不是精确服务结论 |
| materialize_kg_topology | 建立聚落簇、parcel→cluster、facility/water/road→nearest cluster | 地点消歧和候选生成的粗拓扑先验 | 质心和度单位阈值不是最终网络分析 |
| Session KG + CAS | 可按 Layer-1 GIS 指纹复用和恢复 | 基线图只构建一次；增强和场景用 overlay | 不应每次 resume 重建，也不应被意图污染 |
| GroundedAnchor artifact | 生产入口可持久化，bootstrap 可恢复并重放 | 作为 L1 接地输入和增量解析依据 | anchor 数量不等于独立实体数量 |
| PlaceEvidenceIndex | 汇聚 gazetteer、KG 名称、L1 fact、POI 和真实 BSM/点位 | 候选生成与确定性评分核心 | 当前 version 尚未覆盖所有输入 digest |
| EvidenceScore | 有 8 个评分维度，禁止 fuzzy short name 自动通过 | 保留确定性评分，增加粒度、冲突和网络因子 | LLM 不得直接给分 |
| RelationEvidence | 有 subject、predicate、object、source_refs、confidence、query_trace | 表达观测和派生关系证据 | 不能直接充当 desired relation 或 satisfaction |
| KGSpatialQueryAdapter | 支持 bbox、nearest、候选查询 | 快速召回和粗筛 | bbox overlap 不能做最终合规验证 |
| KGSemanticQueryAdapter | 可查实体和关系 | 实体候选和关系导航 | get_constraints 为空、resolve_ambiguous 未实现，不能独立作为约束编译器 |

### 4.1 权威性规则

1. 坐标、WKT、相交、包含、距离和面积以 VillageBundle 与 app/spatial 精确计算为准。
2. 名称、别名、类型和实体 URI 以版本化 KG 与 PlaceEvidenceIndex 解析结果为准。
3. 报告陈述以 EvidenceObservation 和 source_refs 为准。
4. 规划目标以 PlanningIntentGraph 为准。
5. 场景选择以 PlanningScenario 为准。
6. 是否满足目标关系以 RelationSatisfaction 的计算证据为准。
7. 工作流完成以 artifact/checkpoint 为准，不以 KG 三元组数量为准。

## 5. L1 增强实体的目标改造

### 5.1 L1 首先产生观测账本

每次报告提及都保留为独立 observation：

    EvidenceObservation
      observation_id
      mention
      normalized_name
      aliases
      observed_type
      role
      source_document_ref
      source_span
      report_section
      spatial_hint
      relation_mentions
      temporal_status
      confidence
      extraction_method

十份报告提到“老小学”应有十个 observation，但可以绑定到一个 canonical entity。不能为了
减少 anchor 数量而丢掉多来源证据，也不能把十次提及误当成十个设施。

### 5.2 PlaceMention、PlaceIdentifier、SpatialFeature 分离

| 对象 | 作用 |
|---|---|
| PlaceMention | 文本中的一次提及，保留原文和上下文 |
| PlaceIdentifier | 稳定、可链接的地点标识，包含规范名和别名 |
| SpatialFeature | 真实或规划空间对象，具有类型和一个或多个 geometry representation |

这符合 ISO 19155-2 的链接思想：地点标识与外部编码中的 feature/object 通过稳定标识连接，
名称字符串不能直接等同于 feature。

### 5.3 L1 增强写入独立 KG overlay

目标 named graph / artifact 分层如下：

| 层 | 内容 | 可变性 |
|---|---|---|
| base_facts | GIS 导入的现状实体、BSM、属性 | 同一 bundle digest 下稳定 |
| derived_relations | 当前几何计算的拓扑和统计 | 由算法版本和 bundle digest 决定 |
| l1_observations | 报告 observation、mention、source span | 随 L1 artifact 变化 |
| entity_bindings | mention 到 canonical entity 的绑定 | 可增量修订 |
| planning_intent | 目标节点和 desired relation | 随规划程序版本变化 |
| scenario_state | 每个场景的 planned feature 和 satisfaction | 每个 scenario 独立 |

当前 _inject_anchors_into_kg 的能力可继续作为 overlay writer，但每条写入必须带
observation_id、source_ref、binding_status 和版本，不能把未解析或 best-effort anchor 写进
base_facts。

### 5.4 anchor 聚合与去重

121 个 GroundedAnchor 是否冗余，不能只看名称或坐标。正确流程是：

1. 保留全部 observation；
2. 按候选实体 URI、角色、时间状态和空间粒度聚类；
3. 同一实体的不同别名合并到 PlaceIdentifier；
4. 同一坐标且同类型只能作为强共指证据，不能单独决定合并；
5. 同坐标但不同设施类型可能是复合设施，不能误合并；
6. 同名但不同自然村、BSM 或设施类型必须分开；
7. 只有村级 anchor 时可以生成 scope cluster，不得生成虚构设施点；
8. 聚合结果保存 member_observation_refs 和冲突字段。

因此，相关 mention 可以批量交给一次 LLM 调用，但输入必须先由确定性候选生成器构成
mention graph。LLM 只在给定 Top-K 候选中选 candidate_id；额度耗尽后保留 ambiguous 或
unresolved，不把低置信度结果强行落点。

## 6. 地名解析目标架构

### 6.1 两阶段联合消歧

阶段 A 是确定性候选生成：

    名称/别名 + 类型 + 村域/聚落层级 + KG 关系 + 真实几何
      -> 每个 mention 的 Top-K candidate

阶段 B 是联合排序与约束传播：

    文本上下文 + mention 间关系 + 候选间拓扑 + scope 一致性
      -> resolved / ambiguous / unresolved

候选因子包括：

- exact canonical/alias；
- L1 fact exact；
- entity type 与 role；
- 行政村、自然村、ResidentialCluster 的层级包含；
- KG 的 serves、nearby、connected_via_road；
- mention 之间的位于、沿、连接、邻近、服务关系；
- candidate 的真实 geometry 与报告 scope；
- 同一段落的空间最小性，但只作软因子；
- 来源可信度和时间状态；
- 候选冲突和跨来源一致性。

### 6.2 必须保留空间粒度

    GroundedEntityBinding
      mention_ref
      canonical_entity_ref
      status: resolved | ambiguous | unresolved
      geometry_granularity:
        exact_feature | parcel_set | settlement | village_scope | none
      geometry_ref
      source_bsms
      candidate_refs
      evidence_refs
      relation_evidence_refs
      confidence
      uncertainty_reason
      query_trace

| 粒度 | 可用于什么 | 禁止什么 |
|---|---|---|
| exact_feature | 现状设施保留、迁建、网络挂接 | 仍需校验时效和 CRS |
| parcel_set | 候选地块和区域目标接地 | 不得宣称精确设施点 |
| settlement | 聚落级需求和服务范围 | 不得直接作为施工图斑 |
| village_scope | 报告作用域和粗召回 | 不得作为精确 near/within |
| none | 保留语义目标或人工处理 | 不得执行几何 worker |

当前 village_anchor BSM fallback 应保留，但语义必须是 village_scope，而不是实体级设施几何。

### 6.3 地点不应默认只有点

行政村、自然村、聚落、滨水带和道路沿线优先绑定真实面或线。点可能只是 label_point、
centroid 或 entrance，必须标出 representation_role。目标模型支持：

    GeometryRepresentation
      geometry_ref
      geometry_kind
      representation_role:
        footprint | centroid | label_point | entrance | service_area | corridor
      source_ref
      crs
      accuracy_m
      valid_time

不能用 centroid 或 label_point 替代 footprint 做 contains、overlap 或合规判断。

### 6.4 LLM 边界

允许 LLM：

- 识别 mention、别名、角色和关系短语；
- 在 Top-K 候选中选择 candidate_id；
- 判断 mention 是设施、聚落、道路、水体、区域或无法确定；
- 对冲突结果引用 evidence_ref。

禁止 LLM：

- 创建不存在的实体 URI、BSM、坐标或 WKT；
- 选择输入 Top-K 之外的自由文本实体；
- 把“位于某村”解释为设施精确位于全村任一地块；
- 把 query_error 或 no-return 解释为 not_found；
- 通过正则、宽度或 geometry_kind 推断资产语义。

## 7. 设施 KG 的详细利用

### 7.1 现状设施与规划设施分离

    FacilityFeature
      entity_ref
      facility_kind
      lifecycle_status
      geometry_representations
      source_bsms
      capacity
      service_level
      network_access_refs
      settlement_refs
      observation_refs
      provenance

规划目标使用独立对象：

    FacilityTarget
      target_id
      facility_kind
      operation:
        preserve | upgrade | expand | relocate | new | remove
      existing_entity_ref
      demand_refs
      candidate_policy
      relation_intent_refs
      required_capabilities

capacity、service_level 不存在时保持 unknown，不能由 LLM 填充。

### 7.2 从设施 KG 到候选与服务缺口

以“提升社前村卫生服务”为例：

1. PlaceEvidenceIndex 将“社前村”解析为 ResidentialCluster 或 village_scope；
2. KG 查询 Facility、serves、nearby，召回已有卫生设施；
3. facilities_current 或 annotations_current 验证真实点位；
4. NetworkIndex 将设施和需求点挂接到可路由节点；
5. 计算现状服务覆盖、阻抗、容量和缺口；
6. 根据 operation 生成 preserve、upgrade、expand、relocate、new 候选；
7. 候选地块经过硬约束、适宜性、用地兼容和道路可达性筛选；
8. 场景求解器联合选择设施点位与必要的道路改造；
9. 精确网络分析产生 RelationSatisfaction。

### 7.3 serves/nearby 只作粗先验

当前 materialize_kg_topology 使用质心最近邻和 max_distance_deg，为 Facility 建立 serves、
nearby 到 ResidentialCluster 的关系。这些边必须标注：

    derivation_method = centroid_nearest_cluster
    distance_metric = angular_degree_approximation
    intended_use = candidate_recall
    authority = soft_prior

可用于：

- 同名设施候选优先级；
- 判断 report mention 与村域是否相容；
- 初始化 demand/facility 集合。

不能用于：

- 证明居民可以通过道路到达设施；
- 证明容量足够；
- 证明服务半径达标；
- 作为最终验收的 serves 边。

最终服务关系需要真实道路网络、方向、阻抗、需求权重和容量，保存 demand→facility 分配线
以及未覆盖需求。

### 7.4 四类设施状态

| 类型 | 证据 | 允许用途 |
|---|---|---|
| authoritative_current | 权威 GIS 点/面和稳定 URI | 现状分析 |
| reported_current | 报告 observation，有候选但无精确几何 | 需求判断和待核实清单 |
| inferred_current | 多来源与拓扑推断 | 软证据 |
| planned | PlanningScenario 新增或修改的 feature | 仅 scenario graph |

reported_current 不因重复提及升级为 authoritative_current；planned 不写回 base_facts。

## 8. Evidence 融合、来源与冲突

### 8.1 provenance 链

Evidence 使用 W3C PROV-O 的 Entity、Activity、Agent 思路记录：

    source document / GIS layer
      -> observation or feature
      -> candidate evidence
      -> binding or constraint
      -> scenario decision
      -> validation result

每个结论都要知道原始 artifact、处理器版本、解析版本、GIS operation、solver 和 validator。

### 8.2 证据等级

| 等级 | 示例 | 默认用途 |
|---|---|---|
| A | 权威 GIS、法定控制线、明确 BSM | 硬约束或现状事实 |
| B | 多来源一致设施点、可验证报告事实 | 强软约束或候选确认 |
| C | 单份报告、KG 粗拓扑、村级 anchor | 候选和评分 |
| D | 外部 geocoder、模糊别名、LLM 判断 | 消歧辅助 |

硬/软不是 confidence 单独决定，而由 source policy、法定性质、几何粒度和时效共同决定。

### 8.3 冲突状态

- 权威图层冲突：source_conflict，禁止静默择一；
- 报告与 GIS 冲突：保留双方，默认以有效期内权威 GIS 为几何事实；
- 分数接近：ambiguous；
- 查询失败：query_error，不等于 not_found；
- 只有 scope：insufficient_geometry，不等于 unresolved；
- 无候选：no_candidate，不等于 LLM failure；
- 无 worker：deferred_unsupported_capability，不等于 grounding failure。

### 8.4 PlaceEvidenceIndex 版本键

当前 index version 主要由 context.version 和 kg_version 构成。目标指纹应包含：

    place_evidence_fingerprint =
      hash(
        bundle_snapshot_digest,
        kg_layer1_digest,
        kg_derived_relations_digest,
        l1_snapshot_digest,
        grounded_anchor_digest,
        gazetteer_digest,
        resolver_config_digest,
        resolver_code_version
      )

只有输入 digest 变化才重建。索引必须是可恢复 artifact，不能只存在进程内 context。

## 9. LLM 语义编译器

LLM 接收有限证据目录：source claim、candidate_id、允许的 target/asset/operation/relation
集合、worker capability、规则摘要和 evidence_ref。它输出：

    PlanTargetDraft
      target_id
      target_kind
      asset_kind
      operation_template
      existing_entity_candidate_id
      demand_candidate_ids
      relation_drafts
      evidence_refs
      unresolved_fields

    RelationDraft
      relation_template
      subject_target_id
      object_candidate_id_or_target_id
      criticality
      evidence_refs

Instructor/Pydantic 负责结构语法与闭集一致性；domain validator 负责：

- target_kind 与 asset_kind 是否兼容；
- road 是否误用了 utility 参数；
- utility_line 是否缺端点或 corridor 需求；
- relation 的主客体类型是否合法；
- evidence_ref 是否存在；
- candidate_id 是否来自输入目录；
- critical relation 是否缺失。

正确顺序是：闭集词表、正确领域 schema、prompt、Instructor 语法验证、domain validator、
有限 repair。结构化输出不能修复错误的领域 schema。

明确禁止：

- 用正则作为主语义分类器；
- 用线宽判断道路、管线或排水渠；
- 让 LLM 决定 topology、距离、重叠、面积、路径或服务覆盖；
- 因缺 worker 把 utility 目标改成 road。

## 10. 闭集关系模板与编译

| relation_template | 编译结果 | 必要计算 |
|---|---|---|
| within_allowed_area | unary hard/soft factor | ConstraintIndex + exact geometry |
| avoid_constraint | exclusion factor | precise overlay/buffer |
| near | distance factor | projected CRS distance |
| serve | capacity + network allocation factor | demand、facility、NetworkIndex |
| provide_access | network impedance factor | routable endpoints |
| connect_network | topology factor | endpoints、junction、network nodes |
| follow_alignment | corridor similarity factor | line geometry + tolerance |
| preserve_existing | identity/change factor | canonical binding |
| upgrade_existing | identity + attribute factor | current feature |
| part_of | grouping factor | target graph |
| co_locate | pairwise score | geometry compatibility |
| mutually_exclusive | pairwise exclusion | overlap and capacity |
| precedes | execution dependency | capability and milestone |

自然语言中的“和”“及”“同时”不能统一编译为 OR。默认多个硬约束为 AND，只有明确替代
方案时才使用 OR group。

## 11. GroundedPlanningProblem 与候选几何

    GroundedPlanningProblem
      problem_id
      baseline_snapshot_ref
      intent_graph_ref
      entity_bindings
      target_nodes
      candidate_geometries
      constraint_factors
      relation_factors
      shared_resources
      network_refs
      unresolved_items
      deferred_capabilities
      evidence_refs
      fingerprint

    CandidateGeometry
      candidate_id
      target_id
      geometry_kind
      geometry_ref
      source_feature_refs
      source_bsms
      generation_operation
      generation_parameters_ref
      hard_constraint_status
      suitability_components
      relation_prefilter_scores
      granularity
      confidence

点、线、面在目标设计上使用不同生成器；当前实现只能把已有权威 source geometry 直接作为
execution geometry，不能从 parcel union 自动派生入口点、代表点或中心线：

- facility/site_area：现状点、可建设地块、地块内候选点和入口挂接点；
- zone：满足硬约束的相邻地块集合或连续面；
- road：现状节点、目标入口、合法 corridor 和路由；
- utility_line：对应 domain network 的端点、junction 和 corridor；
- waterfront：真实水体/岸线 geometry 与缓冲、可达关系。

CandidateSite 不能继续作为所有 geometry kind 的通用模型。

## 12. 联合场景求解

采用粗到细流程：

1. 粗筛硬约束、用地兼容、候选上限和粗拓扑；
2. 联合分配目标、候选、容量、排他性和关系软分；
3. 对入选设施和线性目标计算真实网络；
4. 网络不可达时只替换受影响候选；
5. 物化计划点、线、面；
6. 全场景验证关键关系、合规、面积、连续性和可达性；
7. 输出多个可比较场景。

设施选址至少包含 required existing facility、candidate new/relocated facility、需求点
权重、网络阻抗、容量、cutoff、coverage/impedance 目标、未分配需求。

不要求所有专业模型一次塞入一个巨型求解器。可以采用 master problem 选择地块和粗位置，
network subproblem 验证连接，relation evaluator 计算 serve/near/connect，失败产生
局部 cut，master 只重选受影响候选。

## 13. 物化、验证和满足度

每条 desired relation 产生：

    RelationSatisfaction
      relation_intent_id
      scenario_id
      status:
        satisfied | partially_satisfied | violated |
        not_evaluable | deferred
      measured_value
      threshold
      unit
      subject_feature_ref
      object_feature_ref
      evidence_refs
      operation_trace
      finding_refs

示例：

| desired relation | 场景验证 |
|---|---|
| clinic serves settlement | 网络时间、覆盖人口、设施容量 |
| site_area within allowed area | 精确 contains/overlap |
| road connects site_area | 端点吸附、连通分量、可路由性 |
| site_area near river but outside buffer | 投影距离和缓冲相交 |
| facilities mutually exclusive | footprint overlap 和用地冲突 |

VALIDATE 不仅验证 feature 本身，还要验证 PlanningIntentGraph 的 critical edges。

## 14. KG 生命周期与 resume

必须独立持久化：

- l1_snapshot；
- grounded_anchors；
- place_evidence_index；
- entity_binding_set；
- planning_intent_graph；
- grounded_planning_problem；
- scenario_candidate_set；
- planning_scenario；
- relation_satisfaction_set；
- execution_plan；
- delivery snapshot。

影响传播规则：

| 变化 | 需要重算 | 不需要重算 |
|---|---|---|
| provider 暂时 529 | 当前未完成 LLM batch | 已完成 L1、KG、anchor、候选 |
| 一处绑定修正 | 关联目标、因子和受影响场景 | 无关目标 |
| GIS bundle 更新 | 对应 Layer-1、evidence、候选、场景 | 原始 observation |
| worker 新增 | deferred execution task | L1/L2/L3、已完成 grounding |
| 阈值变化 | factor、scenario、validation | entity resolution |
| prompt 更新 | intent artifact 及其下游 | bundle、KG BaseFacts |

checkpoint/pending writes 防止并行 super-step 中已完成任务重跑；artifact digest 支持跨进程
恢复。两者都必须保留。

## 15. 失败语义

| 状态 | 含义 | 重试 | 空间链 |
|---|---|---:|---:|
| query_error | 外部或 KG 查询失败 | 有限 | 可用已有证据继续 |
| ambiguous | 多候选不能可靠区分 | 不盲重试 | 保留候选或人工 |
| unresolved | 没有可绑定实体 | 新证据到来时 | 保留语义目标 |
| insufficient_geometry | 只有粗作用域 | 不靠 LLM | 可粗筛，禁止精确执行 |
| no_candidate | 硬约束后无几何 | 方案修复 | 其他目标继续 |
| infeasible_relation | 目标关系无解 | 局部放宽/人工 | 输出解释和替代场景 |
| transient_timeout | 临时服务超时 | 有预算 | 保留已完成结果 |
| unsupported_capability | 无 typed worker | 不重试 | 持久化 deferred |
| semantic_invalid_output | LLM 违反 schema/domain | 有限 repair | 不重跑上游 |

## 16. 当前实现差异与重构优先级

### P0（当前实现状态）

- L1 observation、identity binding 和 canonical entity 已有独立契约，但全量生产路径仍需继续核验；
- anchor overlay 与 base KG 已有持久化边界，仍需补齐跨进程 resume 的完整审计；
- `PlanningIntentGraph`、`ConstraintFactor`、`GroundedPlanningProblem` 和
  `RelationSatisfaction` 已接入 TARGET_PROJECTION→GROUND→SELECT 的 artifact/contract，
  但尚未成为所有 EXECUTE/DELIVER 校验的唯一依据；
- `site_area`、`facility`、`road`、`linear` 已进入闭集 dispatch，未知线性目标不应再降级为 road；
- 关系模板目前由 typed `dependencies` 和结构化 `spatial_requirements` 编译，尚未完成 LLM
  relation-draft 的闭集输入和全部联合求解约束。

### P1（仍未完成）

- PlaceEvidenceIndex 尚未以全部输入 digest 版本化持久化；
- 当前地点解析主要是单 mention 候选和评分，尚未有 mention graph 联合消歧；
- CandidateSite 偏面状，点/线/面候选和 typed asset contract 不完整；
- site、zone、road、utility 仍缺少完整跨目标联合求解；
- validation 已有 relation satisfaction 数据结构，但还不能对所有 desired relation 逐条给出
  可交付级证明。

### P2（仍未完成）

- SemanticQueryAdapter 的 constraints 和 ambiguity contract 需要真正实现；
- SpatialQueryAdapter 的 bbox overlap 只能保留为粗筛，最终验证要换成精确几何；
- capability registry 与 durable deferred ledger 需要完整接入；
- delivery 需要展示场景差异、证据链和未满足关系。

每个模块改造必须登记：模块名、现状证据、原因、方案、影响范围、优先级、验收命令和
artifact 证据。不得用 TODO、pass 或 mock 冒充核心实现。

## 17. 文件级落地路线

### P0：契约与词表

新增或扩展 EvidenceObservation、EntityBindingSet、GeometryRepresentation、PlanTargetNode、
PlanRelationIntent、RelationTemplate、CandidateGeometry、ConstraintFactor、
GroundedPlanningProblem、PlanningScenario、RelationSatisfaction、DeferredSpatialTask。

验收：schema round-trip、闭集兼容矩阵和错误状态覆盖。

### P1：L1 与地名解析

保留 GroundedAnchor 作为观测接地；PlaceEvidenceIndex 增加 artifact snapshot、完整
fingerprint 和粒度；建立 mention graph；LLM fallback 改为 batch Top-K；增强写入
l1_observations/entity_bindings overlay。

验收：多报告同一设施不重复生成 canonical entity；村级 fallback 不产生精确点；resume 不
重复发起已完成解析。

### P2：关系感知 projection

LLM 输出闭集 target/relation draft；确定性 compiler 生成 PlanningIntentGraph；dependencies
迁移为 typed edges；domain validator 拒绝资产错配、非法主客体和缺证据关系。

验收：关系不会在 target projection 后丢失；不依赖正则分类。

### P3：接地问题

统一解析目标、现状实体、需求实体和共享资源；点、线、面生成 typed candidates；relation
template 编译为 factor；所有 factor 带 source/evidence/operation trace。

验收：每个 critical relation 有 factor，或有明确 unsupported/unresolved。

### P4：联合场景

先实现 facility/site/zone 协调，再接 road network 和 utility typed target；生成至少两个可
比较场景；局部不可达只产生 cut。

验收：地块冲突、设施服务、道路连接和容量在同一场景一致。

### P5：执行与验证

按 asset_kind/capability 派发；无 worker 的任务进入 deferred；精确几何与网络验证；
每条 critical relation 输出 RelationSatisfaction。

验收：未知线性目标不进入 road worker；feature 合法但关系未验证时不能交付为完整方案。

## 18. 金田村真实数据验收

以当前状态文档记录的真实基线为起点：660 个地块、131 条道路、235 个约束图层、约
25,068 个 KG triples。运行时必须重新记录 bundle digest、实体数、关系数和 artifact digest，
不能把本文数字当固定断言。

### 18.1 L1 与地名

- 每个真实 observation 有 source span；
- GroundedAnchor artifact 可在新进程恢复；
- 多次提及同一设施时 canonical entity 数量合理且来源不丢；
- ambiguous、unresolved、village_scope 可见；
- 设施、聚落、道路、水体和模糊区域各抽查一类；
- LLM 不生成 BSM、坐标或 WKT。

### 18.2 设施 KG

- 现状设施绑定真实 point/footprint，或明确标为 reported_current；
- serves/nearby 只参与召回；
- 服务覆盖使用真实道路 NetworkIndex；
- 输出未挂接、不可达、超阈值、容量不足需求；
- 新建、保留、提升场景可比较。

### 18.3 规划关系与场景

- 每个 target 有 source claim；
- 每个 critical relation 有 factor 和 satisfaction；
- 道路、设施、项目、分区关系没有在阶段间丢失；
- AND/OR 与原意一致；
- 不能物化的目标保持 deferred/unresolved，不伪造 geometry；
- 至少两个场景可渲染、可解释、可比较、可验证。

## 19. Definition of Done

只有同时满足以下条件，才称为完整的空间目标落地：

1. L1 observation 和 grounded anchor 可持久化、恢复；
2. canonical binding 有稳定标识、粒度、来源和不确定性；
3. 现状 KG 与规划场景分层；
4. LLM 只做闭集语义编译；
5. target、asset、operation、relation 贯穿全链；
6. 每个目标有真实候选 geometry 或明确不可物化状态；
7. 多目标通过关系因子联合求解；
8. 设施服务由真实网络和需求计算；
9. 每个关键关系有可审计 satisfaction；
10. 缺 worker 的目标可 deferred，能力增加后可 resume；
11. checkpoint 和 digest 阻止无关阶段重跑；
12. 真实金田村输入生成可渲染、可解释、可比较、可验证的规划场景。

## 20. 外部依据

- [OGC GeoSPARQL 1.1](https://docs.ogc.org/is/22-047r1/22-047r1.html)：Feature、Geometry、
  多种拓扑关系，以及定性关系与定量计算的兼容。
- [ISO 19155-2 Place Identifier linking](https://www.iso.org/standard/63593.html)：地点标识
  与其他编码中的 feature/object 通过稳定标识链接。
- [INSPIRE Geographical Names Technical Guidelines](https://knowledge-base.inspire.ec.europa.eu/publications/inspire-data-specification-geographical-names-technical-guidelines_en)：
  地名数据应带稳定标识、名称、类型、几何和来源。
- [USGS GNIS-LD](https://www.usgs.gov/publications/gnis-ld-serving-and-visualizing-geographic-names-information-system-gazetteer-linked)：
  权威 gazetteer、feature type ontology、共指链接与地理数据融合。
- [A survey on geocoding](https://link.springer.com/article/10.1007/s10579-024-09730-2)：地名解析
  要结合文本上下文和地理数据库，复杂区域需要 polygon-aware 表达和评估。
- [W3C PROV-O](https://www.w3.org/TR/prov-o/)：使用 Entity、Activity、Agent 表达 provenance。
- [ArcGIS GeoPlanner workflow](https://doc.arcgis.com/en/geoplanner/latest/get-started/what-is-geodesign-for-arcgis.htm)：
  以现状评估、多场景、指标反馈和方案比较形成 geodesign 闭环。
- [ArcGIS Project Screening](https://doc.arcgis.com/en/geoplanner/latest/documentation/perform-project-screening.htm)：
  对设计图层和证据图层显式计算相交、距离、包含等关系。
- [ArcGIS Location-Allocation](https://doc.esri.com/en/arcgis-pro/latest/help/analysis/networks/location-allocation-tutorial.html)：
  设施候选、需求点、道路网络和阻抗共同决定服务分配。
- [OGC LandInfra 1.0](https://docs.ogc.org/is/15-111r1/15-111r1.html)：土地和基础设施对象需要
  明确的 feature、设施、项目与关系语义。
