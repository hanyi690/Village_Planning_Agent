# FastAPI 后端架构分析报告

> **相关文档**: [系统架构总览](architecture.md) | [数据流转](data-flow-architecture.md)
>
> 生成时间：2026-04-05
> 项目版本：3.0.0
> 分析范围：backend/ 目录

---

## 目录

1. [架构概览](#架构概览)
2. [应用入口与生命周期](#应用入口与生命周期)
3. [API 路由模块](#api-路由模块)
4. [服务层](#服务层)
5. [数据库层](#数据库层)
6. [数据模型层](#数据模型层)
7. [技术栈总结](#技术栈总结)
8. [关键设计模式](#关键设计模式)

---

## 架构概览

### 项目结构

```
backend/
├── main.py                          # 应用入口
├── schemas.py                       # Pydantic 数据模型
├── api/
│   ├── routes.py                    # 路由注册
│   ├── planning.py                  # 核心规划接口
│   ├── data.py                      # 数据访问接口
│   ├── files.py                     # 文件上传接口
│   ├── knowledge.py                 # 知识库管理接口
│   ├── tool_manager.py              # 工具管理器
│   └── validate_config.py           # 配置验证
├── services/
│   ├── planning_service.py          # 规划执行服务 ⭐
│   ├── sse_manager.py               # SSE 连接管理 ⭐
│   ├── checkpoint_service.py        # 检查点服务 ⭐
│   ├── session_service.py           # 会话管理 ⭐
│   ├── review_service.py            # 审查服务 ⭐
│   └── rate_limiter.py              # API 限流
├── database/
│   ├── engine.py                    # 数据库引擎配置
│   ├── models.py                    # SQLModel 数据模型
│   └── operations_async.py          # 异步 CRUD 操作
└── utils/
    └── ...
```

### 注册的路由器

| 路由器 | 前缀 | 标签 | 功能 |
|--------|------|------|------|
| `planning_router` | `/api/planning` | Planning | 规划执行核心接口 |
| `data_router` | `/api/data` | Data | 数据访问接口 |
| `files.router` | `/api/files` | Files | 文件上传接口 |
| `knowledge.router` | `/api/knowledge` | Knowledge | 知识库管理接口 |

---

## 应用入口与生命周期

### 文件：`backend/main.py`

#### 启动配置

```python
app = FastAPI(
    title="村庄规划智能体 API",
    description="Router Agent 架构 - Send API 并行执行",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)
```

#### 生命周期管理 (lifespan)

**启动时执行：**
1. 确保工作目录存在
2. 设置 HuggingFace 环境
3. 验证配置文件
4. 初始化异步数据库
5. 启动会话清理后台任务（TTL: 24 小时）

**关闭时执行：**
1. 释放数据库连接
2. 停止会话清理任务

#### CORS 配置

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if IS_PRODUCTION else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
```

---

## API 路由模块

### 1. planning.py - 核心规划接口

**文件路径：** `backend/api/planning.py`

#### 主要端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/planning/start` | POST | 创建并启动规划会话 |
| `/api/planning/stream/{session_id}` | GET | SSE 流式输出 |
| `/api/planning/status/{session_id}` | GET | 查询会话状态 |
| `/api/planning/layers/{session_id}/{layer}` | GET | 获取层级报告 |
| `/api/planning/review/{session_id}` | POST | 审查操作 |
| `/api/planning/messages/{session_id}` | GET/POST | UI 消息管理 |
| `/api/planning/sessions/{session_id}` | DELETE | 删除会话 |
| `/api/planning/resume` | POST | 恢复会话 |

#### 核心特性

**1. PlanningService 业务逻辑分离**

```python
@router.post("/start")
async def start_planning(
    request: StartPlanningRequest,
    background_tasks: BackgroundTasks
):
    # 调用服务层
    session_id = await planning_service.start_planning(
        project_name=request.project_name,
        village_data=request.village_data,
        ...
    )
    return {"task_id": session_id, "status": "running"}
```

**2. SSEManager 集中式状态管理**

```python
@router.get("/stream/{session_id}")
async def stream_events(session_id: str):
    queue = await sse_manager.subscribe_session(session_id)

    async def event_generator():
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

---

### 2. data.py - 数据访问接口

**文件路径：** `backend/api/data.py`

#### 主要端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/data/villages` | GET | 列出所有村庄 |
| `/api/data/villages/{name}/sessions` | GET | 获取村庄会话列表 |
| `/api/data/villages/{name}/layers/{layer}` | GET | 获取层级内容 |
| `/api/data/villages/{name}/checkpoints` | GET | 获取检查点 |

---

### 3. files.py - 文件上传接口

**支持格式：**
- Word: `.docx`, `.doc`
- PDF: `.pdf`
- Excel: `.xlsx`, `.xls`
- PowerPoint: `.pptx`, `.ppt`
- 文本: `.txt`, `.md`, `.py`, `.js`

---

### 4. knowledge.py - 知识库管理接口

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/knowledge/documents` | GET | 列出可用文档 |
| `/api/knowledge/documents` | POST | 上传文档 |
| `/api/knowledge/sync` | POST | 同步源目录 |

---

## 服务层 ⭐

### 架构重构

服务层从 API 层分离，实现业务逻辑集中管理：

```
backend/services/
├── planning_service.py      # 规划执行核心逻辑
├── sse_manager.py           # SSE 连接和状态管理
├── checkpoint_service.py    # 检查点操作
├── session_service.py       # 会话 CRUD
├── review_service.py        # 审查操作
└── rate_limiter.py          # API 限流
```

### 1. PlanningService

**文件：** `backend/services/planning_service.py`

```python
class PlanningService:
    """规划执行核心服务"""

    @staticmethod
    def build_initial_state(...) -> Dict[str, Any]:
        """构建 UnifiedPlanningState 初始状态"""
        return {
            "session_id": session_id,
            "project_name": project_name,
            "messages": [],
            "phase": "init",
            "current_wave": 1,
            "reports": {"layer1": {}, "layer2": {}, "layer3": {}},
            "completed_dimensions": {"layer1": [], "layer2": [], "layer3": []},
            "dimension_results": [],
            "sse_events": [],
            "pending_review": False,
            "step_mode": step_mode,
            "pause_after_step": False,
            "previous_layer": 0,
        }

    @staticmethod
    async def execute_graph_background(
        session_id: str,
        graph,
        initial_state: Dict[str, Any],
        checkpointer
    ):
        """后台执行 Router Agent 图"""
        config = {"configurable": {"thread_id": session_id}}

        async for event in graph.astream(initial_state, config, stream_mode="values"):
            # 发布 SSE 事件
            sse_manager.publish_event(session_id, build_sse_event(event))

            # 检查暂停
            if event.get("pause_after_step"):
                break
```

### 2. SSEManager

**文件：** `backend/services/sse_manager.py`

```python
class SSEManager:
    """集中式 SSE 连接和事件管理"""

    # 全局状态
    _sessions: Dict[str, Dict[str, Any]] = {}
    _session_subscribers: Dict[str, Set[asyncio.Queue]] = {}
    _active_executions: Dict[str, bool] = {}
    _stream_states: Dict[str, str] = {}

    # 线程安全锁
    _sessions_lock = Lock()
    _subscribers_lock = Lock()

    @classmethod
    def subscribe_session(cls, session_id: str) -> asyncio.Queue:
        """订阅 SSE 流"""
        queue = asyncio.Queue(maxsize=200)
        with cls._subscribers_lock:
            cls._session_subscribers.setdefault(session_id, set()).add(queue)
        return queue

    @classmethod
    def publish_event(cls, session_id: str, event: Dict) -> int:
        """发布事件到所有订阅者"""
        count = 0
        with cls._subscribers_lock:
            for queue in cls._session_subscribers.get(session_id, []):
                try:
                    queue.put_nowait(event)
                    count += 1
                except asyncio.QueueFull:
                    pass
        return count

    @classmethod
    def is_execution_active(cls, session_id: str) -> bool:
        """检查执行状态"""
        with cls._active_executions_lock:
            return cls._active_executions.get(session_id, False)
```

### 3. CheckpointService

**文件：** `backend/services/checkpoint_service.py`

```python
class CheckpointService:
    """检查点操作服务"""

    @staticmethod
    async def get_checkpoints(session_id: str) -> List[Dict]:
        """获取检查点列表"""
        checkpointer = await get_global_checkpointer()
        config = {"configurable": {"thread_id": session_id}}
        state = await graph.aget_state(config)
        # ...

    @staticmethod
    async def rollback_checkpoint(session_id: str, checkpoint_id: str) -> Dict:
        """回滚到指定检查点"""
        # 更新 Checkpoint 状态
        await graph.aupdate_state(config, rollback_state)
```

### 4. ReviewService

**文件：** `backend/services/review_service.py`

```python
class ReviewService:
    """审查操作服务"""

    @staticmethod
    async def approve(session_id: str) -> Dict:
        """批准审查"""
        # 清除暂停标志
        await graph.aupdate_state(config, {
            "pause_after_step": False,
            "previous_layer": 0,
        })

    @staticmethod
    async def reject(session_id: str, feedback: str, dimensions: List[str]) -> Dict:
        """驳回审查"""
        await graph.aupdate_state(config, {
            "need_revision": True,
            "revision_target_dimensions": dimensions,
            "review_feedback": feedback,
        })
```

---

## 数据库层

### 文件：`backend/database/engine.py`

```python
ASYNC_DATABASE_URL = "sqlite+aiosqlite:///data/village_planning.db"

# 优化配置
PRAGMA journal_mode=WAL
PRAGMA synchronous=NORMAL
PRAGMA cache_size=-64000  # 64MB
```

### 文件：`backend/database/operations_async.py`

**主要操作：**

```python
async def create_planning_session_async(state: Dict) -> str
async def get_planning_session_async(session_id: str) -> Optional[Dict]
async def update_planning_session_async(session_id: str, updates: Dict) -> bool
async def delete_planning_session_async(session_id: str) -> bool
async def upsert_ui_message_async(session_id: str, message_id: str, ...) -> int
```

---

## 数据模型层

### 文件：`backend/database/models.py`

#### PlanningSession 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | str (PK) | 会话 ID |
| `project_name` | str | 项目名称 |
| `status` | str | running/paused/completed/failed |
| `is_executing` | bool | 执行状态 |
| `stream_state` | str | active/paused/completed |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

#### UIMessage 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int (PK) | 自增 ID |
| `session_id` | str (FK) | 会话 ID |
| `message_id` | str | 前端唯一 ID |
| `role` | str | user/assistant/system |
| `content` | str | 消息内容 |
| `message_type` | str | 消息类型 |
| `message_metadata` | JSON | 元数据 |

---

## 技术栈总结

| 类别 | 技术 | 说明 |
|------|------|------|
| **Web 框架** | FastAPI | 异步 Python Web 框架 |
| **数据验证** | Pydantic V2 | 数据模型和验证 |
| **数据库** | SQLite | 嵌入式数据库 |
| **异步驱动** | aiosqlite | SQLite 异步驱动 |
| **ORM** | SQLModel | SQLAlchemy + Pydantic |
| **状态管理** | LangGraph AsyncSqliteSaver | 检查点存储 |
| **流式输出** | SSE | Server-Sent Events |
| **LLM 框架** | LangChain | AI 应用框架 |

---

## 关键设计模式

### 1. 服务层模式

```python
# API 层只做路由和验证
@router.post("/start")
async def start_planning(request: StartPlanningRequest):
    return await planning_service.start_planning(...)

# 服务层处理业务逻辑
class PlanningService:
    @staticmethod
    async def start_planning(...) -> Dict:
        # 构建状态
        # 创建会话
        # 启动后台任务
        ...
```

### 2. 集中式状态管理

```python
# SSEManager 管理所有运行时状态
class SSEManager:
    _sessions: Dict = {}
    _session_subscribers: Dict = {}
    _active_executions: Dict = {}
    _stream_states: Dict = {}
```

### 3. 单例模式

```python
# 全局 Checkpointer
async def get_global_checkpointer():
    global _checkpointer
    if _checkpointer is None:
        async with _checkpointer_lock:
            if _checkpointer is None:
                _checkpointer = AsyncSqliteSaver(conn)
    return _checkpointer
```

### 4. 订阅者模式

```python
# SSE 消息分发
_session_subscribers: Dict[str, Set[asyncio.Queue]] = {}

for queue in _session_subscribers[session_id]:
    queue.put_nowait(event)
```

---

## 关键文件索引

| 文件路径 | 功能 |
|---------|------|
| `backend/main.py` | 应用入口 |
| `backend/api/planning.py` | 规划 API 路由 |
| `backend/api/data.py` | 数据 API 路由 |
| `backend/services/planning_service.py` | 规划执行服务 |
| `backend/services/sse_manager.py` | SSE 连接管理 |
| `backend/services/checkpoint_service.py` | 检查点服务 |
| `backend/services/review_service.py` | 审查服务 |
| `backend/database/engine.py` | 数据库引擎 |
| `backend/database/models.py` | SQLModel 模型 |
| `backend/database/operations_async.py` | 异步 CRUD |

---

*本文档最后更新：2026-04-05（服务层重构完成）*