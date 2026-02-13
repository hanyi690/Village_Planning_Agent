# 后端实现文档 (Backend Implementation)

> **村庄规划智能体** - FastAPI 后端实现详解

## 目录

- [技术栈](#技术栈)
- [应用结构](#应用结构)
- [SSE/REST 职责分离](#sse-rest-职责分离)
- [异步数据库架构](#异步数据库架构)
- [StreamingQueueManager](#streamingqueuemanager)
- [API 端点](#api-端点)

---

## 技术栈

- **框架**: FastAPI
- **Python 版本**: 3.9+
- **异步支持**: asyncio + uvicorn
- **数据验证**: Pydantic V2
- **流式传输**: Server-Sent Events (SSE)
- **数据库**: SQLite (异步)
- **默认端口**: 8000

---

## 应用结构

```
backend/
├── main.py                     # 应用入口
├── api/                        # API 路由模块
│   ├── planning.py            # 规划执行 API
│   ├── sessions.py            # 会话管理 API
│   ├── data.py               # 数据访问 API
│   ├── validate_config.py     # 配置验证
│   └── files.py             # 文件上传 API
├── database/                   # 数据库模块
│   ├── manager.py            # 数据库管理器（异步/同步模式）
│   ├── operations_async.py    # 异步数据库操作
│   ├── async_wrapper.py      # 异步包装器（带回退）
│   ├── operations.py         # 同步数据库操作
│   └── models.py            # 数据库模型
├── services/                   # 业务逻辑层
│   ├── rate_limiter.py      # 速率限制
│   ├── redis_client.py      # Redis 客户端
│   └── session_state_manager.py  # 会话状态管理
├── schemas.py                  # Pydantic 数据模型
├── utils/                     # 后端工具类
└── requirements.txt           # 依赖列表
```

---

## SSE/REST 职责分离

### 架构设计原则

**REST 职责**：
- 提供可靠的状态查询
- 数据库作为单一真实源
- 每 2 秒轮询获取状态变化

**SSE 职责**：
- 维度级流式文本推送
- 实时 token 传输
- 错误通知

### 数据流架构

```
┌─────────────────────────────────────────────────────┐
│                      前端 (Next.js)           │
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
│              后端 (FastAPI)                    │
│  ┌──────────────────────────────────────────┐      │
│  │       异步数据库 (SQLite)              │      │
│  │  - PlanningSession 表存储所有状态      │      │
│  │  - events 字段存储事件历史          │      │
│  └──────────────────────────────────────────┘      │
│  ┌──────────────────────────────────────────┐      │
│  │    StreamingQueueManager (维度级批处理)  │      │
│  └──────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────┘
```

---

## 异步数据库架构

### 异步模式实现

**文件**: `backend/database/manager.py`

**核心特性**:
- **环境变量控制**: `USE_ASYNC_DATABASE` (默认: `"true"`)
- **双轨支持**: 异步操作 + 同步回退
- **统一接口**: 通过 `DatabaseManager.execute_operation` 路由

### 数据库模型

**文件**: `backend/database/models.py`

**核心表结构**:
```python
class PlanningSession(SQLModel, table=True):
    """规划会话表 - 数据库单一真实源"""
    __tablename__ = "planning_sessions"

    # Primary key
    session_id: str = Field(primary_key=True)

    # Basic info
    project_name: str = Field(index=True)
    status: str = Field(index=True)

    # Layer completion status
    layer_1_completed: bool = Field(default=False)
    layer_2_completed: bool = Field(default=False)
    layer_3_completed: bool = Field(default=False)

    # Pause/review state
    pause_after_step: bool = Field(default=False)

    # Event tracking (JSON field)
    events: Optional[List[Dict[str, Any]]] Field(
        default=None,
        sa_column=Column(JSON)
    )

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
```

### 异步操作实现

**文件**: `backend/database/operations_async.py`

**核心函数**:
```python
async def create_planning_session_async(state: Dict[str, Any]) -> str:
    """创建规划会话（异步版本）"""
    async with get_async_session() as session:
        db_session = PlanningSession(
            session_id=state["session_id"],
            project_name=state.get("project_name", ""),
            status="running",
            events=[],
            ...
        )
        session.add(db_session)
        await session.commit()
        return db_session.session_id

async def add_session_event_async(session_id: str, event: Dict) -> bool:
    """添加事件到 session.events JSON 字段"""
    async with get_async_session() as session:
        result = await session.execute(
            select(PlanningSession)
            .where(PlanningSession.session_id == session_id)
        )
        db_session = result.scalar_one_or_none()

        events = db_session.events or []
        events.append(event)
        db_session.events = events
        db_session.updated_at = datetime.now()

        await session.commit()
        return True
```

### 同步回退机制

**文件**: `backend/database/async_wrapper.py`

**实现**:
```python
async def create_session_async(state: Dict[str, Any]) -> str:
    """创建规划会话（异步，带同步回退）"""
    db_manager = get_db_manager()

    try:
        return await db_manager.execute_operation(
            'create_session',
            None,
            sync_ops.create_planning_session,  # sync fallback
            state
        )
    except Exception as e:
        logger.warning(f"Async create_session failed, trying sync: {e}")
        return sync_ops.create_planning_session(state)
```

---

## StreamingQueueManager

### 批处理架构

**文件**: `src/utils/streaming_queue_manager.py`

**功能**：
- 按维度隔离 token 队列
- 批处理策略（50 tokens 或 100ms 时间窗口）
- 线程安全操作（Lock 保护）
- 维度完成时返回完整内容

### 核心实现

```python
class StreamingQueueManager:
    """流式队列管理器 - 维度级批处理"""

    def __init__(
        self,
        batch_size: int = 50,
        batch_window: float = 0.1,
        flush_callback: Optional[Callable] = None
    ):
        self.batch_size = batch_size          # 50 tokens 触发刷新
        self.batch_window = batch_window      # 100ms 时间窗口
        self.flush_callback = flush_callback  # SSE 事件发射回调
        self.queues: Dict[str, List[str]] = {}  # 维度队列
        self.lock = threading.Lock()                   # 线程安全
```

### 批处理优化效果

| 指标 | 优化前 | 优化后 | 提升 |
|-------|--------|--------|------|
| Token → 前端延迟 | ~500ms | <100ms | **80%** |
| SSE 事件数量 | 频繁 | 减少 >80% | **5x** |

---

## API 端点

### 规划执行 API (`/api/planning`)

**文件**: `backend/api/planning.py`

#### POST `/api/planning/start`

**功能**: 启动新的规划任务

**响应**:
```json
{
  "success": true,
  "task_id": "20240206_123456",
  "status": "running",
  "message": "规划任务已启动"
}
```

#### GET `/api/planning/status/{task_id}`

**功能**: 获取任务可靠状态 - 数据库作为单一真实源

**响应结构**:
```json
{
  "task_id": "20240206_123456",
  "project_name": "示例村庄",
  "status": "running",
  "layer_1_completed": true,
  "layer_2_completed": false,
  "layer_3_completed": false,
  "pause_after_step": false,
  "waiting_for_review": false,
  "current_layer": 2
}
```

#### GET `/api/planning/stream/{task_id}`

**功能**: SSE 流式传输 - 维度级事件

**事件类型**:
```typescript
// 维度增量事件
event: dimension_delta
data: {
  "dimension_key": "location",
  "dimension_name": "区位分析",
  "layer": 1,
  "chunk": "村庄的地理位置...",
  "accumulated": "村庄的地理位置位于..."
}

// 维度完成事件
event: dimension_complete
data: {
  "dimension_key": "location",
  "full_content": "完整维度的报告内容..."
}
```

---

## 启动和配置

### 生命周期管理

**文件**: `backend/main.py`

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 初始化数据库
    from backend.database import init_db
    if init_db():
        logger.info("✅ Database initialized successfully")

    # 初始化异步引擎
    use_async = os.getenv("USE_ASYNC_DATABASE", "true").lower() == "true"
    if use_async:
        from backend.database.operations_async import get_async_engine
        await get_async_engine()
        logger.info("✅ Async database engine initialized")

    yield

    # 清理资源
    if use_async:
        from backend.database.operations_async import dispose_async_engine
        await dispose_async_engine()
        logger.info("✅ Async engine disposed")
```

### 环境变量

```env
# 数据库模式 (默认: true)
USE_ASYNC_DATABASE=true
```

- `true`: 异步模式（推荐，支持并发）
- `false`: 同步模式（回退选项）

---

## 相关文档

- **[前端实现文档](frontend.md)** - Next.js 14 技术栈、维度级流式响应、SSE/REST 解耦
- **[核心智能体文档](agent.md)** - LangGraph 架构、三层规划系统
- **[前端组件架构](../FRONTEND_COMPONENT_ARCHITECTURE.md)** - 组件设计、状态管理
- **[前端视觉指南](../FRONTEND_VISUAL_GUIDE.md)** - UI/UX 设计规范
- **[README](../README.md)** - 项目概述和快速开始

---

**最后更新**: 2026-02-12
**维护者**: Village Planning Agent Team
