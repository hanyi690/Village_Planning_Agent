# 当前模块职责

> 本文只给当前目录和依赖边界做索引。详细目标约束见
> [`../design/14_BACKEND_MODULE_BLUEPRINT.md`](../design/14_BACKEND_MODULE_BLUEPRINT.md)。

| 当前目录 | 职责 | 主要入口 |
|---|---|---|
| `backend/app/api/` | HTTP、SSE、v1 transport | `api/routes.py`、`api/v1/routes/` |
| `backend/app/application/` | command、query、projection、resume | `commands/`、`queries/`、`projections/` |
| `backend/app/contracts/` | 跨边界 Pydantic/Typed contracts | `artifacts/`、`domain/`、`spatial/`、`workflow/` |
| `backend/app/data/` | 上传、摄取、catalog、快照 | `data/ingestion/`、`data/model/` |
| `backend/app/domain/` | 规划、选址、执行、校验和交付 | `assessment/`、`program/`、`allocation/`、`materialization/`、`delivery/` |
| `backend/app/evidence/` | evidence model、index 和 retrieval | `evidence/retrieval/` |
| `backend/app/infrastructure/` | 外部系统和持久化适配器 | `artifacts/`、`events/`、`runtime/`、`llm/`、`kg/`、`rag/` |
| `backend/app/spatial/` | 几何、接地、空间查询、变化和交付 | `geometry` 对应能力分布在各子包 |
| `backend/app/workflow/` | 根图、层编排、阶段节点、对话和工具 | `root_graph.py`、`stages/` |

## 依赖规则

- API 只调用 application；application 通过 contracts、workflow 和 domain 组合用例。
- Domain 和 spatial 不依赖 API、UI 或具体 provider。
- Infrastructure 实现 ports，不把 provider response 当作规划事实。
- Workflow 负责编排和 gate，不负责重新实现 domain 算法。
- Artifact refs 是阶段间的连接方式；不要用全局 singleton、隐式 latest 或路径猜测替代它。

旧的 `app/agent`、`app/modules`、`app/services` 目录已不是当前模块。历史迁移记录请查
`docs/audits/` 和 `docs/superpowers/plans/`，不要从旧文档复制 import 路径。
