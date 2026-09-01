# 10 跨模块可执行基线

> Status: TARGET with PARTIAL implementation
>
> 本文件只定义跨模块产品流、Gate、写入权、增量执行、人工决定和验收顺序。模块内部算法分别
> 由 DATA、<code>01</code>、<code>04</code>、Target Projection、两类 Ground、<code>07</code>
> 及 L2/L3/执行设计
> 负责，避免再复制第二套模块说明。

## 1. 阶段目标

当前开发分成两个闭环，不用“完整生产系统”标准混评初期认知链。

### 1.1 初期：认知闭环

~~~text
DATA snapshot
  → WM bootstrap v0
  → Evidence bootstrap
  → L1 observation
  → Evidence enrichment
  → L1-GROUND
  → Binding/Assertion Proposal
  → Cognition validation
  → WM commit v1
  → binding revalidation
  → L1 final view
~~~

退出条件是：真实输入可跑、可重放、每个工作项有终态、WM 更新原子且 L2/L3 能读取稳定
current-world projection。并不要求此时 SELECT/EXECUTE/DELIVER 已生产完备。

### 1.2 中期：规划 MVP

~~~text
stable WM/L1
  → L2
  → L3
  → TARGET_PROJECTION
  → Planning GROUND
  → SELECT
  → EXECUTE
  → VALIDATE
  → RECONCILE
  → DELIVER
~~~

MVP 限定 existing-feature binding、facility placement、site-area selection、road connection
和 simple zone allocation；空间能力限定 select、buffer、intersect、difference、point
placement、network connection 及明确登记的 repair/derivation。

## 2. 事实、设计与验收的表示

任何能力只能使用以下标签：

| 标签 | 含义 |
|---|---|
| <code>IMPLEMENTED</code> | 代码/contract 已存在，但不代表真实验收 |
| <code>RUNTIME_VERIFIED</code> | 由当前可重复命令或 fresh artifact 验证 |
| <code>PARTIAL</code> | 有实现，仍缺目标 contract、真实链路或迁移出口 |
| <code>TARGET</code> | 仅设计，尚不能当作现状 |
| <code>HISTORICAL</code> | 只解释过去，不作为当前设计或运行输入 |

设计正文描述 TARGET；现状证据只在 <code>architecture/CURRENT_RUNTIME.md</code>；目标到现状
差距只在 <code>05_MIGRATION.md</code>。任何测试数量、session id、临时 digest 或一次运行日志
都不进入本文件。

## 3. 规范产品图

~~~text
DataResourceCatalog / SessionDataSnapshot
  ↓
SessionWorldModelSnapshot v0
  ↓
EvidenceStageSnapshot + EvidenceGapLedger
  ↓
L1ObservationSnapshot
  ↓
EvidenceObservationSnapshot
  ↓
L1BindingSnapshot
  ↓
L1WorldProjectionSnapshot / SessionWorldModelSnapshot v1
  ↓
L1FinalProduct / L1ProductManifest
  ↓
L2Strategy
  ↓
PlanningProgram
  ↓
TargetProjectionArtifact / PlanningGroundingRequest
  ↓
GroundedPlanningProblem
  ↓
ScenarioSet / SelectionDecisionSet / ApprovedExecutionInput
  ↓
ExecutionPlan / SpatialChangeSet / PlannedState
  ↓
ValidationCertificate / DeliveryReadinessManifest / DeliveryManifest
~~~

Workflow state 只保存控制字段和 artifact refs，不嵌入这些完整产品。

## 4. 唯一写入者矩阵

| 对象/命名空间 | 唯一写入边界 | 只读消费者 |
|---|---|---|
| DATA source/current snapshot | DATA admission/ingestion | Cognition、Evidence、规划阶段 |
| World Model source graph | Cognition bootstrap adapter | Cognition、Evidence |
| assertion/world graph | Cognition validator + commit port | L1/L2/L3/Evidence/GROUND/SELECT |
| intent graph | Cognition intent commit port | GROUND/SELECT/EXECUTE |
| planned graph | Cognition planned commit port | VALIDATE/RECONCILE/DELIVER |
| Evidence artifact/gap ledger | Evidence application/store | 所有业务阶段 |
| L1 facts/mentions | L1 application | Evidence/GROUND/L2/L3 |
| binding proposal | L1-GROUND | Cognition |
| executable candidate domain | Planning GROUND | SELECT |
| scenario/selection | SELECT | EXECUTE/审计 |
| spatial changes/planned state | EXECUTE | VALIDATE/交付 |
| HumanDecisionArtifact | human-review command boundary | 原责任模块/Cognition |

