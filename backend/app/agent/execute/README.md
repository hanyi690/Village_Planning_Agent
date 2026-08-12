# agent/execute 子包（EXECUTE 空间执行）

> EXECUTE 阶段：`PortfolioDecision` + `ExecutionPlan` → `ParcelChangeSet` → `PlannedState` → execution review。
> 多 worker 子图把 SELECT 的选址决策编译为完整规划状态。**本目录是整个 agent 层最核心的目录**：它唯一负责把"选好的地块 + 用地目标"落地为确定性空间变更集与规划成果结构。

---

## 职责边界

**做**：构建并运行 EXECUTE 多 worker 子图（`build_execute_agent_graph`，11 节点）；按 `ExecutionPlan` 路由子任务（`route_tasks`：layout 恒跑 + project/facility/axis/road 按需）；`prepare_inputs` 一次性建 `parcel_by_bsm` 索引、应用约束调整、装配 `ExecutionPlan`；5 个 worker（project / zone / facility / axis / road）各自产出统一 `WorkerResult`（**不改共享状态**）；`merge_worker_results` 合并（BSM 冲突检测 + layout 去重 + `ParcelChangeSet`）；`geometry_materialize` 校验几何变更有效性；`planned_state_builder` 把变更集转 `PlannedState`；`execution_review` 做执行级检查（输入/输出完整性、变更血缘、几何有效性、worker 冲突）产出 `validation_result`；`_write_l4_node` 把规划实体写回 KG（L4）。

**不做**：不重读规划文本、不重选地块、不重映射现状用地（只编译 `SiteSelectionDecision + ExecutionPlan`）；不做完整 VALIDATE 聚合（面积守恒/硬约束/拓扑/可达性/阶段归因在 post-L3 的 VALIDATE/RECONCILE 完成）；`execution_review` 不重复完整校验。

### 目录文件

| 文件 | 职责 |
|---|---|
| `execute_agent.py` | ★ 子图构建器 + 全部节点/worker（`build_execute_agent_graph`、`_route_tasks_node`、`_zone_worker`、`_write_l4_node` 等） |
| `execute_state.py` | `ExecuteAgentState`（Pydantic，含 `worker_results` upsert reducer） |
| `land_design_worker.py` | `design_project_footprint` / `design_zone_parcel` / `design_facility_parcel` / `build_parcel_change_set`（确定性变更生产） |
| `merge.py` | `merge_worker_results`：统一合并（纯函数，无 I/O） |
| `planned_state_builder.py` | `changeset_to_planned_state`：`ParcelChangeSet` → `PlannedState`（确定性） |
| `review.py` | EXECUTE 审查包构建（纯 dict） |
| `road_generator.py` | 道路执行适配器：`RoadTarget` → `app/modules/spatial_ops/road` 确定性道路规划服务（Stage 2.6/3/4 门控） |
| `vocab_extractor.py` | L3 报告 → session 功能区词汇表提取器（LLM 只产"类别定义"，不产几何/BSM；留在 agent 层） |

### 图拓扑（来自 `build_execute_agent_graph` 实际边）

```
 START → route_tasks → prepare_inputs → project_worker → zone_worker
           └────────────────────────────► [facility_worker ‖ axis_worker]   （静态扇出菱形，并行）
                                             └──────────────► road_worker
                                                                │
                                         merge_worker_results ←─┘
                                                                ▼
                                         geometry_materialize → planned_state_builder → execution_review
                                                                                        │
                    ┌───────────────────────────────────────────────────────────────────┤
                 retry(≤3 轮 → zone_worker)                                        pass/human → END
```

- **retry 环**：`execution_review` 失败时回 `zone_worker`，`validation_round >= 3` 后转 `human`。
- **worker_results** 用 upsert reducer，重试只替换对应 worker 条目，保证扇入/扇出与重试合并正确。

### 与 spatial_ops 的消费关系

