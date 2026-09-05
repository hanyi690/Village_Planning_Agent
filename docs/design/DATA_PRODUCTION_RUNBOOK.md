# DATA production acceptance and operating contract

本文是当前 DATA 实现的可执行运行说明。DATA 的唯一输入边界是
`DataAdmissionFacade`；`DataCatalog` 只提供 source declaration 和显式 bounded query，
不再组装旧 Bundle，也不从固定的 Jintian boundary 路径推断 provider 查询范围。

空间需求映射不属于 DATA ingestion：当前实现位于
`backend/app/modules/target_projection/spatial_reference_mapper.py`，只消费 typed L3
需求和已准入的 source 引用。旧 `data/ingestion/compiler` 包已物理删除，运行时不存在
旧路径 re-export 或 fallback。

## 0.1 几何适配策略

DATA 不把文件名、图层名或属性字段当作几何契约；几何契约只由解析后的 geometry、显式
CRS 和拓扑审计共同决定。当前 topology policy 是 `surface_family_compatible`：
`Polygon` 与 `MultiPolygon` 都属于二维 polygonal surface family，修复后可以在同族内
改变 exact type，但必须同时保留 raw geometry、normalized geometry、source/repaired
type、parts、面积变化和 `review_required`。

这不是声称 exact GeoJSON type 无损。不能保持既有 point/line/polygon family 的结果不再强行
转换；完整且有效的 `GeometryCollection` 可作为 `collection` normalized representation 进入
WM/Evidence 的来源和审计视图，但只提供 `read` capability，不可作为 polygon/line 执行相交、
缓冲、边界 scope 或规划几何。修复失败、空结果、非法范围、无法确定 CRS、或无法完整保留组件
的结果仍进入 `GEOMETRY_INVALID`；系统不为得到 polygon 而静默丢弃点/线组件，也不扩展
GeoJSON 的 type 枚举。源 family 与 normalized representation family 分别记录，避免下游误判。

解析器可以保留但执行后端不认识的原生 geometry type 使用 DATA 内部 `opaque` kind：raw
geometry 不改写，representation 为 `read_only`，只发布 `read` capability。它可被 WM 登记
为 `SourceRecord` 并被 Evidence 作为有界来源事实读取，但不得创建可执行 `WorldEntity`、
不得进入 `SpatialWorkspace`、BoundaryScope、GROUND、SELECT 或 EXECUTE。已知 geometry type
归一化失败时不能降级为 `opaque`，仍必须以 `GEOMETRY_INVALID` 拒绝；`opaque` 仅表示“未知
类型但原始载荷可保真保存”，不是质量豁免。

source semantic runtime、Planning Ground 和 independent normalized-product replay 也必须读取
`normalized_geometry_kind`。只有 point/line/polygon 才能进入相应空间分组或 grounding candidate；
`collection` 只保留来源、审计和 bounded read，不得按 source family 回退成可执行面、线或点。

金田村当前真实数据中，`landuse.geojson` 的 0-based feature 343 修复后仍为
`MultiPolygon`，parts 由 67 变为 50、面积相对变化约 -1.4464%，因此可以准入但必须标记
人工复核；feature 22、258，以及 `ecological_protection.geojson` feature 4 的修复结果为
`Polygon`，属于同一 surface family，准入时必须标记 exact type changed。

上传调用方如需建立边界范围，必须显式传入 `layer_ref` 和
`boundary_scope_mode="admitted_boundary"`，或使用显式的 polygonized administrative
boundary 声明。缺少该声明时，矢量仍按 generic resource 处理，但不会从文件名、属性或几何
数量猜测 boundary；这样可以避免把任意 Polygon 误当成 provider 查询范围。

在 `create-session` HTTP 入口中，使用 `village_data_layer_refs`（JSON 字符串数组）按序
声明各上传文件的 layer ref，并使用 `boundary_scope_file_index` + `boundary_scope_mode`
显式选择边界来源。该入口会拒绝数组/索引越界和未知模式；它不再根据上传文件名决定边界。

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

