# 后端 API（Backend API）

> 回答"API 端点有哪些、SSE 怎么走"。
> 设计理由见 [design/02_DATA_PERSISTENCE.md](../design/02_DATA_PERSISTENCE.md)。

## 1. 总览

后端为 FastAPI 单体应用，入口 `backend/app/main.py`。

- **API 基础路径**：`/api/*`；会话端点在 `/api/sessions/*`，人工审核在 `/api/human-review/*`
- **数据通道**：SSE 单通道 -- 所有数据通过 SSE 流推送，Checkpoint 为唯一数据源（SSOT）
- **路由聚合**：`routes.py` 统一聚合 session、GIS Dev、human-review、artifact 与 render router
- **GIS Dev 路由**：`gis_test_router` 受 `IS_PRODUCTION` 门控，仅在非生产环境挂载（`routes.py:43`）

```
FastAPI app (main.py)
  └─ router (routes.py)
       ├─ session_router (session_routes.py)   ← 会话、SSE、恢复与反馈
       ├─ gis_test_router (gis_test_routes.py)  ← 开发环境 GIS 测试
       ├─ human_review_router (human_review_routes.py)
       ├─ artifact_router / render_router
       ├─ /api/health
       └─ /api/tiles/tianditu/{layer_proj}/{z}/{y}/{x}  ← 天地图瓦片代理
```

## 2. 主要会话端点（非完整清单）

| # | 方法 | 路径                                          | 说明                                                     |
| - | ---- | --------------------------------------------- | -------------------------------------------------------- |
| 1 | POST | `/api/sessions`                             | 创建会话（支持`multipart/form-data` 文件上传）         |
| 2 | GET  | `/api/sessions/{id}/stream`                 | SSE 事件流（单通道，所有数据由此推送）                   |
| 3 | GET  | `/api/sessions/{id}/sync`                   | 断线重连（`?from_seq=N` 增量同步）                     |
| 4 | POST | `/api/sessions/{id}/feedback`               | 反馈接口（approve / reject 触发级联修订 / message 注入） |
| 5 | GET  | `/api/sessions/{id}/checkpoints`            | 检查点列表（标记 stable / intermediate，并返回 `resume_plan`） |
| 6 | POST | `/api/sessions/{id}/resume/{checkpoint_id}` | 按 `resume_plan` 从稳定 checkpoint 恢复；HUMAN checkpoint 必须走对应审核接口 |
| 7 | GET  | `/api/sessions/{id}/reports/{dim_key}`      | 维度报告全文（`?version=N` 查历史版本）                |

### 人工审核端点（post-L3 HITL，`human_review_routes.py`）

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET  | `/api/human-review/{session_id}` | 返回 canonical `interrupt_info`（含 `event_id/channel/reason/items/paused_stage`）及兼容的 `pending_items`（首次 interrupt 时从 `snapshot.tasks` 兜底） |
| POST | `/api/human-review/{session_id}/resolve` | 提交 `ResolveRequest`，调用 `resume_post_l3_chain` 恢复链 |

`ResolveRequest` 字段：

| 字段 | 类型 | 说明 |
| ---- | ---- | ---- |
| `decisions` | `Dict[str, Any]` | resume payload（非空），进入图前统一为 canonical decision |
| `action`    | `str`            | `retry` / `approve` / `reject`；`accept` 仅作为旧客户端别名（可省略，从 `decisions["action"]` 兜底） |
| `event_id`  | `str`            | 可选的 HUMAN checkpoint 幂等键；不匹配当前暂停点时返回 409 |

`action` 路由语义（见 `route_after_human_review`）：
- `accept`：按 `_STAGE_FORWARD_TARGET[paused_stage]` 前进，`__end__` 则 `END`
- `retry`：回到 `paused_stage` 重跑
- `reject`：回到 `conversation` 节点

### 辅助端点

| 方法      | 路径                                              | 说明                          |
| --------- | ------------------------------------------------- | ----------------------------- |
| GET       | `/api/sessions/{id}/reports/{dim_key}/versions` | 维度报告版本列表              |
| GET       | `/api/sessions/{id}/status`                     | 会话状态（含 interrupt 检测） |
| DELETE    | `/api/sessions/{id}`                            | 删除会话                      |
| GET       | `/api/sessions/{id}/layer/{layer}/reports`      | 层级报告（含知识来源）        |
| GET       | `/api/projects`                                 | 项目列表                      |
| GET       | `/api/projects/{name}/sessions`                 | 项目下会话列表                |
| GET       | `/api/projects/{name}/reports/{dim_key}`        | 跨会话查维度报告              |
| POST      | `/api/sessions/{id}/export`                     | 导出 DOCX/JSON/MD             |
| GET/POST  | `/api/sessions/{id}/planning-text`              | 规划文本生成与查询            |
| GET       | `/api/sessions/{id}/geocode`                    | 村庄地理编码                  |
| GET/PATCH | `/api/sessions/{id}/rag-config`                 | RAG 配置读写                  |
| PATCH     | `/api/sessions/{id}/step-mode`                  | 步进模式切换                  |

### 天地图瓦片代理

```
GET /api/tiles/tianditu/{layer}_{projection}/{z}/{y}/{x}
例: /api/tiles/tianditu/vec_w/14/5312/13532.png
```

代理天地图 WMTS 瓦片，避免前端跨域和 API Key 暴露。支持图层：`vec` `img` `ter` `cva` `cia` `cta`。

## 3. SSE 单通道

