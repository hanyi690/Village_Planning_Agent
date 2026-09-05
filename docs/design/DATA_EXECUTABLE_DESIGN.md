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

上传准入的参数契约必须保持单一且最小：

```text
process_uploaded_file(..., layer_ref="", boundary_scope_mode="")
  → assess_uploaded_source_admission(
       input_role, category, filename, parsed_text, gis_data,
       gis_data_type, parse_status, temporal_llm_enabled
    )
  → DataAdmissionRequest(source_kind="upload", source_ref=...)
  → DataAdmissionFacade.admit()
```

`assess_uploaded_source_admission()` 是上传专用的异步准入入口，不接受底层
`assess_source_admission()` 的 `source` 参数；它在内部以 `source="upload"` 调用通用评估器。
因此上游不得向上传专用入口重复传入 `source`，也不得通过给专用签名添加无效的兼容参数来掩盖
调用方与定义方的契约漂移。`source_kind` 和带内容 digest 的 `source_ref` 在随后的
`DataAdmissionRequest` 中表达来源，不能由文件名推断。

`process_uploaded_file()` 的 `layer_ref` 和 `boundary_scope_mode` 是可选但显式的调用方声明。
它们分别用于稳定的资源分组和 BoundaryScope 构造；未声明时，矢量资源仍可作为无图层名的
generic feature catalog 准入，但不会被猜成 boundary 或其他业务层。文件名只参与安全的
basename/扩展名解析和规划成果冲突信号，不能决定 `layer_ref`、`geometry_kind` 或时态角色。
因此旧的 `infer_data_type_from_filename` 兼容模块已删除，session reload 也不再从文件名或
属性字段重新推断图层。

HTTP multipart 的 `create-session` 适配器使用同一规则：`village_data_layer_refs` 是与
`village_data_files` 按序对应的显式字符串数组；`boundary_scope_file_index` 显式选择哪一个
上传文件作为范围来源，`boundary_scope_mode` 只允许已登记的范围模式。没有这些声明时，
文件仍可进入 generic catalog，但不会生成 BoundaryScope。数组越界、范围索引越界或模式不在
闭集内会在 transport/application boundary 直接拒绝。

准入判断还必须保持几个相互独立的维度：可读性（解析是否成功）、空间有效性（CRS、几何类型、
拓扑和范围）、时态角色（current/control/reference/planned）以及覆盖完整性。文件名、图层名和
业务字段只能作为规划成果冲突信号，不能证明资源是 current，也不能因为字段命名不理想就阻断
一个可读取的资源。局部几何问题应按 topology policy 形成 normalized view 和 quarantine/gap
记录；只有边界、CRS 无法解析、无法建立可执行 representation 等核心问题才提升为资源级阻断。

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
统一入口默认使用 bounded 行政 profile：AMap 扩展 polygon/采样和腾讯边界网格 nearby 不自动开启，
必须显式传入 `--expand-admin` 才执行高请求量覆盖。无论 bounded 还是 expanded，明确的 provider
capability rejection 都在本次 run 内触发 operation 级 circuit breaker，后续请求写入
`missing_capability` 审计行而不再发起网络调用；这只是减少确定性失败等待，不改变 coverage 语义。
provider writer、collector lease 和 published manifest 使用同一个
`data/cache/map_observations` 根，manifest 合并保留 `coverage_status`、`published`、fencing token、
digest 和 normalized record count，避免“文件已写出但 cache loader 无法识别”的假成功。
其中 `normalized_all.jsonl` 的唯一发布内容是逐条 ExternalObservation-compatible 的
canonical row：必须已经包含 scope bucket、行政匹配、坐标契约和可追溯的 source/request ref。
采集请求包装行只允许写入 `normalized.jsonl` audit index，不能交给
`ProviderObservationWriter` 发布，也不能由 DATA loader 根据 provider 私有响应再推断字段。
因此旧 run 若把 `{records: <provider response>, raw_response: ...}` 包装行写入
`normalized_all.jsonl`，会被 fail-closed 视为不可消费；应保留原始响应用于审计，并通过正式
normalization/publish 路径生成新 run，不得放宽 loader 兼容旧格式。
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

### 4.2 session catalog reload

文件：`backend/app/data/catalog/session_resource_catalog.py`

