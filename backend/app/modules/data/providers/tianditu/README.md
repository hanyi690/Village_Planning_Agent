# data.providers.tianditu — 天地图适配器

## 职责边界

- 外部地图/地理编码/矢量服务商（天地图）适配器，含国家级 WFS 与广东省专题服务。
- `provider.py`：`TiandituProvider` 核心封装——行政边界 `get_boundary`
  （V2 API，WKT MULTIPOLYGON → GeoJSON）、POI 周边/区域内搜索
  `search_poi` / `search_poi_in_region`、地理编码 `geocode` / 逆地理编码
  `reverse_geocode`、路径规划 `plan_route`（XML 解析）、委托瓦片与 WFS 子服务。
- `wfs.py`：`WfsService`——WFS GetFeature（HYDA 水系面 / HYDL 水系线 /
  LRDL 公路 / LRRL 铁路 / RESA/RESP 居民地），含 get_water_features /
  get_road_features / get_residential_features 组合接口。
- `tiles.py`：`TileService`——矢量/影像/地形/注记/境界瓦片 URL 与模板。
- `gd_service.py`：`GDSpecializedService`——广东省天地图专题服务（三区三线、
  生态红线、基本农田、地质灾害点等），WFS/WMS/WMTS URL 构建、MapServer REST
  查询与 ESRI JSON→GeoJSON 转换。
- `anchor_service.py`：`TiandituWfsAnchorService` 拉取水系面/水系线/公路
  矢量锚点。
- `constants.py` / `gd_constants.py` / `types.py`：端点、图层/服务配置、
  `TiandituResult` 信封。
- 坐标系：CGCS2000 与 WGS-84 视作兼容（村级精度可接受），无 GCJ 偏移。

## 输入输出契约

- 输入：关键字、WGS-84 坐标、bbox、图层类型/服务 ID。
- 输出：`TiandituResult(success/data/metadata/error)`，内含 GeoJSON
  FeatureCollection 或瓦片 URL。
- 失败不抛异常；418 提示 IP 白名单问题；429/5xx 指数退避重试。

## 依赖方向

- 依赖 `app.core.settings`（TIANDITU_API_KEY / GD_TIANDITU_TOKEN 等）、
  `app.modules.data.connections`（RateLimiter，key="tianditu"）。
- 被 `app.modules.data.providers.poi`、`app.modules.parsing.gazetteer`
  （地理编码）、`app.modules.data.catalog.external_anchors`
  （source="tianditu_wfs"）、`app.modules.data.sources.api_vector` 与
  `sources.wmts_tile`（GDSpecializedService）
  （等时圈/可达性）消费。

## 禁止行为

- 禁止硬编码 API Key / Token（必须读 settings）。
- 禁止绕过 RateLimiter 直接请求。
- 禁止把 GCJ02 转换逻辑引入本包（天地图无需偏移，勿照搬高德）。
- 禁止在 provider 内做业务聚合（归 anchor_service/catalog/sources）。
