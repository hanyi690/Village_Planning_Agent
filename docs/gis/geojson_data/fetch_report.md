# 金田村 GIS 数据获取报告

**获取时间**: 2026-04-06 15:09:01

**目标地点**: 金田村, 泗水镇, 平远县

**缓冲半径**: 2.0 km

**中心坐标**: `(116.040808, 24.816827)`

**边界框**: `(116.02278998198199, 24.79880898198198, 116.05882601801801, 24.83484501801802)`

## 获取状态概览

| 状态 | 说明 |
|------|------|
| complete | 7/7 图层成功 |

## 图层详情

| 图层 | 类型 | 状态 | 要素数 |
|------|------|------|--------|
| 水系面 | HYDA | 成功 | 0 |
| 水系线 | HYDL | 成功 | 1 |
| 水系点 | HYDP | 成功 | 0 |
| 铁路 | LRRL | 成功 | 0 |
| 公路 | LRDL | 成功 | 1 |
| 居民地面 | RESA | 成功 | 0 |
| 居民地点 | RESP | 成功 | 0 |

## 输出文件

| 文件名 | 说明 |
|--------|------|
| metadata.json | 元数据摘要 |
| boundary_pingyuan.geojson | 平远县边界（参考） |
| center_point.geojson | 金田村中心点 |
| water_hyda.geojson | 水系面 |
| water_hydl.geojson | 水系线 |
| water_hydp.geojson | 水系点 |
| water_combined.geojson | 水系合并 |
| road_lrrl.geojson | 铁路 |
| road_lrdl.geojson | 公路 |
| road_combined.geojson | 道路合并 |
| residential_resa.geojson | 居民地面 |
| residential_resp.geojson | 居民地点 |
| residential_combined.geojson | 居民地合并 |
| fetch_report.md | 获取报告 |

## 定位策略说明

采用向上定位策略:

1. 获取平远县边界作为参考区域
2. 尝试泗水镇边界（可能不支持）
3. 通过地理编码定位金田村中心坐标
4. 若地理编码失败，尝试区域内POI搜索
5. 以中心坐标 + 缓冲半径构建 bbox

---

*报告生成于 2026-04-06 15:09:01*