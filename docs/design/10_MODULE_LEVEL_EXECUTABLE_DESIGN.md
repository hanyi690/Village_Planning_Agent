# 10 模块级可执行设计：从动态 GIS 认知到规划成果

> Status: TARGET / NORMATIVE MODULE DESIGN
>
> 本文件是后续实现的模块级基线，统一 Context Runtime、Structured Runtime、DATA、KG、EVIDENCE、L1、L2、L3、GROUND、SELECT、EXECUTE 和 DELIVER 的职责、产品、依赖、失败语义及验收方式。字段级定义仍以 Pydantic contract 和测试为准。

## 1. 总体不变量

1. DATA 可以接收任意文件、字段、图层、几何类型和 CRS；固定字段名只是兼容映射。
2. KG 是认知世界模型，描述实体、部件、关系、能力和语义假设，不拥有最终可执行几何。
3. EVIDENCE 管理来源、事实、冲突、置信度和可调度的证据缺口。
4. L1、L2、L3 是依赖树上的产品生产阶段，不是三批互不相干的长报告。
5. 所有 LLM 输入由集中 Context Runtime 转成有限表格页；所有 LLM 输出由 Structured Runtime 转成有限扁平 rows。
6. GROUND 只做语义目标到实体/表示的绑定；SELECT 只选择可计算本地资源；EXECUTE 只执行确定的空间操作。
7. 外源地图只能是缓存化 observation/source，没有本地 geometry 和 digest 时不能进入 EXECUTE。
8. DELIVER 只消费 DeliverySpatialSnapshot，不回查 Bundle、KG、Evidence 或 provider。

## 2. 统一产品流和引用

```text
SourceDataset/SourceFeature
        ↓ Data semantic profile
SourceObservation / Capability rows
        ↓ L1
L1Fact / LocationMention / EvidenceGap
        ↓ dependency tree
L2Claim / ConstraintRule / DemandRequirement
        ↓ dependency tree
L3Target / SpatialRequirement / CandidateRequest
        ↓ GROUND
EntityBinding / RepresentationBinding
        ↓ SELECT
ExecutableResourceRef / SelectionDecision
        ↓ EXECUTE
PlannedRepresentation / ChangeSet / ExecutionTrace
        ↓ DELIVER
DeliverySpatialSnapshot / GeoJSON / PNG / HTML
```

统一引用必须分开：

```text
source_ref          来源数据或来源响应
fact_ref            L1 事实产品
evidence_ref        Evidence 检索条目
entity_ref          KG WorldEntity
part_ref            KG EntityPart
representation_ref  KG/Data 空间表示
resource_ref        可加载、带 CRS/digest 的本地资源
claim_ref           L2 综合判断或规则
target_ref          L3 规划目标
change_ref          EXECUTE 变更
artifact_ref        CAS 工作流产物
```

任何模块不得把一种 ref 当成另一种 ref 使用。

## 3. 共享基础设施

### 3.1 Context Runtime

实现入口：`backend/app/infrastructure/context_runtime/manager.py`、`runtime.py`、`projection_builder.py`、`budgets.py`、`table_renderer.py`。

Context Runtime 负责构建、版本化和缓存 `PlanningContext`，固定 session/data snapshot/KG/artifact 版本，读取只读 `ExternalObservationSnapshot`，生成阶段 projection、分页 cursor 和有限表格，并拒绝跨 snapshot/context version 混用。

业务模块不得直接拼接全部报告、自己截断 token、自己读取 provider 或用 checkpoint 内联 JSON 替代 CAS artifact。

### 3.2 Structured Runtime

实现入口：`backend/app/infrastructure/structured_runtime/parser.py`、`validator.py`、`assembler.py`、`facade.py`；表格协议入口为 `backend/app/infrastructure/llm/table_protocol.py`。

Structured Runtime 负责 provider 调用、有限重试、schema/rows 校验、失败分类、artifact 组装和 digest。一次调用只允许当前页的扁平 rows：默认 32 行、12 列、6200 字符，嵌套深度超过 2 直接拒绝；超限必须返回 continuation，由程序分页。

