# spatial_ops.allocation — PuLP MIP 全局分区分配

## 职责边界

- EXECUTE zone 合成的全局分配边界：给定各分区面积目标与候选地块列表，
  求解全局分配 MIP，使每个地块至多分配给一个分区、每个分区分配面积不超过目标。
- `allocate_zones(targets, candidates, constraints, metadata)
  -> ZoneAllocationSolution`：纯函数，从不因不可行而抛异常。
- `PuLPZoneAllocator`：`app.modules.ports.zone_allocator.ZoneAllocatorPort`
  的实现，内部委托 `allocate_zones`。
- 黑名单：约束中 `preserve/blacklist/restricted` 类型的地块不可被分配，
  报告为 unassigned_bsms 而非报错。
- 无 pulp 或不可行时返回 `feasible=False` 并给出 diagnostics。

## 输入输出契约

- 输入：`targets: {zone: target_ha}`；`candidates: {zone: [条目]}`，条目可为
  纯 bsm 字符串 / `{"bsm", "area_ha"}` dict / 暴露 bsm/area_ha/area_sqm 的对象；
  `metadata["parcel_by_bsm"]` 作为面积兜底。
- 输出：`ZoneAllocationSolution`（assignments: ZoneAssignmentEntry[] /
  unassigned_bsms / objective_value / feasible / diagnostics）。
- 契约类型来自 `app.modules.schema.contracts.execution_plan_contracts`。

## 依赖方向

- 实现 `app.modules.ports.zone_allocator.ZoneAllocatorPort`。
- 依赖可选 `pulp`（缺失时跳过并记录 diagnostics）。
- 被 EXECUTE zone 合成 / zoning.custom_planning 的分配输入消费。

## 禁止行为

- 禁止对黑名单地块产生分配。
- 禁止在不可行时抛异常或产生部分未声明的分配。
- 禁止修改输入 targets/candidates/metadata（只读构建模型）。
- 禁止在求解器非 Optimal 时返回可行结果。
