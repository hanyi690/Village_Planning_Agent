# database 数据访问层

异步 SQLite 数据访问层：引擎与会话管理（`engine.py`）、SQLModel 表模型（`models.py`）、高层 CRUD 操作（`operations.py`）。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `engine.py` | 异步引擎单例（带引用计数）、会话工厂、建表初始化、轻量迁移、LangGraph 全局 Checkpointer、进程退出前的强制清理 |
| `models.py` | 6 张业务表（SQLModel），另含由 LangGraph 托管的 `checkpoints` 表说明 |
| `operations.py` | 31 个 `async` 高层 CRUD，返回 dict 而非 ORM 对象 |
| `__init__.py` | 导出 `get_async_session` / `init_async_db` / `dispose_async_engine` / `get_global_checkpointer` |

## 架构定位

- 技术栈：`SQLModel` + `sqlalchemy.ext.asyncio` + `aiosqlite`，驱动 `sqlite+aiosqlite:///`（`DATABASE_DIR/village_planning.db`）。
- **状态不在业务表里**：会话运行状态（`status/is_executing/stream_state` 等冗余字段已被移除）统一由 LangGraph `AsyncSqliteSaver` 写入独立的 `checkpoints` 表管理，业务表只存元数据。`operations.py` 中的 `update_session_state_async` / `is_execution_active_async` / `get_stream_state_async` 等为历史遗留，新链路（`services/`）已不再依赖。
- 消费方：`services/`（`runtime/session/report_store/bundle_store/explore_access`）、`api/session_routes.py`、各 `agent` 节点写库。

## engine.py 核心机制

### 异步引擎（引用计数单例）

- `get_async_engine()`：首次创建时建目录并注册 SQLite PRAGMA：
  - `journal_mode=WAL`（并发写安全）、`synchronous=NORMAL`、`cache_size=-64000`（64MB）、`foreign_keys=ON`（FK 级联清理）。
  - 引用计数：每次调用 `+1`，`dispose_async_engine()` `-1`，归零才真正 `dispose`。
- `get_async_session()`：异步上下文管理器依赖注入，`AsyncSessionLocal` 首次使用时惰性创建（`autocommit=False, autoflush=False`）；正常退出自动 `commit`，异常 `rollback` 后重抛。

### 建表与迁移

- `init_async_db()`：导入全部模型 → `SQLModel.metadata.create_all`（`checkpoints` 除外，由 LangGraph 管理）→ `_run_migrations()`。
- `_run_migrations()`：幂等的轻量迁移，按表对 `PRAGMA table_info` 检查缺失列后 `ALTER TABLE`：
  - `planning_sessions`：行政区划列 `village_name/province/city/county/township` + `planning_period`（默认 `2022-2035年`）。
  - `dimension_reports`：P8 新增 `instruction` 列（INSTRUCTION 结构化段独立存储，不参与展示）。

### 全局 Checkpointer（LangGraph）

- `get_global_checkpointer()`：返回单例 `AsyncSqliteSaver`（`langgraph.checkpoint.sqlite.aio`），首次初始化建 `checkpoints` 表并启用相同 WAL PRAGMA；用 `asyncio.Lock` 做双重检查初始化。
- `shutdown_database()`：进程退出前的强制清理（5s 超时保护），覆盖 `dispose_async_engine` 触及不到的连接：Checkpointer 的裸 `aiosqlite` 连接（`aiosqlite>=0.22` 工作线程非 daemon，会导致退出挂起）以及引用计数失衡的引擎。可重复调用、永不抛异常。

## 表模型（models.py）

### planning_sessions — 规划会话元数据

- 主键 `session_id`；`project_name` 带索引，复合索引 `idx_project_created(project_name, created_at)`。
- 行政区划：`province/city/county/township` + `planning_period`（默认 `2022-2035年`）。
- 用户输入：`village_data`(Text)、`task_description`（默认 `DEFAULT_TASK_DESCRIPTION`）、`constraints`。
- 输出与错误：`output_path`、`execution_error`（业务元数据，非运行状态）。
- 时间戳：`created_at/updated_at/completed_at`。

### ui_sessions — UI 会话表

- 主键 `conversation_id`；`status`（默认 `idle`）带索引；`task_id` 关联规划会话。

### dimension_reports — 维度报告表（替代文件存储）