session bootstrap 只从上传行中的 immutable artifact refs 重载
`DataResourceCatalogIndexSnapshot` 及其四类 component products。缺少 receipt、catalog
pointer 或任一 component 时，该 source 进入 quarantine/gap，不能退回 YAML、村名目录、
旧 Bundle 或临时 parser。`check_local_admission_boundary` 只负责本地声明组合的 capability
gate；它不发现 source，也不联系网络。

### 4.3 session catalog projection

文件：`backend/app/api/v1/routes/source_layers.py`

`GET /api/v1/source-layers` 是 DATA catalog 的只读表现层，不是 source
discovery 入口。调用方必须提供 `session_id`；服务只从该 session 已准入的
`DataResourceCatalog` 读取 `normalized_geometry`、`normalized_geometry_kind`、
原始属性和 lineage，并按 `(dataset_ref, layer_ref)` 分组返回。它不读取
`sources.yaml`、固定村域目录、固定文件名，也不根据村名推断或补齐数据。

只有 `point`、`line`、`polygon` 三类已经具备可执行 WGS84 表示的资源进入地图
投影；`collection`、`opaque` 等只读表示保留在 DATA/WM/Evidence 的能力与审计
链路中，但不会被转换成一个“看起来可执行”的图层。栅格只返回不暴露本地路径的
manifest，实际读取仍由 session catalog 和地形能力边界控制。

前端生成类型必须由 `backend/scripts/generate_api_contracts.py` 重新生成，不能
手工恢复 `village_name` 默认值或 `dem/dom` 固定枚举。这样 WM、Evidence 和地图
展示共同消费同一个已准入 catalog，而不会在 API 层重新解释输入。

### 4.4 ingestion public surface

文件：`backend/app/data/ingestion/__init__.py`

当前只导出：

- `process_uploaded_file`；
- `DataResult` / `DataSourceMetadata`；
- `DataSourceDriver` / `DriverRegistry`；
- `Connection` / `ConnectionRegistry`；
- provider transport primitives；不存在 source registry re-export。

旧 ingest.py、typed adapters、POI 聚合、provider anchor service、data-side gazetteer、
独立 encoding detector、admin code loader 和 location parser 已物理删除，不能通过 import 或
re-export 重新出现。

DATA ingestion 不再承载 L3 空间需求编译器。原先位于
`backend/app/data/ingestion/compiler/` 的历史实现已经物理删除；当前仍需要的 typed
空间引用映射归属 `backend/app/modules/target_projection/spatial_reference_mapper.py`，
由 TARGET_PROJECTION 调用并保持其公开映射函数签名。DATA 只提供已准入的
source-feature/resource 引用，不重新解释规划意图，也不提供该模块的兼容导入。

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

当前 policy 是 `surface_family_compatible`。GeoJSON 的 exact geometry type 仍然保留，但 DATA
允许同一 homogeneous surface family 内的适配：

```text
source Polygon      → repaired Polygon       allowed
source MultiPolygon → repaired MultiPolygon  allowed
source Polygon      → repaired MultiPolygon  allowed with audit
source MultiPolygon → repaired Polygon       allowed with audit
```

这里的“允许”不是声称 exact type 无损，而是表示 normalized representation 仍然是有效的
二维 polygonal surface，可以执行相同的空间能力。原始 geometry、normalized geometry 和类型
变化必须同时可追踪。每次修复写入 topology repair transform trace，包括：

- source/repaired exact type；
- source/repaired family；
- source/repaired parts；
- source/repaired area；
- area delta 和 relative area delta；
- `geometry_type_changed`、`part_count_changed`；
- `review_required`。

允许的同族修复必须同时满足：结果非空、有效、与源 geometry family 相同、范围合法、CRS 已明确。
无法保持既有 point/line/polygon family 的结果不再强行标成原 family。若修复结果是完整、有效
的 `GeometryCollection`，DATA 将其作为 `collection` normalized representation 保留全部组件，
并只发布 `read` capability；它可以进入 WM/Evidence 的来源和审计视图，但不能执行 `within`、
`intersect`、`buffer`、`union`、边界 scope 或规划几何操作。修复失败、空结果、非法范围、无法
解析的 CRS 以及不能完整保留的结果仍然进入 `GEOMETRY_INVALID`；系统不能为了获得 polygon 而
静默丢弃 LineString/Point 组件。GeoJSON 的 type 枚举不被扩展，`collection` 是 DATA 内部
representation kind，不是新的 GeoJSON `type`。

