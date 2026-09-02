# 05 目标到当前的迁移账本

> Status: CURRENT
>
> 本文件只记录当前代码与目标设计的差距。模块为什么这样设计见对应 design owner；当前代码路径
> 和运行方式见 <code>architecture/</code>。状态不得从文件数量或旧 session 日志推断。

## 1. 状态定义

| 状态 | 含义 |
|---|---|
| <code>CURRENT</code> | 目标边界、typed product、持久化、失败、下游消费和 fresh 验收均闭合 |
| <code>PARTIAL</code> | 已有真实实现，但仍缺 contract、纵向验收或兼容退出 |
| <code>GAP</code> | 尚无目标实现 |
| <code>BLOCKED</code> | 外部资料/权限/服务明确阻断，并有恢复指针 |
| <code>RETIRE</code> | 旧实现无调用者且退出门已通过 |

本账本只记录跨模块规划闭环的总体状态；DATA 自身的详细实现和删除边界以
<code>DATA_EXECUTABLE_DESIGN.md</code> 为准。DATA 的本地 admission/catalog/WM/Evidence
消费链已通过本地验收；真实远程 provider、部署 ACL、灾备 restore 和线上 SLO 仍是发布环境
门禁，不应通过恢复旧兼容代码解决。

## 2. 当前实现矩阵

| 阶段 | 当前实现事实 | 状态 | 最近出口 |
|---|---|---|---|
| DATA | 统一 local/remote declaration admission、四类 immutable product、BoundaryScope、provider lease/writer、DATA-only DataChangeSet、WM/Evidence consumer 和旧 DATA 物理删除均已落地 | CURRENT（本地） | 真实 provider 在线 coverage、部署 ACL、灾备 restore、线上 SLO/RPO/RTO |
| Cognition/WM | 有 DATA-backed store、snapshot/CAS、source/entity/representation contracts、identity commit | PARTIAL | assertion 全生命周期、merge/split、typed views、dependency digest、多进程 writer |
| Evidence | 有 requirement、retrieval authority/outcome、CAS artifact、coverage、gap ledger 和 scheduler | PARTIAL | authority/sufficiency policy、provider attempt 细状态、融合冲突、proposal contract |
| L1 | 有 bounded dimension input、typed facts/mentions/gaps、aggregation、gate 和 CAS | PARTIAL | source-span report、冲突组、L1ProductManifest、最终视图 Gate |
| L1-GROUND | 有 observation/binding sidecars、闭集候选、identity commit 调用和 projection receipt | PARTIAL | 统一终态 taxonomy、proposal ownership、revalidation、状态迁移测试 |
| L2 | 有 typed strategy/decision rows 和依赖输入 | PARTIAL | 以稳定 L1 final view 完成 fresh 四维消费 |
| L3 | 有 PlanningProgram/claim contracts 和 bounded reasoning | PARTIAL | 以 L2 PASS 形成非空、可接地 intent |
| TARGET_PROJECTION | 有 typed projection、pending request 和 admission validation | PARTIAL | pending/admitted 状态与唯一 Gate matrix 对齐 |
| Planning GROUND | 有 entity/representation/resource lineage、candidate domain、constraint factor | PARTIAL | executable-only Gate、复杂关系/多表示、语义 benchmark |
| SELECT | 有 scenario、solver readiness、selection decision、approval input | PARTIAL | 只接受 resolved domain，补齐 infeasibility certificate 和生产验收 |
| EXECUTE | 有 generic point/line/polygon 路径和 parcel compatibility | PARTIAL | 原子回滚、混合任务重放、旧 parcel 退出 |
| VALIDATE | 有 geometry、relation、lineage 和面积类检查 | PARTIAL | 针对完整 planned state 的 fresh 验收 |
| Delivery Readiness Reconcile | 有 validation/execution/deferral 汇总 | PARTIAL | 收窄为 gap ledger/classifier，并验证不替代上游修复 |
| DELIVER | 有 spatial snapshot、GeoJSON/PNG/HTML/export 路径 | PARTIAL | 非空规划结果、质量报告和 lineage 一致性验收 |

## 3. 初期认知闭环差距

### 3.1 DATA

已实现并本地验证：

- `process_uploaded_file` → `DataAdmissionFacade.admit` 的唯一上传写边界；
- local GeoJSON/矢量/GeoTIFF/表格/Markdown 的 bounded parse 和 current-role admission；
- `RemoteSourceAdmissionRequest` 覆盖 API vector/WFS/MapServer/WMTS/remote raster；
- SourceSnapshot、NormalizedResource、RepresentationSnapshot、CapabilityIndex 和轻量 catalog index；
- BoundaryScopeArtifact、严格 CRS/type/geometry policy、topology repair audit；
- provider lease/fencing/atomic writer/crash recovery 和完整 coverage manifest；
- DATA-only `DataChangeSet` publication；跨模块 dependency/subgraph invalidation 归 Dependency Runtime；
- Jintian upload → WM → Evidence → replay/stale-parent 的本地 E2E；
- 旧 Bundle、BSM/DLBM 派生、external anchor、typed ingest adapter 和 output cache 的物理删除。

