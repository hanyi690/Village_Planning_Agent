# DATA 可执行设计与当前实现

> 状态：CURRENT / DATA-only active path
>
> 本文是 DATA 的唯一详细设计 owner。本文描述当前工作树中真实存在并由测试覆盖的实现，
> 不把未来目标写成已实现，也不把已经删除的 Bundle、typed ingest 或 provider anchor 代码
> 作为兼容能力。代码行为发生变化时，先修改本文对应章节，再修改迁移账本。

## 1. DATA 的责任和非责任

DATA 把显式声明的本地文件或远程来源声明转换为可追踪、不可变、可重载的输入产品，并向
World Model、Evidence 和 Planning Ground 提供带 lineage 的读取接口。

DATA 负责：

- 接收 upload 或 source declaration；
- 计算内容、来源、边界、查询几何和策略 digest；
- 解析 GeoJSON、Shapefile/ZIP、GPKG/GDB、KML/GML、GeoTIFF、表格和 Markdown；
- 校验 media type、encoding、CRS、geometry validity、预算和来源时态角色；
- 构造 SourceSnapshot、NormalizedResource、RepresentationSnapshot、CapabilityIndex；
- 生成 BoundaryScopeArtifact；
- 管理远程 provider declaration、lease、fencing、原子 writer 和 coverage manifest；
- 通过 dependency graph 使下游 stale；
- 为 WM/Evidence 提供只读 catalog/observation 查询。

DATA 不负责：

- 组装 `VillageBundle` 或 session-level typed parcel 集合；
- 生成 BSM、从 DLBM 派生规划分类或把业务字段作为准入前置条件；
- 以文件名、图层名、中心点或外部 POI 猜测 current geometry；
- 将 AMap/Tencent/Tianditu observation 写回本地 DATA geometry；
- 进行规划决策、候选排序、实体最终确认或审批；
- 用 fallback 把失败、未知 CRS、部分 coverage 或缺少 receipt 转成成功。

## 2. 当前唯一主链路

```text
UploadFile / YAML remote declaration
  → bounded discovery and parse
  → source admission / temporal role gate
  → DataAdmissionFacade.admit()
  → immutable component products in CAS
  → catalog index + receipt/gap
  → BoundaryScopeArtifact (boundary only)
  → ProviderAcquisitionPlan / lease / writer / coverage
  → context bootstrap
  → DATA-backed World Model projection
  → Evidence data_catalog_retriever
  → Planning Ground read-only lineage
```

本地上传的真实入口是
`backend/app/data/ingestion/upload.py::process_uploaded_file`。它先读取有限字节并计算
`source_digest`，完成解析和预算检查，调用
`assess_uploaded_source_admission`，再构造 `DataAdmissionRequest` 并调用
`backend/app/modules/data/application.py::DataAdmissionFacade.admit`。

SQLite 的 `UploadedFile` 只保存上传索引、状态、diagnostic 和 artifact refs；session reload
通过已保存的 refs 从 CAS 恢复产品。它不会再次把正文解释成另一套 catalog，也不会从固定
文件路径重建边界。

## 3. 输入闭包

### 3.1 金田村本地输入

当前真实基线位于：

```text
data/gis/jintian/current/boundary.geojson
data/gis/jintian/current/admin_boundary_line.geojson
data/gis/jintian/current/landuse.geojson
data/gis/jintian/current/road.geojson
data/gis/jintian/current/construction_zone.geojson
data/gis/jintian/current/farmland_protection.geojson
data/gis/jintian/current/ecological_protection.geojson
data/gis/jintian/current/historical_protection.geojson
data/gis/jintian/current/geological_hazard_points.geojson
data/gis/jintian/current/annotation.geojson
data/gis/jintian/terrain/dem.tif
docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md
```

这些路径是测试和本地验收的真实输入，不是 DATA 运行时固定读取依赖。生产代码必须通过
upload/admission artifact 传递它们；provider 必须通过 `BoundaryScopeArtifact` 获取边界。

