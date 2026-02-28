# 后端实现文档

> FastAPI 后端架构 - REST 状态同步 + SSE 流式输出

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
│                    backend/main.py                           │
└─────────────────────────────────────────────────────────────┘
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ planning_router │     │  data_router    │     │  files_router   │
│ api/planning.py │     │   api/data.py   │     │   api/files.py  │
└────────┬────────┘     └────────┬────────┘     └─────────────────┘
         │                       │
         └───────────────────────┼───────────────────────┐
                                 ▼                       │
┌─────────────────────────────────────────────────────────────┐
│                   Storage Layer                              │
│  SQLite (village_planning.db):                              │
│    ├── planning_sessions  业务元数据                        │
│    ├── ui_sessions        UI会话                           │
│    ├── ui_messages        UI消息                           │
│    └── checkpoints        LangGraph状态 (AsyncSqliteSaver)  │
└─────────────────────────────────────────────────────────────┘
```

## API 端点

### Planning API (`/api/planning/*`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/planning/start` | POST | 启动新规划会话 |
| `/api/planning/stream/{session_id}` | GET | SSE 流式输出 |
| `/api/planning/status/{session_id}` | GET | 获取会话状态 |
| `/api/planning/review/{session_id}` | POST | 审查操作 |
| `/api/planning/sessions/{session_id}` | DELETE | 删除会话 |
| `/api/planning/resume` | POST | 从检查点恢复 |
| `/api/planning/checkpoints/{project_name}` | GET | 列出检查点 |

### Data API (`/api/data/*`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/data/villages` | GET | 列出所有村庄 |
| `/api/data/villages/{name}/sessions` | GET | 获取村庄会话 |
| `/api/data/villages/{name}/layers/{layer}` | GET | 获取层级内容 |
| `/api/data/villages/{name}/checkpoints` | GET | 获取检查点 |

### Files API (`/api/files/*`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/files/upload` | POST | 上传并解码文件 |

**支持格式**: Word (.docx, .doc), PDF, Excel (.xlsx, .xls), PowerPoint (.pptx, .ppt), 纯文本 (.txt, .md)

**技术实现**: 使用 MarkItDown (Microsoft) 将文档转换为 Markdown，保留结构便于 LLM 处理。

## 核心端点详解

### POST /api/planning/start

启动规划任务

```python
@router.post("/start")
async def start_planning(request: StartPlanningRequest):
    # 1. 限流检查
    allowed, msg = rate_limiter.check_rate_limit(request.project_name)
    
    # 2. 创建数据库记录
    await create_session_async(session_state)
    
    # 3. 获取全局 checkpointer 单例
    checkpointer = await get_global_checkpointer()
    
    # 4. 创建图实例
    graph = create_village_planning_graph(checkpointer=checkpointer)
    
    # 5. 后台执行 (asyncio.create_task)
    asyncio.create_task(_execute_graph_in_background(...))
    
    return {"task_id": session_id, "status": "running"}
```

**请求模型**:
```python
class StartPlanningRequest(BaseModel):
    project_name: str          # 项目名称
    village_data: str          # 村庄现状数据
    task_description: str      # 规划任务描述
    constraints: str           # 规划约束条件
    enable_review: bool        # 启用人工审查
    step_mode: bool            # 步进模式
```

### GET /api/planning/status/{session_id}

**核心端点** - 状态查询 (REST 轮询，前端每2秒调用)

**响应字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | 运行状态: running/paused/reviewing/completed/failed |
| previous_layer | number | 刚完成的层级 (待审查) |
| layer_X_completed | boolean | 层级完成状态 |
| execution_complete | boolean | 执行是否完成 |
| current_layer | number | 当前执行层级 |

### GET /api/planning/stream/{session_id}

SSE 流式输出

**事件类型**:

| 事件 | 数据 | 说明 |
|------|------|------|
| content_delta | {delta} | 文本增量 |
| dimension_delta | {layer, dimension, delta} | 维度内容增量 |
| dimension_complete | {layer, dimension, content} | 维度完成 |
| error | {message} | 错误信息 |

### POST /api/planning/review/{session_id}

审查操作

**请求模型**:
```python
class ReviewActionRequest(BaseModel):
    action: str                # approve | reject | rollback
    feedback: Optional[str]    # 反馈内容（驳回时必填）
    dimensions: Optional[List[str]]  # 审查维度
    checkpoint_id: Optional[str]     # 检查点ID（回退时必填）
```

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
      └─▶ asyncio.create_task(_execute_graph_in_background)
      │
返回 {task_id, status}
```

### 后台执行

```python
async def _execute_graph_in_background(session_id, graph, initial_state):
    config = {"configurable": {"thread_id": session_id}}
    
    async for event in graph.astream(initial_state, config):
        # 维度增量 → SSE事件
        if "dimension_delta" in event:
            await _append_session_event(session_id, {
                "type": "dimension_delta",
                "layer": layer,
                "dimension": dimension,
                "delta": delta,
            })
        
        # 维度完成 → SSE事件
        if event.get("dimension_complete"):
            await _append_session_event(session_id, {
                "type": "dimension_complete",
                ...
            })
        
        # 检测暂停 → 等待审查
        if event.get("pause_after_step"):
            await _append_session_event(session_id, {"type": "pause", ...})
            return  # 终止执行
```

### 状态同步

```
前端 TaskController (每2秒)
      │
      ▼ GET /api/planning/status/{id}
      │
      ├─▶ 数据库: 业务元数据 (status, created_at)
      ├─▶ LangGraph checkpoint: 层级完成状态
      └─▶ 组装响应
      │
返回 JSON → 前端 syncBackendState()
```

## 状态管理

### AsyncSqliteSaver 单例

```python
_checkpointer: Optional[AsyncSqliteSaver] = None

async def get_global_checkpointer() -> AsyncSqliteSaver:
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    
    conn = await aiosqlite.connect(get_db_path())
    _checkpointer = AsyncSqliteSaver(conn)
    await _checkpointer.setup()
    return _checkpointer
```

### 内存会话状态

```python
_sessions: Dict[str, Dict] = {
    "session_id": {
        "session_id": str,
        "project_name": str,
        "status": TaskStatus,
        "initial_state": {...},      # LangGraph 状态
        "events": deque,             # SSE 事件队列
        "execution_complete": bool,
        "execution_error": Optional[str],
    }
}
```

## 暂停恢复机制

### 触发暂停

```python
# LangGraph 执行中检测到 pause_after_step
if event.get("pause_after_step"):
    # 添加 pause 事件
    await _append_session_event(session_id, {"type": "pause", ...})
    
    # 更新状态
    await update_session_async(session_id, {"status": TaskStatus.paused})
    
    return  # 终止执行，等待审查
```

### 恢复执行

```python
async def _resume_graph_execution(session_id: str, state: Dict):
    # 清除暂停标志
    state["pause_after_step"] = False
    state["previous_layer"] = 0
    
    # 使用 aupdate_state 更新 checkpoint
    await graph.aupdate_state(config, {"pause_after_step": False})
    
    # 启动后台任务继续执行
    asyncio.create_task(_execute_graph_in_background(...))
```

## 数据库模型

**文件**: `backend/database/models.py`

```python
class PlanningSession(SQLModel, table=True):
    session_id: str           # 主键
    project_name: str         # 项目名称
    status: str               # running/paused/completed/failed
    village_data: Optional[str]
    task_description: str
    created_at: datetime
    updated_at: datetime

class UISession(SQLModel, table=True):
    conversation_id: str      # 主键
    status: str               # idle/active
    task_id: Optional[str]    # 关联规划会话
    created_at: datetime

class UIMessage(SQLModel, table=True):
    id: Optional[int]         # 主键 (自增)
    session_id: str           # 外键
    role: str                 # user/assistant/system
    content: str
    message_type: str         # text/file/progress/result/error
    timestamp: datetime
```

## 服务模块

### RateLimiter (限流器)

```python
class RateLimiter:
    window_seconds: int = 5       # 时间窗口
    max_requests: int = 3         # 最大请求数
    cooldown_seconds: int = 10    # 冷却时间
    
    def check_rate_limit(project_name) -> tuple[bool, str]
    def mark_task_started(project_name) -> None
    def mark_task_completed(project_name, success) -> None
    def reset_project(project_name) -> bool
```

## 关键文件索引

| 文件 | 功能 |
|------|------|
| `backend/main.py` | FastAPI 应用入口 |
| `backend/schemas.py` | Pydantic 请求/响应模型 |
| `backend/api/planning.py` | 规划 API 核心 |
| `backend/api/data.py` | 数据访问 API |
| `backend/api/files.py` | 文件上传 API |
| `backend/database/models.py` | SQLModel 数据模型 |
| `backend/database/operations_async.py` | 异步 CRUD 操作 |
| `backend/services/rate_limiter.py` | 限流器 |