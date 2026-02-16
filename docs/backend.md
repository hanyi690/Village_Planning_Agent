# 后端实现文档

> 村庄规划智能体 - FastAPI 后端架构详解

## 目录

- [架构概述](#架构概述)
- [核心 API 端点](#核心-api-端点)
- [数据流详解](#数据流详解)
- [状态持久化](#状态持久化)
- [暂停恢复机制](#暂停恢复机制)

---

## 架构概述

### 技术栈

- **框架**: FastAPI
- **Python**: 3.9+
- **异步**: asyncio + uvicorn
- **数据验证**: Pydantic V2
- **流式传输**: Server-Sent Events (SSE)
- **数据库**: SQLite + AsyncSqliteSaver
- **默认端口**: 8000

### 目录结构

```
backend/
├── main.py                     # 应用入口、路由注册
├── api/
│   ├── planning.py             # 核心：规划 API (REST + SSE)
│   ├── sessions.py             # 会话管理 API
│   ├── data.py                 # 数据访问 API
│   └── files.py                # 文件上传 API
├── database/
│   ├── models.py               # 数据模型 (精简版)
│   ├── operations_async.py     # 异步数据库操作
│   └── engine.py               # 数据库引擎
└── utils/
    ├── error_handler.py        # 错误处理
    ├── logging.py              # 日志工具
    └── progress_helper.py      # 进度计算
```

---

## 核心 API 端点

### POST /api/planning/start

启动新规划任务。

**请求体**:
```json
{
  "project_name": "金田村规划",
  "village_data": "村庄现状数据...",
  "task_description": "制定村庄总体规划方案",
  "step_mode": true
}
```

**响应**:
```json
{
  "task_id": "20260216_143052",
  "status": "running"
}
```

**实现** (`backend/api/planning.py`):

```python
@router.post("/start")
async def start_planning(
    request: StartPlanningRequest,
    background_tasks: BackgroundTasks
):
    session_id = _generate_session_id()
    
    # 1. 创建会话记录
    await create_session_async(session_id, request.project_name, ...)
    
    # 2. 构建初始状态
    initial_state = _build_initial_state(request, session_id)
    
    # 3. 获取全局 checkpointer
    checkpointer = await get_global_checkpointer()
    
    # 4. 创建图实例
    graph = create_village_planning_graph(checkpointer=checkpointer)
    
    # 5. 后台执行
    background_tasks.add_task(
        _execute_graph_in_background,
        session_id, graph, initial_state, checkpointer
    )
    
    return {"task_id": session_id, "status": "running"}
```

### GET /api/planning/status/{session_id}

获取会话状态（REST 轮询，每 2 秒）。

**响应**:
```json
{
  "session_id": "20260216_143052",
  "status": "paused",
  "current_layer": 2,
  "previous_layer": 1,
  "pending_review_layer": 1,
  "layer_1_completed": true,
  "layer_2_completed": false,
  "layer_3_completed": false,
  "pause_after_step": true,
  "execution_complete": false
}
```

**实现**:

```python
@router.get("/status/{session_id}")
async def get_session_status(session_id: str):
    # 从内存会话获取基础状态
    session = _get_session_value(session_id, "initial_state", {})
    
    # 从 AsyncSqliteSaver 读取完整状态
    checkpointer = await get_global_checkpointer()
    graph = create_village_planning_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": session_id}}
    
    checkpoint_state = await graph.aget_state(config)
    state_values = checkpoint_state.values if checkpoint_state else {}
    
    return SessionStatusResponse(
        session_id=session_id,
        status=_get_session_value(session_id, "status", "running"),
        pause_after_step=state_values.get("pause_after_step", False),
        layer_1_completed=state_values.get("layer_1_completed", False),
        layer_2_completed=state_values.get("layer_2_completed", False),
        layer_3_completed=state_values.get("layer_3_completed", False),
        previous_layer=state_values.get("previous_layer"),
        pending_review_layer=state_values.get("pending_review_layer"),
        ...
    )
```

### GET /api/planning/stream/{session_id}

SSE 流式传输（维度级文本推送）。

**事件类型**:

| 事件 | 说明 | 数据 |
|------|------|------|
| `dimension_delta` | 维度增量 | `{dimension_key, delta, accumulated, layer}` |
| `dimension_complete` | 维度完成 | `{dimension_key, dimension_name, full_content, layer}` |
| `layer_completed` | 层级完成 | `{layer, report_content, dimension_reports, pause_after_step}` |
| `pause` | 暂停事件 | `{current_layer, checkpoint_id}` |

**实现**:

```python
@router.get("/stream/{session_id}")
async def stream_planning_events(session_id: str):
    async def event_generator():
        last_event_index = 0
        
        while True:
            # 获取新事件
            events = _get_session_events_copy(session_id)
            new_events = events[last_event_index:]
            
            for event in new_events:
                yield _format_sse_json(event)
                last_event_index += 1
            
            # 检查是否结束
            stream_state = _get_stream_state(session_id)
            if stream_state == "completed":
                break
            
            await asyncio.sleep(0.1)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

### POST /api/planning/review/{session_id}

人工审查操作。

**请求参数**:
```
?action=approve     # 批准继续
?action=reject      # 驳回修改
?checkpoint_id=xxx  # 回退到指定检查点
```

**批准流程实现**:

```python
@router.post("/review/{session_id}")
async def handle_review(session_id: str, action: str, ...):
    session = _sessions.get(session_id)
    state = session.get("initial_state", {})
    
    if action == "approve":
        # 清除暂停标志
        state["pause_after_step"] = False
        state["pending_review_layer"] = 0
        session["sent_pause_events"].clear()
        
        # 更新数据库状态
        await update_session_async(session_id, {"status": "running"})
        
        # 恢复执行
        await _resume_graph_execution(session_id, state)
        
        return {"message": "已批准，继续执行", "resumed": True}
```

---

## 数据流详解

### 请求启动流程

```
POST /api/planning/start
  ↓
1. 生成 session_id (时间戳格式)
  ↓
2. 创建数据库会话记录 (planning_sessions 表)
  ↓
3. 构建 LangGraph 初始状态
  ↓
4. 获取全局 AsyncSqliteSaver 单例
  ↓
5. 创建图实例 (带 checkpointer)
  ↓
6. 提交后台任务执行
  ↓
返回 {task_id, status}
```

### 后台执行流程

```
_execute_graph_in_background()
  ↓
graph.astream(initial_state, config)
  ↓
for event in stream:
  ├── 检测层级完成 → 发送 layer_completed 事件
  ├── 检测暂停状态 → 发送 pause 事件
  └── 更新内存会话状态
  ↓
执行完成 → 发送 completed 事件
```

### 状态读取流程

```
GET /api/planning/status/{session_id}
  ↓
1. 从内存获取会话元数据
  ↓
2. 从 AsyncSqliteSaver 读取完整状态
  ├── graph.aget_state(config)
  └── 提取 state_values
  ↓
3. 构建响应 SessionStatusResponse
  ↓
返回 JSON
```

---

## 状态持久化

### AsyncSqliteSaver 单例

```python
_checkpointer: Optional[AsyncSqliteSaver] = None
_checkpointer_lock = asyncio.Lock()

async def get_global_checkpointer() -> AsyncSqliteSaver:
    global _checkpointer
    
    if _checkpointer is not None:
        return _checkpointer
    
    async with _checkpointer_lock:
        if _checkpointer is not None:
            return _checkpointer
        
        import aiosqlite
        conn = await aiosqlite.connect(get_db_path(), check_same_thread=False)
        _checkpointer = AsyncSqliteSaver(conn)
        await _checkpointer.setup()
        
        return _checkpointer
```

### 数据库表结构

**planning_sessions 表** (业务元数据):
```python
class PlanningSession(SQLModel, table=True):
    session_id: str          # 主键
    project_name: str        # 项目名称
    status: str              # running/paused/completed/failed
    execution_error: str     # 错误信息
    village_data: str        # 村庄数据
    created_at: datetime
    updated_at: datetime
```

**checkpoints 表** (LangGraph 自动管理):
- 存储完整状态快照
- 包含所有层级报告、暂停状态等
- 由 AsyncSqliteSaver 自动序列化

### 状态字段说明

| 字段 | 来源 | 说明 |
|------|------|------|
| `layer_X_completed` | checkpoints | 层级完成标志 |
| `pause_after_step` | checkpoints | 步进暂停标志 |
| `previous_layer` | checkpoints | 刚完成的层级 |
| `pending_review_layer` | checkpoints | 待审查层级 |
| `analysis_dimension_reports` | checkpoints | Layer 1 维度报告 |
| `concept_dimension_reports` | checkpoints | Layer 2 维度报告 |
| `detailed_dimension_reports` | checkpoints | Layer 3 维度报告 |

---

## 暂停恢复机制

### 暂停触发

在 LangGraph 主图中，`route_after_pause()` 函数判断是否需要暂停：

```python
# src/orchestration/main_graph.py
def route_after_pause(state: VillagePlanningState):
    step_mode = state.get("step_mode", False)
    pending_review_layer = state.get("pending_review_layer", 0)
    
    # 步进模式 + 有待审查层级 → 终止执行
    if step_mode and pending_review_layer > 0:
        return "end"
    
    # 否则继续执行
    return f"layer{current_layer}_..."
```

### 后端事件发送

```python
# backend/api/planning.py - _execute_graph_in_background()
if event.get("pause_after_step"):
    previous_layer = event.get("previous_layer", 1)
    pause_event_key = f"pause_layer_{previous_layer}"
    
    if pause_event_key not in sent_pause_events:
        # 发送暂停事件
        pause_event = {
            "type": "pause",
            "session_id": session_id,
            "current_layer": previous_layer,
            "checkpoint_id": event.get("last_checkpoint_id", ""),
            "reason": "step_mode"
        }
        _append_session_event(session_id, pause_event)
        sent_pause_events.add(pause_event_key)
        
        # 更新会话状态
        _set_session_value(session_id, "status", "paused")
        await update_session_async(session_id, {"status": "paused"})
        
        return  # 终止执行
```

### 恢复执行

```python
# 批准后恢复
async def _resume_graph_execution(session_id: str, state: Dict):
    # 清除暂停标志
    state["pause_after_step"] = False
    state["pending_review_layer"] = 0
    _sessions[session_id]["sent_pause_events"].clear()
    
    # 更新数据库
    await update_session_async(session_id, {"status": "running"})
    
    # 重新创建图并执行
    checkpointer = await get_global_checkpointer()
    graph = create_village_planning_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": session_id}}
    
    async for event in graph.astream(state, config):
        # ... 处理事件
```

---

## 内存会话管理

### 会话数据结构

```python
_sessions: Dict[str, Dict[str, Any]] = {
    "session_id": {
        "initial_state": {...},      # LangGraph 状态
        "status": "running",          # 会话状态
        "events": [],                 # SSE 事件队列
        "sent_layer_events": set(),   # 已发送的层级事件
        "sent_pause_events": set(),   # 已发送的暂停事件
        "execution_complete": False,
    }
}
```

### 线程安全访问

```python
_sessions_lock = Lock()

def _get_session_value(session_id: str, key: str, default=None):
    with _sessions_lock:
        return _sessions.get(session_id, {}).get(key, default)

def _set_session_value(session_id: str, key: str, value: Any):
    with _sessions_lock:
        if session_id in _sessions:
            _sessions[session_id][key] = value
```

---

## 错误处理

### 404 处理

```python
@router.get("/status/{session_id}")
async def get_session_status(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        # 检查数据库是否存在
        db_session = await get_session_async(session_id)
        if not db_session:
            raise HTTPException(status_code=404, detail="Session not found")
```

### 执行错误处理

```python
async def _execute_graph_in_background(...):
    try:
        # ... 执行图
    except Exception as e:
        error_event = {
            "type": "error",
            "session_id": session_id,
            "error": str(e)
        }
        _append_session_event(session_id, error_event)
        
        _set_session_value(session_id, "status", "failed")
        _set_session_value(session_id, "execution_error", str(e))
```
