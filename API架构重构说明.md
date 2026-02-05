# Village Planning Agent - API架构重构说明

## 概述

本文档详细说明了Village Planning Agent项目的API架构重构，包括文件依赖关系、函数调用关系和项目架构。

---

## 一、实现完成总结

### 新增文件

| 文件 | 行数 | 描述 |
|------|------|------|
| `backend/api/tasks.py` | ~420行 | 统一任务管理API |
| `backend/api/sessions.py` | ~250行 | 会话管理API |
| `backend/api/files.py` | ~100行 | 文件上传辅助API |

### 删除文件

| 文件 | 原因 |
|------|------|
| `backend/api/planning.py` | 已合并到tasks.py |
| `backend/api/conversation.py` | 已合并到sessions.py |
| `backend/api/review.py` | 已合并到tasks.py |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `backend/main.py` | 更新路由导入 |
| `frontend/src/lib/api.ts` | 完全重写 (~735行) |
| `frontend/src/app/villages/new/page.tsx` | 使用taskApi |
| `frontend/src/app/chat/new/page.tsx` | 使用sessionApi |
| `frontend/src/components/PlanningProgress.tsx` | 更新流式处理 |
| `frontend/src/components/ConversationManager.tsx` | 使用taskApi |
| `frontend/src/components/ChatInterface.tsx` | 使用taskApi + sessionApi |
| `frontend/src/components/ReviewDrawer.tsx` | 使用taskApi |

---

## 二、后端架构详解

### 目录结构

```
backend/
├── main.py                        # FastAPI应用入口
│   └── 导入: tasks, sessions, files, villages 路由
│
├── api/                           # API端点
│   ├── tasks.py                   # 统一任务管理 (新增)
│   ├── sessions.py                # 会话管理 (新增)
│   ├── files.py                   # 文件上传辅助 (新增)
│   └── villages.py                # 村庄数据查询 (未修改)
│
├── schemas.py                     # Pydantic数据模型 (未修改)
│
└── services/
    └── shared_task_manager.py     # 任务执行 (未修改)
```

### 2.1 tasks.py - 统一任务管理API

**文件依赖:**
- `schemas.py` - 使用数据模型 (TaskStatus, TaskResponse, TaskStatusResponse等)
- `services/shared_task_manager.py` - 调用任务管理器

**API端点:**

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/tasks` | POST | 创建新规划任务 |
| `/api/tasks/{task_id}` | GET | 获取任务状态 |
| `/api/tasks/{task_id}/stream` | GET | SSE流式更新 |
| `/api/tasks/{task_id}` | DELETE | 删除任务 |
| `/api/tasks` | GET | 列出所有任务 |
| `/api/tasks/{task_id}/review-data` | GET | 获取审查数据 |
| `/api/tasks/{task_id}/review/approve` | POST | 批准审查 |
| `/api/tasks/{task_id}/review/reject` | POST | 驳回审查 |
| `/api/tasks/{task_id}/rollback` | POST | 回退到检查点 |
| `/api/tasks/{task_id}/resume` | POST | 恢复暂停的任务 |

**核心函数:**

```python
# 创建任务
async def create_task(request: CreateTaskRequest, background_tasks: BackgroundTasks)
    ├── 验证输入 (project_name, village_data)
    ├── 生成task_id (uuid)
    ├── 创建PlanningRequest
    ├── task_manager.create_task(task_id, request)
    └── task_manager.run_planning_task(task_id, request) # 后台执行

# SSE流式传输
async def stream_task_status(task_id: str)
    └── async def event_generator()
        ├── 获取任务状态
        ├── 构建event_data = { type, task_id, data }
        ├── 发送: data: {json.dumps(event_data)}\n\n
        └── 完成时: type='complete' 或 type='failed'
```

### 2.2 sessions.py - 会话管理API

**文件依赖:**
- `schemas.py` - 使用数据模型 (ConversationMessage, ConversationState等)
- `services/shared_task_manager.py` - 获取任务状态用于流式传输

**API端点:**

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/sessions` | POST | 创建新会话 |
| `/api/sessions/{session_id}` | GET | 获取会话状态 |
| `/api/sessions/{session_id}` | DELETE | 删除会话 |
| `/api/sessions` | GET | 列出所有会话 |
| `/api/sessions/{session_id}/messages` | POST | 添加消息 |
| `/api/sessions/{session_id}/link` | POST | 关联会话到任务 |
| `/api/sessions/{session_id}/stream` | GET | SSE流式更新 |

