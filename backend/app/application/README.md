# Application 应用层

> 本 README 以 `backend/app/application/` 实际代码为准（核验日期 2026-08-15）。

## 定位

应用层承载“用例（use case）”：把 API transport 的请求翻译成对 workflow/runtime/data 的
调用，并把 checkpoint、artifact 和事件还原成前端可消费的公开 projection。它**不是**第二个
领域算法实现，也不直接读写 artifact 目录或拼装 GIS 事实。

调用方向：`app/api/v1/routes/*` → `app/application/{commands,queries,projections}` →
`app.infrastructure.runtime.PlanningRuntimeService` / `app.database.operations` /
`app.data.ingestion` / `app.workflow`。

## 目录职责

| 目录/文件 | 职责 |
|---|---|
| `commands/` | 写侧用例：创建会话、恢复工作流、提交人工决定 |
| `queries/` | 读侧查询：artifact、checkpoint、delivery、map-layers、run events、workflow state |
| `projections/` | 公开视图模型：SessionProjection、DeliveryProjection、MapLayerCollection、HumanReviewProjection、public event |
| `recovery/` | 恢复计划构造（`resume_service.py`）：分支判定、interrupt 校验、artifact 复用验证 |
| `sessions/` | 会话生命周期（创建/删除/清理）与 session bundle 构建/恢复 |
| `interrupts.py` | 从 checkpoint gate channel 收集 HUMAN review 项目 |
| `unit_of_work.py` | 命令侧 Port 协议（SessionRepository/UploadIngestion/PlanningStarter/Runtime）与事务包装 |

## 关键入口

- `commands/create_session.py::CreateSessionService`：接收 `CreateSessionCommand`，
  校验项目名、摄取上传文件（`data/ingestion/upload.process_uploaded_file`）、构造初始 state
  （`workflow/plan_state/state_factory.StateFactory`）、写 `planning_sessions` 表，并通过
  `PlanningRuntimeService.trigger_planning_execution` 在 `TaskSupervisor` 中启动规划运行。
- `commands/resume_workflow.py::ResumeWorkflowService`：`POST /resume` 的用例。
  区分 `interrupt`（对当前 HUMAN interrupt 恢复）与 `checkpoint`（对历史 checkpoint 分叉），
  通过 `PlanningRuntimeResumePort` 调用 runtime 的 `resume_interrupt` / `fork_checkpoint`。
- `commands/resume_checkpoint.py`：把 checkpoint 快照分类（pending interrupt / replay /
  fork）并构造 `ResumePlan`（`build_resume_plan` + `_PlanBuilderDefault`）。
- `commands/submit_human_review.py::SubmitHumanDecisionService`：`POST /human-review` 用例，
  用 `event_id` 做 compare-and-set，防重放；`submit_human_decision.py` 是其稳定导入路径。
- `queries/run_events.py::RunEventQueryService`：SSE `sync`/`open_stream`/`close_stream`，
  统一从 `infrastructure/events/repository.py` 回放事件并管理在线队列。
- `queries/checkpoint.py`：checkpoint 写完成等待（`CheckpointPersistenceManager`）与
  层报告/阶段查询。
- `projections/session.py`、`projections/delivery.py`：把 checkpoint state / artifact
  投影为 `contracts.py` 中定义的公开 DTO；找不到时抛 `ProjectionNotFoundError` → 404。

## 数据流

```text
POST /api/v1/sessions
  → session_create.py → CreateSessionService
    → data/ingestion/upload → database.operations（planning_sessions）
    → StateFactory.create → PlanningRuntimeService.trigger_planning_execution
GET /state、/delivery、/map-layers、/human-review
  → queries/* → projections/* → api/v1/contracts.py DTO
GET /events、/events/sync
  → queries/run_events → infrastructure/events/repository + connection_hub
POST /human-review、/resume
  → commands/submit_human_review、commands/resume_workflow
```

## 边界规则

- 应用层通过 Port（`unit_of_work.py`、`RuntimePort`、`ArtifactReaderPort` 等）依赖底层，
  不在命令里直接 import 具体 provider。
- 公开结果只从 `projections/` 出；内部 `WorkflowState`、artifact payload 不直接上浮。
- 删除会话由 `sessions/session_service.py::SessionService.delete_session` 协调清理
  tasks/context/bundle/kg/artifacts/checkpoint/SSE/evidence/provider failures。