### 3.2 外部地图和瓦片

```text
data/cache/map_observations/{amap,tianditu,tencent}/
data/cache/tiles/{img_c,ter_c,cia_c}/
```

`map_observations` 保存 provider run 的 manifest、normalized rows、attempt/request 状态和
原始响应引用；它是 Evidence 的 advisory observation 来源，不是 current DATA geometry 来源。
`tiles` 是 WMTS 视觉瓦片缓存，不是矢量事实来源。

`output/` 不承载 DATA cache 或旧 Bundle 输入。以下旧内容已经物理删除：

- `output/map_validation`、`output/amap_validation`、`output/bundle_cache`、`output/intent_cache`；
- `output/experiments/cache`；
- `output/**/grounded-anchor-cache.json`、`output/**/l3-projection-cache`；
- `output/gis-agent-road/**/inputs/bundle`。

### 3.3 Provider validation scripts 的冻结边界

当前仓库仍保留以下 Jintian 专项脚本：

```text
scripts/collect_amap_jintian_validation.py
scripts/collect_three_provider_validation.py
scripts/collect_tianditu_full.py
```

它们没有被 `backend/app` 生产业务链调用，定位是开发验证、在线 provider capability probe、
真实 API acceptance 和 observation fixture/人工审计的 acceptance harness。AMap 脚本当前已经
要求 `BoundaryScopeArtifact`，使用 `ProviderAcquisitionPlan`、provider lease/fencing、
`ProviderObservationWriter` 和 `data/cache/map_observations`；但它仍保留脚本内的
`requests.Session`、retry/cache 状态、L1 snapshot 名称读取、scope classifier 和
`retained_candidates.jsonl`/`rejected_candidates.jsonl` 投影。

因此这些脚本目前是“已接入 DATA 产物的专项 harness”，不是正式 provider runtime，不能作为正式业务采集入口。
它们禁止：

- 被 L1、L1-GROUND 或正式 session workflow 直接调用；
- 自己决定 Evidence sufficient、absence 或现实对象不存在；
- 自己创建 WorldEntity、canonical identity 或写 World Model；
- 将 `retained_candidates.jsonl`、`scope_summary.json` 解释为 Evidence candidate set、
  Coverage 或 Sufficiency 结论；
- 通过硬编码 Jintian 地址、L1 mention 或脚本规则替代 EvidenceRequirement、EvidenceQueryPlan
  和正式 provider acquisition runtime。

后续 Evidence provider runtime 完成后，脚本应收窄为：

```text
acceptance arguments
  → frozen EvidenceQueryPlan / AcquisitionRequest
  → formal provider acquisition runtime
  → ProviderAttempt / AcquisitionReceipt
  → ProviderObservationWriter
  → audit summary
```

迁移完成前不得删除这些脚本的审计产物；迁移完成后才允许删除其直接 HTTP、私有 retry/cache、
L1 读取和 retained/rejected 业务筛选代码。

## 4. 公共入口和模块边界

### 4.1 `DataAdmissionFacade`

文件：`backend/app/modules/data/application.py`

主要操作：

```text
admit(DataAdmissionRequest) → DataAdmissionResult
admit_declared_remote(RemoteSourceAdmissionRequest) → RemoteSourceAdmissionReceipt
load_catalog(state) → DataResourceCatalogSnapshot | None
load_boundary_scope(state) → BoundaryScopeArtifact | None
resume(gap_ref, recovery_input) → DataAdmissionResult
```

`admit()` 是本地数据唯一写边界。它负责：

1. 计算 deterministic attempt ref；
2. 校验 input role、media type、adapter、CRS、parent catalog 和 policy；
3. 将 GeoJSON-like records、raster descriptor、table resource 或 document 转成 generic catalog；
4. 执行 current-world projection；
5. 按 component product 先写 CAS，再一次性提交 catalog index；
6. 生成 receipt、gap、stage、snapshot 和 dependency metadata；
7. 对相同输入幂等 replay，对旧 parent 返回 stale parent。

