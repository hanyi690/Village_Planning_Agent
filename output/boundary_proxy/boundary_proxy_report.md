# 村庄边界代理推算验证报告

**验证时间**: 2026-04-26 00:21:05
**测试地点**: 金田村 (115.891, 24.567)

## 依赖检查

- geopandas: ✅
- shapely: ✅
- alphashape: ✅
- matplotlib: ✅
- contextily: ✅

## 方案对比

| 方案 | 方法 | 成功 | 面积(km²) | 周长(km) |
|------|------|------|-----------|----------|
| 等时圈边界 | 15分钟步行可达性分析 | ✅ | 5.4005 | 8.2674 |
| 形态学包络线 (凸包) | RESA凸包 | ✅ | 9.0072 | 11.8222 |
| 形态学包络线 (凹包) | RESA凹包α=0.5 | ✅ | 9.0072 | 11.8222 |
| 自然闭合边界 | 水系(HYDL)+公路(LRDL)闭合切割 | ✅ | 42.5421 | 347.3098 |

## 详细结果

### 等时圈边界

**方法**: 15分钟步行可达性分析
**状态**: 成功

**统计信息**:
- time_minutes: 15
- travel_mode: walk
- radius_km: 1.25
- area_km2: 5.4005
- perimeter_km: 8.2674

### 形态学包络线

**方法**: 居民地(RESA)分布包络
**状态**: 成功

**统计信息**:
- feature_count: 3

### 自然闭合边界

**方法**: 水系(HYDL)+公路(LRDL)闭合切割
**状态**: 成功

**统计信息**:
- line_count: 14
- water_count: 7
- road_count: 7
- area_km2: 42.5421
- perimeter_km: 347.3098
- polygon_count: 1
- contains_center: True

## 方案评估

### 方案一：等时圈边界
- **优点**: 反映真实可达性，基于路网分析
- **缺点**: 需要API支持，圆形近似精度有限
- **适用场景**: 交通可达性分析、服务范围划定

### 方案二：形态学包络线
- **优点**: 紧密贴合建成区分布，无需API
- **缺点**: 需要足够密集的RESA数据点
- **适用场景**: 居民地聚集范围划定

### 方案三：自然闭合边界
- **优点**: 利用地理屏障，符合自然边界逻辑
- **缺点**: 需要闭合的线要素网络，成功率不稳定
- **适用场景**: 有明显地理分割的区域

## 推荐方案

基于本次验证结果，建议：

1. **主方案**: 形态学凹包（紧密贴合建成区）
2. **备选方案**: 等时圈边界（反映可达性）
3. **校核方案**: 自然边界（如有闭合水系/道路网络）

## 输出文件

- `output/boundary_proxy/isochrone_boundary.geojson`
- `output/boundary_proxy/morphological_hull.geojson`
- `output/boundary_proxy/morphological_concave.geojson`
- `output/boundary_proxy/natural_boundary.geojson`
- `output/boundary_proxy/comparison_chart.png`
- `output/boundary_proxy/boundary_proxy_report.md`