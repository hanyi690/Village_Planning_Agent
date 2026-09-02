# 07 Cognition / World Model 可执行设计

> Status: TARGET with PARTIAL implementation
>
> 本文件是 Source≠Entity≠Representation、assertion 生命周期、World Model 事务、视图权限、
> 版本/rebase 和索引生命周期的设计权威。它不再承载 provider 采集说明、GROUND 算法或迁移
> 日志；这些内容分别归 <code>04_EVIDENCE.md</code>、两类 Ground 的独立设计
> 和 <code>05_MIGRATION.md</code>。

## 1. 核心模型

本系统只有一个会话级认知世界：

- World Model 是 session 某一版本的认知产品；
- KG/RDF/SQL/PostGIS 是该产品的存储或索引实现；
- DATA 保存来源记录和真实几何载荷；
- World Model 保存实体、断言、关系、表示身份和 provenance；
- geometry 运算仍通过 <code>representation_ref → resource_ref → DATA snapshot</code>。

以下对象永不等价：

~~~text
SourceRecord
WorldEntity
EntityPart
SpatialRepresentation
Observation
Assertion
PlanningIntent
PlannedEntity
~~~

同一 source record 可以支持多个实体/部件；同一实体可以由多个 source record 支持并拥有多个
空间表示。名称、feature id、BSM、provider id 和 geometry 都不是通用实体身份。

## 2. 当前实现与目标差异

| 能力 | 当前代码事实 | 设计终态 |
|---|---|---|
| DATA-backed bootstrap | 已有 <code>WorldModelKGStore</code> 与 source catalog adapter | 保留，补齐大规模流式与索引事务 |
| immutable snapshot/CAS | 已有 descriptor、named ref compare-and-set、父 digest | 保留，并标准化 stale-parent/rebase receipt |
| assertion | 已有 candidate/accepted/ambiguous/rejected/superseded contract | 补齐所有状态转移、decision、valid time 与 projection rebuild |
| identity commit | 已有 frozen envelope 和 typed commit result | 扩展为通用 proposal commit transaction |
| merge/split | 当前主要依赖构建/投影逻辑 | 改为 supersede 旧 assertion + 新 assertion + projection rebuild |
| query port | 已有 bounded entity/representation/relation/binding query | 拆成 typed Current/Intent/Planned views |
| indexes | 已有 KG 和部分 projection/cache | 明确 snapshot-scoped lifecycle 与 dependency digest |
|多进程 writer | 当前有 CAS，主要按 session/branch 使用 | 明确数据库 CAS/lease/advisory lock 的部署实现 |

## 3. 图分区与写入权限

一个 session snapshot 至少有五个逻辑 graph：

| Graph | 内容 | 允许写入者 | 允许读取者 |
|---|---|---|---|
| source | source record、raw attribute/geometry refs | DATA bootstrap adapter | Cognition、Evidence |
| assertion | proposal、decision、状态和 supersedes | Cognition transaction | Cognition、审计 |
| world | accepted assertion 的确定性投影 | Cognition projector | L1/L2/L3/Evidence/GROUND/SELECT |
| intent | admitted planning intent | Cognition intent commit adapter | GROUND/SELECT/EXECUTE |
| planned | planned entity/representation/change | Cognition planned commit adapter | VALIDATE/RECONCILE/DELIVER |

模块不得获取“全图读写端口”。规范端口：

~~~text
CurrentWorldQueryPort
IntentWorldQueryPort
PlannedWorldQueryPort
WorldModelCommitPort
~~~

L1/L2/L3/Evidence/L1-GROUND 只注入 <code>CurrentWorldQueryPort</code>；它们在类型上无法读取
planned graph。Planning GROUND 同时读取 current 和 intent，但不能读取 planned。VALIDATE
可同时读取三种 view，但保持命名空间。

当前 <code>WorldModelPort</code> 是迁移期统一只读端口；adapter 必须先按 view 过滤，之后再
拆分协议。不得仅靠调用方约定“不要查 planned”。

## 4. Source、Entity、Part 与 Representation

### 4.1 SourceRecord

最小字段：