“模块调用 commit port”不等于该模块成为 writer。writer 是实施验证、原子提交和版本发布的
Cognition transaction。

## 5. 唯一 Gate Transition Matrix

以下矩阵覆盖所有正式 stage。模块文档不得另写相反语义。

| 当前产品状态 | may enter next | 允许操作 | recovery owner | terminal |
|---|---:|---|---|---:|
| <code>ready</code> 且无 pending/hard gap | 是 | 正式下游事务 | next stage | 否 |
| <code>partial</code>，gap 不破坏当前产品不变量 | 否（正式链） | 持久化、诊断投影、gap 调度 | producer/Evidence | 否 |
| <code>pending_resolution</code> | 只进入声明的 recovery worker | Evidence/GROUND/Cognition 解析 | 指定 owner | 否 |
| <code>human_required</code> | 否 | 生成 review package，等待决定 artifact | HUMAN | 否 |
| <code>blocked_retryable</code> | 否 | bounded retry/resume | infrastructure/owner | 否 |
| <code>rejected</code> | 否 | 审计、上游修订 | producer/upstream | 可配置 |
| <code>diagnostic_only</code> | 否 | 交付诊断，不执行空间变更 | DELIVER diagnostic | 是 |
| <code>failed_permanent</code> | 否 | 失败报告 | operator | 是 |
| <code>completed</code> | 不适用 | 已交付 | none | 是 |

### 5.1 Gate 不变量

- <code>passed=True</code> 意味着 required inputs 闭合，且
  <code>pending_requests/evidence_requests</code> 均为空；
- 携带 pending 的 artifact 可以存在，但 Gate 必须是 recovery route，不是 PASS；
- TARGET pending 可进入 GROUND resolution worker，不能因此进入正式 SELECT；
- Planning GROUND 只有 resolved executable domain 才能进入 SELECT；
- SELECT 只有 feasible scenario、完整 resource binding 和有效 approval 才能进入 EXECUTE；
- diagnostic output 使用显式 terminal，不伪装成正式 SELECT/EXECUTE 成功；
- HUMAN 决定后重新经过责任模块验证，不能直接翻转 gate 字段。

当前代码若仍产生 <code>passed=True + pending</code>，按迁移兼容解释为“不允许下游”；代码应
收敛到本矩阵。

## 6. Context 与 Structured Runtime

所有 LLM 业务事务共享：

~~~text
ContextRuntime
  snapshot-bound projections
  page/cursor/budget
  current-world view
  dependency refs

StructuredRuntime
  response schema
  closed-set membership
  row/column/depth limits
  ref closure
  parser diagnostics
~~~

默认输入是有界二维 row page；复杂对象和 geometry 通过 ref 查询。业务模块不得复制 prompt
截断、整图序列化、JSON repair 或 provider retry。

## 7. World Model 版本与局部依赖

每个下游 artifact 同时记录：

~~~text
global_world_model_snapshot_ref/digest
dependency_refs
dependency/subgraph_digest
producer_contract_version
input_artifact_refs/digests
~~~

判定规则：

- global digest 相同：可直接重放；
- global digest 不同但 dependency digest 相同：可复用该 row；
- dependency digest 不同：只重算受影响 row；
- epoch 或 admission policy 改变：按影响范围强制 rebase；
- planned graph 改变：current-only L1/Evidence artifact 不 stale。

这解决“小 assertion 更新导致整条链全部失效”和“旧 artifact 无条件继续使用”两种极端。

## 8. 增量执行协议

每个可重算 row 记录：

~~~text
row_ref
producer_stage
input refs/digests
dependency refs/digest
query/candidate fingerprint
model/provider/evaluator version
decision
output digest
status
recovery pointer
~~~

事件到达后的通用算法：

1. 解析 changed refs；
2. 查询 dependency index；
3. 标记受影响 row stale；
4. 重跑最早责任阶段；
5. 比较新旧 output digest；
6. 未变化则停止传播；
7. 变化则沿依赖边发布 invalidation；
8. 生成新 manifest，不覆盖旧 artifact。

整层/整链重跑只允许在 schema/admission/epoch 发生无法局部描述的变化时使用。

## 9. HumanDecisionArtifact

人工不是一个状态字符串，而是不可变、可审计输入：

