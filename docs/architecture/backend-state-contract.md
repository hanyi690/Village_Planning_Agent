# 后端状态与交付边界

本文档是实现映射，不替代 `docs/design/14_BACKEND_MODULE_BLUEPRINT.md` 的目标架构。

## 1. 状态所有权

| 数据 | 当前 owner | 持久位置 | 对外方式 |
|---|---|---|---|
| 图路由、阶段、Gate、HUMAN、重试 | LangGraph `WorkflowState`；临时 stage view 存为 `workflow_progress` artifact | checkpoint 只保存控制字段与 refs | application 投影为 `WorkflowState` 后进入 API |
| 稳定控制投影 | `app/workflow/state.py` | 不单独存储，由 checkpoint 派生 | `SessionProjection`、resume 查询 |
| 阶段业务结果 | 对应 Pydantic contract | CAS Artifact Store | 通过显式 artifact endpoint 或交付投影 |
| EXECUTE 结果 | `ExecutionResult`（精确引用 `ParcelChangeSet`、`PlannedState`、任务记录）+ `DeferralLedger` | CAS Artifact Store | 后续阶段只读取 `ExecutionResult` 根引用 |
| 完整期末空间状态 | `DeliverySpatialSnapshot` | CAS Artifact Store + layer files | `MapLayerCollection`、渲染/导出文件 |
| 交付结论 | `DeliveryManifest` | CAS Artifact Store | `DeliveryProjection` |
| 阶段审计 | `modules/evidence.StepReport` | 数据库/事件持久层 | SSE、诊断查询 |
| 对外运行事件 | `EventRepository`（历史/序号）+ `EventConnectionHub`（在线队列）+ `RunEventQueryService`（replay/sync） | SQLite `run_events` + 进程内在线队列 | 历史序号可跨重启恢复；outbox/跨进程发布仍在迁移 |

## 2. WorkflowState 查询边界

`backend/app/workflow/state.py` 中的 `WorkflowState` 只包含：会话/分支标识、阶段、
状态、context ref、artifact refs、gate/interrupt/terminal ref 和 retry。它不包含：

- GIS FeatureCollection、文件内容、空间索引或渲染图层；
- 报告正文、消息历史、worker result 或完整 Pydantic 业务 payload；
- `PlannedState`、`ParcelChangeSet` 等阶段结果的内联副本。

`control_state_from_checkpoint()` 是唯一的 checkpoint-to-public 投影点。迁移期的
`runtime_adapter` 只在节点边界加载 `workflow_progress`，新的 application 模块不得
读取它。`load_workflow_state()` 是 API 的查询入口。

原始 checkpoint 仍只能由 `PlanningRuntimeService` 和 resume command 使用，因为真实
LangGraph resume 需要完整 cursor、task interrupt 和分支信息。不得为了“精简”而把真实
resume 改成从数据库状态重新拼装。

## 3. 数据层与 Agent 边界

用户 GIS 的完整内容由上传文件、`SessionDataSnapshot` 和 `SpatialWorkspace` 保存。
Agent 只接收 context/bundle 的引用或 data-owned workspace adapter；原始 GIS 不进入
前端投影，也不得新增 `InjectedState("gis_data")`、`gis_bundle` 或 `allocated_geojson`
作为图状态通道。缺少 workspace 时应显式失败，不制造空的现状图层。

## 4. EXECUTE 与 DELIVER 不变量

```text
ClassificationDecision
  → GeometryOperation
    → ParcelChange
      + current source layers
        → DeliverySpatialSnapshot
          → render / export / land balance / DeliveryManifest
```

EXECUTE 负责把明确的分类决策落成几何操作和 parcel change；KG、现状 `dlbm`、目标
名称及 advisory crosswalk 不能生成规划编码。DELIVER 只从同一个 snapshot 读取完整
现状、完整规划、变化 overlays、constraints、checksums 和 provenance。

交付渲染必须实际包含一张 PNG 的两个面板：左侧 current、右侧 planned；两侧按地类
分类着色并保留细地块边界，变化项目和定位点作为独立 overlay。HTML、PNG、GeoJSON、
土地平衡和 manifest 必须引用同一 snapshot checksum。若源层缺失、几何无法修复或
规划结果未通过质量检查，交付进入 `diagnostic_only`/`partial`，禁止回退到历史文件。

## 5. 真实 resume 与审计

- HUMAN resume 必须使用当前真实 checkpoint 的 interrupt event id 和
  `Command(resume=...)`；不得用伪造 state 直接调用后续节点。
- checkpoint fork 从指定真实 checkpoint 派生新 branch，沿用父 artifact blob 但写新
  descriptor；named ref 写入必须幂等，重试不能产生不同内容。
- 每个阶段由 `audited_stage()` 生成 StepReport，记录输入 refs、输出 refs、gate、错误
  和质量摘要；DELIVER 额外记录 snapshot checksum、PNG/HTML 路径和 render quality。

## 6. 当前迁移状态

`WorkflowState` 根图切换已完成；`workflow_progress` 内部拆分仍是已知迁移中状态。
已经完成的边界是：
独立阶段 service、CAS artifact refs、data-owned workspace、真实 HUMAN/checkpoint
resume、DeliverySpatialSnapshot 单一空间输入和双面板交付。后续删除 legacy state
字段必须以“静态依赖扫描 + 真实 resume + 实际读取渲染结果 + StepReport”四项同时通过
为准，不能只以单元测试通过为准。
