# 当前项目结构

> 本文是实现映射，不是目标蓝图。状态以
> [`../design/10_IMPLEMENTATION_STATUS.md`](../design/10_IMPLEMENTATION_STATUS.md) 为准。

## 1. 启动与运行路径

```text
uvicorn app.main:app
  → app.bootstrap.lifespan
      → database.init_async_db
      → bootstrap.CompositionRoot
      → infrastructure.runtime.PlanningRuntimeService
  → app.api.routes
      → app.api.v1.routes/*
  → application command/query/projection
  → workflow.root_graph
      → L1/L2/L3 workers
      → TARGET_PROJECTION → GROUND → SELECT → EXECUTE
      → VALIDATE → RECONCILE → DELIVER
```

本地后端启动目录是 `backend/`，入口模块是 `app.main:app`。FastAPI 的 `/docs` 和 `/redoc`
由应用自动生成；具体请求/响应以 v1 路由上的 Pydantic contract 为准。

## 2. 当前目录职责

```text
backend/app/
├── api/              HTTP、SSE、v1 路由和 transport 适配
├── application/      command、query、projection、resume 和 session 用例
├── bootstrap/        FastAPI lifespan 与依赖组合根
├── contracts/        artifact、domain、spatial、workflow 的类型契约
├── core/             配置、LLM 基础设施和 tracing
├── data/             上传、摄取、catalog、快照和外部数据适配
├── database/         数据库引擎、模型和持久化操作
├── domain/           assessment、objectives、program、ground、allocation、
│                     materialization、validation、delivery 等业务决策
├── evidence/         证据索引、检索、KG-facing evidence 模型
├── infrastructure/   artifact、事件、runtime、LLM、KG、RAG、报告和 provider 适配
├── spatial/          geometry、grounding、query、allocation、change、delivery、validation
└── workflow/         根图、控制 state、L1/L2/L3 层编排、阶段节点、对话和工具节点
```

## 3. 依赖边界

```text
api
  → application
    → workflow / domain / contracts
      → data / spatial / evidence
        → infrastructure adapters
```

这是用于理解职责的简化图，不表示每个 Python import 都严格形成一条直线。维护时遵守：

- `api` 不读取 checkpoint 内部 payload，也不拼接 GIS 事实；
- `application` 负责用例和公开 projection，不成为第二个领域算法实现；
- `workflow` 负责编排和路由，`WorkflowState` 只保存控制数据与 artifact refs；
- `domain` 只通过 contracts/ports 消费输入，不反向依赖 API、UI 或 provider；
- `infrastructure` 实现外部系统适配，不把 provider 类型上浮为业务事实；
- `DELIVER` 从同一个 `DeliverySpatialSnapshot` 派生地图、报告、导出和 manifest。

## 4. 阶段产物流

```text
SessionDataSnapshot / SpatialWorkspace
  → L1/L2/L3 artifacts
  → PlanningProgram
  → IntentCompilationResult / SpatialReferenceSpec
  → GroundingResult
  → SiteSelectionDecision / PortfolioDecision
  → ExecutionPlan / ExecutionResult
  → ParcelChangeSet / PlannedState
  → ValidationReport / ReconciliationReport
  → DeliverySpatialSnapshot
  → RenderLayers / DeliveryManifest / exports
```

阶段是否形成完整闭环不能由目录或函数名推断；请同时查看状态台账和验收结果。

## 5. 阅读与验证

- 根图节点和分支：看 [agent-graph.md](agent-graph.md)。
- API 资源和事件：看 [backend-api.md](backend-api.md)。
- state、artifact、事件和交付 owner：看 [backend-state-contract.md](backend-state-contract.md)。
- 领域 contract：从 `backend/app/contracts/` 进入，再跟到 `backend/app/domain/`。
- 运行验证：`pytest backend/tests/contracts backend/tests/core -q`；真实 provider 验收按
  状态台账中的条件执行，未配置 key 时不得把 skip 写成通过。

## 6. 迁移路径说明

`app/agent`、`app/modules` 和 `app/services` 是旧架构路径。它们可以在审计或迁移计划中
作为历史来源出现，但不再是当前目录、当前入口或新代码的落点。若文档需要解释迁移，
请明确写成 `HISTORICAL`，并同时给出当前替代路径。
