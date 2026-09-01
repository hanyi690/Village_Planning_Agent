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
2. <code>data/gis/jintian/terrain/dem.tif</code> 与 source package
   <code>data/gis/广东DEM30M.zip</code>；
3. 现状报告 <code>docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md</code>；
4. <code>output/map_validation/{amap,tianditu,tencent}/</code> 的统一外源地图缓存，作为
   独立 cache inventory 读取并保留状态，不进入本轮 DATA current catalog。

<code>data/gis/jintian/planned/</code>、规划文本和规划成果不在本卡输入范围内。
它们进入 fresh DATA catalog 或 current World Model 即判定为越界。

| Gate | P0 通过条件 | 当前证据状态 |
|---|---|---|
| Entry | capability registry 接纳或拒绝每个声明文件组合 | <code>PARTIAL</code>：代码路径存在，待 DATA-only probe 取证 |
| Product | DATA receipt、gap、catalog、stage、snapshot 可重载 | <code>PARTIAL</code>：代码路径存在，待 DATA-only probe 取证 |
| Consumer | 本轮不进入下游；只确认 DATA 产品通过公开 DATA facade 返回 | <code>NOT IN SCOPE</code> |
| Recovery | 文件失败有 terminal state、DataGap、恢复动作；同输入可重放 | <code>PARTIAL</code>：待 DATA-only probe 取证 |

## P0 必测探针

- 支持输入逐文件走过 <code>DISCOVERED → … → ADMITTED</code>，CAS 重载 digest 一致；
- 上述 10 个现状 GeoJSON、DEM 和现状报告均有明确 source ref/role；DEM 的 raster
  CRS、范围、分辨率和 nodata 校验结果可重载；文本事实带章节/段落 span；
- current 输入快照不含 <code>planned/</code>、规划文本或规划成果；
- 不支持格式：<code>UNSUPPORTED</code>，而不是空成功；
- 缺 CRS：<code>CRS_UNRESOLVED</code> 且不进入 current catalog；
- 非法 geometry：<code>GEOMETRY_INVALID</code>；
- 同请求重放幂等；stale parent 只能作为 DATA admission 的拒绝证据，不覆盖新 catalog；
- 通用属性映射可以没有 BSM、DLBM 或其他业务字段，也不要求输入对象属于某个领域类；
- 本轮不验证 Planning Ground、L1、L2 或完整 workflow 消费。

## Deferred

- P1：稳定覆盖 MVP 规划所需输入矩阵、精确失效和下游回归；
- P2：广格式、并发吞吐、恶意/超大输入治理、权限、安全扫描、SLO 与灾难恢复。

当前不得声明“支持任意 GIS/文件/字段/图层/几何/CRS”。Remaining gaps 只在
<code>../05_MIGRATION.md</code> 维护。