LLM 不得一次接收完整 L1Snapshot、KG 或 Bundle，也不得一次输出完整 WorldModel、PlanningProgram 或 ExecutionPlan。

## 4. DATA 模块

### 4.1 输入

GeoJSON、Shapefile、GPKG、CSV、Excel、PDF、图片、provider cache；任意字段、嵌套属性、空值、未知枚举、混合几何、任意 CRS 和多图层版本。

### 4.2 输出

`SourceDataset`：数据集身份、版本、URI、CRS、digest、读取能力。

`SourceFeature`：

```text
source_feature_ref / dataset_ref / layer_ref
geometry / geometry_kind / source_crs
raw_attributes / normalized_claims / unmapped_attributes
validity_diagnostics / content_digest
```

`SpatialRepresentation`：

```text
representation_ref / entity_ref 或 unresolved_source_ref
purpose / geometry_ref / resource_ref / crs
source_snapshot_ref / derived_from / component_refs
```

未知图层和字段进入 semantic classification，保留原始值和候选语义。LLM 可以判断 candidate_type 和 candidate_role，但不能删字段、创建权威实体或直接生成规划几何。

### 4.3 坐标与失败

外部观察保存 native 和 WGS84；内部聚类与空间检索使用 WGS84；AMap 的 GCJ-02 只在缓存读取时转换一次；天地图不套用 GCJ-02；腾讯只处理 `lat/lng` 轴顺序；EXECUTE 按本地资源 CRS 投影并按交付约定输出。

缺少 BSM、DLBM、固定 layer name 或固定字段不能阻止 source snapshot 保存，只能标为 unresolved。几何错误、缺失 CRS、无法解析属性进入 diagnostics，不能静默丢弃。

## 5. KG / Cognition 模块

### 5.1 实体模型

```text
WorldEntity
  ├── EntityPart
  └── SpatialRepresentation*
```

WorldEntity 是稳定语义对象；EntityPart 是可独立约束、统计或编辑的部件；SpatialRepresentation 是随数据版本变化的点、线、面、多面、范围或派生几何。

无名地块也必须进入 KG：使用 dataset + feature identity + geometry digest 生成 entity_ref，label 可以为空，未知字段进入 claims/unmapped_attributes；语义不足时保持 `WorldEntity + semantic_hypotheses`，状态为 unresolved。

大地块共享用途/权属/约束并作为一个操作对象时保持一个 EntityPart；只有语义、约束或操作不同才拆 EntityPart；索引/渲染切片只是 representation component。

道路采用整体、连续段、表示三层；地点可以同时拥有定位点、建筑面、服务范围面和管理边界面。

### 5.2 外源观察

```text
ExternalObservation
  ↓ spatial support cluster
ExternalEntitySupport
  ↓ accepted/ambiguous assertion
WorldEntity
```

同一坐标范围内默认形成 support cluster，但名称、类型、行政范围或时间冲突时仍保持 ambiguous。外源观察不能直接声明为 Road、Parcel、Facility 或 WaterBody。

### 5.3 输出与禁止

KG 输出实体、部件、表示、关系、capability、source/assertion lineage、confidence 和 ambiguity。KG 不输出 EXECUTE geometry、planned layer，也不把 provider route polyline 当本地道路。

## 6. EVIDENCE 模块

### 6.1 输入和输出

输入为 Data source feature、KG entity/representation/capability、L1Fact、L2Claim、L3Target、文档 source span、地图缓存和 EvidenceGap。

输出为 `EvidenceFact`、`EvidenceSource`、`EvidenceConflict` 和可调度的 `EvidenceGap`。

`L1Fact` 是 L1 生产产品；`EvidenceFact` 是统一检索投影；`EvidenceSource` 是来源。三者只能通过 refs 连接，不能复用同一个 fact_id。

外源缓存投影必须使用 `fact_type=external_map_observation`、`evidence_role=location_binding`、`source_kind=external_map_cache`、`authority=advisory`；它不能宣称完整边界或法定几何。

### 6.2 Gap 和检索顺序

每个 gap 必须有 `gap_ref`、`consumer_dimension`、`requirement`、`subject_ref/subject_text`、`missing_fields`、`allowed_sources`、`retrieval_capability`、`priority` 和 `status`。

