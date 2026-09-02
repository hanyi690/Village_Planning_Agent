# 04 Evidence 可执行设计：采集、推理、缺口调度与认知提议

> Status: TARGET with PARTIAL implementation; EV-01B acquisition spine implemented
>
> 本文件是 Evidence requirement、采集状态、融合、充分性、gap 调度和 Evidence→Cognition
> 提议的设计权威。provider 审计报告只提供样本证据，不定义系统契约。

## 1. 职责和两个子系统

Evidence 回答三个问题：

1. 一个结论需要什么证据；
2. 当前检索实际获得了什么；
3. 这些证据是否足以支持当前用途。

逻辑上拆为两个子系统，物理部署可以共进程：

~~~text
Evidence Acquisition
  source/query/provider/cache/pagination/provenance
        ↓ ExternalObservation / SourceSpan / RetrievalReceipt
Evidence Reasoning
  normalize/dedupe/fusion/conflict/coverage/sufficiency/gap
        ↓ EvidencePacket / EvidenceGap / CognitionProposal
~~~

Acquisition 不作“世界中确实存在该实体”的结论；Reasoning 不直接执行 provider 调用。

## 2. 边界

Evidence 负责：

- 把业务需求编译为 <code>EvidenceRequirement</code>；
- 生成可重放 query plan；
- 路由本地 DATA、World Model、文本、RAG、cache 和已授权 provider；
- 记录每次尝试、分页、额度、超时、空结果和来源地址；
- 对 observation 去重、聚类、冲突归组并计算 coverage/sufficiency；
- 调度未闭合 gap；
- 在证据达到阈值时产生 assertion/entity/relation support proposal。

Evidence 不负责：

- 直接写 World Model；
- 把 provider observation 转成 canonical entity 或执行 geometry；
- 生成 L1 fact、L3 target、scenario 或 execution plan；
- 用单一 confidence 数值替代 authority、时效和来源独立性；
- 把调用失败、未尝试或额度耗尽解释为“现实中不存在”。

### 2.1 Provider validation harness 的非生产地位

`scripts/collect_amap_jintian_validation.py`、`scripts/collect_three_provider_validation.py` 和
`scripts/collect_tianditu_full.py` 是开发/验收 acceptance harness，不能作为正式业务采集入口，也不是
Evidence acquisition 的业务入口。
它们可以调用正式 DATA/provider runtime 或在迁移期间生成审计样本，但不能成为 L1、L1-GROUND 或
正式 session workflow 的隐藏依赖。

当前 AMap harness 仍包含直接 HTTP、私有 retry/cache、Jintian/L1 query 编译、scope classifier
以及 retained/rejected 投影。这些字段只用于审计和 fixture，不能替代：

```text
EvidenceRequirement
EvidenceQueryPlan
ProviderAttempt
Coverage/Sufficiency
Evidence Candidate/ConflictSet
```

Harness 的迁移出口是：脚本只读取冻结的 requirement/query/acquisition artifact，调用正式
provider acquisition runtime，保存 `ProviderAttempt`、`AcquisitionReceipt` 和 observation，最后
打印 acceptance summary。脚本不得自行判断 sufficient、absence、canonical identity 或写 WM。

### 2.2 五类对象不得合并

~~~text
Requirement ≠ Query ≠ Observation ≠ Candidate ≠ Conclusion
~~~

| 对象 | 回答的问题 | 允许的下一步 | 禁止的升级 |
|---|---|---|---|
| Requirement | 为某用途还需要证明什么 | 编译一个或多个 Query | 当作检索已经发生 |
| Query | 向哪个来源按什么范围检索 | 产生 attempt/receipt | 当作来源返回了结果 |
| Observation | 来源实际返回或文档实际记载什么 | 规范化、去重、形成 Candidate | 当作 canonical entity/fact |
| Candidate | 哪个受限解释可能被证据支持 | 排序、冲突检查、弃权 | 当作已接受 Conclusion |
| Conclusion | 对指定用途可接受的判断 | 进入 packet 或 Cognition proposal | 越过 authority/commit gate |

