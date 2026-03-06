# 前端实现文档

> Next.js 14 前端架构 - 单一状态源、后端驱动

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Page Layer (App Router)                         │
│  app/page.tsx (首页)  app/village/[taskId]/page.tsx (任务详情)       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Context Layer                                   │
│  UnifiedPlanningContext (全局状态) ← TaskController (状态同步)       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Component Layer                                   │
│  Layout: UnifiedLayout, Header, HistoryPanel, KnowledgePanel        │
│  Chat: ChatPanel, MessageList, ReviewPanel, LayerReportMessage      │
│  Form: VillageInputForm                                              │
└─────────────────────────────────────────────────────────────────────┘
```

## 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Next.js | 14.2.0 | React 框架 |
| React | 18.3.0 | UI 库 |
| TypeScript | 5.x | 类型安全 |
| Tailwind CSS | 4.2.1 | 实用类 |
| Framer Motion | 12.32.0 | 动画库 |
| react-markdown | 9.0.0 | Markdown 渲染 |

## 核心原则：单一状态源

前端不存储独立业务状态，所有状态从后端 LangGraph Checkpointer 同步：

```
后端状态 (Checkpointer)        →    前端派生状态
────────────────────────────────────────────────
status: 'paused'               →    isPaused: true
previous_layer: 1              →    pendingReviewLayer: 1
layer_1_completed: true        →    completedLayers[1]: true
execution_complete: true       →    停止轮询
```

## 状态同步机制

### REST 轮询 (每2秒)

```typescript
// controllers/TaskController.tsx
const pollLoop = async () => {
  const shouldStop = await fetchStatus();
  if (!shouldStop && taskId) {
    pollTimerRef.current = setTimeout(pollLoop, 2000);
  }
};
```

### SSE 实时事件

```typescript
// 事件类型
type PlanningSSEEventType =
  | 'layer_started'      // 层级开始
  | 'layer_completed'    // 层级完成
  | 'dimension_delta'    // 维度Token增量
  | 'dimension_complete' // 维度完成
  | 'dimension_revised'  // 维度修复完成
  | 'pause'              // 暂停
  | 'error';             // 错误
```

## 目录结构

```
frontend/src/
├── app/                        # 页面路由
│   ├── page.tsx                # 首页
│   └── village/[taskId]/       # 任务详情页
├── contexts/
│   └── UnifiedPlanningContext.tsx  # 全局状态
├── controllers/
│   └── TaskController.tsx      # 状态同步控制器
├── components/
│   ├── layout/                 # 布局组件
│   │   ├── UnifiedLayout.tsx
│   │   ├── UnifiedContentSwitcher.tsx
│   │   ├── Header.tsx
│   │   ├── HistoryPanel.tsx
│   │   └── KnowledgePanel.tsx
│   ├── chat/                   # 聊天组件
│   │   ├── ChatPanel.tsx
│   │   ├── MessageList.tsx
│   │   ├── MessageBubble.tsx
│   │   ├── ReviewPanel.tsx
│   │   ├── LayerReportMessage.tsx
│   │   ├── DimensionReportStreaming.tsx
│   │   └── DimensionSelector.tsx
│   ├── ui/                     # 通用UI组件
│   └── VillageInputForm.tsx    # 输入表单
├── hooks/
│   ├── useTaskSSE.ts           # SSE连接管理
│   ├── useStreamingRender.ts   # 流式渲染批处理
│   └── useStreamingText.ts     # 文本流式渲染
├── lib/
│   └── api.ts                  # API客户端
├── config/
│   ├── dimensions.ts           # 维度配置
│   └── planning.ts             # 规划配置
└── types/                      # 类型定义
    ├── message.ts
    └── message-types.ts
```

## Context 状态管理

### UnifiedPlanningContext

```typescript
interface PlanningState {
  // 任务标识
  taskId: string | null;
  projectName: string | null;
  
  // 状态 (从后端同步)
  status: Status;  // idle|collecting|planning|paused|completed|failed
  
  // 视图状态
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  
  // 审查状态
  isPaused: boolean;              // = status === 'paused'
  pendingReviewLayer: number | null;  // = previous_layer
  
  // 层级完成状态
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  
  // 消息历史
  messages: Message[];
  
  // 历史数据
  villages: VillageInfo[];
  selectedSession: VillageSession | null;
}
```

### 状态同步方法

```typescript
// syncBackendState - 从REST轮询同步
const syncBackendState = useCallback((backendData: any) => {
  setStatusState(backendData.status);
  setIsPaused(backendData.status === 'paused');
  setPendingReviewLayer(backendData.previous_layer);
  
  // 只在会话结束/暂停时同步层级状态
  if (['idle', 'completed', 'failed', 'paused'].includes(backendData.status)) {
    setCompletedLayers({
      1: backendData.layer_1_completed || false,
      2: backendData.layer_2_completed || false,
      3: backendData.layer_3_completed || false,
    });
  }
}, []);