~~~text
source_record_ref
dataset_ref / collection_ref
source_feature_ref
source_snapshot_ref
raw_attribute_ref
source_geometry_refs
valid_time
input_role / admission_status
source_digest
~~~

SourceRecord 不因认知决策变化而被覆盖。

### 4.2 WorldEntity

WorldEntity 表达现实对象的稳定认知身份：

~~~text
entity_ref
concept_refs
canonical_label / aliases
valid_time
identity_status
semantic_status
capabilities
accepted_assertion_refs
supporting_source_refs
~~~

无名称要素仍可有 source-local entity；语义未确认时标为 provisional/unresolved，不生成伪名称
或伪 BSM。

### 4.3 EntityPart

Part 表达真实对象的语义部件，例如道路 segment、建筑组成、设施子单元。它不是为了匹配源
文件而随意拆分。part proposal 必须说明 part-of relation、形成依据和生命周期。

### 4.4 SpatialRepresentation

表示至少包含：

~~~text
representation_ref
entity_ref / part_ref
role / purpose
geometry_kind
resource_ref
source_snapshot_ref
source_feature_refs
CRS
valid_time
authority
accuracy / scale / resolution
derivation_activity_ref
geometry_digest
validation_status
~~~

典型 role：

~~~text
locator_point
physical_extent
administrative_extent
service_extent
network_centerline
legal_extent
execution_geometry
display_geometry
~~~

系统不设置跨用途的“默认 geometry”。调用方必须声明 purpose；只有明确登记的派生规则才能
从一个 representation 生成另一个。

### 4.4 Bootstrap identity levels

DATA admission 的 <code>SourceRecord</code> 不等于 canonical identity acceptance。bootstrap 只做
确定性的 source-local projection：

~~~text
SourceRecord
  → SourceLocalIdentity
      identity_status = source_local | provisional | canonical | superseded
  → EntitySupportProposal
  → identity validation
  → canonical WorldEntity (only when accepted)
~~~

没有名称或没有足够 identity evidence 的 source record 仍可进入 WM 索引，但只能是
<code>source_local</code> 或 <code>provisional</code>。所谓 bootstrap acceptance 只表示该 source-local
identity 可以被认知查询索引，不表示它已经被确认是某个现实世界 canonical entity。只有经过
Cognition identity assertion 和 decision 的对象，才能成为 <code>canonical</code> WorldEntity。

## 5. Assertion 生命周期

### 5.1 状态

~~~text
PROPOSED
  → ACCEPTED
  → AMBIGUOUS
  → REJECTED

ACCEPTED
  → SUPERSEDED
AMBIGUOUS
  → ACCEPTED | REJECTED | SUPERSEDED
~~~

<code>SUPERSEDED</code> 是终态但仍保留审计；任何转移都通过新 decision artifact，不原地删除
来源或旧 assertion。

### 5.2 Assertion 最小契约

~~~text
assertion_ref
assertion_kind
subject_ref
predicate
object_ref or typed value
valid_time
source_refs
evidence_refs
proposal_ref
decision_ref
status
confidence_components
authority
parent_world_model_snapshot_ref/digest
supersedes
created_at
~~~

### 5.3 状态转移校验

确定性 validator 检查：

- subject/object/ref 属于当前 session 或允许的 registry；
- source/evidence refs 可重载；
- assertion kind 与 value 类型一致；
- source role/current-world admission 合法；
- valid time 不冲突；
- proposal authority 满足对应 policy；
- identity/representation 约束不被破坏；
- parent snapshot 未过期；
- decision 未跨越人工审批边界。

LLM 只可提出 proposal 或对闭集候选排序，不能产生 accepted decision。

## 6. Entity identity lifecycle

### 6.1 新实体

~~~text
SourceRecord
  → EntitySupportProposal
  → candidate cluster
  → deterministic identity checks
  → accepted identity assertion
  → WorldEntity projection
~~~

### 6.2 Merge

Merge 不是 <code>entity.merge(A,B)</code> 的破坏性操作：

~~~text
merge proposal
  → supporting/contradicting evidence
  → accepted canonical identity assertion
  → old identity assertions superseded
  → aliases/source links reprojected
  → affected bindings marked stale
  → new snapshot
~~~

