# Task 0-docs 报告：关系感知规划当前状态与修改台账

日期：2026-08-17

## 范围

本任务只更新关系感知空间规划的状态说明和事实台账，不修改 backend 生产代码、前端代码、
测试实现或运行 artifact，也不清理当前工作树。

已维护的文档：

- `docs/design/10_IMPLEMENTATION_STATUS.md`
- `docs/design/27_IMPLEMENTATION_VS_DESIGN.md`
- `docs/design/RELATION_AWARE_MODIFICATION_LEDGER.md`

本报告是上述状态文档在 `docs/superpowers/sdd/2026-08-17-relation-aware-gap-closure/`
下的任务级索引；详细五列台账以 `RELATION_AWARE_MODIFICATION_LEDGER.md` 为准。

## 当前结论

当前不能称为完整规划交付。最新可复核状态是：

- 当前活动 demo 没有合法的 `render_layers`、`delivery_spatial_snapshot` 或
  `delivery_manifest` 交付引用，前端 `/map-layers` 必须 fail-closed，不能把空图层解释为规划完成。
- 旧 fresh-GROUND artifact 的 `grounding_result` 只有 161 个 union candidates，且全部
  `hard_constraint=failed`；它不能代表最新 producer 的候选域。
- fresh branch `fresh-ground-20260817-test5` 已重新生成 6,699 个单 BSM candidates：
  3,512 个硬约束通过、3,187 个失败、9 个 unresolved。facility 仍主要是 parcel candidate，
  road/linear/axis 仍是 parcel/corridor candidate，point/line exact feature 仍为 0。
- 同一 fresh branch 尚未合法走完 SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER；
  恢复脚本自动生成的 `resume-*` 分支与 fresh branch 发生冲突，不能由此推断渲染器丢失了规划图层。
- 2026-08-12 历史运行只作为 `HISTORICAL/PARTIAL`：660 个 `complete_planned_landuse`
  要素是 current/baseline 延续，实际 `ParcelChange` 为 0；只有 17 个 project points 和
  16 个 facilities，且没有 planned road/zone/change layer。
- `scripts/render_integrated_map.py` 直接读取静态 current/planned 文件和报告，不能作为主
  workflow 的 `DeliverySpatialSnapshot → RenderLayers → /map-layers` 证据。

## 文档修正

### `10_IMPLEMENTATION_STATUS.md`

- 将当前活动 demo 的空规划图层提升到顶部 P0 状态说明。
- 将 2026-08-12 的历史 checkpoint 数字明确降级为 `HISTORICAL/PARTIAL`，防止把 baseline
  复制、marker points 或历史 named refs 写成当前规划成果。
- 将 DELIVER 和 GIS checkpoint 状态改为以当前 named refs、非 baseline feature 和实际
  `ParcelChange` 为准。
- 修正旧 access tool 诊断：`execute_node.py` 已经通过 `ToolRegistry` 执行注册工具；专用
  access tool bind 和 Explore gate 闭环仍是未完成项。

### `27_IMPLEMENTATION_VS_DESIGN.md`

- 核验日期更新为 2026-08-17。
- 修正 23 号 Explore 设计文档状态：它仍是活跃设计；`retrieve_evidence()` 有局部 producer，
  但 router/query-plan/sufficiency/gate-driven retrieval 尚未形成生产闭环。
- 修正关系契约状态：第一版 `PlanningIntentGraph`、`ConstraintFactor`、
  `RelationSatisfaction` 和 `GroundedPlanningProblem` 已存在并局部传递，但 SELECT 未把
  factor 接入联合求解，VALIDATE/DELIVER 未消费最终关系测量，因此只能标为 PARTIAL。
- 增加当前空图层、standalone PNG 非主链证据和五列 acceptance 门槛说明。

### `RELATION_AWARE_MODIFICATION_LEDGER.md`

新增统一的：

```text
schema → producer → consumer → validator → acceptance
```

台账覆盖 Explore、TARGET_PROJECTION、GROUND、SELECT、facility service、road/linear、
ExecutionPlan/DAG、Worker/PlannedState、VALIDATE/RECONCILE、DELIVER/map-layers。

台账明确：只存在 schema、局部测试、baseline 复制、marker points、standalone PNG 或旧
运行 named refs，都不足以将模块标记为 CURRENT/COMPLETE。

## 验证

执行：

```powershell
git diff --check -- docs/design/10_IMPLEMENTATION_STATUS.md docs/design/27_IMPLEMENTATION_VS_DESIGN.md
```

结果：通过，无 whitespace 错误。

同时核对：

- `docs/superpowers/sdd/2026-08-17-relation-aware-gap-closure/baseline.md`
- `docs/superpowers/sdd/2026-08-17-relation-aware-gap-closure/final-acceptance.md`
- `docs/superpowers/plans/2026-08-17-relation-aware-spatial-planning-gap-closure-v2.md`

三者均保留“真实主链尚未形成可发布图层”的边界；本报告没有把 focused tests 或旧
checkpoint 结果升级为真实 acceptance。

## 未决项与下一步

1. 固定 replay branch 语义，从 GROUND 之前的 checkpoint 重新生成最新
   `GroundedPlanningProblem`，不能继续从缺失 `materialization_role` 的旧 artifact 直接修补。
2. 在同一 fresh branch 重走 SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER，确认
   `PlanningScenario`、`ExecutionResult`、`FinalScenarioValidation`、`DeliveryManifest`、
   `DeliverySpatialSnapshot` 和 `RenderLayers` 的 refs 与 fingerprint 一致。
3. 证明至少一个非 baseline planning feature 能由 `/map-layers` 从同一 run 的 RenderLayers
   named ref 读取，并完成 zero orphan、zero geometry-kind mismatch、zero hard
   violated/not_evaluable/deferred 检查。
4. 完成真实 resume 和局部 replay 验收；没有 provider/data 时只能记录 `SKIP`/明确原因，不能伪造通过。

本任务不宣称 Wave 3 或最终真实金田村验收完成。