因此，“扩展适配类型”只扩展消费能力的闭集，不扩大执行语义：

```text
raw Polygon/MultiPolygon
    → normalized Polygon/MultiPolygon  → spatial capabilities
    → normalized GeometryCollection     → read-only collection capability
    → incomplete/lower-dimensional loss → GEOMETRY_INVALID
```

对于解析器能够保留、但当前 Shapely/CRS 执行后端不能解释的未知原生 geometry type，DATA
使用内部 `opaque` geometry kind。它不是新的 GeoJSON type，也不是把未知对象猜成 Polygon、
Line 或 Point；其 raw geometry、原生 type、属性、digest 和 source lineage 原样保留，
representation status 为 `read_only`，仅发布 `read` capability。WM 只登记对应的
`SourceRecord` 来源节点，Evidence 可以返回 bounded source-feature fact 和 raw geometry
引用；`select`、`ground`、`execute`、BoundaryScope 以及任何需要 normalized geometry 的
空间操作都必须拒绝该 representation。已知的 Point/Line/Polygon/MultiPatch/Collection
几何在归一化失败时仍然进入 `GEOMETRY_INVALID`，不能借用 `opaque` 绕过质量门。

`SourceFeature.geometry_kind` 保留源 geometry family，`normalized_geometry_kind` 表示规范化
representation 的实际 family；WM/Evidence 读取 representation kind，不能把两者混为一谈。
未知但结构完整的原生 geometry 使用 `geometry_kind=opaque`、
`normalized_geometry_kind=unknown`；这是“可读但不可执行”的明确状态，不是缺少分类的
`unknown` 默认值。