旧 entity ref 作为 tombstone/redirect 保留，不能在同一 snapshot 同时作为两个可执行实体。

### 6.3 Split

~~~text
split proposal
  → partition source/part/assertion support
  → new entity refs
  → old identity assertion superseded
  → relation/representation ownership revalidated
  → unresolved ownership kept explicit
  → new snapshot
~~~

无法唯一分配的 representation 不得复制给所有新实体。

### 6.4 Stable identity

source 属性变化不应无条件改变 entity ref。identity key 的变化与 semantic property 的变化分开；
重建时应验证：

- 同 source identity 在同 lineage 下稳定；
- merge/split 有显式 redirect；
- source record 删除产生 supersede/tombstone，不静默复用 ref；
- entity ref 不依赖显示名称或当前排序位置。

## 7. 事务规范

### 7.1 Bootstrap transaction

输入：

~~~text
SessionDataSnapshot
SourceCatalogSnapshot
SourceSemanticMappingSnapshot
previous WorldModelSnapshot optional
~~~

步骤：

1. 校验 current-world admission 和 DATA digest；
2. 建立 source graph；
3. 生成 source-local identity/part/representation proposals；
4. 校验 schema mapping 和 source-local identity invariants；
5. 构建可进入认知索引的 provisional bootstrap projection，不自动产生 canonical identity；
6. 写临时 CAS artifact；
7. 重载并重算 graph digest；
8. compare-and-set 发布 named ref。

任一步失败都不发布新版本。

### 7.2 Proposal commit transaction

输入：

~~~text
proposal batch
decision artifacts
parent snapshot ref/digest
source/evidence artifact refs
expected named-ref descriptor
~~~

步骤：

1. load and verify parent；
2. validate refs and decisions；
3. append assertions/decisions；
4. rebuild affected world projection；
5. calculate affected dependency digests；
6. validate global invariants；
7. persist immutable child；
8. CAS publish；
9. emit commit receipt and invalidation set。

返回：

~~~text
committed
noop
stale_parent
ambiguous
rejected
aborted
unsupported
~~~

当前 identity commit result 的 <code>committed/noop/aborted/unsupported</code> 已存在；
<code>stale_parent/ambiguous/rejected</code> 是目标扩展。

### 7.3 Planned commit

planned state 写入 planned graph，绝不反向修改 source/world。VALIDATE 若发现问题，产生新的
repair/superseding changeset；不得把 planned geometry 搬进 current representation。

## 8. Snapshot、epoch、digest 与 rebase

单一 global digest 用于完整快照身份，但不能用它决定所有下游 row 是否都 stale。每个 snapshot
同时维护：

~~~text
global graph digest
source catalog digest
schema mapping digest
entity index digest
representation index digest
relation index digest
subgraph/dependency digests
change set digest
parent snapshot ref/digest
world model epoch
~~~

规则：

- global digest 不同：说明快照不同；
- dependency digest 相同：对应下游 row 可复用；
- identity merge/split：提升 affected entity dependency epoch；
- schema mapping 大范围变化：提升相关 collection epoch；
- source re-admission 或 namespace policy 变化：必要时提升 global epoch；
- planned graph 改变不使 current-only artifact stale。

Rebase 输入旧 proposal 与新 parent，重新查询 affected refs 并生成新 proposal/decision。不能只替换
parent digest。

## 9. Query consistency

每次 query 必须绑定：

~~~text
session_id
world_view
snapshot_ref/digest
query_fingerprint
page cursor
limit
projection version
~~~

分页期间 snapshot 不变；若 named ref 更新，旧分页继续读旧 snapshot 或显式返回 stale cursor。
query 不得在读取过程中改变 entity cluster、schema mapping 或索引。

## 10. Index lifecycle

规范索引：

~~~text
EntityNameIndex
EntityPropertyIndex
SourceAttributeIndex
RepresentationIndex
TopologyIndex
AssertionIndex
ProvenanceIndex
IdentityBindingIndex
~~~

索引是 snapshot projection，不是第二事实源。构建流程：

~~~text
snapshot committed
  → build indexes with snapshot digest
  → validate counts/digests
  → publish index descriptor
  → serve query
~~~

