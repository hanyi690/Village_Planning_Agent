# DATA 可执行模块设计

> Status: CURRENT DATA-only scope; implementation PARTIAL
>
> 本文件定义 DATA 的可执行目标契约。它明确限制 P0 能力集合，不承诺任意 GIS、文件、字段、
> 图层、几何或 CRS 都能被正确处理。
>
> 2026-09-02 范围修正：本轮 MVP 只是一次可复现的测试/运行验收探针，不是新的业务模块，
> 也不推进 Cognition、World Model、Evidence、L1、L1-GROUND 或 L2。生产实现只到 DATA
> 读取并准入声明的文件。

## 1. Responsibility

DATA 将声明支持的原始输入转化为不可变 source snapshot、规范化记录、空间表示和
capability index，并在准入成功后发布可供 Cognition、Evidence 和 Planning Ground 读取的
resource catalog。DATA 只陈述来源与表示事实，不决定实体身份、规划意图或候选胜负。

DATA 禁止：

- 把文件名或字段名猜测升级为已接受业务语义；
- 在 CRS、编码或 geometry 不可验证时静默修复；
- 直接更新 current World Model；
- 将外部 observation point 冒充本地可执行 geometry；
- 对未声明 adapter/capability 返回空成功。

## 2. Inputs

输入是 <code>DataAdmissionRequest</code>：

~~~text
session_ref
source_ref
source_kind
content_ref / upload_ref
declared_media_type
declared_encoding optional
declared_crs optional
adapter_hint optional
expected_role optional
policy_context_ref
parent_catalog_snapshot_ref optional
~~~

P0 只接收 capability registry 明确声明的组合。准入前必须冻结字节内容 digest、adapter
版本和 policy 版本；缺少声明能力时输出 <code>DataGap</code>，不得进入解析器碰运气。

### 2.1 金田村 MVP 输入闭包

本项目的最小 MVP 输入不是单个边界文件。DATA 文件读取探针必须逐个读取并准入以下三个
本地输入平面；外源地图只作为独立的缓存清单/尝试记录进行盘点，不伪装成本地 DATA 文件，
也不在本轮拼装成下游输入。一次 fresh run 可以承载这些逐文件 admission，但不得新增一个
MVP 业务模块或固定的输入组合类：

| 输入平面 | 纳入文件/目录 | 角色与边界 |
|---|---|---|
| 现状矢量 | <code>data/gis/jintian/current/admin_boundary_line.geojson</code>、<code>annotation.geojson</code>、<code>boundary.geojson</code>、<code>construction_zone.geojson</code>、<code>ecological_protection.geojson</code>、<code>farmland_protection.geojson</code>、<code>geological_hazard_points.geojson</code>、<code>historical_protection.geojson</code>、<code>landuse.geojson</code>、<code>road.geojson</code> | current evidence；提供边界、地类、道路、保护范围、灾害点、注记和行政界线。每个要素必须保留原始文件引用、要素定位和几何表示引用。 |
| 现状地形 | <code>data/gis/jintian/terrain/dem.tif</code>；其原始数据包 <code>data/gis/广东DEM30M.zip</code> 作为 source package 记录 | terrain/raster evidence；用于高程、坡度或地形可用性相关能力。栅格 CRS、范围、分辨率和 nodata 未确认时必须形成 gap，不能按矢量成功处理。 |
| 现状文本 | <code>docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md</code> | current textual evidence；文本事实必须保留章节/段落 span，不能因文件名直接升级为 World Model 事实。 |
| 外源地图缓存 | <code>output/map_validation/amap/</code>、<code>output/map_validation/tianditu/</code>、<code>output/map_validation/tencent/</code> 下各阶段的 <code>manifest.json</code>、<code>normalized_all.jsonl</code>、<code>attempts.jsonl</code>、<code>requests.jsonl</code>、<code>raw_responses/</code> 和 <code>cache/</code> | cache inventory / Evidence 预留；盘点时必须保留 provider、stage、request/attempt 状态、采集时间、坐标契约、范围筛选和原始响应引用。它不进入本轮 DATA current catalog，也不得直接成为本地可执行 geometry。 |

外源缓存按 provider 独立记录：高德包含 <code>01_admin_scope</code> 与
<code>02_l1_place_names</code>，天地图包含同名两个阶段，腾讯当前仅有
<code>01_admin_scope</code> 且存在配额中断。缺失阶段要记录为
<code>NOT_ATTEMPTED</code> 或对应失败状态，不能当作“没有数据”。

以下内容不属于本次 MVP 的 current input：<code>data/gis/jintian/planned/</code>、规划文本、
规划图件、规划工程包以及由规划阶段生成的 planned output。<code>output/amap_validation/</code>
只有在经过统一缓存迁移并由统一 manifest 引用时才能作为 cache source，不能绕过统一
external-observation loader 直接读取旧格式。规划/设计资料如未来需要，只能进入显式
<code>reference_plan</code> 或 control 通道，不能进入 current catalog、current World Model
或 L1 现状事实。

