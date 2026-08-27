# Evaluation and Acceptance

> Status: TARGET
> Authority: Normative correctness, contract-efficiency, prompt-boundary, replay and release gates. Current implementation status belongs only in `05_MIGRATION.md`; observed live evidence belongs in `../architecture/CURRENT_RUNTIME.md`.

## 1. Acceptance rule

系统通过验收必须同时证明：

1. canonical chain 的语义正确、closed-set、可追溯且 fail-closed；
2. 每个阶段只有一个 canonical semantic output；
3. 跨阶段只传 named minimal projection 和 refs/digests；
4. prompt、contract、checkpoint 和 retry input 在显式预算内；
5. 无重复语义字段、无未消费 semantic 字段、无 provider bypass；
6. resume 稳定复用 refs/digests，且不重复已提交副作用。

流畅报告、schema 可解析、单元测试通过或历史 live run 都不能单独证明 release complete。

## 2. Evidence levels

| Level | Meaning | Minimum evidence |
|---|---|---|
| component | 单一 contract/compiler/evaluator 的局部行为 | unit/property tests and exact fixture |
| boundary | 两个 owner 间 projection、失败、lineage 和预算正确 | contract/integration tests plus serialized artifacts |
| scenario | 固定 snapshot 上完成代表性闭环和 replay | deterministic scenario manifest, refs/digests and certificates |
| release | 默认配置、退化路径、恢复和正式交付通过 | versioned benchmark report plus fresh acceptance artifacts |

`CURRENT` 只需要证明表述所限定的当前 capability；“默认 live 能力完成”必须达到 release 级。证据必须记录代码 revision、配置 digest、data snapshot、provider/model、seed、预算、artifact refs 和 evaluator version。

## 3. Semantic-chain gates

| Boundary | Pass condition | Fail-closed result |
|---|---|---|
| L3 → admission | 每个 accepted claim 有 coarse family、planning role、closed objective/fact/evidence refs 和明确 requirements；target/package IDs 由应用建立，执行关键未知项转 typed requirement/gap | pending/deferred/invalid claim or target |
| admission → GROUND | target projection 不含模型生成 identity/geometry，grounding requirements 完整 | `EvidenceGap` / human-required |
| GROUND → SELECT | candidate completeness、solver readiness、snapshot 和 problem fingerprint 闭合 | diagnostic/bounded problem |
| proposal → ScenarioSet | proposal 仅引用闭集 IDs；所有 formal metrics、membership 和 certificate 由确定性 evaluator 产生 | proposal rejected or typed upstream return |
| ScenarioSet → approval | selected member formal feasible，set/member/problem/snapshot digests 一致 | no executable approval |
| approval → recipe plan | tasks 覆盖全部且仅覆盖 approved outcome，plan semantic digest 稳定 | stale/invalid approval |
| recipe plan → PlannedState | staged coverage 100%，unexpected output 0，pre-commit 和 atomic commit 通过 | aborted staging, no formal state |
| PlannedState → delivery | validation/reconciliation 通过并绑定同一 run-root 和 parent digests | diagnostic/partial delivery only |

infeasible problem 可以“诊断完成”，但不能产生 executable approval、formal PlannedState 或成功交付状态。

## 4. Efficiency acceptance gates

每次 boundary benchmark 必须输出机器可读 efficiency manifest。安全和所有权类指标采用零容忍；容量阈值由版本化 manifest 针对 consumer 明确声明，不能省略或在失败后临时放宽。

### 4.1 Contract efficiency

| Metric | Required result |
|---|---|
| `canonical_output_count_by_stage` | 每个 stage 的正式 semantic owner 恰好 1 个 |
| `semantic_owner_violation_count` | 0 |
| `full_upstream_payload_copy_count` | 0 |
| `contract_serialized_bytes` | 不超过该 contract manifest 的显式预算 |
| `projection_to_source_size_ratio` | 不超过 consumer manifest 的显式上限 |
| `field_without_producer_count` | 0 |
| `field_without_consumer_or_lifecycle_count` | 0 |

field-level authority 是 Pydantic/OpenAPI。验收工具从实际 schema 和 producer/consumer declaration 计算结果，不在文档维护第二份字段表。

### 4.2 Prompt projection size

每个 LLM call record 必须记录 stage、contract key、projection name/version/digest、message count、`prompt_input_chars`、`projection_items`、`retry_input_chars` 和预算，且不得记录 prompt body。

通过条件：

