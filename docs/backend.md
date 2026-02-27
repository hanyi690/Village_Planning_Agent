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
│    ├── ui_sessions        UI会话                           │
│    ├── ui_messages        UI消息                           │
│    └── checkpoints        LangGraph状态 (AsyncSqliteSaver)  │
│                                                             │
│  _sessions 内存: 运行时状态 + SSE事件队列                    │
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
| `/api/planning/health` | GET | 健康检查 |
| `/api/planning/sessions` | GET | 列出活跃会话 |
| `/api/planning/rate-limit/status` | GET | 限流状态 |
| `/api/planning/rate-limit/reset/{project_name}` | POST | 重置限流 |

### Data API (`/api/data/*`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/data/villages` | GET | 列出所有村庄 |
| `/api/data/villages/{name}/sessions` | GET | 获取村庄会话 |
| `/api/data/villages/{name}/layers/{layer}` | GET | 获取层级内容 |
| `/api/data/villages/{name}/checkpoints` | GET | 获取检查点 |
| `/api/data/villages/{name}/compare/{cp1}/{cp2}` | GET | 比较检查点 |
| `/api/data/villages/{name}/plan` | GET | 获取综合规划 |

### Files API (`/api/files/*`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/files/upload` | POST | 上传并解码文件 |

**支持格式**: Word (.docx, .doc), PDF, Excel (.xlsx, .xls), PowerPoint (.pptx, .ppt), 纯文本

## 核心端点详解

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

**请求模型**:
```python
class StartPlanningRequest(BaseModel):
    project_name: str          # 项目名称
    village_data: str          # 村庄现状数据
    task_description: str      # 规划任务描述
    constraints: str           # 规划约束条件
    enable_review: bool        # 启用人工审查
    step_mode: bool            # 步进模式
    stream_mode: bool          # 流式输出
```

### GET /api/planning/status/{session_id}

**核心端点** - 状态查询 (REST 轮询)

**响应字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | 运行状态: running/paused/reviewing/revising/completed/failed |
| pause_after_step | boolean | 步进模式暂停标志 |
| previous_layer | number | 刚完成的层级 (待审查) |
| layer_X_completed | boolean | 层级完成状态 |
| execution_complete | boolean | 执行是否完成 |
| current_layer | number | 当前执行层级 |
| checkpoints | array | 检查点列表 |

### GET /api/planning/stream/{session_id}

SSE 流式输出

**事件类型**:

| 事件 | 数据 |
|------|------|
| dimension_delta | {layer, dimension, delta, accumulated} |
| dimension_complete | {layer, dimension, content} |
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
    
    elif request.action == "reject":
        # 记录反馈，触发修复
        ...
    
    elif request.action == "rollback":
        # 回退到指定检查点
        ...
```

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
      └─▶ 提交后台任务
      │
返回 {task_id, status}
```

### 后台执行

```python
async def _execute_graph_in_background(session_id, graph, initial_state, checkpointer):
    config = {"configurable": {"thread_id": session_id}}
    
    async for event in graph.astream(initial_state, config):
        # 检测维度增量 → 发送 dimension_delta 事件
        if "dimension_delta" in event:
            await _append_session_event_async(session_id, {
                "type": "dimension_delta",
                "layer": layer,
                "dimension": dimension,
                "delta": delta,
            })
        
        # 检测维度完成 → 发送 dimension_complete 事件
        if event.get("dimension_complete"):
            await _append_session_event_async(session_id, {
                "type": "dimension_complete",
                "layer": layer,
                "dimension": dimension,
                "content": content,
            })
        
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
        "session_id": str,
        "project_name": str,
        "status": TaskStatus,
        "initial_state": {...},      # LangGraph 状态
        "events": deque,             # SSE 事件队列
        "execution_complete": bool,
        "execution_error": Optional[str],
        "sent_layer_events": set,    # 已发送的层级事件（去重）
        "sent_revised_events": set,  # 已发送的修订事件（去重）
        "sent_pause_events": set,    # 已发送的暂停事件（去重）
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

## 数据库模型

**文件**: `database/models.py`

```python
class PlanningSession(SQLModel, table=True):
    __tablename__ = "planning_sessions"
    
    session_id: str           # 主键
    project_name: str         # 项目名称 (索引)
    status: str               # running/paused/completed/failed (索引)
    execution_error: Optional[str]
    village_data: Optional[str]
    task_description: str
    constraints: str
    output_path: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]

class UISession(SQLModel, table=True):
    __tablename__ = "ui_sessions"
    
    conversation_id: str      # 主键
    status: str               # idle/active (索引)
    project_name: Optional[str]
    task_id: Optional[str]    # 关联规划会话
    created_at: datetime
    updated_at: datetime

class UIMessage(SQLModel, table=True):
    __tablename__ = "ui_messages"
    
    id: Optional[int]         # 主键 (自增)
    session_id: str           # 外键
    role: str                 # user/assistant/system
    content: str
    message_type: str         # text/file/progress/action/result/error
    message_metadata: Optional[Dict]
    timestamp: datetime
```

## 服务模块

### RateLimiter (限流器)

**文件**: `services/rate_limiter.py`

```python
class RateLimiter:
    """限流管理器 - 单例模式"""
    
    window_seconds: int = 5       # 时间窗口
    max_requests: int = 3         # 最大请求数
    cooldown_seconds: int = 10    # 冷却时间
    
    def check_rate_limit(project_name, session_id) -> tuple[bool, str]
    def mark_task_started(project_name) -> None
    def mark_task_completed(project_name, success) -> None
    def get_status() -> dict
    def reset_project(project_name) -> bool
```

## 工具模块

| 模块 | 文件 | 功能 |
|------|------|------|
| error_handler | utils/error_handler.py | 统一错误处理，标准化 HTTPException |
| progress_helper | utils/progress_helper.py | 进度计算（根据层级计算百分比） |
| logging | utils/logging.py | 日志装饰器，支持性能追踪 |
| session_helper | utils/session_helper.py | 会话目录查找和解析 |

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
| `backend/api/files.py` | 文件上传 API |
| `backend/database/models.py` | SQLModel 数据模型 |
| `backend/database/engine.py` | 数据库引擎管理 |
| `backend/database/operations_async.py` | 异步 CRUD 操作 |
| `backend/services/rate_limiter.py` | 限流器 |
| `backend/utils/error_handler.py` | 错误处理 |
| `backend/utils/progress_helper.py` | 进度计算 |
