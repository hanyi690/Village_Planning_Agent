# spatial_ops.index — 空间索引桥（bundle 几何 → 空间查询）

## 职责边界

- 提供 EXECUTE / EXPLORE 等 Agent 访问 bundle 几何的唯一空间查询桥。
- `build_spatial_index(bundle)`：为 `polygons.landuse_current` 构建
  `SpatialIndex`（R-tree 空间索引 + bsm→属性映射）。
- `build_constraint_index(bundle)`：为约束多边形（基本农田/生态红线/历史保护
  /开发边界等 10 类）构建 `ConstraintIndex`，供违建检查。
- `compute_cross_layer_relations(bundle)`：批量计算跨层空间关系
  （located_in / intersects / contains），输出与 PlanningKG 消费格式兼容。
- `compute_water_overlap`：找出完全被水面覆盖的 DLBM=3100 地块。
- 架构原则：spatial_ops 做临时空间查询；KG 只存 BSM 与派生属性，不存完整几何。

## 输入输出契约

- `SpatialIndex`：`get_parcel_geometry(bsm)`、`parcels_intersecting(geometry)`
  -> `List[OverlapResult]`、`parcels_within_bbox`、`parcels_within_distance`。
- `ConstraintIndex`：`parcel_in_constraint(bsm)` / `geometry_in_constraint(geometry)`
  -> `List[ConstraintOverlap]`（含 constraint_type/label/rule/重叠面积与百分比）。
- `compute_cross_layer_relations -> {"located_in": [...], "intersects": [...],
  "contains": [...]}`；空 bundle 或无几何返回空 dict。

## 依赖方向

- 依赖 geopandas / shapely（缺失时返回 None/空并记 error）。
- 消费 bundle：`bundle.polygons` / `bundle.lines` / `bundle.points`。
- 被 grounding、selection、conflict、context 等模块消费；不反向依赖它们。

## 禁止行为

- 禁止修改 bundle 几何（索引构建为只读）。
- 禁止将约束多边形作为 KG 实体写入（参考层数据不可修改）。
- 禁止在 `__init__.py` 层绕过本桥直接遍历 bundle 几何。
- 禁止对超大 bbox 做无空间索引的全量笛卡尔比对。
