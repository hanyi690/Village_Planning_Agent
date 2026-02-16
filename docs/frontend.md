# 前端实现文档

> 村庄规划智能体 - Next.js 前端架构详解

## 目录

- [技术栈](#技术栈)
- [架构概述](#架构概述)
- [核心状态管理](#核心状态管理)
- [TaskController 详解](#taskcontroller-详解)
- [数据流](#数据流)
- [核心组件](#核心组件)

---

## 技术栈

- **框架**: Next.js 14 (App Router)
- **语言**: TypeScript
- **样式**: Tailwind CSS
- **状态管理**: React Context + Hooks
- **实时通信**: REST 轮询 + SSE

---

## 架构概述

### 设计原则

1. **后端状态为单一真实源**: 前端 UI 状态直接从后端状态派生
2. **状态驱动 UI**: 通过条件渲染响应状态变化
3. **Controller 纯数据搬运**: TaskController 只负责获取和同步状态，不做业务逻辑判断
4. **幂等性**: 无论轮询多少次，只要后端状态不变，前端渲染结果不变

### 目录结构

```
frontend/src/
├── app/                         # Next.js App Router
│   ├── layout.tsx               # 根布局
│   └── page.tsx                 # 首页
├── contexts/
│   └── UnifiedPlanningContext.tsx   # 全局状态 Context
├── controllers/
│   └── TaskController.tsx           # REST 轮询 + SSE 管理
├── components/
│   ├── chat/
│   │   ├── ChatPanel.tsx            # 主聊天界面
│   │   ├── MessageList.tsx          # 消息列表
│   │   └── ReviewPanel.tsx          # 审查面板
│   └── ui/                          # 通用 UI 组件
├── hooks/
│   └── useStreamingRender.ts        # 流式渲染 Hook
├── lib/
│   ├── api.ts                       # API 客户端
│   └── constants.ts                 # 常量定义
└── types/
    └── index.ts                     # TypeScript 类型定义
```

---

## 核心状态管理

### UnifiedPlanningContext

**文件**: `contexts/UnifiedPlanningContext.tsx`

全局状态管理 Context，作为前端的单一数据源。

**核心状态**:

```typescript
interface PlanningState {
  // 任务信息
  taskId: string | null;
  projectName: string | null;
  status: Status;  // 'idle' | 'planning' | 'paused' | 'completed' | 'failed'
  
  // 消息
  messages: Message[];
  
  // 审查状态 (来自后端)
  isPaused: boolean;
  pendingReviewLayer: number | null;
  
  // 层级完成状态 (来自后端)
  completedLayers: {
    1: boolean;
    2: boolean;
    3: boolean;
  };
  
  // 其他
  checkpoints: Checkpoint[];
  currentLayer: number | null;
}
```

**关键 Action - syncBackendState**:

```typescript
const syncBackendState = useCallback((backendData: any) => {
  // 直接同步后端状态，不做任何判断
  setStatusState(backendData.status || 'idle');
  
  // 暂停状态
  const shouldPause = backendData.pause_after_step || backendData.status === 'paused';
  setIsPaused(shouldPause);
  
  // 待审查层级
  const pendingLayer = backendData.previous_layer ?? backendData.pending_review_layer ?? null;
  setPendingReviewLayer(pendingLayer);
  
  // 层级完成状态
  setCompletedLayers({
    1: backendData.layer_1_completed || false,
    2: backendData.layer_2_completed || false,
    3: backendData.layer_3_completed || false,
  });
}, []);
```

**状态变化检测**:

```typescript
// 使用 ref 跟踪之前状态，避免不必要的更新
const previousBackendStateRef = useRef<any>(null);

const syncBackendState = useCallback((backendData: any) => {
  const previousState = previousBackendStateRef.current;
  const hasStateChanged = !previousState ||
    previousState.status !== backendData.status ||
    previousState.pause_after_step !== backendData.pause_after_step ||
    previousState.pending_review_layer !== backendData.pending_review_layer;

  if (!hasStateChanged) return;
  
  // ... 更新状态
  
  previousBackendStateRef.current = {...};
}, []);
```

---

## TaskController 详解

**文件**: `controllers/TaskController.tsx`

### 核心理念

- **纯数据搬运**: 只负责获取状态和同步，不做任何业务逻辑判断
- **REST 轮询**: 每 2 秒调用 `/api/planning/status` 获取状态
- **SSE 流式**: 仅用于接收维度文本内容

### 接口定义

```typescript
interface TaskState {
  status: 'idle' | 'running' | 'paused' | 'completed' | 'failed';
  current_layer: number | null;
  previous_layer: number | null;
  pending_review_layer: number | null;
  layer_1_completed: boolean;
  layer_2_completed: boolean;
  layer_3_completed: boolean;
  pause_after_step: boolean;
  execution_complete: boolean;
}

interface TaskControllerActions {
  approve: () => Promise<void>;
  reject: (feedback: string) => Promise<void>;
  rollback: (checkpointId: string) => Promise<void>;
}
```

### REST 轮询实现

```typescript
export function useTaskController(taskId: string | null, callbacks) {
  const [state, setState] = useState<TaskState>({...});
  
  // 状态获取函数
  const fetchStatus = useCallback(async () => {
    if (!taskId) return false;
    
    const statusData = await planningApi.getStatus(taskId);
    
    // 直接同步状态 (不做任何判断)
    setState({
      status: statusData.status,
      pause_after_step: statusData.pause_after_step,
      previous_layer: statusData.previous_layer,
      pending_review_layer: statusData.pending_review_layer,
      layer_1_completed: statusData.layer_1_completed,
      layer_2_completed: statusData.layer_2_completed,
      layer_3_completed: statusData.layer_3_completed,
      ...
    });
    
    // 只有 execution_complete=true 时才停止轮询
    return statusData.execution_complete;
  }, [taskId]);
  
  // 轮询循环
  useEffect(() => {
    if (!taskId) return;
    
    const pollLoop = async () => {
      const shouldStop = await fetchStatus();
      if (!shouldStop) {
        pollTimerRef.current = setTimeout(pollLoop, 2000);
      }
    };
    
    pollLoop();
    
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, [taskId, fetchStatus]);
  
  return [state, actions];
}
```

### SSE 连接管理

```typescript
useEffect(() => {
  // 暂停时不需要 SSE，批准后需要重新连接
  const shouldConnectSSE = !state.execution_complete && !state.pause_after_step;
  
  if (shouldConnectSSE) {
    const es = planningApi.createStream(taskId, (event) => {
      if (event.type === 'dimension_delta') {
        callbacks.onDimensionDelta?.(event.data);
      } else if (event.type === 'layer_completed') {
        callbacks.onLayerCompleted?.(event.data);
      }
      // ... 其他事件
    });
    
    sseConnectionRef.current = es;
  } else {
    // 关闭连接
    sseConnectionRef.current?.close();
  }
}, [taskId, state.pause_after_step, state.execution_complete]);
```

### Action 方法

```typescript
const actions: TaskControllerActions = {
  approve: async () => {
    await planningApi.approveReview(taskId);
  },
  
  reject: async (feedback: string) => {
    await planningApi.rejectReview(taskId, feedback);
  },
  
  rollback: async (checkpointId: string) => {
    await planningApi.rollbackCheckpoint(taskId, checkpointId);
  },
};
```

---

## 数据流

### 完整数据流

```
用户点击"开始规划"
  ↓
UnifiedPlanningContext.startPlanning()
  ↓
POST /api/planning/start
  ↓
返回 {task_id, status}
  ↓
TaskController 开始轮询 + SSE 连接
  ↓
┌─────────────────────────────────────┐
│ REST 轮询 (每 2 秒)                  │
│   GET /api/planning/status/{id}     │
│   ↓                                 │
│   syncBackendState(statusData)      │
│   ↓                                 │
│   更新 Context 状态                  │
│   ↓                                 │
│   UI 重新渲染                        │
└─────────────────────────────────────┘
┌─────────────────────────────────────┐
│ SSE 流式                            │
│   dimension_delta → 更新维度内容     │
│   layer_completed → 添加消息         │
│   pause → 触发暂停处理               │
└─────────────────────────────────────┘
```

### 暂停/恢复流程

```
后端: 层级完成 + 步进模式
  ↓
route_after_pause() 返回 "end"
  ↓
前端 REST 轮询获取到:
  pause_after_step = true
  previous_layer = 1
  ↓
syncBackendState() 更新 Context:
  isPaused = true
  pendingReviewLayer = 1
  ↓
ChatPanel 条件渲染:
  {isPaused && pendingReviewLayer && <ReviewPanel />}
  ↓
用户点击"批准"
  ↓
handleReviewApprove()
  ↓
approve() → POST /api/planning/review?action=approve
  ↓
后端清除暂停标志，恢复执行
  ↓
前端轮询检测到:
  pause_after_step = false
  ↓
syncBackendState():
  isPaused = false
  ↓
ReviewPanel 自动消失
```

---

## 核心组件

### ChatPanel

**文件**: `components/chat/ChatPanel.tsx`

主聊天界面组件。

**核心功能**:
- 消息列表渲染
- 条件渲染审查面板
- 维度内容流式显示

**状态同步**:

```typescript
// 从 TaskController 同步状态到 Context
useEffect(() => {
  if (!taskId) return;
  syncBackendState(taskState);
}, [taskId, taskState, syncBackendState]);
```

**审查面板条件渲染**:

```typescript
// 直接从 Context 读取状态
const { isPaused, pendingReviewLayer } = useUnifiedPlanningContext();

// 条件渲染
{isPaused && pendingReviewLayer && (
  <ReviewPanel
    layer={pendingReviewLayer}
    onApprove={handleReviewApprove}
    onReject={handleReviewReject}
    onRollback={handleRollback}
  />
)}
```

### ReviewPanel

**文件**: `components/chat/ReviewPanel.tsx`

审查面板组件，提供批准/驳回/回退操作。

**Props**:

```typescript
interface ReviewPanelProps {
  layer: number;                          // 待审查层级
  onApprove: () => Promise<void>;         // 批准回调
  onReject: (feedback: string) => Promise<void>;  // 驳回回调
  onRollback: (checkpointId: string) => Promise<void>;  // 回退回调
  isSubmitting?: boolean;                 // 提交中状态
}
```

### MessageList

**文件**: `components/chat/MessageList.tsx`

消息列表组件，支持多种消息类型渲染。

**消息类型**:
- `text`: 文本消息
- `layer_completed`: 层级完成消息
- `review_interaction`: 审查交互消息
- `progress`: 进度消息
- `error`: 错误消息

---

## 类型系统

### 核心类型

```typescript
// 任务状态
type Status = 'idle' | 'collecting' | 'planning' | 'paused' | 
              'reviewing' | 'revising' | 'completed' | 'failed';

// 消息类型
type MessageType = 'text' | 'layer_completed' | 'review_interaction' | 
                   'progress' | 'error' | 'file';

// 层级完成消息
interface LayerCompletedMessage extends Message {
  type: 'layer_completed';
  layer: number;
  content: string;
  fullReportContent: string;
  dimensionReports: Record<string, string>;
  summary: {
    word_count: number;
    dimension_count: number;
  };
}

// 审查交互消息
interface ReviewInteractionMessage extends Message {
  type: 'review_interaction';
  layer: number;
  reviewState: 'pending' | 'approved' | 'rejected';
  availableActions: Array<'approve' | 'reject' | 'rollback'>;
}
```

---

## 性能优化

### 1. 状态变化检测

使用 `useRef` 跟踪之前状态，避免不必要的更新：

```typescript
const previousBackendStateRef = useRef<any>(null);

const hasStateChanged = !previousState ||
  previousState.pause_after_step !== backendData.pause_after_step;

if (!hasStateChanged) return;
```

### 2. 稳定回调引用

使用 `useCallback` 和 `useMemo` 稳定回调引用：

```typescript
const callbacks = useMemo(() => ({
  onDimensionDelta: handleDimensionDelta,
  onLayerCompleted: handleLayerCompleted,
}), [handleDimensionDelta, handleLayerCompleted]);
```

### 3. 批处理渲染

`useStreamingRender` Hook 实现维度内容批处理渲染：

```typescript
const { addToken, completeDimension } = useStreamingRender(
  (dimensionKey, content) => {
    // 批量更新维度内容
  },
  { batchSize: 10, batchWindow: 50 }
);
```
