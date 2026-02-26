# 前端实现文档

> Next.js 14 前端架构 - 后端状态驱动、单一真实源

## 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Page (app/page.tsx)                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  UnifiedPlanningProvider                     │
│                  (contexts/UnifiedPlanningContext.tsx)       │
│                                                             │
│  状态: taskId, status, isPaused, pendingReviewLayer         │
│  方法: syncBackendState(), startPlanning()                  │
└─────────────────────────────────────────────────────────────┘
         ┌─────────────────┬─────────────────┐
         ▼                 ▼                 ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│UnifiedLayout │   │ ChatPanel    │   │ HistoryPanel │
└──────────────┘   └──────┬───────┘   └──────────────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │MessageList   │ │TaskController│ │ReviewPanel   │
  │              │ │(REST轮询+SSE)│ │(条件渲染)    │
  └──────────────┘ └──────────────┘ └──────────────┘
```

## 核心原则：后端状态为单一真实源

前端不存储业务逻辑状态，所有关键状态从后端同步：

```
后端状态                          前端派生状态
─────────────────────────────────────────────────────
status: 'paused'         →      isPaused: true
previous_layer: 1        →      pendingReviewLayer: 1
layer_1_completed: true  →      completedLayers[1]: true
execution_complete: true →      停止轮询
```

## 数据流

### REST 状态同步 (每2秒)

```
┌──────────────────────────────────────────────────────────────┐
│                     Backend                                   │
│  AsyncSqliteSaver → checkpoints 表                           │
│  _sessions 内存 → 运行时状态                                  │
└──────────────────────────────────────────────────────────────┘
                          │
                GET /api/planning/status/{id}
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                   TaskController                              │
│                                                              │
│  const fetchStatus = async () => {                           │
│    const statusData = await planningApi.getStatus(taskId);   │
│    setState({                                                │
│      status: statusData.status,                              │
│      pause_after_step: statusData.pause_after_step,          │
│      previous_layer: statusData.previous_layer,              │
│      layer_X_completed: statusData.layer_X_completed,        │
│    });                                                       │
│    return statusData.execution_complete;                     │
│  }                                                           │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                   ChatPanel                                   │
│                                                              │
│  useEffect(() => {                                           │
│    if (taskId) syncBackendState(taskState);                  │
│  }, [taskId, taskState]);                                    │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│               UnifiedPlanningContext                          │
│                                                              │
│  syncBackendState(backendData) {                             │
│    setStatus(backendData.status);                            │
│    setIsPaused(backendData.status === 'paused');             │
│    setPendingReviewLayer(backendData.previous_layer);        │
│    setCompletedLayers({                                      │
│      1: backendData.layer_1_completed,                       │
│      2: backendData.layer_2_completed,                       │
│      3: backendData.layer_3_completed,                       │
│    });                                                       │
│  }                                                           │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                     UI 渲染                                   │
│                                                              │
│  {isPaused && pendingReviewLayer && (                        │
│    <ReviewPanel layer={pendingReviewLayer} />                │
│  )}                                                          │
└──────────────────────────────────────────────────────────────┘
```

### SSE 流式文本

```
TaskController SSE 连接条件:
  !execution_complete && !pause_after_step

事件类型:
  - dimension_delta: 维度增量文本
  - layer_completed: 层级完成
  - pause: 暂停等待审查

处理流程:
┌─────────────────────────────────────────┐
│ planningApi.createStream(taskId)        │
│     │                                   │
│     ▼ event: dimension_delta            │
│ onDimensionDelta(key, delta, accumulated)│
│     │                                   │
│     ▼ 实时更新维度内容显示              │
└─────────────────────────────────────────┘
```

### 审查操作流程

```
用户点击"批准"
      │
      ▼
TaskController.approve()
      │
      ▼
POST /api/planning/review?action=approve
      │
      ▼
后端处理:
  - pause_after_step = false
  - previous_layer = 0
  - 启动后台任务继续执行
      │
      ▼
REST轮询检测 (2秒后):
  status: 'running'
  pause_after_step: false
      │
      ▼
syncBackendState():
  isPaused = false
      │
      ▼
ReviewPanel 消失 (条件渲染)
```

## 核心组件

### UnifiedPlanningContext

**职责**: 全局状态容器，同步后端状态

```typescript
interface PlanningState {
  // 任务标识
  taskId: string | null;
  projectName: string | null;
  status: Status;  // idle|collecting|planning|paused|completed|failed
  