只有 `ready_for_retrieval` 且本地 Data、cache 或 KG 存在能力时才立即补充；否则进入 `not_available` 或 `requires_human_confirmation`，不得由 LLM 猜测填平。

检索顺序为 local Data/KG → cached map observations → local text/reports/RAG → 显式授权在线 provider；本阶段默认 cache-only。

## 7. L1：OBSERVE

L1 只回答“输入中观察到了什么”，不回答“应该怎么规划”。输入是 ContextHeader、Data SourceObservation 表、文档 source index、Evidence source/fact 表和 L1 dimension contract。输出是 `L1Fact rows`、`LocationMention rows`、`SpatialObservation rows`、`DerivedMetric rows`、`EvidenceGap rows` 和 L1Gate。

每个 L1Fact 必须有 `fact_ref`、`fact_kind`、`dimension`、`subject_text 或 subject_ref`、`predicate/value/unit`、`inference_level`、`source_refs`、`source_span/source_feature_ids` 和 `snapshot_ref`。L1 可以写 `needs_retrieval`，不能把 name-only mention 变成已定位实体。

L1 的 location、socio_economic、land_use、traffic、public_services、natural_environment、historical_culture 等维度都只生产本领域观察和缺口，不生产 L3 项目或最终 geometry。

## 8. L2：STRATEGIZE

L2 是跨 L1 维度的综合和规则生产层，回答“问题是什么、目标和评价规则是什么”。输入为上游 L1Fact rows、EvidenceGap 状态、KG capability rows 和 L2 input product。输出为 `L2Claim`、`ConstraintRule`、`DemandRequirement`、`ServiceRequirement`、`SuitabilityFactor`、`PriorityDecision` 和 L2Gate。

每个产物必须保留 `input_fact_refs`、`evidence_refs`、`unresolved_gap_refs`、适用范围和 confidence。resource_endowment、planning_positioning、development_goals、planning_strategies 等 L2 维度只生产规则、需求和评价方法，不直接选择地块或创建 planned geometry。

## 9. L3：PLAN / TARGET PROJECTION

L3 把 L2 规则和 L1 事实转成规划目标、项目包和空间需求，回答“要规划什么、需要什么空间能力”。输入为 L1/L2 artifact refs、dependency product rows、KG capability、Data representation capability 和 Evidence gap。

输出为 `PlanningClaim`、`PlanningProgram`、`Target`、`SpatialRequirement`、`CandidateRequest` 和 L3Gate。每个 target 必须有 `target_ref`、`claim_family`、`subject_ref 或 subject_text`、`operation`、`representation_purpose`、`required_capabilities`、`constraint_refs` 和 `evidence_refs`。

L3 不创建 candidate_id、parcel BSM、geometry、scenario approval 或 execution task。

## 10. GROUND

GROUND 是语义目标到世界模型的绑定层，回答“这个目标指向哪个 WorldEntity、使用哪个 SpatialRepresentation、哪些证据支持、是否仍有歧义”。

输入为 L3 Target/SpatialRequirement、Evidence candidate rows、KG entity/part/representation rows、Data capability rows、location mention、external observation support 和 world model snapshot。

输出 `GroundBinding`：

```text
target_ref / entity_ref / part_ref / representation_ref / resource_ref
geometry_kind / source_snapshot_ref / source_feature_refs
evidence_refs / confidence / ambiguity / diagnostics
```

name/alias 只用于召回；外源 observation 只能放入 evidence_refs；representation purpose 决定点、中心线、范围面或管理边界；没有本地 representation 时返回 `unresolved_geometry`；低置信度或冲突时返回 `ambiguous`。

## 11. SELECT

SELECT 把 GROUND 绑定结果和 L3 操作需求编译为可计算的本地资源选择，不负责执行。

输入为 GroundBinding、target/operation/representation_purpose、Data capability/resource catalog、KG allowed_operations、约束关系、evidence_refs 和审批状态。

输出 `SelectionDecision`：

```text
selection_ref / target_ref / entity_ref / representation_ref / resource_ref
operation / operation_parameters / input_crs / resource_digest
constraint_refs / evidence_refs / status / rejection_reason
```

