# 前端实现文档

> Next.js 14 前端架构 - 单一状态源、后端驱动

## 架构概览

### 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Next.js | 14.2.0 | React 框架 |
| React | 18.3.0 | UI 库 |
| TypeScript | 5.x | 类型安全 |
| Bootstrap | 5.3.0 | CSS 框架 |
| Tailwind CSS | 4.2.1 | 实用类 |
| Framer Motion | 12.32.0 | 动画库 |
| react-markdown | 9.0.0 | Markdown 渲染 |
| FontAwesome | 7.1.0 | 图标库 |

### 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Page Layer                              │
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
│                    Component Layer                           │
│  Layout: UnifiedLayout, Header, HistoryPanel, KnowledgePanel│
│  Chat: ChatPanel, MessageList, ReviewPanel                  │
│  Report: LayerReportCard, DimensionSection                  │
│  Form: VillageInputForm                                      │
│  UI: Card, SegmentedControl                                  │
└─────────────────────────────────────────────────────────────┘
```

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

## 目录结构

```
frontend/src/
├── app/                        # 页面路由
│   ├── page.tsx                # 首页
│   ├── layout.tsx              # 根布局
│   └── village/[taskId]/       # 任务详情页
├── contexts/
│   └── UnifiedPlanningContext.tsx  # 全局状态
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
│   │   ├── MessageContent.tsx
│   │   ├── ReviewPanel.tsx
│   │   ├── LayerReportCard.tsx
│   │   ├── LayerReportMessage.tsx
│   │   ├── DimensionSection.tsx
│   │   ├── DimensionReportStreaming.tsx
│   │   ├── DimensionSelector.tsx
│   │   ├── StreamingText.tsx
│   │   ├── ThinkingIndicator.tsx
│   │   └── ActionButtonGroup.tsx
│   ├── report/                 # 报告组件
│   │   ├── KnowledgeReference.tsx
│   │   └── README.md
│   ├── ui/                     # 通用UI组件
│   │   ├── Card.tsx
│   │   └── SegmentedControl.tsx
│   ├── MarkdownRenderer.tsx
│   └── VillageInputForm.tsx
├── hooks/
│   ├── useTaskSSE.ts           # SSE连接管理
│   ├── useStreamingRender.ts   # 流式渲染批处理
│   └── useStreamingText.ts     # 文本流式渲染
├── lib/
│   ├── api.ts                  # API客户端
│   ├── logger.ts               # 日志工具
│   ├── constants.ts            # 常量定义
│   └── utils.ts                # 工具函数
├── config/
│   ├── dimensions.ts           # 维度配置
│   └── planning.ts             # 规划配置
├── styles/
│   ├── globals.css             # 全局样式
│   └── layer-report.css        # 层级报告样式
└── types/                      # 类型定义
    ├── message.ts              # 基础消息类型
    ├── message-types.ts        # 特定消息类型
    └── index.ts                # 类型导出
```

## Context 状态管理

### UnifiedPlanningContext

**文件**: `contexts/UnifiedPlanningContext.tsx`

```typescript
interface PlanningState {
  // 任务标识
  taskId: string | null;
  projectName: string | null;
  conversationId: string;
  
  // 状态 (从后端同步)
  status: Status;  // idle|collecting|planning|paused|reviewing|revising|completed|failed
  
  // 视图状态
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  
  // 审查状态 (直接从后端同步)
  isPaused: boolean;              // = status === 'paused'
  pendingReviewLayer: number | null;  // = previous_layer
  
  // 层级完成状态 (SSE驱动，REST用于断线恢复)
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  
  // 消息历史
  messages: Message[];
  
  // 历史数据
  villages: VillageInfo[];
  selectedVillage: VillageInfo | null;
  selectedSession: VillageSession | null;
  
  // 检查点
  checkpoints: Checkpoint[];
  currentLayer: number | null;
  
  // 报告同步状态
  reportSyncState: ReportSyncState;
}

interface UnifiedPlanningContextType {
  // 状态
  // ... (同上)
  
  // 同步后端状态
  syncBackendState: (backendData: any) => void;
  
  // SSE驱动的层级完成状态更新
  setUILayerCompleted: (layer: number, completed: boolean) => void;
  
  // 规划操作
  startPlanning: (params: PlanningParams) => Promise<void>;
  resetConversation: () => void;
  
  // 历史操作
  loadVillagesHistory: () => Promise<void>;
  selectVillage: (village: VillageInfo) => void;
  selectSession: (session: VillageSession) => void;
  loadHistoricalSession: (villageName: string, sessionId: string) => Promise<void>;
  loadHistoricalReports: (villageName: string, sessionId: string) => Promise<void>;
}
```

### 状态同步机制

```typescript
// syncBackendState - 从REST轮询同步状态
const syncBackendState = useCallback((backendData: any) => {
  // 比较关键字段，避免不必要的更新
  const hasStateChanged = !previousState ||
    previousState.status !== backendData.status ||
    previousState.previous_layer !== backendData.previous_layer ||
    previousState.layer_1_completed !== backendData.layer_1_completed;
    
  if (!hasStateChanged) return;
  
  setStatusState(backendData.status);
  setIsPaused(backendData.status === 'paused');
  setPendingReviewLayer(backendData.previous_layer);
  
  // 只在会话结束、暂停或初始状态时同步REST状态
  // 运行中的状态由SSE的layer_completed事件驱动
  if (['idle', 'completed', 'failed', 'paused'].includes(backendData.status)) {
    setCompletedLayers({
      1: backendData.layer_1_completed || false,
      2: backendData.layer_2_completed || false,
      3: backendData.layer_3_completed || false,
    });
  }
}, []);

