# Planning and Execution Design

> Status: TARGET
> Authority: Normative ownership and boundaries from planning claims through approved materialization. Observed implementation belongs in `../architecture/CURRENT_RUNTIME.md`; target-to-current status belongs only in `05_MIGRATION.md`.
> Related invariants: `00_SYSTEM_DESIGN.md`, `01_CONTRACTS_AND_INVARIANTS.md`, `02_EVIDENCE_AND_GROUNDING.md`, `04_EVALUATION_AND_ACCEPTANCE.md`.

## 1. Canonical planning chain

规划和执行只使用一条主链：

```text
PlanningClaimSet
  → AdmittedTargetSet
  → GroundedPlanningProblem
  → ScenarioProposal (temporary LLM output)
  → ScenarioSet (canonical solver-backed artifact)
  → ApprovedExecutionInput
  → MaterializationRecipePlan
  → PlannedState
```

箭头表示 named minimal projection，不表示复制完整上游对象。正式 artifact 只保存自己的语义，并通过 artifact ref、content digest、fingerprint 和必要的 parent digest 连接上游。

`PlanningDeliberationGraph` 是 SELECT 的目标编排门面，`ConstrainedMaterializationGraph` 是 EXECUTE 的目标编排门面；它们不是新的语义 artifact，也不改变上面的唯一权威链。

## 2. Ownership and lifecycle

| Object | Lifecycle | Sole responsibility | Explicitly not responsible for |
|---|---|---|---|
| `PlanningClaimSet` | persisted canonical semantic artifact | 保存 L3 已验证、带 objective/fact/evidence refs、location hints 和 requirements 的粗粒度非可执行规划主张 | target/package identity、项目组件拆分、typed spatial parameters、candidate membership、geometry、solver truth、approval |
| `AdmittedTargetSet` | persisted canonical semantic artifact | 确定性建立 target identity、target family、grouping/package identity、claim lineage 和 typed requirement slots；只接纳语义与证据足以进入 grounding 的目标 | 从 prose 猜执行参数，或要求 L3 provider 预先生成内部 target/GROUND 对象 |
| `GroundedPlanningProblem` | persisted canonical semantic artifact | 冻结闭集 targets/candidates、geometry/relation/constraint inputs、snapshot refs 和 problem fingerprint | winner、recommendation、execution task |
| `ScenarioProposal` | temporary LLM proposal | 在闭集 IDs 上提出方案结构、需要的工具计算和理由 | 可行性、指标、geometry、certificate、正式成员资格 |
| `ScenarioSet` | persisted canonical semantic artifact | 保存 solver-backed alternatives、formal membership、objectives、recommendation 和 certificate | 接受未验证 proposal 或自然语言 winner |
| `ApprovedExecutionInput` | persisted approval authority | 冻结获批 ScenarioSet/member、problem、baseline、snapshot 和 materialization semantics 的 refs/digests | 重新选址、改 route/layout、放宽 hard constraint |
| `MaterializationRecipePlan` | persisted derived control artifact | 将获批 outcome 投影为 allowlisted recipes、依赖、tasks、预算和 plan digest，供 resume/replay 使用 | 成为第二份方案或复制完整 ScenarioSet/problem |
| `PlannedState` | persisted canonical semantic artifact | 表示全部获批任务通过 pre-commit 后的一次原子提交结果 | staged、partial、diagnostic 或 aborted 输出 |

`ScenarioProposal` 可以进入短期 checkpoint 或 audit record，但不能被下游当作 authority。`MaterializationRecipePlan` 可以持久化以支持幂等恢复，但它是 approval 的确定性派生物，不拥有规划选择语义。

## 3. Current-code naming boundary

目标名称与当前类名并非全部一一对应：

- 当前 `backend/app/contracts/program.py::PlanningClaimSet` 是单个 L3 维度的非权威 provider/compilation 输出；当前确定性 assembler 产出的 `PlanningProgram` 才是聚合 authority。目标仍要求最终收敛为一个明确的 canonical `PlanningClaimSet` owner。
- 当前没有独立 `AdmittedTargetSet` 类；admission 主要由 `PlanningProgram.interventions`、claim disposition 和 `IntentCompilationResult` 承载。
- 当前 `GroundedPlanningProblem`、`ScenarioSet`、`ApprovedExecutionInput` 和 `PlannedState` 已有同名 contracts。
- 当前没有专用 `ScenarioProposal`；SELECT 先运行确定性 optimizer/solver，再用 `CandidateSelectionProposal` 做可选 closed-set advisory reasoning。该 reasoning 不生成或修改 formal ScenarioSet。
- 当前 `ExecutionPlan`、`build_execution_plan_draft()` 和 `execution_plan_semantic_digest()` 是 `MaterializationRecipePlan` 的过渡实现。

这些映射只解释代码导航，不声明目标已经完成；状态只在 `05_MIGRATION.md` 记账。

## 4. LLM proposal versus deterministic truth

LLM 可以：