~~~text
decision_ref
subject_ref / decision_kind
candidate_refs
decision
reason
operator_ref
evidence_refs
scope
context_version/fingerprint
world_model_snapshot_ref/digest
supersedes
created_at
~~~

应用流程：

~~~text
review package
  → HumanDecisionArtifact
  → owner validation
  → assertion/admission/approval proposal
  → atomic commit
  → affected-row revalidation
~~~

同一 subject 的新决定通过 supersedes 形成链；旧 context/WM 上的决定默认 stale。

## 10. 约束编译边界

L2/L3 产生语义规则，Target Projection 结构化意图，Planning Ground 编译 typed constraint，
SELECT 求解：

~~~text
semantic requirement
  → constraint_ref/operator/unit/threshold/scope/valid_time
  → hard_or_soft/lexicographic_tier/source_ref
  → evaluator capability
  → grounded factor
  → solver
  → feasibility/unsat certificate
~~~

LLM 不能动态执行空间函数或把软目标提升为硬约束。无解时保留 unsat/infeasibility certificate，
不得静默删除约束以获得场景。

## 11. Current / Intent / Planned 隔离

隔离必须同时存在于四层：

1. DATA admission：planned/reference/unclassified 不进入 current snapshot；
2. typed WorldView：L1/L2/L3 不具 planned query capability；
3. artifact lineage：每个输入声明 namespace 和 role；
4. runtime guard：候选、执行和交付再次验证 admission/view。

文件名、图层名、自然语言提示和模型判断都不能突破这些边界。

## 12. 错误与恢复所有权

| 错误 | owner |
|---|---|
| source role/CRS/parse | DATA |
| schema/entity/assertion/commit | Cognition |
| provider/query/coverage/sufficiency | Evidence |
| fact/source-span/conflict | L1 |
| mention/entity/scope/relation identity | L1-GROUND |
| execution representation/resource/geometry/CRS/capability | Planning Ground |
| solver readiness/feasibility/approval | SELECT |
| geometry operation/atomic changeset | EXECUTE |
| invariant/lineage/quality | VALIDATE |
| human authority decision | HUMAN command boundary |

下游发现问题必须通过 recovery pointer 返回 owner，不能在下游补造上游事实。

## 13. 初期验收顺序

~~~text
A. DATA snapshot reload/admission
B. WM bootstrap reload/CAS
C. Evidence bootstrap + provider state correctness
D. L1 observation/source-span validation
E. L1 location work-item terminal taxonomy
F. Cognition identity commit/rebase
G. binding revalidation
H. L1 final view consumed by a bounded L2 probe
~~~

完成 A–H 才能把认知闭环标为 CURRENT。

## 14. 中期 MVP 验收顺序

~~~text
I. non-empty L2/L3 typed products
J. TARGET pending/admitted routing
K. Planning GROUND executable domains
L. SELECT feasible/unsat certificate
M. approval artifact
N. generic point/line/polygon EXECUTE
O. VALIDATE/RECONCILE
P. non-empty DELIVER with lineage
~~~

固定 fixture、空 changeset、baseline copy 或单个 facade import 不能替代纵向验收。

## 15. 语义 benchmark

~~~text
schema mapping precision
entity false-merge / false-split
GROUND candidate recall@K
final grounding precision
representation-purpose accuracy
Evidence sufficiency false positive/negative
hard constraint violation count
plan result expert review
~~~

所有 contract PASS 但实体绑错，不算系统正确。

## 16. 文档责任

- <code>00_SYSTEM_DESIGN.md</code>：业务主链和阶段目标；
- <code>01_CONTRACTS_AND_INVARIANTS.md</code>：L1；
- <code>04_EVIDENCE.md</code>：Evidence；
- <code>05_PROJECTION_AND_GROUND.md</code>：Target Projection；
- <code>L1_GROUND_EXECUTABLE_DESIGN.md</code>：L1 mention-to-entity/scope；
- <code>PLANNING_GROUND_EXECUTABLE_DESIGN.md</code>：执行表示、资源和候选闭集；
- <code>DATA_EXECUTABLE_DESIGN.md</code>：DATA admission/capability；
- <code>07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md</code>：Cognition/WM；
- <code>06_SELECT_EXECUTE_AND_CODE.md</code>：SELECT/EXECUTE/交付；
- 本文件：跨模块协议；
- <code>05_MIGRATION.md</code>：唯一完成度账本。

不再维护第二份“全模块字段表”或把 provider 专项、旧 parcel 迁移和逐次运行日志塞入本文件。
