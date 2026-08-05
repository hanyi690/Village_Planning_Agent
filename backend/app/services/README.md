# Services 层

> 会话级业务服务层：规划会话的生命周期、LangGraph 运行时、SSE 事件分发、报告/快照持久化与人工审核编排。位于 `api/`（HTTP 入口）与 `agent/`（图执行）之间，是两者的粘合层。

---

## 一、层定位

```
HTTP (api/) ──> services/ ──> agent/ (LangGraph)
                    │
                    └──> database/ (SQLModel) + modules/ (数据/解析)
```

- **单一职责**：`api/` 路由只做参数校验与响应组装，业务编排全部下沉到本层
- **单例模式**：大多数服务以模块级单例导出（`sse_manager` / `session_service` / `checkpoint_service` / `planning_runtime_service`）
- **会话状态 SSOT**：内存态统一收归 `sse.py` 的 `SSEManager`，持久态在 `database/`，Checkpoint 态在 LangGraph `SqliteSaver`

---

## 二、文件清单

| 模块 | 职责 | 核心入口 |
|------|------|----------|
| `sse.py` | SSE 连接订阅、事件发布、会话内存态（SSOT） | `SSEManager.publish` / `subscribe` |
| `runtime.py` | 统一规划运行时（LangGraph 图执行 + 会话管理） | `PlanningRuntimeService.start_session` / `resume_from_interrupt` |
| `checkpoint.py` | Checkpoint 业务逻辑 + 持久化同步 | `CheckpointService.rebuild_events` / `get_layer_reports` |
| `session.py` | 会话生命周期（创建/删除/层级报告） | `SessionService.create_session` / `delete_session` |
| `report_store.py` | 维度报告存储（版本化，SQLModel） | `ReportStore.save` / `bulk_save` / `get_layer_reports_with_sources` |
| `bundle_store.py` | session 级 `VillageBundle` 快照持久化 | `BundleStore.save` / `load_bundle` |
| `session_bundle.py` | bundle 构建编排 + 进程内缓存 | `build_session_bundle` / `snapshot_session_bundle` |
| `session_kg.py` | 会话 KG 预建（L1 前注入基础空间认知 + 地块拓扑关系），幂等 | `ensure_session_kg` |
| `context/` | 会话规划上下文工厂（组装 `PlanningContext` + 注入端口 + 缓存） | `build_planning_context`（见 `context/README.md`） |
| `step_report.py` | 全链步骤 Report 落库与查询（`step_reports` 表） | `save_step_report` / `get_session_step_reports` |
| `stage_report.py` | GIS 全管线 stage 报告 → 人类可读 Markdown | `render_stage_report_markdown` |
| `review_package.py` | 人工审核包磁盘序列化（manifest/summary/trace/decision） | `write` / `read` / `query` review packages |
| `artifact_store.py` | 管线 artifact 文件存储（原子写 + 路径约束，实现 `ArtifactStorePort`） | `FilesystemArtifactStore` |
| `post_l3_resume.py` | post-L3 链 HITL 中断恢复（`Command(resume=...)` + 快照持久化） | `resume_post_l3` |

> ⚠️ **services/modules/ 已移除**（Batch B）：旧 `services/modules/gis/road/` 的道路算法已迁移至 `app/modules/spatial_ops/road/`（staged 道路规划管线，见 `modules/spatial_ops/road/README.md`），不再作为应用服务子包存在。

> `app/services/__init__.py` 仍为旧时代遗留：仅懒加载转发 `RagService`（实际实现在 `app/modules/rag/service.py`）。新代码不应依赖 `app.services.RagService`，请直接引用 `app.modules.rag`。

---

## 三、核心服务详述

### 3.1 SSEManager（`sse.py`）

会话内存状态的 **SSOT**，全部共享类属性 + 锁保护：

- **事件生命周期**：`publish` → 分配全局递增 `seq` → 写 `_seq_buffer`（断线重连同步，容量 50）→ 按 `CACHE_CONFIG` 缓存关键事件 → 分发给订阅队列
- **订阅同步**：`subscribe()` 按优先级回放 `pending flush → 缓存事件 → 历史事件`（terminal 事件跳过），保证新连接不丢关键状态
- **Delta 合并**：`DIMENSION_DELTA` 队列溢出时经 `_delta_coalesce_index` 与最近同维 delta 合并，避免队列无界增长
- **跨线程发布**：`publish_sync` 借助 `save_event_loop` 保存的主事件循环 `run_coroutine_threadsafe` 发布（LLM 回调等同步上下文使用）
- **执行态**：`_active_executions`（防重复执行）、`_stream_states`（active/paused/completed）、`_status_log_tracker`（抑制日志刷屏）
- **清理**：`cleanup_expired_sessions`（默认 24h 过期 + 孤儿状态回收）、`delete_session_all_states`

**CACHE_CONFIG 关键事件**：`DIMENSION_START/COMPLETE/ERROR`、`RAG_RESULT/QUERY`、`LAYER_STARTED/COMPLETED`、`RESUMED`、`CASCADE_IMPACT/COMPLETE`、`GIS_RESULT` —— 维度级事件以 `dimension_key` 二次索引。

### 3.2 PlanningRuntimeService（`runtime.py`）