**核心函数:**

```python
# 创建会话
async def create_new_session(request: CreateSessionRequest)
    ├── 生成session_id (uuid)
    ├── 创建ConversationState
    ├── 添加欢迎消息 (如果type='conversation')
    └── 返回 SessionResponse

# 关联任务
async def link_to_task(session_id: str, request: LinkTaskRequest)
    ├── 验证会话存在
    ├── 验证任务存在 (task_manager.get_task)
    ├── 更新会话: session.task_id = task_id
    ├── 添加系统消息
    └── 返回关联结果

# SSE流式传输
async def stream_session_updates(session_id: str)
    └── async def event_generator()
        ├── 获取会话状态
        ├── 如果session.task_id存在:
        │   ├── 获取任务状态 (task_manager.get_task)
        │   ├── 构建event_data
        │   └── 发送更新
        └── 完成时关闭连接
```

### 2.3 files.py - 文件上传辅助API

**文件依赖:** 无外部依赖

**API端点:**

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/files/upload` | POST | 上传并解码文件 |

**核心函数:**

```python
# 文件上传解码
async def upload_file(file: UploadFile)
    ├── 读取文件内容
    ├── 验证文件大小 (max 10MB)
    ├── 解码文件内容 (自动检测编码)
    │   ├── 尝试 UTF-8
    │   ├── 使用 chardet 检测
    │   ├── 尝试 GBK
    │   ├── 尝试 GB2312
    │   └── 最后使用 UTF-8 with errors='replace'
    └── 返回 FileUploadResponse (content, encoding, size)
```

### 2.4 main.py - 应用入口

**依赖导入:**

```python
from api import tasks, sessions, files, villages

# 路由注册
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(villages.router, prefix="/api/villages", tags=["villages"])
```

**删除旧路由:**
```python
# 已删除:
# app.include_router(planning.router, ...)
# app.include_router(conversation.router, ...)
# app.include_router(review.router, ...)
```

---

## 三、前端架构详解

### 目录结构

```
frontend/src/
├── lib/
│   └── api.ts                     # 统一API客户端 (重写)
│
├── app/
│   ├── villages/new/page.tsx      # 表单式规划页面
│   └── chat/
│       ├── new/page.tsx           # 创建新对话
│       └── [conversationId]/      # 对话页面
│
└── components/
    ├── PlanningProgress.tsx       # 进度显示组件
    ├── ConversationManager.tsx    # 对话管理器
    ├── ChatInterface.tsx          # 聊天界面
    └── ReviewDrawer.tsx           # 审查抽屉
```

### 3.1 lib/api.ts - API客户端 (完全重写)

**导出内容:**

| API对象 | 功能 | 来源 |
|---------|------|------|
| `villageApi` | 村庄数据查询 | 保持不变 |
| `taskApi` | 任务管理 | 新增 (合并planningApi + reviewApi) |
| `sessionApi` | 会话管理 | 新增 (替代conversationApi) |
| `fileApi` | 文件上传 | 新增 |

**TypeScript类型定义:**

```typescript
// 任务相关类型
type TaskStatusType = 'pending' | 'running' | 'paused' | 'reviewing' | 'revising' | 'completed' | 'failed';

interface CreateTaskRequest {
  project_name: string;
  village_data: string;
  task_description?: string;
  constraints?: string;
  need_human_review?: boolean;
  stream_mode?: boolean;
  step_mode?: boolean;
  input_mode?: 'text' | 'file-base64';
}

interface TaskResponse {
  task_id: string;
  status: TaskStatusType;
  message?: string;
}

interface TaskStatus {
  task_id: string;
  status: TaskStatusType;
  progress?: number;
  current_layer?: string;
  message?: string;
  result?: any;
  error?: string;
  created_at: string;
  updated_at: string;
}

