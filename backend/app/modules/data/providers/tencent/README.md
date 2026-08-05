# data.providers.tencent — 腾讯地图适配器

## 职责边界

- 外部地图/地理编码服务商（腾讯）适配器，统一封装腾讯位置服务 Web API。
- `provider.py`：`TencentMapProvider` 核心封装——区域搜索 `search_region`
  （boundary=region(...)）、周边搜索 `search_nearby`（boundary=nearby(lat,lng,
  radius)）、POI 解析 `_parse_pois`。统一结果信封 `TencentMapResult`
  （success/data/metadata/error）。
- 坐标系：默认 GCJ02，通过 `coord_type=wgs84` 直接返回 WGS84。
- `anchor_service.py`：`TencentAnchorService` 并发拉取外源锚点——行政村
  （region 搜"村"）、设施/道路/水体（周边搜索），输出与 AmapAnchorService
  同结构的 4 类数据 + errors。
- `constants.py`：URL、coord_type、分页、filter 分类关键词（FILTER_CATEGORIES）。
- `types.py`：`TencentMapResult` 信封类型。

## 输入输出契约

- 输入：单关键字 + boundary（region/nearby），可选 filter=category 与分页；
  nearby 半径上限 1000 米，lat 在前。
- 输出：统一 POI dict（id/name/lon/lat/address/tel/category/type/distance/
  adcode/province/city/district）。
- 失败不抛异常：返回 `TencentMapResult(success=False, error=...)`；
  429/5xx 指数退避重试。

## 依赖方向

- 依赖 `app.core.settings`（TECENT_MAP_API_KEY 等）、
  `app.modules.data.connections`（RateLimiter，key="tencent_map"）。
- 被 `app.modules.data.catalog.external_anchors` 消费（source="tencent_map"）。

## 禁止行为

- 禁止硬编码 API Key（必须读 settings）。
- 禁止绕过 RateLimiter 直接请求。
- 禁止返回 GCJ02 坐标冒充 WGS-84（须用 coord_type=wgs84）。
- 禁止在 provider 内做业务聚合（聚合归 anchor_service/catalog）。
