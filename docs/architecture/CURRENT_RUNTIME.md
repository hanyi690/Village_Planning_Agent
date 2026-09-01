# Current Runtime

> Status: CURRENT
>
> 本文件只描述当前工作树中可观察的代码和 contract。目标设计见
> <code>../design/README.md</code>，完成度判断见 <code>../design/05_MIGRATION.md</code>。

## 1. 运行入口

- FastAPI：<code>backend/app/main.py</code>；
- lifespan/composition：<code>backend/app/bootstrap/</code>；
- runtime service：<code>backend/app/infrastructure/runtime/planning_runtime_service.py</code>；
- root workflow：<code>backend/app/workflow/graph.py</code>；
- segments：<code>backend/app/workflow/segments.py</code>。

当前图分为：

~~~text
intent_loop
cognitive
spatial_chain
hitl
~~~

当前空间链：

~~~text
TARGET_PROJECTION
  → GROUND
  → SELECT
  → EXECUTE
  → VALIDATE
  → RECONCILE
  → DELIVER
~~~

SELECT 可回到 GROUND；VALIDATE 可按 failure artifact 回到责任阶段。

## 2. DATA 与 current-world admission

当前代码包含：

- <code>DataResourceCatalog</code> 和 <code>SessionDataSnapshot</code>；
- GIS、文档、表格、栅格描述等 adapter；
- source role/admission；
- purpose-specific representation/resource/capability；
- 无 BSM 的 source feature identity；
- current/planned/reference/unclassified 的入口隔离；
- geometry 仍由 DATA resource 加载。

主要入口：

~~~text
backend/app/data/resource_catalog.py
backend/app/data/admission.py
backend/app/data/model/snapshot.py
backend/app/data/ingestion/
backend/app/spatial/model/workspace.py
~~~

代码存在这些边界不等于所有格式、媒体和复杂来源都已完成验收。

## 3. Cognition / World Model

当前 V2 实现：

~~~text
backend/app/contracts/cognition/
backend/app/contracts/ports/world_model.py
backend/app/modules/cognition/
backend/app/infrastructure/cognition_runtime/world_model_store.py
backend/app/infrastructure/kg/adapters/source_catalog_adapter.py
~~~

可观察能力：

- DATA catalog 投影为 source/entity/part/representation 支持；
- <code>SessionWorldModelSnapshot</code>；
- TriG/descriptor artifact 持久化；
- named <code>world_model</code> ref compare-and-set；
- bounded entity/representation/relation/identity-binding query；
- intent/planned/identity commit port；
- identity commit 的 frozen envelope 和 typed result；
- legacy KG identity commit 返回 unsupported，而不是部分写入。

仍未在代码层完整体现的目标：

- assertion 全状态机和通用 proposal/decision transaction；
- merge/split + supersede + affected binding invalidation；
- typed Current/Intent/Planned query ports；
- dependency/subgraph digest；
-通用 stale-parent rebase；
- 多进程 writer lease/fencing 的生产实现。

这些是 GAP/PARTIAL，不得从 CAS 已存在推断为已经完成。

## 4. Evidence

当前入口：

~~~text
backend/app/contracts/evidence/
backend/app/modules/evidence/
backend/app/infrastructure/evidence_runtime/
~~~

可观察能力：

- typed <code>EvidenceRequirement</code>；
- requirement compilation 和 fingerprint；
- frozen retrieval authority；
- sufficient/partial/insufficient/human/failed outcome；
- write-once retrieval artifact 和 receipt；
- coverage/sufficiency 基础计算；
- immutable <code>EvidenceGapLedger</code>；
- gap scheduler row；
- local text、KG、artifact、cache 等 retriever 路由；
- external observation 的坐标信任与 advisory evidence boundary。

仍未完整实现：

- requirement-specific authority/时效/独立来源/conflict policy；
- retryable/permanent/quota/partial provider attempt contract；
- 跨 provider conflict/fusion；
- Evidence→Cognition proposal contract；
- 统一语义 benchmark。

## 5. L1 与 L1 Identity GROUND

L1 当前包含：

- bounded source page 和 <code>L1InputContext</code>；
- per-dimension observe/report pass；
- typed <code>L1Fact</code>、<code>LocationMention</code>、<code>EvidenceGap</code>；
- source quote/row validation 逻辑；
- spatial work-item admission；
- aggregate <code>L1Snapshot</code> 与 CAS ref。

