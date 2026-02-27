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
│(Header+Main) │   │ (主界面)     │   │ (历史抽屉)   │
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

前端不存储业务逻辑状态，所有关键状态从后端 `/api/planning/status` 同步：

```
后端状态                    →    前端派生状态
────────────────────────────────────────────────
status: 'paused'            →    isPaused: true
previous_layer: 1           →    pendingReviewLayer: 1
layer_1_completed: true     →    completedLayers[1]: true
execution_complete: true    →    停止轮询
```

## 数据流

### 1. REST 状态同步 (每2秒轮询)

```
┌──────────────────────────────────────────┐
│              Backend State               │
│  AsyncSqliteSaver + _sessions 内存       │
└──────────────────────────────────────────┘
                    │
          GET /api/planning/status/{id}
                    │
                    ▼
┌──────────────────────────────────────────┐
│            TaskController                │
│  fetchStatus() → setState(taskState)    │
└──────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────┐
│              ChatPanel                   │
│  useEffect → syncBackendState(taskState)│
└──────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────┐
│        UnifiedPlanningContext            │
│  isPaused = (status === 'paused')        │
│  pendingReviewLayer = previous_layer     │
└──────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────┐
│              UI 渲染                      │
│  {isPaused && <ReviewPanel />}           │
└──────────────────────────────────────────┘
```

### 2. SSE 流式事件

```
TaskController SSE 连接条件:
  !execution_complete && !pause_after_step

事件类型:
  - dimension_delta: 维度增量文本
  - layer_completed: 层级完成
  - pause: 暂停等待审查
  - completed: 执行完成
```

### 3. 审查操作流程

```
用户点击"批准"
      │
      ▼
POST /api/planning/review?action=approve
      │
      ▼
后端: 清除暂停标志，启动后台任务
      │
      ▼
REST轮询检测: status = 'running'
      │
      ▼
syncBackendState(): isPaused = false
      │
      ▼
ReviewPanel 消失 (条件渲染)
```

## 核心组件

### UnifiedPlanningContext

**文件**: `contexts/UnifiedPlanningContext.tsx`

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
  
  // 视图模式
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  
  // 历史
  villages: VillageInfo[];
  selectedVillage: VillageInfo | null;
  selectedSession: VillageSession | null;
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

**文件**: `controllers/TaskController.tsx`

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

**文件**: `components/chat/ChatPanel.tsx`

**职责**: 主界面容器，协调状态同步

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
| MessageContent | chat/MessageContent.tsx | 消息内容渲染 |
| StreamingText | chat/StreamingText.tsx | 流式文本显示 |
| LayerReportCard | chat/LayerReportCard.tsx | 层级报告卡片 |
| DimensionSection | chat/DimensionSection.tsx | 维度内容显示 |
| ReviewPanel | chat/ReviewPanel.tsx | 审查操作面板 |

### UI 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| Card | ui/Card.tsx | 卡片容器 |
| SegmentedControl | ui/SegmentedControl.tsx | 分段控制器 |

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
  getCheckpoints(name, session)    // GET /api/data/villages/{name}/checkpoints
}

fileApi: {
  uploadFile(file)                 // POST /api/files/upload
}
```

### API 响应格式

```typescript
interface APIResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
  request_id?: string;
}
```

### 重试机制

```typescript
const MAX_RETRIES = 3;
const INITIAL_RETRY_DELAY = 1000; // ms
const RETRY_BACKOFF_MULTIPLIER = 2;
```

## 条件渲染

```typescript
// ReviewPanel 显示逻辑
{isPaused && pendingReviewLayer && (
  <ReviewPanel 
    layer={pendingReviewLayer} 
    onApprove={actions.approve} 
    onReject={actions.reject} 
  />
)}

// 视图模式切换
{viewMode === 'WELCOME_FORM' && <VillageInputForm />}
{viewMode === 'SESSION_ACTIVE' && <ChatInterface />}
```

## 消息类型

```typescript
// types/message.ts
type MessageType = 
  | 'text'              // 普通文本
  | 'layer_completed'   // 层级完成
  | 'review_interaction' // 审查交互
  | 'error';            // 错误消息

interface Message {
  id: string;
  timestamp: Date;
  role: 'user' | 'assistant' | 'system';
  type: MessageType;
  content: string;
  layer?: number;
  summary?: {
    word_count: number;
    dimension_count?: number;
  };
  dimensionReports?: Record<string, string>;
  actions?: MessageAction[];
}
```

## 性能优化

1. **状态变化检测**: `useRef` 跟踪前状态，避免不必要更新
2. **稳定回调引用**: `useCallback` + `useMemo`
3. **条件渲染**: 状态驱动，无冗余计算

## 关键文件索引

| 文件 | 功能 |
|------|------|
| `contexts/UnifiedPlanningContext.tsx` | 全局状态管理 |
| `controllers/TaskController.tsx` | REST轮询+SSE管理 |
| `lib/api.ts` | API客户端 |
| `components/chat/ChatPanel.tsx` | 主界面容器 |
| `components/chat/ReviewPanel.tsx` | 审查面板 |
| `components/chat/MessageList.tsx` | 消息列表 |
| `components/layout/UnifiedLayout.tsx` | 主布局 |
| `config/dimensions.ts` | 维度配置 |
| `types/message.ts` | 类型定义 |