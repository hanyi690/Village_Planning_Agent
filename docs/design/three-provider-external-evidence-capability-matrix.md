# 三 Provider 外源证据能力矩阵

本文件约束 AMap、天地图和腾讯位置服务在验证采集阶段的边界。它服务于 `07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md` 的 Source Data / Evidence / Cognition / GROUND 分层，不把任一地图服务的 POI 结果直接当作 WorldEntity 或完整几何。

## 官方能力依据

| Provider | 官方依据 | 本项目使用的能力 |
|---|---|---|
| AMap | [POI 搜索 2.0](https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch)、[输入提示](https://lbs.amap.com/api/webservice/guide/api-advanced/inputtips)、[地理/逆地理编码](https://lbs.amap.com/api/webservice/guide/api/georegeo)、[路线规划 2.0](https://lbs.amap.com/api/webservice/guide/api/newroute) | 文本、周边、多边形、POI ID 详情、输入提示、地理编码、完整逆地理、有限路线验证 |
| 天地图 | [地名搜索 V2.0](https://lbs.tianditu.gov.cn/server/search2.html) | 行政区搜索、视野/普通搜索、地名搜索、多边形搜索、分类搜索、统计搜索、地理编码、逆地理编码、行政边界、路线、WFS |
| 腾讯位置服务 | [腾讯位置服务开发平台](https://lbs.qq.com/)、[WebService 地点搜索说明](https://lbs.qq.com/webservice_v1/guide-search.html)、[WebService 地理编码说明](https://lbs.qq.com/webservice_v1/guide-geocoder.html) | 区域搜索、周边搜索、矩形搜索、输入提示、地址/逆地址解析、有限路线验证；当前公开 WebService 未确认通用 POI detail，记为 capability missing |

## 坐标契约

| Provider | 请求/返回约定 | 本地空间判断 |
|---|---|---|
| AMap | API 点使用 GCJ-02；Polygon 输入也转换为 GCJ-02 | 转一次为 WGS84 后与 bundle/boundary 判断；保留两份坐标 |
| 天地图 | 搜索和 WFS 使用官方 lon/lat；项目按 CGCS2000 与 WGS84-compatible 记录 | 保存 `location_crs`，不套用 GCJ-02 偏移 |
| 腾讯 | `boundary=nearby(lat,lng,radius)` 和路线 `from/to` 使用纬度在前；显式请求 `coord_type=wgs84` | 规范化为 GeoJSON 的 `[lon,lat]`，保留原始响应结构 |

## 请求状态

请求事件必须区分：

```text
success_nonempty  接口成功且有记录
missing           接口成功但无记录，或公开接口不提供该能力
failed            已尝试但网络、HTTP、限流、服务或参数错误导致未完成
```

`failed` 保存每次 attempt，并按可重试策略再次执行；成功缓存不会重复请求。`missing` 不应触发无意义重试，也不能被解释成实体不存在。

## 两阶段产物

```text
output/map_validation/<provider>/<stage>/
├── cache/
├── raw_responses/
├── runs/<run_id>/attempts.jsonl
├── runs/<run_id>/requests.jsonl
├── runs/<run_id>/normalized_all.jsonl
├── runs/<run_id>/retained_candidates.jsonl
└── runs/<run_id>/rejected_candidates.jsonl
```

行政基线只使用行政区划和本地边界/网格/既有 bundle 几何；L1 阶段只使用不可变 L1Snapshot 中的地点名称。两阶段、三个 provider 的缓存必须保持独立。

## 能力边界

- 地图底图上可见的任意文字标注，不等于 POI，也不等于公开接口可枚举的数据。
- 天地图 WFS 线面点和本地 bundle 可形成道路/水系的几何候选，但不能因为 WFS 返回单个 feature 就直接命名为现实实体。
- 腾讯 nearby 半径有限时，矩形分块与 nearby 网格是公开 API 范围内的替代策略，不等价于完整路网或完整底图。
- Evidence 只接收经过行政范围和坐标规范化的候选包；GROUND 只从既有 WorldEntity/SpatialRepresentation 闭集绑定，不创建 API 几何。
