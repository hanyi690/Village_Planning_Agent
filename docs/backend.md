# 后端实现文档

> FastAPI 后端架构 - REST 状态同步 + SSE 流式输出

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FastAPI Application (main.py)                     │
│                    Lifespan Manager → init_db() → init_async_db()   │
└─────────────────────────────────────────────────────────────────────┘
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ planning_router │     │  data_router    │     │knowledge_router │
│ api/planning.py │     │   api/data.py   │     │ api/knowledge.py│
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Storage Layer (SQLite + LangGraph)                │
│  AsyncSqliteSaver (Checkpointer单例) → 状态唯一真实源               │
│  PlanningSession / UISession / UIMessage                            │
└─────────────────────────────────────────────────────────────────────┘
```

## API 路由

### Planning API (`/api/planning/*`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/start` | POST | 启动新规划会话 |
| `/stream/{session_id}` | GET | SSE 流式输出 |
| `/status/{session_id}` | GET | 获取会话状态 (REST轮询) |
| `/review/{session_id}` | POST | 审查操作 (approve/reject/rollback) |
| `/resume` | POST | 从检查点恢复 |
| `/checkpoints/{project_name}` | GET | 列出项目检查点 (支持 session_id 参数精确查询) |
| `/messages/{session_id}` | POST | 创建 UI 消息 (存储到数据库) |
| `/messages/{session_id}` | GET | 获取 UI 消息列表 (支持 role 过滤) |
| `/sessions/{session_id}` | DELETE | 删除会话（完整删除：数据库+UI消息+Checkpoint） |
| `/rate-limit/reset/{project}` | POST | 重置限流 |

### Data API (`/api/data/*`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/villages` | GET | 列出所有村庄项目 |
| `/villages/{name}/sessions` | GET | 获取村庄会话列表 |
| `/villages/{name}/layers/{layer}` | GET | 获取层级内容 |
| `/villages/{name}/checkpoints` | GET | 获取检查点列表 |
| `/villages/{name}/compare/{cp1}/{cp2}` | GET | 比较检查点 |
| `/villages/{name}/plan` | GET | 获取综合规划报告 |

### Files API (`/api/files/*`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/upload` | POST | 上传并解析文件 |

**支持格式**: Word (.docx, .doc), PDF, Excel, PowerPoint, 纯文本

### Knowledge API (`/api/knowledge/*`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/stats` | GET | 知识库统计 |
| `/documents` | GET/POST | 文档列表/上传 |
| `/documents/{filename}` | DELETE | 删除文档 |
| `/sync` | POST | 同步源目录 |

## 核心调用流程

### POST /api/planning/start

```
请求入口
    │
    ├─→ 1. 限流检查 (rate_limiter.check_rate_limit)
    │       - 5秒窗口内最多3次请求
    │       - 任务完成后10秒冷却期
    │
    ├─→ 2. 生成 session_id (YYYYMMDD_HHMMSS格式)
    │
    ├─→ 3. 状态构建 (_build_initial_state)
    │       - 创建 OutputManager
    │       - 构建 LangGraph 状态字典
    │
    ├─→ 4. 数据库创建 (create_session_async)
    │       - 异步写入 PlanningSession 表
    │
    ├─→ 5. 内存初始化 (_sessions[session_id])
    │       - events: deque(maxlen=1000)
    │       - sent_layer_events: set()
    │
    ├─→ 6. 获取 Checkpointer (get_global_checkpointer)
    │       - 单例模式 AsyncSqliteSaver
    │       - WAL 模式 + 64MB 缓存
    │
    ├─→ 7. 创建图实例 (create_village_planning_graph)
    │
    └─→ 8. 后台执行 + 立即返回响应
            background_tasks.add_task(_execute_graph_in_background)
            return {"task_id": session_id, "status": "running"}
```

### 后台图执行流程

```python
async def _execute_graph_in_background(session_id, graph, initial_state, checkpointer):
    config = {"configurable": {"thread_id": session_id}}
    
    # Token 回调工厂（用于实时发送维度内容）
    def token_callback_factory(layer: int, dimension: str):
        def on_token(token: str, accumulated: str):
            _append_session_event(session_id, {
                "type": "dimension_delta",
                "layer": layer,
                "dimension_key": dimension,
                "delta": token,
                "accumulated": accumulated,
            })
        return on_token
    
    # 流式执行图
    async for event in graph.astream(clean_state, config, stream_mode="values"):
        # 1. 检测层级开始 → 发送 layer_started
        # 2. 检测层级完成 → 发送 layer_completed
        # 3. 检测修复完成 → 发送 dimension_revised
        # 4. 检测暂停 → 更新状态为 paused，返回
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

SSE 流式输出事件：

| 事件 | 数据 | 说明 |
|------|------|------|
| connected | `{session_id}` | 连接建立 |
| layer_started | `{layer, layer_name}` | 层级开始 |
| content_delta | `{delta}` | 文本增量 |
| dimension_delta | `{layer, dimension, delta, accumulated}` | 维度Token增量 |
| dimension_complete | `{layer, dimension, content}` | 维度完成 |
| dimension_revised | `{layer, dimension, old_content, new_content}` | 维度修复 |
| layer_completed | `{layer, report_content, dimension_reports}` | 层级完成 |
| pause | `{layer}` | 步进暂停 |
| completed | `{message}` | 规划完成 |
| error | `{message}` | 错误信息 |

### POST /api/planning/review/{session_id}

```python
class ReviewActionRequest(BaseModel):
    action: str                # approve | reject | rollback
    feedback: Optional[str]    # 反馈内容（驳回时必填）
    dimensions: Optional[List[str]]  # 审查维度（驳回时）
    checkpoint_id: Optional[str]  # 检查点ID（回退时必填）
```

**级联更新机制**：

当用户选择修复某个维度时，系统会自动识别并更新所有依赖它的下游维度：

| 维度类型 | Feedback 策略 | 说明 |
|----------|--------------|------|
| 目标维度 | 用户 feedback | 使用用户提供的修改意见 |
| 下游维度 | 级联更新 prompt | 基于上游更新内容自动调整 |

**执行流程**：
```
用户选择修复: ["land_use"]
    │
    ├─→ Wave 0: land_use (目标维度)
    │       → 使用用户 feedback
    │
    ├─→ Wave 1: [spatial_structure, land_use_planning]
    │       → 使用级联更新 prompt
    │
    └─→ Wave 2: [project_bank]
            → 使用级联更新 prompt
```

**级联更新 Prompt 结构** (`src/subgraphs/revision_subgraph.py`):
```
【级联更新任务】
上游相关维度已完成修订，请根据上游更新内容调整本维度。

【上游已更新的内容】
{filtered_detail}

【原始修改背景（供参考）】
{user_feedback}

【要求】
1. 仔细阅读上游已更新的内容
2. 识别本维度中受上游更新影响的部分
3. 调整本维度内容，确保与上游维度保持一致
4. 只修改确实受影响的部分
5. 在修改处标注【级联更新】
```

### DELETE /api/planning/sessions/{session_id}

完整删除会话，包括：

**删除范围**：
1. **内存状态**：`_sessions`、`_active_executions`、`_stream_states`
2. **数据库记录**：`planning_sessions` 表中的会话记录
3. **UI 消息**：`ui_messages` 表中的所有相关消息
4. **LangGraph Checkpoint**：AsyncSqliteSaver 中的检查点数据

**响应**：
```json
{
  "message": "Session {session_id} deleted completely",
  "deleted": {
    "memory": true,
    "database": true,
    "ui_messages": 15,
    "checkpoints": 3
  }
}
```

**错误处理**：
- 404: 会话不存在
- 500: 删除失败

## 数据库模型

### PlanningSession

```python
class PlanningSession(SQLModel, table=True):
    __tablename__ = "planning_sessions"
    
    session_id: str          # 主键 (YYYYMMDD_HHMMSS)
    project_name: str        # 项目名称 (索引)
    status: str              # running/paused/completed/failed (索引)
    execution_error: str     # 执行错误信息
    
    village_data: str        # 村庄现状数据
    task_description: str    # 规划任务描述
    constraints: str         # 约束条件
    
    output_path: str         # 输出路径
    created_at: datetime
    updated_at: datetime
    completed_at: datetime
```

### UISession / UIMessage

```python
class UISession(SQLModel, table=True):
    __tablename__ = "ui_sessions"
    
    conversation_id: str     # 主键
    status: str              # idle/running
    project_name: str
    task_id: str             # 关联规划会话ID
    messages: List[UIMessage]  # 一对多

class UIMessage(SQLModel, table=True):
    __tablename__ = "ui_messages"
    
    id: int                  # 自增主键
    session_id: str          # 外键
    role: str                # user/assistant/system
    content: str             # 消息内容
    message_type: str        # text/file/progress/action/result/error/system
    message_metadata: dict   # 元数据 (JSON)
```

## Checkpointer 单例

**文件**: `backend/database/engine.py`

```python
_checkpointer: Optional[AsyncSqliteSaver] = None
_checkpointer_lock = asyncio.Lock()

async def get_global_checkpointer() -> AsyncSqliteSaver:
    """获取全局 Checkpointer 单例"""
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

**配置**:
- WAL 模式启用
- 连接池: 5 + 10 overflow
- 64MB 缓存

## LLM 配置

### 支持的提供商

| 提供商 | 模型前缀 | API Base |
|--------|----------|----------|
| DeepSeek (默认) | `deepseek-*` | `https://api.deepseek.com/v1` |
| OpenAI | `gpt-*` | 默认官方 API |
| ZhipuAI | `glm-*` | 官方 SDK |

### 配置方式

```env
# DeepSeek 配置 (默认)
OPENAI_API_KEY=your_deepseek_api_key
OPENAI_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
MAX_TOKENS=65536

# 智谱 GLM 配置
ZHIPUAI_API_KEY=your_key
LLM_MODEL=glm-4-flash
```

## 目录结构

```
backend/
├── main.py                 # 应用入口
├── schemas.py              # Pydantic 请求/响应模型
├── api/
│   ├── planning.py         # 规划 API 核心
│   ├── data.py             # 数据访问 API
│   ├── files.py            # 文件上传 API
│   ├── knowledge.py        # 知识库 API
│   └── validate_config.py  # 配置验证
├── database/
│   ├── engine.py           # Checkpointer 单例
│   ├── models.py           # SQLModel 数据模型
│   └── operations_async.py # 异步 CRUD 操作
├── services/
│   └── rate_limiter.py     # 请求限流 (3次/5秒)
└── utils/
    ├── error_handler.py    # 统一错误处理
    ├── logging.py          # 执行时间日志
    ├── progress_helper.py  # 进度计算
    └── session_helper.py   # 会话辅助函数
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `main.py` | FastAPI 应用入口 |
| `api/planning.py` | 规划 API 核心，SSE 事件 |
| `database/engine.py` | Checkpointer 单例 |
| `database/models.py` | SQLModel 数据模型 |
| `services/rate_limiter.py` | 请求限流 |