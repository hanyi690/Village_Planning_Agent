# backend/app

FastAPI 后端应用根包。入口为 `app/main.py`（`app:app`），生命周期在
`app/bootstrap/lifespan.py`，统一路由在 `app/api/routes.py`（聚合 `/api/v1`）。

模块一览（各模块详细 README）：

| 模块 | 职责 |
|---|---|
| `api/` | HTTP/SSE transport 与 v1 路由 |
| `application/` | 命令/查询/投影用例、resume 与 session 生命周期 |
| `bootstrap/` | FastAPI lifespan 与组合根 |
| `config/` | 领域配置（`phases.yaml` 28 维度 + 依赖计算） |
| `contracts/` | 跨边界 Pydantic 契约与 Ports |
| `core/` | 环境/运行参数（`settings.py`） |
| `data/` | 数据获取、摄取、catalog、编码与快照 |
| `database/` | 异步 SQLite 引擎、SQLModel 表与 CRUD |
| `domain/` | 规划业务决策（认知/程序/接地/选址/执行/校验/交付） |
| `evidence/` | 证据模型、索引与检索 |
| `infrastructure/` | artifact CAS、事件/SSE、LLM、KG、RAG、渲染、导出、任务等适配器 |
| `spatial/` | 几何、接地、查询、分配、网络、地形与空间校验 |
| `workflow/` | LangGraph 根图（四段子图）、阶段节点、层编排、对话与工具 |

依赖方向（简化）：`api → application → workflow/domain/contracts → data/spatial/evidence
→ infrastructure`。`WorkflowState` 只保存控制字段与 artifact refs；完整业务结果由 typed
contracts 与 CAS artifact 持有。