# 01 L1 可执行设计：从来源观察到可消费的现状事实

> Status: TARGET with PARTIAL implementation
>
> 本文件是 L1 生命周期、事实接纳、地点工作项和 L1 最终产品的设计权威。当前代码事实见
> <code>../architecture/CURRENT_RUNTIME.md</code>，迁移完成度只见 <code>05_MIGRATION.md</code>。

## 1. 职责与边界

L1 回答“当前资料能够证明村庄现在是什么样”，不回答“应该规划什么”。它必须把来源内容
转换为有地址、可验证、可撤销的事实和地点工作项，并把身份解析留给 Evidence、L1-GROUND
和 Cognition。

L1 负责：

- 从已准入的 <code>current_evidence</code> 中形成 source observation；
- 形成 <code>L1FactRow</code>、<code>L1LocationMention</code>、
  <code>L1RelationMention</code>、冲突和 <code>L1Gap</code>；
- 校验 source span、来源角色、计量单位、时间和推理等级；
- 冻结观察结果，引用后续 binding/commit 产物；
- 为 L2/L3 发布只读、版本一致的 L1 最终视图。

L1 不负责：

- 创建或修改 <code>WorldEntity</code>、<code>SpatialRepresentation</code> 或 geometry；
- 直接写 World Model/KG；
- 把外源 provider point 当成本地执行几何；
- 生成 L2 策略、L3 目标、候选、scenario 或 execution task；
- 为了让 Gate 通过而补写来源中不存在的数值、名称或空间关系。

## 2. 当前实现与目标差异

| 能力 | 当前代码事实 | 设计终态 |
|---|---|---|
| 事实产物 | 已有 <code>L1Snapshot</code>、fact、mention、gap 兼容 contract | 收敛为 <code>L1ObservationSnapshot</code> 与分型 rows |
| 有界输入 | 已有 <code>L1InputContext</code>、<code>L1DimensionInput</code>、分页和 digest | 保留；补齐统一 source-span 验证报告 |
| 观察与绑定分离 | 已有 <code>EvidenceObservationSnapshot</code>、binding sidecar | 收敛为 <code>L1BindingSnapshot</code>，由 final manifest 引用且不修改冻结观察 |
| WM 提交回执 | 已有 <code>L1WorldProjectionSnapshot</code> 和 identity commit envelope | 回执必须成为 L2/L3 的前置引用 |
| 冲突处理 | 已有 fact/gap 状态和部分聚合逻辑 | 补齐逐 predicate 冲突组、authority 与 supersedes 语义 |
| 最终 L1 产品 | 当前由多个 artifact ref 组合表达 | 增加轻量 <code>L1ProductManifest</code>；不复制完整事实或 binding |

表中的“当前代码事实”不等于已通过真实会话验收；完成度仍以迁移账本为准。

## 3. 规范产品生命周期

~~~text
SessionDataSnapshot + SourceIndex + WorldModelSnapshot v0
  → L1DimensionInput pages
  → L1ObservationSnapshot
      ├─ L1FactRow
      ├─ L1LocationMention
      ├─ L1RelationMention
      ├─ L1GroundingRequest
      ├─ L1Gap
      └─ ConflictGroup rows
  → Evidence bounded enrichment
  → EvidenceObservationSnapshot
  → L1-GROUND
  → L1BindingSnapshot
  → Cognition validation and atomic commit
  → L1WorldProjectionSnapshot / WorldModelSnapshot v1
  → binding revalidation against v1
  → L1ProductManifest
  → L2 / L3 bounded projections
~~~

观察、绑定和提交是三个不可变事务。不得加载 <code>L1ObservationSnapshot</code> 后修改
<code>location_mentions</code> 并覆盖同一 artifact。

最终产品采用引用封套：

~~~text
L1ProductManifest
  manifest_ref
  observation_product_ref
  l1_snapshot_ref
  binding_snapshot_ref
  world_projection_ref
  world_model_snapshot_ref
  world_model_snapshot_digest
  fact_row_digest
  binding_row_digest
  open_gap_refs
  terminal_gap_refs
  status
~~~

<code>status</code> 只允许 <code>ready | partial | human_required | blocked</code>。
它是产品状态，不是 workflow 路由指令。

## 4. 行契约

### 4.1 L1FactRow

每个事实至少包含：

~~~text
fact_id
dimension_key
subject_ref or unresolved_subject_ref
predicate / semantic_type
value / unit / counting_basis
valid_time
fact_kind
inference_level
source_refs
source_span_refs
evidence_refs
derivation_ref
confidence_components
status
supersedes
~~~

