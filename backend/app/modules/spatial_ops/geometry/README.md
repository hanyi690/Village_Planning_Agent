# spatial_ops.geometry — 纯几何计算原语

## 职责边界

- 纯几何/空间拓扑计算原语层，无 Agent 状态、无业务编排。
- `geometry.py`：质心、总面积、近点地块搜索、三层空间关系计算
  （`compute_parcel_relations` 是系统内唯一使用 geopandas/shapely 做几何计算
  的入口）、`point_in_polygon` 射线法判断、村庄边界提取。
- `relations.py`：居民点之间的方位关系（`_compute_spatial_relations`）与
  分区邻接矩阵（`_compute_zone_adjacency`）。
- `subdivision.py`：OBB 递归切分（Vanegas 2012），`obb_subdivide` /
  `split_for_footprint` 生成项目占地与剩余地块，`apply_setback` 内缩。
- `axis_builder.py`：`AxisBuilder` 生成"一核一带三区"发展轴结构 GeoJSON
  （点=村核、线=生态廊道、面=三区），支持 AxisIntent 显式轴线或自动生成。

## 输入输出契约

- 输入为**类型化要素列表**（如 `BaseLandUseParcel`，直接访问 `.bsm/.dlbm/
  .geometry`）或 GeoJSON FeatureCollection dict；不做字段名猜测。
- `compute_parcel_relations(parcels, roads, water_bodies) -> ParcelRelations`，
  含 touches/nearby/connected 及 parcel↔road、parcel↔water 跨层关系，
  供 PlanningKG 消费。
- 坐标单位：subdivision 假设米制；geometry.py 处理 EPSG:4326。
- 失败不抛异常：各函数捕获异常返回空结果并记 warning。

## 依赖方向

- 依赖 `app.utils`（crs_engine / area_engine / geo_utils / geojson_utils）。
- `relations.py` 依赖 `app.modules.schema.contracts.context_contracts` 的类型。
- 本包不依赖 agent / services / api 层，被 context、index、grounding 等消费。

## 禁止行为

- 禁止修改 bundle 或任何输入要素（只读计算）。
- 禁止在 geometry.py 之外新增 geopandas/shapely 几何计算入口。
- 禁止返回原始 GeoJSON 大对象给调用方直接遍历（应由类型化结果承载）。
- 禁止吞掉需要调用方决策的异常。