索引缺失时允许 bounded fallback query；索引 digest 不匹配时 fail closed 或重建，不能返回混合版本。

## 11. 并发与多进程

逻辑规则是 session + branch single writer，物理实现必须是可跨进程验证的 CAS，而不是进程内锁。
生产可选数据库 CAS、advisory lock 或带 fencing token 的 lease，但必须满足：

- writer 有 parent descriptor 和 fencing token；
- lease 过期 writer 无法发布；
- child artifact 可先写，named ref 发布只有一次；
- 失败 child 未发布且可被 GC；
- reader 只读 immutable descriptor；
- retry 可判定 committed/noop/stale-parent。

## 12. 失败、恢复和 GC

| 失败 | 行为 |
|---|---|
| parent digest mismatch | 返回 stale_parent，触发 affected rebase |
| invalid proposal/ref | rejected，不写 child |
| projection validation failure | aborted，保留 parent |
| CAS publish race | child 不发布，返回 stale_parent |
| index build failure | snapshot 保持有效，索引标记 unavailable 并重建 |
| corrupted artifact | fail closed，禁止回退到不明版本 |
| source removed | 新 assertion supersede/tombstone，旧 snapshot 仍可重放 |

GC 只清理由任何 named ref、artifact lineage、audit/HumanDecision 或保留策略都不可达的未发布对象。

## 13. LLM 边界

允许：

- schema mapping proposal；
- entity candidate ranking；
- concept/relationship proposal；
- ambiguous/abstain 分类。

禁止：

- 生成 entity/assertion/representation stable id；
- 直接写 graph；
- 决定 accepted、merge、split 或 supersede；
- 修改 geometry、CRS、digest、epoch 或 commit；
- 读取 planned graph 后影响 current-world 推理。

## 14. 可观测性

至少记录：

~~~text
commit outcome and latency
CAS conflict rate
assertions by status/kind
merge/split/rebase count
affected dependency rows
snapshot/index build duration
stale binding count
query page/stale cursor count
orphan artifact count
entity false-merge / false-split benchmark
~~~

## 15. 文件责任

当前实现：

~~~text
contracts/cognition/
contracts/ports/world_model.py
modules/cognition/application.py
modules/cognition/schema_understanding.py
modules/cognition/validation.py
infrastructure/cognition_runtime/world_model_store.py
infrastructure/kg/adapters/source_catalog_adapter.py
infrastructure/kg/adapters/world_model_commit_adapter.py
infrastructure/context_runtime/cognition_projection.py
~~~

目标收敛：

~~~text
contracts/cognition/proposals.py
contracts/cognition/rebase.py
contracts/cognition/views.py
modules/cognition/assertion_lifecycle.py
modules/cognition/entity_identity.py
modules/cognition/rebase.py
infrastructure/cognition_runtime/indexes/
infrastructure/cognition_runtime/writer_lease.py
~~~

文件名描述未来职责，不表示当前已存在。

## 16. 不变量

1. SourceRecord、Entity、Part、Representation 不得共用身份；
2. source graph 不因 assertion 决策被覆盖；
3. world graph 可由 accepted assertions 确定性重建；
4. planned 永不进入 current-world query；
5. GROUND、Evidence、L1 不直接写 World Model；
6. merge/split 通过 assertion supersede，不破坏历史；
7. 每次 commit 要么完整发布，要么完全不可见；
8. global digest 变化不自动使无关 dependency row stale；
9. representation 必须声明 purpose/role 和 DATA lineage；
10. provider observation 默认没有 execution geometry authority。

## 17. 验收

1. bootstrap、reload、digest、CAS race 和 corruption fail-closed；
2. assertion 全状态机与非法转移测试；
3. merge/split 后实体、表示、关系和 binding 精确失效；
4. typed view 证明 L1/L2/L3 无法读取 planned；
5. 小范围 assertion 更新不导致全链无条件重算；
6. index rebuild 与 snapshot 查询一致；
7. 多进程 writer 竞争只有一个 child 发布；
8. HumanDecision 生成新 decision/assertion，不直接改状态字段；
9. 真实标注集测 false merge/false split；
10. 当前代码尚未具备的目标项保持在迁移账本中，不写成 CURRENT。