- `session_id`（FK → `planning_sessions`，`ondelete=CASCADE`）+ `dimension_key` + `layer`；复合索引 `idx_report_session_dim`、`idx_report_session_version`。
- 版本管理：`version` 自增 + `report_id`（外部引用 UUID，唯一）。
- 内容：`content`(Text) + `summary`(Text，结构化 JSON) + `instruction`(Text，P8 剥离段，不参与展示)。
- 溯源：`revision_trigger`、`knowledge_sources`(JSON，RAG 引用)、`gis_data`(JSON)。
- 写入方：`services/report_store.py::ReportStore`（`save/bulk_save`）直接经 `get_async_session` 操作本表；版本查询如 `get_by_version/get_latest`。

### uploaded_files — 上传文件存储表（替代磁盘存储）

- `session_id`（FK CASCADE）+ `file_category`（village_data/task_description/constraint）+ `file_type`（document/geojson/shapefile 等）。
- 内容：`filename/original_filename/file_size/content_type`、`parsed_text`(Text)、`gis_data`(JSON，GeoJSON FeatureCollection)、`gis_data_type`。
- 解析状态：`parse_status`（pending/success/failed）+ `parse_error`；`parse_text` 由 `modules/parsing` 填充。

### planning_text_documents — 规划文本文档表

- `session_id`（FK CASCADE）+ `version` + `document_id`（UUID 唯一）；每次重新生成创建新版本。
- 内容：`markdown_content`(Text) + `json_content`(JSON)；`article_count/generation_duration_seconds`。
- 版本元数据：`trigger_reason`（initial/dimension_change/manual）+ `changed_dimensions`(JSON)。

### planning_bundles — 规划数据包快照表

- `session_id`（FK CASCADE）+ `version`；`bundle_json`(Text，会话级 VillageBundle 全量 JSON 快照，含原始输入文档、空间要素与已嵌入的 L1/L2/L3 报告)。
- 去重：`sha256`；`trigger_reason`（layer1/layer2/layer3/final/manual）。
- 写入方：`services/bundle_store.py::BundleStore`。模型注释声明其**后续作为统一数据源替换 dimension_reports 存储**。

### checkpoints（外部托管）

- 由 LangGraph `AsyncSqliteSaver` 建表/写入，本模块不定义模型，仅通过 `get_global_checkpointer` 提供实例。

## CRUD（operations.py）

- 全部函数返回 dict（经 `make_json_serializable` 递归处理 datetime/set 等非 JSON 类型；`_*_to_dict` 序列化）。
- 按表分组：

| 分组 | 函数 |
| --- | --- |
| Planning Session | `create/get/update/delete_planning_session_async`、`list_planning_sessions_async`、`list_projects_async`、`list_project_sessions_async(project_name, limit=100)` |
| 会话状态（遗留） | `update_session_state_async`、`add_session_event_async`、`get_session_events_async`、`is_execution_active_async`、`set_execution_active_async`、`get_stream_state_async`、`set_stream_state_async` |
| UI Session | `create/get/update/delete_ui_session_async`、`list_ui_sessions_async` |
| UploadedFile | `create_uploaded_file_async`、`get_uploaded_files_by_session_async`、`get_uploaded_geojson_data_async`、`delete_uploaded_files_async` |
| PlanningText | `create/get_planning_text_document_async`、`list_planning_text_versions_async`、`update_planning_text_status_async` |
| DimensionReport | `get_session_reports_async`（按 layer 分组、只取每维最新版本） |
| PlanningBundle | `create/get_planning_bundle_async`（默认最新版本）、`list_planning_bundle_versions_async`（不含 bundle_json） |

## 使用示例

```python
from app.database import get_async_session
from app.database.engine import get_global_checkpointer

async def demo():
    async with get_async_session() as session:
        session.add(SomeModel(...))
        # 正常退出自动 commit
    checkpointer = await get_global_checkpointer()
```

## 相关文档

- `app/services/README.md`：ReportStore（dimension_reports 写入）、BundleStore（planning_bundles 快照）、SSEManager 内存状态与数据库的关系。
- `app/core/README.md`：`core/settings.py` 中 `DATABASE_DIR` 等配置来源。
- `app/api/README.md`：会话 API 与检查点恢复（resume）链路。
