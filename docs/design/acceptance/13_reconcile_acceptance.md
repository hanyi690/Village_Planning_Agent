# Delivery Readiness Reconcile 成熟度验收卡

设计 owner：<code>../06_SELECT_EXECUTE_AND_CODE.md</code>。当前目标：P1 / MVP Ready。

## 职责边界

RECONCILE 是交付就绪度 ledger/classifier。它汇总 ValidationCertificate、阶段产品、gap、approval
和 lineage，分类 complete、partial、diagnostic_only 或 failed；它不解决 Evidence、identity、
geometry、candidate、constraint、approval 或 execution 问题。

| Gate | 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | 所有必需终端 artifact/ref 可枚举 | <code>PARTIAL</code> |
| Product | DeliveryReadinessManifest 含 gap owner、blocking/deferred 和恢复指针 | <code>PARTIAL</code> |
| Consumer | DELIVER 按 readiness 分类渲染，不推断缺失状态 | <code>PARTIAL</code> |
| Recovery | 只路由到真实 owner；新 artifact 到达后重新分类 | <code>TARGET</code> |

探针需证明同一组 gap 被稳定分类，且 RECONCILE 不调用上游求解器或修改事实。P2 的治理、SLO
和跨版本审计后置。Remaining gaps 见 <code>../05_MIGRATION.md</code>。
