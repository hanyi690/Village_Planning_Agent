# Contracts and Invariants

> Status: TARGET
> Authority: Normative ownership, identity, lineage and cross-stage invariants. Pydantic models remain the executable schema source.

本文定义契约的语义所有权，不复制字段清单。实现时以 `backend/app/contracts/` 中的 Pydantic 模型、生成的 OpenAPI 和测试为字段级事实。

## 1. Authority chain

```text
PlanningProblemSpec / PlanningProgram {claims, objectives, project packages}
→ EvidenceRequirement + EvidenceCoverage
→ admitted executable target specs
→ GroundedPlanningProblem
→ PlanningDeliberationGraph { prototypes, tool observations, critic rounds }
→ ScenarioSet { PlanningScenario[], SolverCertificate[], deliberation audit }
→ ApprovedExecutionInput { ApprovedOutcomeEnvelope }
→ ConstrainedMaterializationGraph { recipes, observations, equivalence checks }
→ PlannedState / ChangeSet
→ ValidationCertificate
→ ReconciliationReport
→ DeliveryManifest
```

同一阶段可以生成诊断报告和只读定位视图，但生产链不再维护旧合并兼容对象；每个决策只能有一个权威产物。旧 planning payload 不再有官方迁移入口，也不能反向覆盖权威产物。

## 2. Contract ownership

| Contract | Owner | Producer → Consumer | Stable identity and version | Failure state | Forbidden behavior |
|---|---|---|---|---|---|
| `PlanningProblemSpec` | L3 planning domain | L3 → TARGET_PROJECTION/Evidence | problem ID、revision、intent fingerprint、source fact refs | ambiguous/incomplete/human-required | 写入候选 ID、坐标或最终选择 |
| `EvidenceRequirement` | Evidence plane | L1/L2/L3/TARGET_PROJECTION/GROUND → evidence controller | requirement ID、requesting artifact revision、scope | unsupported/ambiguous/unavailable | 退化成无来源的 raw query |
| `EvidenceClaim` | Evidence plane | retrievers/resolvers → consumers | claim ID、source locator、content/source digest | contradicted/low-authority/unlocatable | 丢失页码、span、feature ID 或 source ref |
| `EvidenceCoverage` | Evidence plane | evidence controller → gate/requester | requirement-set fingerprint、source/query scope、run ID | insufficient/source-exhausted/human-required/budget-exhausted | 声称开放世界绝对完整 |
| `ProjectPackage` / target admission | L3 planning domain | L3 → TARGET_PROJECTION | package/claim IDs、source refs、intervention type、admission reason/revision | non-spatial/not-admitted/incomplete/human-required | 把事实、指标、约束或任意非行动 claim 自动升级为可执行空间目标 |
| `SpatialQuery` | Spatial query domain | TARGET_PROJECTION/GROUND → spatial adapter | AST fingerprint、snapshot、CRS、query version | invalid/unresolved/unsupported | 用自由 SQL、自由文本或 LLM 坐标越过 AST |
| `GroundedPlanningProblem` | GROUND/SELECT scoped re-solve | GROUND → PlanningDeliberationGraph → approval | problem ID、fingerprint、scope policy、parent problem fingerprint、deferred target IDs、baseline/snapshot refs、source artifact refs | unresolved/deferred/not-candidate-complete | 记录最终 winner、让 SELECT 创造候选或无 lineage 地缩小问题范围 |
| `ConstraintSpec` | Planning domain | L3/TARGET_PROJECTION/GROUND → optimizer/validator | constraint ID、semantic revision、evidence refs、evaluator version | unmeasurable/conflicting/unresolved | 把 soft preference 当 hard constraint，或无依据修改阈值 |
| `ScenarioSet` | SELECT planning domain | PlanningDeliberationGraph → approval/RECONCILE | set ID、problem fingerprint、prototype/tool/critic digests、solver/model digests | infeasible/bounded/upstream-required/budget-exhausted | 只保留 winner、隐藏替代/critic/搜索边界，或把未验证 prototype 当方案 |
| `PlanningScenario` | SELECT planning domain | validated prototype + tool observations → ScenarioSet/approval | scenario ID、problem fingerprint、scenario fingerprint | infeasible/not-selected/superseded | 无确定性 observation 宣称可行，创造坐标或改变 candidate membership |
| `SolverCertificate` | SELECT tool domain | deterministic tools → ScenarioSet/RECONCILE | problem/scenario/tool/input digest、solver version、seed | infeasible/timeout/unknown-bound | 接受 LLM 自报计算，或宣称证明需求理解/开放世界完整性 |
| `ApprovedExecutionInput` | Approval boundary | policy/human gate → EXECUTE | approval ID、scenario/problem/baseline fingerprints、outcome-envelope/approval digest | expired/revoked/stale/mismatched | 批准后换方案/baseline，或允许 recipe/recovery 越过 outcome envelope |
| `MaterializationRecipePlan` | Execution domain | ConstrainedMaterializationGraph → materializer tools | plan ID、approved-input/envelope fingerprint、recipe/action digests | unmaterializable/worker-blocked/non-equivalent | 脱离 ApprovedExecutionInput 成为规划事实源、携带自由写操作或改变获批 outcome |
| `ExecutionStaging` | Execution domain | EXECUTE → VALIDATE/RECONCILE/diagnostic | staging ID、approved/plan refs、staged child refs、commit ID/status | staged/aborted/committed | 把 staged child 当作已提交 PlannedState，或失败后提升正式 refs |
| `PlannedState` | Execution domain | atomic EXECUTE → VALIDATE/RECONCILE | state/change-set fingerprint、baseline and run-root lineage | staged/aborted/partial-diagnostic | 部分正式提交或混合 snapshot |
| `ValidationCertificate` | Validation domain | VALIDATE → RECONCILE/DELIVER | certificate digest、approved input/scenario/planned-state digests | rejected/incomplete/stale | 自动改方案、掩盖 hard violation |
| `DeliveryManifest` | Delivery domain | DELIVER → API/UI/export | manifest ID、run-root、snapshot digests、artifact refs | diagnostic-only/incomplete | 从未验证或不同 run 的产物拼装正式交付 |