开放项只属于发布环境：真实 provider 在线 coverage、部署主机 ACL、CAS/SQLite 灾备恢复和
实际 SLO/RPO/RTO 测量。

### 3.1.1 Provider validation harness 迁移检查项

当前存在但未进入生产链的脚本：

```text
scripts/collect_amap_jintian_validation.py
scripts/collect_three_provider_validation.py
scripts/collect_tianditu_full.py
```

这些脚本暂时保留为 acceptance harness，不能作为正式业务采集入口，也不作为 DATA 或 Evidence 的第二个正式入口。AMap
harness 已使用 `BoundaryScopeArtifact`、`ProviderAcquisitionPlan`、lease/fencing、
`ProviderObservationWriter` 和统一 map observation cache，但仍直接使用 `requests.Session`，并
保留自己的 retry/cache、Jintian/L1 查询编译、scope classifier 以及
`retained_candidates.jsonl`/`rejected_candidates.jsonl` 筛选。因此它们的输出只能作为审计样本，
不能作为 Evidence sufficiency 或 World Model identity 的权威来源。

退出条件：

- 正式 Evidence provider runtime 能接收 `EvidenceQueryPlan → AcquisitionRequest`；
- 脚本直接 HTTP 和私有 retry/cache 已迁移到正式 runtime；
- `ProviderAttempt`、分页完整性、quota/timeout/empty/missing 状态由正式 runtime 产生；
- L1 mention 读取和业务 query 编译移入 EvidenceRequirement/QueryPlan；
- retained/rejected 仅作为 Evidence candidate/ConflictSet 的受控投影，不再由脚本决定；
- 迁移后 acceptance harness 仍能重放同一 acquisition fingerprint。

在这些条件满足前，不能删除脚本的 acceptance 入口和审计产物；但也不能把脚本接入正式业务
workflow。

### 3.2 Cognition / World Model

已实现：

- <code>SessionWorldModelSnapshot</code>、source/entity/part/representation contract；
- DATA-backed bootstrap；
- immutable artifact 与 named-ref CAS；
- <code>IdentityBindingCommitEnvelope/Result</code>；
- bounded entity、representation、relation、identity-binding query。

仍缺：

- assertion 的完整 proposal→decision→accepted/ambiguous/rejected/superseded 转移；
- merge/split 的 supersede + rebuild + binding invalidation；
- <code>CurrentWorldQueryPort / IntentWorldQueryPort / PlannedWorldQueryPort</code>；
- global digest + dependency/subgraph digest；
- stale-parent rebase contract；
- 生产多进程 writer lease/fencing 验收。

### 3.3 Evidence

已实现：

- requirement compilation 与 requirement fingerprint；
- frozen retrieval authority、typed outcome、write-once artifact；
- coverage/sufficiency 的基础计算；
- immutable gap ledger 和 scheduler row；
- external observation 的坐标信任与 advisory 边界。

仍缺：

- required authority、独立来源、max age、legal effective time、conflict policy；
- retryable/permanent/quota/partial 的统一 provider attempt contract；
- 完整分页证书、跨 provider candidate cluster 和 conflict set；
- Evidence→Cognition proposal artifact；
- requirement-specific sufficiency benchmark。

### 3.4 L1

已实现：

- source page、input context、dimension pass state；
- typed fact、location mention、gap 和 snapshot；
- spatial work-item admission；
- observation/binding sidecar 和 WM projection receipt 的实际调用链。

仍缺：

- 独立 source-span validation report；
- fact conflict group 与 supersedes；
- 轻量 <code>L1ProductManifest</code>；
- commit 后 binding revalidation；
- L2/L3 只消费 final view 的硬门禁。

### 3.5 L1-GROUND

已实现：

- source/catalog/WM/evidence 候选召回；
- closed-set LLM proposal 与 deterministic checks；
- exact/feature-set/inferred/ambiguous/unresolved 兼容状态；
- identity commit envelope 与 L1 world projection artifact。

仍缺：

- 设计定义的细粒度终态和 candidate_count=0 reason taxonomy；
- proposal 与 commit owner 的显式 contract 分层；
- merge/split/WM 更新后的精确 revalidation；
- HumanDecisionArtifact；
- 标注集上的 candidate recall@K、grounding precision 和 representation-purpose accuracy。

