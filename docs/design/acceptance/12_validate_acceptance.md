# VALIDATE 成熟度验收卡

设计 owner：<code>../06_SELECT_EXECUTE_AND_CODE.md</code>。当前目标：P1 / MVP Ready。

## Gates

| Gate | 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | PlannedState 与 execution/source lineage 可重载 | <code>PARTIAL</code> |
| Product | ValidationCertificate 区分 pass、failure 与 diagnostic | <code>PARTIAL</code> |
| Consumer | Delivery Readiness Reconcile 只消费证书与 refs | <code>PARTIAL</code> |
| Recovery | 失败指向真正 owner，不在 VALIDATE 内重做规划 | <code>PARTIAL</code> |

探针覆盖 geometry、relation、coverage、lineage 和空/部分结果，证明验证器不产生新规划决策。
P2 的完整规则库、性能和治理后置。Remaining gaps 见 <code>../05_MIGRATION.md</code>。
