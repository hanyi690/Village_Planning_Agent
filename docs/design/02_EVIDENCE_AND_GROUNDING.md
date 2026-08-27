# Evidence Retrieval and Grounding Design

> Status: TARGET
> Authority: Primary normative design for stage-neutral evidence requirements, retrieval, grounding, and consumer projections. Observed runtime behavior belongs in `../architecture/CURRENT_RUNTIME.md`; unfinished convergence and retirements belong in `05_MIGRATION.md`.
> Related invariants: `00_SYSTEM_DESIGN.md`, `01_CONTRACTS_AND_INVARIANTS.md`, `03_PLANNING_EXECUTION.md`, `04_EVALUATION_AND_ACCEPTANCE.md`, `05_MIGRATION.md`.

## 1. Scope

本文件只定义 retrieval 和 grounding 的目标契约边界，不把当前代码中的分散实现误写成“已经存在一个统一 Evidence Plane”或“已经存在一个全局 cognition gate”。

当前代码已经提供若干锚点：`backend/app/evidence/retrieval/requirements.py` 负责从多个阶段编译 `EvidenceRequirement`，`query_planner.py` 负责确定性 query plan，`evidence_service.py` 负责 source adapter 编排与 sufficiency/coverage，`project_cognition.py` 负责 preflight digest 与 prompt-safe projection，`identity_contracts.py` 与 `grounded_problem.py` 分别承载 binding snapshot 和 planning problem。它们说明方向已成型，不说明收敛已经完成。

## 2. Shared evidence flow

唯一规范化的共享流程是：

```text
Any stage
  → EvidenceGap
  → EvidenceRequirement
  → cognition/scope preflight
  → deterministic query plan
  → source adapters
  → normalized EvidenceResult
  → EvidenceCoverage
  → consumer-specific projection
```

这里的 “shared flow” 指契约视角上的统一，而不是要求当前运行时已经只剩一个物理实现入口。任何实现差异、重复 wiring 或阶段特化，都必须服从这条 flow，并在 migration ledger 中显式记账。

### 2.1 `EvidenceGap` is stage-neutral

`EvidenceGap` 是 stage-neutral 的 control record。它表达“还缺什么支持”，不表达“如何检索”，也不表达“已经获得了什么证据”。

规范上，`L1`、`L2`、`L3`、`TARGET_PROJECTION`、`GROUND`、`SELECT` 都可以产生 gap。gap 至少要回答：

- 哪个 stage / artifact / decision 缺支持；
- 缺的是 identity、claim、metric、spatial input、constraint、relation 还是 source lineage；
- 当前结果是继续、降级、defer 还是必须 human review；
- 缺口是否阻断正式语义链。

gap 不是事实，不是 geometry，不是 candidate，也不是第二套 planning claim。

当前代码仍存在 shape 差异：L1/L3 直接携带 `EvidenceGap`，L2 仍有 `L2EvidenceGap`，GROUND 则主要通过 `GroundingFinding`、`unresolved`、`deferred` 表达未满足项。目标设计把这些都视为同一类 lifecycle role；它们何时完全收敛到同一 contract，属于 `05_MIGRATION.md`。

### 2.2 `EvidenceRequirement` is the executable retrieval need

`EvidenceRequirement` 是由应用确定性编译出的可执行检索需求。它回答“必须证明什么、从哪里证明、在什么 scope 内证明、允许什么推断等级、成功条件是什么”。

它至少必须绑定：

- `requesting_artifact_ref` 与 `requesting_artifact_revision`；
- `producer_stage`；
- `statement` 与 `kind`；
- `source_families` 与 `scope`；
- `spatial_granularity` 与 `allowed_inference`；
- `evidence_role` 与 `success_condition`。

`EvidenceRequirement` 可以从 gap 编译，也可以从 typed artifact 直接编译。当前代码已经有 `requirements_from_l1()`、`requirements_from_l2()`、`requirements_from_l3()`、`requirements_from_target_projection()` 和 `requirements_from_ground()` 这些 producer；request-level `compile_requirements()` 仍是过渡入口，不应被误解为最终统一形态。

## 3. L1 compilation boundary

L1 的规范关系是：

```text
LLM L1Observation draft
  → deterministic L1Fact compilation
  → deterministic LocationMention compilation
  → deterministic EvidenceGap compilation
```

这里的 `L1Observation draft` 指 provider 输出的 observation envelope，例如 `L1ObservationProviderOutput` / `L1ObservationPassOutput`。它只是待验证输入，不是正式事实。

### 3.1 `L1Fact` is the canonical semantic evidence

