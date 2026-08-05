# Tools GIS _generation — 布局生成编排器

> **定位**：工具层的 GIS 图层生成**编排器**（`pipeline.py`：`run_layout_pipeline`），被 API 路由与工具共享。Batch B 后本目录**仅剩 pipeline.py**。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：`run_layout_pipeline` —— 运行完整 **KG → Conflict → Allocate → Generate** 管线，从空间意图产出 GIS 图层（function_zone / planning_zone / facility_point / axis 等），并接导出（`_run_export_step`）与渲染（`_run_render_step`）步骤。

**不负责**：
- 不实现生成算法（下列能力均已迁至 `modules/`）：
  - 发展轴生成 `AxisBuilder` → `modules/spatial_ops/geometry/axis_builder.py`
  - 词汇驱动自定义功能区 → `modules/spatial_ops/zoning/custom_zone_generator.py`
  - 冲突检测/消解 `ConflictDetector` / `ConflictResolver` → `modules/spatial_ops/conflict/`
  - 指标计算 → `modules/schema/utils/metrics.py`
- 不做 `parse_planning_text`（PARSE 已是独立顶层阶段，Wave A.1 移除）

---

## 输入/输出契约

**入口**：`run_layout_pipeline(intent, gis_data, ...)` → 布局结果（`build_three_way_comparison` 三向对比等）。

**内部步骤**（pipeline.py 模块级函数）：

| 函数 | 职责 |
|---|---|
| `_parcel_from_feature` / `_zone_targets_of` | GeoJSON feature → 地块形状；intent → `ZoneTarget` 列表 |
| `_allocated_from_changes` | 重分类地块打标 `planning_land_use` / `zone_type` |
| `_function_zone_layer` / `_planning_zone_layer` / `_facility_point_layer` / `_axis_layer` | 各图层组装 |
| `run_layout_pipeline` | 主编排（KG → Conflict → Allocate → Generate） |
| `_run_export_step` / `_run_render_step` / `build_three_way_comparison` | 导出 / 渲染 / 对比 |

---

## 依赖方向

```
_generation/pipeline.py → modules/spatial_ops（axis_builder / conflict / zoning）、modules/kg.manager、
                        → modules/data.catalog、modules/schema（PLANNING_ZONE_COLORS / contracts）、
                        → tools/gis._analytics（metrics_calculator）、tools/gis.export（_compute_land_balance）
```

⚠️ **已知遗留边**：`run_layout_pipeline` 仍导入 `app.agent.execute.land_design_worker`（`design_zone_parcel`）——这是工具→agent 的**已知待迁移边**（Batch B 记录在案），领域算法收敛后应移除。

- 禁止：新增任何 `modules/spatial_ops` 中已有能力的重复实现

---

## 禁止行为

- 恢复已迁出的 axis_builder / custom_zone_generator 于本目录（域在 `modules/`）
- 新增第二个布局入口（`run_layout_pipeline` 是 canonical 编排器）
- 扩大工具→agent 的遗留边（应逐步收敛到领域模块）