资源必须有 dataset/resource identity、feature/geometry ref、geometry kind、CRS、source snapshot、content digest 和 supported operation。parcel solver 可以兼容 BSM，但必须同时拥有完整资源信息。`external-observation:*` 只能是 evidence ref，不能是 resource_ref 或 representation_ref。

## 12. EXECUTE

EXECUTE 对 SELECT 已批准的本地资源执行确定的空间操作，创建 planned representation 和 changeset。

输入为 SelectionDecision、真实本地 geometry/resource、operation/parameters、input/output CRS、constraint result、approval artifact 和 snapshot digest。

输出为 `PlannedEntity`、`PlannedRepresentation`、`ChangeSet`、`ExecutionTrace` 和 `ExecutionResult`。每个 planned geometry 必须记录 `change_ref`、`target_ref`、`input_resource_ref`、`input_representation_ref`、`source_snapshot_ref`、`world_model_digest`、`operation`、`parameters`、CRS、`geometry_digest` 和 `approval_ref`。

允许的操作必须来自 capability：buffer、offset、intersect、difference、union、split、merge、snap、topology repair、assign、reclassify、point placement、network connection 和 representation derivation。LLM 文本不能动态执行任意空间函数。

没有本地 geometry、CRS、snapshot/digest、approval 或 capability，或者目标仍为 ambiguous/unresolved_geometry 时，EXECUTE 必须 fail-closed。

## 13. DELIVER / RENDER

DELIVER 只接受 `DeliverySpatialSnapshot`，其中包含 baseline/planned representations、changesets、render metadata 和 quality diagnostics。输出 GeoJSON、PNG、HTML、quality report、lineage report 及 baseline-only/diagnostic-only 状态。

planned feature 必须有真实 geometry，并至少具备 `resource_ref`、`representation_ref`、`source_snapshot_ref` 或 `world_model_digest` 之一。没有 geometry 时不得画占位线面；没有 lineage 时只能标记 diagnostic-only。

## 14. 依赖树和 Gap 传播

```text
L1Fact rows
  ↓ fact_ref / source_ref
L2Claim / ConstraintRule rows
  ↓ claim_ref / requirement_ref
L3Target / SpatialRequirement rows
  ↓ target_ref / candidate_request_ref
GROUND Binding rows
  ↓ representation_ref / evidence_refs
SELECT Resource rows
  ↓ operation + approved lineage
EXECUTE ChangeSet rows
```

修改一个上游 fact 时，只沿 dependency tree 重算受影响的产品；无关维度不重新生成完整上下文。L1 gap 经 Evidence 补充后只更新对应 source/fact rows，再向下游传播。

## 15. 命名和表格协议

推荐命名空间：

```text
l1.fact.<dimension>.<fact_kind>.<hash>
evidence.source.<source_kind>.<hash>
evidence.observation.<provider>.<stage>.<hash>
evidence.gap.<consumer_dimension>.<requirement>.<hash>
l2.claim.<dimension>.<claim_family>.<hash>
l3.target.<dimension>.<claim_family>.<hash>
ground.binding.<target>.<hash>
select.resource.<operation>.<hash>
execute.change.<target>.<hash>
```

LLM 只消费表格页：`source_observation_rows`、`dependency_fact_rows`、`constraint_gap_rows`、`target_rows`。一行只代表一个事实、实体、约束、gap 或目标；关系使用 `from_ref/relation/to_ref` 三列；长文本和几何只保留摘要及 ref；复杂对象由程序按 ref 组装。

默认页大小为 32 行、12 列、6200 字符；未知列、超行、超深度、缺主键、直接返回 geometry 坐标且缺 representation/source ref 都必须由 Structured Runtime 拒绝。

## 16. 模块验收和迁移顺序

验收必须覆盖：无名地块、同一实体多表示、大地块部件、道路连续段、未知字段、多 CRS、多 provider 支持簇、L1/L2/L3 产品 refs、immediate gap、GROUND ambiguity、SELECT external ref 拒绝、EXECUTE lineage 和 DELIVER diagnostic-only。