`L1Fact` 是 L1 唯一可被后续阶段稳定引用的 semantic evidence。它必须携带 statement、fact kind、semantic type、source refs、source span、source snapshot 与必要 attributes。

人类可读的 `facts` 列表只是 display projection，不能替代 `L1Fact` 成为引用面。

### 3.2 `LocationMention` is a grounding work item, not geometry

`LocationMention` 是设计角色，当前代码主要由 `L1LocationFact` 承载，并辅以 `L1SpatialMention` 一类 transport/helper 结构。它表达的是 grounding work item：

- mention / normalized name；
- role / scopes / aliases / related mentions；
- source lineage；
- resolution state。

它不等于 resolved identity，不等于 coordinates，不等于 WKT，不等于 authoritative geometry。

当前 `L1LocationFact` 的职责必须理解为“等待接地的空间工作项”。L1 观察中出现地点，不代表系统已经完成定位。

### 3.3 Report bodies do not re-enter the semantic chain

L1 report body 是 display projection。GROUND、Project Bank、SELECT 或下游 retrieval 不得把整篇报告重新当作 primary semantic source 解析。若 L1 缺少必要空间事实，应产生 `EvidenceGap` / `EvidenceRequirement`，而不是在 GROUND 内偷偷重读原文。

## 4. Cognition and scope preflight

在任何 retrieval 执行前，请求都必须先绑定当前 session 的 project cognition 和 scope。

规范上的 preflight 至少包括：

- 当前 `PlanningContext` 对应的 bundle、KG、L1 snapshot identity 与 digest；
- 当前 request 的 `entity_scope`、project-wide/scoped source coverage 和 temporal/spatial scope；
- 可用 source families、bundle layers、KG relations、L1 fact types；
- retrieval 是否只是提示 recall，还是正式约束 source coverage。

当前 `build_project_cognition()` 会构造 `ProjectCognitionSnapshot` 与 `cognition_digest`；`retrieve_evidence()` 会区分 inferred scope hint 与真正的 source coverage。这些是 retrieval preflight 与审计锚点，不是一个已经完成的跨阶段 semantic gate。

## 5. Deterministic query plan and source adapters

preflight 之后，系统必须从 `EvidenceRequirement` 或等价 request boundary 生成确定性的 query plan，而不是把任意自然语言直接扔给所有 retriever。

当前 `build_query_plan()` 已体现这条规则：

- 一个 request 对应一个稳定 fingerprint；
- 每个 routed retriever 拿到一条 bounded query；
- query 保留 full scope、required facts 和 source refs；
- 当前 `max_rounds=2`，属于明确的 bounded loop。

source adapters 是 retrieval 的执行面，不是语义 owner。当前主适配器包括：

- `local_text`
- `report`
- `rag`
- `kg`
- `bundle`
- `artifact`
- `history`
- `external`

它们的职责是执行查询、返回 source-backed rows、保留 lineage 和失败状态。它们不能：

- 从 scope promotion 出 canonical identity；
- 发明 BSM、entity ID、coordinates 或 geometry；
- 把 external POI 直接升级为项目内执行几何；
- 用 adapter 成功代替 requirement satisfied。

dense / embedding 通道不可用时，structured、lexical、KG、bundle 通道必须继续工作，并把降级写入 coverage/audit，而不是把整个 evidence surface 宣布为 unavailable。

## 6. Normalized `EvidenceResult` and `EvidenceCoverage`

共享 flow 中的 normalized `EvidenceResult` 是一个设计角色；当前代码中的直接承载对象是 `ExplorationResult`。

它包含三层边界：

### 6.1 `EvidenceBundle`

`EvidenceBundle` 是 general fact view。它承载：

- `EvidenceFact`
- `EvidenceSource`
- conflicts
- unresolved

它是 answer-facing 的事实面，但仍然不是 prompt-ready projection。事实统一存在 `EvidenceBundle.facts`，而不是再创建一个并行 fact registry。

### 6.2 `EvidencePacket`

`EvidencePacket` 是 spatial retrieval detail view。它承载：

- `candidate_refs`
- `relation_evidence`
- pagination
- `missing_evidence`
- `query_trace`
- opaque `bundle://feature/<BSM>` references

它不是第二个事实注册表，也不是 resolved geometry authority。geometry 仍在 bundle/KG authority 边界之后，只有被允许的 consumer 才能按 opaque ref 回读。

### 6.3 `EvidenceCoverage`

`EvidenceCoverage` 是 requirement-set 级别的 bounded completeness artifact。它必须记录：

- requirement set fingerprint；
- per-requirement coverage；
- claims；
- unresolved requirements；
- unavailable source families；
- conflict refs；
- stop reason。