统一规划运行时，合并了旧 `GraphRuntimeService` + `PlanningService`：

- **初始化**：`initialize()` 单例获取 `SqliteSaver` checkpointer + `create_unified_planning_graph()`（幂等，`ensure_initialized` 懒初始化）
- **会话启动**：`start_session()` → 限流检查 → 生成 UUID → `build_initial_state` → 建库 → 初始化 SSE → 后台任务 `_trigger_planning_execution`
- **执行守护**：`_execution_locks[session_id]` 防止同会话重复执行；`wait_for_subscriber`（脚本模式 1s 提前返回）
- **合成意图消息**：无既有 intent 时注入带 `advance_planning_intent` tool_call 的合成 `AIMessage`（`_KNOWN_INTENT_NAMES` 去重）
- **流式执行**：`_execute_planning` 以 `stream_mode=['values','checkpoints']` 消费图输出，`values` 检测层级/修订完成，`checkpoints` 发 `checkpoint_saved` 事件（修订后清空 `last_revised_dimensions` 防误判）
- **中断恢复**：`resume_from_interrupt()` 走官方 `Command(resume=...)` 模式；`resume_execution()` 从 checkpoint 恢复
- **状态工具**：`aget_state` / `aupdate_state`（`as_node="__start__"` 写新鲜线程初始态）/ `aget_state_history`

### 3.3 CheckpointService（`checkpoint.py`）

- **`rebuild_events`**：从 checkpoint + DB 重建 `layer_completed` / `dimension_complete` / `pause` 事件（SSE 断线重连时 `runtime.subscribe_with_history` 调用）
- **`CheckpointPersistenceManager`**：`mark_write_complete` / `wait_for_write` 同步写入与读取（Future 跟踪 + 300s TTL 清理）
- **业务查询**：`get_layer_reports`、`get_completion_status`、`calculate_next_layer`、`get_project_name`

### 3.4 ReportStore（`report_store.py`）

维度报告版本化存储（`dimension_reports` 表）：

- **P8 INSTRUCTION 分离**：`split_instruction` 剥离文末【INSTRUCTION】markdown 表格段，`content` 存展示文本、`instruction` 独立列（PARSE 据此定位）
- **摘要**：`_generate_summary` 调 `modules.parsing.summary_generator` 生成结构化 JSON 摘要，失败降级 `BaseDimensionSummary`
- **批量写入**：`bulk_save` 单事务 upsert（重复 `report_id` 更新），供 `analysis/node.py` 的 `pending_reports` 批量落库
- **版本查询**：`get_latest` / `get_latest_version` / `list_versions` / `get_by_version`（时间旅行）
- **层读取**：`get_layer_reports`（SQLite 连接错误 3 次重试）、`get_layer_reports_with_sources`（含 `knowledge_sources` + `instruction`）

### 3.5 SessionService（`session.py`）

- `create_session`：DB 写 `planning_sessions`
- `delete_session`：依次清理内存态 → 上传文件 → 维度报告 → UI 会话 → DB 记录（CASCADE）→ LangGraph checkpoint
- `get_layer_reports`：转发到 `checkpoint_service`

### 3.6 Bundle 体系（`session_bundle.py` + `bundle_store.py`）

未来统一数据源的雏形：

- `build_session_bundle`：`DataCatalog.load_village_bundle_async` 构建 session 级 bundle（原始输入文档 + 空间数据 + 内嵌 L1/L2/L3 报告），进程内缓存
- `snapshot_session_bundle`：每层完成时由 `layer_completion_check` 调用，刷新 bundle 并持久化版本化快照到 `planning_bundles` 表（sha256 去重校验）
- `BundleStore.get_layer_reports_from_bundle`：未来替代 `dimension_reports` 读路径的接口

---

## 四、会话数据流（一次规划会话）

```
POST /api/planning/start
  → PlanningRuntimeService.start_session()
      → 建 DB 会话 + SSE 内存态 + 后台 _trigger_planning_execution
          → wait_for_subscriber → aupdate_state(as_node="__start__", 合成 intent)
          → graph.astream(values+checkpoints)
              → values: 检测层完成 → checkpoint_saved SSE
              → checkpoints: mark_write_complete
          → 完成后发 completed 事件
  ← 前端 SSE /stream/{session_id} 订阅（reconnect 走 subscribe_with_history 重建）
```

人工审核（step_mode）路径：

```
layer_completion_check interrupt()
  → session_routes.py /api/sessions/{id}/feedback (approve/reject)
      → PlanningRuntimeService.resume_from_interrupt(Command(resume={"action": ...}))
      → 恢复节点 → 下一层或修订
  rollback → 目标 checkpoint state 覆盖（不恢复执行）
```

---

## 五、相关文档

- `app/agent/README.md` — 主图（5 节点）与 state 模型
- `app/agent/completion/README.md` — `layer_completion_check` 节点（interrupt / bundle 快照 / KG enrichment）
- `app/database/README.md` — 数据表与读写操作
- `modules/spatial_ops/road/README.md` — 6-stage staged 道路规划管线（自 `services/modules/gis/road/` 迁入）
- `modules/context/README.md` + `services/context/README.md` — `PlanningContext` 数据结构与构建工厂