五类对象使用不同 ref、schema、状态与 digest。即使一次 provider 调用只返回一条记录，也不能
省略中间边界；空 Query、失败 attempt 和空 Observation set 更不能直接形成 absence Conclusion。

## 3. 当前实现与目标差异

| 能力 | 当前代码事实 | 设计终态 |
|---|---|---|
| requirement | typed requirement 已绑定 purpose、policy_ref、subject/valid-time 基础字段；authority/时效策略由 policy registry 提供 | 继续补齐 requirement-specific coverage/conflict 执行 |
| retrieval authority | 已冻结 session/run/branch/context/WM/cache refs | 保留，并把 query plan 与分页清单纳入 receipt |
| retrieval outcome | 已区分 sufficient/partial/insufficient/human/failed | 保留，补齐 provider attempt 的细粒度状态 |
| provider observation | 已有统一 attempt taxonomy、route/page/observation lineage；local DATA/WM/source-span 不生成伪 page | online provider-native acquisition、lease/retry 仍后续实现 |
| gap ledger | 已有 immutable ledger 与 scheduler row | 补齐 lease、next-attempt、dedupe 与 dependency row |
| sufficiency | 已有 coverage/sufficiency 实现 | 从通用文本覆盖提升为 requirement-specific policy |
| Cognition proposal | 本轮不触碰；Evidence 只停在 ObservationSnapshot/Receipt | 统一为 proposal artifact，永不由 Evidence 直接 commit |

EV-01B/EV-01C 已落地的采集脊柱为：`EvidenceQueryPlanV1` 由 runtime 的
`AcquisitionRouteExecutor` 逐 route 产出 terminal attempt；Application 只校验和汇总，
不得从 query trace 反推 attempt。Receipt 按 `required_for_acquisition` route 完成度判定，
  `SUCCESS_EMPTY` 只表示有界查询完成为空，不产生 absence conclusion。Frozen cache 使用
  独立的 `frozen_cache` attempt；cache read completeness 与 origin provider completeness
  分开记录，origin provider 的 page/status 只作为 provenance，不计入本次分页。

## 4. EvidenceRequirement

每个 requirement 至少包含：

~~~text
requirement_ref
requesting_artifact_ref / revision
producer_stage
subject_refs
statement
kind
required
purpose
scope / spatial_granularity
valid_time
allowed_inference
source_families
required_authority
geometry_authority
legal_authority
min_independent_sources
max_age
legal_effective_time
conflict_policy
success_condition
earliest_resolution_stage
retrieval_capability
budget_class
~~~

这些字段是设计终态。当前 <code>EvidenceRequirement</code> 已实现其中基础字段，缺失项在
补齐 contract 前可放入 metadata，但不得因此写成“已实现”。

### 4.1 Requirement policy 示例

| 用途 | required_authority | 独立来源 | geometry_authority | 允许推理 |
|---|---|---:|---|---|
| 地名候选召回 | advisory | 1 | none | inferred |
| 本地设施存在性 | local/source-backed | 1 | locator 可选 | exact/derived |
| 法定建设边界 | statutory | 1 个有效法定来源 | legal extent | exact |
| 道路执行中心线 | authoritative local GIS | 1 | execution geometry | exact/derived |
| 服务半径假设 | policy 或显式业务规则 | 1 | none | derived |

不同用途不能共享一个固定 confidence threshold。

### 4.2 EvidencePolicyRegistry

证据标准由版本化的 <code>EvidencePolicyRegistry</code> 统一拥有，业务模块不能临时创建自己的
authority 或 sufficiency threshold。每条 policy 至少包含：

~~~text
policy_id / policy_version
requirement_kind / purpose
required_authority / geometry_authority / legal_authority
min_independent_sources / max_age / legal_effective_time
allowed_inference / conflict_policy / absence_policy
success_condition
~~~

L1、L1-GROUND、L2、L3 和 Planning Ground 只能引用已登记的 <code>policy_id</code>，并补充 subject、
scope 和 valid time。LLM 不能选择 authority、source count、age 或 absence policy。Evidence 的
coverage/sufficiency 必须先解析 policy version，再输出结论或 Cognition proposal。

