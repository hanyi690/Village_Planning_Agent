# Planning Ground 可执行模块设计

> Status: TARGET with PARTIAL implementation
>
> Planning Ground 将已编译规划 target 接地为可求解的本地资源、表示、geometry、CRS 和候选
> 闭集。与允许 entity-only 的 L1-GROUND 不同，本模块的正式 PASS 必须满足执行能力要求。

## 1. Responsibility

Planning Ground 消费 <code>PlanningGroundingRequest</code>，按 operation/purpose 选择 World Model
entity 的适用 representation 和 DATA resource，验证 geometry/CRS/capability，编译关系与硬约束，
最终生成 <code>GroundedPlanningProblem</code>。它不改变 L3 意图、不求解胜者、不做审批或执行。

## 2. Inputs

~~~text
TargetProjectionArtifact ref
accepted PlanningGroundingRequest[]
L1FinalProduct ref
L1BindingSnapshot ref
current WorldModelSnapshot ref/digest
ResourceCatalogSnapshot ref/digest
EvidencePacket refs
solver/evaluator capability registry
budget and recovery cursor
~~~

所有 request 必须为 current、lineage 完整且非 pending。stale 或 pending request 只能进入恢复路径。

## 3. Outputs

~~~text
GroundedTargetDomain[]
GroundedCandidateDomain[]
GroundedPlanningProblem
PlanningGroundGate
PlanningGroundGap[]
CandidateAndConstraintTrace
~~~

每个 executable candidate 至少引用 target、entity/part、representation、resource、source
feature/snapshot、WM snapshot、geometry kind/CRS/digest、required capabilities、evidence/assertion、
relation finding、hard constraint finding 和 candidate status。

## 4. Public Facade

共享 runtime 暴露独立的 <code>PlanningGroundingPort.ground(request)</code>。SELECT 只能消费该
port 发布的 PASS artifact；不得自行查询 DATA/KG 并补候选。

## 5. State Machine

~~~text
REQUEST_ACCEPTED
  → ENTITY_RESOLVED
  → PURPOSE_COMPILED
  → REPRESENTATION_SELECTED
  → RESOURCE_BOUND
  → GEOMETRY_CRS_VERIFIED
  → CAPABILITIES_VERIFIED
  → CANDIDATES_CLOSED
  → CONSTRAINTS_COMPILED
  → PROBLEM_VALIDATED
  ├─ READY_FOR_SELECT
  ├─ RECOVERY_REQUIRED
  ├─ HUMAN_REQUIRED
  ├─ NO_FEASIBLE_DOMAIN
  └─ REJECTED
~~~

<code>READY_FOR_SELECT</code> 是唯一正式 PASS 终态。

## 6. Transactions

每个 target domain 可独立构建并缓存，但整个 planning problem 只有在所有 required target 均
闭合后原子发布 PASS。partial/diagnostic artifact 可以保存，不能与 PASS gate 同时出现。相同
依赖向量重放幂等。

## 7. Invariants

1. 所有规划空间 target 都走 L3 → Target Projection → Planning Ground → SELECT。
2. 没有 bypass、默认中心点、首个同名要素或 provider point 兜底。
3. representation 必须适配 operation/purpose，而非仅仅“有 geometry”。
4. resource、geometry、CRS 和 required capability 全部可验证。
5. external observation 只能是 evidence ref。
6. 硬约束缺输入或 evaluator 不支持时，不生成 executable candidate。
7. SELECT 只能在本模块冻结的候选闭集上求解。
8. <code>passed=true + pending</code> 非法。

## 8. Failure Taxonomy

区分 entity unresolved、representation missing/ambiguous、resource missing/stale、geometry
missing/invalid、CRS unresolved、capability missing、relation anchor unresolved、hard constraint
uncompilable、candidate domain empty、evidence insufficient、stale dependency、human decision required
和 runtime/provider failure。

无候选必须给出 deterministic blocking reason，不能只返回空列表。

## 9. Gap & Recovery

每个 gap 指向 target、失败状态、缺失 capability/input、owner 与恢复路径：DATA 补资源或 CRS，
L1-GROUND 补 identity/anchor，Evidence 补 requirement，Target Projection 修正 typed intent，HUMAN
做不可替代决定。依赖无变化时停止；恢复后只重建受影响 target domain。

## 10. Persistence/CAS

target domain、candidate set、constraint IR、problem、gate、gap 和 trace 均为不可变 artifact。
发布 current problem 时 CAS 校验 target projection、WM、resource catalog、L1 binding 和 evaluator
registry digests；冲突时不留下部分 PASS。

## 11. Version & Digest

~~~text
target_projection_digest
l1_final_and_binding_digest
world_model_snapshot_digest
resource_catalog_digest
evidence_packet_digest
representation_requirement_fingerprint
candidate_set_digest
constraint_compiler/evaluator/config version
~~~

任何执行相关 digest 改变都令问题或相应 candidate stale。

## 12. Dependency/Invalidation

target → entity → representation → resource → geometry/capability → relation/constraint → problem 的
依赖必须显式索引。WM merge/split、source/geometry/CRS、L1 anchor、Evidence 或 evaluator 变化时，
只失效相关 target domain；若闭集 digest 不变则不得重复求解前置过程。

跨模块失效的唯一 owner 是 Dependency Runtime。DATA 只发布 DATA-owned `DataChangeSet`，不直接
清理 WM/Evidence cache，也不直接决定 Planning Ground 的 stale row。Dependency Runtime 将 DATA
change set、WM change set、Evidence packet 和 Ground dependency index 合并后，按
target → entity → representation → resource → geometry/capability → relation/constraint → problem
的反向边精确唤醒受影响 domain；没有完整 dependency metadata 时才采用声明的保守策略。

## 13. Deterministic vs LLM Boundary

确定性逻辑负责 capability blocking、geometry/CRS、valid time、authority、关系测量、硬约束 IR、
candidate closure 和 gate。LLM 只能对闭集候选或受限表示用途给出建议/弃权，不能创建 candidate、
geometry、坐标、resource、operator 或放宽 hard constraint；建议必须再验证。

## 14. Observability/Trace

记录每个 target 的状态迁移、候选召回与过滤、representation 选择依据、geometry/CRS/capability
验证、constraint 编译、gap routing 和 gate。统计 ready rate、零候选原因、capability miss、stale
拒绝、增量重建范围和下游 SELECT 消费成功率。

## 15. Acceptance Probe

真实规划探针至少覆盖点/线/面用途、关系 anchor、缺 CRS、缺 capability、多 representation 与零
候选：

1. 合法 target 生成可重载 GroundedPlanningProblem；
2. entity-only L1 binding 在无执行 representation 时明确失败，不能通过；
3. pending Target 不进入正式候选域；
4. provider point 不成为执行 geometry；
5. 只有 READY_FOR_SELECT artifact 被 SELECT 消费；
6. source/WM 变化只重建受影响 domain；
7. hard constraint 缺 evaluator 时产生 gap 而非被忽略。

## 16. Remaining Gaps

当前实现已有 typed grounded problem、candidate builder、reference resolution、constraint/stage
流程的部分能力；统一 purpose-aware representation gate、完整 capability/CRS 检查、无旁路路由、
精确依赖失效和独立 PlanningGroundingPort 仍需按 <code>05_MIGRATION.md</code> 验证与收敛。