// SSE事件格式
interface TaskStreamEvent {
  type: 'status' | 'complete' | 'failed';
  task_id: string;
  data: {
    status: TaskStatusType;
    progress?: number;
    current_layer?: string;
    message?: string;
    result?: any;
    error?: string;
    updated_at: string;
  };
}

// 会话相关类型
type SessionType = 'conversation' | 'form' | 'cli' | 'api';

interface SessionState {
  session_id: string;
  messages: SessionMessage[];
  task_id: string | null;
  project_name: string | null;
  status: 'idle' | 'collecting' | 'planning' | 'paused' | 'reviewing' | 'revising' | 'completed' | 'failed';
  created_at: string;
  updated_at: string;
}

// 文件上传响应
interface FileUploadResponse {
  content: string;
  encoding: string;
  size: number;
}
```

**taskApi核心方法:**

```typescript
export const taskApi = {
  // 创建任务
  async createTask(data: CreateTaskRequest): Promise<TaskResponse> {
    const response = await fetch(`${API_BASE_URL}/api/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return response.json();
  }

  // SSE流式监听
  createTaskStream(
    taskId: string,
    onMessage: (event: TaskStreamEvent) => void,
    onError?: (error: Error) => void
  ): EventSource {
    const url = `${API_BASE_URL}/api/tasks/${taskId}/stream`;
    const eventSource = new EventSource(url);

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data) as TaskStreamEvent;
      onMessage(data);
      if (data.type === 'complete' || data.type === 'failed') {
        eventSource.close();
      }
    };

    return eventSource;
  }

  // 审查相关 (来自reviewApi)
  async getReviewData(taskId: string): Promise<ReviewData>
  async approveReview(taskId: string): Promise<ReviewActionResponse>
  async rejectReview(taskId: string, feedback: string, dimensions?: string[]): Promise<ReviewActionResponse>
  async rollbackCheckpoint(taskId: string, checkpointId: string): Promise<ReviewActionResponse>
  async resumeTask(taskId: string): Promise<ReviewActionResponse>
};
```

**sessionApi核心方法:**

```typescript
export const sessionApi = {
  // 创建会话
  async createSession(type: SessionType = 'conversation'): Promise<SessionResponse> {
    const response = await fetch(`${API_BASE_URL}/api/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_type: type }),
    });
    return response.json();
  }

  // 关联任务
  async linkToTask(sessionId: string, taskId: string): Promise<{
    success: boolean;
    task_id: string;
    session_id: string;
    status: string;
    message: string;
  }> {
    const response = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}/link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_id: taskId }),
    });
    return response.json();
  }

  // SSE流式监听
  createSessionStream(
    sessionId: string,
    onMessage: (event: SessionStreamEvent) => void,
    onError?: (error: Error) => void
  ): EventSource;

  // 其他方法
  async getSessionState(sessionId: string): Promise<SessionState>
  async deleteSession(sessionId: string): Promise<void>
  async listSessions(): Promise<{ total: number; sessions: any[] }>
  async addMessage(sessionId: string, message: { ... }): Promise<{ ... }>
};
```

**fileApi核心方法:**

```typescript
export const fileApi = {
  async uploadFile(file: File): Promise<FileUploadResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(`${API_BASE_URL}/api/files/upload`, {
      method: 'POST',
      body: formData,
    });
    return response.json();
  }
};
```

### 3.2 页面组件依赖关系

#### villages/new/page.tsx - 表单式规划

**依赖:**
- `@/lib/api` → taskApi, fileApi
- `@/components/FileUpload`
- `@/components/PlanningProgress`

**数据流:**

```
用户上传文件 → FileUpload组件
    ↓
page.tsx: handleFileUpload(file, content)
    ↓
用户填写项目名称 + 点击"开始AI规划"
    ↓
page.tsx: handleStartPlanning()
    ├── taskApi.createTask({
    │     project_name,
    │     village_data: fileContent,
    │     input_mode: 'text',
    │     ...
    │   })
    ├── setTaskId(response.task_id)
    └── setStep('planning')
    ↓
<PlanningProgress taskId={taskId} />
    ↓
PlanningProgress: taskApi.createTaskStream(taskId, onMessage)
    ↓
