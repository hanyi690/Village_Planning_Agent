# spatial_ops.land_balance — 用地平衡表与交付门

## 职责边界

- 计算现状（L1）与规划（L4）地块级用地平衡，产出《土地利用结构调整表》
  （附表2），并评估交付门槛。
- `compute_land_balance(current_parcels, planned_parcels, total_area_ha)`
  -> `LandBalanceTable`：按地类代码聚合现状/规划面积、占比与增减，
  统计农业/建设/生态三类汇总，校验闭合格差（closure_tolerance_pct=0.5）。
- `check_delivery_gate(...)` -> `DeliveryGate`：综合用地平衡是否闭合、
  三线违建数、保护区侵入数、变更地块占比、分区完整性，评估能否交付。

## 输入输出契约

- 输入：L1 `CurrentLandUseParcel` 与 L4 planned 地块（支持对象/dict，
  `_get_attr` 兼容），可选总面积覆盖值。
- 输出契约类型来自 `app.modules.schema.contracts.land_balance_contracts`
  （LandBalanceRow/LandBalanceTable）与
  `delivery_manifest_contracts.DeliveryGate`。
- 面积单位：公顷；代码→名称通过 `code_sets`（GHYTBM_TO_GHYTMC/DLBM_TO_DLMC）
  查找，未命中回退为代码本身。

## 依赖方向

- 依赖 `app.modules.schema.contracts` 类型与
  `app.modules.schema.encodings.code_sets`。
- 被 L3→L4 交付链与 output.export_package 消费。

## 禁止行为

- 禁止修改输入地块。
- 禁止在总面积缺失时伪造面积（以地块累加为准）。
- 禁止对不平衡/违建交付门放行（须如实报告）。
- 禁止在此模块内做几何计算（仅面积聚合）。
