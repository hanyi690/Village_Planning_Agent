# data.providers.amap — 高德地图适配器

## 职责边界

- 外部地图/地理编码服务商（高德）适配器，统一封装高德 Web 服务 API。
- `provider.py`：`AmapProvider` 核心封装——POI 关键字/周边/类型搜索、
  地理编码 `geocode` / 逆地理编码 `reverse_geocode`、行政区划查询
  `get_district`（含边界 polyline→GeoJSON）、驾车/步行路径规划
  `plan_route_driving` / `plan_route_walking`、道路数据获取
  `search_roads_by_poi` / `get_road_network_by_routing`。
  统一结果信封 `AmapResult`（success/data/metadata/error）。
- `anchor_service.py`：`AmapAnchorService` 并发拉取外源锚点——行政村村委会、
  设施（typecode 扫描）、道路名、水体名，输出 4 类 POI 字典 + errors。
- `constants.py`：URL、POI 类型码、服务半径标准、交通态势、策略常量。
- `types.py`：`AmapResult` 信封类型。
- 坐标：GCJ-02 → WGS-84 转换（`gcj02_to_wgs84`）。

## 输入输出契约

- 输入：WGS-84 坐标、关键字/类型码、城市名、半径（米）等。
- 输出：统一 POI dict（id/name/lon/lat/lon_gcj02/lat_gcj02/address/distance/
  category/typecode/tel）或路径/区划 GeoJSON。
- 失败不抛异常：返回 `AmapResult(success=False, error=...)`；429/5xx 指数退避重试。

## 依赖方向

- 依赖 `app.core.settings`（AMAP_API_KEY 等）、`app.modules.data.connections`
  （RateLimiter，key="amap"）、`app.utils.coord_transform`。
- 被 `app.modules.data.providers.poi`（POIProviderFactory）与
  `app.modules.data.catalog.external_anchors` 消费。

## 禁止行为

- 禁止硬编码 API Key（必须读 settings）。
- 禁止绕过 RateLimiter 直接请求（避免触发 429）。
- 禁止返回 GCJ-02 坐标冒充 WGS-84（POI/路径必须转换）。
- 禁止在 provider 内做业务聚合（聚合逻辑归 anchor_service/catalog）。
