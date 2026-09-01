# 05 Target Projection 可执行设计

> Status: TARGET with PARTIAL implementation
>
> 本文件只拥有 L3 到 typed grounding request 的编译规则。L1 身份接地见
> <code>L1_GROUND_EXECUTABLE_DESIGN.md</code>；规划可执行接地见
> <code>PLANNING_GROUND_EXECUTABLE_DESIGN.md</code>。

## 1. Responsibility

Target Projection 把 <code>PlanningProgram</code> 中已接纳的 L3 claim 编译为稳定、可审计的
<code>PlanningGroundingRequest</code>。它负责 claim admission、目标身份、operation、
representation purpose、约束与证据需求的结构化；不检索候选、不生成 geometry、不求解。

## 2. Inputs

输入为可重载的 <code>PlanningProgram</code>、L1 final product ref、L1 binding snapshot ref、
current World Model snapshot ref、配置与 evidence refs。输入不完整或 lineage 不闭合时拒绝编译。

## 3. Outputs

~~~text
TargetProjectionArtifact
  admitted_targets[]
  planning_grounding_requests[]
  pending_grounding_work[]
  rejected_claims[]
  gate
~~~

pending 是显式恢复工作，不是可执行 target。

## 4. Public Facade

唯一入口为 <code>TargetProjectionFacade.compile(request)</code>。下游只读取 artifact 和 typed
request，不直接调用 claim parser 或 requirement compiler。

## 5. State Machine

~~~text
RECEIVED → LINEAGE_VALIDATED → CLAIM_ADMITTED → INTENT_COMPILED
  ├─ REQUEST_READY
  ├─ PENDING_GROUNDING
  └─ REJECTED
~~~

每个 claim 必须有唯一终态，pending 不得标记 admitted executable。

## 6. Transactions

一个 PlanningProgram 的投影是单个 artifact 事务。所有 claim 结果均生成后再发布 gate；异常
不得留下只有部分 claim 且标记 PASS 的 artifact。相同输入 digest 重放幂等。

## 7. Invariants

- 每个 request 回溯到 claim、L2 decision、L1 refs 和配置；
- 不创建 entity、representation、resource、candidate、geometry、scenario 或 approval；
- 所有空间 target 都必须进入 Planning Ground；
- pending 只能进入恢复队列，不能旁路进入 SELECT 或 EXECUTE；
- 自然语言数量、面积和关系只能形成待验证 typed requirement，不能被猜成执行参数。

## 8. Failure Taxonomy

区分 invalid lineage、unsupported claim、unresolved target identity、missing relation anchor、
uncompilable constraint、missing evidence requirement 和 runtime failure。不得统一压成
<code>unresolved</code>。

## 9. Gap & Recovery

pending work 携带 claim ref、缺失字段、owner、所需 Evidence/L1-GROUND/HUMAN 动作和重试输入
digest。恢复后必须重新编译受影响 claim；输入无变化时停止。

## 10. Persistence/CAS

投影、request、pending 和 gate 作为同一不可变 artifact 保存。current pointer 使用父
PlanningProgram digest 与目标投影配置 digest 做 CAS。

## 11. Version & Digest

版本向量包含 L3 program、L1 final、L1 binding、World Model、Evidence、compiler/config/schema
digest。任一语义输入改变都会令受影响 request stale。

## 12. Dependency/Invalidation

claim 到 request 是一对多显式依赖。L1 binding 或 World Model 变化只重编受影响 target；
compiler/config 变化重编全部。旧 request 可审计但不能进入 current Planning Ground。

## 13. Deterministic vs LLM Boundary

admission、schema、lineage、单位和允许 operator 均为确定性。LLM 只能从封闭 claim projection
提出结构化候选解释，不能创建引用、坐标、候选或放宽约束；输出需 schema 与规则复核。

## 14. Observability/Trace

记录每个 claim 的 admission reason、编译状态、pending owner、输入输出 refs 和 digest；统计
request ready、pending、rejected、恢复成功率及下游 stale request 拒绝数。

## 15. Acceptance Probe

同一真实 PlanningProgram 中同时覆盖：直接可编译 claim、缺 anchor claim、不支持 claim 和
非空间 claim。验证所有空间 target 都生成 request 或 pending，且不存在到 SELECT 的旁路；
重载 artifact 后结果与 digest 一致。

## 16. Remaining Gaps

当前实现已有 target projection application、requirement compilation 与 validation，但完整
lineage gate、无旁路路由和细粒度 pending taxonomy 仍需按 <code>05_MIGRATION.md</code> 验证。