统一 harness 的默认行政阶段是 bounded profile：AMap 不默认执行扩展 polygon/边界采样，腾讯不默认
执行边界网格 nearby 扫描；这些高请求量探测只有显式 `--expand-admin` 才运行。bounded profile
仍保留地址、行政、有限 POI/建议、矩形和路线探测，并把每个 provider 的真实失败、部分覆盖和
发布状态写入 `data/cache/map_observations/<provider>/<stage>/runs/<run>/manifest.json`。

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
`normalized_all.jsonl` 只能包含已经完成 scope、行政匹配、坐标契约和 source/request ref
规范化的 canonical rows；request-level wrapper 只能进入 `normalized.jsonl` audit index。
如果旧 run 的 normalized 文件仍是 `{records: ...}` 包装格式，loader 必须拒绝其行并保持
PARTIAL/不可消费状态；修复方式是从保留的 raw response 重新经过正式 normalization/publish
生成新 run，而不是在 DATA loader 中增加 provider-specific 兼容解析。
`recover()` 为过期 staging 写入 `recovery.json: ABANDONED`，并将 lease 审计记录原子标记为
`EXPIRED`；新 run 只能使用更高 fencing token，旧 staging 不会被当成成功缓存。部署启动、
定时维护或人工故障处理可以调用 `ProviderRunLeaseStore.reconcile_expired()`，它只处理
已经过期的 `ACTIVE` 记录，且具有幂等性；`RELEASED` 和仍在 TTL 内的 lease 不会被改写。
lease JSON 不删除，以便审计和 replay；只有明确属于旧迁移区的内容才按迁移清单物理删除。

Provider acceptance harness 对明确的 capability rejection（例如 AMap `10012 /
INSUFFICIENT_PRIVILEGES`）启用 run-local circuit breaker：同一 operation 第一次收到不可恢复
的能力拒绝后，后续同 operation 请求不再访问网络，而是逐条写入
`status=missing_capability`、`attempted=false` 的 request audit row。该优化只减少确定性失败的
网络和限速等待，不把 skipped 变成成功、不删除 query plan，也不改变 COMPLETE/PARTIAL/FAILED
coverage 结论；临时的 provider acceptance 脚本仍不是正式业务入口。

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

2026-09-04 的真实 bounded admin 运行已验证三家 cache 的发布和 loader 消费链：AMap、Tianditu、
Tencent 均有 published manifest，coverage 分别为 `PARTIAL`、`PARTIAL`、`partial_failed`；
loader 读到 80 条边界过滤后的 advisory observations，但 snapshot `complete=false`。这证明
“可被 WM/Evidence advisory 消费”已经成立，不证明三 provider 的完整覆盖；COMPLETE 仍需在
具备稳定接口权限和服务响应的环境单独验收。

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

## 6. CUDA 部署决策

当前 DATA 没有启用 CUDA。即使部署主机有 NVIDIA GPU，也必须先确认可选运行时和基准结果；
不能因为安装了 CUDA toolkit 就把 GPU 路径视为生产可用。当前金田村 P0 的约 1,662 个空间
要素不足以证明 GPU 有收益，CPU canonical path 是验收基线。

允许 GPU 加速的范围只有规范化之后的大批量数值计算：例如点面包含、空间连接、候选四叉树、
点到线距离，以及未来实际存在的 DEM 坡度、阴影、栅格分类等数组运算。GeoJSON 解码、显式
CRS 变换、Shapely/GEOS `make_valid`、CAS/SQLite、provider 网络运行时、WM 投影和 Evidence
检索继续使用 CPU。尤其不能用 GPU 替换 `make_valid`，因为它会破坏现有的 topology repair
trace、surface-family 审计和 fail-closed 语义。

正式接入时应以独立 optional accelerator port 实现，并遵守：

1. 输入必须是已准入、已规范化、带明确 CRS 的 canonical 表示；
2. GPU 结果必须回到 host，执行确定性不变量校验，并且不改变 source/catalog digest；
3. CUDA、显存、kernel 或校验失败必须回退 CPU，不能改变 admission、coverage 或 Evidence
   sufficiency；
4. 只有 benchmark 证明达到收益阈值，且 CPU 对照验收通过，才允许在 provider run 或 DEM
   批处理配置中启用；
5. 加速器版本、设备、批大小和耗时写 execution trace，不写入数据身份摘要。