失败或可恢复的输入由 `DataAdmissionGap` 描述；`resume()` 只能以 gap 为父引用创建新
attempt，不能把旧 receipt 原地改成成功。

`admit_declared_remote()` 只验证和持久化声明，不联系网络、不实例化 connection、不执行
provider。真实抓取属于 provider run，并且必须有 receipt、boundary scope 和 `ProviderAcquisitionPlan`。

### 4.2 `DataCatalog`

文件：`backend/app/data/catalog/catalog.py`

`DataCatalog` 只做三件事：读取 `sources.yaml`、经 DriverRegistry 实例化 driver、执行显式
bounded query。它不组装 session object、不推断村界、不注入外部锚点、不执行 LLM。

本地组合的 capability gate 是
`app.data.admission.check_local_admission_boundary`；它只接受已登记的 media type、adapter、
encoding、CRS 和 role 组合。缺少组合声明时返回 gap，不进入旧 parser 试探。

### 4.3 ingestion public surface

文件：`backend/app/data/ingestion/__init__.py`

当前只导出：

- `process_uploaded_file`；
- `DataResult` / `DataSourceMetadata`；
- `DataSourceDriver` / `DriverRegistry`；
- `Connection` / `ConnectionRegistry`；
- 延迟导出的 `DataCatalog`。

旧 ingest.py、typed adapters、POI 聚合、provider anchor service、data-side gazetteer、
独立 encoding detector、admin code loader 和 location parser 已物理删除，不能通过 import 或
re-export 重新出现。

## 5. 生命周期和失败状态

成功生命周期是：

```text
DISCOVERED
  → CLASSIFIED
  → PARSING
  → NORMALIZED
  → REPRESENTATION_BUILT
  → CAPABILITY_INDEXED
  → ADMITTED
```

终态包括：

```text
UNSUPPORTED
INVALID
CRS_UNRESOLVED
ENCODING_UNRESOLVED
GEOMETRY_INVALID
POLICY_REJECTED
```

运行故障与数据语义终态分开：parser/storage 暂态错误和预算中断产生 retryable gap，不伪装成
`ADMITTED`；provider 的 `PARTIAL`、`FAILED`、`ABANDONED` coverage 不得进入 current DATA。

每次恢复都创建新 attempt，并把旧 receipt/gap 作为 parent lineage；不得原地修改旧产品。

## 6. 解析与预算

### 6.1 矢量

`upload.parse_vector_file_bytes()` 支持 GeoJSON、Shapefile/ZIP、GPKG/GDB、KML/GML 的受控
解析。解析后只产生 lossless GeoJSON envelope 和 source locator metadata：

```text
__source_layer
__source_record_id
__source_layer_feature_index
__source_crs
```

它不把 BSM、DLBM、固定字段或固定图层名变成 DATA schema 前置条件。

### 6.2 栅格

`parse_raster_file_bytes()` 只解析 raster metadata：CRS、width、height、band count、bounds、
transform 和 nodata 描述。DEM 不被拆成伪造的 vector feature；没有明确空间 CRS 时进入
`CRS_UNRESOLVED`。

### 6.3 文档和表格

Markdown 直接进入文本 representation。其他文档和表格在 upload 中通过 MinerU 形成 Markdown
文本，同时表格保留为 `TableResource`。生产 upload 显式使用 `allow_fallback=False`；解析失败
产生 failure/gap，不使用 MarkItDown/Docling/PDF fallback 把失败变成成功。

### 6.4 budgets

上传 byte、文本字符、表格行数、feature 数和 provider request/record/zoom 均有上限。预算超限
只产生 quarantine/gap，并保留 observed budget state；不得静默截断成功。

## 7. 时态角色准入

`source_admission.py` 负责区分：

| role | 行为 |
|---|---|
| `current_evidence` | 可以进入 current DATA |
| `planning_brief` / `planning_instruction` | control-only，不是 current 事实 |
| `reference_plan` | reference-only，不进入 current 事实 |
| `planned_output` | excluded，不能重新作为规划输入 |
| `unclassified` | quarantine |

