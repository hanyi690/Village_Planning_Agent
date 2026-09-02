# AMap provider client

`provider.py` 封装高德的显式 API 请求，包括 POI、地理编码、行政区划和路径查询。
provider 只返回 API response envelope，不组装 DATA catalog，不生成本地 geometry，不执行
provider 间 fallback。

## 输入与输出

- 输入：由 provider run 提供的 `BoundaryScopeArtifact` 派生 query geometry，或声明式 driver
  需要的受控参数。
- 输出：带 provider、请求范围、坐标契约和状态的 observation response。
- 凭据：只从 settings/connection 读取，不写入 URL、manifest 或日志。
- 坐标：高德原始 GCJ-02 结果必须按明确 contract 转换；未知坐标不能按 WGS84 处理。

## 运行边界

三家地图采集脚本负责 `ProviderAcquisitionPlan`、lease、writer 和 coverage manifest；AMap client 不直接
写 `data/cache/map_observations`。缓存由
`app.data.catalog.provider_run_lease.ProviderObservationWriter` 统一发布。

禁止在 provider 内做外部锚点注入、地名词典构建、领域聚合或本地 DATA geometry 覆盖。
