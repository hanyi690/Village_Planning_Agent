# Target Projection 成熟度验收卡

设计 owner：<code>../05_PROJECTION_AND_GROUND.md</code>。当前目标：P1 / MVP Ready。

## Gates

| Gate | 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | PlanningProgram 与 L1/WM lineage 可验证 | <code>PARTIAL</code> |
| Product | request/pending/rejected/gate 作为单一 artifact 重载 | <code>PARTIAL</code> |
| Consumer | 所有空间 target 进入 Planning Ground，无 bypass | <code>TARGET</code> |
| Recovery | pending 指向 Evidence、L1-GROUND、HUMAN 或重新编译 | <code>PARTIAL</code> |

## Probe 与 deferred

一个混合 PlanningProgram 应产生 request、pending 与 rejected 的互斥终态；pending 可以进入恢复
队列但不得进入 SELECT。P2 的高吞吐、并发投影和配置治理后置。Remaining gaps 见
<code>../05_MIGRATION.md</code>。