“完成”以 coverage 为准，不以“某个 retriever 返回了结果”为准。`stop_reason=sufficient` 只能在不存在 unresolved requirements 时成立。

## 7. Consumer-specific projection is the only prompt boundary

只有 consumer-specific projection 可以进入 prompt、API summary 或 display。`EvidenceBundle`、`EvidencePacket`、`EvidenceCoverage` 这三类对象都不能整包进入分析模型。

当前代码的主要锚点是：

- `render_analysis_evidence()`：保留 semantic dedup、conflict grouping、source lineage；
- `render_analysis_evidence_for_prompt()`：进一步排除 raw retrieval、geometry payload、query trace 和重复 source table。

因此，analysis prompt 的允许输入是：

- facts projection；
- coverage projection；
- gap projection；
- 与消费者直接相关的最小 metadata。

analysis prompt 的禁止输入是：

- raw retrieval rows；
- provider response；
- full query trace；
- full report body；
- full geometry payload；
- packet pagination internals；
- 用于审计而非推理的内部控制状态。

### 7.1 L1/L2/L3 consumer projections

三个分析层使用不同的 named projection，不能共用一个“依赖上下文大包”：

| Consumer | Required projection | Explicit exclusions |
|---|---|---|
| L1 observation | 当前 bounded source page、允许的 observation families、source index identity | 其他页原文、下游决策、报告正文、完整 project bundle |
| L2 abstract decision | 直接相关且去重的 canonical L1 facts、scope、coverage/gaps、当前 L2 decision refs | L1 report/summary、完整 source rows、原始 retrieval、几何、历史 messages |
| L3 rough claim | 相关 L2 abstract decisions、这些 decisions 引用的 canonical facts、L3 直接需要的额外 facts、任务级定向 evidence/gaps | L1/L2/L3 report 或 summary、原始 prompt、上游完整 RAG context、relation catalog、candidate geometry、空间参数规范、项目组件模板、历史 messages |

L3 只表达“规划什么、依据什么、大致面向何处、还需要补什么证据”。它可以提出文本化 `grounding requirement`，但不能看到或输出 `relation_template`、`object_ref_kind`、`geometry_scope`、parcel/network membership 或具体 candidate IDs。后者只能在 admission/TARGET_PROJECTION 形成 typed requirement 后由 GROUND 的 closed-set projection 消费。

同一 canonical fact 在一个 projection 中只能出现一次。位置 work item、fact record、source row、display statement 和 evidence ref 若指向同一事实，projection builder 必须选定唯一展开面并以 refs 连接其余身份；禁止把 L1 facts 与 location facts 作为两张可重复的事实表同时注入 L3。

summary 是 display projection，默认不得进入 L2 或 L3 semantic prompt。若某个消费者确需标签，只能按 canonical ref 确定性派生 bounded label，不得传递自由文本 summary。

## 8. Grounding flow and output boundaries

GROUND 的规范输入输出关系是：

```text
LocationMention / SpatialTarget
  → GroundingRequest
  → canonical identity candidates
  → geometry / relationship validation
  → GroundedPlanningProblem
```

这里的 `SpatialTarget` 来自 TARGET_PROJECTION 或等价 admitted planning target；`LocationMention` 来自 L1 mention compilation。

### 8.1 `GroundingRequest`

`GroundingRequest` 是进入 grounding 的最小 contract。它必须把 semantic owner、location hints、required source refs、scope、relation inputs、planning role 与必要的 evidence requirement 绑定起来。

GROUND 可以使用 KG、bundle、L1 mention、typed target input 和 requirement-set 进行候选召回，但不能绕过它们发明 runtime identity。

### 8.2 Canonical identity candidates and validation

GROUND 的核心不是“模型猜一个最像的点”，而是：

1. 在已声明 source families 内召回 canonical identity candidates；
2. 验证 snapshot membership、source lineage、geometry authority、relation inputs 与 uncertainty；
3. 产出可供后续阶段消费的 closed-set binding/problem artifact；
4. 对无法满足的 requirement 保留 unresolved/deferred/human-required。

LLM 可以在闭集 candidate IDs 上做排序、解释或提出 retrieval action，但不能创建：

- 新 ID；
- 新 coordinates；
- 新 geometry；
- 新 CRS；
- 新 candidate membership；
- solver 结论；
- final location；
- recommended scenario。

GROUND 明确禁止写 final location 或 recommended scenario。

### 8.3 `GroundedEntityBindingSnapshot` and `GroundedPlanningProblem`

`GroundedEntityBindingSnapshot` 与 `GroundedPlanningProblem` 的边界必须分开：

