# 前端组件架构文档 (Frontend Component Architecture)

> **村庄规划智能体** - Next.js 前端组件架构详解

## 目录

- [架构概述](#架构概述)
- [SSE/REST 解耦架构](#sserest-解耦架构)
- [数据流管理](#数据流管理)
- [组件层级](#组件层级)
- [类型系统](#类型系统)
- [审查面板显示逻辑](#审查面板显示逻辑)

---

## 架构概述

### 技术栈

- **框架**: Next.js 14 (App Router)
- **UI 库**: React 18
- **语言**: TypeScript
- **样式**: Tailwind CSS
- **状态管理**: React Context + Hooks
- **实时通信**: REST 轮询 + Server-Sent Events (SSE)

### 组件架构原则

1. **单一职责**: 每个组件只负责一个功能
2. **自包含**: 组件包含自己的状态和逻辑
3. **可复用**: 通过 props 配置，支持多种使用场景
4. **类型安全**: 使用 TypeScript 接口定义 props

---

## SSE/REST 解耦架构

### 架构设计原则

**REST 职责**：可靠的状态同步（每 2 秒轮询）
- 从 AsyncSqliteSaver 读取完整状态
- 层级完成、暂停、审查状态
- 数据库单一真实源

**SSE 职责**：维度级实时流式推送
- `dimension_delta` - 维度增量 token
- `dimension_complete` - 维度完成
- `layer_progress` - 层级进度

### 完整数据流

```
┌─────────────────────────────────────────────────────┐
│                   前端 (Next.js)                    │
│  ┌──────────────────────────────────────────┐      │
│  │         ChatPanel (主界面)              │      │
│  │  ┌────────────────────────────────────┐ │      │
│  │  │  MessageList (消息列表)            │ │      │
│  │  │  ├─ TextMessage                    │ │      │
│  │  │  ├─ LayerCompletedMessage          │ │      │
│  │  │  └─ ReviewInteractionMessage       │ │      │
│  │  └────────────────────────────────────┘ │      │
│  │  ┌────────────────────────────────────┐ │      │
│  │  │  TaskController (REST 轮询)        │ │      │
│  │  │  - 状态同步                         │ │      │
│  │  └────────────────────────────────────┘ │      │
│  │  ┌────────────────────────────────────┐ │      │
│  │  │  useTaskSSE (SSE 流式)             │ │      │
│  │  │  - dimension_delta                 │ │      │
│  │  │  - dimension_complete              │ │      │
│  │  └────────────────────────────────────┘ │      │
│  └──────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────┘
                    ↓ REST 轮询 (每2秒) + SSE 流式
┌─────────────────────────────────────────────────────┐
│                后端 (FastAPI)                       │
│  ┌──────────────────────────────────────────┐      │
│  │  AsyncSqliteSaver (状态持久化)          │      │
│  │  ↓  checkpoints 表 (自动管理)            │      │
│  │  - layer_X_completed                   │      │
│  │  - analysis_dimension_reports           │      │
│  │  - concept_dimension_reports            │      │
│  │  - detailed_dimension_reports           │      │
│  │  - pause_after_step                    │      │
│  │  - previous_layer                      │      │
│  │  - pending_review_layer                │      │
│  └──────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────┘
```

### SSE 事件类型

| 事件类型 | 说明 | 数据结构 |
|----------|-----------|----------|
| **dimension_delta** | 维度增量事件 | `{"dimension_key":"location","dimension_name":"区位分析","layer":1,"chunk":"...","accumulated":"完整内容"}` |
| **dimension_complete** | 维度完成事件 | `{"dimension_key":"location","dimension_name":"区位分析","layer":1,"full_content":"完整维度的报告内容..."}` |
| **layer_progress** | 层级进度事件 | `{"layer":1,"completed":2,"total":12,"percentage":16}` |
| **pause** | 暂停事件 | `{"current_layer":1,"checkpoint_id":"...","reason":"step_mode"}` |
| **stream_paused** | 流暂停事件 | `{"current_layer":1,"reason":"waiting_for_resume"}` |

### layer_completed 事件详解

**后端位置**: `backend/api/planning.py:575-576`

**事件结构**:
```python
event_data = {
    "type": "layer_completed",
    "layer": layer_num,                           # 层级编号 (1, 2, 3)
    "layer_number": layer_num,
    "session_id": session_id,
    "message": f"Layer {layer_num} completed",
    "report_content": report[:500000],           # 完整报告内容（截断至 500k 字符）
    "dimension_reports": dimension_reports,      # 各维度报告字典
    "pause_after_step": event.get("pause_after_step", False),  # ✅ 是否需要暂停审查
    "pending_review_layer": event.get("pending_review_layer", 0),  # ✅ 待审查层级
    "timestamp": datetime.now().isoformat()
}
```

**字段说明**:
- `pause_after_step`: 指示是否在步进模式下暂停
- `pending_review_layer`: 指示哪个层级需要审查（0 表示无需审查）

**前端响应机制**:
- **当前实现**: 通过 REST 轮询获取 `pause_after_step` 和 `pending_review_layer` 状态（每 2 秒）
- **数据流**: TaskController → UnifiedPlanningContext → ReviewPanel 条件渲染
- **显示条件**: `isPaused && pendingReviewLayer` 都为真时显示审查面板
- **延迟**: 最多 2 秒轮询延迟

**优化建议**:
为了实现无延迟显示，可以在 SSE 事件处理中直接响应 `layer_completed` 事件：
```typescript
// 在 TaskController 中添加 layer_completed 事件处理
} else if (eventType === 'layer_completed') {
  const pauseAfterStep = event.data?.pause_after_step || false;
  const pendingReviewLayer = event.data?.pending_review_layer || 0;

  // 立即更新状态，无需等待轮询
  if (pauseAfterStep && pendingReviewLayer > 0) {
    actions.syncBackendState({
      ...taskState,
      pause_after_step: true,
      pending_review_layer: pendingReviewLayer,
    });
  }
}
```

---

## 数据流管理

### UnifiedPlanningContext

**文件**: `contexts/UnifiedPlanningContext.tsx`

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

  // ✅ 新增：简化后的审查状态（单一真实源，来自后端）
  isPaused: boolean;
  pendingReviewLayer: number | null;
  
  // ✅ 新增：层级完成状态
  completedLayers: {
    1: boolean;
    2: boolean;
    3: boolean;
  };

  // 状态
  status: TaskStatus;
  currentLayer: number | null;
  currentCheckpoint: Checkpoint | null;

  // 错误
  error: string | null;
}
```

### TaskController 集成模式

**文件**: `controllers/TaskController.tsx`

**职责**: 无头状态管理，协调 REST 轮询和 SSE 回调

**关键特性**:
- REST 轮询每 2 秒获取状态（从 AsyncSqliteSaver 读取）
- SSE 事件处理（维度级流式）
- 纯数据搬运: 获取状态 -> 同步到 Context
- 无任何业务逻辑判断

**数据流**:
```
TaskController.fetchStatus()
  ↓
GET /api/planning/status/{session_id}
  ↓
返回状态 (pauseAfterStep, layer_X_completed, previousLayer, pendingReviewLayer, etc.)
  ↓
actions.syncBackendState(status)
  ↓
直接更新 Context 状态 (不做任何判断)
  ↓
UI 重新渲染 (条件渲染 ReviewPanel)
```

### 消息驱动的 UI 状态管理

**核心思想**: 所有 UI 状态通过 messages 数组表示

**消息类型**:
```typescript
type Message =
  | TextMessage              // 文本消息
  | SystemMessage            // 系统消息
  | LayerCompletedMessage   // 层级完成消息
  | ReviewInteractionMessage // 审查交互消息
  | ErrorMessage;           // 错误消息
```

---

## 组件层级

### 组件层级树

```
RootLayout (app/layout.tsx)
└── Page (app/page.tsx)
    └── UnifiedPlanningContext
        ├── VillageInputForm
        │   ├── VillageInputForm
        │   └── SubmitButton
        └── ChatPanel (规划执行界面)
            ├── MessageList
            │   ├── TextMessage
            │   ├── SystemMessage
            │   ├── LayerCompletedMessage
            │   └── ReviewInteractionMessage
            │       ├── ApproveButton
            │       ├── RejectButton
            │       ├── RollbackButton
            │       └── FeedbackInput
            └── TaskController (状态管理层)
                ├── REST 轮询 (每 2 秒)
                └── SSE 流式
```

### 核心组件

#### ChatPanel

**文件**: `components/chat/ChatPanel.tsx`

**职责**: 主聊天界面，管理消息显示和交互

**关键功能**:
- 消息列表渲染（流式文本）
- 条件渲染审查面板（状态驱动）
- 状态指示器（层进度、暂停状态）
- 错误提示

**Props**:
```typescript
interface ChatPanelProps {
  messages: Message[];
  status: TaskStatus;
  taskId: string | null;
  onReviewApprove: (sessionId: string) => Promise<void>;
  onReviewReject: (sessionId: string, feedback: string) => Promise<void>;
  onReviewRollback: (sessionId: string, checkpointId: string) => Promise<void>;
}
```

#### ReviewInteractionMessage

**文件**: `components/chat/ReviewInteractionMessage.tsx`

**职责**: 人工审查消息组件

**关键功能**:
- 显示审查信息（层级信息）
- 通过/驳回按钮
- 回退修复功能
- 反馈输入

**数据流**:
```
用户点击"通过"
  ↓
handleReviewApprove(sessionId)
  ↓
TaskController.approve()
  ↓
POST /api/planning/review/{id}?action=approve
  ↓
后端清除 pause 标志 → 恢复执行
  ↓
前端 TaskController 检测到 pauseAfterStep=false
  ↓
继续执行规划任务
```

#### TaskController

**文件**: `controllers/TaskController.tsx`

**职责**: 无头状态管理

**关键功能**:
- REST 轮询（每 2 秒）
- SSE 事件处理
- 状态同步
- 回调触发

**使用示例**:
```typescript
const [taskState, { approve, reject, rollback }] = useTaskController(taskId);
```

---

## 类型系统

### 核心类型定义

**文件**: `types/index.ts`

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

// TaskState
interface TaskState {
  status: TaskStatus;
  currentLayer: number | null;
  previousLayer: number | null;      // 上一个完成的层级
  pendingReviewLayer: number | null; // 待审查的层级
  layer1Completed: boolean;
  layer2Completed: boolean;
  layer3Completed: boolean;
  pauseAfterStep: boolean;
  waitingForReview: boolean;
  lastCheckpointId: string | null;
  executionError: string | null;
  executionComplete: boolean;
  progress: number | null;
}
```

### 状态响应类型

```typescript
// SessionStatusResponse
interface SessionStatusResponse {
  session_id: string;
  status: string;
  current_layer: number;
  previous_layer: number | null;      // 上一个完成的层级
  pending_review_layer: number | null; // 待审查的层级
  layer_1_completed: boolean;
  layer_2_completed: boolean;
  layer_3_completed: boolean;
  pause_after_step: boolean;
  waiting_for_review: boolean;
  execution_complete: boolean;
  progress: number | null;
}

// SSE 事件类型
interface DimensionDeltaEvent {
  dimension_key: string;
  dimension_name: string;
  layer: number;
  chunk: string;
  accumulated: string;
}

interface DimensionCompleteEvent {
  dimension_key: string;
  dimension_name: string;
  layer: number;
  full_content: string;
}
```

---

## 审查面板显示逻辑

### 审查面板组件

**文件**: `components/chat/ReviewPanel.tsx`

**职责**: 状态驱动的独立审查组件，不依赖消息流

**显示条件**: `isPaused && pendingReviewLayer`

```typescript
// ChatPanel.tsx:860-880
{isPaused && pendingReviewLayer && (
  <div className="border-t border-gray-200 bg-white">
    <div className="max-w-4xl mx-auto">
      <ReviewPanel
        layer={pendingReviewLayer}
        onApprove={async () => {
          await approve();
          addMessage(createSystemMessage(`✅ 已批准，继续执行下一层...`));
          setStatus('planning');
        }}
        onReject={async (feedback) => {
          await reject(feedback);
          addMessage(createSystemMessage('🔄 正在根据反馈修复规划内容...'));
          setStatus('revising');
        }}
        onRollback={async (checkpointId) => {
          await rollback(checkpointId);
          addMessage(createSystemMessage(`↩️ 已回退到检查点: ${checkpointId}`));
        }}
        isSubmitting={status === 'reviewing'}
      />
    </div>
  </div>
)}
```

### 状态数据流

```
后端 layer_completed 事件
  ↓
pause_after_step = True
pending_review_layer = N
  ↓
TaskController 轮询 /status (2秒间隔)
  ↓
syncBackendState(taskState)
  ↓
isPaused = True
pendingReviewLayer = N
  ↓
ReviewPanel 显示 (条件渲染)
```

### 状态同步机制

**UnifiedPlanningContext.syncBackendState()**:
```typescript
// UnifiedPlanningContext.tsx:252-253
const syncBackendState = useCallback((backendData: any) => {
  console.log('[UnifiedPlanningContext] Syncing backend state:', backendData);

  setStatusState(backendData.status || 'idle');
  setIsPaused(backendData.pause_after_step || backendData.status === 'paused');
  setPendingReviewLayer(backendData.previous_layer ?? backendData.pending_review_layer ?? null);
  setCurrentLayer(backendData.current_layer ?? null);

  // 同步层级完成状态
  setCompletedLayers({
    1: backendData.layer_1_completed || false,
    2: backendData.layer_2_completed || false,
    3: backendData.layer_3_completed || false,
  });
}, []);
```

**ChatPanel 状态同步**:
```typescript
// ChatPanel.tsx:353-366
useEffect(() => {
  if (!taskId) return;

  // 直接将 taskState 同步到 Context
  // Controller 只负责数据搬运,不做任何业务逻辑判断
  syncBackendState(taskState);

  console.log('[ChatPanel] Synced backend state:', {
    taskId,
    taskState,
  });
}, [taskId, taskState, syncBackendState]);
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
│  ├─ previousLayer (上一个完成的层级)
│  ├─ pendingReviewLayer (待审查的层级)
│  └─ executionComplete (执行完成)
├─ SSE: /api/planning/stream (dimension_delta, dimension_complete)
└─ UI更新 (ChatPanel渲染)
```

### 暂停/恢复流程

```
步进模式 + 层级完成
  ↓
PauseManagerNode 设置 pause_after_step=True
  ↓
前端 REST 轮询检测到 pauseAfterStep=true
  ↓
TaskController.syncBackendState()
  ↓
Context.isPaused = true, Context.pendingReviewLayer = 1
  ↓
ReviewPanel 显示 (条件渲染)
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
syncBackendState()
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

### 2. 状态驱动 UI

**技术**: 条件渲染 `{isPaused && <ReviewPanel ... />}`

**效果**:
- 无重复渲染风险
- React 自动优化
- 状态一致性保证

### 3. 稳定回调引用

**技术**: useCallback + useRef

**效果**:
- 防止不必要的重新渲染
- 减少内存分配