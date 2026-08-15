# database 数据访问层

> 本 README 以 `backend/app/database/` 实际代码为准（核验日期 2026-08-15）。

## 定位

异步 SQLite 数据访问层：引擎与会话管理、SQLModel 表模型、高层 CRUD。会话运行状态由
LangGraph checkpoint（独立 `checkpoints` 表）管理，业务表只存元数据/输入/报告。

## 文件职责

| 文件 | 职责 |
|---|---|
| `engine.py` | 异步引擎单例（引用计数 + WAL PRAGMA）、`get_async_session`、`init_async_db`（建表/迁移）、`get_global_checkpointer`、`dispose_async_engine`/`shutdown_database` |
| `models.py` | SQLModel 表：`PlanningSession`、`UISession`、`DimensionReport`、`UploadedFile`、`PlanningBundle`、`StepReportModel`、`RunEvent` |
| `operations.py` | 高层 async CRUD（返回 dict）：planning/ui session、uploaded files、reports、planning bundle 等 |
| `__init__.py` | 导出 `get_async_session` / `init_async_db` / `dispose_async_engine` / `get_global_checkpointer` |

## 关键机制

- 引擎：`sqlite+aiosqlite:///`（`DATABASE_DIR/village_planning.db`），`journal_mode=WAL`、
  `synchronous=NORMAL`、`cache_size=-64000`、`foreign_keys=ON`；引用计数归零才真正 dispose。
- Checkpointer：LangGraph `AsyncSqliteSaver` 使用独立 `checkpoints` 表，业务表不复制运行状态。
- `operations.py` 消费方：`application/commands/create_session`（创建/更新/删除 planning
  session）、`application/queries/*` 等。

## 边界规则

- 状态不在业务表里伪装持久化；SSE 事件由 `infrastructure/events/` 管理。
- 运行状态统一从 LangGraph checkpoint 恢复，业务表只做元数据。