// setUILayerCompleted - SSE驱动的层级完成
const setUILayerCompleted = useCallback((layer: number, completed: boolean) => {
  setCompletedLayers(prev => {
    if (prev[layer as 1|2|3] === completed) return prev;
    return { ...prev, [layer]: completed };
  });
}, []);
```

## 消息类型系统

### 基础消息类型 (`types/message.ts`)

```typescript
interface BaseMessage {
  id: string;
  timestamp: Date;
  role: 'user' | 'assistant' | 'system';
  type: string;
}

interface ActionButton {
  id: string;
  label: string;
  action: string;
  variant?: 'primary' | 'secondary' | 'danger';
}

interface KnowledgeReference {
  source: string;
  content: string;
  relevance: number;
}
```

### 特定消息类型 (`types/message-types.ts`)

| 类型 | 说明 | 关键字段 |
|------|------|----------|
| `text` | 普通文本消息 | content, streamingState |
| `layer_completed` | 层级完成 | layer, fullReportContent, dimensionReports |
| `dimension_report` | 维度报告流式 | layer, dimensionKey, streamingState |
| `dimension_revised` | 维度修复完成 | layer, dimensionKey, oldContent, newContent |
| `review_request` | 审查请求 | layer, summary, actions |
| `checkpoint_list` | 检查点列表 | checkpoints, actions |
| `progress` | 进度更新 | progress, currentLayer |
| `error` | 错误消息 | content, recoverable |
| `system` | 系统消息 | content, level |

## 组件详情

### Layout 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| UnifiedLayout | layout/UnifiedLayout.tsx | 主布局容器：Header + 主内容区 |
| UnifiedContentSwitcher | layout/UnifiedContentSwitcher.tsx | 视图切换：表单/聊天 |
| Header | layout/Header.tsx | 顶部导航栏：Logo + 新建 + 历史 + 知识库 |
| HistoryPanel | layout/HistoryPanel.tsx | 历史记录面板：村庄列表 + 会话列表 |
| KnowledgePanel | layout/KnowledgePanel.tsx | 知识库管理面板 |

### Chat 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| ChatPanel | chat/ChatPanel.tsx | 主界面容器，协调SSE和状态同步 |
| MessageList | chat/MessageList.tsx | 消息列表渲染 |
| MessageBubble | chat/MessageBubble.tsx | 消息气泡样式 |
| MessageContent | chat/MessageContent.tsx | 消息内容渲染（根据type分发） |
| ReviewPanel | chat/ReviewPanel.tsx | 审查面板：批准/驳回/回退 |
| LayerReportCard | chat/LayerReportCard.tsx | 层级报告卡片 |
| LayerReportMessage | chat/LayerReportMessage.tsx | 层级完成消息组件 |
| DimensionSection | chat/DimensionSection.tsx | 单个维度卡片 |
| DimensionReportStreaming | chat/DimensionReportStreaming.tsx | 维度报告流式渲染 |
| DimensionSelector | chat/DimensionSelector.tsx | 维度选择器（用于驳回） |
| StreamingText | chat/StreamingText.tsx | 流式文本显示 |
| ThinkingIndicator | chat/ThinkingIndicator.tsx | 思考指示器 |
| ActionButtonGroup | chat/ActionButtonGroup.tsx | 操作按钮组 |

### Report 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| KnowledgeReference | report/KnowledgeReference.tsx | RAG知识引用展示 |

### UI 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| Card | ui/Card.tsx | 通用卡片容器 |
| SegmentedControl | ui/SegmentedControl.tsx | 分段控制器 |

### Form 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| VillageInputForm | VillageInputForm.tsx | 村庄信息输入表单 |

## Hooks

| Hook | 文件 | 功能 |
|------|------|------|
| useTaskSSE | hooks/useTaskSSE.ts | SSE 连接管理，事件处理 |
| useStreamingRender | hooks/useStreamingRender.ts | 流式渲染批处理 |
| useStreamingText | hooks/useStreamingText.ts | 文本流式渲染动画 |

### useTaskSSE 示例

```typescript
const useTaskSSE = (
  sessionId: string | null,
  onEvent: (event: PlanningSSEEvent) => void,
  shouldConnect: boolean
) => {
  useEffect(() => {
    if (!sessionId || !shouldConnect) return;
    
    const eventSource = planningApi.createStream(
      sessionId,
      onEvent,
      (error) => console.error('SSE error:', error)
    );
    
    return () => eventSource.close();
  }, [sessionId, shouldConnect]);
};
```

## API 客户端

**文件**: `lib/api.ts`

### 模块结构

```typescript
// Planning API
planningApi: {
  startPlanning(request)           // POST /api/planning/start
  createStream(sessionId, onEvent) // GET /api/planning/stream (SSE)
  getStatus(sessionId)             // GET /api/planning/status
  reviewAction(sessionId, request) // POST /api/planning/review
  approveReview(sessionId)         // 批准
  rejectReview(sessionId, feedback, dimensions)  // 驳回
  rollbackCheckpoint(sessionId, checkpointId)    // 回退
  deleteSession(sessionId)         // DELETE /api/planning/sessions
  resetProject(projectName)        // POST /api/planning/rate-limit/reset
}