文件名、图层名和业务字段只能作为 contradiction signal，不能独立证明 current。当前上传入口
调用 bounded async temporal classifier；分类结果必须受固定角色枚举、输入/输出长度、两轮
一致性和置信度门限约束。provider failure 或低置信度不会自动准入。

## 8. Generic Resource Catalog

文件：`backend/app/data/resource_catalog.py`

`DataResourceCatalog.from_records()` 接收通用 mapping、GeoJSON FeatureCollection、table 或
raster descriptor，构造以下 generic 对象：

```text
SourceDataset
SourceFeature
SpatialRepresentation
DataCapability
SourceAdmissionDecision
DataResourceCatalogSnapshot
```

每个 feature 使用 dataset/layer/source record/ordinal 组成稳定 identity。raw attributes 保持
不透明；geometry、CRS、transform、source feature digest 和 normalized digest 都可追踪。

### 8.1 CRS

DATA 只接受明确 CRS contract。GeoJSON CRS84 只能按规范化规则作为 EPSG:4326 等价声明；未知
CRS、BD09、GCJ02 或不完整转换链路不得静默按 WGS84 处理。统一坐标规则在
`backend/app/data/coordinate_contract.py`。

### 8.2 topology policy

当前 policy 是 `strict_geometry_type`：

```text
source Polygon      → repaired Polygon       allowed
source MultiPolygon → repaired MultiPolygon  allowed
source Polygon      → repaired MultiPolygon  rejected
source MultiPolygon → repaired Polygon       rejected
```

`make_valid` 只产生 normalized view，不覆盖 raw source。允许的修复必须同时满足：结果有效、
范围合法、exact geometry type 不变。每次修复写入 topology repair transform trace，包括：

- source/repaired type；
- source/repaired family；
- source/repaired parts；
- source/repaired area；
- area delta 和 relative area delta；
- `review_required`。

金田村 `landuse.geojson` 的第 343 个 0-based feature：MultiPolygon 仍为 MultiPolygon，parts
从 67 变为 50，面积相对变化约 -1.4464%，所以可发布 normalized view 但必须人工复核。
`ecological_protection.geojson` 的修复发生 MultiPolygon→Polygon 类型变化，严格 policy 下为
`GEOMETRY_INVALID`。

### 8.3 catalog artifact slimming

四个 component product 独立保存正文：

```text
SourceSnapshotArtifact        raw/source metadata and native content
NormalizedResourceArtifact    normalized geometry/value view
RepresentationSnapshotArtifact representation lineage and spatial form
CapabilityIndexArtifact       executable read/query capability index
```

`DataResourceCatalogIndexSnapshot` 只保存 refs、identity、digest、decision 和 capability index，
不复制 raw geometry、normalized geometry 或 raw attributes。运行时 `DataResourceCatalogSnapshot`
可以被 WM 用作只读 projection 输入，但 catalog pointer 本身保持轻量。

## 9. BoundaryScopeArtifact

文件：`backend/app/data/boundary_scope.py`

边界 scope 只能来自：

1. 已准入的 `boundary.geojson` Polygon/MultiPolygon representation；或
2. 已显式 polygonize、单独准入并带 lineage 的行政界线 polygon representation。

任意行政 MultiLineString 不会被猜测成村界。artifact 携带：

```text
scope_ref
source_snapshot_ref
dataset_ref
source_feature_ref
representation_ref
source_digest
boundary_digest
query_geometry_digest
normalized_crs = EPSG:4326
```

三家地图 collector 只接收 `boundary_ref + normalized boundary geometry`。生产代码不读取固定
`data/gis/jintian/current/boundary.geojson` 来决定 query scope。

## 10. Remote admission 和 driver 协议

文件：`backend/app/contracts/data/remote_admission_contracts.py`

远程来源 contract 支持：

```text
api_vector / wfs / mapserver / wmts / remote_raster
```

