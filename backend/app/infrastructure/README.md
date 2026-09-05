# Infrastructure 基础设施层

> 本 README 以 `backend/app/infrastructure/` 实际代码为准（核验日期 2026-08-15）。

## 定位

外部系统与持久化适配器：artifact CAS、事件/SSE、LLM、KG、RAG、渲染、导出、报告、任务
调度、context、日志等。`infrastructure/` 实现 `contracts/ports/` 的 Protocol，不把
provider 类型上浮为业务事实；领域层不反向依赖这里的具体实现。

## 目录职责

| 目录 | 职责 | 关键文件 |
|---|---|---|
| `artifacts/` | 内容寻址 artifact 仓库 | `repository.ContentAddressedArtifactRepository`（CAS：digest/blob/named ref）、`runtime.py`（`ARTIFACT_KEYS`、store/load/fork）、`fingerprint.py`（语义指纹） |
| `events/` | 事件持久化与 SSE | `repository.EventRepository`（SQLite run_events）、`connection_hub.EventConnectionHub`（在线队列）、`sse_publisher`（发事件/工具状态/GIS 事件）、`sse_events.py`（GIS 事件模型）、`event_factory` |
| `runtime/` | 规划运行时 | `planning_runtime_service.PlanningRuntimeService`：graph 单例、`trigger_planning_execution`、`resume_from_interrupt`、`fork_checkpoint`、`aget_state` |
| `llm/` | LLM 适配 | `factory.create_llm`（openai/zhipuai/minimax）、`instructor_client`、`manager`（统一调用/上下文/输出边界）、`planning_claims.PlanningClaimGenerator`、`retry`、`stats_collector`、`tracing`；`prompts/`；`tools/`（ToolRegistry + DATA/evidence/knowledge/reports 工具） |
| `kg/` | DATA-backed World Model 适配 | `ontology`、`source_catalog_adapter`、`current_world_adapter`、`world_model_adapter`、`external_observation_adapter`；旧 KG builder/manager/session/query/enrichment/gazetteer/spatial index 已物理删除 |
| `rag/` | RAG 检索 | `service.RagService`、`vector_store`（chroma/faiss/qdrant + Aliyun embeddings）、`chunker`、`cli`（管理命令）、`context`、`utils/` |
| `rendering/` | 交付渲染 | `html_render.render_interactive_map`、`static_render`（PNG）、`map_layers.build_map_layers`、`colors` |
| `export/` | 交付导出 | `delivery_snapshot`（快照→GeoJSON 图层）、`export_package.export_delivery_package`、`gdb` |
| `reports/` | 阶段/步骤报告 | `stage_report`（markdown 报告）、`step_report.StepReport`（审计）、`review_package`（人工审核包）、`report_store` |
| `context_runtime/` | 统一规划上下文 | `manager`、`projection_builder`、`table_renderer`、`budgets`、`runtime`（版本化、投影、预算、缓存） |
| `evidence_runtime/` | 统一证据执行 | `facade`、`query_planner`、`retriever_router`、provider retrievers、`fusion`、`provenance`、`coverage`、`sufficiency`、`dimension_runtime`（维度证据适配与审计辅助） |
| `structured_runtime/` | 统一结构化执行 | `parser`、`validator`、`assembler`、阶段调用 facade |
| `checkpoint/` | checkpoint 分类 | `checkpoint_policy`（has_pending_interrupt/classify_checkpoint） |
| `tasks/` | 后台任务 | `task_supervisor.TaskSupervisor`（session 级任务跟踪/取消） |
| `storage/` | 通用持久化适配器 | DATA 与工作流 artifact 通过 `infrastructure/artifacts` CAS 管理 |
| `search/` | 外部搜索 | `provider_registry`（显式 Exa 或 typed unavailable adapter） |
| `gis/` | 空间数据 port | `spatial_data_port.SpatialDataPort`（文件校验/裁剪/bbox 过滤） |
| 顶层 | 通用 | `logging.py`（SessionFilter/set_session_id）、`paths.py`、`registry.py`（默认单例读写） |

## 关键机制

- **artifact CAS**：`ContentAddressedArtifactRepository` 以内容 sha256 为身份，descriptor
  记录 schema/version/parent_digests/producer；named ref 不可覆盖（冲突抛 `NamedRefConflict`）。
- **事件**：`EventRepository` 持久化事件序号（`run_events` 表），`EventConnectionHub` 只管理
  在线 SSE 队列；replay/sync 由 `application/queries/run_events.py` 统一完成。
- **runtime**：`PlanningRuntimeService` 持有编译后的 LangGraph 图与 checkpointer，负责
  trigger/restore/resume/fork；所有 v1 路由通过 `api/v1/dependencies.py` 的
  `PlanningRuntime` Protocol 访问它。
