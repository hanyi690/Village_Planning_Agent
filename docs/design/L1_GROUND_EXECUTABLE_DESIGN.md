# L1-GROUND 可执行模块设计

> Status: TARGET with PARTIAL implementation
>
> L1-GROUND 只解决 observation 中 mention 到 World Model entity/scope 的认知绑定。它允许
> entity-only、inferred-scope 和 source gap 终态，不要求本地可执行 geometry。

## 1. Responsibility

L1-GROUND 消费 <code>L1ObservationSnapshot</code> 中的地点、实体和关系 mention，形成可审计的
identity/scope/relation binding、未决 gap 及 World Model proposals。它不选择规划用途表示，
不形成 solver candidate，也不直接写 current World Model。

## 2. Inputs

~~~text
L1ObservationSnapshot ref
L1GroundingRequest[]
EvidenceObservationSnapshot ref
current WorldModelSnapshot ref/digest
DATA ResourceCatalogSnapshot ref
EvidencePacket/RetrievalReceipt refs
budget and recovery cursor
~~~

输入只读且必须同一 session/branch。L1-GROUND 可使用 DATA 的 identity/representation rows 做
来源证据，但不能把 resource row 自动等同于 canonical entity。

## 3. Outputs

~~~text
L1BindingSnapshot
  entity_bindings[]
  scope_bindings[]
  relation_bindings[]
  terminal_results[]
  gaps[]
  trace_refs[]

BindingProposal[]
AssertionProposal[]
WorldModelCommitRequest optional
~~~

提交成功并重验证后的 binding 与 observation 一起形成 L1 final product；proposal 本身不是
current-world fact。

## 4. Public Facade

共享 Ground runtime 对本模块暴露 <code>MentionGroundingPort.ground(request)</code>。L1 只通过
该 port 提交工作项和读取 binding snapshot；candidate retriever、ranker、空间验证器、Evidence
runtime 与 commit adapter 都是内部依赖。

## 5. State Machine

每个 mention/subject 独立运行：

~~~text
NEW
  → CLASSIFIED
  ├─ NOT_SPATIAL_WORK_ITEM
  └─ SPATIAL
      → QUERY_COMPILED
      → CANDIDATES_RETRIEVED
      ├─ SOURCE_GAP
      ├─ PROVIDER_FAILURE
      └─ CANDIDATE_SET_READY
          → CLOSED_SET_RESOLUTION
          ├─ AMBIGUOUS
          ├─ ABSTAINED
          └─ SELECTED
              → IDENTITY_SCOPE_VERIFY
              → RELATION_VERIFY
              → BINDING_PROPOSAL
              → COGNITION_VALIDATION
              ├─ COMMITTED
              ├─ REJECTED
              └─ STALE_PARENT
                  → REVALIDATED
                  → TERMINAL
~~~

合法主终态：

| 终态 | 语义 | 可进入 L1 final | 可直接进入 SELECT |
|---|---|---:|---:|
| <code>grounded_exact</code> | entity 唯一，存在经验证 exact source binding | 是 | 否 |
| <code>grounded_feature_set</code> | entity 对应审计过的 feature 集 | 是 | 否 |
| <code>grounded_entity_without_geometry</code> | entity 唯一，当前无适用本地 geometry | 是 | 否 |
| <code>inferred_scope</code> | 只确定 scope，未冒充 exact entity | 是，带不确定性 | 否 |
| <code>ambiguous_entity</code> | 多实体无法唯一决定 | 作为 gap | 否 |
| <code>ambiguous_representation</code> | entity 明确但来源表示仍冲突 | 作为 gap | 否 |
| <code>source_geometry_missing</code> | 来源存在但无几何 | 作为 gap | 否 |
| <code>source_semantics_missing</code> | 来源角色或字段语义不足 | 作为 gap | 否 |
| <code>evidence_insufficient</code> | requirement 未满足 | 作为 gap | 否 |
| <code>provider_failed</code> | 检索未完成，不能推断不存在 | 作为 gap | 否 |
| <code>not_spatial_work_item</code> | 工作项不需要空间绑定 | 是 | 否 |
| <code>human_required</code> | 需要人工决定 | 作为 gap | 否 |
| <code>rejected</code> | 违反来源、身份或关系不变量 | 作为诊断 | 否 |

每个工作项必须恰有一个主终态；可附带多个 gap/reason code。

## 6. Transactions

候选检索和解析不写 World Model。事务分为：

