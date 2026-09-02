# DATA 成熟度验收卡

设计 owner：<code>../DATA_EXECUTABLE_DESIGN.md</code>。

## 当前目标：P0 / DATA file-read probe

验收范围必须列出确切 adapter、文件格式、geometry kind 与 CRS。字段只作为原始属性映射
保留，不构成读取前置条件；声明能力外必须 fail closed。本卡不验收 DATA 之后的模块。

本轮 MVP 是可复现的测试/运行探针，不是业务模块；不得添加金田村专用 MVP 组合类或
<code>mvp_*</code> 生产路径。

## 金田村 MVP 输入范围

本卡的真实输入集合固定为：

1. <code>data/gis/jintian/current/</code> 下 10 个现状 GeoJSON：
   <code>admin_boundary_line</code>、<code>annotation</code>、<code>boundary</code>、
   <code>construction_zone</code>、<code>ecological_protection</code>、
   <code>farmland_protection</code>、<code>geological_hazard_points</code>、
   <code>historical_protection</code>、<code>landuse</code>、<code>road</code>；
2. 唯一的 DEM 文件 <code>data/gis/jintian/terrain/dem.tif</code>；不附带未被确认存在的
   source package；
3. 现状报告 <code>docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md</code>；
4. <code>data/cache/map_observations/{amap,tianditu,tencent}/</code> 的统一外源地图缓存，作为
   独立 cache inventory 读取并保留状态；旧 <code>output/map_validation/</code> 已物理删除，
   不进入本轮 DATA current catalog。

<code>data/gis/jintian/planned/</code>、规划文本和规划成果不在本卡输入范围内。
它们进入 fresh DATA catalog 或 current World Model 即判定为越界。

## 当前运行证据（截至 2026-09-02）

当前已完成一次真实输入逐文件 facade → CAS → reload probe；本节同时区分可复现的代码/测试
证据与不属于 P0 的下游 context 验收。

| 结果 | 实际观察 | 状态 |
|---|---|---|
| 文件准入 | 10 个现状 GeoJSON、<code>dem.tif</code>、现状 Markdown 均经真实 facade probe 到达 <code>ADMITTED</code> | <code>RUNTIME_VERIFIED</code> |
| 边界范围 | <code>boundary.geojson</code> 只能从 admitted polygon 生成 <code>BoundaryScopeArtifact</code>；三 provider acquisition plan 均绑定同一 boundary/query digest | <code>RUNTIME_VERIFIED</code>：真实 Jintian acceptance |
| DATA 记录 | 上传统一经过 temporal role gate + facade；session loader 对 admitted 上传只 reload CAS payload，不重新解释正文 | <code>IMPLEMENTED</code> |
| DEM 元数据 | 只读盘点确认 <code>EPSG:4326</code>、3601×3601、单波段 int16、分辨率约 0.0002777778°、nodata=null | <code>RUNTIME_VERIFIED</code>：文件元数据盘点 |
| CAS 重载 | receipt、catalog index、四类 catalog product、snapshot、stage 可从 artifact refs 重载；相同 request replay 幂等 | <code>RUNTIME_VERIFIED</code>：fixture + 真实文件 probe |
| 通用输入 | generic mapping 不要求 BSM、DLBM 或领域类；真实 10 个 GeoJSON、DEM、Markdown 均通过 facade | <code>RUNTIME_VERIFIED</code> |
| 失败分类 | contract/code 已定义 <code>UNSUPPORTED</code>、<code>CRS_UNRESOLVED</code>、<code>GEOMETRY_INVALID</code> 等终态；不支持格式有 facade 拒绝回归 | <code>RUNTIME_VERIFIED</code> |
| 失败产品重载 | receipt/DataGap 的 CAS 产品路径存在；quarantine/unsupported 的失败产品由同一 facade ingress 记录 | <code>IMPLEMENTED</code> |
| 幂等与排除 | fixture 已验证 replay 幂等、stale parent 拒绝和 planned/非 current 隔离 | <code>RUNTIME_VERIFIED</code> |

### 外源地图缓存盘点

