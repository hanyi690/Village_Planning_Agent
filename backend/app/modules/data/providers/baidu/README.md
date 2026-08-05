# data.providers.baidu — 百度地图适配器

## 职责边界

- 外部地图/地理编码服务商（百度）适配器，统一封装百度地图 Web 服务 API。
- `provider.py`：`BaiduProvider` 核心封装——行政区划区域检索
  `search_region`（place/v3/region）、城市检索 `search_city`（place/v2/search）、
  地点输入提示 `search_suggestion`、静态解析 `_parse_pois`（results → 统一 POI）。
  统一结果信封 `BaiduResult`（success/data/metadata/error）。
- 坐标系：通过 `coord_type=1`（COORD_TYPE_WGS84）强制返回 WGS84，
  避免后续 GCJ/BD09 转换。
- `constants.py`：URL、coord_type 常量、默认分页、POI 分类 tag
  （TAGS_FACILITY/TAGS_GEOGRAPHY）。
- `types.py`：`BaiduResult` 信封类型。

## 输入输出契约

- 输入：query 关键字 + region（行政区名/adcode）、可选 tag、分页参数。
- 输出：统一 POI dict（id/name/lon/lat/address/province/city/area/adcode/
  telephone/type/tag/distance/result_type）；suggestion 输出联想列表。
- 失败不抛异常：返回 `BaiduResult(success=False, error=...)`；429/5xx 指数退避重试。

## 依赖方向

- 依赖 `app.core.settings`（BAIDU_API_KEY 等）、`app.modules.data.connections`
  （RateLimiter，key="baidu"）。
- 被 `app.modules.data.catalog.external_anchors` 消费（source="baidu_v3"）。

## 禁止行为

- 禁止硬编码 API Key（必须读 settings）。
- 禁止绕过 RateLimiter 直接请求。
- 禁止返回 bd09/gcj02 坐标冒充 WGS-84（须用 coord_type=1 或显式转换）。
- 禁止在 provider 内做跨源去重/业务聚合（归 external_anchors）。