~~~text
binding evaluation
  → immutable proposal batch
  → Cognition validation
  → WorldModelCommitPort CAS
  → new WorldModelSnapshot
  → binding revalidation
  → publish L1BindingSnapshot
~~~

proposal batch 原子提交；任一硬不变量失败时整批不写。stale parent 必须重读受影响 subgraph
并重新评估，不能只替换 parent ref 重试。

## 7. Invariants

1. Fact 与 Mention 分离；mention 文本不是已绑定事实。
2. L1-GROUND 不要求每个合法认知对象都有 geometry。
3. provider observation 只能作为 evidence，不能成为本地 resource/representation。
4. 候选集合由确定性检索产生；LLM 不能创建 candidate/entity ref。
5. <code>candidate_count=0</code> 必须有来源、语义、provider 或过滤原因。
6. GROUND 只提 proposal；只有 Cognition/WorldModelCommitPort 可改变 current World Model。
7. commit 后必须按新 snapshot 重验证 binding。
8. 未决 binding 不得被 L2 当作确定空间事实。

## 8. Failure Taxonomy

零候选至少区分：

~~~text
role_filter_excluded_all
name_or_alias_missing
scope_filter_excluded_all
source_geometry_missing
source_semantics_missing
provider_not_attempted
provider_failed
pagination_incomplete
world_model_snapshot_stale
~~~

此外区分 ambiguous、abstained、deterministic rejection、commit conflict、stale parent、budget
exhausted 与 runtime failure。provider failure 绝不解释为实体不存在。

## 9. Gap & Recovery

gap 记录 subject/mention、terminal state、candidate/query digest、缺失 requirement、owner、可用
recovery action 和停止依据。恢复可由新 Evidence receipt、新 DATA resource、新 WM snapshot、
HumanDecision 或 provider 恢复触发。所有依赖 digest 未变时立即停止。

## 10. Persistence/CAS

observation、candidate set、decision trace、proposal、commit result、binding snapshot 和 gap 均为
不可变 artifact。binding current pointer 只在其 source observation 与 committed WM parent 都
匹配时发布；重放同 proposal fingerprint 幂等。

## 11. Version & Digest

~~~text
observation_snapshot_digest
resource_catalog_digest
world_model_snapshot_digest
evidence_packet_digest
query_fingerprint
candidate_set_digest
resolver/model/provider/version
policy/config digest
~~~

HumanDecision 也必须绑定上述上下文；输入变化后自动 stale，除非决定 scope 明确允许复用。

## 12. Dependency/Invalidation

依赖索引连接 mention、candidate、entity、assertion、representation、relation anchor 与 evidence。
entity merge/split/supersede、source digest、scope、anchor 或 assertion status 改变时只失效相关
binding。重验证结果为 <code>valid</code>、<code>stale_identity</code>、
<code>stale_representation</code>、<code>stale_relation</code>、<code>stale_geometry</code> 或
<code>superseded</code>。

## 13. Deterministic vs LLM Boundary

确定性逻辑负责 current-view 过滤、session/source/valid-time、authority、scope 硬冲突、候选
闭集、geometry/CRS 可验证性、关系测量和 proposal schema。LLM 只在闭集内返回
<code>selected</code>、<code>ambiguous</code> 或 <code>abstain</code>，随后再经确定性验证。

LLM 不得生成 entity、candidate、坐标、WKT、BSM、查询范围或 provider 请求。

## 14. Observability/Trace

至少记录 subject 状态迁移、query/candidate refs、rank features、LLM 决定、确定性拒绝、commit
结果和重验证结果；统计 terminal state、零候选原因、闭集弃权率、commit conflict、恢复轮次、
candidate recall 与 identity precision。

## 15. Acceptance Probe

使用金田村标注 fixture 覆盖设施、道路、水体、自然村、相对位置和非空间工作项：

1. 每个 mention 有唯一终态；
2. entity-only 和 inferred-scope 可合法形成 L1 final，而不伪造 geometry；
3. 多候选时 LLM 只能闭集选择或弃权；
4. GROUND 不直接写 WM，commit conflict 无部分写入；
5. merge/split 后仅关联 binding stale 并可重验证；
6. provider failure 与空结果可区分；
7. L2 读取的是 final observation + binding view，而非裸 facts。

## 16. Remaining Gaps

当前代码已有 fact/mention/gap、observation 与 binding sidecar、grounding resolver 和 World Model
commit adapter 的部分能力；细粒度终态、完整 proposal 事务、精确失效和 L1 final gate 仍需
按 <code>05_MIGRATION.md</code> 收敛。
