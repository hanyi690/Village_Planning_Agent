# 后端实现文档

> FastAPI 后端架构 - REST + SSE 双通道状态同步

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
│                    backend/main.py                           │
└─────────────────────────────────────────────────────────────┘
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ planning_router │     │  data_router    │     │  files.router   │
│ api/planning.py │     │   api/data.py   │     │  api/files.py   │
└────────┬────────┘     └────────┬────────┘     └─────────────────┘
         │                       │
         └───────────────────────┼───────────────────────┐
                                 ▼                       │
┌─────────────────────────────────────────────────────────────┐
│                   Storage Layer                              │
│                                                             │
│  SQLite (village_planning.db):                              │
│    ├── planning_sessions  业务元数据                        │
│    └── checkpoints  LangGraph状态 (AsyncSqliteSaver)        │
│                                                             │
│  _sessions 内存: 运行时状态 + SSE事件队列                    │
└─────────────────────────────────────────────────────────────┘
```

## 核心 API 端点

### POST /api/planning/start

启动规划任务

```python
@router.post("/start")
async def start_planning(request: StartPlanningRequest, background_tasks: BackgroundTasks):
    # 1. 限流检查
    allowed, msg = rate_limiter.check_rate_limit(request.project_name, session_id)
    
    # 2. 创建数据库记录
    await create_session_async(session_state)
    
    # 3. 获取全局 checkpointer 单例
    checkpointer = await get_global_checkpointer()
    
    # 4. 创建图实例
    graph = create_village_planning_graph(checkpointer=checkpointer)
    
    # 5. 后台执行
    background_tasks.add_task(_execute_graph_in_background, ...)
    
    return {"task_id": session_id, "status": "running"}
```

### GET /api/planning/status/{session_id}

**核心端点** - 状态查询 (REST 轮询)

**响应字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | 运行状态: running/paused/completed/failed |
| pause_after_step | boolean | 步进模式暂停标志 |
| previous_layer | number | 刚完成的层级 (待审查) |
| layer_X_completed | boolean | 层级完成状态 |
| execution_complete | boolean | 执行是否完成 |
| checkpoints | array | 检查点列表 |

### GET /api/planning/stream/{session_id}

SSE 流式输出

**事件类型**:

| 事件 | 数据 |
|------|------|
| dimension_delta | {layer, dimension, delta, accumulated} |
| layer_completed | {layer, report_content, dimension_reports} |
| pause | {current_layer, checkpoint_id} |
| completed | {success} |

### POST /api/planning/review/{session_id}

审查操作

```python
@router.post("/review/{session_id}")
async def handle_review(session_id: str, request: ReviewActionRequest):
    if request.action == "approve":
        # 清除暂停标志
        initial_state["pause_after_step"] = False
        initial_state["previous_layer"] = 0
        
        # 持久化到数据库
        await update_session_async(session_id, {"status": TaskStatus.running})
        
        # 恢复执行
        return await _resume_graph_execution(session_id, initial_state)
```

### GET /api/data/villages

列出所有村庄及其会话

### GET /api/data/villages/{name}/layers/{layer}

获取指定层级的规划内容

## 数据流

### 启动流程

```
POST /api/planning/start
      │
      ├─▶ 限流检查 (RateLimiter)
      ├─▶ 生成 session_id (YYYYMMDD_HHMMSS)
      ├─▶ 创建数据库记录 (PlanningSession)
      ├─▶ 构建 LangGraph 初始状态
      ├─▶ 获取 AsyncSqliteSaver 单例
      ├─▶ 创建图实例
      └─▶ 提交后台任务
      │
返回 {task_id, status}
```

### 后台执行

```python
async def _execute_graph_in_background(session_id, graph, initial_state, checkpointer):
    config = {"configurable": {"thread_id": session_id}}
    
    async for event in graph.astream(initial_state, config):
        # 检测层级完成 → 发送 layer_completed 事件
        if event.get("layer_X_completed"):
            await _append_session_event_async(session_id, {
                "type": "layer_completed",
                "layer": layer_num,
                "report_content": report,
            })
        
        # 检测暂停 → 发送 pause 事件
        if event.get("pause_after_step"):
            await _append_session_event_async(session_id, {
                "type": "pause",
                "current_layer": previous_layer,
            })
            return  # 终止执行