- `GroundedEntityBindingSnapshot`：mention-to-entity decisions，服务于 inventory/binding 视角；
- `GroundedPlanningProblem`：planning-ready closed-set problem，服务于 SELECT。

前者不等于 planning candidate domain，后者也不应退化成 mention registry。

`GroundedPlanningProblem` 至少应保持：

- target domains；
- candidate domains；
- candidate geometries；
- relation / constraint inputs；
- parcel / network / shared resource refs；
- unresolved / deferred findings；
- candidate completeness；
- evidence requirements；
- fingerprint。

## 9. `inventory_binding` and `planning_grounding`

目标设计只有一套 grounding contract surface，但允许两种 consumer mode：

- `inventory_binding`
- `planning_grounding`

### 9.1 `inventory_binding`

`inventory_binding` 面向 L1 之后的 inventory / mention resolution。它消费 `LocationMention` 类 work items，输出 `GroundedEntityBindingSnapshot`，并且只负责：

- 对 mention 做 canonical identity binding；
- 保留 ambiguity / unresolved；
- 保留 source lineage；
- 不把 inferred scope 冒充 exact feature。

### 9.2 `planning_grounding`

`planning_grounding` 面向 TARGET_PROJECTION 之后的 planning input closure。它消费 typed spatial targets / spatial requirements，输出 `GroundedPlanningProblem`，并且只负责：

- 生成 closed candidate domains；
- 绑定 geometry / relation / constraint inputs；
- 形成 SELECT 可直接消费的 problem fingerprint；
- 在缺口未补齐时 fail-closed。

### 9.3 Convergence note

这两个 mode 是当前目标设计的共享 contract 视角，不等于代码里已经完成了一个可复用 child graph。当前运行时仍通过 `context_bootstrap.py`、binding store、`target_projection.py`、`ground.py` 等路径分别接线；统一实现和旧路径拆除必须写进 `05_MIGRATION.md`。

## 10. Search scope and planning geometry

模糊定位、村域范围、推断范围、近邻检索范围与正式执行几何必须分开。

如果某个引用当前只能形成 search scope，那么它只能作为 non-materializable scope 使用。无论当前 contract 最终表现为 `SearchScopeRef` 还是等价 projection，它都必须满足：

- 只支持 retrieval / context narrowing / nearby lookup；
- 不自动成为 candidate；
- 不自动成为 execution geometry；
- uncertainty 必须可见；
- source lineage 必须可追溯。

“有一个范围”不等于“已经有了可执行位置”。

## 11. Retirement boundary

active authority surface 已不再把以下概念当作规范产物：

- `GroundedAnchor`
- `grounded_anchors`
- `village_anchor`
- `anchor_cluster`
- `village_cluster`

但这不等于当前代码里这些词已经完全消失。运行时仍有少量非权威内部遗留，例如：

- `identity_contracts.py` 仍识别 `village_anchor:` 粗粒度 geometry；
- `resolver.py` 仍包含 `village_cluster` / `anchor_cluster_selection` 一类内部路径；
- `domain/ground/aggregate.py` 仍使用 `anchor_geometry` 这类内部 geometry role。

这些都只能被视为 non-authoritative internal residue：可用于兼容读取、审计或内部过渡，但不能作为 canonical artifact、完成证据或新的外部 authority surface。当前规范替代物只有：

- `GroundedEntityBindingSnapshot`
- `EvidenceRequirement`-driven retrieval
- `GroundedPlanningProblem`
- explicit scope / candidate / coverage / unresolved boundaries

进一步 retirement 与 shared-graph convergence 只在 `05_MIGRATION.md` 记账。

## 12. Normative invariants

```text
INV-E01  Any stage may emit an EvidenceGap; the gap role is stage-neutral.
INV-E02  Only deterministic compilation may turn a gap or typed artifact into EvidenceRequirement.
INV-E03  L1Observation is a draft; L1Fact is the canonical semantic evidence.
INV-E04  LocationMention work items are not resolved geometry; current code mainly carries them as L1LocationFact.
INV-E05  EvidenceBundle and EvidencePacket are distinct transport surfaces, not competing fact registries.
INV-E06  EvidenceCoverage decides bounded completeness at requirement-set level.
INV-E07  Project cognition binds retrieval preflight and audit metadata, not semantic truth by itself.
INV-E08  Only consumer-specific projections may enter prompts; raw retrieval and geometry payload stay outside.
INV-E09  GROUND binds and validates closed candidates; SELECT chooses; EXECUTE materializes only approved geometry.
INV-E10  Retired GroundedAnchor paths are never restored as active authority.
```