<code>fact_kind</code> 表达来源形态，<code>inference_level</code> 表达推理距离，两者不得混用。
建议状态：

~~~text
candidate → accepted
          → conflicted
          → rejected
accepted  → superseded
candidate → pending_evidence
~~~

只有 <code>accepted</code> 事实进入 L2/L3 的默认事实投影；其他状态只进入诊断或显式冲突上下文。

### 4.2 L1LocationMention

地点工作项至少包含：

~~~text
work_item_ref
mention_ref
literal_name
normalized_name
role
scope_mentions
relation
related_mentions
source_refs
source_span_refs
source_feature_refs
evidence_refs
dimension_key
admission_status
~~~

<code>L1LocationMention</code> 是检索工作项，不是实体断言。名称相同、行政范围相同或 provider
返回坐标均不能在 L1 内把它升级为 canonical entity。

### 4.3 L1RelationMention

关系 mention 保留原始语义，不把 anchor 或空间测量提前固化：

~~~text
relation_mention_ref
subject_mention_ref
relation_type_candidate
anchor_mention_refs
literal_expression
typed_parameter_candidates
source_refs / source_span_refs
evidence_refs
status
~~~

“位于、邻近、沿、连接、服务、避让、属于”等表达都必须先形成 relation mention；subject 与
每个 anchor 独立接地，关系测量由 L1-GROUND 的确定性验证完成。

### 4.4 L1GroundingRequest

每个通过空间工作项准入的 mention 形成 typed request：

~~~text
grounding_request_ref
mention_ref
relation_mention_refs
allowed_binding_kinds
required_identity_authority
scope_constraints
source/evidence refs
observation_snapshot_ref/digest
world_model_snapshot_ref/digest
~~~

request 只要求认知 identity/scope binding，不声明规划用途的 geometry/capability 需求；后者只
属于 Planning Ground。

### 4.5 L1Gap

每个 gap 必须包含：

~~~text
gap_ref
producer_stage=l1
subject_refs
missing_fields
requirement_ref
earliest_resolution_stage
retrieval_capability
allowed_source_families
status
failure_reason
recovery_pointer
input_digest
~~~

一个 gap 不得同时表示“没有查到”“provider 失败”“存在冲突”和“需要人确认”。Evidence
完整定义见 <code>04_EVIDENCE.md</code>。

## 5. 事实接纳算法

每个候选事实按固定顺序处理：

1. 来源准入：来源必须属于当前 session，且为 <code>current_evidence + admitted</code>。
2. 地址验证：source ref、segment/span 必须存在，引用文本必须能在规范化后回指原文。
3. 类型验证：predicate、value kind、unit 和 dimension contract 一致。
4. 时间验证：现状、历史、预测和规划文本不得混入同一 valid-time 语义。
5. 推理验证：derived 必须有确定性 derivation；inferred 必须列出前提事实。
6. 冲突归组：相同 subject/predicate/valid-time 的不兼容值进入同一 conflict group。
7. 接纳决策：按 authority、时效、独立来源和冲突策略得到 accepted/pending/rejected。

数值事实不得只靠“文本包含类似数字”接纳。至少校验数值、单位、计量对象、统计时间和
计数口径；缺一项时保留为 pending 或 qualitative observation。

## 6. 来源片段验证

source-span validator 是确定性组件，输出：

~~~text
valid
source_missing
segment_missing
literal_mismatch
offset_mismatch
cross_source_reference
role_not_admitted
~~~

展示性规范化只允许统一空白、全半角和明确登记的 Unicode 等价形式；不得做会改变语义的
模糊改写。无法逐字回指不代表结论一定错误，但它不能成为 <code>observed</code> 事实。

## 7. 冲突与合并

冲突聚合键为：

~~~text
subject_key + predicate + valid_time_bucket + measurement_basis
~~~

处理规则：

- 完全相同的独立观察去重并合并 source refs；
- 单位可确定换算时保留原值并生成 derived canonical value；
- authority 不同但值冲突时不得简单平均；
- 法定/权威结论使用 requirement 声明的 authority policy；
- 不能自动解决的冲突形成 <code>ConflictGroup</code> 和 <code>L1Gap</code>；
- 新证据推翻旧事实时新增 superseding fact，不覆盖旧 artifact。

## 8. L1 子状态机

每个维度独立运行：

~~~text
NEW
  → INPUT_FROZEN
  → OBSERVING
  → ROWS_PARSED
  → SOURCE_VALIDATED
  → FACTS_CLASSIFIED
  ├─ EVIDENCE_REQUIRED → EVIDENCE_PENDING → FACTS_CLASSIFIED
  ├─ HUMAN_REQUIRED
  └─ OBSERVATION_COMPLETE
