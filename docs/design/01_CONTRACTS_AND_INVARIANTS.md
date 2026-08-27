# Contracts and Invariants

> Status: TARGET
> Authority: Normative ownership, projection and cross-stage invariants. Pydantic models and generated OpenAPI are field-level authority; implementation status belongs in `../architecture/CURRENT_RUNTIME.md` and `05_MIGRATION.md`.

## 1. Contract authority

设计文档只定义语义所有权、生命周期、允许的投影和不变量，不复制 Pydantic 字段表。字段名、类型、默认值、validator 和 wire schema 发生冲突时，以 `backend/app/contracts/`、实际 provider response model、生成 OpenAPI 和可重复测试为准；随后修正文档，不在 Markdown 中建立平行 schema。

代码中的 contract registry role（`llm_output`、`domain`、`artifact`、`api`、`event`、`render`）描述跨模块注册用途；本文件的 canonical/derived/transport/display/control/audit 描述语义生命周期。两组分类互补，不能互相替代。

## 2. Canonical ownership chain

唯一语义权威链是：

```text
L1SemanticSnapshot
  → L2DecisionSet
  → PlanningClaimSet
  → AdmittedTargetSet
  → GroundedPlanningProblem
  → ScenarioSet
  → ApprovedExecutionInput
  → PlannedState
  → ValidationCertificate
  → DeliveryManifest
```

| Canonical artifact | Sole semantic owner | Boundary rule |
|---|---|---|
| `L1SemanticSnapshot` | L1 assessment | 只持有已验证、可定位的当前事实；现有 `L1Snapshot.fact_records` 是主要实现锚点，display/control 混载的收敛状态见 migration ledger。 |
| `L2DecisionSet` | L2 objectives | 只在 L1 fact refs 上表达目标、策略、优先级和 target decisions；目标值不是已测量事实。 |
| `PlanningClaimSet` | L3 program | 非可执行、带证据的规划主张集合；不得携带候选成员或最终几何。 |
| `AdmittedTargetSet` | deterministic target admission | 只接纳满足 planning role、project package、typed parameters、位置需要和 lineage 的空间干预。当前实现名称不等同于本目标名称。 |
| `GroundedPlanningProblem` | GROUND | 绑定闭集身份、snapshot、候选、几何、关系与约束输入；不记录最终 winner。 |
| `ScenarioSet` | SELECT | 唯一正式方案决策 artifact；成员、指标、可行性、Pareto/recommendation 与 solver proof 必须一致。 |
| `ApprovedExecutionInput` | approval boundary | 冻结获批 scenario/problem/baseline/outcome refs 与 digests；变更即失效。 |
| `PlannedState` | atomic EXECUTE | 只表示已完整提交的物化状态；staged、partial、diagnostic 不得冒充。 |
| `ValidationCertificate` | VALIDATE | 独立绑定 approved input、scenario、baseline、snapshot 与 planned-state digests。 |
| `DeliveryManifest` | DELIVER | 只组织同一 run-root/snapshot lineage 且已验证的地图、报告和导出 refs。 |

链中未与当前类名一一对应的名称是目标语义，不表示代码已完成重命名或拆分。当前事实以 [CURRENT_RUNTIME.md](../architecture/CURRENT_RUNTIME.md) 为准，差距只在 [05_MIGRATION.md](05_MIGRATION.md) 记账。

## 3. Object classification