### 2.2 本轮 MVP 的实现边界

MVP 的唯一运行目标是证明 DATA 能按声明读取文件并产生可重载的准入结果：

- 入口是 <code>DataAdmissionFacade.admit(DataAdmissionRequest)</code>，按文件逐个调用；不
  建立 <code>mvp_*</code> 生产模块，不建立金田村专用 bundle/composition 模块；
- 当前只读 GeoJSON、GeoTIFF/DEM 和 Markdown 现状报告。读取结果可以生成 DATA 自己的
  <code>DataResourceCatalog</code>、快照、receipt、gap 和 CAS 引用，但这只是 DATA 产品，
  不是 L1 或完整认知闭环的入口；
- 读取器只依赖声明的 media type、encoding、CRS、adapter 和 expected role。GeoJSON
  <code>properties</code> 作为不透明属性映射保留，不要求 BSM、DLBM、固定图层名、固定字段
  集合或固定输入领域类；
- <code>DataResourceCatalog</code> 是 DATA 的输出/持久化契约，不是文件读取前置条件。输入可
  以是文件路径或通用 mapping/record；不能因缺少某个业务字段或某个输入类实例而拒绝；
- 外源地图缓存只做 manifest/attempt/cache 的读取盘点并保留缺失、失败、配额耗尽等状态，
  不在本轮把 provider 结果送入 Cognition、Evidence enrichment、L1 或 L2；
- 规划文本、规划图件、规划工程包和 planned output 永远不作为本轮 DATA 输入。

## 3. Outputs

成功产品：

~~~text
SourceSnapshot
NormalizedResource
RepresentationSnapshot
CapabilityIndex
DataAdmissionReceipt(status=ADMITTED)
SessionResourceCatalogSnapshot
~~~

失败或未决产品：

~~~text
DataAdmissionReceipt(status=terminal_failure)
DataGap
DiagnosticArtifact
~~~

所有产品携带 source/content/adapter/schema/policy digest。<code>ADMITTED</code> 只表示当前声明
用途可消费，不表示数据对所有规划用途都适用。

## 4. Public Facade

唯一写入入口为 <code>DataAdmissionFacade.admit(request)</code>；读取通过
<code>ResourceCatalogPort</code> 和只读 snapshot ref。adapter、parser、normalizer、CRS 工具和
geometry validator 都是内部实现，不允许下游直接调用并绕过准入 receipt。

建议的 facade 操作：

~~~text
discover(request) -> DiscoveredSource
admit(request) -> DataAdmissionResult
load_catalog(snapshot_ref) -> SessionResourceCatalogSnapshot
query_capabilities(snapshot_ref, requirement) -> CapabilityMatchResult
resume(gap_ref, recovery_input) -> DataAdmissionResult
~~~

## 5. State Machine

主状态机：

~~~text
DISCOVERED
  → CLASSIFIED
  → PARSING
  → NORMALIZED
  → REPRESENTATION_BUILT
  → CAPABILITY_INDEXED
  → ADMITTED
~~~

任一步均可 fail closed 到以下终态：

~~~text
UNSUPPORTED
INVALID
CRS_UNRESOLVED
ENCODING_UNRESOLVED
GEOMETRY_INVALID
POLICY_REJECTED
~~~

恢复不是把终态原地改为成功，而是以旧 receipt 为父引用创建新 admission attempt。只有新
attempt 完整通过状态机后，才发布新 catalog snapshot。

## 6. Transactions

一个 admission attempt 的原子边界包含：source snapshot、normalized resource、
representation、capability index 和 receipt。内部产物可先写 staging CAS，但 catalog 指针只在
全部验证通过后一次提交。失败不能留下部分可见 resource，也不能覆盖上一个已准入版本。

同一 <code>session_ref + content_digest + adapter_version + policy_digest</code> 必须幂等。并发提交
使用父 catalog snapshot 的 compare-and-swap；父版本过期返回 stale parent 并重放准入发布，
不得合并未知中间状态。

## 7. Invariants

1. 原始 source snapshot 永不原地修改。
2. 每个 representation 必须回溯到 source snapshot 和 normalized resource。
3. capability 来自验证结果，不来自文件扩展名猜测。
4. 空数据、解析失败和不支持是不同结果。
5. 空间 representation 必须有已解析 CRS 或明确的非空间用途。
6. geometry kind、validity 和 digest 在发布前确定性验证。
7. 未准入资源不得出现在 current catalog view。
8. DATA 只能提交资源事实或 proposal，不能提交实体身份结论。

## 8. Failure Taxonomy

| 状态 | 含义 | 默认恢复 |
|---|---|---|
| <code>UNSUPPORTED</code> | capability registry 无匹配 adapter/组合 | 增加受测 adapter 或转换输入 |
| <code>INVALID</code> | 内容不满足已声明格式/schema | 修正来源并重新提交 |
| <code>CRS_UNRESOLVED</code> | 空间坐标参考无法可靠确定 | 提供权威 CRS 或人工决定 |
| <code>ENCODING_UNRESOLVED</code> | 文本编码不能无损确定 | 提供编码声明或转换文件 |
| <code>GEOMETRY_INVALID</code> | 几何非法且无受控修复策略 | 修复来源或由治理决定 |
| <code>POLICY_REJECTED</code> | 来源、许可、大小或安全策略拒绝 | 修改策略输入或替换来源 |

