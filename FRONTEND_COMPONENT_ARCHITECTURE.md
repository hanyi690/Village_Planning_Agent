# 前端组件架构文档

> Next.js 14 组件架构 - 单一状态源、后端驱动

## 架构概览

### 组件树

```
App (page.tsx)
  │
  ├── UnifiedPlanningProvider (Context)
  │      ├── 状态: messages, status, taskId, isPaused
  │      ├── 历史: villages, sessions
  │      └── 同步: syncBackendState, setUILayerCompleted
  │
  └── UnifiedLayout
         │
         ├── Header (导航栏)
         │
         └── UnifiedContentSwitcher (视图切换)
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
                       │                    ├── DimensionReportStreaming
                       │                    └── DimensionRevisedMessage
                       │
                       └── ReviewPanel (条件渲染)
```

## 核心原则：单一状态源

```
后端状态 (Checkpointer)        →    前端派生状态
────────────────────────────────────────────────
status: 'paused'               →    isPaused: true
previous_layer: 1              →    pendingReviewLayer: 1
layer_1_completed: true        →    completedLayers[1]: true
execution_complete: true       →    停止轮询
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
│   ├── useTaskSSE.ts
│   ├── useStreamingRender.ts
│   └── useStreamingText.ts
├── lib/
│   └── api.ts                  # API客户端
├── config/
│   ├── dimensions.ts           # 维度配置
│   └── planning.ts             # 规划配置
└── types/                      # 类型定义
```

## 组件说明

### Layout 组件

| 组件 | 功能 |
|------|------|
| UnifiedLayout | 主布局容器：Header + 主内容区 |
| UnifiedContentSwitcher | 视图切换器：WELCOME_FORM / SESSION_ACTIVE |
| Header | 顶部导航栏：Logo + 新建 + 历史 + 知识库 |
| HistoryPanel | 历史记录面板：村庄列表 + 会话列表 |
| KnowledgePanel | 知识库管理面板 |

### Chat 组件

| 组件 | 功能 |
|------|------|
| ChatPanel | 主聊天面板，协调SSE和状态同步 |
| MessageList | 消息列表渲染 |
| MessageBubble | 消息气泡样式 |
| ReviewPanel | 审查面板：批准/驳回/回退 |
| LayerReportMessage | 层级完成消息组件 |
| DimensionReportStreaming | 维度报告流式渲染 |
| DimensionSelector | 维度选择器（用于驳回） |

## Context 状态

```typescript
interface PlanningState {
  // 任务状态
  taskId: string | null;
  projectName: string | null;
  status: Status;
  
  // 视图状态
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  
  // 审查状态 (直接从后端同步)
  isPaused: boolean;
  pendingReviewLayer: number | null;
  
  // 层级完成状态
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  
  // 消息历史
  messages: Message[];
  
  // 历史数据
  villages: VillageInfo[];
  selectedSession: VillageSession | null;
}
```

## 状态同步机制

### REST 轮询

```typescript
// controllers/TaskController.tsx
const pollLoop = async () => {
  const shouldStop = await fetchStatus();
  if (!shouldStop && taskId) {
    pollTimerRef.current = setTimeout(pollLoop, 2000);
  }
};
```

### SSE 事件处理

```typescript
// 事件类型
| 'layer_started'      // 层级开始
| 'layer_completed'    // 层级完成
| 'dimension_delta'    // 维度Token增量
| 'dimension_complete' // 维度完成
| 'dimension_revised'  // 维度修复完成
| 'pause'              // 暂停
| 'error'              // 错误
```

## Hooks

| Hook | 功能 |
|------|------|
| useTaskSSE | SSE 连接管理，事件处理 |
| useStreamingRender | 流式渲染批处理 (RAF + 防抖) |
| useStreamingText | 文本流式渲染动画 |

## 消息类型

| 类型 | 说明 |
|------|------|
| `text` | 普通文本消息 |
| `layer_completed` | 层级完成消息 |
| `dimension_report` | 维度报告流式 |
| `dimension_revised` | 维度修复完成 |
| `progress` | 进度更新 |
| `error` | 错误消息 |

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

## API 客户端

```typescript
// lib/api.ts

planningApi: {
  startPlanning(request)
  createStream(sessionId, onEvent, onError)
  getStatus(sessionId)
  approveReview(sessionId)
  rejectReview(sessionId, feedback, dimensions)
}

dataApi: {
  listVillages()
  getLayerContent(villageName, layerId)
  getCheckpoints(villageName)
}

knowledgeApi: {
  listDocuments()
  addDocument(file)
}
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `contexts/UnifiedPlanningContext.tsx` | 全局状态管理 |
| `controllers/TaskController.tsx` | REST轮询 + SSE事件 |
| `lib/api.ts` | API客户端封装 |
| `config/dimensions.ts` | 28个维度配置 |
| `types/message-types.ts` | 消息类型定义 |
| `hooks/useTaskSSE.ts` | SSE连接管理 |
| `components/chat/ChatPanel.tsx` | 主界面容器 |
| `components/chat/ReviewPanel.tsx` | 审查面板 |