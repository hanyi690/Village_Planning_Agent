# SELECT 成熟度验收卡

设计 owner：<code>../06_SELECT_EXECUTE_AND_CODE.md</code>。当前目标：P1 / MVP Ready。

## Gates

| Gate | 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | 只接收 READY_FOR_SELECT 且 digest current 的 problem | <code>PARTIAL</code> |
| Product | ScenarioSet/无解或 diagnostic certificate 可重载 | <code>IMPLEMENTED</code>，边界待验 |
| Consumer | 只有明确审批的 ApprovedExecutionInput 进入 EXECUTE | <code>PARTIAL</code> |
| Recovery | 输入变化时重求解；无变化时停止 | <code>PARTIAL</code> |

探针需证明 solver 不扩充候选、不放宽硬约束，LLM 只解释 formal scenario，且无方案、需审批和
可执行方案三种结果互斥。P2 的大规模优化、性能与公平治理后置。Remaining gaps 见
<code>../05_MIGRATION.md</code>。