- `prompt_input_chars <= prompt_budget_chars`；
- `projection_items <= projection_item_budget`；
- `retry_input_chars <= retry_input_budget_chars`；
- oversize input 在 provider transport 前失败；
- retry 只带原 projection ref/digest、typed error 和允许的修复上下文，不重新拼入完整上游 payload。

至少报告 max、p50、p95 和超预算计数。平均值不能掩盖单次 complete-upstream dump。

### 4.3 Duplicate fields and facts

对 contract、artifact 和单次 prompt 分别计算：

- `duplicate_semantic_field_count == 0`：同一意义不能由多个可写字段拥有；
- `duplicate_fact_representation_count == 0`：同一 fact 不同时以 record、report paragraph、source row 和 trace 重复出现；
- `duplicate_fact_ref_count == 0`：同一 projection 内 ref 去重且排序稳定；
- `conflicting_duplicate_owner_count == 0`：同 stable ID 不同 digest 必须报错，不能覆盖。

必要的 display label 或 audit pointer 必须引用 canonical ref，并在 ownership manifest 中标为 projection；否则按重复字段处理。

### 4.4 Unused fields

`unconsumed_emitted_field_count == 0`。正式 contract 中每个非空 semantic 字段必须在 benchmark corpus 内至少有一个声明 consumer，或明确标记为 display/control/audit、forwarded-by-ref、deprecation/retirement。仅“可能以后有用”不构成 lifecycle。

验收必须同时检查：

- schema 中已无 producer 的字段；
- producer 持续写入但所有 consumer 忽略的字段；
- prompt projection 选择后模型 contract 不可能引用的字段；
- resume 后不会读取、也不参与 digest/失效判断的 checkpoint 字段。

### 4.5 Provider bypass

`provider_bypass_count == 0`。生产 chat/structured/tool-calling 路径必须经过统一 LLM manager admission；禁止 domain/workflow 代码直接调用 provider `invoke/ainvoke`、直接调用低层 structured runner，或自行实现重试、timeout 和 audit。

gate 必须同时包含：

- repository-wide static scan/AST test；
- manager runtime audit 中每个生产模型调用均有 stage、contract key、budget 和 safe metadata；
- provider factory 只负责构造 client，不构成调用授权；
- embedding/vector operation 与 chat-model call 分开计数，不能用 embedding adapter 规避 manager gate。

### 4.6 Resume ref/digest stability

| Metric | Required result |
|---|---|
| `checkpoint_full_payload_count` | 0 for canonical upstream artifacts and geometry bodies |
| `resume_ref_digest_mismatch_count` | 0 on unchanged replay |
| `changed_parent_accepted_count` | 0 |
| `repeated_provider_call_count` | 0 for already committed call refs |
| `repeated_solver_or_tool_call_count` | 0 for committed fingerprints |
| `repeated_worker_side_effect_count` | 0 |
| `repeated_atomic_commit_count` | 0 |

相同输入 resume 必须复用同一 artifact refs、content digests、problem/scenario/plan fingerprints；任一 parent digest 改变时，从最早失效 owner 重跑，并使下游 approval/certificate/delivery 失效。

### 4.7 Leakage and class separation

以下计数必须全部为 0：

- `report_body_leakage_count`：semantic/analysis prompt 中出现完整 report body；
- `audit_trace_leakage_count`：query/solver/provider trace 进入分析 prompt；
- `raw_retrieval_leakage_count`；
- `geometry_payload_leakage_count`，除非 consumer 是明确的 deterministic geometry tool；
- `control_as_semantic_truth_count`：cursor/gap/status 被当作事实；
- `semantic_as_display_copy_count`：完整 semantic artifact 被复制进 display payload 而非按 ref 投影。

### 4.8 LLM transaction and failure atomicity

结构化调用还必须报告 schema、事务范围和失败原子：

| Metric | Required result |
|---|---|
| `provider_schema_forbidden_domain_field_count` | 0；provider schema 不复制 admission/GROUND/solver/execute 内部字段 |
| `heterogeneous_responsibility_count_per_call` | 1；一次调用只有一个认知目的 |
| `accepted_item_lost_due_to_peer_error_count` | 0 |
| `whole_dimension_retry_due_to_single_item_count` | 0 |
| `full_batch_semantic_reask_count` | 0，除非 envelope 本身不可恢复且没有 accepted item |
| `implicit_retry_policy_override_count` | 0 |
| `nested_retry_amplification_count` | 0 |
| `item_rejection_without_error_path_count` | 0 |

每次 call record 除 projection metrics 外，还必须记录 provider schema name/version/digest/serialized bytes、attempt index、retry class（transport/schema/item-semantic/workflow）、input/output item count、accepted/rejected count和 typed error-path histogram。只有初始 message 字符数而没有 schema/retry/item metrics，不能证明结构化调用已受控。

