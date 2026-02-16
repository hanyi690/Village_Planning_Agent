# 前端组件架构文档

> 村庄规划智能体 - Next.js 组件架构详解

## 目录

- [架构概述](#架构概述)
- [组件层级](#组件层级)
- [核心组件](#核心组件)
- [数据流](#数据流)
- [类型系统](#类型系统)

---

## 架构概述

### 技术栈

- **框架**: Next.js 14 (App Router)
- **语言**: TypeScript
- **样式**: Tailwind CSS
- **状态管理**: React Context

### 设计原则

1. **单一职责**: 每个组件只负责一个功能
2. **状态驱动**: UI 通过条件渲染响应状态变化
3. **类型安全**: 使用 TypeScript 接口定义所有 Props

---

## 组件层级

```
RootLayout (app/layout.tsx)
└── Page (app/page.tsx)
    └── UnifiedPlanningProvider
        ├── VillageInputForm (输入表单)
        └── ChatPanel (规划界面)
            ├── 状态指示器
            ├── MessageList
            │   ├── TextMessage
            │   ├── LayerCompletedMessage
            │   ├── ReviewInteractionMessage
            │   └── ProgressMessage
            ├── ReviewPanel (条件渲染)
            └── TaskController (无头组件)
```

---

## 核心组件

### UnifiedPlanningProvider

**文件**: `contexts/UnifiedPlanningContext.tsx`

全局状态管理 Provider。

**职责**:
- 管理所有规划状态
- 提供 `syncBackendState` 方法同步后端状态
- 提供各种 Actions 供组件调用

**核心状态**:

```typescript
interface PlanningState {
  // 任务信息
  taskId: string | null;
  projectName: string | null;
  status: Status;
  
  // 消息列表
  messages: Message[];
  
  // 审查状态 (后端同步)
  isPaused: boolean;
  pendingReviewLayer: number | null;
  
  // 层级完成状态 (后端同步)
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  
  // 其他
  checkpoints: Checkpoint[];
  currentLayer: number | null;
}
```

### ChatPanel

**文件**: `components/chat/ChatPanel.tsx`

主聊天界面组件。

**职责**:
- 消息列表渲染
- 审查面板条件渲染
- 维度内容流式显示
- 状态指示器显示

**核心逻辑**:

```typescript
export default function ChatPanel() {
  const { isPaused, pendingReviewLayer, syncBackendState } = useUnifiedPlanningContext();
  
  // TaskController 管理 REST 轮询和 SSE
  const [taskState, { approve, reject, rollback }] = useTaskController(taskId, callbacks);
  
  // 同步后端状态到 Context
  useEffect(() => {
    if (!taskId) return;
    syncBackendState(taskState);
  }, [taskId, taskState, syncBackendState]);
  
  return (
    <div>
      {/* 状态指示器 */}
      {status === 'planning' && <StatusIndicator />}
      
      {/* 消息列表 */}
      <MessageList messages={messages} />
      
      {/* 审查面板 (条件渲染) */}
      {isPaused && pendingReviewLayer && (
        <ReviewPanel
          layer={pendingReviewLayer}
          onApprove={handleReviewApprove}
          onReject={handleReviewReject}
        />
      )}
    </div>
  );
}
```

### TaskController

**文件**: `controllers/TaskController.tsx`

无头状态管理组件（不渲染任何 UI）。

**职责**:
- REST 轮询 (每 2 秒)
- SSE 连接管理
- 状态同步到父组件
- 提供 approve/reject/rollback 方法

**使用方式**:

```typescript
const [taskState, actions] = useTaskController(taskId, {
  onDimensionDelta: (key, delta, accumulated, layer) => {...},
  onLayerCompleted: (layer, report, dimensionReports) => {...},
  onPause: (layer, checkpointId) => {...},
});

// 调用 actions
await actions.approve();
await actions.reject(feedback);
await actions.rollback(checkpointId);
```

### MessageList

**文件**: `components/chat/MessageList.tsx`

消息列表组件，支持多种消息类型。

**消息类型渲染**:

| 类型 | 组件 | 说明 |
|------|------|------|
| `text` | TextMessage | 文本消息 |
| `layer_completed` | LayerCompletedMessage | 层级完成，显示维度报告 |
| `review_interaction` | ReviewInteractionMessage | 审查交互，显示操作按钮 |
| `progress` | ProgressMessage | 进度消息 |
| `error` | ErrorMessage | 错误消息 |

### ReviewPanel

**文件**: `components/chat/ReviewPanel.tsx`

审查面板组件。

**Props**:

```typescript
interface ReviewPanelProps {
  layer: number;                              // 待审查层级
  onApprove: () => Promise<void>;             // 批准
  onReject: (feedback: string) => Promise<void>;  // 驳回
  onRollback?: (checkpointId: string) => Promise<void>;  // 回退
  isSubmitting?: boolean;
}
```

**UI 结构**:

```
┌─────────────────────────────────────┐
│ 📋 第 {layer} 层规划已完成           │
│                                     │
│   [查看详情]  [驳回]  [批准继续]     │
└─────────────────────────────────────┘
```

### LayerCompletedMessage

**文件**: `components/chat/messages/LayerCompletedMessage.tsx`

层级完成消息组件。

**显示内容**:
- 层级标题
- 维度报告列表（可折叠）
- 操作按钮（查看详情）

---

## 数据流

### 状态同步流程

```
后端 AsyncSqliteSaver
  ↓ (REST 轮询 / 2秒)
TaskController.fetchStatus()
  ↓
setState(taskState)
  ↓
ChatPanel useEffect 检测到 taskState 变化
  ↓
syncBackendState(taskState)
  ↓
UnifiedPlanningContext 更新:
  - isPaused
  - pendingReviewLayer
  - completedLayers
  ↓
UI 重新渲染 (条件渲染 ReviewPanel)
```

### 审查操作流程

```
用户点击"批准"
  ↓
handleReviewApprove()
  ↓
approve() → POST /api/planning/review?action=approve
  ↓
后端清除暂停标志
  ↓
REST 轮询获取新状态:
  pause_after_step = false
  ↓
syncBackendState():
  isPaused = false
  ↓
ReviewPanel 消失 (条件渲染)
```

### 流式文本流程

```
后端 graph.astream() 执行
  ↓
SSE: dimension_delta 事件
  ↓
TaskController.onDimensionDelta 回调
  ↓
ChatPanel 更新维度内容缓存
  ↓
LayerCompletedMessage 显示流式内容
```

---

## 类型系统

### 消息类型

```typescript
type MessageType = 'text' | 'layer_completed' | 'review_interaction' | 
                   'progress' | 'error' | 'file';

interface Message {
  id: string;
  timestamp: Date;
  role: 'user' | 'assistant' | 'system';
  type: MessageType;
  content: string;
}
```

### 层级完成消息

```typescript
interface LayerCompletedMessage extends Message {
  type: 'layer_completed';
  layer: number;
  content: string;
  fullReportContent: string;
  dimensionReports: Record<string, string>;
  summary: {
    word_count: number;
    dimension_count: number;
    key_points: string[];
  };
  actions: ActionButton[];
}
```

### 审查交互消息

```typescript
interface ReviewInteractionMessage extends Message {
  type: 'review_interaction';
  layer: number;
  reviewState: 'pending' | 'approved' | 'rejected' | 'rolled_back';
  availableActions: Array<'approve' | 'reject' | 'rollback'>;
  submittedAt?: Date;
  submissionType?: 'approve' | 'reject' | 'rollback';
  submissionFeedback?: string;
}
```

### 操作按钮

```typescript
interface ActionButton {
  id: string;
  label: string;
  action: 'approve' | 'reject' | 'rollback' | 'view';
  variant?: 'primary' | 'secondary' | 'danger';
  onClick?: () => void | Promise<void>;
}
```

---

## 条件渲染规则

### ReviewPanel 显示

```typescript
// 条件: isPaused && pendingReviewLayer
{isPaused && pendingReviewLayer && (
  <ReviewPanel layer={pendingReviewLayer} ... />
)}
```

### 状态指示器

```typescript
{status === 'planning' && <StatusBadge status="running" />}
{status === 'paused' && <StatusBadge status="paused" />}
{status === 'completed' && <StatusBadge status="completed" />}
```

### 消息类型判断

```typescript
function renderMessage(message: Message) {
  switch (message.type) {
    case 'layer_completed':
      return <LayerCompletedMessage {...message} />;
    case 'review_interaction':
      return <ReviewInteractionMessage {...message} />;
    case 'progress':
      return <ProgressMessage {...message} />;
    default:
      return <TextMessage {...message} />;
  }
}
```