现有 `GroundingResult` 可以作为 GROUND 阶段包装器，但其 `.problem` 才是求解边界。现有 `PlanningScenario` 保留为 `ScenarioSet` 元素；`SiteSelectionDecision`、旧选择投影和合并 L1/L3 response model 不再暴露为生产 API/worker 输入。`ValidationReport` 保留详细 findings，`ValidationCertificate` 才是下游硬门控摘要。

## 3. Normative invariants

INV-01 No planning claim becomes complete without supporting evidence identifiers.

INV-02 No spatial target becomes executable without an authoritative or explicitly degraded geometry reference.

INV-03 GROUND recalls and binds candidates; it never selects the final scenario.

INV-04 SELECT LLM may frame, prototype, plan tools, critique and recommend only over closed IDs; deterministic tools alone establish geometry, metrics, hard-constraint and solver truth.

INV-05 EXECUTE may plan recipes and diagnose failures only inside an immutable ApprovedOutcomeEnvelope; every recovery is deterministically proven equivalent and never re-selects a location.

INV-06 VALIDATE measures the materialized result independently from generation.

INV-07 Open-world retrieval reports scope and unresolved gaps; it never claims absolute completeness.

INV-08 Embedding failure degrades dense recall only and never disables structured, lexical, graph, or spatial retrieval.

INV-09 A complete scenario has zero unresolved hard constraints.

INV-10 Delivery is complete only when the same run-root and snapshot lineage reaches map layers, reports, and exports.

INV-11 A planning claim, indicator, constraint, objective, or non-spatial action never becomes an executable spatial target merely because it is not labelled as narrative text.

INV-12 Any operation that compares alternatives, selects candidate membership, chooses a route, or changes the planning outcome executes before approval; EXECUTE cognition is limited to choosing and repairing the materialization method without changing the frozen outcome.

INV-13 Formal execution is all-or-nothing. `partial` is a diagnostic staging outcome, never a committed `PlannedState` or formally deliverable result.

INV-14 Raw planning documents are opaque outside L1. Only L1 may read or
structure session-owned `village_data` and explicit uploads; it must persist an
`L1SourceIndex` and typed observations with source segments and locators. Each
L1 dimension owns its semantic observations; the aggregate only unions and
validates those observations and may recover the L1-owned source-index
artifact. L1 observe/validate/report passes are bounded and resume-keyed by
`(session, dimension, input_digest, pass, attempt)`; completed passes are not
rerun. L2/L3/Project Bank/TARGET_PROJECTION/GROUND/EXECUTE and the frontend
must consume that artifact and must not reconstruct quantities, demand points,
locations, or geometry from raw input text.