接收SSE事件 → 更新进度条 → 完成时跳转
```

**关键代码:**

```typescript
// 创建任务
const response = await taskApi.createTask({
  project_name: projectName.trim(),
  village_data: fileContent,
  task_description: taskDescription,
  constraints: '无特殊约束',
  need_human_review: false,
  stream_mode: streamMode,
  step_mode: stepMode,
  input_mode: 'text',
});

// 流式监听
taskApi.createTaskStream(taskId, (event) => {
  const data = event.data;
  if (event.type === 'complete') {
    onComplete(data.result);
  }
});
```

#### chat/new/page.tsx - 创建新对话

**依赖:**
- `@/lib/api` → sessionApi

**数据流:**

```
访问 /chat/new
    ↓
page.tsx: useEffect(() => {
    sessionApi.createSession('conversation')
    ↓
    获取 session_id
    ↓
    router.replace(`/chat/${session_id}`)
    ↓
    跳转到 chat/[conversationId]/page.tsx
})
```

#### chat/[conversationId]/page.tsx - 对话页面

**依赖:**
- `@/contexts/ConversationContext`
- `@/components/ConversationManager`

**数据流:**

```
渲染 ConversationProvider
    ↓
<ConversationManager conversationId={conversationId} />
    ↓
    ├── 使用 Context 的状态
    │   ├── taskId
    │   ├── status
    │   ├── messages
    │   └── ...
    │
    └── 渲染子组件:
        ├── <ChatInterface />
        │   └── 收集用户输入
        │       ↓
        │   收集完成后:
        │   ├── taskApi.createTask(...)
        │   └── sessionApi.linkToTask(sessionId, taskId)
        │
        └── taskApi.createTaskStream() 监听任务更新
```

### 3.3 组件依赖详解

#### PlanningProgress.tsx - 进度显示

**依赖:**
- `@/lib/api` → taskApi
- `@/contexts/PlanningContext`
- `@/components/ReviewDrawer`

**关键代码:**

```typescript
// SSE连接
const eventSource = taskApi.createTaskStream(
  taskId,
  (event) => {
    const data = event.data;  // 新事件格式: { type, task_id, data }
    setStatus(data as TaskStatus);

    if (data.status === 'paused') {
      setShowReviewButton(true);
    }

    if (event.type === 'complete') {
      onComplete(data.result);
      eventSource.close();
    }
  }
);
```

**事件处理流程:**

```
createTaskStream()
    ↓
接收SSE事件
    ↓
    ├── type='status' → 更新进度
    ├── type='complete' → 显示完成状态
    ├── type='failed' → 显示错误
    └── data.status='paused' → 显示审查按钮
```

#### ConversationManager.tsx - 对话管理器

**依赖:**
- `@/lib/api` → taskApi
- `@/contexts/ConversationContext`
- `@/components/ChatInterface`
- `@/components/ViewerSidePanel`

**关键代码:**

```typescript
// 监听任务更新
const es = taskApi.createTaskStream(
  taskId,
  (event) => {
    const data = event.data;
    handleSSEMessage(data);
    // 更新状态、消息、查看器标签等
  }
);
```

#### ChatInterface.tsx - 聊天界面

**依赖:**
- `@/lib/api` → taskApi, sessionApi
- `@/contexts/ConversationContext`
- `@/components/FileUpload`

**关键代码:**

```typescript
// 启动规划
const task = await taskApi.createTask({
  project_name: collectedData.projectName,
  village_data: collectedData.villageData,
  step_mode: true,
  stream_mode: true,
  input_mode: 'text',
});

// 关联会话到任务
await sessionApi.linkToTask(conversationId, task.task_id);

setTaskId(task.task_id);
onTaskStart?.(task.task_id);
```

#### ReviewDrawer.tsx - 审查抽屉

**依赖:**
- `@/lib/api` → taskApi
- `@/components/DimensionSelector`
- `@/components/MarkdownRenderer`

**关键代码:**

```typescript
// 加载审查数据
const data = await taskApi.getReviewData(taskId);
setReviewData(data);

