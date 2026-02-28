# 前端实现文档

> Next.js 14 前端架构 - 后端状态驱动、单一真实源

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                      Page (app/page.tsx)                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  UnifiedPlanningProvider                     │
│              contexts/UnifiedPlanningContext.tsx             │
│  状态: taskId, status, isPaused, pendingReviewLayer         │
└─────────────────────────────────────────────────────────────┘
         ┌─────────────────┬─────────────────┐
         ▼                 ▼                 ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│UnifiedLayout │   │  ChatPanel   │   │ HistoryPanel │
└──────────────┘   └──────┬───────┘   └──────────────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │ MessageList  │ │TaskController│ │ ReviewPanel  │
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

### REST 状态同步 (每2秒轮询)

```
Backend State (SQLite + LangGraph checkpoint)
                    │
          GET /api/planning/status/{id}
                    │
                    ▼
            TaskController
          fetchStatus() → setState
                    │
                    ▼
              ChatPanel
         syncBackendState(taskState)
                    │
                    ▼
        UnifiedPlanningContext
     isPaused = (status === 'paused')
     pendingReviewLayer = previous_layer
                    │
                    ▼
              UI 条件渲染
      {isPaused && <ReviewPanel />}
```

### SSE 流式事件

```
TaskController SSE 连接条件:
  !execution_complete && !pause_after_step

事件类型:
  - content_delta: 文本增量
  - dimension_delta: 维度增量文本
  - dimension_complete: 维度完成
  - error: 错误信息
```

### 审查操作流程

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
ReviewPanel 消失
```

## 组件层级

### Layout 组件

| 组件 | 功能 |
|------|------|
| UnifiedLayout | 主布局容器：Header + 主内容区 |
| Header | 顶部导航栏：Logo + 新建按钮 + 历史按钮 |
| HistoryPanel | 历史记录面板：村庄列表 + 会话列表 |
| UnifiedContentSwitcher | 内容切换器：表单或聊天界面 |

### Chat 组件

| 组件 | 功能 |
|------|------|
| ChatPanel | 主界面容器，协调状态同步 |
| MessageList | 消息列表渲染 |
| MessageBubble | 消息气泡 |
| MessageContent | 消息内容渲染器 |
| ReviewPanel | 审查面板：批准/驳回 |
| LayerReportMessage | 层级完成消息 |
| LayerReportCard | 层级报告卡片 |
| DimensionSection | 单个维度卡片 |
| DimensionReportStreaming | 流式维度报告 |
| StreamingText | 流式文本显示 |
| ThinkingIndicator | 思考状态指示器 |
| DimensionSelector | 维度选择器 |

### Form 组件

| 组件 | 功能 |
|------|------|
| VillageInputForm | 村庄数据输入表单 |

## 核心组件详解

### UnifiedPlanningContext

**文件**: `contexts/UnifiedPlanningContext.tsx`

```typescript
interface PlanningState {
  taskId: string | null;
  status: Status;  // idle|planning|paused|completed|failed
  isPaused: boolean;              // = status === 'paused'
  pendingReviewLayer: number | null;  // = previous_layer
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  villages: VillageInfo[];
  checkpoints: Checkpoint[];
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

职责: REST 轮询 + SSE 管理

```typescript
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

## Hooks

| Hook | 功能 |
|------|------|
| useStreamingRender | 批处理渲染 |
| useStreamingText | 流式文本输出 |

## Types 类型定义

```typescript
// 核心消息类型
type Message =
  | TextMessage
  | FileMessage
  | ProgressMessage
  | LayerCompletedMessage
  | DimensionReportMessage
  | ErrorMessage

// 层级完成消息
interface LayerCompletedMessage {
  type: 'layer_completed'
  layer: number
  content: string
  dimensionReports?: Record<string, string>
}
```

## API 客户端

**文件**: `lib/api.ts`

```typescript
planningApi: {
  startPlanning(request)           // POST /api/planning/start
  createStream(sessionId)          // GET /api/planning/stream (SSE)
  getStatus(sessionId)             // GET /api/planning/status
  approveReview(sessionId)         // POST /api/planning/review
  rejectReview(sessionId, feedback)
  rollbackCheckpoint(sessionId, checkpointId)
}

dataApi: {
  listVillages()                   // GET /api/data/villages
  getLayerContent(name, layer)     // GET /api/data/villages/{name}/layers/{layer}
}

fileApi: {
  uploadFile(file)                 // POST /api/files/upload
}
```

## 条件渲染

```typescript
// 视图模式切换
{viewMode === 'WELCOME_FORM' && <VillageInputForm />}
{viewMode === 'SESSION_ACTIVE' && <ChatPanel />}

// ReviewPanel 显示
{isPaused && pendingReviewLayer && (
  <ReviewPanel layer={pendingReviewLayer} />
)}

// 消息类型渲染
switch (message.type) {
  case 'layer_completed': return <LayerReportMessage />;
  case 'dimension_report': return <DimensionReportStreaming />;
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
| `components/chat/ChatPanel.tsx` | 主界面容器 |
| `components/chat/ReviewPanel.tsx` | 审查面板 |
| `components/layout/UnifiedLayout.tsx` | 主布局 |