parser 崩溃、存储暂态错误和预算耗尽是 attempt failure，不得伪装成上述数据语义终态；它们
产生可重试的运行 gap。

## 9. Gap & Recovery

<code>DataGap</code> 至少包含：

~~~text
gap_ref
source_ref
attempt_ref
state_at_failure
reason_code
required_capability
observed_metadata
input_refs
recovery_action
retryability
owner
budget_state
~~~

恢复动作限定为：补充声明、受控格式转换、选择已注册 adapter、提供 CRS/encoding、替换来源、
人工 policy 决定或修复 geometry。输入 digest 和 capability registry 均未改变时立即停止，
不得按固定次数反复解析。

## 10. Persistence/CAS

所有 source、normalized、representation、index、receipt 和 gap 都以不可变 artifact 保存。
catalog snapshot 只保存 refs 与索引，不复制可变对象。失败 attempt 同样可重载，以便诊断和
恢复。artifact 写入必须先校验 digest，发布 current catalog 使用 CAS。

## 11. Version & Digest

最小版本向量：

~~~text
content_digest
adapter_id/version
normalizer_version
schema_version
crs_resolver_version
geometry_validator_version
capability_registry_version
policy_digest
parent_catalog_snapshot_ref/digest
~~~

任何影响规范化值、几何、语义角色或能力声明的变化都必须生成新 artifact；只读展示元数据
变化可生成新 projection，但不能悄悄改变旧 digest。

## 12. Dependency/Invalidation

依赖链为：

~~~text
source bytes
  → normalized resource
  → representation
  → capability index
  → session resource catalog
  → World Model proposal / Evidence query / Planning Ground candidate
~~~

source digest、adapter、CRS、geometry 或 capability 改变时，通过 dependency index 失效所有
下游引用；只重算受影响 resource。旧 artifact 保留审计能力，但不能继续出现在 current view。

## 13. Deterministic vs LLM Boundary

确定性逻辑负责字节识别、schema 验证、字段类型、CRS 校验、geometry validity、digest、
capability admission 和 policy gate。LLM 仅可为未决字段语义或 source role 产生有证据引用的
候选建议；建议必须经过白名单、schema 和确定性规则验证，并以 proposal 状态保存。

LLM 不得生成 CRS、坐标、geometry、source digest、capability 或成功 receipt。

## 14. Observability/Trace

每个 attempt 记录状态迁移、耗时、adapter 选择原因、输入输出 refs、warning/reason code 和
catalog commit 结果。至少统计：

~~~text
admission_by_terminal_state
unsupported_by_source_kind
parse_and_normalize_latency
crs_unresolved_rate
geometry_invalid_rate
catalog_cas_conflict_rate
recovery_success_by_action
downstream_capability_miss
~~~

## 15. Acceptance Probe

本轮 P0 MVP 探针只验证 DATA 文件读取，不以下游模块能运行作为验收条件：

1. 逐个读取 10 个现状 GeoJSON、<code>dem.tif</code> 和现状 Markdown 报告，使用各自声明
   的 adapter、media type、encoding、CRS 和 <code>current_evidence</code> role；
2. 每个支持文件完整走到 <code>ADMITTED</code>，并从 CAS 重载 receipt、catalog、stage 和
   snapshot，核对 digest、source ref、文件/要素 lineage；
3. 使用不含业务字段的通用记录做一次读取归一化检查，证明不存在 BSM、DLBM、固定字段集或
   输入领域类依赖；
4. 不支持格式产生 <code>UNSUPPORTED + DataGap</code>，缺空间 CRS 产生
   <code>CRS_UNRESOLVED</code>，非法 geometry 产生 <code>GEOMETRY_INVALID</code>；
5. 检查 current DATA 输入中不出现 <code>planned/</code>、规划文本、规划图件、规划工程包
   或 planned output；
6. 只读盘点高德、天地图、腾讯的统一缓存 manifest/attempt/request/raw/cache 文件，保留
   <code>NOT_ATTEMPTED</code>、失败、部分完成和配额状态；本轮不把它们转交给下游模块；
7. 不运行、不验收 Cognition、World Model、Evidence enrichment、L1、L1-GROUND 或 L2。

探针必须记录确切 adapter、文件路径和状态；结论只能覆盖已声明的 DATA 文件组合。

## 16. Remaining Gaps

当前仓库已有 admission、resource catalog、source snapshot、representation selection 等部分
实现；但完整状态机、统一 receipt/gap、catalog CAS、精确失效和覆盖矩阵仍需以运行证据确认。
唯一 current-to-target 状态与迁移出口记录在 <code>05_MIGRATION.md</code>；本节不复制完成百分比。