以下是对 <code>data/cache/map_observations/amap/</code>、<code>tianditu/</code>、<code>tencent/</code>
三个统一 provider 目录的只读盘点；它不代表本轮已执行 Evidence enrichment，也不把外源
坐标写入 DATA current catalog。

| provider | manifest / normalized / attempts / requests | cache / raw response 文件 | 观察到的状态 |
|---|---|---|---|
| 高德 | manifest 2、normalized 2、attempt 2、request 5 | provider 目录存在 cache/raw 及运行文件 | 只读盘点，不进入 current catalog |
| 天地图 | manifest 7、normalized 7、attempt 7、request 7 | provider 目录存在 cache/raw 及运行文件 | 只读盘点，不进入 current catalog |
| 腾讯 | manifest 1、normalized 0、attempt 1、request 1 | provider 目录存在 cache/raw 及运行文件 | 未生成 normalized rows 的状态必须保留，不能解释为无数据 |

缓存的 manifest、attempt、request、raw response 和 cache 内容只作为 provider 状态与来源
证据保留；后续若接入 Evidence，必须继续沿用这些状态，不得把 missing/failed/quota 当作
现实中不存在。

| Gate | P0 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | capability registry 接纳或拒绝每个声明文件组合 | <code>PASS</code>：local vector/table/document/raster matrix；remote/API 仍显式 UNSUPPORTED |
| Product | DATA receipt、gap、catalog index、四类 product、stage、snapshot 可重载 | <code>PASS</code>：component product reload 已验证 |
| Consumer | context bootstrap 接收并保留 BoundaryScopeArtifact；Evidence 只读加载 provider cache 并返回 observation facts | <code>RUNTIME_VERIFIED</code>：真实 Jintian acceptance |
| Recovery | 文件失败有 terminal state、DataGap、恢复动作；resume 必须携带可重试 gap；同输入可重放，stale parent 不覆盖 current ref | <code>PASS</code>：生命周期、recovery、replay 回归已覆盖 |

## P0 必测探针

- 支持输入逐文件走过 <code>DISCOVERED → … → ADMITTED</code>，并证明 CAS 重载 digest 一致；
- 上述 10 个现状 GeoJSON、DEM 和现状报告均有明确 source ref/role；DEM 的 raster
  CRS、范围、分辨率和 nodata 校验结果可重载；报告文本至少保留 UTF-8 Markdown content
  digest 和 `markdown_line` span strategy；
- current 输入快照不含 <code>planned/</code>、规划文本或规划成果；
- 不支持格式：<code>UNSUPPORTED</code>，而不是空成功；
- 缺 CRS：<code>CRS_UNRESOLVED</code> 且不进入 current catalog；
- 无法确定性修复或修复后仍无效的 geometry：<code>GEOMETRY_INVALID</code>；可保持类型且
  结果有效的拓扑修复必须在 transform trace 中留痕；
- 同请求重放幂等；stale parent 只能作为 DATA admission 的拒绝证据，不覆盖新 catalog；
- 真实 Jintian acceptance 必须完成：upload → admission receipt → normalized boundary →
  三 provider acquisition plan → cache/snapshot → context bootstrap → Evidence retrieval，并且
  前后 local catalog digest、boundary digest 不变；同一内容 replay 必须复用 boundary scope，
  stale parent 和精确 feature/representation/capability invalidation 必须保持拒绝/失效结果；
- 通用属性映射可以没有 BSM、DLBM 或其他业务字段，也不要求输入对象属于某个领域类；
- 上传 byte、Markdown text、FeatureCollection feature、TableResource row 均受 DATA budget 限制，超限只能形成 quarantined gap；
- 本轮不验证 Planning Ground、L1、L2 或完整 workflow 消费。

## Deferred

- P1：在线/API/WMTS/remote raster driver 的声明式 admission、精确失效和下游回归仍需单独闭环；
- P2：并发吞吐、权限、安全扫描、SLO 与灾难恢复仍需独立的生产验收；本轮已完成基础输入 budget 与 recovery contract。

当前不得声明“支持任意 GIS/文件/字段/图层/几何/CRS”。Remaining gaps 只在
<code>../05_MIGRATION.md</code> 维护。
