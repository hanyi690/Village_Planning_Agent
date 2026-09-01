# Evidence 成熟度验收卡

设计 owner：<code>../04_EVIDENCE.md</code>。

本轮 DATA-only MVP 不执行本卡的 Evidence enrichment/consumer 验收。高德、天地图、腾讯
缓存只按 <code>01_data_acceptance.md</code> 的 cache inventory 规则盘点并保留原始状态；本卡
的 provider、requirement、observation 和下游消费条件仍属于后续阶段。

## 当前目标：P0 / Loop Ready

验收必须证明以下对象没有混写：

~~~text
Requirement ≠ Query ≠ Observation ≠ Candidate ≠ Conclusion
~~~

| Gate | P0 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | typed requirement 带 consumer、purpose、authority 与 scope | <code>PARTIAL</code>：requirements/contracts 已存在 |
| Product | retrieval receipts、observation snapshot、packet、gap ledger 可重载 | <code>PARTIAL</code> |
| Consumer | L1/L2/L3/GROUND 通过 facade 消费 ref，不读取 provider 私有返回 | <code>PARTIAL</code> |
| Recovery | provider 状态与 gap 可区分并按新输入调度 | <code>PARTIAL</code> |

## P0 必测探针

- provider 状态覆盖 <code>NOT_ATTEMPTED</code>、<code>SUCCESS_NONEMPTY</code>、
  <code>SUCCESS_EMPTY</code>、<code>FAILED_RETRYABLE</code>、<code>FAILED_PERMANENT</code>、
  <code>QUOTA_EXHAUSTED</code>、<code>TIMEOUT</code>、<code>AUTH_FAILED</code>、<code>PARTIAL</code>；
- 空结果、未尝试和失败不会被合并；
- confidence 分离 acquisition、semantic、binding；
- authority 分离 source、geometry、legal；
- Observation 不能直接升级为 Conclusion 或 executable geometry；
- 从 <code>output/map_validation/amap/</code>、<code>tianditu/</code>、<code>tencent/</code> 的
  本地缓存重建外源 observation snapshot；每个 provider/stage 的 manifest、normalized
  rows、attempt status、采集时间、范围与 raw/cache ref 可重载。腾讯当前未完成的阶段必须
  保留 <code>NOT_ATTEMPTED</code> 或失败 gap；
- 新 receipt 只唤醒受影响 requirement/consumer；无新依赖时停止。

## Deferred

- P1：MVP provider/source 组合的稳定覆盖、sufficiency 校准和下游回归；
- P2：配额治理、并发、缓存一致性、隐私/许可、安全和 provider SLO。

Remaining gaps 见 <code>../05_MIGRATION.md</code>。
