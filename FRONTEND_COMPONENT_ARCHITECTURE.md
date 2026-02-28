# 前端组件架构文档

> Next.js 14 组件架构 - 后端状态驱动

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                         Page Layer                           │
│  app/page.tsx (首页)  app/village/[taskId]/page.tsx          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Context Layer                           │
│  UnifiedPlanningContext (全局状态管理)                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Controller Layer                          │
│  TaskController (REST轮询 + SSE文本流)                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Component Layer                           │
│  Layout: UnifiedLayout, Header, HistoryPanel                │
│  Chat: ChatPanel, MessageList, ReviewPanel, ...             │
│  Form: VillageInputForm                                      │
│  Report: KnowledgeReference                                  │
└─────────────────────────────────────────────────────────────┘
```

## 核心原则：后端状态为单一真实源

前端不存储业务逻辑状态，所有关键状态从后端同步：

```
后端状态                    →    前端派生状态
────────────────────────────────────────────────
status: 'paused'            →    isPaused: true
previous_layer: 1           →    pendingReviewLayer: 1
layer_1_completed: true     →    completedLayers[1]: true
execution_complete: true    →    停止轮询
```

## 数据流

### REST 状态同步

```
Backend State → TaskController.fetchStatus() 
            → ChatPanel.syncBackendState() 
            → UnifiedPlanningContext 
            → UI 渲染

轮询间隔: 2秒
```

### SSE 流式事件

```
连接条件: !execution_complete && !pause_after_step

事件类型:
  - content_delta: 文本增量
  - dimension_delta: 维度增量
  - dimension_complete: 维度完成
  - error: 错误信息
```

## 组件详情

### Layout 组件

| 组件 | 功能 |
|------|------|
| UnifiedLayout | 主布局容器 |
| Header | 顶部导航栏 |
| HistoryPanel | 历史记录面板 |
| UnifiedContentSwitcher | 内容切换器 |

### Chat 组件

| 组件 | 功能 |
|------|------|
| ChatPanel | 主聊天面板 |
| MessageList | 消息列表 |
| MessageBubble | 消息气泡 |
| MessageContent | 消息内容渲染 |
| ReviewPanel | 审查面板 |
| LayerReportMessage | 层级完成消息 |
| LayerReportCard | 层级报告卡片 |
| DimensionSection | 维度卡片 |
| DimensionReportStreaming | 流式维度报告 |
| DimensionSelector | 维度选择器 |
| StreamingText | 流式文本 |
| ThinkingIndicator | 思考指示器 |
| ActionButtonGroup | 操作按钮组 |

### Form 组件

| 组件 | 功能 |
|------|------|
| VillageInputForm | 村庄信息输入表单 |

### Report 组件

| 组件 | 功能 |
|------|------|
| KnowledgeReference | RAG 知识引用显示 |

### UI 组件

| 组件 | 功能 |
|------|------|
| Card | 卡片组件 |
| SegmentedControl | 分段控制器 |

## Context 状态管理

### UnifiedPlanningContext

```typescript
interface PlanningState {
  // 任务状态
  taskId: string | null;
  status: Status;  // idle|planning|paused|completed|failed
  
  // 审查状态 (从后端同步)
  isPaused: boolean;
  pendingReviewLayer: number | null;
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  
  // 视图状态
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  
  // 历史状态
  villages: VillageInfo[];
  checkpoints: Checkpoint[];
}

// 核心方法
syncBackendState(backendData)  // 同步后端状态
startPlanning(params)          // 启动规划
approve/reject/rollback        // 审查操作
```

## Controller 层

### TaskController

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

// 返回 actions
actions.approve()   // 批准审查
actions.reject()    // 驳回审查
actions.rollback()  // 回退检查点
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
| `types/message.ts` | 消息类型定义 |
| `components/chat/ChatPanel.tsx` | 主界面容器 |
| `components/chat/ReviewPanel.tsx` | 审查面板 |
| `components/layout/UnifiedLayout.tsx` | 主布局 |