INV-15 Structured-output shape is not semantic evidence. Every L1 observation
must be validated against the L1 source index for source segment, digest and
source span. Follow-up retrieval may provide contextual evidence through the
unified evidence router, but it cannot alter canonical source fields or create
a spatial identity. A bounded call budget exhausted by invalid or unresolved
observations produces diagnostics and a resumable cursor rather than fabricated
completeness.

## 3.1 L1/L3 双投影语义契约

`LLM loop` 是结构化输出的交付机制，不是规划目标。L1/L3 不再要求一次
LLM 调用同时生成正文和机器结构化结果；生产路径使用多个有界、可恢复的
投影调用，并在每个投影之间做确定性校验。验收只看下面的语义产物是否成立：

| 层 | 允许读取的输入 | 面向人的产物 | 面向后续规划的权威产物 | 明确不产出 |
|---|---|---|---|---|
| L1 OBSERVE | 当前 session 持久化输入、显式上传、已声明的 GIS/KG 证据引用和本维度检索结果；不得读取仓库参考文档 | `report_body`：完整现状分析、表格/段落和缺口说明 | `L1SourceIndex`、typed observations、`L1Fact`、`L1LocationFact`、source segment/span、约束/冲突/不确定性和 pass cursor | 规划目标、候选地块、坐标、未来方案；不能把人口总数自动变成 demand point |
| L3 PLAN | L1 typed facts/register、L2 策略和目标、任务约束、已定位证据及维度语义契约 | `report_body`：完整规划分析/项目包说明 | `PlanningClaimSet`、项目包、typed parameters、objective/constraint refs、semantic relation、`grounding_requirements` 和 source lineage | WKT/GeoJSON/BSM/候选成员/最终路线或最终选址；不能把每条事实/指标机械升级为空间干预 |

表中的“面向人的产物”指该层最终持久化的维度产物，不表示 OBSERVE/claims
那一次 provider 响应中包含 `report_body`；正文只在后续独立 report-synthesis
pass 生成。

L1 的 `report_body` 与结构化 observation/fact 是双投影：结构化通道缺失或不完整
时，正文仍必须保存，但下游只消费已通过 source identity、状态和字段校验的
typed facts。L3 同样必须保存正文；只有声明 `planning_role=spatial_intervention`、
项目包、typed 参数、定位要求和证据 lineage 的 claim 才能通过 admission，其他
claim 留在 `PlanningProgram` 中作为 evidence/metric/constraint/objective/非空间
行动。

生产调用顺序固定如下；每一步都有独立响应模型、checkpoint 和缓存键，恢复时
只重做缺失的投影，不重放已经完成的 provider 调用：

```text
L1: source index/retrieval
    → observe (L1ObservationPassOutput)
    → register/repair (L1RegisterPassOutput, 按需)
    → source/materialization validation
    → report synthesis (L1ReportOutput, 只读已验证材料)

L3: typed L1/L2 context + retrieval
    → claims (L3ClaimOutput)
    → structural/semantic repair (claims only, 按需)
    → deterministic admission/normalization
    → report synthesis (L3ReportOutput, 只读已验证 claims)
```

报告投影不得创建新的事实、目标、位置、几何或关系；结构化投影也不得把
`report_body` 当作第二事实源。原始输入只在 L1 建立 source index 并由 L1
observation/register pass 读取，L3/Project Bank/GROUND 不重新解析原始文档。

L1/L3 的维度契约分别限制 observation kind、claim family 和 GROUND 所需输入。
例如 traffic 需要 network/endpoint 语义，public service 需要 facility/service 或
demand 语义，ecology 需要 protection/restoration/overlay 语义；没有相应事实或
关系时必须返回 diagnostic/deferred，不能由 loop、RAG 或模型自行补齐。后续权威
路径固定为：

```text
L1 observe/register/repair → validated typed facts/register
  + L1 report synthesis → report_body
  → L2 strategy/objectives
  → L3 claims/repair → validated PlanningClaimSet
  → L3 report synthesis → report_body
  → deterministic claim admission/adapter
  → TARGET_PROJECTION → GROUND
```

