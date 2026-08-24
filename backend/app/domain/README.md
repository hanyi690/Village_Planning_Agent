# Domain 领域层

> 本 README 以 `backend/app/domain/` 实际代码为准（核验日期 2026-08-15）。

## 定位

规划业务决策的实现层：认知分析、目标/规划程序组装、接地、选址、执行物化、校验、对账
与交付。`domain/` 只通过 `contracts/` 与 Port 消费输入，不反向依赖 API、UI 或 provider。

## 目录职责

| 目录 | 职责 | 关键文件/产出 |
|---|---|---|
| `assessment/` | L1 现状分析：维度 worker、聚合、gate | `analysis_node.analyze_dimension`、`aggregate.l1_aggregate`、`gate.evaluate_l1_gate` → `L1Snapshot`/`AnalysisReport`/`GateDecision` |
| `objectives/` | L2 规划思路：worker、聚合、gate | `aggregate.l2_aggregate` → `L2Strategy`/`StrategyConflict` |
| `program/` | L3 详细规划：claim 生成/组装/语义修复/分类 | `worker.analyze_l3_dimension`、`assembler.assemble_planning_program`、`aggregate.l3_aggregate`、`classification_generator`、`semantic_repair`、`flash_unit_repair`、`unit_normalization`；`target_projection/` 子目录：`compile.py` 组装 SpatialReferenceSpec |
| `ground/` | 接地聚合：把空间引用绑定到证据与候选 | `aggregate.ground_aggregate`、`anchors.py`（L1 锚点接地） |
| `allocation/` | SELECT：需求→适宜性→ScenarioSet/批准输入 | `demand`（在 `demand/`）、`suitability`（在 `suitability/`）、`scenario_optimizer`/`select_gate`/`approval_input` |
| `suitability/` | 候选适宜性评估 | `service.build_suitability_surface`、`terrain`/`spatial_factors` → `SuitabilitySurface` |
| `demand/` | 需求组合 | `service.derive_demand_portfolio` → `DemandPortfolio` |
| `materialization/` | EXECUTE：执行计划物化为地块变更 | `execute_agent.build_execute_agent_graph`（worker 子图）、`approved_plan_builder`、`execution_boundaries`、`merge`、`planned_state_builder`、各类 materializer worker → `ParcelChangeSet`/`PlannedState` |
| `validation/` | VALIDATE/RECONCILE：校验、对账、修复指令 | `validate.validate_aggregate`、`validate_checks`、`reconcile`、`reconcile_gate`、`repair_directives`、`repair_impact`、`adjustment_executor`、`report_service` → `ValidationReport`/`RepairDirectiveCompilation`/`ReconciliationReport` |
| `delivery/` | DELIVER：交付聚合、快照构建、清单 | `aggregate.deliver_aggregate`、`delivery_snapshot_builder.build_spatial_delivery_products`、`delivery_validator`/`delivery_renderer`/`delivery_exporter`/`render_layers`/`deferral_ledger`/`checks`/`gate` → `DeliveryManifest`/`DeliverySpatialSnapshot`/`RenderLayers` |
| `common/` | 跨领域辅助 | `context_guard`、`execution_evidence`、`gate_progress` |

## 数据流（阶段主链）

```text
L1 analysis → L2 objectives → L3 program（PlanningClaimSet → PlanningProgram）
  → TARGET_PROJECTION（domain/program/target_projection）
  → GROUND（domain/ground + spatial/grounding）
  → SELECT（demand → suitability → allocation）
  → EXECUTE（materialization → ParcelChangeSet/PlannedState）
  → VALIDATE（validation → ValidationReport/RepairDirectives）
  → RECONCILE（validation/reconcile → ReconciliationReport）
  → DELIVER（delivery → DeliverySpatialSnapshot/DeliveryManifest）
```

## 边界规则

- 阶段业务结果写入 `infrastructure/artifacts`（CAS）；`domain/` 不直接写 checkpoint 业务载荷。
- gate 决策由 `domain/*/gate.py` 计算，路由由 `workflow/root_graph.py` 消费。
- 空间计算不在 domain 内实现：几何/接地/网络计算在 `app/spatial/`，domain 消费 typed 结果。