## 4. 已知设计—实现不一致

### 4.1 GROUND Gate

目标规则：

~~~text
PASS ⇔ required target domains resolved
       ∧ hard inputs ready
       ∧ executable candidate domain non-empty
       ∧ pending/evidence requests empty
~~~

当前 <code>modules/ground/validation.py</code> 仍可能在 unresolved/problem issue 下返回
<code>passed=True</code> 并携带 pending requests；路由基础设施又把 pending 视为不允许继续。
运行安全目前依赖后一道检查，但 contract 表达不唯一。

迁移：

1. Gate evaluator 对 recovery/HUMAN 一律 <code>passed=False</code>；
2. artifact 的 partial/diagnostic 与 workflow Gate 分离；
3. pending TARGET 只进入 GROUND recovery worker；
4. SELECT 不接收 pending/ambiguous/unresolved domain；
5. 添加 matrix-driven route tests。

### 4.2 World Model writer

当前 L1-GROUND orchestration 调用 <code>WorldModelCommitPort</code>，实际 V2 store 执行原子提交。
目标设计将其明确为“GROUND 产 proposal，Cognition transaction 是 writer”。需要把 proposal
validation/decision contract 从 orchestration 中进一步抽出；旧 KG adapter 对 identity commit
返回 unsupported 并 fail closed。

### 4.3 Digest invalidation

当前 artifact 广泛记录 global World Model digest。目标要求同时记录 dependency/subgraph
digest，否则小范围 identity 更新可能导致无关 artifact stale。新增字段前保持 conservative
invalidity，不能假装已经支持局部 rebase。

### 4.4 Human review

当前有 HUMAN route、review API 和 pending request，但尚未统一为不可变
<code>HumanDecisionArtifact</code>。在 contract 完成前，人工操作不得被文档描述成完整
assertion/admission/approval 事务。

## 5. 当前可重复验证面

仓库已有或可直接运行的验证入口：

~~~text
python -m compileall -q backend/app
python scripts/acceptance/business_stage_boundary_probe.py
python scripts/acceptance/l1_facade_probe.py --help
python scripts/acceptance/l1_l2_facade_probe.py --help
python scripts/acceptance/ground_current_session_probe.py --help
python -m pytest tests -q
git diff --check
~~~

只有本次实际运行成功的命令才能在交付报告中写成 RUNTIME_VERIFIED。本账本不保存某次运行的
test count、session id、临时路径或 digest。

## 6. 初期退出门

认知闭环标为 CURRENT 前必须同时满足：

1. fresh DATA snapshot 可重载，来源角色隔离有效；
2. WM v0 bootstrap、CAS、reload 和 corruption/race fail-closed；
3. Evidence provider 状态、coverage、gap 可重放；
4. L1 facts 有 source-span 验证，地点项有唯一终态；
5. L1-GROUND 只产 proposal，Cognition 原子提交 WM v1；
6. commit 后 binding revalidation；
7. L1ProductManifest 发布并由 bounded L2 probe 消费；
8. 新 evidence/WM 变化只重算受影响 row；
9. HUMAN 决定通过不可变 artifact 应用；
10. 真实标注集达到已登记的语义质量门。

## 7. 中期 MVP 退出门

1. 至少一条 fresh session 产生非空 L2/L3；
2. TARGET pending/admitted 路由符合唯一 Gate matrix；
3. Planning GROUND 形成 resolved executable domains；
4. SELECT 产生 feasible 或可解释 infeasible certificate；
5. approval、execution plan、changeset 和 planned state digest 闭合；
6. generic point/line/polygon 至少各一类真实执行；
7. VALIDATE/RECONCILE/DELIVER 产生非空、有 lineage 的成果；
8. 无资料会话形成 HUMAN 或 diagnostic-only，而不是伪造完整规划。

## 8. 上层 parcel/BSM 迁移边界

DATA 已不再提供 parcel/BSM typed ingest、Bundle assembly 或 BSM/DLBM 派生入口。仍被更高层
规划契约引用的历史字段和响应容器不属于 DATA current path；它们必须在独立的上层迁移中处理，
不能重新加回 DATA 作为兼容 shim。DATA 只向上层提供 generic resource/representation/capability
lineage；上层若仍要求旧 typed contract，缺少对应投影时必须显式失败。

## 9. 更新规则

1. 只记录当前差距和最近出口；
2. 代码事实变化后先更新 <code>architecture/CURRENT_RUNTIME</code>，再更新本账本；
3. 运行日志留在测试/CI/artifact，不粘贴到设计；
4. 设计目标变化时更新对应 owner，不在本文件发明新架构；
5. 任何 CURRENT 状态都必须指向 fresh、可重放、下游可消费的证据。