## 5. Confidence 与 Authority

Evidence 保留分量，不压成一个貌似精确的总分：

~~~text
EvidenceConfidence
  acquisition
  semantic
  binding
  temporal_fit

EvidenceAuthority
  source_authority
  geometry_authority
  legal_authority
~~~

confidence 表示不确定性，authority 表示该来源是否有资格用于某类结论；二者不可互相补偿。
例如 provider 高置信度返回一个河流 POI，只能证明“provider 返回了这个名称/点”，不能证明
该点是法定河道范围或本地执行 geometry。

## 6. Provider attempt 状态机

每个 provider × stage × query fingerprint 都必须有 attempt 记录：

~~~text
NOT_ATTEMPTED
  → RUNNING
  ├─ SUCCESS_NONEMPTY
  ├─ SUCCESS_EMPTY
  ├─ PARTIAL
  ├─ MISSING_CAPABILITY
  ├─ FAILED_RETRYABLE
  ├─ FAILED_PERMANENT
  ├─ QUOTA_EXHAUSTED
  ├─ TIMEOUT
  └─ AUTH_FAILED
~~~

语义规则：

- <code>SUCCESS_EMPTY</code> 只表示该明确查询在已完成分页范围内返回空；
- <code>PARTIAL</code> 表示分页、范围或字段不完整；
- <code>QUOTA_EXHAUSTED</code>、<code>FAILED_*</code> 不得映射为 missing；
- <code>TIMEOUT</code> 与 <code>AUTH_FAILED</code> 是独立终态，分别由运行恢复与配置/授权处理；
- <code>NOT_ATTEMPTED</code> 不参与 absence 结论；
- <code>MISSING_CAPABILITY</code> 表示 provider 不支持该查询，不是现实对象缺失；
- 只有 query plan 声明的完整性条件满足时，空结果才可参与 unavailable 判断。

当前 <code>ExternalObservationStatus</code> 仅用于冻结外部 observation 的原始记录；采集运行状态
统一使用 <code>ProviderAttemptStatus</code>，不得再写入未分型的 <code>failed</code> 状态。

## 7. Query plan

Query plan 由确定性 planner 生成：

~~~text
query_plan_ref
requirement_refs
normalized_query
subject/scope filters
provider routes
page strategy
page size / hard page limit
dedupe key
cache policy
retry policy
timeout
budget
completion condition
query_fingerprint
~~~

LLM 可以把需求分类到已登记的 query template，但不能生成任意 provider URL、扩大行政范围、
改变授权或突破预算。

### 7.1 检索顺序

默认顺序：

1. 当前 requirement 对应的 write-once retrieval artifact；
2. session 本地 DATA 和 source spans；
3. 当前 World Model 的只读 current view；
4. 已冻结 external cache；
5. 当前 session 已授权的外部 adapter；
6. HUMAN 或 not_available。

后一步不得覆盖前一步的 authority；多来源在 reasoning 层融合。

## 8. 分页与完整性

每页记录：

~~~text
query_fingerprint
provider
cursor_in / cursor_out
page_index
item_count
response_digest
attempt_status
latency
raw_response_ref
~~~

终止原因只允许：

~~~text
provider_exhausted
declared_limit_reached
budget_exhausted
quota_exhausted
failed
cancelled
~~~

只有 <code>provider_exhausted</code> 或 requirement 明确允许的
<code>declared_limit_reached</code> 才能声明分页完整。重复 cursor、缺页或排序不稳定进入
<code>partial</code>。

## 9. 归一化、去重、融合和冲突

### 9.1 四种对象不能混用

~~~text
ProviderResponse
  → ExternalObservation
  → ExternalCandidateEvidence
  → Entity/Relation/AssertionSupportProposal
  → Cognition validation
  → accepted World Model assertion
~~~

每一步都生成新 ref，不原地升级对象。

### 9.2 去重

去重键按来源类型选择：

- 同 provider：provider record id + operation + valid time；
- 文本：source ref + span digest；
- 本地 GIS：dataset/resource/source-feature identity；
- 跨 provider：只形成 candidate cluster，不直接合并身份。

