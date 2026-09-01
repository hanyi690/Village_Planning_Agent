# DELIVER 成熟度验收卡

设计 owner：<code>../06_SELECT_EXECUTE_AND_CODE.md</code>。当前目标：P1 / MVP Ready。

## Gates

| Gate | 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | readiness、validation、planned state 和 lineage 一致 | <code>PARTIAL</code> |
| Product | DeliveryManifest、snapshot 与文件清单可重载 | <code>PARTIAL</code> |
| Consumer | 用户可区分 complete、partial、diagnostic_only、failed | <code>PARTIAL</code> |
| Recovery | 重渲染幂等，缺失 artifact 不被伪造成空交付 | <code>PARTIAL</code> |

探针覆盖完整交付、部分交付、纯诊断和失败，校验文件 digest、geometry lineage 与可读状态一致。
P2 的发布权限、隐私、制品保留、容量和灾难恢复后置。Remaining gaps 见
<code>../05_MIGRATION.md</code>。
