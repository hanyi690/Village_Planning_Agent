# 前端组件架构文档 (Frontend Component Architecture)

> **村庄规划智能体** - Next.js 前端组件架构详解

## 目录

- [架构概述](#架构概述)
- [维度级流式响应架构](#维度级流式响应架构)
- [数据流管理](#数据流管理)
- [组件层级](#组件层级)
- [类型系统](#类型系统)
- [暂停/恢复组件](#暂停恢复组件)

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

## 维度级流式响应架构

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
│  │  │  - 暂停检测                        │ │      │
│  │  │  - 层级完成检测                    │ │      │
│  │  └────────────────────────────────────┘ │      │
│  │  ┌────────────────────────────────────┐ │      │
│  │  │  useTaskSSE (SSE 流式)             │ │      │
│  │  │  - dimension_delta                 │ │      │
│  │  │  - dimension_complete              │ │      │
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
│  │  - analysis_dimension_reports           │      │
│  │  - sent_pause_events (内存状态)        │      │
│  └──────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────┘
```

### SSE 事件类型

| 事件类型 | 说明 | 数据结构 |
|----------|-----------|----------|
| **dimension_delta** | 维度增量事件 | `{"dimension_key":"location","dimension_name":"区位分析","layer":1,"chunk":"...","accumulated":"完整内容"}` |
| **dimension_complete** | 维度完成事件 | `{"dimension_key":"location","dimension_name":"区位分析","layer":1,"full_content":"完整维度的报告内容..."}` |
| **layer_progress** | 层级进度事件 | `{"layer":1,"completed":2,"total":12,"percentage":16}` |

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
- 暂停检测和去重
- 稳定回调引用

**暂停检测流程**:
```
TaskController.pollStatus()
  ↓
GET /api/planning/status/{session_id}
  ↓
返回 pauseAfterStep = len(sent_pause_events) > 0
  ↓
检测到 pauseAfterStep 从 false 变为 true
  ↓
生成 pauseKey = `pause_${taskId}_layer_${currentLayer}`
  ↓
如果 pauseKey 不在 triggeredEventsRef 中:
  ↓
触发 callbacksRef.current.onPause?.(currentLayer)
  ↓
ChatPanel.handlePause(layer) 显示审查 UI
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
        └── VillageInputForm
            ├── VillageInputForm
            └── SubmitButton
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
            └── StatusIndicator
```

### 核心组件

#### ChatPanel

**文件**: `components/chat/ChatPanel.tsx`

**职责**: 主聊天界面，管理消息显示和交互

**关键功能**:
- 消息列表渲染（流式文本）
- 人工审查交互（ReviewInteractionMessage）
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
- 暂停检测和去重
- 回调触发

**使用示例**:
```typescript
const [taskState, { approve, reject, rollback }] = useTaskController(taskId, {
  onPause: (layer) => {
    // 处理暂停
  },
  onLayerCompleted: (layer) => {
    // 处理层级完成
  },
  onComplete: () => {
    // 处理完成
  },
});
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

## 暂停/恢复组件

### ChatPanel 暂停处理

**文件**: `components/chat/ChatPanel.tsx`

```typescript
const handlePause = useCallback((layer: number) => {
  logger.chatPanel.info(`Task paused at Layer ${layer}`, { layer }, taskId);

  setMessages((prevMessages) => {
    // 幂等性检查
    const hasAnyReviewForLayer = prevMessages.some(m =>
      m.type === 'review_interaction' && m.layer === layer
    );

    const hasPendingReviewForLayer = prevMessages.some(m =>
      m.type === 'review_interaction' && m.layer === layer && m.reviewState === 'pending'
    );

    if (hasPendingReviewForLayer) {
      // 已有待处理的审查消息，跳过
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
}, [taskId, setMessages]);
```

### TaskController 暂停检测

**文件**: `controllers/TaskController.tsx`

```typescript
// Pause detection with layer-scoped deduplication
const isPaused = newState.pauseAfterStep || newState.status === 'paused';
const wasPaused = prev.pauseAfterStep || prev.status === 'paused';

if (isPaused && !wasPaused) {
  const currentLayer = newState.currentLayer ?? 1;
  const pauseKey = `pause_${taskId}_layer_${currentLayer}`;

  // 状态抖动检测
  if (currentLayer <= lastTriggeredPauseLayerRef.current) {
    console.log(`[TaskController] 检测到状态抖动：Layer ${currentLayer} <= 已触发的最高层级，跳过 onPause`);
  } else if (!triggeredEventsRef.current.has(pauseKey)) {
    eventsToTrigger.push(() => {
      console.log(`[TaskController] Pause detected at Layer ${currentLayer}`);
      callbacksRef.current.onPause?.(currentLayer);
    });
    triggeredEventsRef.current.add(pauseKey);
    lastTriggeredPauseLayerRef.current = Math.max(
      lastTriggeredPauseLayerRef.current,
      currentLayer
    );
  }
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

### 1. 暂停事件去重

**技术**: 层级作用域去重 + 状态抖动检测

**效果**:
- 防止同一层重复触发
- 状态抖动检测
- 自动清理超时键

### 2. SSE/REST 解耦

**技术**: REST 轮询 + SSE 流式

**效果**:
- 无事件丢失风险
- 无需复杂去重逻辑
- 状态一致性保证

### 3. 稳定回调引用

**技术**: useCallback + useRef

**效果**:
- 防止不必要的重新渲染
- 减少内存分配