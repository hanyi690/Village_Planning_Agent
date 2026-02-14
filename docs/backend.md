# 后端实现文档 (Backend Implementation)

> **村庄规划智能体** - FastAPI 后端实现详解

## 目录

- [技术栈](#技术栈)
- [应用结构](#应用结构)
- [AsyncSqliteSaver 状态持久化](#asyncsqlitesaver-状态持久化)
- [SSE/REST 职责分离](#sse-rest-职责分离)
- [数据流架构](#数据流架构)
- [API 端点](#api-端点)
- [暂停/恢复机制](#暂停恢复机制)

---

## 技术栈

- **框架**: FastAPI
- **Python 版本**: 3.9+
- **异步支持**: asyncio + uvicorn
- **数据验证**: Pydantic V2
- **流式传输**: Server-Sent Events (SSE)
- **数据库**: SQLite (AsyncSqliteSaver)
- **LangGraph**: 1.0.8+
- **langgraph-checkpoint-sqlite**: 3.0.3+
- **默认端口**: 8000

---

## 应用结构

```
backend/
├── main.py                     # 应用入口
├── api/                        # API 路由模块
│   ├── planning.py            # 规划执行 API (REST + SSE)
│   ├── sessions.py            # 会话管理 API
│   ├── data.py               # 数据访问 API
│   ├── validate_config.py     # 配置验证
│   └── files.py             # 文件上传 API
├── database/                   # 数据库模块
│   ├── models.py               # 数据库模型（精简版）
│   ├── operations_async.py     # 异步数据库操作
│   └── engine.py              # 数据库引擎
├── services/                   # 业务逻辑层
│   ├── rate_limiter.py      # 速率限制
│   ├── session_state_manager.py  # 会话状态管理
│   └── sse_event_stream.py   # SSE 事件流
├── schemas.py                  # Pydantic 数据模型
├── utils/                     # 后端工具类
└── requirements.txt           # 依赖列表
```

---

## AsyncSqliteSaver 状态持久化

### 架构设计

**核心概念**: SQLite 作为 AI 的"自动硬盘"

```
┌─────────────────────────────────────────────────────┐
│                LangGraph 执行图                    │
│                                                      │
│  状态变化 → AsyncSqliteSaver.put()                  │
│             ↓                                      │
│  自动序列化 → checkpoints 表                        │
│                                                      │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│              SQLite 数据库                         │
│                                                      │
│  ┌──────────────────────────────────────────┐       │
│  │   planning_sessions 表 (业务元数据)       │       │
│  │   - session_id, project_name, status     │       │
│  │   - created_at, updated_at               │       │
│  └──────────────────────────────────────────┘       │
│                                                      │
│  ┌──────────────────────────────────────────┐       │
│  │   checkpoints 表 (AI 状态快照)            │       │
│  │   - thread_id                            │       │
│  │   - checkpoint_id                        │       │
│  │   - checkpoint (JSON/二进制)             │       │
│  │   - layer_X_completed                    │       │
│  │   - analysis_report                     │       │
│  │   - planning_concept                    │       │
│  │   - detailed_plan                       │       │
│  └──────────────────────────────────────────┘       │
│                                                      │
│  ┌──────────────────────────────────────────┐       │
│  │   checkpoints_blobs 表 (二进制数据)       │       │
│  │   - checkpoint_id                        │       │
│  │   - blob                                 │       │
│  └──────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────┘
```

### 全局 Checkpointer 单例

**文件**: `backend/api/planning.py`

```python
# 全局 checkpointer 实例（应用级别共享）
_checkpointer: Optional[AsyncSqliteSaver] = None
_checkpointer_lock = asyncio.Lock()

async def get_global_checkpointer() -> AsyncSqliteSaver:
    """
    获取全局 AsyncSqliteSaver 实例（单例模式）

    使用单例模式避免重复创建连接和调用 setup()，提高性能。
    """
    global _checkpointer, _checkpointer_initialized

    if _checkpointer is not None and _checkpointer_initialized:
        return _checkpointer

    async with _checkpointer_lock:
        if _checkpointer is not None and _checkpointer_initialized:
            return _checkpointer

        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        conn = await aiosqlite.connect(get_db_path(), check_same_thread=False)
        _checkpointer = AsyncSqliteSaver(conn)
        await _checkpointer.setup()

        _checkpointer_initialized = True
        return _checkpointer
```

### LangGraph 集成

**文件**: `src/orchestration/main_graph.py`

```python
def create_village_planning_graph(checkpointer: Optional[BaseCheckpointSaver] = None):
    """
    创建村庄规划主图，使用 AsyncSqliteSaver 进行状态持久化
    """
    if checkpointer is None:
        # checkpointer 由调用方提供（从全局单例获取）
        logger.info("[主图构建] Using provided checkpointer (persistent storage)")

    # ... 图构建逻辑

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"]
    )
```

### 状态查询流程

```
API: GET /api/planning/status/{session_id}
  ↓
config = {"configurable": {"thread_id": session_id}}
  ↓
checkpointer = get_global_checkpointer()
graph = create_village_planning_graph(checkpointer)
  ↓
checkpoint_state = await graph.get_state(config)
  ↓
AsyncSqliteSaver.get(config)
  ↓
从 checkpoints 表读取完整状态
  ↓
提取状态值 (layer_X_completed, status, etc.)
  ↓
返回 SessionStatusResponse
```

### 数据库模型精简

**文件**: `backend/database/models.py`

**关键变化**: 删除手动维护的状态字段

```python
class PlanningSession(SQLModel, table=True):
    """
    规划会话表 - 只存储业务元数据
    AI 状态由 AsyncSqliteSaver 自动管理
    """
    __tablename__ = "planning_sessions"

    # Primary key
    session_id: str = Field(primary_key=True)

    # Basic info
    project_name: str = Field(index=True)
    status: str = Field(index=True)

    # Village data
    village_data: Optional[str] = Field(default=None, sa_column=Text())

    # Task info
    task_description: str = Field(default="制定村庄总体规划方案")
    constraints: str = Field(default="无特殊约束")
    output_path: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # 注释：以下字段已删除，由 AsyncSqliteSaver 管理
    # - layer_X_completed
    # - pause_after_step
    # - need_human_review
    # - state_snapshot
    # - events
    # - current_layer
    # - 等等...
```

### 优势

✅ **自动管理**: LangGraph 自动保存状态，无需手动维护
✅ **代码简洁**: 删除了 12+ 个手动维护的字段
✅ **数据一致性**: AI 状态 = 数据库内容，天然匹配
✅ **毫秒级恢复**: 从 checkpoint 毫秒级还原完整状态

---

## SSE/REST 职责分离

### 架构设计原则

**REST 职责**：
- 提供可靠的状态查询
- AsyncSqliteSaver 作为状态源
- 每 2 秒轮询获取状态变化

**SSE 职责**：
- 维度级流式文本推送
- 实时 token 传输
- 错误通知

### 数据流架构

```
┌─────────────────────────────────────────────────────┐
│                   前端 (Next.js)                   │
│  ┌──────────────────────────────────────────┐      │
│  │         TaskController (状态管理层)      │      │
│  │  ┌────────────────────────────────────┐ │      │
│  │  │  REST 轮询 (每 2 秒)            │ │      │
│  │  │  GET /api/planning/status/{id}    │ │      │
│  │  └────────────────────────────────────┘ │      │
│  │  ┌────────────────────────────────────┐ │      │
│  │  │  SSE (维度级流式)                │ │      │
│  │  │  GET /api/planning/stream/{id}    │ │      │
│  │  └────────────────────────────────────┘ │      │
│  └──────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────┐
│                后端 (FastAPI)                       │
│  ┌──────────────────────────────────────────┐      │
│  │  AsyncSqliteSaver (状态持久化)          │      │
│  │  ↓  checkpoints 表 (自动管理)            │      │
│  │  - layer_X_completed                   │      │
│  │  - analysis_report                     │      │
│  │  - planning_concept                    │      │
│  │  - sent_pause_events (内存状态)        │      │
│  └──────────────────────────────────────────┘      │
│  ┌──────────────────────────────────────────┐      │
│  │    PauseManagerNode (暂停管理)         │      │
│  └──────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────┘
```

---

## 数据流架构

### REST 数据流（状态同步）

```
前端: TaskController (每2秒轮询)
  ↓
后端: GET /api/planning/status/{session_id}
  ↓
config = {"configurable": {"thread_id": session_id}}
  ↓
graph.get_state(config)
  ↓
AsyncSqliteSaver.get(config)
  ↓
从 checkpoints 表读取完整状态
  ↓
提取状态值 (pauseAfterStep, layer_X_completed, etc.)
  ↓
返回: SessionStatusResponse
  ↓
前端: 更新 UI 状态、触发回调
```

### SSE 数据流（流式文本）

```
前端: useTaskSSE
  ↓
后端: GET /api/planning/stream/{session_id}
  ↓
维度级批处理
  ↓
SSE 事件: dimension_delta, dimension_complete
  ↓
前端: 实时显示流式文本
```

### 状态保存流程

```
LangGraph 节点执行
  ↓
状态更新: state["layer_1_completed"] = True
  ↓
graph.update_state(config, updates)
  ↓
AsyncSqliteSaver.put(config, checkpoint)
  ↓
自动序列化 → checkpoints 表
  ↓
返回新 checkpoint_id
```

---

## API 端点

### 1. POST /api/planning/start

启动新的规划任务

**请求体**:
```json
{
  "project_name": "金田村规划",
  "task_description": "制定村庄总体规划方案",
  "village_data": "...",
  "step_mode": true
}
```

**响应**:
```json
{
  "task_id": "uuid",
  "status": "running",
  "message": "规划任务已启动"
}
```

### 2. GET /api/planning/status/{session_id}

获取规划会话状态（从 AsyncSqliteSaver 读取）

**响应**:
```json
{
  "session_id": "uuid",
  "status": "running",
  "current_layer": 1,
  "layer_1_completed": false,
  "layer_2_completed": false,
  "layer_3_completed": false,
  "pause_after_step": false,
  "waiting_for_review": false,
  "execution_complete": false,
  "progress": 33.3
}
```

**实现**:
```python
@router.get("/api/planning/status/{session_id}")
async def get_session_status(session_id: str):
    # 从内存状态获取 sent_pause_events
    session_state = _get_session_value(session_id, "sent_pause_events", set())
    pause_after_step = len(session_state) > 0

    return {
        "session_id": session_id,
        "pause_after_step": pause_after_step,
        "waiting_for_review": pause_after_step,
        # ... 其他状态
    }
```

### 3. GET /api/planning/stream/{session_id}

SSE 流式传输（维度级文本）

**事件类型**:
- `dimension_delta`: 维度增量 token
- `dimension_complete`: 维度完成
- `layer_progress`: 层级进度
- `error`: 错误通知

### 4. POST /api/planning/review/{session_id}

人工审查操作

**请求参数**:
- `action`: approve/reject/rollback
- `feedback`: 反馈内容（可选）
- `checkpoint_id`: 检查点ID（回退时需要）

**响应**:
```json
{
  "message": "已批准，继续执行",
  "current_layer": 2,
  "resumed": true
}
```

---

## 暂停/恢复机制

### 暂停流程

```
步进模式 (step_mode=True)
  ↓
层级完成 (layer_X_completed=True)
  ↓
PauseManagerNode 检测到暂停条件
  ↓
设置 state["pause_after_step"] = True
  ↓
后台执行检测到 pause_after_step
  ↓
生成 pause_event_key = f"pause_layer_{current_layer}"
  ↓
如果 pause_event_key 不在 sent_pause_events 中:
  ↓
发送 pause 事件
  ↓
sent_pause_events.add(pause_event_key)
  ↓
_set_session_value(session_id, "sent_pause_events", sent_pause_events)
  ↓
前端 REST 轮询检测到 pauseAfterStep=true
  ↓
显示审查 UI
```

**关键代码** (`backend/api/planning.py:586`):
```python
sent_pause_events.add(pause_event_key)
_set_session_value(session_id, "sent_pause_events", sent_pause_events)  # 保存回session
```

### 恢复流程

```
用户点击"批准"
  ↓
POST /api/planning/review/{session_id}?action=approve
  ↓
清除 pause 标志:
  - initial_state["pause_after_step"] = False
  - session["sent_pause_events"].clear()
  ↓
推进 current_layer
  ↓
调用 _resume_graph_execution()
  ↓
继续执行 LangGraph
```

**关键代码** (`backend/api/planning.py:1114`):
```python
sent_pause_events = session.get("sent_pause_events", set())
if sent_pause_events:
    # 清除旧的 pause 事件
    for event_key in sent_pause_events:
        sent_pause_events.discard(event_key)
    session["sent_pause_events"] = sent_pause_events
```

---

## 核心优势

### 1. AsyncSqliteSaver 状态持久化
- 自动管理，无需手动维护
- 双重表设计（checkpoints + checkpoints_blobs）
- 毫秒级恢复

### 2. SSE/REST 解耦
- REST 可靠状态查询
- SSE 流式文本推送
- 无去重风险

### 3. 双表精简设计
- 业务表：只存储元数据
- 检查点表：AsyncSqliteSaver 自动管理

### 4. 暂停机制
- 层级作用域去重
- 状态抖动检测
- 内存状态持久化（_set_session_value）