迁移顺序：先固定 Context/Structured Runtime；再迁 DATA SourceFeature/Representation；再统一 L1 表格产品；再迁 L2/L3 dependency rows；再改 Evidence gap；然后迁 GROUND、SELECT、EXECUTE，最后收紧 DELIVER。实际状态只记录在 `05_MIGRATION.md` 和 `architecture/CURRENT_RUNTIME.md`。

## 17. LLM 推理能力的正确落点

LLM 的价值不是一次性生成庞大的嵌套规划对象，而是在 Context Runtime 提供的有限表格页上完成可审计的语义变换。每次推理都必须回指输入行和来源 ref，并产生有限输出 rows；几何计算、唯一身份、版本、权限和执行安全由程序负责。

### 17.1 允许 LLM 推理的内容

| 层 | LLM 可以推理 | 必须回指 |
|---|---|---|
| DATA 语义 | 未知字段/图层的候选语义、角色、几何用途、字段之间的对应关系 | source_feature_ref、原始字段、样本行 |
| L1 | 从文本和 GIS 观察归纳事实、识别地点 mention、区分 observed/derived/inferred、提出 gap | source_ref、source_span、source_feature_ref |
| L2 | 跨维度归纳问题、解释因果链、形成目标指标、比较约束和机会、提出评价规则 | L1 fact_ref、Evidence ref、冲突 ref |
| L3 | 将 L2 规则编译为规划目标、项目意图、空间需求、所需能力和优先级 | L2 claim_ref、requirement_ref、Evidence gap |
| GROUND 辅助 | 对候选实体/表示排序、解释名称/别名/类型冲突、提出 ambiguous/unresolved | candidate entity_ref、representation_ref、evidence_refs |
| EVIDENCE | 判断 gap 是否可由已有来源补充、选择允许的检索能力、解释来源冲突 | gap_ref、source_ref、capability_ref |
| SELECT 辅助 | 在已生成的可行候选中按目标偏好排序、说明选择理由 | candidate/resource ref、constraint refs |

### 17.2 不允许 LLM 单独决定的内容

- `entity_ref` 的最终唯一身份；
- 坐标转换、距离、拓扑、面积、长度和缓冲结果；
- 从外源点或文本创建本地 polygon/line；
- 将名称相同的对象强制合并；
- 将道路整体、连续段、中心线和红线混为一个几何；
- 选择没有 CRS、digest 或 source snapshot 的 resource；
- 执行任意空间函数；
- 跳过审批、版本校验或 capability 校验；
- 直接写入 KG 权威实体、planned state 或最终渲染层；
- 将无法验证的推断标记为 observed/verified。

### 17.3 五种可审计推理

1. **分类**：判断未知字段、图层或事实的候选语义，输出候选和置信度，不覆盖原始值。
2. **归纳**：从多条 L1Fact 归纳 L2Claim，例如由道路宽度、人口集中和会车困难归纳“村中心连接段优先拓宽”。
3. **比较**：比较候选实体、表示或规则，明确优缺点和未解决冲突。
4. **缺口规划**：判断 gap 需要什么字段、允许什么来源、是否能立即补充，并生成下一步检索行。
5. **目标编译**：把已确认的 L2 规则转成 L3 target、operation、representation purpose 和 required capabilities，但不输出 geometry。

每种推理都必须输出扁平行：

```text
reasoning_ref / reasoning_kind / input_refs
conclusion / confidence / uncertainty
rejected_alternatives / next_action
```

### 17.4 推理与确定性计算的分工

```text
LLM：语义理解、归纳、比较、解释、提出假设和补证据计划
程序：ref 解析、实体 ID、坐标归一化、空间运算、约束求解、版本检查、审批、渲染
```

如果 LLM 认为某外源点对应某个本地地块，只能产出候选 `entity_ref`/`representation_ref`、`evidence_refs`、confidence、`reasoning_ref` 和 `status=candidate`。GROUND 随后必须用确定性几何、CRS、距离和行政范围检查验证；没有本地 representation 时只能保持 `unresolved_geometry`。

### 17.5 推理质量门