// setUILayerCompleted - SSE驱动更新
const setUILayerCompleted = useCallback((layer: number, completed: boolean) => {
  setCompletedLayers(prev => ({ ...prev, [layer]: completed }));
}, []);
```

## 组件层次

### 组件树

```
App (page.tsx)
  │
  ├── UnifiedPlanningProvider (Context)
  │
  └── UnifiedLayout
         │
         ├── Header (导航栏)
         │      ├── Logo
         │      ├── 新建规划按钮
         │      ├── 历史记录按钮
         │      └── 知识库按钮
         │
         └── UnifiedContentSwitcher
                │
                ├── [WELCOME_FORM] → VillageInputForm
                │
                └── [SESSION_ACTIVE] → ChatPanel
                       │
                       ├── useTaskSSE (SSE连接)
                       │
                       ├── MessageList
                       │      └── MessageBubble
                       │             └── MessageContent
                       │                    ├── TextMessage
                       │                    ├── LayerReportMessage
                       │                    └── DimensionReportStreaming
                       │
                       └── ReviewPanel (条件渲染)
```

### 核心组件

| 组件 | 文件 | 功能 |
|------|------|------|
| UnifiedLayout | layout/UnifiedLayout.tsx | 主布局容器 |
| UnifiedContentSwitcher | layout/UnifiedContentSwitcher.tsx | 视图切换 |
| ChatPanel | chat/ChatPanel.tsx | 主聊天面板 |
| MessageList | chat/MessageList.tsx | 消息列表渲染 |
| ReviewPanel | chat/ReviewPanel.tsx | 审查面板 |
| LayerReportMessage | chat/LayerReportMessage.tsx | 层级完成消息 |
| DimensionReportStreaming | chat/DimensionReportStreaming.tsx | 维度流式报告 |

## 消息类型

| 类型 | 说明 | 关键字段 |
|------|------|----------|
| `text` | 普通文本 | content, streamingState |
| `layer_completed` | 层级完成 | layer, fullReportContent, dimensionReports |
| `dimension_report` | 维度报告 | layer, dimensionKey, streamingState |
| `dimension_revised` | 维度修复 | layer, dimensionKey, oldContent, newContent |
| `progress` | 进度更新 | progress, currentLayer |
| `error` | 错误 | content, error |

## API 客户端

```typescript
// lib/api.ts

// Planning API
planningApi.startPlanning(request)           // POST /start
planningApi.createStream(sessionId, onEvent) // GET /stream (SSE)
planningApi.getStatus(sessionId)             // GET /status
planningApi.approveReview(sessionId)         // POST /review (approve)
planningApi.rejectReview(sessionId, feedback, dimensions)  // POST /review (reject)

// Data API
dataApi.listVillages()                       // GET /villages
dataApi.getLayerContent(villageName, layerId)  // GET 层级内容
dataApi.getCheckpoints(villageName)          // GET 检查点

// Knowledge API
knowledgeApi.listDocuments()                 // GET /documents
knowledgeApi.addDocument(file)               // POST /documents
```

## Hooks

| Hook | 功能 |
|------|------|
| useTaskSSE | SSE 连接管理、事件处理、重试机制 |
| useStreamingRender | 批处理流式渲染 (RAF + 防抖) |
| useStreamingText | 流式文本渲染动画 |

## 条件渲染

```typescript
// 视图模式切换
{viewMode === 'WELCOME_FORM' && <VillageInputForm />}
{viewMode === 'SESSION_ACTIVE' && <ChatPanel />}

// ReviewPanel 显示
{isPaused && pendingReviewLayer && (
  <ReviewPanel 
    layer={pendingReviewLayer}
    onApprove={() => planningApi.approveReview(taskId)}
    onReject={(feedback, dimensions) => 
      planningApi.rejectReview(taskId, feedback, dimensions)
    }
  />
)}

// 消息类型渲染
switch (message.type) {
  case 'layer_completed': return <LayerReportMessage message={message} />;
  case 'dimension_report': return <DimensionReportStreaming message={message} />;
  default: return <TextMessage message={message} />;
}
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `contexts/UnifiedPlanningContext.tsx` | 全局状态管理 |
| `controllers/TaskController.tsx` | REST轮询 + SSE事件处理 |
| `lib/api.ts` | API客户端封装 |
| `config/dimensions.ts` | 28个维度配置 |
| `types/message-types.ts` | 消息类型定义 |
| `hooks/useTaskSSE.ts` | SSE连接管理 |
| `components/chat/ChatPanel.tsx` | 主界面容器 |
| `components/chat/ReviewPanel.tsx` | 审查面板 |