| Object | Class | Normative meaning |
|---|---|---|
| `L1Observation` family (`L1ObservationProviderOutput` / `L1ObservationPassOutput`) | transport | LLM observation draft 和本地校验 envelope；未确认 observation 不进入 canonical facts。 |
| `L1Fact` | canonical | L1 唯一 provenance-rich semantic evidence；human-readable `facts` 只是 deterministic display projection。 |
| `L1LocationFact` | derived | 当前 `LocationMention` 设计角色的主要承载体：从已验证 observation 编译出的 spatial resolution work item；不是 resolved identity、coordinate 或 geometry。 |
| `L2DecisionSet` | canonical | L2 的 typed semantic decision；其中 proposal/target metric 表达意图，不证明实测值。 |
| `EvidenceGap` | control | stage-neutral 的缺失支持 record；只描述缺什么、阻断什么或需要什么补证，不执行检索，也不成为事实。当前 L2/grounding 仍有 shape 差异，收敛状态只在 migration ledger 记账。 |
| `EvidenceRequirement` | control | 从 gap 或 typed artifact 确定性编译的可执行、可审计问题，驱动 retrieval、coverage 和 stop decision。 |
| `EvidenceBundle` | transport | 一般 facts/sources/conflicts/unresolved 的检索载体；它是 general fact view，不是第二个 fact registry，不能整包进入 prompt。 |
| `EvidencePacket` | transport | 空间 candidate/relation/pagination/query-audit 的 detail view；不是 resolved geometry authority，也不是第二个事实面。 |
| `PlanningClaimSet` | canonical | L3 唯一非可执行 semantic claim artifact；admission 后以 refs 连接目标，不复制整套 claims。 |
| `ScenarioSet` | canonical | solver-backed SELECT 决策 artifact；LLM prototype/recommendation 只有经确定性闭集校验、指标与证书绑定后才能成为其成员或说明。 |
| L3 intent summary | display | 可选的主张、依据、不确定性和缺口摘要；只能引用 `PlanningClaimSet`，不得冒充详细规划结果。 |
| detailed planning / delivery reports | display | `ScenarioSet` 后或验证交付后的空间规划解释；必须绑定所属 canonical refs/digests，不得由 L3 claims 直接生成。 |
| other reports / report bodies / summaries | display | 人类可读解释；不得创建事实、目标、位置、几何、关系、状态或证书，也不得默认回流到 L1/L2/L3 semantic prompt。 |
| provenance / compiler / query / solver / LLM call traces | audit | 重放与诊断证据；默认不进入 semantic prompt，且不能作为 gate truth 的替代。 |
| pass / retry / checkpoint / pagination cursors | control | 恢复和预算位置；不能证明语义完成、证据充分或执行成功。 |

`EvidenceCoverage`、gate decision 和 lifecycle status 属于 control；normalized `EvidenceResult` 当前主要由 `ExplorationResult` 承载。`EvidenceClaim`/投影后的 evidence fact 只有在 canonical owner 接纳并保留 source refs 后，才能成为该 owner 的 semantic input。API/event/render 对象是 transport/display projection，不拥有上游语义。

## 4. Efficiency invariants

以下八条同时约束设计、代码、prompt、artifact 和验收：

**EFF-01 Every semantic meaning has one canonical owner.**

同一事实、目标、候选、方案、批准、执行状态或证书不得存在两个可互相覆盖的权威副本。

**EFF-02 LLMs produce drafts, observations, decisions, proposals, or summaries only.**

其中 observation 必须解释为 observation draft；操作上允许的四类输出仍是 draft、decision、proposal、summary。任何 provider output 都先是待验证输入，不因 schema 合法而自动取得 authority。

**EFF-03 IDs, snapshots, scope, lineage, geometry, metrics, certificates, and status are deterministic outputs.**

模型可以引用闭集 ID 或提出目标值，但最终 identity、snapshot/scope、geometry/candidate membership、实测 metric、hard status 和 certificate 必须由确定性 producer 建立。

**EFF-04 Downstream stages receive named minimal projections, never complete upstream dumps.**

没有 projection name、producer/consumer、allowlist、budget 和 digest 的跨阶段输入必须拒绝。

**EFF-05 Display, semantic, control, and audit data cannot substitute for one another.**

report、summary、event status、cursor、trace 或 diagnostic 都不能被重新解析为 semantic truth。

**EFF-06 Equivalent facts are referenced once and expanded only at a consumer boundary.**

同一 prompt 或 artifact 不同时复制 statement、完整 source row、report paragraph 和 trace；保留一次 canonical ref，并按消费者需要展开。

**EFF-07 Every output field must have a producer, consumer, and lifecycle owner.**

没有消费方、生命周期或删除/失效规则的字段不得进入正式 contract。

**EFF-08 Contract size, prompt size, duplication, and unused fields are acceptance concerns.**

大小预算、重复率和未消费字段必须像正确性一样进入测试和发布 gate，不能只作为后续优化事项。

## 5. Deterministic derivation rules

