# 当前架构实现

本目录只描述已经存在于 `backend/app/` 或 `frontend/` 的实现：入口、调用链、状态边界、
接口和验证方式。目标架构、未实现能力和未来迁移顺序不在这里定义，分别见
[`../design/00_SYSTEM_DESIGN.md`](../design/00_SYSTEM_DESIGN.md)、
[`../design/14_BACKEND_MODULE_BLUEPRINT.md`](../design/14_BACKEND_MODULE_BLUEPRINT.md) 和
[`../design/10_IMPLEMENTATION_STATUS.md`](../design/10_IMPLEMENTATION_STATUS.md)。

## 当前实现入口

```text
backend/app/main.py
  → bootstrap/lifespan.py
  → api/routes.py
  → api/v1/routes/*
  → application/commands|queries|projections
  → infrastructure/runtime/planning_runtime_service.py
  → workflow/root_graph.py
```

FastAPI 的生命周期负责数据库、运行时、事件循环和资源释放；路由只负责 transport 与
projection；工作流负责编排；领域模块负责业务决策；`contracts/` 负责跨边界类型契约。

## 文档索引

| 文档 | 只回答一个问题 |
|---|---|
| [structure.md](structure.md) | 当前目录和依赖边界是什么？ |
| [agent-graph.md](agent-graph.md) | 根图有哪些节点、阶段和恢复路径？ |
| [backend-api.md](backend-api.md) | 当前 HTTP、SSE、resume 和 delivery 接口是什么？ |
| [backend-state-contract.md](backend-state-contract.md) | state、artifact、事件和交付的 owner 是谁？ |
| [modules.md](modules.md) | 各应用模块的职责和依赖是什么？ |
| [frontend.md](frontend.md) | 前端如何消费状态、事件和地图？ |
| [rag-system.md](rag-system.md) | 当前 RAG 摄取和检索如何运行？ |
| [deployment.md](deployment.md) | 当前本地和容器启动方式是什么？ |
| [../frontend/API_SSE_DEVELOPER_GUIDE.md](../frontend/API_SSE_DEVELOPER_GUIDE.md) | 前端接入、同步和恢复如何实现？ |

## 事实规则

- `backend/app/**` 和可重复测试是实现事实源；本目录不能覆盖代码行为。
- 每一条“当前”描述应带代码路径、契约名称或验证命令。
- 目标行为必须链接到 `design/`，并显式标为 `TARGET`、`GAP` 或 `PARTIAL`。
- `audits/`、`superpowers/plans/` 和 `graphify-out/` 中带日期的内容是证据或历史快照，
  不作为当前入口。
- 已删除的 `app/agent`、`app/modules`、`app/services` 路径只允许出现在迁移历史中，
  不能出现在当前目录树或当前调用链里。

## 变更后检查

```powershell
rg -n --glob '*.md' 'app/agent|app/modules|app/services|backend/app/modules' docs README.md
rg -n --glob '*.md' '\[.*\]\([^)]*\)' docs/architecture docs/design/10_IMPLEMENTATION_STATUS.md
pytest backend/tests/contracts backend/tests/core -q
```

第一条命令的结果只能来自 `audits/`、`superpowers/plans/` 或明确的历史说明；发现当前实现
文档命中时，应先确认路径是否已经迁移。