~~~

维度终态：

- <code>complete</code>：所有 required facts 已 accepted 或被显式证明 not_available；
- <code>partial</code>：可发布部分事实，但有不破坏当前不变量的开放 gap；
- <code>human_required</code>：冲突或授权决策必须由人处理；
- <code>blocked</code>：当前输入 artifact、provider 或 contract 无法使用。

<code>partial</code> 不能被上层解释成 PASS。L1 Gate 根据消费者所需 requirement 决定能否发布
特定 projection；不能因为已有若干事实就宣称整个 L1 完整。

## 9. Evidence 与 L1-GROUND 调用时机

L1 只在以下条件调用 Evidence：

- required fact 缺来源；
- 多来源冲突需要 authority/时效判断；
- <code>L1LocationMention</code> 缺少候选召回所需的名称、scope 或关系证据；
- 下游明确声明的 L1 requirement 尚未覆盖。

L1 只在 <code>L1LocationMention</code> 已通过空间工作项准入并形成
<code>L1GroundingRequest</code> 后调用 L1-GROUND。抽象主题、
产业名称、政策动作和纯统计项应终止为 <code>not_spatial_work_item</code>。

## 10. 增量重算

L1 每个事务记录：

~~~text
input_artifact_refs
input_digest
source_page_digest
requirement_set_fingerprint
model/provider/version
row_digest
dependency_refs
output_digest
~~~

新 Evidence 到达时只定位依赖该 gap 的事实或地点工作项。若 source/requirement/candidate
fingerprint 未变化，则复用旧结果。World Model 更新后，仅重新验证依赖已变更
entity/representation/assertion 的 binding；全局 digest 改变但 dependency digest 未变时，
不重跑无关事实。

## 11. LLM 边界

允许 LLM：

- 从有界 source page 提议 observation row；
- 对已给定的 fact type 做闭集分类；
- 对冲突原因、gap 类型做闭集提议；
- 提取来源明确的地点名称、角色、scope 和关系。

禁止 LLM：

- 生成 source ref、entity ref、geometry、坐标或 BSM；
- 自行声明 authority 或 accepted；
- 输出完整可变 <code>L1ObservationSnapshot</code>；
- 访问整份 KG、整个 session state 或未分页原文；
- 把规划成果文本重新解释为当前事实。

所有 LLM 输出经 Structured Runtime 的行数、列数、枚举、主键和引用闭包校验。

## 12. 持久化、恢复与可观测性

每个产品写入 CAS 后再发布 named ref。恢复时必须校验：

- run/branch/session 一致；
- context/version/fingerprint 一致；
- source snapshot 和 World Model parent 一致；
- artifact semantic digest 可重算；
- 观察、binding、commit receipt 的父子引用闭合。

至少记录：

~~~text
facts_by_status
facts_by_inference_level
source_span_validation_failures
conflict_group_count
location_work_items_by_status
evidence_gap_age
dimension_retry_count
reused_row_count / recomputed_row_count
~~~

## 13. 文件责任

当前实现入口：

~~~text
contracts/l1/l1_contracts.py
modules/l1/observation_draft.py
modules/l1/context.py
modules/l1/aggregation.py
modules/l1/gate.py
modules/l1/spatial_admission.py
modules/ground/application.py
contracts/evidence/identity_contracts.py
contracts/cognition/stage_contracts.py
~~~

目标新增或收敛点：

~~~text
modules/l1/source_span_validation.py
modules/l1/fact_acceptance.py
modules/l1/conflict_resolution.py
contracts/l1/product_manifest.py
modules/l1/final_projection.py
~~~

文件名是实施落点，不表示上述目标能力已经存在。

## 14. 验收

L1 完成至少需要：

1. 真实 current-evidence 输入生成可重载 L1 observation product；
2. 每个 accepted fact 可回指 source span，derived/inferred 可回指前提；
3. 规划成果、未知角色来源和历史会话内容无法进入 current fact；
4. 非空间项不会进入 GROUND；
5. 地点项均产生 binding 或明确终态；
6. Cognition commit 后生成新 WM snapshot，原 L1 artifact 不被修改；
7. L2/L3 只消费版本一致的最终 projection；
8. 新证据只重算受影响行；
9. 冲突、provider failure、资料缺失和 HUMAN 能被区分；
10. 空结果、部分维度或 mock artifact 不得冒充完整 L1。