1. LLM 返回的 ID 是 candidate label；应用必须按 namespace、source identity、content digest 和 membership 重新建立或验证正式 ID。
2. snapshot、scope、revision、fingerprint 和 lineage 必须从持久化 artifact 与 canonical serialization 派生；`latest`、文件名或文本相等不能证明身份相同。
3. coordinates、CRS、geometry、spatial relation 和 candidate membership 只能来自允许的数据资产、query compiler、GIS/KG adapter 和 deterministic evaluator。
4. L2 的 `TargetMetric` 可表达 proposed/required 目标；baseline、scenario objective value、coverage、面积、距离和 hard-constraint result 必须由确定性 evaluator 计算。
5. `SolverCertificate`、`ValidationCertificate`、reconciliation outcome、commit/delivery status 只能由所属 gate 根据 refs/digests 和测量结果生成。
6. 任何输入变化导致相关 digest/fingerprint 变化时，下游 cache、approval、certificate 和 delivery projection 必须失效或重新建立。

## 6. Named minimal projection contract

每个 projection 至少声明：稳定名称与版本、producer、唯一 consumer 或 consumer class、canonical source refs、字段 allowlist、排序/去重规则、char/item budget、projection digest、明确排除的数据类，以及失效条件。

最小边界规则如下：

- L1 → L2：只给已验证 `L1Fact` 的必要值与 refs；不传 raw source、完整 report、trace 或 cursor。
- L2 → L3：只给跨依赖归并去重后的相关 decisions/objectives/strategies/target metrics 与 L1 refs；不传 summary、report body、原始 prompt、历史 message 或上游 RAG context，也不让 L3 重解析 L1/L2 display projection。
- Evidence → analysis prompt：只给 consumer 所需 fact projection、coverage 与 gaps；不传 raw retrieval、完整 source table、geometry body 或 query trace。
- Claims → admission：只给 claim refs、粗粒度 claim family、planning role、fact/evidence refs、location hints、grounding/evidence requirements 与 claim-set digest。应用建立正式 identity、package/grouping 和 target family；不能从 prose 补猜的执行关键参数使 claim 保持 pending/deferred，而不是扩张 L3 provider schema。
- Admission → GROUND：只给 admitted target refs、typed requirement slots、已有的 source-backed parameter values、grounding requirements 与 parent digest；GROUND 不接收 L1/L2/L3 report body。
- GROUND → SELECT：只给闭集 `GroundedPlanningProblem` projection；SELECT 不接收可越权扩展候选域的原始 dump。
- Scenario → approval → EXECUTE：approval 引用 `ScenarioSet` 成员并冻结 `ApprovedExecutionInput`；EXECUTE 不接收可覆盖获批结果的第二份方案。
- VALIDATE → DELIVER：只传 certificate、reconciliation 与 artifact refs；DELIVER 不重跑检索、规划或验证。

现有 `DependencyContext.render_for_prompt()`、`render_analysis_evidence_for_prompt()` 和 `LLMCallSpec.messages` 是可复用的实现锚点：前两者分别过滤 raw/audit dependency keys、缩减 evidence 并排除 raw retrieval/geometry；LLM manager 对输入大小和 safe audit metadata 设边界。`ProjectCognitionSnapshot` / `cognition_digest` 当前是 retrieval preflight 锚点，不是已经完成的跨阶段 gate。这些局部机制不证明所有生产调用已使用 named minimal projection，也不证明不存在 manager bypass。

### 6.1 Provider wire contract 不复制内部 domain contract

provider-facing response model 只描述当前模型事务必须产生的最小语义草稿。内部 domain model 为编译、准入、grounding、solver 和执行保留的字段，不得因为“后续可能需要”而前置到 provider schema。

| Transaction | Provider may emit | Provider must not emit |
|---|---|---|
| L1 observation | source-backed statement、fact family hint、source segment/quote、uncertainty | canonical fact ID、resolved identity、geometry、报告正文 |
| L2 abstract decision | objective/constraint/strategy/priority proposal、proposed metric、closed L1 refs、evidence gap | 项目组件、candidate/geometry、执行参数、完整详细规划 |
| L3 rough claim | statement、coarse claim family、planning role、closed objective/fact/evidence refs、textual location hint、grounding/evidence requirement、uncertainty | provider-chosen formal ID/package ID、facility/road/axis/polygon/site parameters、parcel/network refs、relation template/object ref/geometry scope、candidate membership、geometry、capacity/footprint truth |