### 9.3 冲突

冲突至少区分：

~~~text
value_conflict
identity_conflict
geometry_conflict
temporal_conflict
authority_conflict
scope_conflict
provider_status_conflict
~~~

Reasoning 输出 <code>ConflictSet</code>，并按 requirement 的
<code>conflict_policy</code> 得到 resolve/defer/human/reject；不得默认选第一项、最长几何或
land-use fallback。

### 9.4 DATA acquisition boundary

Evidence 的 <code>EvidenceQueryPlan</code> 只描述业务语义：要证明什么、查询哪些 subject/scope、
使用哪些 provider route、什么条件表示 requirement 已经充分。Evidence 不负责 endpoint、credential、
lease、fencing、网络重试的物理执行。

执行边界固定为：

~~~text
EvidenceRequirement
  → EvidenceQueryPlanV1
  → AcquisitionRouteExecutor
  → AcquisitionRouteResult
  → EvidenceAcquisitionReceipt / EvidenceObservationSnapshot
  → Evidence Reasoning
~~~

<code>ProviderAcquisitionPlan</code> 是 DATA 的执行输入，包含 boundary/query digest、CRS、请求几何、
provider transport 和 coverage contract；它不能回答 EvidenceRequirement 是否已经满足。
Evidence 不能把自己的 <code>EvidenceQueryPlan</code> 写进 DATA catalog，DATA 也不能替 Evidence
决定 provider route、分页完成条件或 sufficiency。

## 10. Coverage 与 Sufficiency

Coverage 回答“查到了哪些要求”，Sufficiency 回答“对当前用途是否够用”。

计算顺序：

1. requirement 是否有可定位 claim；
2. source family 和 authority 是否满足；
3. 独立来源数是否满足；
4. valid time/max age 是否满足；
5. geometry/legal authority 是否满足；
6. conflict 是否按策略闭合；
7. allowed inference 是否越界；
8. pagination 和 provider attempt 是否足以支持 absence 结论。

终态：

~~~text
sufficient
partial
insufficient
contradicted
not_available
human_required
failed
~~~

<code>partial</code> 允许业务阶段生成诊断产品，但不能满足 required hard input。

## 11. Gap scheduler

Gap 生命周期：

~~~text
OPEN
  → READY_FOR_RETRIEVAL
  → LEASED
  → RETRIEVING
  ├─ RESOLVED
  ├─ PARTIAL
  ├─ RETRY_WAIT
  ├─ NOT_AVAILABLE
  ├─ REQUIRES_HUMAN
  └─ FAILED
~~~

调度键：

~~~text
gap_ref
requirement_fingerprint
producer_artifact_ref
dependency_refs
source/world_model/cache digests
retrieval_capability
attempt
next_attempt_at
lease_owner / lease_expiry
~~~

相同 fingerprint 的并发请求只执行一次。新证据到达时 scheduler 找到依赖该 gap 的 row，
只触发这些 row 的重新评价。

## 11.1 Evidence ↔ World Model cognition round

Evidence 与 WM 之间采用显式 round/epoch 协议，禁止无界的相互唤醒：

~~~text
CognitionRound N
  → pin World Model vN
  → evaluate affected EvidenceRequirements
  → freeze EvidencePacket N
  → produce CognitionProposalBatch N
  → Cognition commit → World Model vN+1
  → calculate affected dependency set
  → wake only affected requirements
  → no-change / no-new-evidence stop
~~~

每一轮必须绑定 <code>round</code>、<code>wm_epoch</code>、parent snapshot digest、requirement set digest
和 proposal fingerprint。停止条件包括：

- affected requirement 没有新的 output digest；
- 没有新的 evidence observation；
- proposal fingerprint 与上一轮相同；
- 达到 <code>max_rounds</code>；
- 需要 HumanDecision。

WM vN 只读固定 parent；EvidencePacket N 在本轮冻结后不可因 vN+1 原地修改。新一轮只由
Dependency Runtime 唤醒真正受影响的 requirements。

## 12. Evidence→Cognition proposal