源文档正文不在 L2/L3/Project Bank/GROUND 重新解析；Project Bank 只能投影 L1/L3
artifact，RAG/EXPLORE 只能补充带 locator 的证据，不能成为事实或几何的第二权威。

## 4. Additional invariants for the authoritative planning chain

- `ScenarioSet.problem_fingerprint` 必须等于其输入 `GroundedPlanningProblem.fingerprint`。
- 显式 deferred target 触发的 scoped `GroundedPlanningProblem` 必须保留 `parent_problem_fingerprint`、`deferred_target_ids`、`scope_reason` 和 source refs；其 `ScenarioSet.problem_fingerprint` 必须等于 scoped problem fingerprint。
- `ApprovedExecutionInput` 必须引用 `ScenarioSet` 中存在的一个 `PlanningScenario`，冻结两者 fingerprint，并携带 `ApprovedOutcomeEnvelope`、允许 recipe/repair classes 与 tolerance policy。
- 任何获批后发生的问题、候选、约束、baseline 或 scenario 变更都会使批准失效。
- EXECUTE 的所有 recipe/tool action 只能读取同一 `ApprovedExecutionInput` 派生、通过验证的 `MaterializationRecipePlan`；恢复动作还必须通过 equivalence checker。
- 每个进入 TARGET_PROJECTION 的空间目标必须携带 target-admission lineage，指回项目包、原始 claim/source refs、空间干预类型和准入理由；未准入内容保留在 PlanningProgram，但不能进入 GROUND/EXECUTE。
- facility-location、CP-SAT/MILP、图搜索、走廊算法、邻接/拓扑求解和 Pareto 比较是 SELECT deliberation graph 的确定性工具。LLM 规划调用和解释 observation，但不得伪造结果；EXECUTE 只能物化获批 candidate/route/layout。
- 原子执行要么提交批准输入允许的完整 ChangeSet（显式 deferred 目标已从执行计划排除），要么不改变正式状态；worker/L4 失败产物只能进入诊断区。
- `ValidationCertificate` 必须独立关联 approved input、selected scenario、baseline 和 PlannedState digests。
- 每个可执行 `ScenarioFeature` 必须显式携带至少一个 `relation_ids` lineage；核心权威模型不得隐式生成关系 ID。没有关系因子的 reference adapter 也必须在自己的边界写入可审计的 reference scope ID。
- SolverCertificate 证明形式化求解；ValidationCertificate 证明物化一致性；ReconciliationReport 证明跨阶段覆盖。三者不得互相替代。
- infeasible 是合法求解结果，但必须带约束冲突解释，且不能进入 EXECUTE。

## 5. Snapshot and provenance rules

所有可执行空间身份必须至少能追溯到：数据资产、snapshot、feature ID、geometry digest、CRS 和查询/绑定过程。文本证据必须至少能追溯到：source ID、版本或 digest，以及页码、段落、字符 span、表格单元格或等价 locator。

Fingerprint 用于判断内容身份，revision 用于表达演进顺序，artifact ref 用于定位持久化对象，run-root 用于约束同一次运行 lineage；这些概念不能互换。`latest`、静态文件名、文本相等或数量相等均不能证明同一身份。

## 6. Gate semantics

| Gate | Pass condition | Failure route |
|---|---|---|
| Evidence gate | 必需要求被支持或获得明确降级批准 | EXPLORE / requester / HUMAN |
| Grounding gate | 候选、身份、几何和硬约束测量均达到 candidate completeness | GROUND / L3 / HUMAN |
| Deliberation gate | 有经工具 observation 验证的可行替代/推荐，或有可证明的 infeasible/typed upstream request | SELECT / GROUND / L3 / HUMAN |
| Approval gate | 选定方案及全部 fingerprints 被明确批准 | HUMAN / policy owner |
| Execution gate | 完整 ChangeSet 在 staging 中成功生成，所有 recovery 通过 equivalence，coverage=100% 且无意外输出 | EXECUTE / GROUND / SELECT / HUMAN |
| Validation gate | hard violations 为零，覆盖和 lineage 达标 | 责任阶段 / HUMAN |
| Delivery gate | ValidationCertificate 与 ReconciliationReport 均接受 | VALIDATE / responsible stage |

人工批准可以改变政策决定，不能篡改已经测量出的事实状态。所有降级都必须成为可查询、可展示、可重放的类型化决定。