阶段 validator 必须检查：结论引用至少一个输入 ref；observed/derived/inferred/pending 区分正确；外源 observation 没有被当成 geometry/resource；没有未声明的实体、坐标、BSM 或 candidate；冲突没有被隐藏在自然语言中；输出了下一步 gap/action；没有超出表格页预算。

LLM 可以失败、低置信度或无法判断，但不能静默制造完整规划对象。正确失败结果是带来源的 `ambiguous`、`unresolved`、`source_gap` 或 `requires_human_confirmation`。

## 18. Evidence Gap 的即时调度和完整执行时序

### 18.1 不是“等到 L3 再补”，而是按最早可判定点处理

Evidence Gap 的调度原则是：

```text
发现 gap
  ↓
判断是否已经具备补充所需的 subject、字段和 capability
  ├─ 是：当前阶段立即补充
  └─ 否：记录为 deferred_until=<最早可判定阶段>
```

“即时”不是无条件地调用外部 provider，而是在当前阶段使用允许的本地能力、缓存、KG 或已授权的 Evidence adapter。每个 gap 必须有 `earliest_resolution_stage`，防止所有缺口被粗暴推迟到 L3。

### 18.2 Gap 类型和最早处理阶段

| Gap 类型 | 最早处理阶段 | 典型来源/动作 | 是否可以等待 L3 |
|---|---|---|---|
| source_readability | Data PREPARE | 解码、文件读取、CRS 检测、几何修复 | 否，必须先处理 |
| schema_semantics | Data PREPARE / L1 | 字段/图层语义分类、未知属性保留 | 否，至少先得到 candidate |
| admin_scope | Data / L1 | 本地边界、已有缓存反查、行政范围匹配 | 否 |
| place_binding | L1 | 本地 Data、KG、缓存地图观察、别名匹配 | 通常不应等到 L3 |
| source_conflict | L1 / Evidence | 多来源对照、冲突行、人工确认请求 | 否，先显式化 |
| metric_definition | L2 | 单位、统计口径、时间基线、标准来源 | 可等 L2，不应提前猜 |
| demand_definition | L2 | 需求点、人口口径、服务半径和覆盖规则 | 需要 L2 语义 |
| representation_purpose | L3 / GROUND | 根据目标判断 point/centerline/footprint/service area | 可以等到目标确定 |
| candidate_geometry | GROUND | 通过 entity/representation/resource 查询本地几何 | 不能在 L1 猜 |
| solver_capability | SELECT | 检查 resource、CRS、operation 和约束能力 | 不能等 EXECUTE |
| approval_or_lineage | SELECT / EXECUTE | 审批、snapshot、digest、操作血缘校验 | 必须在执行前解决 |

### 18.3 Evidence Scheduler 的行为

Evidence Scheduler 不是一个只在 L3 运行的补救模块，而是跨阶段服务，输入为：

```text
gap_ref
earliest_resolution_stage
allowed_sources
retrieval_capability
current_context_version
budget
```

它返回：

```text
resolved_rows
new_source_refs
new_evidence_refs
remaining_gap_rows
next_stage
diagnostics
```

调度器必须遵守：

1. 当前阶段可解决的 gap 立即执行；
2. 同一个 gap 在相同 snapshot/context version 下不得重复请求；
3. provider cache 命中优先于在线请求；
4. `failed`、`success_empty`、`not_attempted` 和 `missing` 不得互相改写；
5. 补充后的 rows 进入当前阶段的 Context projection，并更新下游依赖影响树；
6. 无法解决的 gap 带原因向下游传递，而不是伪装成已解决；
7. 需要目标语义才能确定的 gap 必须记录 `deferred_until`，不能盲目预取。

### 18.4 实际执行时序

