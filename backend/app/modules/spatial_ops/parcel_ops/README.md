# spatial_ops.parcel_ops — 地块几何变更面

## 职责边界

- 地块几何/属性变更原语，是系统内唯一发生 Shapely 几何突变的位置。
- `reclassify_parcel`：改地类码（几何不变，最常用"字段计算器"式操作）。
- `modify_parcel`：属性字段修改（几何不变）。
- `merge_parcels`：多地块 union 合并（自动/指定新 BSM）。
- `split_parcel_by_geometry`：按给定线/面几何切分。
- `create_parcel`：从零新建地块（无 derived_from）。
- `apply_operations`：批量操作入口，未变更地块按原代码 reclassify 保留，
  输出 (planned_parcels, warnings)。
- 所有操作返回 PlannedParcel 兼容 dict（含 operation 标记与 derived_from_bsms）。

## 输入输出契约

- 输入：类型化地块或 dict（bsm/geometry/dlbm/area_sqm/area_ha），
  通过 `_get_attr` 兼容两者。
- 输出 dict 关键字段：bsm / planning_land_use / zone_type / area_ha /
  geometry（JSON 字符串）/ derived_from_bsms / derived_from_zone_target /
  operation（reclassify|modify|merge|split|create）。
- 合并/切分失败返回 None 或空列表（不抛异常）。

## 依赖方向

- 依赖 shapely / geopandas（几何突变）与 `app.utils.crs_engine`。
- 被 EXECUTE 操作管线与 land_balance 消费。

## 禁止行为

- 禁止修改输入 parcel 对象（必须返回新 dict）。
- 禁止在 apply_operations 之外自行生成 planned 地块。
- 禁止丢失 derived_from 血缘（每个操作必须记录来源 BSM）。
- 禁止对无效几何静默产出（须 buffer(0) 修复或失败返回）。
