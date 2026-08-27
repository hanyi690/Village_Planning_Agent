# Village Planning Agent System Design

> Status: TARGET
> Authority: Normative global architecture and efficiency principles. Observed implementation belongs in `../architecture/CURRENT_RUNTIME.md`; target-to-current status belongs only in `05_MIGRATION.md`.

## 1. Outcome and boundary

系统交付的不是一段看似合理的规划文字，而是一组可从事实、决策、目标、空间问题、方案、审批、执行状态、验证证书追溯到交付物的成果。每个正式结果必须有唯一语义所有者、稳定引用、确定性 lineage 和明确失败状态。

本设计不承诺开放世界的绝对完整，不允许模型以叙述替代身份、几何、指标、状态或证书，也不把局部测试、报告生成成功或历史 live run 当作当前能力已完成的证明。

## 2. Single canonical semantic chain

全局只有一条语义权威链：

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

每个箭头表示一次有名字、有生产者和消费者的最小投影，不表示把完整上游对象复制到下游。下游保存稳定 ref/digest；需要展开时，只在消费者边界按允许字段展开。报告、事件、trace、cursor 和 API view 是该链的投影或控制面，不是第二条事实链。

链中名称是目标语义名称。当前代码仍有命名或承载差异，例如 `L1Snapshot` 同时带 `fact_records` 和 display projection，TARGET_PROJECTION 当前产出 `IntentCompilationResult` 等 artifact。它们是否已收敛到目标名称和边界，只由 [CURRENT_RUNTIME](../architecture/CURRENT_RUNTIME.md) 与 [05_MIGRATION](05_MIGRATION.md) 判定。

## 3. Generation and deterministic derivation

LLM 只允许产生四类临时或语义输出：draft、decision、proposal、summary。现有 `L1Observation` 属于 observation draft，不是已确认事实。模型可以解释、提出和排序闭集引用，但不能建立最终身份或证明计算结果。

以下内容必须由应用、契约校验器、检索器、GIS/solver、artifact store 或 gate 确定性产生或确认：

- identity、ID、artifact ref、digest、fingerprint；
- snapshot、scope、revision、lineage、candidate membership；
- coordinates、CRS、geometry、topology、network relation；
- measured metrics、hard-constraint result、lifecycle status；
- solver、validation、reconciliation 和 delivery certificates/manifests。

模型返回的同名字段最多是待验证主张。未通过确定性编译、闭集成员校验和来源校验前，不得进入权威链。

### 3.1 L1/L2/L3 的模型事务边界

结构化输出只约束一次 provider 事务的 wire shape，不代表应把一个阶段的完整内部对象交给模型一次生成。模型事务必须按单一认知目的拆分，且失败原子不能大于可独立验证和重试的最小语义单元。

- L1 observation transaction：从一个 bounded source page 提取 observation drafts；每条 draft 独立校验、独立隔离，应用再确定性编译 `L1Fact`、`LocationMention` 与 `EvidenceGap`。
- L2 decision transaction：从 named L1 projection 形成一组高度抽象、可闭集引用的 decision proposals；目标、指标、策略、优先级、冲突和空间结构意图不得因为内部 `L2DecisionSet` 可承载而被强制一次全部生成。
- L3 claim transaction：只形成粗粒度、非可执行 planning claim drafts；不生成项目组件拆分、target identity、package identity、空间关系、候选成员、几何参数或执行参数。
- display transaction：不得与 semantic transaction 混合。报告若需要模型润色，必须只消费已经验证的 semantic refs/projection，并且不能创建新的语义。

一个数组中的单项无效时，系统必须保留其余已验证项并返回 typed rejection；禁止因单项错误重试或丢弃整个维度。schema retry、semantic repair 和 workflow retry 是三个不同预算，不得隐式嵌套或互相覆盖。

## 4. Minimal projections and data classes

阶段边界默认拒绝 complete upstream dump。每个允许的 projection 必须记录名称、生产者、消费者、选择规则、大小预算、来源 refs/digest、生命周期 owner 和明确排除项。

数据必须按职责分离：

- **semantic**：链上的事实、决策、主张、目标、问题、方案和正式状态；
- **display**：report body、summary、map/API view，只解释或展示 semantic refs；
- **control**：gap、requirement、gate、cursor、retry、interrupt、pagination 和 routing status；
- **audit**：provenance、trace、call record、diagnostic、query/solver/reconciliation detail；
- **transport**：provider envelope、retrieval bundle/packet、event 和 consumer projection。

display、control、audit、transport 都不能替代 semantic authority。semantic artifact 也不得通过内嵌完整报告、raw retrieval、完整 trace 或控制状态来复制其他职责。

## 5. Evidence and bounded completeness

证据缺口统一表达为 `EvidenceGap`，可执行检索需要统一表达为 `EvidenceRequirement`；检索结果必须说明来源范围、覆盖、冲突、未解决项和停止原因。证据检索与 GROUND 的主规范在 [02_EVIDENCE_AND_GROUNDING.md](02_EVIDENCE_AND_GROUNDING.md)，本文件只规定其全局边界。