// Data API
dataApi: {
  listVillages()                   // GET /api/data/villages
  getVillageSessions(villageName)  // GET /api/data/villages/{name}/sessions
  getLayerContent(villageName, layerId, session?, format)  // GET /api/data/villages/{name}/layers/{layer}
  getCheckpoints(villageName, session?)  // GET /api/data/villages/{name}/checkpoints
  compareCheckpoints(villageName, cp1, cp2)  // GET /api/data/villages/{name}/compare/{cp1}/{cp2}
  getCombinedPlan(villageName, session?, format)  // GET /api/data/villages/{name}/plan
}

// File API
fileApi: {
  uploadFile(file)                 // POST /api/files/upload
}

// Knowledge API
knowledgeApi: {
  listDocuments()                  // GET /api/knowledge/documents
  addDocument(file, category?)     // POST /api/knowledge/documents
  deleteDocument(filename)         // DELETE /api/knowledge/documents/{filename}
  getStats()                       // GET /api/knowledge/stats
  syncDocuments()                  // POST /api/knowledge/sync
}
```

### 统一响应格式

```typescript
interface APIResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
  request_id?: string;
}
```

### SSE 事件类型

```typescript
type PlanningSSEEventType =
  | 'layer_started'
  | 'layer_completed'
  | 'checkpoint_saved'
  | 'pause'
  | 'progress'
  | 'completed'
  | 'error'
  | 'resumed'
  | 'dimension_delta'
  | 'dimension_complete'
  | 'dimension_revised'
  | 'stream_paused';

interface PlanningSSEEvent {
  type: PlanningSSEEventType;
  session_id?: string;
  data: {
    layer?: number;
    dimension?: string;
    delta?: string;
    accumulated?: string;
    message?: string;
    error?: string;
    // ...
  };
}
```

## 维度配置

**文件**: `config/dimensions.ts`

```typescript
// 维度名称映射
export const DIMENSION_NAMES: Record<string, string> = {
  // Layer 1
  location: '区位与对外交通分析',
  socio_economic: '社会经济分析',
  // ...
  
  // Layer 2
  resource_endowment: '资源禀赋分析',
  // ...
  
  // Layer 3
  industry: '产业规划',
  // ...
};

// 维度图标映射
export const DIMENSION_ICONS: Record<string, string> = {
  location: '📍',
  socio_economic: '👥',
  // ...
};

// 按层级分组
export const DIMENSIONS_BY_LAYER: Record<number, string[]> = {
  1: ['location', 'socio_economic', ...],
  2: ['resource_endowment', ...],
  3: ['industry', ...],
};

// 辅助函数
export const getDimensionName = (key: string): string;
export const getDimensionIcon = (key: string): string;
export const getDimensionsByLayer = (layer: number): string[];
export const getDimensionConfigsByLayer = (layer: number): Array<{key, name, icon}>;
```

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
    onReject={(feedback, dimensions) => planningApi.rejectReview(taskId, feedback, dimensions)}
  />
)}

// 消息类型渲染 (MessageContent.tsx)
switch (message.type) {
  case 'layer_completed': 
    return <LayerReportMessage message={message} />;
  case 'dimension_report': 
    return <DimensionReportStreaming message={message} />;
  case 'dimension_revised':
    return <DimensionRevisedMessage message={message} />;
  default: 
    return <TextMessage message={message} />;
}
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `contexts/UnifiedPlanningContext.tsx` | 全局状态管理 |
| `lib/api.ts` | API客户端 |
| `lib/constants.ts` | 常量定义 (LAYER_ID_MAP等) |
| `config/dimensions.ts` | 维度配置 (28个维度) |
| `types/message-types.ts` | 消息类型定义 |
| `hooks/useTaskSSE.ts` | SSE连接管理 |
| `hooks/useStreamingRender.ts` | 流式渲染 |
| `components/chat/ChatPanel.tsx` | 主界面容器 |
| `components/chat/ReviewPanel.tsx` | 审查面板 |
| `components/chat/LayerReportCard.tsx` | 层级报告卡片 |
| `components/layout/UnifiedLayout.tsx` | 主布局 |
| `styles/globals.css` | 全局样式 + CSS变量 |