- 产生非可执行 planning claim draft；
- 在 `GroundedPlanningProblem` 的闭集 target/candidate IDs 上产生 `ScenarioProposal`；
- 建议 allowlisted solver/tool action，并根据 observation 修订 proposal；
- 解释 ScenarioSet 中的 trade-off，或在 approval envelope 内建议 materialization recipe/recovery；
- 生成 display summary。

LLM 不可以建立：

- identity、ID、candidate membership、snapshot、scope、lineage 或 digest；
- coordinates、CRS、WKT、GeoJSON、geometry、distance、area、capacity 或 topology truth；
- hard-constraint result、objective measurement、feasible/Pareto membership；
- solver、approval、validation、reconciliation 或 delivery certificate/status；
- atomic commit 或正式 `PlannedState`。

所有模型输出先是 proposal。应用必须重新校验 closed-set membership、input digest、允许字段和预算；solver/GIS/evaluator 必须重新计算约束与指标。provider 失败只能留下 typed diagnostic，不能增加、删除或提升正式方案。单个 claim 无效时只隔离该 claim；禁止重新生成或丢弃整个维度中已验证的 claims。

### ScenarioSet remains the sole authoritative decision artifact

`ScenarioSet` 是 SELECT 的唯一权威结果。正式 scenario 必须绑定同一个 problem fingerprint、确定性 objective vector、hard-constraint result、solver backend/version/input digest 和 certificate。推荐只能指向 formal feasible member；单独保存的 `PlanningScenario`、LLM recommendation、report body 或 worker task 都不是第二权威。

infeasible 是正式、可接受的决策结果。它必须绑定 closed input、solver termination、冲突或界限证据；不得产生 executable `ApprovedExecutionInput`。

## 5. Stage behavior

### 5.1 Rough claims and deterministic admission

L3 的基础模型事务只产生粗粒度 claim drafts。合法 claim 至少表达 planning intent、coarse claim family、planning role、closed objective/fact/evidence refs、可选 location hints、grounding/evidence requirements 与 uncertainty；正式 claim ID 由应用按输入 lineage 和 canonical content 建立。

deterministic admission 负责：

1. 校验 claim family、planning role、refs 和来源充分性；
2. 建立 target ID、group/package identity 与 claim-set lineage；
3. 将 coarse claim family 映射到 allowlisted target family；
4. 从 source-backed values 派生已有 typed parameters，并把未知执行关键字段编译为 typed requirement slots/gaps；
5. 把 claim 分类为 admitted、pending、deferred、invalid 或 non-spatial semantic claim。

项目组件拆分、facility/road/axis/polygon/site 参数、parcel/network refs、relation template、object ref、geometry scope、candidate membership 与 geometry 不属于基础 L3 provider contract。无法确定性建立 target family 或必需输入的 claim 保持 pending/deferred，并生成 typed gap；不得通过扩张 L3 schema 或从 prose 猜测来补齐。

### 5.2 Grounding and scenario proposal

GROUND 产生 closed `GroundedPlanningProblem`。SELECT 在任何 LLM 调用前校验 problem fingerprint、candidate completeness、solver readiness 和 required snapshots。LLM 只收到 named proposal projection：目标、候选 IDs、关系/约束摘要、允许工具、预算和 projection digest；完整 geometry、raw evidence、report body 与 trace 留在确定性 store。

### 5.3 Deterministic solve and approval

proposal validator 拒绝未知 ID、过期 digest、自由 geometry、未注册工具和越权字段。solver/tool portfolio 计算 formal scenarios、metrics、Pareto membership 和 certificate，随后编译一个 `ScenarioSet`。

人工可以从 formal feasible members 中选择、表达政策偏好或明确延期；人工不能把 incomplete、invalid 或 infeasible 结果变成技术可执行。

### 5.4 Approved materialization

EXECUTE 消费不可变的 `ApprovedExecutionInput`。recipe planning 只能决定“如何物化已获批结果”，不能改变“物化什么”。`MaterializationRecipePlan` 必须覆盖全部且仅覆盖 approved targets/candidates，并绑定 approval fingerprint 与 plan semantic digest。

确定性 fast path 可以零 LLM 调用。复杂 case 的 LLM recipe/recovery proposal 只能引用 allowlisted recipe IDs 和稳定 refs；任何 candidate substitution、route/layout/footprint 变化、面积/数量变化、hard-constraint 放宽或新 side-effect target 都必须返回 SELECT、GROUND 或 HUMAN。

### 5.5 Atomic state

所有 worker 在 staging 执行。pre-commit 必须验证 approved-to-staged coverage 为 100%、unexpected outputs 为 0、资源与 geometry 守恒、lineage 完整且 plan digest 未漂移。任一失败使整个 batch `aborted`；只有一次成功 atomic commit 可以产生正式 `PlannedState`。

VALIDATE 独立测量，不修改结果。RECONCILE 对账 canonical chain；DELIVER 只组织同一 run-root、snapshot lineage 和通过证书的 refs。