“完整”只表示在已声明的来源、查询计划、候选域、预算和停止原因内满足 gate。嵌入服务失效时，dense recall 可以降级，但结构化、词法、KG、bundle 和空间通道必须独立工作并暴露缺口；不得把 embedding 可用性变成事实或几何权威。

## 6. Stage responsibilities

- L1：从 session-owned 原始输入生成 observation drafts，再确定性编译可追溯事实、位置 work items 和证据缺口；原文与报告不下传。
- L2：在 named L1 fact projection 上形成高度抽象的目标、方向、约束、偏好、优先级和策略决策；不展开项目组件，不创造测量事实或几何。
- L3：把相关 L2 decisions、去重后的 canonical L1 facts 与定向 evidence 投影为粗粒度、非可执行 `PlanningClaimSet`；只有确定性 admission 可产生 `AdmittedTargetSet`。L3 不是详细空间规划生成器。
- TARGET_PROJECTION / GROUND：把 admitted targets 绑定到闭集身份、snapshot、候选、几何、关系和可测约束；GROUND 不选最终方案。
- SELECT：在闭集问题上提出或评议方案，由确定性工具建立可行性、指标和证书，最终只提交一个 `ScenarioSet`。
- Approval / EXECUTE：冻结 `ApprovedExecutionInput`；EXECUTE 只物化获批 outcome，不重新选址、寻路或改变 candidate membership。
- VALIDATE / RECONCILE / DELIVER：独立测量、跨阶段对账，并从同一 run-root 与 snapshot lineage 生成证书和交付清单。

为保持现有规划链的代码导航和 convergence 测试可追溯性，下面保留编排阶段关键词；它是语义链的执行映射，不是第二条语义权威链。正常主链是：

```text
L1 / L2 / L3
→ TARGET_PROJECTION
→ GROUND
→ GroundedPlanningProblem
→ PlanningDeliberationGraph
→ ScenarioSet
→ Approval Gate
→ ApprovedExecutionInput
→ ConstrainedMaterializationGraph
→ Atomic Commit
→ committed PlannedState
→ VALIDATE
→ ValidationCertificate
→ RECONCILE
→ DELIVER
```

`PlanningDeliberationGraph` 是 SELECT 的决策门面；`ConstrainedMaterializationGraph` 是 EXECUTE 的目标设计门面。二者在当前实现中的状态不得从本设计推断：`05_MIGRATION.md` 当前仍将相关能力区分为 `CURRENT`、`PARTIAL` 或 `GAP`。`GroundedPlanningProblem`、`ScenarioSet`、`ApprovedExecutionInput`、`PlannedState` 和 `ValidationCertificate` 是阶段间契约，不要求各自成为新的顶层图节点。

### 6.1 报告生成时点

`PlanningClaimSet` 只足以支撑可选的意图、依据、不确定性和证据缺口摘要；该摘要不得称为“详细规划报告”，也不得描述已选目标、地块、道路、空间关系、几何、容量、指标或实施结果。

详细规划报告必须等待空间链路至少完成 `TARGET_PROJECTION → GROUND → SELECT → ScenarioSet`，并只引用闭集 targets/candidates、problem fingerprint、formal scenario membership 与确定性测量结果。面向正式交付的最终报告还必须等待 approval、materialization、VALIDATE 与 RECONCILE，绑定 `ApprovedExecutionInput`、`PlannedState`、`ValidationCertificate` 和同一 run-root。报告是这些 artifact 的 display projection，不是 L3 的第二语义输出。

## 7. Gates and fail-closed behavior

任何边界缺少必需证据、身份、snapshot、scope、几何、闭集成员、硬约束输入、审批 digest 或 lineage 时，都必须产生 typed diagnostic、deferred/human-required 或失败结果；不得补猜并继续正式链。

阶段只能修改自己拥有的语义：证据缺口回 evidence requester，意图/准入缺口回 L3，候选或几何缺口回 GROUND，不可行或方案冲突回 SELECT/L3，物化偏差回 EXECUTE，验证失败回最早责任阶段。人工可以选择政策和降级路径，但不能改写已经测量出的事实。

正式执行是 all-or-nothing：staged、partial 或 diagnostic 不能提升为 committed `PlannedState`。`ValidationCertificate` 只证明获批输入与物化状态的一致性；`DeliveryManifest` 只引用通过验证且 lineage 一致的成果。

## 8. Efficiency completion rule

系统设计只有在 [01_CONTRACTS_AND_INVARIANTS.md](01_CONTRACTS_AND_INVARIANTS.md) 的 `EFF-01` 至 `EFF-08` 和 [04_EVALUATION_AND_ACCEPTANCE.md](04_EVALUATION_AND_ACCEPTANCE.md) 的量化 gate 均有可重复证据时，才能被称为收敛。至少必须证明：每阶段一个 canonical semantic output、每个消费者只收到 named minimal projection、无 report/audit/raw leakage、refs/digests 可稳定复用，并且 contract/prompt/duplicate/unused-field 预算受控。

目标能力、当前行为和迁移状态严格分开：本文件定义目标；[CURRENT_RUNTIME.md](../architecture/CURRENT_RUNTIME.md) 记录观察到的代码与 live 证据；[05_MIGRATION.md](05_MIGRATION.md) 是唯一 target-to-current ledger。