L2 或 L3 需要多个异质集合时，目标实现必须先产最小 seed/claim items，再由确定性代码归并、建立 ID 和交叉引用；只有确有必要的未闭合字段才进入引用既有 closed IDs 的窄 follow-up transaction。禁止用一个宽 envelope 同时承担语义生成、内部对象预编译和 GROUND 输入准备。

### 6.2 Item-level failure atomicity

集合输出必须以单项为校验与修复原子。provider envelope 可以完成传输解析，但应用必须逐项执行 schema、closed-set ref、source lineage 和 domain normalization，并产出 `accepted_items`、typed `rejected_items` 与 diagnostics。一个无效 item 不得使已验证 items 失效；repair 只能携带失败 item 的稳定 index/digest、typed error paths 和原 projection ref/digest，不得重发或重写整个维度。

transport/schema retry、item semantic repair、dimension/workflow retry 必须分别声明预算并记录实际次数。统一 manager 不得静默把调用者声明的零 schema retry 提升为非零，也不得把一次完整 batch reask 隐藏在“结构化输出重试”中。

## 7. Cross-stage invariants

- 原始 `village_data` 与显式上传只由 L1 建 source index；下游只消费 typed facts/refs，不重解析原文或 report body。
- 任何 planning claim 都必须保留 supporting fact/evidence refs；任何 executable target 都必须有 deterministic admission lineage。
- `L1LocationFact`、place mention、retrieval candidate 和 candidate score 都不是 resolved geometry 或最终方案。
- GROUND 只召回、绑定和测量候选；SELECT 只在闭集 ID 上决策；LLM 不得创造坐标、几何或候选成员。
- `ScenarioSet.problem_fingerprint` 必须绑定输入问题；feasible/Pareto/recommended membership 和 solver certificate 必须一致。
- `ApprovedExecutionInput` 冻结 scenario/problem/baseline/snapshot refs 与 digests；任何漂移都使 approval 失效。
- EXECUTE 只物化获批 candidate/route/layout，且只能完整 atomic commit；partial 只允许 diagnostic/staging。
- VALIDATE 独立测量，不修改方案；RECONCILE 定位跨阶段遗漏；DELIVER 只组织同 lineage 的已验证 refs。
- embedding、provider、retriever 或工具降级必须显式进入 control/audit，不得静默改变 semantic truth。
- infeasible、insufficient、deferred 和 human-required 都是合法 typed 结果；不得伪装为 complete/success。
- L3 阶段不得生成详细规划报告。可选 intent summary 只解释 claims；空间规划报告在 `ScenarioSet` 后生成，正式交付报告在 validation/reconciliation 后生成。

## 8. Current implementation alignment

当前代码已提供若干对齐锚点，但不得据此宣称目标完成：

- `backend/app/contracts/registry.py` 为主要 LLM/domain/artifact/API/event/render 边界提供稳定 key、owner、version 和 model path；
- L1 当前有 provider observation envelope、deterministic validation/repair、`L1Fact`、`L1LocationFact` 和 `L1Snapshot`；L2 有 strict `L2DecisionSet`；L3 有非可执行 `PlanningClaimSet` 与 deterministic admission 路径；
- `backend/app/infrastructure/llm/manager.py` 集中 typed/tool call 的预算、并发、retry 和 safe call audit，且不持久化 prompt/response text；
- `dependency_context.py` 只装载直接依赖并从 semantic instruction 中排除 raw/report/audit keys；
- `project_cognition.py` 确定性构建 cognition digest，合并等价 facts，并为 prompt 提供 bounded projection，显式排除 raw retrieval 与 geometry payload；它是 evidence preflight/projection 锚点，不代表全局 cognition gate 已完成。

以上是代码事实的局部摘要，不是 completion claim。完整当前行为、live 证据和 `PARTIAL/GAP` 边界见 [CURRENT_RUNTIME.md](../architecture/CURRENT_RUNTIME.md)；所有目标到当前的差距和下一步只见 [05_MIGRATION.md](05_MIGRATION.md)。