L1/L2/L3 的 benchmark 必须分别证明：L1 page 中单条 observation 可隔离；L2 不因一个 metric/strategy/ref 错误重写全部有效 decisions；L3 不因一个 claim 的内部归一化错误丢弃或重发整个维度。

### 4.9 Report timing and authority

以下计数必须为 0：

- `premature_detailed_planning_report_count`：在 `ScenarioSet` 之前生成或标记为详细规划报告；
- `claim_report_spatial_assertion_count`：只消费 `PlanningClaimSet` 的摘要声称 candidate、geometry、relation、quantity、capacity、formal metric 或 winner；
- `report_created_semantic_owner_count`：报告创建或修改 claim、target、scenario、approval、planned state 或 certificate；
- `unvalidated_delivery_report_count`：正式交付报告未绑定 `PlannedState`、`ValidationCertificate` 和 RECONCILE lineage。

若 L3 intent summary 不是产品必需项，默认验收路径应为零 LLM report call。若保留 intent summary，其 contract、预算和内容规则必须与 post-`ScenarioSet` detailed planning report 使用不同的名称和 owner，不能继续共用 `l3.report` 的模糊语义。

## 5. Domain-quality benchmarks

### 5.1 Evidence and grounding

固定 declared source universe，至少记录 claim recall@k、context precision、source-family coverage、locator accuracy、conflict detection、coverage calibration、entity top-k recall、candidate precision/recall、CRS/unit correctness 和 unresolved calibration。

embedding unavailable 必须单独运行：structured、lexical、KG 和 bundle 通道继续可用，dense degradation 可见，不能误报 requirement sufficient。

### 5.2 Planning and solver

覆盖 feasible、多解、Pareto、capacity conflict、network input、infeasible、upstream gap 和 budget termination。至少记录：

- hard-constraint violation count；
- feasible alternative recall 与 Pareto precision/coverage；
- objective vector correctness；
- proposal closed-set validity；
- solver/backend certificate consistency；
- problem/scenario fingerprint stability；
- infeasibility explanation accuracy；
- provider unavailable 时的 deterministic truth preservation。

一个合法 winner 不能单独通过多方案 benchmark；除非 solver 可复核地证明只有一个 formal feasible member。

### 5.3 Materialization and delivery

覆盖 deterministic fast path、recipe planning、等价/不等价 recovery、worker failure、stale approval、duplicate resume、validation failure 和 delivery projection。至少记录：

- selected-to-materialized coverage；
- unexpected materialization count；
- lineage completeness；
- atomic abort correctness；
- hard-constraint recheck agreement；
- replay fingerprint stability；
- delivery run-root consistency；
- recovery equivalence acceptance/rejection accuracy。

## 6. Complete and partial outcomes

正式 `complete` 至少要求：

- unresolved hard constraints 为 0；
- selected-to-materialized coverage 为 100%；
- required lineage completeness 为 100%；
- unexpected materialization count 为 0；
- approval、ScenarioSet、problem、baseline、snapshot、recipe plan、PlannedState 和 ValidationCertificate digests 一致；
- reconciliation 无未处置遗漏；
- 地图、报告和导出来自同一 run-root；
- 所有 efficiency zero-tolerance gates 通过，所有显式 size budgets 未超限；
- replay 不重复已提交副作用。

存在 deferred/diagnostic target 时，只能声明 scoped/partial outcome；它不能被累计阶段状态、前端完成提示或历史 run 表述提升为全村法定规划完成。

## 7. Required regression surfaces

最低发布检查包括：

1. contract ownership/unused/duplicate-field static checks；
2. prompt projection snapshot、budget、leakage 和 provider-bypass checks；
3. evidence/grounding closed-set and embedding-off benchmarks；
4. solver readiness、ScenarioSet membership/certificate tests；
5. approval/plan digest、staging/atomic commit/validation tests；
6. resume parent-digest invalidation and zero-repeat side-effect tests；
7. 两个不同村庄、设施/共享地块/道路/分区或生态/mixed-worker 的 fresh scenario evidence。
8. L1/L2/L3 item-level quarantine/repair、retry-class 对账和 single-item failure 不丢失 peer items；
9. L3 intent summary、post-ScenarioSet detailed report 与 post-validation delivery report 的时点和 lineage 负例。

具体命令、当前 pass/fail 和剩余缺口只记录在 `05_MIGRATION.md` 或 release benchmark report；本文件只定义不可降低的目标 gate。