L1 Identity GROUND 当前包含：

- L1 location mention → <code>EvidenceObservationSnapshot</code>；
- source/catalog/WM/evidence 候选召回；
- closed-set model proposal 与 deterministic check；
- <code>GroundedEntityBindingSnapshot</code>；
- exact/feature-set/inferred/name-only/ambiguous/unresolved/not-applicable 兼容状态；
- <code>IdentityBindingCommitEnvelope</code>；
- V2 store 的 atomic identity projection；
- <code>L1WorldProjectionSnapshot</code> receipt。

当前 orchestration 位于 <code>modules/ground/application.py</code>，它通过
<code>WorldModelCommitPort</code> 提交。目标设计把“proposal producer”和“Cognition writer”
进一步显式分层；当前代码尚未具备完整终态 taxonomy、post-commit revalidation 和
<code>L1ProductManifest</code>。

## 6. L2/L3、TARGET 与 Planning GROUND

当前 typed 产品：

~~~text
L2Strategy / L2DecisionSet
PlanningProgram / PlanningClaimSet
IntentCompilationResult / GroundingRequest
GroundedPlanningProblem
GroundingBinding / candidate domains / constraint factors
~~~

当前 TARGET 可以登记 pending grounding work。当前 GROUND gate evaluator 仍有
<code>passed=True</code> 同时携带 pending request 的兼容表达；路由层会把 pending 作为未闭合
输入阻止正式下游。目标 contract 已统一为 recovery route 必须 <code>passed=False</code>，
但代码尚未完成该迁移。

Planning GROUND 已支持 entity/part/representation/resource lineage、无 BSM DATA geometry、
闭集候选和 typed problem；复杂多表示、关系和语义质量仍为 PARTIAL。

## 7. SELECT、EXECUTE 与交付

当前 typed 产品：

~~~text
ScenarioSet
SolverReadiness
SelectionDecision / SelectionDecisionSet
ApprovedExecutionInput
ExecutionPlan
SpatialChangeSet / ParcelChangeSet
PlannedState
ValidationCertificate
FinalManifest
DeliverySpatialSnapshot / DeliveryManifest
~~~

可观察边界：

- SELECT 检查 grounded problem、solver readiness、feasible scenario、resource binding 和 approval；
- SelectionDecision 传递 resource/representation/operation lineage；
- EXECUTE 校验 approval、scenario 和 plan digest；
- generic point/line/polygon/multipatch 与 parcel compatibility 分流；
- <code>PlannedState.features</code> 是 non-cadastral 规范输出；
- VALIDATE/RECONCILE/DELIVER 通过 artifact refs 消费；
- delivery 可表达 complete/partial/diagnostic-only。

当前仍未证明所有 target、solver、repair、mixed-worker 和真实多层交付均满足生产验收。

## 8. State、API 与 HUMAN

<code>WorkflowState</code> 保存 stage、routing、diagnostics 和 artifact refs；完整业务产品单独
持久化。API/SSE/resume 的 owner 见 <code>API_AND_STATE.md</code>。

当前有 HUMAN route、pending request、human-review API 和 checkpoint/resume。当前还没有统一
的不可变 <code>HumanDecisionArtifact</code> 覆盖 admission、identity、representation 和
approval；因此不能把 HUMAN 状态存在描述成完整人工决策模块。

## 9. 当前最重要的不一致

1. GROUND gate 的 passed/pending 表达不唯一；
2. World Model query 尚未拆成 typed views；
3. global WM digest 尚未配套 dependency/subgraph digest；
4. assertion merge/split/rebase 生命周期未闭合；
5. Evidence sufficiency 仍未业务化到所有 requirement；
6. L1 final product 仍由多个 ref 组合，尚无 manifest；
7. 语义 benchmark 尚未成为 release gate。

这些差距在 <code>../design/05_MIGRATION.md</code> 维护。

## 10. 可重复验证入口

~~~text
python -m compileall -q backend/app
python scripts/acceptance/business_stage_boundary_probe.py
python scripts/acceptance/l1_facade_probe.py --help
python scripts/acceptance/l1_l2_facade_probe.py --help
python scripts/acceptance/ground_current_session_probe.py --help
python -m pytest tests -q
git diff --check
~~~

只有本次实际执行成功的命令才能在任务报告中标为 runtime verified；本文件不保留旧 session
id、临时 digest、test count 或一次性运行叙述。
