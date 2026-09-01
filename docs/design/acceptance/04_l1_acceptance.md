# L1 成熟度验收卡

设计 owner：<code>../01_CONTRACTS_AND_INVARIANTS.md</code>。

## 当前目标：P0 / Loop Ready

| Gate | P0 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | DATA/Evidence/WM refs 版本闭合，observation 可冻结 | <code>PARTIAL</code> |
| Product | observation、fact、mention、relation、grounding request、gap 分型保存 | <code>PARTIAL</code>：typed contracts 与 sidecars 已存在 |
| Consumer | L2/L3 消费 L1 final product + binding snapshot + WM ref | <code>TARGET</code>：现有入口仍需统一 |
| Recovery | 未决 mention 经 L1-GROUND 后重新 finalization | <code>PARTIAL</code> |

## P0 必测探针

- <code>L1FactRow</code> 与 <code>L1LocationMention/L1RelationMention</code> 不混写；
- <code>L1ObservationSnapshot</code> 可在尚未接地时保存；
- observation → L1-GROUND → binding → L1 finalization 有完整 lineage；
- entity-only/inferred-scope 可保留为带不确定性的 final view；
- ambiguous/provider failure 作为 <code>L1Gap</code>，不制造事实；
- L2 不接收裸 facts 或未验证 mention。

## Deferred

- P1：所有 MVP 维度稳定消费同一 final product、增量 finalization 和质量回归；
- P2：大规模 observation、并发版本、权限、审计与长期演进。

Remaining gaps 见 <code>../05_MIGRATION.md</code>。
