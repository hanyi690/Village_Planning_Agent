# Planning Ground 成熟度验收卡

设计 owner：<code>../PLANNING_GROUND_EXECUTABLE_DESIGN.md</code>。当前目标：P1 / MVP Ready。

## Gates

| Gate | 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | 仅 current、accepted PlanningGroundingRequest 可进入 | <code>PARTIAL</code> |
| Product | representation/resource/geometry/CRS/capability 全闭合后发布 problem | <code>PARTIAL</code> |
| Consumer | SELECT 只消费 READY_FOR_SELECT 的 GroundedPlanningProblem | <code>PARTIAL</code> |
| Recovery | 每个 target gap 有明确上游 owner，增量重建 | <code>TARGET</code> |

## 必测探针

- entity-only L1 binding 在缺执行 representation 时不能 PASS；
- 缺 CRS、缺 capability、多表示冲突和零候选均有不同 reason；
- external observation point 不能成为执行 geometry；
- hard constraint 缺 evaluator 时产生 gap；
- <code>passed=true + pending</code> 被拒绝；
- source/WM 变化只失效受影响 target domain。

P2 的大候选域性能、并发、空间服务 SLO 与治理后置。Remaining gaps 见
<code>../05_MIGRATION.md</code>。