**架构原则**：所有数据通过 SSE 流推送，Checkpoint 为唯一数据源。

```
Checkpoint (SSOT)
     │
     ▼
SSE Manager (sse_manager)
     │ 单通道 EventStream
     ▼
Frontend (EventSource)
```

- `POST /api/sessions` 创建会话后，后台任务启动 `PlanningRuntimeService._trigger_planning_execution`
- `GET /api/sessions/{id}/stream` 返回 `StreamingResponse`（`text/event-stream`）
- 事件通过 `sse_manager` 的队列推送，15 秒无事件发送心跳
- `GET /api/sessions/{id}/sync?from_seq=N` 支持断线重连，补发丢失事件
- `completed` / `error` 事件关闭流

### SSE 事件类型（`app/core/events.py::SSEEventType`）

| 类别 | 事件 |
| ---- | ---- |
| 连接 | `connected`、`heartbeat`、`completed`、`error`、`resumed`、`pause` |
| 层级 | `layer_started`、`layer_completed`、`layer_paused`、`execution_resumed` |
| 维度 | `dimension_start`、`dimension_delta`、`dimension_complete`、`dimension_error` |
| 级联 | `cascade_impact`、`cascade_complete` |
| AI 响应 | `ai_response_delta`、`ai_response_complete` |
| 检查点 | `checkpoint_saved`、`revision_completed` |
| 工具 | `tool_started`、`tool_status`（legacy: `tool_call` / `tool_progress` / `tool_result`） |
| GIS | `gis_result`、`gis_layer_update` |
| RAG | `rag_query`、`rag_result` |
| 配置 / HITL | `rag_config_updated`、`step_mode_updated`、`human_review_paused` |

`human_review_paused` 由 `human_review_publish` 节点幂等发布，携带 `event_id`、`paused_stage`、`reason`、`item_count`。

### Checkpoint 与恢复计划

`GET /api/sessions/{id}/checkpoints` 的每项都包含：

```json
{
  "checkpoint_id": "...",
  "stable": true,
  "kind": "layer | revision | human | completed | intermediate",
  "resume_plan": {
    "mode": "resume_checkpoint | resume_interrupt | rerun_from_stage | completed | blocked",
    "resume_from": "SELECT",
    "reuse": ["grounding_result"],
    "rerun": ["SELECT", "EXECUTE", "VALIDATE", "RECONCILE", "DELIVER"],
    "reason": "...",
    "input_checksums": {},
    "output_checksums": {}
  }
}
```

`stable=true` 不代表可以无条件恢复：真实 pending `PregelTask.interrupts` 会被分类为 `kind=human`，普通 checkpoint resume 对此返回 `409`，必须提交同一个 `event_id` 对应的 canonical HUMAN decision。`next` 只描述 LangGraph cursor，`resume_plan` 才描述业务 artifact 的复用与重跑边界。

## 4. 应用生命周期（`main.py` lifespan）

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 初始化异步数据库
    await init_async_db()
    # 2. 初始化 PlanningRuntimeService（LangGraph 运行时单例）
    await PlanningRuntimeService.initialize()
    # 3. 保存 event loop（供跨线程 SSE 发布）
    sse_manager.save_event_loop(asyncio.get_running_loop())
    # 4. 启动定时清理任务
    sse_cleanup_task  # 每 10 分钟清理过期 SSE 会话
    log_cleanup_task  # 每 24 小时清理旧日志
    yield
    # 清理资源
```

## 5. 服务层（`backend/app/services/`）

| 服务                       | 文件                               | 职责                                                                   |
| -------------------------- | ---------------------------------- | ---------------------------------------------------------------------- |
| `PlanningRuntimeService` | `runtime.py`                     | LangGraph 运行时单例。图构建缓存、状态读写、执行触发、interrupt/resume |
| `sse_manager`            | `sse.py`                    | SSE 事件队列管理、历史事件缓存、断线重连                               |
| `checkpoint_service`     | `checkpoint.py`                  | 检查点重建、stable 检测                                                |
| `ReportStore`            | `report_store.py`                | 维度报告持久化、版本管理、层级摘要                                     |

## 6. 相关文件

```
backend/app/
├── main.py                    # FastAPI 入口 + lifespan + 中间件
├── api/
│   ├── routes.py              # 统一路由器（聚合 session、GIS Dev、审核、artifact、render）
│   ├── session_routes.py      # 会话、SSE、恢复与反馈端点
│   ├── gis_test_routes.py     # 开发环境 GIS 测试
│   └── schemas.py             # Pydantic 请求/响应模型
├── services/
│   ├── runtime.py             # PlanningRuntimeService 单例
│   ├── sse.py                 # SSE 管理器
│   ├── checkpoint.py          # 检查点服务
│   └── report_store.py        # 报告存储
├── database/                  # SQLModel + 异步引擎
└── core/
    ├── settings.py            # 配置（环境变量）
    └── llm.py                 # LLM 工厂
```

## 7. 废弃端点

以下旧版端点已**废弃并移除**（`routes.py` 注释记录于 2026-05-08/09）：

| 旧端点                                | 替代                                      |
| ------------------------------------- | ----------------------------------------- |
| `/api/planning/*`                   | `/api/sessions/*`                       |
| `/api/data/*`                       | 数据通过规划流程内部获取                  |
| `/api/files/*`, `/api/gis_upload` | 整合到`POST /api/sessions`（multipart） |
| `/api/knowledge/*`                  | 移至命令行脚本                            |
