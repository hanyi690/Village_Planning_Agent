# FastAPI 后端架构分析报告

> **相关文档**: [系统架构总览](architecture.md) | [数据流转](data-flow-architecture.md)
>
> 生成时间：2026-03-15
> 项目版本：1.0.0
> 分析范围：backend/ 目录

---

## 目录

1. [架构概览](#架构概览)
2. [应用入口与生命周期](#应用入口与生命周期)
3. [API 路由模块](#api 路由模块)
4. [数据库层](#数据库层)
5. [数据模型层](#数据模型层)
6. [服务层](#服务层)
7. [工具层](#工具层)
8. [技术栈总结](#技术栈总结)
9. [代码规范与最佳实践](#代码规范与最佳实践)
10. [关键设计模式](#关键设计模式)

---

## 架构概览

### 项目结构

```
backend/
├── main.py                          # 应用入口
├── schemas.py                       # Pydantic 数据模型
├── api/
│   ├── planning.py                  # 核心规划接口 (~3000 行)
│   ├── data.py                      # 数据访问接口
│   ├── files.py                     # 文件上传接口
│   ├── knowledge.py                 # 知识库管理接口
│   ├── tool_manager.py              # 工具管理器
│   └── validate_config.py           # 配置验证
├── database/
│   ├── engine.py                    # 数据库引擎配置
│   ├── models.py                    # SQLModel 数据模型
│   └── operations_async.py          # 异步 CRUD 操作
├── services/
│   └── rate_limiter.py              # 速率限制服务
└── utils/
    ├── logging.py                   # 日志工具
    ├── error_handler.py             # 错误处理
    ├── session_helper.py            # 会话辅助
    └── progress_helper.py           # 进度计算
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
    description="基于 LangGraph 的村庄规划智能系统后端服务",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)
```

#### 环境变量配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HF_ENDPOINT` | `https://hf-mirror.com` | HuggingFace 镜像 |
| `IS_PRODUCTION` | `False` | 生产环境标志 |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:8000` | CORS 白名单 |

#### 生命周期管理 (lifespan)

**启动时执行：**
1. 确保工作目录存在
2. 设置 HuggingFace 环境（镜像 + 离线模式）
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

#### 健康检查端点

```python
@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": "village-planning-backend",
        "version": "1.0.0"
    }
```

---

## API 路由模块

### 1. planning.py - 核心规划接口

**文件路径：** `backend/api/planning.py`
**代码行数：** ~3000 行

#### 主要端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/planning/start` | POST | 创建并启动规划会话 |
| `/api/planning/stream/{session_id}` | GET | SSE 流式输出 |
| `/api/planning/status/{session_id}` | GET | 查询会话状态 |
| `/api/planning/review/{session_id}` | POST | 审查操作（批准/驳回/回滚） |
| `/api/planning/messages/{session_id}` | GET/POST | UI 消息管理 |
| `/api/planning/sessions/{session_id}` | DELETE | 删除会话 |
| `/api/planning/resume` | POST | 恢复会话 |
| `/api/planning/checkpoints/{project_name}` | GET | 获取检查点历史 |

#### 核心特性

**1. 全局 Checkpointer 单例**

使用双重检查锁定模式确保单例：

```python
async def get_global_checkpointer() -> Any:
    global _checkpointer, _checkpointer_initialized

    # 快速路径：如果已初始化，直接返回
    if _checkpointer is not None and _checkpointer_initialized:
        return _checkpointer

    # 慢速路径：需要初始化（带锁）
    async with _checkpointer_lock:
        # 双重检查
        if _checkpointer is not None and _checkpointer_initialized:
            return _checkpointer

        # 创建连接并初始化
        conn = await aiosqlite.connect(get_db_path(), check_same_thread=False)
        await conn.execute("PRAGMA journal_mode=WAL")
        _checkpointer = AsyncSqliteSaver(conn)
        await _checkpointer.setup()
```

**2. SSE 跨线程发布**

```python
@router.on_event("startup")
async def _save_main_event_loop():
    """保存主事件循环引用，支持在 LLM 回调的同步线程中发布事件"""
    global _main_event_loop
    _main_event_loop = asyncio.get_running_loop()
```

**3. 订阅者管理系统**

```python
_session_subscribers: Dict[str, set] = {}  # session_id -> set of asyncio.Queue
```

每个 SSE 连接拥有独立的 `asyncio.Queue`，避免消息竞争。

**4. 会话清理后台任务**

```python
SESSION_TTL_HOURS = 24  # 会话过期时间
EVENT_CLEANUP_INTERVAL_SECONDS = 300  # 清理间隔：5 分钟
```

**5. 全局事件计数器**

```python
_event_counter = 0
_event_counter_lock = Lock()  # 解决 deque rotation 问题
```

**6. FastAPI 依赖注入模式**

```python
# 使用 Annotated + Depends 模式实现依赖注入
from typing_extensions import Annotated
from fastapi import Depends

# 依赖注入函数
def get_rate_limiter() -> RateLimiter:
    return rate_limiter

def get_tool_manager() -> ToolManager:
    return tool_manager

# 类型别名
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
ToolManagerDep = Annotated[ToolManager, Depends(get_tool_manager)]

# 端点使用
@router.post("/api/planning/start")
async def start_planning(
    request: StartPlanningRequest,
    background_tasks: BackgroundTasks,
    limiter: RateLimiterDep
):
    ...
```

#### 线程安全全局状态

| 变量 | 类型 | 用途 |
|------|------|------|
| `_sessions` | `Dict[str, Dict]` | 内存会话存储 |
| `_active_executions` | `Dict[str, bool]` | 跟踪活跃执行 |
| `_stream_states` | `Dict[str, str]` | SSE 流状态 |
| `_status_log_tracker` | `Dict[str, Dict]` | 状态查询日志优化 |

---

### 2. data.py - 数据访问接口

**文件路径：** `backend/api/data.py`

#### 主要端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/data/villages` | GET | 列出所有村庄（项目） |
| `/api/data/villages/{name}/sessions` | GET | 获取村庄会话列表 |
| `/api/data/villages/{name}/layers/{layer}` | GET | 获取层级内容 |
| `/api/data/villages/{name}/checkpoints` | GET | 获取检查点 |
| `/api/data/villages/{name}/compare/{cp1}/{cp2}` | GET | 比较检查点 |
| `/api/data/villages/{name}/plan` | GET | 获取组合规划报告 |

#### 设计特点

1. **使用 LangGraph AsyncSqliteSaver 获取检查点历史**
2. **`previous_layer` 判断检查点层级**（与 planning.py 一致）
3. **支持状态比较和差异分析**

#### Layer 映射配置

```python
LAYER_MAP = {
    "layer_1_analysis": "layer_1_analysis",
    "layer_2_concept": "layer_2_concept",
    "layer_3_detailed": "layer_3_detailed",
    "analysis": "layer_1_analysis",
    "concept": "layer_2_concept",
    "detailed": "layer_3_detailed",
}

LAYER_TO_STATE_KEY = {
    "layer_1_analysis": "analysis_reports",
    "layer_2_concept": "concept_reports",
    "layer_3_detailed": "detail_reports",
}
```

---

### 3. files.py - 文件上传接口

**文件路径：** `backend/api/files.py`

#### 支持的文档格式

**MarkItDown 处理：**
- Word: `.docx`, `.doc`（后者需先转换为.docx）
- PDF: `.pdf`
- Excel: `.xlsx`, `.xls`
- PowerPoint: `.pptx`, `.ppt`
- 其他：`.epub`, `.html`, `.csv`, `.json`, `.xml`, `.zip`

**纯文本处理：**
- 文本：`.txt`, `.md`, `.rst`
- 代码：`.py`, `.js`, `.ts`, `.java`, `.c`, `.cpp`, `.h`
- 样式：`.css`, `.scss`, `.less`
- 配置：`.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`

#### 编码检测策略

```
UTF-8 → chardet 检测 → GBK → GB2312 → UTF-8 with error replacement
```

#### 文件大小限制

- 最大：50MB
- 最小：10 字符（验证 decoded content）

---

### 4. knowledge.py - 知识库管理接口

**文件路径：** `backend/api/knowledge.py`

#### 主要端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/knowledge/documents` | GET | 列出可用文档 |
| `/api/knowledge/summary/{source}` | GET | 获取文档执行摘要 |
| `/api/knowledge/chapters/{source}` | GET | 列出文档章节 |
| `/api/knowledge/documents` | POST | 上传文档 |
| `/api/knowledge/documents/{filename}` | DELETE | 删除文档 |
| `/api/knowledge/sync` | POST | 同步源目录 |

#### 后台任务处理

```python
@router.post("/documents", response_model=AddDocumentResponse)
async def add_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category: Optional[str] = None
):
    # 保存文件后添加后台任务
    background_tasks.add_task(add_document_task, str(file_path), category)
```

---

## 数据库层

### 文件：`backend/database/engine.py`

#### 引擎配置

```python
ASYNC_DATABASE_URL = "sqlite+aiosqlite:///data/village_planning.db"

# 优化配置（通过 event listener）
PRAGMA journal_mode=WAL      # WAL 模式提高并发写入安全性
PRAGMA synchronous=NORMAL    # 平衡性能和安全性
PRAGMA cache_size=-64000     # 64MB 缓存
```

#### 引用计数管理

```python
async_engine = None
_async_engine_ref_count = 0

async def get_async_engine() -> create_async_engine:
    if async_engine is None:
        # 创建引擎
        async_engine = create_async_engine(ASYNC_DATABASE_URL, ...)
    _async_engine_ref_count += 1
    return async_engine

async def dispose_async_engine() -> None:
    _async_engine_ref_count -= 1
    if _async_engine_ref_count <= 0 and async_engine is not None:
        await async_engine.dispose()
```

#### 会话管理

```python
@asynccontextmanager
async def get_async_session() -> AsyncSession:
    """使用上下文管理器自动提交/回滚"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

---

## 数据模型层

### 文件：`backend/database/models.py`

#### PlanningSession 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | str (PK) | 会话 ID |
| `project_name` | str | 项目名称（索引） |
| `status` | str | running/paused/completed/failed |
| `is_executing` | bool | 执行状态标志（索引） |
| `stream_state` | str | active/paused/completed |
| `village_data` | str | 村庄数据 |
| `task_description` | str | 任务描述 |
| `constraints` | str | 约束条件 |
| `output_path` | str | 输出路径 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |
| `completed_at` | datetime | 完成时间 |

**复合索引：**
- `idx_status_created`: (status, created_at)
- `idx_project_status`: (project_name, status)

#### UISession / UIMessage 表

**UISession：**
- `conversation_id` (PK)
- `status`, `project_name`, `task_id`
- `messages` Relationship

**UIMessage：**
- `id` (PK, 自增)
- `session_id` (FK → UISession)
- `message_id` (前端唯一 ID)
- `role`, `content`, `message_type`
- `message_metadata` (JSON)
- `created_at`, `timestamp`

**唯一约束：** `(session_id, message_id)` - 支持 Upsert 操作

#### DimensionRevision 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int (PK) | 修订 ID |
| `session_id` | str (FK) | 会话 ID |
| `layer` | int | 层级 (1/2/3) |
| `dimension_key` | str | 维度标识 |
| `content` | str | 修订后内容 |
| `previous_content_hash` | str | 前版本哈希 |
| `reason` | str | 修改原因 |
| `created_by` | str | 修改者 |
| `version` | int | 版本号（自增） |
| `created_at` | datetime | 创建时间 |

**复合索引：**
- `idx_revision_session_dim`: (session_id, dimension_key)
- `idx_revision_session_version`: (session_id, layer, dimension_key, version)

---

### 文件：`backend/database/operations_async.py`

#### 异步 CRUD 操作模式

```python
async with get_async_session() as session:
    db_session = await session.execute(
        select(PlanningSession).where(PlanningSession.session_id == session_id)
    )
    db_session = db_session.scalar_one_or_none()
```

#### JSON 序列化辅助函数

```python
def make_json_serializable(obj: Any) -> Any:
    """递归转换不可 JSON 序列化类型"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, dict):
        return {k: make_json_serializable(v) for k, v in obj.items()}
    # ...
```

#### 新增执行状态和流状态操作

```python
# 替代内存中的 _active_executions
async def is_execution_active_async(session_id: str) -> bool
async def set_execution_active_async(session_id: str, active: bool) -> bool

# 替代内存中的 _stream_states
async def get_stream_state_async(session_id: str) -> str
async def set_stream_state_async(session_id: str, state: str) -> bool
```

#### Upsert 操作

```python
async def upsert_ui_message_async(
    session_id: str,
    message_id: str,
    role: str,
    content: str,
    message_type: str = "text",
    metadata: Optional[Dict[str, Any]] = None
) -> int:
    """使用 SQLite INSERT ... ON CONFLICT UPDATE 语法"""
```

---

## 数据模型层（Pydantic Schemas）

### 文件：`backend/schemas.py`

#### 请求模型

```python
class PlanningRequest(BaseModel):
    """规划任务请求"""
    project_name: str
    village_data: str
    task_description: str = DEFAULT_TASK_DESCRIPTION
    constraints: str = DEFAULT_CONSTRAINTS
    need_human_review: bool = DEFAULT_ENABLE_REVIEW
    stream_mode: bool = DEFAULT_STREAM_MODE
    step_mode: bool = DEFAULT_STEP_MODE

class ReviewRejectRequest(BaseModel):
    """审查驳回请求"""
    feedback: str = Field(..., min_length=1)
    target_dimensions: Optional[List[str]] = None

class RollbackRequest(BaseModel):
    """回退请求"""
    checkpoint_id: str
```

#### 响应模型

```python
class TaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    message: str

class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskStatus
    progress: Optional[float]
    current_layer: Optional[str]
    message: Optional[str]
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    created_at: datetime
    updated_at: datetime

class ReviewDataResponse(BaseModel):
    task_id: str
    current_layer: int
    content: str
    summary: Dict[str, Any]
    available_dimensions: List[str]
    checkpoints: List[Dict[str, Any]]

class ReviewActionResponse(BaseModel):
    success: bool
    message: str
    task_status: TaskStatus
    revision_progress: Optional[Dict[str, Any]]
```

#### 数据模型

```python
class ConversationMessage(BaseModel):
    role: str
    content: str
    message_type: str = "text"
    timestamp: datetime
    metadata: Optional[Dict[str, Any]]

class ConversationState(BaseModel):
    conversation_id: str
    status: str
    project_name: Optional[str]
    task_id: Optional[str]
    messages: List[ConversationMessage]
    created_at: datetime
    updated_at datetime

class FileUploadResponse(BaseModel):
    success: bool
    filename: str
    content: str
    size: int
    message: str

class VillageInfo(BaseModel):
    name: str
    session_count: int
    last_updated: Optional[datetime]

class VillageDetail(BaseModel):
    name: str
    sessions: List[Dict[str, Any]]
    analysis_reports: Optional[Dict[str, str]]
    concept_reports: Optional[Dict[str, str]]
    detail_reports: Optional[Dict[str, str]]
    final_report: Optional[str]
```

---

## 服务层

### 文件：`backend/services/rate_limiter.py`

#### 限流配置

| 参数 | 值 | 说明 |
|------|-----|------|
| `window_seconds` | 5 | 时间窗口（秒） |
| `max_requests` | 3 | 窗口内最大请求数 |
| `cooldown_seconds` | 10 | 任务完成后的冷却时间 |

#### 单例模式

```python
class RateLimiter:
    _instance: RateLimiter | None = None
    _lock = threading.Lock()

    def __new__(cls) -> RateLimiter:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
```

#### 限流检查逻辑

```python
def check_rate_limit(self, project_name: str, session_id: str) -> tuple[bool, str]:
    with self._lock:
        now = datetime.now()

        # 1. 检查是否正在执行
        if project_name in self._active_tasks:
            return False, "请求过于频繁，请稍后再试"

        # 2. 检查冷却期
        if project_name in self._completed_tasks:
            completed_at = self._completed_tasks[project_name]
            cooldown_end = completed_at + timedelta(seconds=self.cooldown_seconds)
            if now < cooldown_end:
                return False, "请求过于频繁，请稍后再试"

        # 3. 检查窗口内请求数
        if project_name in self._history:
            window_start = now - timedelta(seconds=self.window_seconds)
            recent_requests = [r for r in self._history[project_name] if r.timestamp >= window_start]
            if len(recent_requests) >= self.max_requests:
                return False, "请求过于频繁，请稍后再试"

        # 4. 记录请求
        self._record_request(project_name, session_id, now)
        return True, "请求通过限流检查"
```

#### 任务生命周期跟踪

```python
def mark_task_started(self, project_name: str) -> None
def mark_task_completed(self, project_name: str, success: bool = True) -> None
def get_retry_after(self, project_name: str) -> int | None
def reset_project(self, project_name: str) -> bool
```

---

## 工具层

### 文件：`backend/api/tool_manager.py`

#### 单例模式工具管理

```python
class ToolManager:
    _instance: Optional['ToolManager'] = None
    _file_manager = None

    def get_file_manager(self):
        """懒加载 FileManager"""
        from src.tools.file_manager import FileManager
        if self._file_manager is None:
            self._file_manager = FileManager()
        return self._file_manager

    def clear_all_tools(self):
        """清除所有缓存的工具（用于测试）"""
```

---

## 技术栈总结

| 类别 | 技术 | 说明 |
|------|------|------|
| **Web 框架** | FastAPI | 异步 Python Web 框架 |
| **数据验证** | Pydantic V2 | 数据模型和验证 |
| **数据库** | SQLite | 嵌入式数据库 |
| **异步驱动** | aiosqlite | SQLite 异步驱动 |
| **ORM** | SQLModel | SQLAlchemy + Pydantic 集成 |
| **状态管理** | LangGraph AsyncSqliteSaver | 检查点存储 |
| **流式输出** | SSE | Server-Sent Events |
| **文档处理** | MarkItDown | Microsoft 文档转 Markdown |
| **向量数据库** | ChromaDB | 嵌入存储 |
| **LLM 框架** | LangChain | AI 应用框架 |
| **编码检测** | chardet | 字符编码检测 |

---

## 代码规范与最佳实践

### MUST DO（必须遵守）

1. **类型注解**：所有函数参数和返回值必须使用类型注解
   ```python
   async def get_planning_session_async(session_id: str) -> Optional[Dict[str, Any]]:
   ```

2. **异步优先**：所有 I/O 操作使用 async/await
   ```python
   async with get_async_session() as session:
       db_session = await session.execute(select(...))
   ```

3. **依赖注入**：使用 `Annotated + Depends` 模式进行依赖注入（✅ 已实现）
   ```python
   # backend/api/planning.py

   # 依赖注入函数
   def get_rate_limiter() -> RateLimiter:
       """获取 RateLimiter 实例的依赖注入函数"""
       return rate_limiter

   def get_tool_manager() -> ToolManager:
       """获取 ToolManager 实例的依赖注入函数"""
       return tool_manager

   # 类型别名：用于端点参数的便捷类型注解
   RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
   ToolManagerDep = Annotated[ToolManager, Depends(get_tool_manager)]

   # 端点使用示例
   @router.post("/api/planning/start")
   async def start_planning(
       request: StartPlanningRequest,
       background_tasks: BackgroundTasks,
       limiter: RateLimiterDep  # 依赖注入
   ):
       # 使用 limiter 而非全局 rate_limiter
       is_allowed, message = limiter.check_rate_limit(...)
   ```

4. **日志记录**：使用 `logging` 模块，减少 print 语句
   ```python
   logger = logging.getLogger(__name__)
   logger.info(f"[Async DB] Created planning session: {session_id}")
   ```

5. **错误处理**：使用 HTTPException 抛出适当的状态码
   ```python
   if not db_session:
       raise HTTPException(status_code=404, detail="Session not found")
   ```

6. **文档字符串**：公共函数必须有 docstring
   ```python
   async def create_planning_session_async(state: Dict[str, Any]) -> str:
       """
       Create planning session (async)

       Args:
           state: Session state dictionary

       Returns:
           str: Session ID
       """
   ```

### 数据库操作规范

1. **使用上下文管理器管理会话**
   ```python
   async with get_async_session() as session:
       # 自动提交/回滚
   ```

2. **使用 `make_json_serializable` 处理复杂对象**
   ```python
   clean_state = make_json_serializable(state)
   ```

3. **复合索引优化查询性能**
   ```python
   __table_args__ = (
       Index("idx_status_created", "status", "created_at"),
       Index("idx_project_status", "project_name", "status"),
   )
   ```

4. **WAL 模式提高并发安全性**
   ```python
   await conn.execute("PRAGMA journal_mode=WAL")
   await conn.execute("PRAGMA synchronous=NORMAL")
   ```

### SSE 流式输出规范

1. **使用 StreamingResponse 和 text/event-stream**
   ```python
   StreamingResponse(event_generator(), media_type="text/event-stream")
   ```

2. **设置正确的响应头**
   ```python
   headers={
       "Cache-Control": "no-cache",
       "Connection": "keep-alive",
       "X-Accel-Buffering": "no",
   }
   ```

3. **跨线程事件发布需要保存主事件循环引用**
   ```python
   @router.on_event("startup")
   async def _save_main_event_loop():
       global _main_event_loop
       _main_event_loop = asyncio.get_running_loop()
   ```

4. **使用订阅者模式管理多个并发连接**
   ```python
   _session_subscribers: Dict[str, set] = {}  # session_id -> set of asyncio.Queue
   ```

### 状态管理规范

1. **业务元数据存储在 PlanningSession 表**
2. **执行状态数据由 LangGraph AsyncSqliteSaver 自动管理**
3. **使用内存缓存跟踪活跃执行和流状态**
4. **定期清理过期会话状态（TTL: 24 小时）**

---

## 关键设计模式

### 1. 单例模式 (Singleton)

**应用场景：**
- 全局 Checkpointer
- 工具管理器
- 限流器

```python
class SingletonPattern:
    _instance: Optional['SingletonPattern'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
```

### 2. 双重检查锁定 (Double-Checked Locking)

**应用场景：** 全局 Checkpointer 初始化

```python
async with _checkpointer_lock:
    if _checkpointer is not None and _checkpointer_initialized:
        return _checkpointer
    # 初始化逻辑
```

### 3. 上下文管理器 (Context Manager)

**应用场景：**
- 数据库会话管理
- 应用生命周期管理

```python
@asynccontextmanager
async def get_async_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### 4. 订阅者模式 (Observer Pattern)

**应用场景：** SSE 消息分发

```python
_session_subscribers: Dict[str, set] = {}  # session_id -> set of asyncio.Queue

async def publish_event(session_id: str, event: dict):
    if session_id in _session_subscribers:
        for queue in _session_subscribers[session_id]:
            await queue.put(event)
```

### 5. 工厂模式 (Factory Pattern)

**应用场景：** LangGraph 图创建

```python
from src.orchestration.main_graph import create_village_planning_graph
graph = create_village_planning_graph(checkpointer=saver)
```

### 6. 仓储模式 (Repository Pattern)

**应用场景：** 数据库 CRUD 操作

```python
# operations_async.py 作为仓储层
async def create_planning_session_async(state: Dict[str, Any]) -> str
async def get_planning_session_async(session_id: str) -> Optional[Dict[str, Any]]
async def update_planning_session_async(session_id: str, updates: Dict[str, Any]) -> bool
async def delete_planning_session_async(session_id: str) -> bool
```

---

## 验证方法

### 1. 启动服务器

```bash
# 方式 1：直接运行
python backend/main.py

# 方式 2：使用 uvicorn
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. 访问 API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 3. 健康检查

```bash
curl http://localhost:8000/health
```

### 4. 测试 API

```bash
# 列出村庄
curl http://localhost:8000/api/data/villages

# 获取检查点
curl http://localhost:8000/api/data/villages/{name}/checkpoints?session={session_id}
```

---

## 待续开发注意事项

1. **保持向后兼容**：修改 API 时注意版本管理，使用版本号前缀（如 `/api/v1/`）
2. **数据库迁移**：修改模型后需要更新数据库 schema，考虑使用 Alembic
3. **检查点兼容性**：LangGraph 状态变更需考虑历史数据兼容
4. **并发安全**：内存状态需使用锁保护（threading.Lock 或 asyncio.Lock）
5. **生产环境部署**：
   - 考虑使用 PostgreSQL 替代 SQLite
   - 使用 Redis 替代内存中的 session 存储
   - 配置适当的 Gunicorn worker 数量

---

## 附录：关键文件路径汇总

```
backend/
├── main.py                          # 应用入口
├── schemas.py                       # Pydantic 数据模型
├── api/
│   ├── planning.py                  # 核心规划接口
│   ├── data.py                      # 数据访问接口
│   ├── files.py                     # 文件上传接口
│   ├── knowledge.py                 # 知识库管理接口
│   ├── tool_manager.py              # 工具管理器
│   └── validate_config.py           # 配置验证
├── database/
│   ├── engine.py                    # 数据库引擎配置
│   ├── models.py                    # SQLModel 数据模型
│   └── operations_async.py          # 异步 CRUD 操作
├── services/
│   └── rate_limiter.py              # 速率限制服务
└── utils/
    ├── logging.py                   # 日志工具
    ├── error_handler.py             # 错误处理
    ├── session_helper.py            # 会话辅助
    └── progress_helper.py           # 进度计算
```

---

*本文档由架构分析工具生成，最后更新：2026-03-15（依赖注入模式已实现）*
