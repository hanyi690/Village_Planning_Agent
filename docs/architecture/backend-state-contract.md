# 当前状态、artifact 与交付边界

> 本文描述当前实现。目标不变量见
> [`../design/14_BACKEND_MODULE_BLUEPRINT.md`](../design/14_BACKEND_MODULE_BLUEPRINT.md)，
> 完成度见 [`../design/10_IMPLEMENTATION_STATUS.md`](../design/10_IMPLEMENTATION_STATUS.md)。

## 1. Owner 表

| 内容 | 当前 owner | 持久位置 / 对外方式 |
|---|---|---|
| 根图路由、阶段、gate、retry、interrupt、branch | `workflow/state.py` 的 `WorkflowState` | LangGraph checkpoint；由 application projection 对外 |
| 阶段业务结果 | 对应 `contracts/` + `domain/` 阶段 | `infrastructure/artifacts/` 的 CAS descriptor/blob |
| 输入资料和快照 | `data/` 的 ingestion/model/snapshot | `SessionDataSnapshot`、`SpatialWorkspace` 和 data-owned sources |
| 运行事件 | `infrastructure/events/repository.py` | SQLite `run_events`；SSE 在线队列由 `connection_hub.py` 管理 |
| 阶段审计 | `infrastructure/reports/step_report.py`、`stage_report.py` | 报告/事件持久层；不是业务事实副本 |
| 执行结果 | `domain/materialization/` + spatial changeset/planned state | artifact refs；后续阶段只消费根引用 |
| 最终空间快照 | `domain/delivery/` / `spatial/delivery/` | `DeliverySpatialSnapshot`；地图、导出和交付清单共享其 digest |
| 公开结果 | `application/projections/` | API response models、SSE event projection、map/delivery projection |

## 2. WorkflowState 允许保存什么

`WorkflowState` 只保存控制和引用：会话/运行/分支身份、阶段、状态、context reference、
artifact refs、gate/interrupt/terminal refs、完成维度、retry 和必要的消息/审计控制字段。

它不保存：

- 完整 GIS FeatureCollection、空间索引、文件正文或渲染图层；
- 完整 `PlanningProgram`、`GroundingResult`、`SiteSelectionDecision`、`PlannedState`、
  `ValidationReport` 等业务 payload；
- 由多个阶段各自维护的 `latest`、隐式副本或第二套事件序号。

阶段节点通过 `infrastructure/artifacts/runtime.py` 加载 typed artifact；产物 key → 契约类型的
权威注册表是 `workflow/stage_adapter.py::_KEY_BY_TYPE`。根图只根据 gate
artifact 和 refs 做路由。缺少或无法验证的 gate 必须 fail closed，不能默认 PASS。

## 3. 数据、证据和空间边界

- 上传文件先由 `data/ingestion/` 处理；快照和来源信息由 data 层拥有。
- 空间计算由 `spatial/` 和其 ports/adapters 负责；领域层消费 typed spatial result。
- 证据检索由 `evidence/` 负责，KG、RAG、Gazetteer 等外部实现位于 `infrastructure/`。
- LLM、工具和 provider 只能通过 contracts/ports 接入；它们不能直接修改规划事实。
- 不得新增把裸 GIS、文件路径或 `latest` 塞进 graph state 的通道。

## 4. EXECUTE → DELIVER 不变量

```text
PlanningProgram / SiteSelectionDecision
  → ExecutionPlan
    → WorkerResult
      → ParcelChangeSet
        → PlannedState
          + current source layers
          → DeliverySpatialSnapshot
            → RenderLayers / land balance / HTML / PNG / GeoJSON / manifest
```

EXECUTE 必须使用显式分类、目标和选址决定；不能用现状 `dlbm`、项目名称、KG alias 或
advisory crosswalk 静默补规划编码。DELIVER 必须从同一个空间快照生成所有输出，不能让
renderer、exporter、土地平衡和 API 各自选择事实源。

若没有实际变化、存在未决分类、空间证据不足或质量检查失败，交付必须显式标记
`partial` / `diagnostic_only` / HUMAN；复制现状图不是规划完成。

## 5. Resume 与幂等

HUMAN resume 必须使用真实 checkpoint 的 interrupt identity，并通过
`application/commands/resume_*` 和 `application/recovery/resume_service.py` 生成恢复计划。
历史 checkpoint 恢复应创建新 branch；父 artifact 可复用，但新的 descriptor 必须能证明
parent digest 和 context identity。

LangGraph 的 interrupt 恢复可能重放中断节点之后的调用，因此中断前只允许可重放或幂等
操作；不可逆副作用放在恢复之后。事件发布、artifact 写入和 named ref 更新均应支持安全重试。

## 6. 当前迁移边界

根图已经使用 `WorkflowState` 和 artifact refs，v1 查询也通过 application projection；
但部分阶段仍有迁移载荷和兼容字段，真实 provider、进程重启 resume、完整规划变化和多
进程事件 outbox 仍需按状态台账验收。契约测试通过不能单独关闭这些 `PARTIAL/GAP`。
