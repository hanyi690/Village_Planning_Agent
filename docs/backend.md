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
    
    # 2. 先创建数据库记录 (避免前端立即轮询时 404)
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

```python
@router.get("/status/{session_id}")
async def get_session_status(session_id: str):
    # 1. 从数据库获取业务元数据
    db_session = await get_session_async(session_id)
    
    # 2. 从内存状态获取实时进度
    if session_id in _sessions:
        session_state = _sessions[session_id]
        current_layer = session_state.get("current_layer", 1)
        sent_events = session_state.get("sent_layer_events", set())
        layer_1_completed = "layer_1_completed" in sent_events
        # ...
    
    # 3. 返回完整状态
    return {
        "session_id": session_id,
        "status": db_session.get("status", "running"),
        "current_layer": current_layer,
        "previous_layer": previous_layer,      # 待审查层级
        "layer_1_completed": layer_1_completed,
        "layer_2_completed": layer_2_completed,
        "layer_3_completed": layer_3_completed,
        "pause_after_step": pause_after_step,
        "execution_complete": execution_complete,
    }
```

**响应字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | 运行状态: running/paused/completed/failed |
| pause_after_step | boolean | 步进模式暂停标志 |
| previous_layer | number | 刚完成的层级 (待审查) |
| layer_X_completed | boolean | 层级完成状态 |
| execution_complete | boolean | 执行是否完成 |

### GET /api/planning/stream/{session_id}

SSE 流式输出

```python
@router.get("/stream/{session_id}")
async def stream_planning_events(session_id: str):
    async def event_generator():
        while True:
            events = _get_session_events_copy(session_id)
            for event in events[last_index:]:
                yield f"data: {json.dumps(event)}\n\n"
            
            if stream_state == "completed": break
            await asyncio.sleep(0.1)
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**事件类型**:

| 事件 | 数据 |
|------|------|
| dimension_delta | {layer, dimension_key, delta, accumulated} |
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

## 数据流

### 启动流程

```
POST /api/planning/start
      │
      ├─▶ 限流检查
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
                "dimension_reports": dimension_reports,
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

## 暂停恢复

### 触发暂停

```python
# LangGraph 执行中
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
    
    return  # 终止执行
```

### 恢复执行

```python
async def _resume_graph_execution(session_id: str, state: Dict) -> Dict:
    # 清除暂停标志
    state["pause_after_step"] = False
    state["previous_layer"] = 0
    
    # 使用 aupdate_state 更新 checkpoint
    await graph.aupdate_state(config, {"pause_after_step": False})
    
    # 启动后台任务
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

## 工具管理器

**文件**: `api/tool_manager.py`

```python
class ToolManager (Singleton):
    _checkpoint_tools: Dict[str, CheckpointTool]  # 按项目缓存
```

## 关键文件索引

| 文件 | 功能 |
|------|------|
| backend/main.py | FastAPI 应用入口 |
| backend/api/planning.py | 核心 API |
| backend/api/data.py | 数据访问 API |
| backend/api/tool_manager.py | 工具管理器 |
| backend/database/models.py | 数据模型 |
| backend/database/operations_async.py | 异步 CRUD |
| backend/services/rate_limiter.py | 限流器 |