// 批准/驳回/回滚
await onApprove();  // 内部调用 taskApi.approveReview()
await onReject(feedback, dimensions);  // 内部调用 taskApi.rejectReview()
await onRollback(checkpointId);  // 内部调用 taskApi.rollbackCheckpoint()
```

---

## 四、数据流示例

### 4.1 表单式规划流程

```
┌──────────────────────────────────────────────────────────────────┐
│                        用户界面                                    │
│  villages/new/page.tsx                                            │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ 用户上传文件 + 填写项目名称
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│                    taskApi.createTask()                           │
│  POST /api/tasks                                                  │
│  Body: {                                                          │
│    project_name: "金田村",                                         │
│    village_data: "村庄现状数据...",                                 │
│    input_mode: 'text'                                             │
│  }                                                                │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ↓ HTTP响应
┌──────────────────────────────────────────────────────────────────┐
│  { task_id: "uuid-123", status: "pending" }                       │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ 建立SSE连接
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│                 taskApi.createTaskStream(taskId)                  │
│  GET /api/tasks/{taskId}/stream (SSE)                             │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ 持续接收事件
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  SSE事件流:                                                        │
│  data: {"type":"status","data":{"status":"running",...}}        │
│  data: {"type":"status","data":{"progress":33,...}}             │
│  data: {"type":"status","data":{"progress":66,...}}             │
│  data: {"type":"complete","data":{"result":{...}}}               │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ 每个事件触发UI更新
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  PlanningProgress组件:                                            │
│    - 更新进度条                                                    │
│    - 显示当前层级                                                  │
│    - 完成时显示结果                                                │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 对话式规划流程

```
┌──────────────────────────────────────────────────────────────────┐
│                        用户界面                                    │
│  chat/new/page.tsx                                                │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ 访问 /chat/new
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│                 sessionApi.createSession()                        │
│  POST /api/sessions                                               │
│  Body: { session_type: 'conversation' }                            │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ↓ HTTP响应
┌──────────────────────────────────────────────────────────────────┐
│  { session_id: "uuid-456", status: "idle" }                       │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ 重定向到 /chat/{sessionId}
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  ChatInterface组件:                                                │
│    - 显示欢迎消息                                                  │
│    - 收集用户输入 (村庄名称、数据)                                  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ 用户点击"开始规划"
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│                    taskApi.createTask()                           │
│  POST /api/tasks                                                  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ 获得task_id
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│                 sessionApi.linkToTask()                           │
│  POST /api/sessions/{sessionId}/link                               │
│  Body: { task_id: "uuid-123" }                                    │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ 开始监听任务更新
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│    taskApi.createTaskStream(taskId)                               │
│    或 sessionApi.createSessionStream(sessionId)                   │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ 实时更新聊天界面
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  ConversationManager:                                             │
│    - 添加进度消息到聊天                                            │
│    - 更新状态显示                                                  │
│    - 完成时显示查看器按钮                                          │
└──────────────────────────────────────────────────────────────────┘
```

### 4.3 审查流程

```
┌──────────────────────────────────────────────────────────────────┐
│  任务执行到检查点 (step_mode=true)                                  │
│  agent在每层完成后暂停                                             │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ SSE事件: type='pause'
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  PlanningProgress / ConversationManager:                          │
│    - 显示"开始审查"按钮                                             │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ 用户点击"开始审查"
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│                    taskApi.getReviewData()                        │
│  GET /api/tasks/{taskId}/review-data                               │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ↓ 返回审查数据
┌──────────────────────────────────────────────────────────────────┐
│  ReviewDrawer组件:                                                 │
│    - 显示当前层级内容                                               │
│    - 显示可选维度                                                   │
│    - 显示检查点列表                                                 │
└──────────────────────────────────────────────────────────────────┘
                              │
         ┌──────────────────────┬──────────────────────┐
         │                      │                      │
         ↓                      ↓                      ↓
    用户批准               用户驳回                用户回退
         │                      │                      │
         ↓                      ↓                      ↓
  taskApi.approveReview()  taskApi.rejectReview()  taskApi.rollbackCheckpoint()
  POST /approve            POST /reject             POST /rollback
         │                      │                      │
         └──────────────────────┴──────────────────────┘
                              │
                              │ 任务继续执行
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  agent继续执行下一层或进行修复                                      │
└──────────────────────────────────────────────────────────────────┘
```

