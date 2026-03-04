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
│ planning_router │     │  data_router    │     │knowledge_router │
│ api/planning.py │     │   api/data.py   │     │ api/knowledge.py│
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│                   Storage Layer                              │
│  SQLite (village_planning.db):                              │
│    ├── planning_sessions  业务元数据                        │
│    └── checkpoints        LangGraph状态 (单一真实源)        │
└─────────────────────────────────────────────────────────────┘
```

## API 路由

### Planning API (`/api/planning/*`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/planning/start` | POST | 启动新规划会话 |
| `/api/planning/stream/{session_id}` | GET | SSE 流式输出 |
| `/api/planning/status/{session_id}` | GET | 获取会话状态 |
| `/api/planning/review/{session_id}` | POST | 审查操作 |
| `/api/planning/sessions/{session_id}` | DELETE | 删除会话 |
| `/api/planning/rate-limit/reset/{project_name}` | POST | 重置限流 |

### Data API (`/api/data/*`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/data/villages` | GET | 列出所有村庄 |
| `/api/data/villages/{name}/sessions` | GET | 获取村庄会话 |
| `/api/data/villages/{name}/layers/{layer}` | GET | 获取层级内容 |
| `/api/data/villages/{name}/checkpoints` | GET | 获取检查点列表 |
| `/api/data/villages/{name}/compare/{cp1}/{cp2}` | GET | 比较检查点 |
| `/api/data/villages/{name}/plan` | GET | 获取综合规划 |

### Files API (`/api/files/*`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/files/upload` | POST | 上传并解析文件 |

**支持格式**: Word (.docx, .doc), PDF, Excel (.xlsx, .xls), PowerPoint (.pptx, .ppt), 纯文本 (.txt, .md)

**实现**: MarkItDown 转换 + win32com 处理 .doc 格式

### Knowledge API (`/api/knowledge/*`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/knowledge/stats` | GET | 知识库统计 |
| `/api/knowledge/documents` | GET | 文档列表 |
| `/api/knowledge/documents` | POST | 上传文档 |
| `/api/knowledge/documents/{doc_id}` | DELETE | 删除文档 |
| `/api/knowledge/sync` | POST | 同步文档 |

## 核心端点实现

### POST /api/planning/start

**文件**: `backend/api/planning.py`

```python
@router.post("/start")
async def start_planning(request: StartPlanningRequest):
    # 1. 限流检查
    allowed, msg = rate_limiter.check_rate_limit(request.project_name)
    
    # 2. 生成 session_id (YYYYMMDD_HHMMSS)
    session_id = _generate_session_id()
    
    # 3. 创建数据库记录
    await create_session_async(session_state)
    
    # 4. 获取全局 checkpointer 单例
    checkpointer = await get_global_checkpointer()
    
    # 5. 创建图实例
    graph = create_village_planning_graph(checkpointer=checkpointer)
    
    # 6. 构建初始状态
    initial_state = _build_initial_state(request, session_id)
    
    # 7. 后台执行
    asyncio.create_task(_execute_graph_in_background(
        session_id, graph, initial_state, checkpointer
    ))
    
    return {"task_id": session_id, "status": "running"}
```

### GET /api/planning/status/{session_id}

**核心端点** - 前端每2秒轮询，用于状态同步

**响应字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | running/paused/reviewing/completed/failed |
| previous_layer | number | 刚完成的层级 (待审查) |
| layer_X_completed | boolean | 层级完成状态 |
| execution_complete | boolean | 执行是否完成 |
| current_layer | number | 当前执行层级 |
| pause_after_step | boolean | 是否暂停等待审查 |
| messages | array | 消息历史 |
| revision_history | array | 修订历史 |

### GET /api/planning/stream/{session_id}

SSE 流式输出

**事件类型**:

| 事件 | 数据 | 说明 |
|------|------|------|
| connected | `{session_id}` | 连接建立 |
| layer_started | `{layer, layer_name}` | 层级开始（非暂停时发送） |
| content_delta | `{delta}` | 文本增量 |
| dimension_delta | `{layer, dimension, delta, accumulated}` | 维度内容增量（Token级） |
| dimension_complete | `{layer, dimension, content}` | 维度完成 |
| dimension_revised | `{layer, dimension, old_content, new_content}` | 维度修复完成 |
| layer_completed | `{layer, report_content, dimension_reports}` | 层级完成 |
| pause | `{layer}` | 步进暂停 |
| stream_paused | `{}` | 流暂停 |
| resumed | `{layer}` | 恢复执行 |
| completed | `{message}` | 规划完成 |
| error | `{message}` | 错误信息 |

### POST /api/planning/review/{session_id}

审查操作

```python
class ReviewActionRequest(BaseModel):
    action: str                # approve | reject | rollback
    feedback: Optional[str]    # 反馈内容（驳回时必填）
    dimensions: Optional[List[str]]  # 审查维度（驳回时）
    checkpoint_id: Optional[str]  # 检查点ID（回退时必填）
```

## 后台执行流程

### _execute_graph_in_background

```python
async def _execute_graph_in_background(
    session_id: str,
    graph,
    initial_state: Dict[str, Any],
    checkpointer
):
    config = {"configurable": {"thread_id": session_id}}
    
    # 创建 Token 回调工厂（用于实时发送维度内容）
    def token_callback_factory(layer: int, dimension: str):
        def on_token(token: str, accumulated: str):
            event_data = {
                "type": "dimension_delta",
                "layer": layer,
                "dimension_key": dimension,
                "delta": token,
                "accumulated": accumulated,
            }
            _append_session_event(session_id, event_data)
        return on_token
    
    # 流式执行图
    async for event in graph.astream(clean_state, config, stream_mode="values"):
        # 1. 检测层级开始
        current_layer = event.get("current_layer")
        if current_layer and not event.get("pause_after_step"):
            # 发送 layer_started 事件
            await _append_session_event_async(session_id, {
                "type": "layer_started",
                "layer": current_layer,
                ...
            })
        
        # 2. 检测层级完成
        for layer_num in [1, 2, 3]:
            if event.get(f"layer_{layer_num}_completed"):
                # 生成报告内容
                # 发送 layer_completed 事件
                await _append_session_event_async(session_id, {
                    "type": "layer_completed",
                    "layer": layer_num,
                    "report_content": report,
                    "dimension_reports": dimension_reports,
                    ...
                })
        
        # 3. 检测修复完成
        if event.get("last_revised_dimensions"):
            # 发送 dimension_revised 事件
            for dim in last_revised_dimensions:
                await _append_session_event_async(session_id, {
                    "type": "dimension_revised",
                    "dimension": dim,
                    ...
                })
        
        # 4. 检测暂停
        if event.get("pause_after_step"):
            await update_session_async(session_id, {"status": "paused"})
            return
```

## 状态管理

### AsyncSqliteSaver 单例

**文件**: `backend/database/engine.py`

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
        
        conn = await aiosqlite.connect(get_db_path())
        _checkpointer = AsyncSqliteSaver(conn)
        await _checkpointer.setup()
        return _checkpointer
```

### 单一状态源原则

- **LangGraph Checkpointer** 是状态的唯一权威来源
- REST API 从 Checkpointer 读取状态返回给前端
- 前端不存储独立业务状态，完全由后端同步派生

## 数据库模型

**文件**: `backend/database/models.py`

```python
class PlanningSession(SQLModel, table=True):
    session_id: str           # 主键
    project_name: str         # 项目名称
    status: str               # running/paused/completed/failed
    execution_error: Optional[str]
    village_data: Optional[str]
    task_description: str
    constraints: str
    output_path: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]

class SessionEvent(SQLModel, table=True):
    """会话事件表（用于SSE）"""
    id: Optional[int]         # 主键
    session_id: str           # 外键
    event_type: str           # 事件类型
    event_data: str           # JSON数据
    created_at: datetime
```

**注意**: Checkpoint 表由 LangGraph 的 `AsyncSqliteSaver` 管理，不在此模型中定义。

## LLM 配置

### 支持的 LLM 提供商

| 提供商 | 模型前缀 | API Base | 说明 |
|--------|----------|----------|------|
| **DeepSeek** (默认) | `deepseek-*` | `https://api.deepseek.com/v1` | OpenAI 兼容接口，高性价比 |
| OpenAI | `gpt-*` | 默认官方 API | 原生 OpenAI |
| ZhipuAI | `glm-*` | 官方 SDK | 智谱 GLM 系列 |

### 配置方式

**环境变量** (`.env`):

```bash
# DeepSeek 配置 (默认)
OPENAI_API_KEY=your_deepseek_api_key
OPENAI_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
MAX_TOKENS=65536

# 智谱 GLM 配置
ZHIPUAI_API_KEY=your_key
LLM_MODEL=glm-4-flash
```

### LLM Factory

**文件**: `src/core/llm_factory.py`

```python
def detect_provider(model_name: str) -> LLMProvider:
    if model_name.startswith("glm-"):
        return LLMProvider.ZHIPUAI
    elif model_name.startswith("gpt-") or model_name.startswith("deepseek-"):
        return LLMProvider.OPENAI
    return LLMProvider.OPENAI  # 默认

def create_llm(model: str, temperature: float = 0.7, **kwargs):
    provider = detect_provider(model)
    if provider == LLMProvider.ZHIPUAI:
        return ChatZhipuAI(model=model, **kwargs)
    else:
        return ChatOpenAI(model=model, **kwargs)
```

## Token 级流式输出

### 频率控制

```python
# 频率控制参数
DELTA_MIN_INTERVAL_MS = 50  # 最小发送间隔（毫秒）
DELTA_MIN_TOKENS = 5        # 最小 token 数量

def append_dimension_delta_event(
    session_id: str,
    layer: int,
    dimension_key: str,
    dimension_name: str,
    delta: str,
    accumulated: str
) -> bool:
    """发送维度增量事件（带频率控制）"""
    current_time = time.time() * 1000
    
    # 检查是否应该发送
    time_elapsed = current_time - last_sent
    should_send = (time_elapsed >= DELTA_MIN_INTERVAL_MS) or 
                  (token_count >= DELTA_MIN_TOKENS)
    
    if not should_send:
        return False
    
    # 发送事件
    _append_session_event(session_id, {
        "type": "dimension_delta",
        "layer": layer,
        "dimension_key": dimension_key,
        "delta": delta,
        "accumulated": accumulated,
    })
    
    return True
```

## 目录结构

```
backend/
├── main.py                 # 应用入口
├── schemas.py              # Pydantic 请求/响应模型
├── requirements.txt        # Python依赖
├── Dockerfile              # Docker配置
├── api/
│   ├── planning.py         # 规划 API 核心
│   ├── data.py             # 数据访问 API
│   ├── files.py            # 文件上传 API
│   ├── knowledge.py        # 知识库 API
│   ├── tool_manager.py     # 工具管理单例
│   └── validate_config.py  # 配置验证
├── database/
│   ├── __init__.py
│   ├── engine.py           # Checkpointer 单例
│   ├── models.py           # SQLModel 数据模型
│   └── operations_async.py # 异步 CRUD 操作
├── services/
│   └── rate_limiter.py     # 请求限流 (3次/5秒)
├── scripts/
│   ├── migrate_checkpoints.py
│   ├── migrate_to_langgraph_schema.py
│   ├── validate_database.py
│   └── verify_migration.py
└── utils/
    ├── __init__.py
    ├── error_handler.py    # 统一错误处理
    ├── logging.py          # 执行时间日志装饰器
    ├── progress_helper.py  # 进度计算工具
    └── session_helper.py   # 会话辅助函数
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `backend/main.py` | FastAPI 应用入口，HF镜像设置 |
| `backend/schemas.py` | Pydantic 请求/响应模型 |
| `backend/api/planning.py` | 规划 API 核心，SSE事件 |
| `backend/api/data.py` | 数据访问 API |
| `backend/api/files.py` | 文件上传 API |
| `backend/api/knowledge.py` | 知识库 API |
| `backend/database/models.py` | SQLModel 数据模型 |
| `backend/database/engine.py` | Checkpointer 单例 |
| `backend/database/operations_async.py` | 异步 CRUD 操作 |
| `backend/services/rate_limiter.py` | 请求限流 |
| `backend/utils/error_handler.py` | 统一错误处理 |
| `backend/utils/logging.py` | 执行时间日志装饰器 |
| `backend/utils/progress_helper.py` | 进度计算工具 |
