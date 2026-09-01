# World Model / Cognition 成熟度验收卡

设计 owner：<code>../07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md</code>。

## 当前目标：P0 / Loop Ready

| Gate | P0 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | proposal 引用 source snapshot、parent WM 和 authority | <code>PARTIAL</code>：commit envelope/contracts 已存在 |
| Product | assertion/proposal/decision/commit/version 生命周期可重载 | <code>PARTIAL</code>：snapshot/CAS 主干存在，完整生命周期待验 |
| Consumer | current-only typed view 被 L1-GROUND、L2/L3、Planning Ground 消费 | <code>PARTIAL</code> |
| Recovery | stale parent、merge/split/supersede 可精确重验证 | <code>TARGET</code> |

## P0 必测探针

- DATA、Evidence、L1、GROUND 只能提交 proposal，不能直接改变 current view；
- 只有 Cognition validator 经 <code>WorldModelCommitPort</code> 原子发布新 snapshot；
- stale parent 不部分写入；同 proposal fingerprint 重放幂等；
- rejected/proposed assertion 不出现在 current-only view；
- 新 snapshot 能被重载且 lineage/digest 完整；
- identity、representation、relation 的旧引用可被判为 stale。

## Deferred

- P1：merge/split/supersede 与 dependency digest 驱动主链稳定增量重算；
- P2：高并发 commit、权限/治理、审计保留、容量与跨版本迁移。

对象模型存在不等于 World Model 生命周期完成。Remaining gaps 见
<code>../05_MIGRATION.md</code>。
