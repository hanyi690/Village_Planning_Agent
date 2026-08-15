# 规划空间产出链（当前实现映射）

本文只描述当前代码的实际运行路径；目标原则和禁止事项仍以 `docs/design/` 为准。

## 1. 唯一产出链

```text
GIS files / upload records
  → data ingest + SessionDataSnapshot + SpatialWorkspace
  → Assessment / Objectives / Demand / Suitability / Allocation
  → L3 PlanningClaimSet → ProgramProposal → ProgramAssembler → PlanningProgram（规划目标，不是空间成果）
  → TARGET_PROJECTION/GROUND/SELECT
  → ExecutionPlan + target-bound selection
  → EXECUTE workers
  → ParcelChangeSet（实际操作与血缘）
  → PlannedState（EXECUTE 结构化结果）
  → DeliverySpatialSnapshot
       ├── complete_planned_landuse（期末地块）
       ├── current/constraint source refs
       └── checksum/provenance
  → DELIVER render layers
       ├── current_landuse / current_road / boundary / input_constraint
       ├── complete_planned_landuse / planned_changes
       ├── function_zone
       ├── planned_project + planned_project_point
       ├── facility_point
       ├── planned_road
       └── development_axis
  → planning_map.html + planning_preview.png + export package
```

当 `ParcelChangeSet` 没有任何非 `preserve/unchanged` 操作时，快照将自动标记为
`delivery_status=partial`；双面板 PNG 在规划面板显示“地类变更 0 个（全部保留现状）”，HTML
显示 `NO_PARCEL_CHANGES` 和交付事实。项目/设施定位点仍可存在，但不能被解释为地块已经落地。

## 2. 各阶段到底产出什么

| 阶段 | 权威产物 | 语义 | 是否直接给前端 |
|---|---|---|---|
| 数据层 | `SessionDataSnapshot` + `SpatialWorkspace` | 现状地块、道路、边界、约束和属性；正文只在 data/spatial 边界打开 | 否 |
| L3 | `PlanningClaimSet` | 带证据的规划判断、需求、建议措施和不确定性；不可执行 | 否 |
| TARGET_PROJECTION | `target_projection` artifact | 将已组装 `PlanningProgram` 确定性投影为 GROUND 所需的 typed spatial refs；不调用 LLM、不生成分类 | 否 |
| SYNTHESIZE | `PlanningProgram` | 由 claims、候选与领域决策确定性组装的规划目标 | 否 |
| SELECT | `SiteSelectionDecision` | 哪些真实 BSM/候选满足目标 | 否 |
| SELECT | `DemandPortfolio` / `SuitabilitySurface` / `PortfolioDecision` | 需求、候选可行性和显式组合分配 | 否 |
| EXECUTE | `ParcelChangeSet` | 实际新增、重分类、拆分、保留及来源血缘 | 否 |
| EXECUTE | `PlannedState` | EXECUTE 内部结构化 materialization 结果 | 仅用于校验/构建 snapshot |
| DELIVER | `DeliverySpatialSnapshot` | 完整期末地类与所有输入层的统一快照 | 间接 |
| DELIVER | render layers | 前端可消费的 GeoJSON 视图 | 是 |
| DELIVER | PNG/HTML/export package | 静态预览、交互地图、交付文件包 | 是 |

`PlanningProgram` 不是“已经落地的项目”；只有 `PortfolioDecision` 允许的 task 由 EXECUTE 产生 `ParcelChange`，并且经 `DeliverySpatialSnapshot` 投影，才可以显示为 `planned_project`。只有 project worker 写入 `project_ref` 的地块才会生成 `planned_project_point`。zone/facility 的 `intervention_id` 不得回填为 `project_ref`。

## 3. 当前代码入口

- 数据边界：`app.data.model.snapshot.SessionDataSnapshot`、`app.spatial.model.workspace.SpatialWorkspace`
- 交付输入适配：`app.modules.spatial_ops.io.delivery_snapshot.canonical_gis_data_from_workspace`
- EXECUTE 变更：`app.agent.execute.land_design_worker`、`app.modules.schema.contracts.parcel_change_contracts`
- 变更到结构化状态：`app.agent.execute.planned_state_builder`
- 快照：`app.modules.spatial_ops.io.delivery_snapshot`
- 交付图层：`app.agent.deliver.render_layers.build_delivery_render_layers`
- 静态产出：`app.agent.deliver.delivery_renderer`、`app.tools.gis.html_render`、`app.tools.gis.static_render`
- 导出：`app.modules.spatial_ops.output.export_package`
- 前端查询：`app.api.v1.routes.get_map_layers`，只读取 DELIVER 已持久化的 `RenderLayers` artifact；不在 API 层重新读取 `PlannedState` 或调用 renderer

## 4. 当前运行证据与边界

历史 `jintian` GIS + deterministic PlanningProgram 运行记录（不是当前重构分支的新真实 LLM 验收）：

- `current_landuse`：660 个真实地块；
- `complete_planned_landuse`：660 个完整期末地块；
- EXECUTE 变更：3 个；
- `planned_project`：1 个；
- `planned_project_point`：1 个；
- 当前输入没有 facility/road/axis 目标，因此这些层按约定省略；
- 缺少 `construction_zone` 输入时，Manifest 保持 `diagnostic_only`，不能宣称法定完整成果。

该运行证明的是主图 checkpoint/HUMAN resume 和空间交付链，不证明真实 LLM/L3 规划内容已经完整生成。仓库现有 `real-post-l3-*` artifact 的 L3 为非空间 `l3-action-v1`，没有可继续的真实空间规划 checkpoint。

正式产物必须来自同一次 DELIVER 运行；单独调用 renderer 的验证文件不构成正式交付证据。