  // 审查状态 (从后端同步)
  isPaused: boolean;              // = status === 'paused'
  pendingReviewLayer: number | null;  // = previous_layer
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  
  // 历史
  villages: Village[];
  selectedVillage: Village | null;
}

// 核心方法
syncBackendState(backendData) {
  setStatus(backendData.status);
  setIsPaused(backendData.status === 'paused');
  setPendingReviewLayer(backendData.previous_layer);
  setCompletedLayers({
    1: backendData.layer_1_completed,
    2: backendData.layer_2_completed,
    3: backendData.layer_3_completed,
  });
}
```

### TaskController

**职责**: REST 轮询 + SSE 管理 (无头组件)

```typescript
interface TaskState {
  status: Status;
  pause_after_step: boolean;
  previous_layer: number | null;
  layer_1_completed: boolean;
  layer_2_completed: boolean;
  layer_3_completed: boolean;
  execution_complete: boolean;
}

function useTaskController(taskId, callbacks): [TaskState, TaskActions]

// REST 轮询 (每2秒)
useEffect(() => {
  const pollLoop = async () => {
    const shouldStop = await fetchStatus();
    if (!shouldStop) setTimeout(pollLoop, 2000);
  };
  if (taskId) pollLoop();
}, [taskId]);

// SSE 连接条件
const shouldConnectSSE = !execution_complete && !pause_after_step;
```

### ChatPanel

**职责**: 主界面容器

```typescript
export default function ChatPanel() {
  const { syncBackendState, isPaused, pendingReviewLayer } = useContext();
  const [taskState, actions] = useTaskController(taskId, callbacks);
  
  // 同步后端状态
  useEffect(() => {
    if (taskId) syncBackendState(taskState);
  }, [taskId, taskState]);
  
  return (
    <div>
      <ProgressHeader />
      <MessageList messages={messages} />
      {isPaused && pendingReviewLayer && (
        <ReviewPanel layer={pendingReviewLayer} {...actions} />
      )}
    </div>
  );
}
```

## 组件层级

### Layout 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| UnifiedLayout | layout/UnifiedLayout.tsx | 主布局容器 |
| Header | layout/Header.tsx | 顶部导航栏 |
| HistoryPanel | layout/HistoryPanel.tsx | 历史记录抽屉 |

### Chat 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| ChatPanel | chat/ChatPanel.tsx | 主界面容器 |
| MessageList | chat/MessageList.tsx | 消息列表 |
| MessageBubble | chat/MessageBubble.tsx | 消息气泡 |
| LayerReportMessage | chat/LayerReportMessage.tsx | 层级完成消息 |
| ReviewPanel | chat/ReviewPanel.tsx | 审查操作面板 |

## API 客户端

**文件**: `lib/api.ts`

```typescript
planningApi: {
  startPlanning(request)           // POST /api/planning/start
  createStream(sessionId)          // GET /api/planning/stream (SSE)
  getStatus(sessionId)             // GET /api/planning/status
  approveReview(sessionId)         // POST /api/planning/review?action=approve
  rejectReview(sessionId, feedback)
  rollbackCheckpoint(sessionId, checkpointId)
}

dataApi: {
  listVillages()                   // GET /api/data/villages
  getVillageSessions(name)         // GET /api/data/villages/{name}/sessions
  getLayerContent(name, layer)     // GET /api/data/villages/{name}/layers/{layer}
}
```

## 条件渲染

```typescript
// ReviewPanel 显示逻辑
{isPaused && pendingReviewLayer && (
  <ReviewPanel layer={pendingReviewLayer} onApprove={...} onReject={...} />
)}

// 消息类型渲染
switch (message.type) {
  case 'layer_completed': return <LayerReportMessage />;
  case 'review_interaction': return <ReviewInteractionMessage />;
  default: return <TextMessage />;
}
```

## 性能优化

1. **状态变化检测**: useRef 跟踪前状态，避免不必要更新
2. **稳定回调引用**: useCallback + useMemo
3. **条件渲染**: 状态驱动，无冗余计算

## 关键文件索引

| 文件 | 功能 |
|------|------|
| contexts/UnifiedPlanningContext.tsx | 全局状态管理 |
| controllers/TaskController.tsx | REST轮询+SSE管理 |
| components/chat/ChatPanel.tsx | 主界面容器 |
| components/chat/ReviewPanel.tsx | 审查面板 |
| lib/api.ts | API 客户端 |
