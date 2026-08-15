# 数据 / 上下文 / 产物持久化设计

> 模块：`backend/app/database/`、`backend/app/infrastructure/artifacts/`、`backend/app/infrastructure/events/`

| 文档 | 内容 | 状态 |
|---|---|---|
| [02_DATA_PERSISTENCE.md](02_DATA_PERSISTENCE.md) | 数据、上下文与规划产物持久化目标 | TARGET |

当前事实：`infrastructure/artifacts/` 内容寻址 CAS（descriptor + blob + named ref）；
`database/` 7 张 SQLModel 业务表；运行状态在 LangGraph `checkpoints` 表；事件在 `run_events` 表。