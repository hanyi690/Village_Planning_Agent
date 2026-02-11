# 后端实现文档

> **村庄规划智能体** - FastAPI 后端实现指南

## 目录

- [架构概述](#架构概述)
- [SSE/REST 解耦架构](#sserest-解耦架构)
- [数据流管理](#数据流管理)
- [API 端点](#api-端点)
- [数据库状态管理](#数据库状态管理)
- [部署指南](#部署指南)

---

## 架构概述

### 技术栈

- **框架**: FastAPI
- **Python 版本**: 3.9+
- **异步支持**: asyncio + uvicorn
- **数据验证**: Pydantic
- **流式传输**: Server-Sent Events (SSE)
- **数据库**: SQLite
- **默认端口**: 8000

### 应用结构

```
backend/
├── main.py                     # 应用入口
├── api/                        # API 路由模块
│   ├── planning.py            # 规划执行 API
│   ├── sessions.py            # 会话管理 API
│   └── files.py               # 文件上传 API
├── database/                   # 数据库模块
│   ├── models.py              # 数据模型
│   └── crud.py                # 数据库操作
├── services/                   # 业务逻辑层
│   └── planning_service.py    # 规划服务
├── schemas.py                  # Pydantic 数据模型
└── requirements.txt           # 依赖列表
```

---

## SSE/REST 解耦架构

### 架构概述 ⭐ 核心设计

**设计原则**: REST 提供可靠状态，SSE 仅负责流式文本效果

**重构前** (已废弃):
```
SSE 发送 7+ 种事件:
- progress, layer_completed, pause, stream_paused, completed, error, checkpoint_saved
- 前后端都需要复杂的去重逻辑
- 状态同步不可靠
```

**重构后** (当前):
```
SSE 仅发送 2 种事件:
- text_delta: 流式文本（打字机效果）
- error: 错误信息

REST API 提供可靠状态:
- GET /api/planning/status/{id}: 获取任务状态
- 数据库作为单一真实源
- 前端每 2 秒轮询状态变化
```

### 数据流架构

```
┌─────────────────────────────────────────────────────────────┐
│                      前端 (Next.js)                    │
│  ┌────────────────────────────────────────────────────┐   │
│  │         TaskController (状态管理层)             │   │
│  │  ┌──────────────────────────────────────────┐  │   │
│  │  │  REST 轮询 (每 2 秒)                    │  │   │
│  │  │  GET /api/planning/status/{id}          │  │   │
│  │  └──────────────────────────────────────────┘  │   │
│  │  ┌──────────────────────────────────────────┐  │   │
│  │  │  SSE (仅流式文本)                       │  │   │
│  │  │  GET /api/planning/stream/{id}          │  │   │
│  │  └──────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      后端 (FastAPI)                    │
│  ┌────────────────────────────────────────────────────┐   │
│  │              SQLite 数据库 (单一真实源)           │   │
│  │  - tasks 表存储所有状态                           │   │
│  │  - 状态更新立即写入数据库                        │   │
│  └────────────────────────────────────────────────────┘   │
│                          │                             │
│                          ▼                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │              核心智能体 (LangGraph)             │   │
│  │  - 三层规划主图                                   │   │
│  │  - 并行维度分析                                   │   │
│  │  - 检查点管理                                    │   │
│  └────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 状态更新流程

```
1. 层级完成时
   LangGraph → 数据库更新 (layer_X_completed = True)
                    ↓
   REST 轮询检测到状态变化
                    ↓
   前端触发 onLayerCompleted 回调

2. 暂停时
   LangGraph → 数据库更新 (pause_after_step = True)
                    ↓
   REST 轮询检测到状态变化
                    ↓
   前端触发 onPause 回调

3. 流式文本
   LangGraph → SSE 发送 text_delta 事件
                    ↓
   前端更新当前消息内容（打字机效果）
```

---

## 数据流管理

### REST API 状态端点

**文件**: `api/planning.py`

#### GET `/api/planning/status/{task_id}`

**功能**: 获取任务可靠状态 - 数据库作为单一真实源

**响应结构**:

```python
@router.get("/status/{task_id}")
async def get_task_status(task_id: str):
    """获取任务可靠状态"""
    # 从数据库获取状态
    task = await db.get_task(task_id)

    return {
        # 任务基础信息
        "task_id": task.id,
        "project_name": task.project_name,
        "status": task.status,
        "created_at": task.created_at,

        # 层级完成状态
        "layer_1_completed": task.layer_1_completed,
        "layer_2_completed": task.layer_2_completed,
        "layer_3_completed": task.layer_3_completed,

        # 暂停状态
        "pause_after_step": task.pause_after_step,
        "waiting_for_review": task.waiting_for_review,

        # 执行状态
        "execution_complete": task.status == "completed",
        "current_layer": task.current_layer,

        # 检查点信息
        "checkpoints": await db.get_checkpoints(task_id),
        "checkpoint_count": len(task.checkpoints),
    }
```

### SSE 流式端点

**文件**: `api/planning.py`

#### GET `/api/planning/stream/{task_id}`

**功能**: SSE 流式传输 - 仅发送流式文本和错误

**实现**:

```python
@router.get("/stream/{task_id}")
async def stream_planning_progress(task_id: str):
    """SSE 流式传输 - 仅发送流式文本和错误"""

    async def event_generator():
        try:
            # 仅发送流式文本事件
            async for text_delta in planning_stream:
                yield f"event: text_delta\ndata: {json.dumps({'text': text_delta})}\n\n"

            # 完成后无需发送 completed 事件，由 REST 状态提供
            _stream_states[task_id] = "completed"

        except Exception as e:
            # 错误事件
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

**移除的事件**:
- ❌ `progress` - 改由 REST `/status` 提供
- ❌ `layer_completed` - 改由 REST `/status` 提供
- ❌ `pause` - 改由 REST `/status` 提供
- ❌ `stream_paused` - 不再需要
- ❌ `completed` - 改由 REST `/status` 提供
- ❌ `checkpoint_saved` - 改由 REST `/status` 提供

---

## API 端点

### 1. 规划执行 API (`/api/planning`)

**模块位置**: `backend/api/planning.py`

#### POST `/api/planning/start`

**功能**: 启动新的规划任务

**请求体**:
```json
{
  "project_name": "示例村庄",
  "village_data": "村庄基础数据...",
  "task_description": "制定村庄总体规划方案",
  "constraints": "无特殊约束",
  "enable_review": true,
  "step_mode": true
}
```

**响应**:
```json
{
  "success": true,
  "session_id": "20240206_123456",
  "status": "running",
  "message": "规划任务已启动"
}
```

---

#### POST `/api/planning/review/{session_id}`

**功能**: 审查操作（批准/驳回/回退）

**请求体**:
```json
{
  "action": "approve",
  "feedback": "审查通过",
  "dimensions": ["industry", "traffic"],
  "checkpoint_id": "checkpoint_001_layer1_completed"
}
```

**操作类型**:
- `approve`: 批准，继续执行
- `reject`: 驳回，触发修复
- `rollback`: 回退到指定检查点

**响应**:
```json
{
  "success": true,
  "message": "审查已批准，继续执行"
}
```

---

#### GET `/api/planning/status/{session_id}`

**功能**: 获取会话状态

**响应**:
```json
{
  "session_id": "20240206_123456",
  "project_name": "示例村庄",
  "status": "paused",
  "current_layer": 2,
  "layer_1_completed": true,
  "layer_2_completed": false,
  "layer_3_completed": false,
  "pause_after_step": true,
  "waiting_for_review": false,
  "execution_complete": false,
  "created_at": "2024-02-06T12:34:56",
  "checkpoints": [...],
  "checkpoint_count": 2
}
```

---

### 2. 会话管理 API (`/api/sessions`)

**模块位置**: `backend/api/sessions.py`

#### GET `/api/sessions`

**功能**: 获取所有会话列表

**响应**:
```json
{
  "sessions": [
    {
      "session_id": "20240206_123456",
      "project_name": "示例村庄",
      "status": "completed",
      "created_at": "2024-02-06T12:34:56"
    }
  ],
  "count": 1
}
```

---

#### GET `/api/sessions/{session_id}`

**功能**: 获取会话详情

**响应**:
```json
{
  "session_id": "20240206_123456",
  "project_name": "示例村庄",
  "status": "paused",
  "current_layer": 2,
  "progress": 66.7,
  "created_at": "2024-02-06T12:34:56",
  "updated_at": "2024-02-06T13:45:67",
  "analysis_report": "...",
  "planning_concept": "...",
  "detailed_plan": "..."
}
```

---

### 3. 文件管理 API (`/api/files`)

**模块位置**: `backend/api/files.py`

#### POST `/api/files/upload`

**功能**: 上传并解析文件，支持多种格式

**支持的文件格式**:
- **.txt, .md**: 文本文件，自动编码检测（UTF-8/GBK/GB2312）
- **.docx**: Word 文档，提取所有段落文本
- **.pdf**: PDF 文档，提取所有页面文本

**响应**:
```json
{
  "content": "解析后的文件内容...",
  "encoding": "gbk",  // 或 "docx", "pdf"
  "size": 5000
}
```

---

## 数据库状态管理

### 数据库模型

**文件**: `database/models.py`

```python
class Task(Base):
    """任务模型 - 数据库单一真实源"""
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    project_name = Column(String, nullable=False)
    village_data = Column(Text, nullable=False)
    status = Column(String, default="idle")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 层级完成状态
    layer_1_completed = Column(Boolean, default=False)
    layer_2_completed = Column(Boolean, default=False)
    layer_3_completed = Column(Boolean, default=False)

    # 暂停状态
    pause_after_step = Column(Boolean, default=False)
    waiting_for_review = Column(Boolean, default=False)

    # 当前层级
    current_layer = Column(Integer, default=1)

    # 检查点
    checkpoints = relationship("Checkpoint", back_populates="task")
```

### 关键状态更新

```python
# 层级完成时立即更新数据库
async def on_layer_completed(task_id: str, layer: int):
    await db.update_task(
        task_id,
        {
            f"layer_{layer}_completed": True,
            "current_layer": layer,
        }
    )

# 暂停时立即更新数据库
async def on_pause(task_id: str, reason: str):
    await db.update_task(
        task_id,
        {
            "pause_after_step": (reason == "step_mode"),
            "waiting_for_review": (reason == "review"),
        }
    )

# 完成时立即更新数据库
async def on_completed(task_id: str):
    await db.update_task(
        task_id,
        {
            "status": "completed",
            "execution_complete": True,
        }
    )
```

### 去重逻辑移除

**删除的代码**:
```python
# ❌ 已删除：SSE 事件去重集合
sent_pause_events: Set[str] = set()
sent_layer_events: Set[Tuple[str, int]] = set()

# ❌ 已删除：前端去重逻辑
# processedPauseEventsRef, completedLayersRef
```

**新架构**:
- ✅ 数据库状态是唯一真实源
- ✅ REST 轮询确保状态同步
- ✅ SSE 仅负责流式文本效果
- ✅ 无需任何去重逻辑

---

## 部署指南

### 开发环境

**启动后端**:
```bash
cd backend
pip install -r requirements.txt
python main.py
```

访问: http://127.0.0.1:8000

API 文档: http://127.0.0.1:8000/docs

---

### 生产环境

**使用 Uvicorn**:
```bash
uvicorn main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 4 \
  --log-level info \
  --access-log
```

---

### Docker 部署

**Dockerfile**:
```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]
```

**docker-compose.yml**:
```yaml
version: '3.8'

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - ZHIPUAI_API_KEY=${ZHIPUAI_API_KEY}
      - LLM_MODEL=glm-4-flash
    volumes:
      - ./results:/app/results
```

---

## 最新改进 (2025) ⭐⭐⭐

### SSE/REST 解耦重构

**核心变更**: 从复杂的 SSE 事件流迁移到简单的 SSE/REST 职责分离架构

**关键改进**:
- ✅ 后端：SSE 仅发送 `text_delta` 和 `error` 事件
- ✅ 前端：引入 `TaskController` 统一状态管理，REST 轮询获取可靠状态
- ✅ 移除所有前后端去重逻辑
- ✅ 数据库作为单一真实源

**优势对比**:

| 特性 | 重构前 | 重构后 |
|------|--------|--------|
| **事件类型** | 7+ 种 | 2 种 |
| **状态源** | SSE 事件 | 数据库 |
| **去重逻辑** | 需要前后端去重 | 无需去重 |
| **状态可靠性** | 事件可能丢失 | REST 轮询确保 |
| **代码复杂度** | 高 | 低 |
| **维护成本** | 高 | 低 |
| **扩展性** | 困难 | 容易 |

---

## 相关文档

- **[前端实现文档](frontend.md)** - Next.js 14 技术栈、类型系统、SSE/REST 解耦
- **[核心智能体文档](agent.md)** - LangGraph 架构、三层规划系统
- **[README](../README.md)** - 项目概述和快速开始