Evidence 只有在 observation 具备稳定来源、作用域、时间和必要 authority 时，才可输出：

~~~text
EntitySupportProposal
RelationSupportProposal
PropertyAssertionProposal
RepresentationSupportProposal
~~~

proposal 必须包含支持与反对证据、候选集合、confidence components、authority、valid time、
source refs、requirement refs 和 source WM digest。Cognition 决定 accepted/ambiguous/
rejected，并通过 <code>WorldModelCommitPort</code> 提交；Evidence 永远不是 writer。

外源点默认只能成为 locator support。要成为 execution representation，必须经过本地 DATA
admission、CRS/geometry validation 和明确 geometry authority。

## 13. 缓存、幂等与恢复

retrieval fingerprint 至少包含：

~~~text
normalized request
requirement set
session/run/branch/context
DATA snapshot digest
World Model snapshot digest
external cache digest
query plan version
provider policy version
~~~

写入采用 CAS/write-once。相同 fingerprint 复用 receipt；请求语义变化必须生成新 artifact。
恢复不能用其他 session 的 provider cache snapshot 冒充当前结果。

## 14. LLM 边界

允许 LLM：

- 从闭集模板选择 query intent；
- 对候选 observation 做语义分类；
- 提议冲突类型、支持关系和 abstain；
- 对短 source spans 生成 candidate claim。

禁止 LLM：

- 决定 authority、分页完整性或 provider 是否调用成功；
- 生成 provider record id、source ref、entity ref 或 geometry；
- 把 observation 直接写入 World Model；
- 用自然语言理由覆盖 deterministic conflict/sufficiency gate。

## 15. 失败与恢复

| 失败 | 权威状态 | 恢复 owner |
|---|---|---|
| provider timeout | failed_retryable | Evidence scheduler |
| quota exhausted | quota_exhausted | operator/budget policy |
| provider 不支持 | missing_capability | query planner |
| 完整查询返回空 | success_empty | Evidence reasoning |
| source 冲突 | conflict | Evidence reasoning/HUMAN |
| authority 不足 | insufficient | producer stage/HUMAN |
| proposal commit 冲突 | stale_parent | Cognition rebase |
| geometry 不具执行权威 | partial/insufficient | DATA/GROUND |

## 16. 文件责任

当前实现：

~~~text
contracts/evidence/requirement_contracts.py
contracts/evidence/retrieval_contracts.py
contracts/evidence/retrieval_artifact_contracts.py
contracts/evidence/stage_contracts.py
contracts/evidence/external_observation_contracts.py
modules/evidence/application.py
modules/evidence/requirements.py
modules/evidence/coverage.py
modules/evidence/sufficiency.py
infrastructure/evidence_runtime/artifact_store.py
infrastructure/evidence_runtime/gap_scheduler.py
~~~

目标收敛：

~~~text
modules/evidence/query_planning.py
modules/evidence/conflict_resolution.py
modules/evidence/proposals.py
infrastructure/evidence_runtime/provider_attempts.py
infrastructure/evidence_runtime/fusion.py
~~~

不得把目标文件名当成当前完成证明。

## 17. 可观测性与验收

指标至少包含：

~~~text
requirements_by_status
provider_attempts_by_terminal_state
pagination_completion_rate
dedup_hit_rate
conflicts_by_kind
gap_age / retry_count
coverage_by_requirement_kind
sufficiency_false_positive_rate
proposal_accept/reject/ambiguous_rate
~~~

完成验收至少要求：

1. provider failure、quota、not-attempted、empty 和 missing 的测试互不混淆；
2. 分页缺失不能产生 absence 结论；
3. requirement-specific authority/sufficiency 有 fixture；
4. 相同 query fingerprint 幂等重放；
5. EvidencePacket 可重载且 provenance 闭合；
6. 外源 observation 无法直接进入 executable geometry；
7. proposal 必经 Cognition commit；
8. 新 evidence 只唤醒依赖 gap；
9. 语义 benchmark 覆盖 sufficiency 误判和冲突处理；
10. 所有业务阶段只通过统一 Evidence facade。
