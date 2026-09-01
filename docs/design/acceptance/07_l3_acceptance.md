# L3 成熟度验收卡

设计 owner：<code>../03_PLANNING_INTENT.md</code>。当前目标：P1 / MVP Ready。

## Gates

| Gate | 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | L2DecisionSet、L1 final/binding 与 current WM lineage 一致 | <code>PARTIAL</code> |
| Product | PlanningProgram/claims/pending grounding items 可重载 | <code>IMPLEMENTED</code>，完整 lineage 待验 |
| Consumer | 所有空间 claim 只交给 Target Projection | <code>PARTIAL</code> |
| Recovery | 不可编译 claim 保留 typed gap，不猜 geometry/参数 | <code>PARTIAL</code> |

## Probe 与 deferred

探针同时覆盖空间与非空间 claim，证明 LLM 只生成粗意图，且每个空间 claim 形成 typed target
输入或 pending item；不存在直接 candidate/geometry/execute 参数。P2 广度与规模后置。
Remaining gaps 见 <code>../05_MIGRATION.md</code>。
