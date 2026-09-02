# DATA production acceptance and operating contract

本文是当前 DATA 实现的可执行运行说明。DATA 的唯一输入边界是
`DataAdmissionFacade`；`DataCatalog` 只提供 source declaration 和显式 bounded query，
不再组装旧 Bundle，也不从固定的 Jintian boundary 路径推断 provider 查询范围。

## 0. Provider validation harness 不是生产入口

`scripts/collect_amap_jintian_validation.py`、`scripts/collect_three_provider_validation.py` 和
`scripts/collect_tianditu_full.py` 仅是 Jintian provider acceptance harness。它们用于 capability
probe、在线 API 验收、fixture/cache 生成和人工审计，不能作为正式业务采集入口，也不能被 L1、
L1-GROUND 或 session workflow 直接调用。

AMap 脚本虽然已经接收 `BoundaryScopeArtifact`、生成 `ProviderAcquisitionPlan`、使用 provider
lease/fencing 和 `ProviderObservationWriter`，但当前仍有脚本自有的 `requests.Session`、retry/cache
逻辑、L1 snapshot 读取、scope classifier 和 retained/rejected candidate 投影。这些结果只能作为
audit-all observation 和诊断产物；`retained_candidates.jsonl`、`rejected_candidates.jsonl`、
`scope_summary.json` 不是 Evidence candidate set、Coverage 或 Sufficiency 的权威结果。

正式业务路径必须经过：

```text
EvidenceQueryPlan
  → AcquisitionRequest
  → DATA ProviderAcquisitionPlan / formal provider runtime
  → ProviderAttempt / AcquisitionReceipt
  → ExternalObservation
  → Evidence Reasoning
```

在正式 provider runtime 完成迁移前，不得把这些脚本的新业务逻辑复制到 L1、Evidence 或其他
workflow；迁移完成后脚本才可以收窄为正式 runtime 的 acceptance driver。

## 1. 远程来源准入

API vector、WFS、MapServer、WMTS 和 remote raster 均先提交
`RemoteSourceAdmissionRequest`。声明必须包含：

- allowlisted HTTPS endpoint；
- `boundary_ref`、`boundary_digest`、`query_geometry_digest`；
- 明确的 source CRS 到 `WGS84/EPSG:4326` 目标契约；
- capability、请求数、记录数、超时和 zoom 上限；
- 只引用凭据的 `env://` 或 `credential://`，不得把 token 放进 endpoint、query 或 receipt。

`DataAdmissionFacade.admit_declared_remote()` 只发布 immutable receipt，不发起网络请求。
Provider run 只有在 receipt、BoundaryScopeArtifact 和 `ProviderAcquisitionPlan` 都存在时才能执行；provider
必须再发布带完整 coverage 的 normalized snapshot，失败或部分覆盖不得升级为 current DATA。
API vector 的声明协议是封闭的：声明 MapServer 只执行 MapServer，声明 WFS 只执行 WFS；协议失败
即返回失败，不跨协议 fallback，也不把 WMS 可视化 URL 当作可供 WM/Evidence 消费的矢量数据。

YAML source declaration 可通过
`RemoteSourceAdmissionRequest.from_catalog_declaration()` 编译为同一 contract。没有显式
endpoint 的远程声明直接拒绝，不从 connection 或 provider 名称猜 endpoint。

## 2. Provider writer、lease、fencing、recovery

每个 `<provider>/<stage>/<run>` 使用 `ProviderRunLeaseStore` 获得独占 lease。lease 文件和
临时写锁采用原子创建/替换并执行 fsync；重新取得过期 lease 时 fencing token 单调递增。
writer 在 request、normalized row、manifest 发布前后均检查 owner、token、状态和 expiry。
因此旧进程即使在 crash 后继续运行，也不能覆盖新 writer 的结果。

`ProviderObservationWriter.publish()` 以临时文件 + replace 发布
`normalized_all.jsonl` 和 `manifest.json`，manifest 至少包含 boundary/query digest、CRS
contract、fencing token、record count、checksum、coverage status 和 published status。
`recover()` 为过期 staging 写入 `recovery.json: ABANDONED`；新 run 只能使用更高 fencing
token，旧 staging 不会被当成成功缓存。

## 3. DATA change publication

DATA only publishes DataChangeSet；它不拥有 WM、Evidence 或 Ground 的跨模块失效动作。

每个 DATA run 构造只包含 DATA-owned 节点的 `DataDependencyGraph`，并通过
`plan_data_change_set(previous, current)` 发布不可变 `DataChangeSet`：

`data:catalog → source/normalized/representation/capability`。

DATA 可以沿自身 reverse edges 找出受影响的数据产品，但不清理 WM runtime cache、不清理 Evidence
retrieval cache，也不直接标记 Ground stale。统一 Dependency Runtime 才能把 `DataChangeSet`
映射到 WM/Evidence/GROUND 的 dependency/subgraph row。跨模块 stale 传播必须只有这一处 owner。

CAS 中的 immutable DATA/WM/Evidence blob 保留，便于 replay、审计和恢复；没有 dependency metadata
时由 Dependency Runtime 按其自身策略保守失效，而不是由 DATA 猜测下游状态。

## 4. WM 与 Evidence 消费边界

World Model 通过 `project_source_catalog()` 消费 normalized DATA catalog；几何和属性只在
DATA artifact / World Model projection 内使用。Evidence 使用
`data_catalog_retriever` 返回 source-feature ref、snapshot ref、digest 和 geometry authority，
不从 provider cache 或本地文件直接读取可执行 geometry。三家地图 cache 只能由
`cached_map_retriever` 作为 advisory observation 读取，不能改写本地 DATA catalog。

Jintian acceptance 必须覆盖：上传 boundary、receipt、normalized boundary、三 provider acquisition
plan、canonical cache/snapshot、context bootstrap、WM/Evidence retrieval、geometry digest
未变化、idempotent replay、stale parent 和跨 WM/Evidence/GROUND invalidation。

## 5. Production gate

`scripts/acceptance/data_production_acceptance.py` 执行静态 gate：扫描部署源文件的凭据字面量、
不安全权限和已退役路径。动态 gate 由 pytest 执行：

```text
python -m pytest tests -q
python scripts/acceptance/data_production_acceptance.py --root .
```

默认 SLO 为 admission ≤ 2 s、context bootstrap ≤ 10 s、Evidence retrieval ≤ 3 s；默认 RPO
≤ 15 min、RTO ≤ 30 min。任一安全扫描、SLO、replay、stale-parent、invalidation、provider
crash-recovery、WM consumable 或 Evidence consumable 失败，报告为 FAIL。

当前工作树已验证本地端到端和故障语义；真实远程 provider 的在线覆盖率、凭据轮换、跨主机
备份恢复和实际部署 ACL 仍需在发布环境使用同一 contract 做一次演练，不能用本地 cache-only
测试替代该证据。
从代码、测试和本地 Jintian E2E 的角度，DATA 层已经不再依赖旧 Bundle 和旧 output cache，可以作为当前 MVP 的真实实现基础。 但仍不能把本地测试通过直接等同于完整生产就绪。还需要在实际部署环境补齐： - 三家地图线上真实覆盖率与限流行为； - production 级文件系统权限和多进程 writer 验证； - 真实 crash recovery 与 fencing 场景； - 灾难恢复、备份恢复和跨存储迁移； - 线上 SLO、RPO、RTO； - 完整 API vector/WFS/MapServer/WMTS/remote raster 的线上 provider acceptance。
