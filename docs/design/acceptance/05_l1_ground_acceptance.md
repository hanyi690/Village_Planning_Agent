# L1-GROUND 成熟度验收卡

设计 owner：<code>../L1_GROUND_EXECUTABLE_DESIGN.md</code>。

## 当前目标：P0 / Loop Ready

| Gate | P0 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | observation/mention、Evidence、WM 和 DATA refs 同版本 | <code>PARTIAL</code> |
| Product | 每个 work item 唯一终态，binding/proposal/gap/trace 可重载 | <code>PARTIAL</code>：现有状态较粗 |
| Consumer | L1 finalization 只接收 commit 后重验证 binding | <code>TARGET</code> |
| Recovery | 新 Evidence/DATA/WM/HUMAN 只重跑受影响 subject | <code>TARGET</code> |

## P0 必测探针

- 设施、道路、水体、自然村、相对位置与非空间项都有唯一终态；
- <code>grounded_entity_without_geometry</code>、<code>inferred_scope</code>、source gap 合法存在；
- candidate_count=0 可区分来源、语义、provider 和过滤原因；
- LLM 仅闭集选择/ambiguous/abstain；
- proposal 只能经 Cognition commit，stale parent 无部分写；
- commit 后 binding 重新验证，merge/split 可精确失效；
- 所有 L1-GROUND 产物都不能直接进入 SELECT。

## Deferred

- P1：金田村标注集上的 identity precision、candidate recall 和恢复稳定性门槛；
- P2：大规模实体、并发 commit、人工治理、性能和多 provider 运营。

Remaining gaps 见 <code>../05_MIGRATION.md</code>。