声明必须包含 HTTPS allowlist endpoint、provider、layer、boundary/query digests、CRS contract、
capability、limits 和安全 auth ref。receipt 的 `network_contacted` 必须是 false。

协议边界是封闭的：

- `ApiVectorDriver(protocol=mapserver_rest)` 只执行 MapServer；
- `ApiVectorDriver(protocol=wfs)` 只执行 WFS；
- MapServer 失败不转 WFS；
- 不把 WMS URL 作为 vector success；
- WMTS 只执行 WMTS；
- remote raster 只执行 remote raster declaration；
- 没有 admitted receipt 的 driver fetch 直接失败。

## 11. Provider run 写入和 recovery

文件：`backend/app/data/catalog/provider_run_lease.py`

每一个 `<provider>/<stage>/<run>` 使用 `ProviderRunLeaseStore`：

1. 以独占 lock 保护 lease read-modify-write；
2. lease 过期后重新取得更大的 fencing token；
3. 每次 request、row write 和 finalize 前执行 `assert_writer`；
4. normalized JSONL 和 manifest 先写临时文件、fsync，再 atomic replace；
5. crash 后由 `recover()` 写入 `ABANDONED` recovery marker；
6. 旧 owner/token 无法覆盖新 writer 的结果。

manifest 至少包含：

```text
run_ref
provider
stage
fencing_token
boundary_ref
boundary_digest
query_geometry_digest
crs_contract
record_count
normalized_checksum
coverage_status
published
```

只有 `COMPLETE` 才能作为完整 provider observation；`PARTIAL`、`FAILED`、`ABANDONED` 只能保留
为诊断或 Evidence coverage 状态。

## 12. Cache 读取边界

`external_observation_cache.py` 只从 `data/cache/map_observations` 读取带 manifest 的结果，
校验 provider、stage、scope、时间、坐标契约、状态和 coverage。它不修改 `DataResourceCatalog`
或 local geometry。

Evidence 可以通过 `cached_map_retriever` 读取 advisory observation；不能把它升级为 current
DATA。WM 不直接使用地图 cache 建立本地事实图。

## 13. WM / Evidence / Planning Ground 消费

### 13.1 WM

`context_runtime.manager.build_planning_context()` 接收 normalized DATA catalog，调用
`project_source_catalog()` 建立 DATA-backed World Model。当前 production mode 固定为
`v2_only`。WM 使用 source/representation/capability lineage 和 dependency digest，不要求
旧 session Bundle。

### 13.2 Evidence

文件：`backend/app/infrastructure/evidence_runtime/retrievers/data_catalog_retriever.py`

retriever 返回 bounded source-feature facts，包括 source feature ref、dataset/layer、snapshot
ref、digest、geometry kind、authority 和 spatial granularity；不返回未经限制的 geometry body。
Evidence 的 source reference 以 `data:` 开头，geometry authority 为
`data_resource_catalog`。

### 13.3 Planning Ground

Planning Ground 只读取带 resource/representation/CRS/capability lineage 的 DATA/WM/Evidence
结果。缺少 DATA catalog、scope、representation 或 capability 时必须产生 gap，不能用空集合伪造
可执行候选。

## 14. DATA dependency graph 和 DataChangeSet

文件：`backend/app/modules/data/invalidation.py`。

DATA 只构造 DATA-owned dependency graph，不把 WM、Evidence 或 Ground 作为 DATA 节点：

```text
data:catalog
  → data:source:*
  → data:normalized:*
  → data:representation:*
  → data:capability:*
```

`plan_data_change_set(previous, current)` 比较 DATA 节点的 identity、digest 和依赖边，并发布
不可变 `DataChangeSet`。它可以在 DATA 子图内计算受影响的 normalized、representation 和
capability 节点，但不决定任何下游 row 是否 stale。

`DataChangeSet` 至少包含：

```text
previous_graph_digest
current_graph_digest
changed_nodes
affected_data_nodes
conservative
reason_codes
```

