# Tencent Map provider client

`provider.py` 封装腾讯位置服务的区域搜索和周边搜索，返回受控的
`TencentMapResult`。provider 不负责 session 组装、外部锚点绑定或 provider 间 fallback。

## 输入与输出

- 输入：由 `BoundaryScopeArtifact` 派生的 query geometry，以及明确的关键字、分页和过滤条件。
- 输出：带 provider、请求范围、坐标契约和状态的 observation response。
- 坐标：使用服务声明的 WGS84 返回模式；坐标契约不明确时拒绝消费。
- 凭据：从 connection/settings 读取，不写入 URL、manifest 或日志。

## 运行边界

三家地图采集脚本负责 `ProviderAcquisitionPlan`、lease、writer 和 coverage manifest；Tencent client 不直接
写 `data/cache/map_observations`。缓存由
`app.data.catalog.provider_run_lease.ProviderObservationWriter` 统一发布。

禁止在 provider 内做 POI 聚合、外部锚点注入、地名词典构建或本地 DATA geometry 覆盖。