```text
T0  SESSION_OPEN
    └─ 建立 session、输入清单、运行模式和预算

T1  DATA_PREPARE
    ├─ 读取任意文件/图层/字段/CRS
    ├─ 生成 SourceDataset、SourceFeature、能力表
    ├─ 读取已有 AMap/天地图/腾讯缓存（cache-only）
    ├─ 立即解决 source_readability、schema_semantics、admin_scope
    └─ 建立 Context v1 和 source snapshot

T2  L1_OBSERVE（同层维度可并行）
    ├─ 每个维度消费自己的 source_observation_rows 表页
    ├─ 输出 L1Fact、LocationMention、EvidenceGap rows
    ├─ 每页结束后立即调度 place_binding、source_conflict 等 gap
    ├─ 解决结果回写当前 L1 projection，不重发全部上下文
    └─ 所有 L1 dimension gate 通过后固化 L1Snapshot

T3  L2_STRATEGIZE（按 dependency wave）
    ├─ wave 1 消费已完成的 L1 产品行
    ├─ 后续 wave 只消费上游 claim/fact refs
    ├─ 立即处理 metric_definition、demand_definition 和 policy_source gap
    ├─ 生成 L2Claim、ConstraintRule、DemandRequirement、SuitabilityFactor
    └─ L2 gate 通过后固化 L2Strategy

T4  L3_PLAN（按 dependency wave）
    ├─ 消费 L1/L2 产品行和 capability 表
    ├─ 生成 Target、SpatialRequirement、CandidateRequest
    ├─ 只有在目标目的明确后才产生 representation_purpose gap
    ├─ 不生成 geometry，不执行空间操作
    └─ 固化 PlanningProgram / L3Gate

T5  GROUND
    ├─ 查询 KG entity/part/representation 和 Data resource
    ├─ 使用 Evidence 结果进行候选排序、冲突解释和别名合并
    ├─ 解决 candidate_geometry、representation_purpose、identity_conflict
    ├─ 输出 accepted / ambiguous / unresolved_geometry binding
    └─ 只有 accepted binding 才进入 SELECT

T6  SELECT
    ├─ 检查 resource_ref、representation_ref、CRS、digest 和 capability
    ├─ 应用 L2/L3 约束和选择目标
    ├─ 可以调用 LLM 对合法候选进行偏好排序
    ├─ 立即处理 solver_capability 和 missing_resource gap
    └─ 输出 SelectionDecision 或显式 rejected/unresolved

T7  APPROVE → EXECUTE
    ├─ 检查 approval、context/snapshot/world digest
    ├─ 加载本地 geometry
    ├─ 执行声明过的空间操作
    ├─ 生成 PlannedRepresentation、ChangeSet、ExecutionTrace
    └─ 任一 lineage/CRS/geometry 失败则原子中止

T8  VALIDATE / RECONCILE
    ├─ 校验 planned geometry、拓扑、面积、约束和 changeset
    ├─ 把缺口分派回责任阶段（L2、L3、GROUND、SELECT 或 EXECUTE）
    └─ 不让 DELIVER 通过缺少实际 geometry 的结果

T9  DELIVER
    ├─ 只读取 DeliverySpatialSnapshot
    ├─ 生成 GeoJSON、PNG、HTML 和诊断
    └─ 缺 geometry/lineage 时输出 diagnostic-only 或 baseline-only
```

### 18.5 并行和门禁

- T1 Data prepare 必须完成 source snapshot 后才能派发 L1；
- L1 同层维度可以并行，但各自 gap 只回写自己的产品行；跨维度 gap 进入共享 Evidence Scheduler；
- L2 按 dependency wave 执行，未完成的上游产品不能被下游维度读取；
- L3 可以并行处理互不依赖的 target，但 GROUND 必须等对应 target rows 固化；
- GROUND、SELECT、EXECUTE 对同一个目标是串行门禁；
- 一个目标失败不得伪造其他目标成功，也不能让缺 geometry 的目标进入 DELIVER。

### 18.6 为什么有些 Gap 仍然要等到 L3

延迟不是因为 Evidence 被动，而是因为某些问题只有在下游语义明确后才有确定答案。例如：

- “这个地点应该使用 point 还是 service-area polygon？”必须等 L3 明确操作目的；
- “大地块是否整体使用还是拆分？”必须等目标的约束和操作范围明确；
- “道路应使用 centerline 还是 corridor？”必须等 L3 的道路操作类型明确；
- “候选地块按什么指标排序？”必须等 L2/L3 目标权重明确。

这些 gap 要在早期记录并尽早补充它们能够补充的部分（名称、别名、类型、来源、候选表示），但最终的 representation purpose 和 candidate selection 必须延迟到 GROUND/L3 语义确定后处理。
