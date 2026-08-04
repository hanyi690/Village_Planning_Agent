# 后端 API（Backend API）

> 回答"API 端点有哪些、SSE 怎么走"。
> 设计理由见 [design/02_DATA_PERSISTENCE.md](../design/02_DATA_PERSISTENCE.md)。

## 1. 总览

后端为 FastAPI 单体应用，入口 `backend/app/main.py`。

- **API 基础路径**：`/api/sessions/*`（旧版 `/api/planning/*` 已**废弃并移除**）
- **数据通道**：SSE 单通道 —— 所有数据通过 SSE 流推送，Checkpoint 为唯一数据源（SSOT）
- **路由聚合**：`routes.py` 统一路由器，聚合 `session_router` + `gis_test_router`

```
FastAPI app (main.py)
  └─ router (routes.py)
       ├─ session_router (session_routes.py)   ← 7 核心端点
       ├─ gis_test_router (gis_test_routes.py)  ← 开发环境 GIS 测试
       ├─ /api/health
       └─ /api/tiles/tianditu/{layer_proj}/{z}/{y}/{x}  ← 天地图瓦片代理
```

## 2. 7 个核心端点

| # | 方法 | 路径                                          | 说明                                                     |
| - | ---- | --------------------------------------------- | -------------------------------------------------------- |
| 1 | POST | `/api/sessions`                             | 创建会话（支持`multipart/form-data` 文件上传）         |
| 2 | GET  | `/api/sessions/{id}/stream`                 | SSE 事件流（单通道，所有数据由此推送）                   |
| 3 | GET  | `/api/sessions/{id}/sync`                   | 断线重连（`?from_seq=N` 增量同步）                     |
| 4 | POST | `/api/sessions/{id}/feedback`               | 反馈接口（approve / reject 触发级联修订 / message 注入） |
| 5 | GET  | `/api/sessions/{id}/checkpoints`            | 检查点列表（标记 stable / intermediate）                 |
| 6 | POST | `/api/sessions/{id}/resume/{checkpoint_id}` | 从检查点恢复（仅允许 stable 检查点）                     |
| 7 | GET  | `/api/sessions/{id}/reports/{dim_key}`      | 维度报告全文（`?version=N` 查历史版本）                |

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
| `sse_manager`            | `sse/sse_manager.py`（`sse/`） | SSE 事件队列管理、历史事件缓存、断线重连                               |
| `checkpoint_service`     | `checkpoint.py`                  | 检查点重建、stable 检测                                                |
| `ReportStore`            | `report_store.py`                | 维度报告持久化、版本管理、层级摘要                                     |

## 6. 相关文件

```
backend/app/
├── main.py                    # FastAPI 入口 + lifespan + 中间件
├── api/
│   ├── routes.py              # 统一路由器（聚合 session + gis_test + tiles）
│   ├── session_routes.py      # 7 核心端点 + 辅助端点
│   ├── gis_test_routes.py     # 开发环境 GIS 测试
│   └── schemas.py             # Pydantic 请求/响应模型
├── services/
│   ├── runtime.py             # PlanningRuntimeService 单例
│   ├── sse/                   # SSE 管理器
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
