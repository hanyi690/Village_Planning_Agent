# 前端实现文档 (Frontend Implementation)

> **村庄规划智能体** - Next.js 前端实现详解

## 目录

- [技术栈](#技术栈)
- [SSE/REST 解耦架构](#sse-rest-解耦架构)
- [数据流管理](#数据流管理)
- [核心组件](#核心组件)
- [类型系统](#类型系统)
- [API 客户端](#api-客户端)

---

## 技术栈

### 核心框架
- **Next.js 14** - React 框架 (App Router)
- **TypeScript** - 类型安全开发
- **Tailwind CSS** - 实用优先级 CSS 框架

### 构建模式
- **开发模式**: `npm run dev` - 热模块替换（HMR）
- **生产构建**: `npm run build` - 优化打包

---

## SSE/REST 解耦架构

### 架构设计原则

**REST 职责**：
- 可靠的状态同步（每 2 秒轮询）
- 完整的状态管理
- AsyncSqliteSaver 作为状态源

**SSE 职责**：
- 维度级流式文本推送（打字机效果）
- 实时 token 推送
- 维度级增量事件

### 数据流图

```
┌─────────────────────────────────────────────────────┐
│                   前端 (Next.js)                    │
│  ┌──────────────────────────────────────────┐      │
│  │         TaskController (状态管理层)      │      │
│  │  ┌────────────────────────────────────┐ │      │
│  │  │  REST 轮询 (每 2 秒)            │ │      │
│  │  │  ├─ GET /api/planning/status/{id} │ │      │
│  │  │  ├─ pauseAfterStep               │ │      │
│  │  │  ├─ layer_X_completed            │ │      │
│  │  │  └─ current_layer                 │ │      │
│  │  └────────────────────────────────────┘ │      │
│  │  ┌────────────────────────────────────┐ │      │
│  │  │  SSE (维度级流式)                │ │      │
│  │  │  GET /api/planning/stream/{id}    │ │      │
│  │  └────────────────────────────────────┘ │      │
│  └──────────────────────────────────────────┘      │
│  ┌──────────────────────────────────────────┐      │
│  │  ChatPanel (主界面)                     │      │
│  │  ┌────────────────────────────────────┐ │      │
│  │  │  ReviewInteractionMessage         │ │      │
│  │  │  (审查交互 UI)                     │ │      │
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

### 维度级 SSE 事件

| 事件类型 | 说明 | 数据结构 |
|----------|-----------|----------|
| **dimension_delta** | 维度增量事件 | `{"dimension_key":"location","dimension_name":"区位分析","layer":1,"chunk":"...","accumulated":"完整内容"}` |
| **dimension_complete** | 维度完成事件 | `{"dimension_key":"location","dimension_name":"区位分析","layer":1,"full_content":"完整维度的报告内容..."}` |
| **layer_progress** | 层级进度事件 | `{"layer":1,"completed":2,"total":12,"percentage":16}` |

---

## 数据流管理

### UnifiedPlanningContext

**文件**: `frontend/src/contexts/UnifiedPlanningContext.tsx`

**职责**: 单一真实源，管理所有规划状态

**状态结构**:
```typescript
interface PlanningState {
  // 任务信息
  taskId: string | null;
  sessionId: string | null;
  projectName: string | null;

  // 消息（UI 状态通过 messages 数组表示）
  messages: Message[];

  // 状态
  status: TaskStatus;
  currentLayer: number | null;
  currentCheckpoint: Checkpoint | null;

  // 错误
  error: string | null;
}
```

### TaskController

**文件**: `frontend/src/controllers/TaskController.tsx`

**职责**: 无头状态管理，协调 REST 轮询和 SSE 回调

**关键特性**:
- REST 轮询每 2 秒获取状态（从 AsyncSqliteSaver 读取）
- SSE 事件处理（维度级流式）
- 暂停检测和去重
- 稳定回调引用

**数据流**:
```
TaskController.startMonitoring()
  ↓
setInterval(() => pollStatus(), 2000)
  ↓
pollStatus()
  ↓
GET /api/planning/status/{session_id}
  ↓
AsyncSqliteSaver.get_state()
  ↓
返回状态 (pauseAfterStep, layer_X_completed, etc.)
  ↓
触发回调: onPause, onLayerComplete, onStatusUpdate
  ↓
UnifiedPlanningContext 更新状态
  ↓
UI 重新渲染
```

### 暂停检测流程

```
后端: PauseManagerNode 设置 pause_after_step=True
  ↓
后台执行检测暂停 → 发送 pause 事件
  ↓
_set_session_value 保存 sent_pause_events
  ↓
前端 REST 轮询: GET /api/planning/status/{id}
  ↓
返回 pauseAfterStep = len(sent_pause_events) > 0
  ↓
TaskController 检测到 pauseAfterStep 变化
  ↓
触发 onPause(layer) 回调
  ↓
ChatPanel.handlePause() 显示审查 UI
```

---

## 核心组件

### ChatPanel

**文件**: `frontend/src/components/chat/ChatPanel.tsx`

**职责**: 主聊天界面，管理消息显示和交互

**核心功能**:
- 消息列表渲染（流式文本）
- 人工审查交互（ReviewInteractionMessage）
- 状态指示器（层进度、暂停状态）
- 错误提示

**暂停处理**:
```typescript
const handlePause = useCallback((layer: number) => {
  setMessages((prevMessages) => {
    // 检查是否已存在同层级的审查消息
    const hasAnyReviewForLayer = prevMessages.some(m =>
      m.type === 'review_interaction' && m.layer === layer
    );

    if (hasAnyReviewForLayer) {
      // 已有审查消息，跳过（幂等性）
      return prevMessages;
    }

    // 创建审查交互消息
    return [
      ...prevMessages,
      {
        type: 'review_interaction',
        layer,
        reviewState: 'pending',
        content: '规划已暂停，请审查后决定下一步操作',
        availableActions: ['approve', 'reject', 'rollback'],
      } as ReviewInteractionMessage,
    ];
  });
}, [setMessages]);
```

### ReviewInteractionMessage

**文件**: `frontend/src/components/chat/ReviewInteractionMessage.tsx`

**职责**: 人工审查消息组件

**核心功能**:
- 显示审查信息
- 通过/驳回按钮
- 回退修复功能
- 反馈输入

**数据流**:
```
用户点击"通过"
  ↓
handleReviewApprove(sessionId)
  ↓
POST /api/planning/review/{id}?action=approve
  ↓
后端清除 pause 标志 → 恢复执行
  ↓
前端 TaskController 检测到 pauseAfterStep=false
  ↓
继续执行规划任务
```

### UnifiedPlanningContext

**文件**: `frontend/src/contexts/UnifiedPlanningContext.tsx`

**职责**: 全局状态管理

**核心状态**:
```typescript
const state: PlanningState = {
  sessionId: string | null;
  projectName: string | null;
  status: 'idle' | 'running' | 'paused' | 'reviewing' | 'completed' | 'failed';
  currentLayer: number | null;
  messages: Message[];
  error: string | null;
};
```

---

## 类型系统

### 核心类型定义

**文件**: `frontend/src/types/index.ts`

```typescript
// 任务状态
type TaskStatus =
  | 'idle'
  | 'running'
  | 'paused'
  | 'reviewing'
  | 'revising'
  | 'completed'
  | 'failed';

// 消息类型
type MessageRole = 'user' | 'assistant' | 'system' | 'review';

// 审查交互消息
interface ReviewInteractionMessage extends Message {
  type: 'review_interaction';
  layer: number;
  reviewState: 'pending' | 'approved' | 'rejected';
  availableActions: Array<'approve' | 'reject' | 'rollback'>;
  enableDimensionSelection: boolean;
  enableRollback: boolean;
  feedbackPlaceholder: string;
  quickFeedbackOptions: string[];
}

// 检查点类型
interface Checkpoint {
  checkpoint_id: string;
  description: string;
  timestamp: string;
  layer: number;
}
```

### 状态响应类型

```typescript
// SessionStatusResponse
interface SessionStatusResponse {
  session_id: string;
  status: string;
  current_layer: number;
  layer_1_completed: boolean;
  layer_2_completed: boolean;
  layer_3_completed: boolean;
  pause_after_step: boolean;
  waiting_for_review: boolean;
  execution_complete: boolean;
  progress: number | null;
}
```

---

## API 客户端

### HTTP 客户端

**文件**: `frontend/src/lib/api.ts`

**核心方法**:
```typescript
class PlanningApi {
  // POST /api/planning/start
  async startPlanning(data: StartPlanningRequest): Promise<StartPlanningResponse>

  // GET /api/planning/status/{sessionId}
  async getStatus(sessionId: string): Promise<SessionStatusResponse>

  // POST /api/planning/review/{id}?action=approve
  async approveReview(sessionId: string): Promise<{ message: string }>

  // POST /api/planning/review/{id}?action=reject
  async rejectReview(sessionId: string, feedback: string): Promise<{ message: string }>

  // POST /api/planning/review/{id}?action=rollback
  async rollbackCheckpoint(sessionId: string, checkpointId: string): Promise<{ message: string }>
}
```

### SSE 客户端

**文件**: `frontend/src/hooks/useTaskSSE.ts`

**核心方法**:
```typescript
function useTaskSSE(sessionId: string, callbacks: SSECallbacks) {
  // 连接 SSE
  const connect = () => {
    const eventSource = new EventSource(`/api/planning/stream/${sessionId}`);

    eventSource.addEventListener('dimension_delta', (e) => {
      const data = JSON.parse(e.data);
      callbacks.onDimensionDelta?.(data);
    });

    eventSource.addEventListener('dimension_complete', (e) => {
      const data = JSON.parse(e.data);
      callbacks.onDimensionComplete?.(data);
    });
  };

  return { connect, disconnect };
}
```

---

## 数据流总结

### 完整数据流

```
用户操作
  ↓
UnifiedPlanningContext.startPlanning()
  ↓
POST /api/planning/start
  ↓
TaskController (REST轮询每2秒) + useTaskSSE (SSE流式)
  ↓
├─ REST: /api/planning/status (从 AsyncSqliteSaver 读取状态)
│  ├─ pauseAfterStep (暂停状态)
│  ├─ layer_X_completed (层级完成)
│  └─ current_layer (当前层级)
├─ SSE: /api/planning/stream (dimension_delta, dimension_complete)
└─ UI更新 (ChatPanel渲染)
```

### 暂停/恢复流程

```
步进模式 + 层级完成
  ↓
PauseManagerNode 设置 pause_after_step=True
  ↓
后台执行检测暂停 → 发送 pause 事件
  ↓
_set_session_value 保存 sent_pause_events
  ↓
前端 REST 轮询检测到 pauseAfterStep=true
  ↓
TaskController 触发 onPause(layer)
  ↓
ChatPanel 显示审查 UI
  ↓
用户批准 → POST /api/planning/review/{id}?action=approve
  ↓
后端清除 pause 标志 → 恢复执行
  ↓
前端检测到 pauseAfterStep=false
  ↓
继续执行
```

### 状态同步流程

```
AsyncSqliteSaver (后端)
  ↓
GET /api/planning/status/{session_id}
  ↓
TaskController.pollStatus()
  ↓
onPause/onLayerComplete 回调
  ↓
UnifiedPlanningContext.setState()
  ↓
UI 重新渲染
```

### 流式文本流程

```
LangGraph 节点执行
  ↓
维度内容生成
  ↓
SSE: dimension_delta 事件
  ↓
useTaskSSE.onDimensionDelta()
  ↓
UI 实时显示
```

---

## 性能优化

### 1. SSE/REST 解耦

**技术**: REST 轮询 + SSE 流式

**效果**:
- 无事件丢失风险
- 无需复杂去重逻辑
- 状态一致性保证

### 2. 暂停事件去重

**技术**: 层级作用域去重

**效果**:
- 防止同一层重复触发
- 状态抖动检测
- 自动清理超时键

### 3. 稳定回调引用

**技术**: useCallback + useRef

**效果**:
- 防止不必要的重新渲染
- 减少内存分配