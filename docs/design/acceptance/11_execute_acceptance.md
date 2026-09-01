# EXECUTE 成熟度验收卡

设计 owner：<code>../06_SELECT_EXECUTE_AND_CODE.md</code>。当前目标：P1 / MVP Ready。

## Gates

| Gate | 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | approval、scenario、problem 和 source digests 一致 | <code>PARTIAL</code> |
| Product | ExecutionPlan、staged changeset、PlannedState、ExecutionResult 可重载 | <code>PARTIAL</code> |
| Consumer | VALIDATE 消费冻结 PlannedState，不读取 worker 临时态 | <code>PARTIAL</code> |
| Recovery | worker 失败可定位、重放幂等、原子 materialization | <code>PARTIAL</code> |

探针应覆盖多 worker、部分失败、重复重放和 stale approval，证明 EXECUTE 只物化已批准内容，
不会替换候选或修改约束。P2 的并发调度、容量、权限与灾难恢复后置。Remaining gaps 见
<code>../05_MIGRATION.md</code>。
