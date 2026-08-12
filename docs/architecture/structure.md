# 项目结构与目标实现映射

本文档只描述当前代码的实现边界和迁移方向。规范性设计以
[`docs/design/14_BACKEND_MODULE_BLUEPRINT.md`](../design/14_BACKEND_MODULE_BLUEPRINT.md)
为准，阶段完成情况以
[`docs/design/10_IMPLEMENTATION_STATUS.md`](../design/10_IMPLEMENTATION_STATUS.md)
为准。

## 1. 当前运行拓扑

```text
API / SSE
  → application queries / commands
    → services.runtime（LangGraph checkpoint 与执行生命周期）
      → workflow.root_graph
        → L1 / L2 / L3
        → TARGET_PROJECTION → GROUND → SELECT → EXECUTE
        → VALIDATE → RECONCILE → DELIVER
          → DeliverySpatialSnapshot
            → render / export / land balance / manifest
```

根图已改用 `WorkflowState` 编译；阶段节点通过
`workflow/runtime_adapter.py` materialize 一个临时 stage view。该 view 在写入
checkpoint 前固化为 `workflow_progress` artifact，根 checkpoint 只保存控制字段和
artifact refs。它不是前端协议，也不是最终阶段模型；下一步继续把 progress 拆为 typed
stage artifacts。

## 2. 目录职责

```text
backend/app/
├── api/                         # HTTP、SSE、稳定 contract adapter
├── application/                # 面向用例的 query/command 与公开投影
│   └── queries/workflow_state.py
├── workflow/                   # 根图、阶段适配器、阶段审计、阶段 service
│   ├── root_graph.py
│   ├── state.py                # ref-only WorkflowState 投影
│   └── stages/                 # projection/ground/select/execute/.../deliver
├── agent/                      # 尚未迁移完的 L1-L3、HUMAN、EXECUTE 子图与交付适配器
├── modules/
│   ├── data/                   # 上传文件、SessionDataSnapshot、SpatialWorkspace
│   ├── schema/                 # Pydantic contracts、artifact descriptor、分类闭集
│   ├── spatial_ops/            # 空间算法、snapshot IO、土地平衡、导出底层能力
│   ├── kg/                     # 语义查询、别名、BSM、证据索引；不做规划编码决策
│   └── context/                # PlanningContext 与上下文索引
├── infrastructure/             # CAS artifact repository、LLM、持久化适配器
├── services/                  # 运行生命周期、SSE、数据库/外部适配器；不再拥有 StepReport
└── tools/                     # 外部工具和 GIS 技术适配器；不拥有业务状态
```

## 3. 模块间单向边界

| 边界 | 允许 | 禁止 |
|---|---|---|
| API → application | session command、control projection、delivery projection | 读取 `AgentState` 原始 payload、拼接 GIS 状态 |
| workflow → data | 传 `context_ref`、`SpatialWorkspace` adapter、artifact refs | 把完整 GIS / 报告正文写入 checkpoint |
| agent → domain | 读取 bundle/context，产出 typed claim/decision | 在 worker 内从名称、`dlbm` 或 KG 推导规划编码 |
| EXECUTE → spatial_ops | `ClassificationDecision → GeometryOperation → ParcelChange` | worker 自行重复面积、分类、地块读取 |
| DELIVER → spatial_ops/output | 只接收同一 `DeliverySpatialSnapshot` | 从 `PlannedState`、`gis_data` 或历史文件重新组装期末图层 |
| renderer/exporter/land balance | 只读 snapshot | 各自选择 current/planned 来源 |

## 4. 阶段产物流

```text
Data layer
  → SessionDataSnapshot / PlanningContext / SpatialWorkspace
  → L1/L2/L3 artifacts
  → PlanningProgram / IntentCompilationResult
  → GroundingResult
  → PortfolioDecision / SiteSelectionDecision
  → ExecutionPlan / ExecutionResult(root → ParcelChangeSet, PlannedState, task records)
  → ValidationReport / ReconciliationReport / DeferralLedger
  → DeliverySpatialSnapshot
  → RenderArtifacts / ExportResult / DeliveryManifest
```

当前实现中的分类决策边界：`domain/program/classification.py` 只接受显式闭集
`ClassificationDecision`，并为缺失的 polygon/parcel 目标生成 `classification_decision_required`
问题。L3 gate 将其投影为 HUMAN request；`root_graph.py` 在 HUMAN resume 中持久化新的
`PlanningProgram` artifact，然后从 TARGET_PROJECTION 重新走空间链。EXECUTE 不从项目名称、
现状 `dlbm` 或 KG 推导规划编码。

checkpoint 只保存控制字段和 `ArtifactDescriptor` 引用；阶段 payload、GeoJSON、
渲染文件和导出文件由 Artifact Store / data layer 持有。`StepReport` 是审计事件，
记录阶段输入输出引用、耗时、质量摘要和错误，不是第二个业务状态仓库。

## 5. 迁移中的明确切片

1. 根图已切换为 `WorkflowState`；`runtime_adapter` 只作为迁移边界，不能新增业务字段。
2. 新 application/API 查询已经统一由 `control_state_from_checkpoint()` 生成
   `WorkflowState`；不得新增对 raw `AgentState` 的前端读取。
3. `workflow_progress` 是当前阶段迁移载荷的唯一临时 artifact owner；下一阶段按
   L1/L2/L3 progress、conversation 和 gate contract 拆分它，并删除旧字段读取。
4. DELIVER 的唯一空间真相是 `DeliverySpatialSnapshot`：同一 snapshot checksum
   必须贯穿 current/planned/render/export/land balance。