| 领域模块 | 消费点 |
|---|---|
| `modules/spatial_ops/selection` | `_project_worker` 读 `SiteSelectionDecision.selected_combination`（`select_parcel` / `parse_scale_ha`） |
| `modules/spatial_ops/parcel_ops` | `land_design_worker`：`create_parcel` / `merge_parcels` / `reclassify_parcel` |
| `modules/spatial_ops/geometry/subdivision` | `land_design_worker`：`apply_setback` / `split_for_footprint`（OBB 切分） |
| `modules/spatial_ops/geometry/axis_builder` | `_axis_worker`：`AxisBuilder` |
| `modules/spatial_ops/allocation` | `_zone_worker` 空 `candidate_bsms` 分区经 `PuLPZoneAllocator`（MIP）求解；不可行 → `design_unresolved`，绝不静默跳过 |
| `modules/spatial_ops/zoning` | EXECUTE 不从词汇表推导规划分类；custom zone 必须先形成 `ClassificationDecision`，否则进入 `classification_unresolved`。 |
| `modules/spatial_ops/road` | `road_generator.py`：`build_road_network` / `run_stage4_road_planning` 等 |

## 输入/输出契约

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 执行计划 | `app/modules/schema/contracts/execution_plan_contracts.py` | `ExecutionPlan`、`WorkerTask`、`WorkerType`、`WorkerResult`、`RoadPlanResult`、`ParcelAllocationProblem`、`ZoneAllocationSolution`、`ZoneAssignmentEntry` |
| 变更集 | `app/modules/schema/contracts/parcel_change_contracts.py` | `ParcelChange`、`ParcelChangeSet`（含 `area_conservation_verified` / `geometry_validity_verified`）、`FacilityChange`、`RoadChange` |
| 规划状态 | `app/modules/schema/contracts/planned_state_contracts.py` | `PlannedState`、`PlannedParcel`、`PlannedZone`、`PlannedFacility`、`PlannedRoad`、`PlannedAxis` |
| 输入分配 | `app/domain/allocation/model.py` | `PortfolioDecision`（通过 `ExecutionPlan.portfolio_decision_ref` 引用） |
| 输入任务 | `app/modules/schema/contracts/execution_plan_contracts.py` | `ExecutionPlan`、`WorkerTask`；每个 task 带 target binding 和输入 refs |
| 选址审计 | `app/modules/schema/contracts/selection_contracts.py` | `SiteSelectionDecision`、`LandDesignBrief` 由 post-L3 独立 ref 读取，不嵌入 ExecutionPlan |

**子图边界**：输入 `ExecuteAgentState`（由 post-L3 `execute_node` 从当前 `AgentState` 构造）；输出 `parcel_changeset`、`planned_state`、`layout_configs`、`execution_errors`、`validation_result`。

## 依赖方向

**可导入**：`app/agent/execute/*` 内部模块、`app/modules/spatial_ops/{selection, parcel_ops, geometry, allocation, zoning, road, land_balance}`、`app/modules/schema/contracts/*`、`app/modules/kg/manager` + `builder/layer4`（仅 `_write_l4_node` 内局部导入）。

**禁止导入**：上层 stage（`l1_observe`/`l2_strategize`/`l3_plan`/`target_projection`/`ground`/`select`/`validate`/`reconcile`/`deliver` 的实现）；直接 import `app/agent/ground` 或 `app/agent/select` 内部函数（只经 typed 契约交互）。

## 禁止行为

- 不得在 EXECUTE 内重读文本 / 重选地块 / 重映射现状用地（违反"只编译"原则）。
- 不得静默跳过空 `candidate_bsms` 分区的 MIP 分配失败（必须记 `design_unresolved` 诊断，禁止静默丢弃候选失败）。
- 不得让 worker 直接改共享状态——必须返回 `WorkerResult` 由 `merge_worker_results` 统一合并。
- `execution_review` 不得重复完整 VALIDATE 聚合（那是 post-L3 VALIDATE 的职责）。
- 不得绕过 `_route_after_execution_review` 的 3 轮重试上限直接放行。
- `vocab_extractor` 的 LLM 不得产几何 / BSM（只产类别定义），几何一律走 `custom_zone_generator`。

---

## 相关文档

- `../README.md` — agent 编排层总览
- `../../workflow/stages/execute.py` — EXECUTE 子图在主图中的调用（`execute_node`）
- `../select/README.md` — SELECT（上游：`SiteSelectionDecision`）
- `../validate/README.md` — VALIDATE（下游：消费 `ParcelChangeSet` + `PlannedState`）
- `app/modules/spatial_ops/` — 空间算子域
