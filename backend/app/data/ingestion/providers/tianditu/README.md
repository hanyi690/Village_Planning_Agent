# Tianditu provider clients

本目录包含国家级天地图 API、WFS、WMTS 和广东省专题 MapServer/WFS 服务的协议客户端：

- `provider.py`：行政区划、POI、地理编码和路径 API；
- `wfs.py`：WFS GetFeature response；
- `tiles.py`：WMTS URL/template；
- `gd_service.py`：广东省专题服务的 WFS/WMTS/MapServer 请求和 response 转换；
- `constants.py`、`gd_constants.py`、`types.py`：端点、服务声明和结果 envelope。

## 输入与输出

- 输入：由 `BoundaryScopeArtifact` 派生的 query geometry、显式服务 ID 和 layer declaration；
- 输出：带 provider、请求范围、坐标契约和 coverage 状态的 response；
- 坐标：服务声明的 CGCS2000/WGS84 contract 必须明确，不能把未知坐标当作 WGS84；
- 凭据：从 connection/settings 读取，不写入 URL、manifest 或日志。

## 运行边界

`sources.api_vector` 只执行 receipt 声明的 WFS 或 MapServer 协议；
`sources.wmts_tile` 只执行 WMTS。三家地图采集脚本负责 `ProviderAcquisitionPlan`、lease、writer 和 coverage
manifest；client 不直接写 provider cache。

禁止在 provider 内做外部锚点注入、地名词典构建、领域聚合或本地 DATA geometry 覆盖。