### 5.6 Planning report ownership

L3 claims 完成后不直接生成详细规划报告。系统可以选择不调用模型，或从 `PlanningClaimSet` 生成一个严格受限的 intent summary；它只能说明规划意图、事实依据、不确定性和待补证项，不能声称已经完成选址、空间关系、数量、容量、路线、分区或方案选择。

详细规划报告的最早合法输入是空间链路返回的 `GroundedPlanningProblem` 与 `ScenarioSet`。该 report projection 必须绑定 problem/scenario refs、fingerprints、formal membership、确定性指标和 unresolved/deferred findings。若报告描述获批或已实施成果，则还必须绑定 `ApprovedExecutionInput`；若作为正式交付报告，则必须等待 `PlannedState`、`ValidationCertificate` 与 RECONCILE 结果。任何报告文本都不能回写 claims、targets、candidate membership、geometry、metrics 或 lifecycle status。

## 6. Ref/digest-only linkage

| Boundary | Required link | Forbidden duplication |
|---|---|---|
| claims → admission | claim refs、claim-set digest、admission decision refs | 完整 claims payload 的第二份副本 |
| admission → GROUND | admitted target refs、typed grounding requirements、parent digest | L1/L2/L3 report body 或完整上游 artifacts |
| GROUND → proposal | problem ref/fingerprint、closed IDs、named projection digest | candidate geometry dump、raw evidence、query trace |
| proposal → ScenarioSet | proposal digest、solver input digest、tool observation refs | 把 proposal 文本当作 feasible truth |
| ScenarioSet → approval | set/member refs、scenario/problem fingerprints、snapshot/baseline digests | 完整 ScenarioSet/problem payload |
| approval → recipe plan | approval ref/fingerprint、recipe allowlist refs、plan semantic digest | 第二份 selected outcome |
| recipe plan → PlannedState | recipe-plan ref/digest、task result refs、atomic commit ID | staged payload 冒充 committed state |
| validation/delivery | approved/scenario/planned-state/certificate refs and digests | 重跑规划或复制上游 bodies |
| L3 intent summary | claim-set ref/digest、accepted/rejected/gap counts、bounded claim labels | candidate、geometry、formal metrics 或详细规划结论 |
| ScenarioSet → detailed planning report | problem/scenario refs、formal metrics、unresolved refs、projection digest | 从 claims/report prose 重建 target 或 geometry |

消费者需要展开时，只能按 ref 水合该消费者 allowlist 中的字段，并重新计算 projection digest。禁止把“为方便”作为复制完整上游 payload 的理由。

## 7. Resume and replay

checkpoint 只保存 artifact refs、digests/fingerprints、typed cursor、budget ledger 和 stop status；大 geometry、完整 upstream payload、provider response 与 audit trace 不进入 graph state。

resume 必须：

1. 验证当前 context fingerprint、artifact digest 和 parent digests；
2. 复用已提交的 proposal/tool/solver/recipe/task refs；
3. 从最早失效 owner 重跑，不能 last-write-wins；
4. 不重复已成功的 provider、solver、worker、external 或 atomic-commit side effect；
5. 对相同 failure/recovery fingerprint 停止伪进展。

## 8. Fail-closed gates

- claim 语义或 evidence lineage 不完整：保持 L3 pending/deferred；target family 或 requirement slots 无法确定性建立：停在 admission/TARGET_PROJECTION；
- candidate、geometry、relation、source 或 snapshot 不完整：回 GROUND；
- solver readiness 不完整：只产生 diagnostic/bounded result；
- 无 formal feasible member：不产生 approval；
- approval、scenario、problem、snapshot 或 plan digest 漂移：在 worker/LLM 前停止；
- recipe 不等价或 worker coverage 不完整：abort staging；
- validation 或 reconciliation 不通过：不产生正式 delivery。

任何 provider/budget failure 都不能伪装成 feasible、approved、committed、validated 或 delivered。

## 9. Normative invariants

```text
INV-P01  PlanningClaimSet is non-executable; only deterministic admission creates AdmittedTargetSet.
INV-P02  ScenarioProposal is temporary and closed-set; it never establishes solver truth.
INV-P03  ScenarioSet is the only SELECT authority and binds deterministic proof.
INV-P04  ApprovedExecutionInput freezes refs/digests, not copied upstream payloads.
INV-P05  MaterializationRecipePlan is derived control state, never a second planning decision.
INV-P06  EXECUTE may change method only when deterministic equivalence is proven.
INV-P07  Formal PlannedState requires complete atomic commit.
INV-P08  Resume reuses stable refs/digests and never repeats committed side effects.
INV-P09  L3 may emit only an intent summary; detailed planning reports require ScenarioSet, and delivery reports require validation/reconciliation lineage.
```

量化验收由 `04_EVALUATION_AND_ACCEPTANCE.md` 定义；当前实现差距只由 `05_MIGRATION.md` 判定。
