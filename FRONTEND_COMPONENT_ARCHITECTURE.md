# 前端组件架构文档

> Next.js 14 组件架构 - 后端状态驱动

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                         Page (app/page.tsx)                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   UnifiedPlanningProvider                    │
│                   (contexts/UnifiedPlanningContext.tsx)      │
│                                                             │
│  状态: taskId, status, isPaused, pendingReviewLayer         │
│  方法: syncBackendState(), startPlanning()                  │
└─────────────────────────────────────────────────────────────┘
         ┌──────────────────┬──────────────────┐
         ▼                  ▼                  ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│UnifiedLayout │   │  ChatPanel   │   │ HistoryPanel │
│ (Header+Main)│   │  (主界面)    │   │ (历史抽屉)   │
└──────────────┘   └──────┬───────┘   └──────────────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │MessageList   │ │TaskController│ │ReviewPanel   │
  │              │ │(REST轮询+SSE)│ │(条件渲染)    │
  └──────────────┘ └──────────────┘ └──────────────┘
```

## 核心原则

### 后端状态为单一真实源

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

### 1. REST 状态同步 (每2秒)

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
| ChatPanel | chat/ChatPanel.tsx | 主界面容器，协调状态同步 |
| MessageList | chat/MessageList.tsx | 消息列表渲染 |
| MessageBubble | chat/MessageBubble.tsx | 消息气泡样式 |
| MessageContent | chat/MessageContent.tsx | 消息内容渲染分发 |
| StreamingText | chat/StreamingText.tsx | 流式文本显示 |
| ThinkingIndicator | chat/ThinkingIndicator.tsx | 思考中指示器 |
| LayerReportCard | chat/LayerReportCard.tsx | 层级报告卡片 |
| DimensionSection | chat/DimensionSection.tsx | 维度内容显示 |
| ReviewPanel | chat/ReviewPanel.tsx | 审查操作面板 |

### UI 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| Card | ui/Card.tsx | 卡片容器 |
| SegmentedControl | ui/SegmentedControl.tsx | 分段控制器 |

### Form 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| VillageInputForm | VillageInputForm.tsx | 村庄数据输入表单 |

## 核心组件详解

### UnifiedPlanningContext

**职责**: 全局状态容器

```typescript
interface PlanningState {
  // 任务标识
  taskId: string | null;
  projectName: string | null;
  status: Status;
  
  // 审查状态 (从后端同步)
  isPaused: boolean;
  pendingReviewLayer: number | null;
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  
  // 视图模式
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  
  // 历史
  villages: VillageInfo[];
  selectedVillage: VillageInfo | null;
}
```

### TaskController

**职责**: REST 轮询 + SSE 管理

```typescript
interface TaskState {
  status: Status;
  pause_after_step: boolean;
  previous_layer: number | null;
  layer_X_completed: boolean;
  execution_complete: boolean;
}

// 轮询条件
useEffect(() => {
  if (taskId && !execution_complete) {
    const interval = setInterval(fetchStatus, 2000);
    return () => clearInterval(interval);
  }
}, [taskId, execution_complete]);

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

## API 客户端

**文件**: `lib/api.ts`

```typescript
// Planning API
planningApi: {
  startPlanning(request)           // POST /api/planning/start
  createStream(sessionId)          // GET /api/planning/stream (SSE)
  getStatus(sessionId)             // GET /api/planning/status
  approveReview(sessionId)         // POST /api/planning/review?action=approve
  rejectReview(sessionId, feedback)
  rollbackCheckpoint(sessionId, checkpointId)
}

// Data API
dataApi: {
  listVillages()                   // GET /api/data/villages
  getVillageSessions(name)         // GET /api/data/villages/{name}/sessions
  getLayerContent(name, layer)     // GET /api/data/villages/{name}/layers/{layer}
  getCheckpoints(name, session)    // GET /api/data/villages/{name}/checkpoints
}

// File API
fileApi: {
  uploadFile(file)                 // POST /api/files/upload
}
```

## 消息类型

```typescript
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

## 条件渲染

```typescript
// 视图模式切换
{viewMode === 'WELCOME_FORM' && <VillageInputForm />}
{viewMode === 'SESSION_ACTIVE' && <ChatInterface />}

// ReviewPanel 显示逻辑
{isPaused && pendingReviewLayer && (
  <ReviewPanel 
    layer={pendingReviewLayer} 
    onApprove={actions.approve} 
    onReject={actions.reject} 
  />
)}

// 消息类型渲染
switch (message.type) {
  case 'layer_completed': return <LayerReportMessage />;
  case 'review_interaction': return <ReviewInteractionMessage />;
  default: return <TextMessage />;
}
```

## 关键文件索引

| 文件 | 功能 |
|------|------|
| `contexts/UnifiedPlanningContext.tsx` | 全局状态管理 |
| `controllers/TaskController.tsx` | REST轮询+SSE管理 |
| `lib/api.ts` | API客户端 |
| `types/message.ts` | 类型定义 |
| `config/dimensions.ts` | 维度配置 |
| `components/chat/ChatPanel.tsx` | 主界面容器 |
| `components/chat/ReviewPanel.tsx` | 审查面板 |
| `components/chat/MessageList.tsx` | 消息列表 |
| `components/layout/UnifiedLayout.tsx` | 主布局 |