---

## 五、关键架构变更

### 5.1 统一任务入口点

**变更前:**
- `/api/planning/start` - 表单式
- `/api/planning/upload` - 文件上传
- `/api/conversations/{id}/start-planning` - 对话式

**变更后:**
- `/api/tasks` POST - 统一创建入口

### 5.2 会话抽象

**设计理念:**
- Task (任务) = 核心规划工作单元
- Session (会话) = UI交互上下文 (可选)

**关系:**
```
Session (可选UI) ──links to──> Task (核心规划)
    │                            │
    ├─ conversation               ├─ project_name
    ├─ form                       ├─ village_data
    ├─ cli                       ├─ status
    └─ api                       └─ result
```

### 5.3 SSE事件结构统一

**变更前 (旧格式):**
```json
{
  "task_id": "uuid",
  "status": "running",
  "progress": 50,
  "message": "处理中..."
}
```

**变更后 (新格式):**
```json
{
  "type": "status",
  "task_id": "uuid",
  "data": {
    "status": "running",
    "progress": 50,
    "message": "处理中..."
  }
}
```

**事件类型:**
- `type: 'status'` - 状态更新
- `type: 'complete'` - 任务完成
- `type: 'failed'` - 任务失败

### 5.4 API分离

| API类型 | 功能 | 示例 |
|---------|------|------|
| Tasks (核心) | 规划任务CRUD + 审查控制 | 创建任务、获取状态、批准/驳回 |
| Sessions (UI层) | 会话状态管理 | 创建会话、添加消息、关联任务 |
| Files (工具) | 文件处理 | 上传并解码文件 |
| Villages (数据) | 村庄数据查询 | 获取村庄信息、查看规划结果 |

---

## 六、前后端交互时序图

```
前端 (React)                    后端 (FastAPI)              服务层
│                                │                          │
│  1. 创建任务                    │                          │
│  ──────────────────────────>   │                          │
│  POST /api/tasks               │                          │
│  {project_name, ...}           │                          │
│                                │ 2. 创建任务               │
│                                │ ──────────────────────>  │
│                                │ task_manager.create()    │
│                                │ <──────────────────────  │
│                                │                          │
│  <─────────────────────────    │                          │
│  {task_id, status}             │                          │
│                                │                          │
│  3. 建立SSE连接                 │                          │
│  ──────────────────────────>   │                          │
│  GET /api/tasks/{id}/stream    │                          │
│                                │                          │
│                                │ 4. 轮询任务状态            │
│                                │ <──────────────────────  │
│                                │ task_manager.get_task()  │
│                                │                          │
│  5. 接收SSE事件                 │                          │
│  <─────────────────────────    │                          │
│  data: {type, data}            │                          │
│                                │                          │
│  6. 更新UI                     │                          │
│  (进度条、状态等)               │                          │
│                                │                          │
│  [重复 4-5]                    │                          │
│                                │                          │
│  7. 任务完成                    │                          │
│  <─────────────────────────    │                          │
│  data: {type:'complete', ...}  │                          │
│                                │                          │
│  8. 显示结果                    │                          │
│  跳转到结果页面                 │                          │
│                                │                          │
```

---

## 七、总结

### 代码变化统计

- **新增代码**: ~770 行 (tasks.py + sessions.py + files.py)
- **删除代码**: ~820 行 (planning.py + conversation.py + review.py)
- **重写代码**: ~735 行 (api.ts)
- **修改代码**: ~200 行 (各组件更新)
- **净减少**: ~265 行

### 架构改进

1. **清晰分层**: 核心任务层 vs UI会话层
2. **统一入口**: 所有任务通过 `/api/tasks` 创建
3. **一致性**: 统一的SSE事件格式
4. **可扩展性**: 易于添加新的UI模式 (CLI、移动端等)
5. **可维护性**: 单一实现，减少重复代码

### 向后兼容性

⚠️ **破坏性变更**: 不向后兼容旧API
- 旧端点已删除 (`/api/planning/*`, `/api/conversations/*`)
- 前端必须同步更新
- 建议前后端同时部署

---

*文档生成时间: 2026-02-05*
*API版本: v2.0.0*