该边界与规范语义一致：GeoJSON 的固定 geometry type 集合以及 Polygon/MultiPolygon 的坐标
结构见 [RFC 7946](https://www.rfc-editor.org/rfc/rfc7946.html)；Polygon 是一个 Surface，
MultiPolygon 是由 Polygon 组成的 MultiSurface，见 [OGC Simple Feature Access Part 1](https://docs.ogc.org/is/06-103r3/06-103r3.pdf)。
实现使用 [Shapely make_valid](https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html)
进行确定性修复，但不把修复结果当作唯一真相：不同 make-valid 方法可能产生不同维度的结果，
因此最终仍以同族、有效、非空、范围和审计条件决定是否准入。GDAL 对有效性和
`linework`/`structure` 差异的说明见 [Geometry validity](https://gdal.org/en/stable/user/geometry_validity.html)
与 [GDAL make-valid](https://gdal.org/en/stable/programs/gdal_vector_make_valid.html)。

金田村 `landuse.geojson` 的第 343 个 0-based feature：MultiPolygon 仍为 MultiPolygon，parts
从 67 变为 50，面积相对变化约 -1.4464%，所以可发布 normalized view 但必须人工复核。
`landuse.geojson` 的第 22、258 个 feature，以及 `ecological_protection.geojson` 的第 4 个
feature，修复结果为 Polygon；它们属于同一 surface family，可以发布 normalized view，但
必须在 audit 中标记 exact type changed，并由下游按 normalized representation 消费，不能把
这解释为源文件类型未发生变化。

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
5. crash 后由 `recover()` 将 lease 原子标记为 `EXPIRED` 并写入 `ABANDONED` recovery marker；
6. 旧 owner/token 无法覆盖新 writer 的结果。

运行维护可调用 `ProviderRunLeaseStore.reconcile_expired()` 对 lease 目录进行一次幂等
扫描。它只处理 expiry 已到的 `ACTIVE` lease，不删除 lease 审计文件，不改变 `RELEASED`
或仍然有效的 lease；因此可以安全地作为 worker 启动检查、定时恢复任务或人工恢复命令的
公共实现，而不是每个 provider 各自维护一套 crash recovery。

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

`SpatialWorkspace` 的 `points`、`lines`、`polygons` 和 `query_resources()` 也按
`normalized_geometry_kind` 建立空间视图；只有 normalized kind 为 point/line/polygon 的资源才会
进入对应可执行空间集合。源 `geometry_kind` 仍用于 source/audit lineage。因拓扑修复得到的
完整 `GeometryCollection` 可以通过 `iter_source_features()` 和 Evidence 读取，但不会被放入
polygon/current-parcels 视图，也不会获得 polygon spatial capability。

source semantic runtime 和 Planning Ground 遵循同一规则：source semantic 的分组、候选几何
类型和 grounding 的 `feature_kind` 均以 normalized representation 为准；当 normalized kind 为
`collection`、`unknown` 或其他不可执行类型时，资源只能作为来源/审计事实读取，不能进入点、线、
面语义分组，也不能生成可执行 grounding candidate。`NormalizedResourceArtifact` 显式保存
`normalized_geometry_kind`，因此独立产品重放不依赖 `SourceFeature.model_post_init()` 的隐式推断。

### 13.2 Evidence

文件：`backend/app/infrastructure/evidence_runtime/retrievers/data_catalog_retriever.py`

retriever 返回 bounded source-feature facts，包括 source feature ref、dataset/layer、snapshot
ref、digest、geometry kind、authority 和 spatial granularity；不返回未经限制的 geometry body。
Evidence 的 source reference 以 `data:` 开头，geometry authority 为
`data_resource_catalog`。

Evidence 的 `KG` route 也只读取 Context Runtime 注入的
`CurrentWorldQueryPort`，其来源根为 `world_model:{session_id}`；它提供 WM 的 entity、part、
representation lineage 和 bounded relation 摘要，不再访问旧 `KGManager`、session Bundle、
BSM-specific query 或 assertion/planned graph。DATA catalog route 与 current-world route
可以同时存在，但二者都指向同一 immutable DATA snapshot，不能形成第二套几何或身份权威。

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

### 15.1 CUDA 加速边界

当前实现未启用 CUDA：仓库没有 `cupy`、`cudf` 或 `cuspatial` 运行依赖，且本地准入、
规范化、WM 投影和 Evidence 检索均走 CPU 路径。即使部署主机具备 NVIDIA GPU，也不能把
“检测到 CUDA”解释为 DATA 已经完成 GPU 加速。

CUDA 只允许作为可选的批量计算后端，不能改变 DATA 的权威语义或写入边界：

| 工作 | CUDA 适配结论 | 原因 |
| --- | --- | --- |
| GeoJSON/Shapefile 解码、字段解析、哈希、CAS/SQLite 写入 | 不接入 | 主要受 I/O、Python 对象和事务约束，GPU 传输开销不能改善权威写入语义。 |
| CRS 解析和权威坐标规范化 | 默认 CPU | 当前 `pyproj` 负责显式 CRS contract；不得用近似 GPU 公式替代 fail-closed 规则。 |
| `Shapely/GEOS make_valid` 拓扑修复 | 不接入 | 修复结果可能拆分部件、改变 geometry family 或降维；当前审计和拒绝策略依赖 GEOS 语义。 |
| 大批量 point-in-polygon、空间连接、候选四叉树、点到线距离 | 可选 CUDA | RAPIDS cuSpatial 正好覆盖这些批量空间运算，但结果必须回到 canonical CPU 表示并通过不变量校验。 |
| DEM 窗口数组运算、坡度/阴影/栅格分类、批量重采样 | 可选 CUDA | CuPy 可承载数值数组；当前 DATA 只读取 DEM descriptor/统计，尚没有值得 GPU 化的重型栅格算子。 |
| Provider HTTP、限流、lease/fencing、crash recovery | 不接入 | 瓶颈是网络和持久化一致性，不是数值计算。 |
| WM RDF/CAS projection、Evidence bounded retrieval | 不接入 | 主要是图构造、身份/摘要、字符串和受限查询，GPU 不会提供稳定收益。 |

因此，未来如需接入，必须新增独立的 optional accelerator port，而不是在现有
`DataAdmissionFacade`、remote admission contract 或 `BoundaryScopeArtifact` 中混入 CUDA 分支。该 port
至少满足以下合同：

```text
canonical normalized input (CPU, explicit CRS)
    → batch accelerator (GPU optional)
    → host result
    → deterministic invariant check
    → immutable product / advisory index
```

GPU 后端不得执行 topology repair、推断 CRS、产生 feature identity、修改 source digest，
也不得在校验失败时改变 admission status。CUDA 不可用、显存不足、kernel/provider 失败或
结果不通过校验时，必须回退 CPU；回退不能改变 geometry、feature ref、CRS、coverage 或
Evidence sufficiency。CPU/GPU 只能共享同一 canonical input 和结果规范化规则，性能差异
应写入 execution trace，不能写入 source/catalog digest。

当前金田村 P0 规模约为 1,662 个空间要素，另有一个 DEM 和一份现状报告。这个规模下，
解析、GEOS 修复、CAS、WM 图投影和 Evidence 检索的固定开销通常高于一次 GPU 数据搬运；
当前 acceptance 不应依赖 CUDA。只有在真实 provider observation 或栅格批处理达到基准
阈值后，才允许按 benchmark 启用 GPU，并保留同一批输入的 CPU 对照验收。推荐的候选库是
[RAPIDS cuSpatial](https://docs.rapids.ai/api/cuspatial/stable/) 的空间连接/索引能力和
[CuPy](https://docs.cupy.dev/en/stable/overview.html) 的 GPU 数组能力；二者均为可选部署
能力，不应成为无 GPU 环境的 DATA 必需依赖。

本轮 CPU 优化的实测记录（同一工作树、同一真实输入，耗时会受文件系统和 RDFLib 状态
影响）如下：

```text
完整 pytest 回归：约 32--44 s；完整 Jintian DATA→WM→Evidence 验收：约 11--16 s；
单独 10 个 GeoJSON + DEM + Markdown admission：约 7--10 s
```

主要成本仍来自首轮 import、Pydantic 物化、Shapely/PROJ 几何处理和 CAS 文件系统写入。
当前实现复用一次 current-world catalog、按 resource 建 DATA dependency index、一次性
合并多个 catalog、`include_reports=false` 时不加载文档数据库，以及避免已 canonical
catalog 在 `DataApplication.run()` 中再次投影。WM 的单次冷启动通常约 9--11 s，其中约 3--4 s
是 RDF projection、约 4–6 s 是不可变 TriG/CAS 写入；当前 TriG 写出已改为按 named graph
分组、按完整 N3 term 排序的直接 writer，避免 RDFLib Turtle subject-ordering 的额外索引，
但仍由 RDFLib parser 负责回读验收。它只改变序列化布局，不改变 RDF term、graph、digest 或
WM/Evidence 消费契约；这部分仍需在更大生产图上继续 benchmark，不能用 CUDA 宣称已经解决。

在上述基础上，当前实现还做了三项不改变契约的热路径收敛：

- CAS `store_artifact()` 先生成一次 JSON-safe payload，同时复用这次结果生成 canonical JSON
  和 semantic digest，避免重复执行 Pydantic/model conversion。四类无嵌套 volatile timestamp
  的 DATA 产品直接复用 canonical blob digest；stage/gate 和 source product 仍按原规则过滤
  `created_at`、`artifact_id`、provenance timestamp 和 execution-result task id。
- WM 暴露的 road retry port 改为惰性构建。context bootstrap 仍然提供同一个 callable port，
  但只有真正发生 road retry 时才扫描 RDF 图建立 retry index；DATA、WM current view 和
  Evidence 的启动路径不再为未使用的 retry 预付索引成本。
- source catalog 的连接线 identity 计算先为每条线预计算 accepted semantic token，再用固定
  端点网格产生距离候选，最后仍用原来的精确平方距离阈值和 union-find 合并。因此优化只减少
  不可能相连的 pair，不改变“同一 accepted name 且端点相近”这一身份规则。
- WM source projection 对重复的 immutable RDF `Literal` 和 ontology predicate 做进程内复用，
  只减少 RDF term 构造与 namespace lookup，不共享可变 Graph、不改变任何三元组或 digest；
  acceptance 的单次耗时仍受 Windows 文件系统和 RDFLib 状态影响，不能据此宣称固定百分比收益。
- WM source projection 在一个不可变 projection transaction 内先收集 source/world 三元组，
  最后使用 RDFLib store 的 `addN()` 批量发布；这只减少逐条 `Graph.add()` 的 store bookkeeping，
  不改变三元组集合、named graph、CAS digest 或任何 WM/Evidence 查询语义。异常发生在 flush
  前时不会把半成品图发布到调用方。
- 上传文件的纯本地解析（GeoJSON 审计、Shapely 几何检查、栅格/表格解码和 MinerU 调用）在
  `process_uploaded_file()` 中通过 bounded async worker 执行；事件循环只负责流读取、bounded
  temporal-role classifier 和统一 admission。文件解析不会绕过 P0 budget、CRS、topology 或
  receipt 写入，因此并发上传不会改变准入结果。
- `DataAdmissionFacade.admit_many()` 只对相互独立的输入启用有界 worker 并发；每个输入仍独立
  生成 receipt、完整 lifecycle artifact 和 CAS lineage，返回顺序与请求顺序一致。真实多文件
  upload 在 CreateSession 中按最多 4 个任务并发调度，单文件 `admit()` 契约不变；并发不会
  合并 receipt、跳过 fencing/fsync 或改变任一输入的准入结果。
- 对已经完成过完整检查的 immutable catalog，`assert_current_world_catalog()` 按
  `snapshot.digest` 使用 64 项成功校验 LRU；失败结果不缓存，policy version 或 digest 变化
  会重新执行 fail-closed 校验。Evidence 的 DATA retriever 对同一 digest 建立最多 8 项的
  bounded 属性搜索索引，只缓存 feature 引用和折叠后的文本，不缓存 geometry，也不替代
  current-world admission。
- 对同一 `catalog.digest + schema_mapping fingerprint + graph mode` 的重复 WM context，
  `project_source_catalog()` 使用最多 2 项的进程内有界投影缓存。缓存只保存已构造的 RDF
  source/world 三元组和 projected count，不保存 raw geometry，也不替代 DATA catalog、CAS
  或 Evidence authority。首次投影完整执行；命中时只把同一不可变 RDF term 回放到当前 session
  的新 Graph。catalog digest、mapping fingerprint 或 split/single graph mode 任一变化都会
  失效；进程退出即清空，淘汰采用 LRU。缓存回放必须与完整投影通过三元组集合和 WM/Evidence
  消费回归，不能用缓存绕过 admission、CRS、topology 或 lineage 校验。
- 规范化函数对 `(source_crs, geometry digest)` 使用最多 8,192 项进程内 LRU，复用
  WGS84 校验/拓扑修复结果；已知 CRS 到 WGS84 的 PROJ Transformer 另使用最多 32 项缓存。
  这些缓存不持久化、不参与 source/catalog identity，也不会把 native geometry 写回或覆盖；
  cache miss 仍执行原有 CRS、bounds、Shapely validity、`make_valid` 和 geometry-family
  policy。WM 的 coordinate-support anchor 按 `source_feature_digest + CRS` 使用最多 8,192
  项只读缓存，命中只复用近邻支撑索引的 anchor，不改变 WorldEntity identity 或 geometry
  authority。
- DATA dependency graph 的 normalized 节点直接复用已覆盖 native/normalized geometry、
  CRS transform 和 topology audit 的 `SourceFeature.source_feature_digest`，不再为每个
  feature 重新 JSON 序列化完整坐标树；因此 invalidation 仍能捕获 normalized geometry
  或 CRS/topology 变化，同时保留 source、representation、capability 的精确依赖边。
- `current_world_snapshot()` 完成中心准入过滤后会把结果 digest 记入 bounded validation LRU，
  使 Context Runtime 和 WM 紧接着执行的 fail-closed guard 只校验一次同一 immutable snapshot；
  digest、policy version 变化或 LRU 淘汰仍会重新校验，失败结果不会被缓存。
- 几何归一化缓存键使用运行时依赖 `orjson` 对 GeoJSON geometry 做高速排序编码；它只用于
  8,192 项进程内缓存寻址，正式的 source feature/catalog digest 仍使用既有 canonical JSON
  算法，不能把运行时编码差异传播到身份、CAS 或 replay。缺少 `orjson` 时自动回退到标准库
  JSON，结果语义不变。
- road network snapshot 对具有 DATA `source_feature_digest` 的输入按 feature digest、CRS、
  impedance、snap tolerance 和其它网络参数使用最多 32 项进程内缓存。命中只复用不可变
  `NetworkGraphSnapshot` 的只读路由结构；没有 DATA digest 的临时 mapping 不进入缓存，避免
  为临时输入引入隐含身份。网络算法、端点吸附和路线结果不因缓存改变。

这些优化只能减少重复序列化、未使用索引和明显不可能的线段比较；它们不跳过 geometry
normalization、`make_valid`、CRS fail-closed、DATA admission、CAS fencing、WM digest 或
Evidence provenance。focused Jintian acceptance 的历史 warm run 约为 9.2--9.6 s，最近
观测约为 7.7--8.2 s；这是单机观测值，不是发布 SLO，也不代表冷启动上界。发布环境仍需分别记录
admission、catalog merge、WM projection、CAS 和 Evidence 各段耗时。

随后对 WM 冷启动又合并了 TriG 序列化和 graph digest 的一次遍历：同一批稳定 N3 term
同时生成排序后的 named-graph TriG 和 `sha256-sorted-rdflib-n3-quads-v2-length-prefixed`
digest，且 CAS 写入复用已生成的 TriG bytes。digest 行使用长度前缀，避免每个四元组重复
调用 `json.dumps`；该优化只改变摘要算法版本，不改变 RDF 内容。相邻两次真实 Windows
acceptance 的完整 P0 测试历史约 9.2--9.6 s，最近本轮约 7.7--8.2 s（单机 warm run，
非 SLO）；与旧记录相比只能作为当前优化后的观测，不能直接外推到不同 CPU、磁盘、Python
或 RDFLib 版本。
最新函数级 profile 显示，普通 acceptance 中剩余的主要固定成本在
`project_source_catalog()` 的 RDF projection；instrumented profile 约 24.6 s，另有
`DataResourceCatalog.from_records()` 的重复资源建立成本。该 profile 会被解释为热点定位，
不直接作为线上耗时基线；后续应优先研究 source projection 的可验证分层缓存/批量写入，
并保留 `NormalizedSourceClaim`、source feature lineage、geometry authority 和 digest，
不能通过删除来源声明或绕过 topology/CRS 校验换取表面加速。

## 16. 验收证据

### Runtime-verified

当前已通过：

- `python -m pytest tests -q`：全量测试；
- `python -m compileall -q backend/app scripts tests`；
- `git diff --check`；
- `python scripts/acceptance/data_production_acceptance.py --root .`；
- Jintian upload → admission → BoundaryScope → ProviderAcquisitionPlan → context → WM → Evidence → replay/stale parent/DataChangeSet 测试；
- provider lease/fencing/atomic writer/crash recovery 测试；
- surface-family topology policy、landuse feature 343 面积/parts audit 和低维结果拒绝测试；
- 旧 DATA 模块、旧 output cache、旧 Bundle input 物理缺失测试。

### Jintian 本地真实输入结果

使用 `data/gis/jintian/current/` 下的 10 个 GeoJSON、`terrain/dem.tif` 和
`docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md` 验证时：10 个矢量源、
DEM 和现状 Markdown 均可通过当前 `DataAdmissionFacade` 准入；`landuse` 的 5 个无效要素和
`ecological_protection` 的 1 个无效要素按 `surface_family_compatible` 形成可审计的 normalized
view。新增 acceptance 进一步证明 boundary + landuse 合并后的单一 catalog 可以被 WM bootstrap
和 Evidence `data_catalog_retriever` 消费，且消费前后的 DATA digest 不变。完整 P0 验收还覆盖
其余 8 个 GeoJSON、DEM 和现状报告；全部本地产品合并后，WM 的空间支持索引和 CAS projection
仍能完成，Evidence 可以分别按 `landuse` 和报告 layer ref 读取 source facts。空间邻近支持投影
写入 WM 当前 graph，但只作为支持关系，不改变 source-local identity。

完整验收还逐一查询 10 个 GeoJSON layer、DEM 和现状报告的 `layer_ref`，并校验 WM
`SourceRecord` 数量等于合并 catalog 的 feature 数量、WM source graph 包含全部声明层；因此
“可加载”与“已被 WM/Evidence 消费”分别有可执行的证据，而不是只用一个代表性图层推断全部输入。

这不等价于三家地图已经完整在线可用：以完整行政范围和当前 boundary bbox 重新加载时，
AMap、Tianditu、Tencent 的 provider snapshot 均为 `complete=false`。旧 AMap run 的
`normalized_all.jsonl` 原来是 request wrapper，已从保留的 raw response 离线重建一个
canonical run；当前 loader 可消费 AMap 93 条、Tencent 84 条带 provenance 的观测，Tianditu
当前 run 因记录落在梅州市外而为 0 条。三家 run 仍分别保持 `PARTIAL`/`PARTIAL`/`PARTIAL`
覆盖语义，不能合并宣称 COMPLETE，也不能把这些 advisory 观测升级为 current DATA。旧
wrapper run 未被覆盖，仍作为审计来源；loader 不增加 provider-specific 兼容解析。
在线 provider 的 COMPLETE 验收仍需单独完成；缺失、接口能力拒绝、WFS/请求失败和越界记录均
保持在 provider attempt/manifest 中，不由本地矢量、DEM 或报告准入结果代替。

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