```

### 状态读取

```
GET /api/planning/status/{id}
      │
      ├─▶ 数据库: 业务元数据 (status, created_at)
      ├─▶ 内存: 实时进度 (current_layer, sent_events)
      └─▶ 组装响应
      │
返回 JSON
```

## 状态管理

### AsyncSqliteSaver 单例

```python
_checkpointer: Optional[AsyncSqliteSaver] = None

async def get_global_checkpointer() -> AsyncSqliteSaver:
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    
    conn = await aiosqlite.connect(get_db_path(), check_same_thread=False)
    _checkpointer = AsyncSqliteSaver(conn)
    await _checkpointer.setup()
    return _checkpointer
```

### 内存会话状态

```python
_sessions: Dict[str, Dict] = {
    "session_id": {
        "initial_state": {...},      # LangGraph 状态
        "status": "running",
        "events": [],                # SSE 事件队列
        "sent_layer_events": set(),  # 已发送的层级完成事件
        "sent_pause_events": set(),  # 已发送的暂停事件
    }
}
```

### 状态字段来源

| 字段 | 来源 | 说明 |
|------|------|------|
| status | 数据库 + 内存 | 运行状态 |
| current_layer | 内存 | 当前层级 |
| previous_layer | 内存 | 刚完成的层级 |
| layer_X_completed | 内存 (sent_events) | 层级完成 |
| pause_after_step | 内存 | 步进暂停 |
| execution_complete | 内存 | 执行完成 |

## 暂停恢复机制

### 触发暂停

```python
# LangGraph 执行中检测到 pause_after_step
if event.get("pause_after_step"):
    previous_layer = event.get("previous_layer", 1)
    
    # 添加 pause 事件
    await _append_session_event_async(session_id, {
        "type": "pause",
        "current_layer": previous_layer,
    })
    
    # 更新状态
    _set_session_value(session_id, "status", TaskStatus.paused)
    await update_session_async(session_id, {"status": TaskStatus.paused})
    
    return  # 终止执行，等待审查
```

### 恢复执行

```python
async def _resume_graph_execution(session_id: str, state: Dict) -> Dict:
    # 清除暂停标志
    state["pause_after_step"] = False
    state["previous_layer"] = 0
    
    # 使用 aupdate_state 更新 checkpoint
    await graph.aupdate_state(config, {"pause_after_step": False})
    
    # 启动后台任务继续执行
    asyncio.create_task(_execute_graph_in_background(...))
```

## 限流器

**文件**: `services/rate_limiter.py`

```python
class RateLimiter:
    window_seconds = 5       # 时间窗口
    max_requests = 3         # 最大请求数
    cooldown_seconds = 10    # 冷却时间
```

## 数据库模型

**文件**: `database/models.py`

```python
class PlanningSession(SQLModel, table=True):
    __tablename__ = "planning_sessions"
    
    session_id: str = Field(primary_key=True)
    project_name: str
    status: str
    created_at: datetime
    updated_at: datetime
    config: dict  # JSON配置

class Checkpoint(SQLModel, table=True):
    __tablename__ = "checkpoints"
    
    # LangGraph AsyncSqliteSaver 自动管理
```

## 应用生命周期

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    ensure_working_directory()
    init_db()               # 同步数据库初始化
    await init_async_db()   # 异步数据库初始化
    
    yield
    
    # 关闭
    dispose_engine()
    await dispose_async_engine()
```

## 关键文件索引

| 文件 | 功能 |
|------|------|
| `backend/main.py` | FastAPI 应用入口 |
| `backend/schemas.py` | Pydantic 请求/响应模型 |
| `backend/api/planning.py` | 规划 API 核心 |
| `backend/api/data.py` | 数据访问 API |
| `backend/api/tool_manager.py` | 工具管理器 |
| `backend/database/models.py` | SQLModel 数据模型 |
| `backend/database/operations_async.py` | 异步 CRUD 操作 |
| `backend/services/rate_limiter.py` | 限流器 |