推荐候选为 [RAPIDS cuSpatial](https://docs.rapids.ai/api/cuspatial/stable/) 和
[CuPy](https://docs.cupy.dev/en/stable/overview.html)。它们是部署增强项，不是 DATA 的
必要依赖；无 GPU 环境必须得到相同的可消费 WM/Evidence 产品。

当前本机观测：完整 pytest 回归约 27--30 s，真实 Jintian DATA→WM→Evidence acceptance 约
最近 focused Jintian P0 acceptance warm run 约 7.7--8.2 s（历史观测为 9.2--9.6 s），
10 个 GeoJSON + DEM + Markdown admission 约 7--10 s。主要收益来自消除
current-world 重复 canonicalization、将 admission decision 和 DATA dependency 按 resource
建索引、将多份上传 catalog 一次合并，以及在 `include_reports=false` 时跳过文档 DB 读取。
WM 的 TriG/CAS 写出采用确定性
full-N3 named-graph writer，按 graph 和 term 排序并保留 literal lexical form；回读仍通过
RDFLib TriG parser，故它是 WM 表示层优化，不是 DATA 几何或身份规则的变化。上述数字是
性能观测，不是跨主机硬门限；发布环境必须重新测量 admission、context、WM projection、
CAS 和 Evidence 各段。

WM 冷启动还将 TriG named-graph 序列化与稳定 graph digest 合并为一次 RDF 四元组遍历，
并将已生成的 TriG bytes 直接复用到 CAS。当前稳定 digest 使用
`sha256-sorted-rdflib-n3-quads-v2-length-prefixed`；版本升级会使旧算法快照不能被错误恢复，
但不会改变 RDF 四元组、来源引用或 WM/Evidence 消费契约。当前一次真实 Windows acceptance
的完整 P0 测试历史约 9.2--9.6 s，最近本轮约 7.7--8.2 s，完整回归约 22--30 s；这些数字仅用于说明优化方向，
不是 SLO。

当前热路径的增量优化也已与上述验收保持一致：CAS 写入复用一次 JSON-safe payload 的
canonical JSON 和 semantic digest，避免重复执行 Pydantic/model conversion；四类无嵌套
volatile timestamp 的 DATA 产品直接复用 canonical blob digest，stage/gate 和 source product
仍按原规则过滤 `created_at`/`artifact_id`/provenance timestamp 等字段。WM 的 road retry port 只在首次真实 retry 时建立 RDF
索引；source catalog 的线段 identity 使用预计算 semantic token 和端点网格筛选候选，最终
距离判断仍使用原有精确阈值。这些改变不改变 catalog/WM/Evidence digest、父级关系、CRS、
geometry authority 或 Evidence 的来源引用。无 retry 请求的 context bootstrap 不应因为构造
未使用的 road retry 索引而产生额外扫描成本。
多文件输入可以通过 `DataAdmissionFacade.admit_many()` 使用有界 worker 并发；CreateSession
按最多 4 个任务调度真实 upload，并按输入顺序收集结果。每个文件仍拥有独立 receipt、完整
lifecycle、CAS parent 和数据库记录，不合并准入决策，也不削弱 fsync、lease/fencing 或
crash recovery。相同 immutable catalog 的重复 admission 校验按 `snapshot.digest` 使用
64 项成功 LRU，Evidence DATA retriever 另使用 8 项 bounded 属性搜索索引；这两个缓存均
只在进程内生效，失败不缓存，不缓存 geometry，digest 变化即失效。
几何缓存键使用 `orjson` 的高速排序编码，但只用于进程内寻址；source/catalog 的正式
canonical digest 算法保持不变。具有 DATA feature digest 的道路输入另使用最多 32 项
network snapshot LRU，未携带 DATA digest 的临时 mapping 不进入缓存。
同一不可变 DATA catalog 被多个 context 重复投影时，可命中最多 2 项的进程内 source/world
RDF projection LRU。它只缓存不含 raw geometry 的 RDF 三元组，按 catalog digest、schema
mapping fingerprint 和 graph mode 隔离；缓存命中只回放三元组，不改变 DATA/CAS/Evidence
权威。缓存不跨进程、不跨重启，首次投影和 cache miss 仍完整执行所有 DATA admission、CRS、
topology、identity 与 lineage 逻辑。
截至本次离线缓存审计，完整行政范围下 AMap canonical cache 可被 Evidence 读取 93 条，
Tencent 可读取 84 条，Tianditu 可读取 0 条；三家整体均为 `complete=false`/非 COMPLETE。
旧 AMap wrapper run 保留为审计源，并通过 raw response 重建了新 canonical run；DATA loader
不承担旧 wrapper 的 provider-specific 解析兼容。
从代码、测试和本地 Jintian E2E 的角度，DATA 层已经不再依赖旧 Bundle 和旧 output cache，可以作为当前 MVP 的真实实现基础。 但仍不能把本地测试通过直接等同于完整生产就绪。还需要在实际部署环境补齐： - 三家地图线上真实覆盖率与限流行为； - production 级文件系统权限和多进程 writer 验证； - 真实 crash recovery 与 fencing 场景； - 灾难恢复、备份恢复和跨存储迁移； - 线上 SLO、RPO、RTO； - 完整 API vector/WFS/MapServer/WMTS/remote raster 的线上 provider acceptance。
