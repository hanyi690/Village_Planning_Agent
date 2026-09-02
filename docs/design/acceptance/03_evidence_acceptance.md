# Evidence 成熟度验收卡

设计 owner：<code>../04_EVIDENCE.md</code>。

本轮完成 EV-03 的 Evidence reasoning/proposal vertical slice：在 EV-01B acquisition spine
之上，按 `Observation → CandidateEvidence → ConflictSet → Coverage → Sufficiency`
执行 requirement-specific policy gates，再按 `EvidencePacket →
EvidenceProposalBatch → Cognition AssertionProposal` 生成可重放提案。Cognition
仍独占 decision/commit；Evidence 不直接写 WM。Gap scheduler 与 online provider
仍属于后续阶段。

## 当前目标：P0 / Loop Ready

验收必须证明以下对象没有混写：

~~~text
Requirement ≠ Query ≠ Observation ≠ Candidate ≠ Conclusion
~~~

| Gate | P0 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | typed requirement 带 consumer、purpose、authority 与 scope | <code>PARTIAL</code>：purpose/policy/subject/scope 已落地，consumer-specific authority 仍由 policy 解析 |
| Product | retrieval receipts、observation snapshot、packet、gap ledger 可重载 | <code>PASS (EV-01B acquisition)</code>：typed snapshot/receipt 已进入 retrieval artifact/CAS |
| Consumer | L1/L2/L3/GROUND 通过 facade 消费 ref，不读取 provider 私有返回 | <code>PARTIAL</code> |
| Recovery | provider 状态与 gap 可区分并按新输入调度 | <code>PARTIAL</code> |
| Sufficiency | 十个 policy gate 逐 requirement 运行并可重放 | <code>PASS (EV-02 policy evaluator)</code> |
| Absence | 仅在完整权威采集、分页耗尽、独立来源满足且无冲突时结论化 | <code>PASS (EV-02 late gate)</code> |
| Proposal | sufficient requirement 生成四类 proposal，保留完整 lineage 并可经 Cognition adapter 转换 | <code>PASS (EV-03 proposal artifact)</code> |

## P0 必测探针

- provider 状态覆盖 <code>NOT_ATTEMPTED</code>、<code>SUCCESS_NONEMPTY</code>、
  <code>SUCCESS_EMPTY</code>、<code>FAILED_RETRYABLE</code>、<code>FAILED_PERMANENT</code>、
  <code>QUOTA_EXHAUSTED</code>、<code>TIMEOUT</code>、<code>AUTH_FAILED</code>、<code>PARTIAL</code>；
- 空结果、未尝试和失败不会被合并；
- confidence 分离 acquisition、semantic、binding；
- authority 分离 source、geometry、legal；
- Observation 不能直接升级为 Conclusion 或 executable geometry；
- 从 <code>data/cache/map_observations/amap/</code>、<code>tianditu/</code>、<code>tencent/</code> 的
  本地缓存（旧 <code>output/map_validation/</code> 已物理删除）重建外源 observation snapshot；
  每个 provider/stage 的 manifest、normalized
  rows、attempt status、采集时间、范围与 raw/cache ref 可重载。腾讯当前未完成的阶段必须
  保留 <code>NOT_ATTEMPTED</code> 或失败 gap；
- 新 receipt 只唤醒受影响 requirement/consumer；无新依赖时停止。

EV-01B/EV-01C/EV-02 额外验收条件：required route 必须有 runtime terminal attempt；DATA 与
CurrentWorld observation 必须分型并保留 route/attempt/query-plan lineage；bounded local
query 不得伪造 PageRecord；`SUCCESS_EMPTY` 不得升级为 absence；同一业务 digest 和 plan
fingerprint 必须 replay 同一 artifact，WM/DATA/policy business digest 改变才生成新 artifact。
Frozen external cache 必须使用独立的 `frozen_cache` attempt，保留 origin provider
attempt/status/query/page provenance，且 cache read complete 不得覆盖 origin incomplete。
Sufficiency 必须持久化每个 requirement 的 candidate refs、conflict refs、policy identity
和十项 gate 结果；`SUCCESS_EMPTY`、`NOT_ATTEMPTED`、`MISSING_CAPABILITY`、`PARTIAL`、
`QUOTA_EXHAUSTED` 必须保持不同的 acquisition 语义。absence gate 必须最后执行，不能在
receipt、provider origin 或 pagination 未闭合时输出 absence conclusion。

## Deferred

- P1：MVP provider/source 组合的稳定覆盖、sufficiency 校准和下游回归；
- P2：配额治理、并发、缓存一致性、隐私/许可、安全和 provider SLO。

Remaining gaps 见 <code>../05_MIGRATION.md</code>。