DATA 不再提供 `apply_data_dependency_invalidation()`，也不导入 WM context cache、Evidence
retrieval cache 或 Ground runtime。统一 Dependency Runtime 未来消费 `DataChangeSet`，再按
WM/Evidence/GROUND 自己的 dependency/subgraph index 决定精确失效范围。这样 DATA 与下游只有一
个失效传播 owner，immutable CAS 产品仍然保留用于 replay 和审计。

## 15. 生产验收合同

文件：

- `backend/app/contracts/data/production_acceptance_contracts.py`；
- `backend/app/modules/data/production_acceptance.py`；
- `scripts/acceptance/data_production_acceptance.py`；
- `docs/design/DATA_PRODUCTION_RUNBOOK.md`。

默认门限：

```text
admission ≤ 2s
context bootstrap ≤ 10s
Evidence retrieval ≤ 3s
RPO ≤ 15min
RTO ≤ 30min
```

静态 gate 检查：

- secret-like literal；
- repository/path permission；
- 删除的 DATA 模块；
- output cache 和旧 `inputs/bundle` 目录；
- active import boundary。

动态本地 gate 是全量 pytest；发布环境仍需执行真实 provider coverage、Windows ACL、备份恢复
和实际 SLO/RPO/RTO 测量。

## 16. 验收证据

### Runtime-verified

当前已通过：

- `python -m pytest tests -q`：全量测试；
- `python -m compileall -q backend/app scripts tests`；
- `git diff --check`；
- `python scripts/acceptance/data_production_acceptance.py --root .`；
- Jintian upload → admission → BoundaryScope → ProviderAcquisitionPlan → context → WM → Evidence → replay/stale parent/DataChangeSet 测试；
- provider lease/fencing/atomic writer/crash recovery 测试；
- 严格 topology policy 和 landuse feature 343 audit 测试；
- 旧 DATA 模块、旧 output cache、旧 Bundle input 物理缺失测试。

### Documented but environment-dependent

- AMap/Tencent/Tianditu 在线 provider 的真实覆盖率；
- WFS/MapServer/WMTS/remote raster 真实服务响应；
- 发布主机 NTFS ACL；
- 跨主机或灾备环境的 CAS/SQLite restore；
- 线上 SLO、RPO、RTO 实测。

## 17. 物理删除边界

已经删除的 DATA 历史实现包括：

- `backend/app/data/ingestion/ingest.py`；
- `backend/app/data/ingestion/adapters/`；
- `backend/app/data/ingestion/providers/poi.py`；
- 三家 provider 的 `anchor_service.py`；
- `backend/app/data/ingestion/gazetteer.py`；
- `backend/app/data/ingestion/encoding_detector.py`；
- `backend/app/data/catalog/admin_code_loader.py`；
- `backend/app/data/model/location_parser.py`；
- 旧 Bundle assembly/store/retriever/session KG/external anchor 模块和旧 runner。

不能把仍被更高层规划 API 使用的 `EvidenceBundle` response container、规划历史字段名或
非-DATA 的业务校验一次性宣称为 DATA 已删除；它们不是当前 DATA 写入/读取入口。DATA 的
删除边界是：凡无生产调用且会提供旧兼容语义的 DATA 实现，物理删除；凡仍有明确上层调用者的
非-DATA 契约，必须先完成独立迁移再删除。

## 18. 当前结论

当前 DATA 已是精简的 generic admission/catalog/product 层：

```text
声明 → 准入 → 规范化 → 表示 → capability → immutable catalog → 受控消费
```

它不再以旧 Bundle、typed ingest、provider anchor、固定 boundary 或 output cache 为隐含前提。
本地测试和 Jintian E2E 证明 WM 与 Evidence 能消费同一 DATA 产品且不修改本地 geometry。
真实发布前唯一未闭合的证据是外部服务在线覆盖、部署 ACL、灾备 restore 和线上延迟/恢复指标，
这些必须在发布环境实测，不能通过恢复旧兼容路径解决。
