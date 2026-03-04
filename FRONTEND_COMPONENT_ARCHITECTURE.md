# 前端组件架构文档

> Next.js 14 组件架构 - 单一状态源、后端驱动

## 技术栈

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

## 架构概览

### 组件树

```
App (page.tsx)
  │
  ├─── UnifiedPlanningProvider (Context)
  │      │
  │      ├─── 状态管理: messages, status, taskId, isPaused
  │      ├─── 历史管理: villages, sessions
  │      ├─── 同步: syncBackendState, setUILayerCompleted
  │      └─── 操作: startPlanning, loadHistoricalSession
  │
  └─── UnifiedLayout
         │
         ├─── Header (导航栏)
         │      ├─── Logo
         │      ├─── 新建规划按钮
         │      ├─── 历史记录按钮
         │      └─── 知识库按钮
         │
         └─── UnifiedContentSwitcher (视图切换)
                │
                ├─── [WELCOME_FORM] → VillageInputForm
                │
                └─── [SESSION_ACTIVE] → ChatPanel
                       │
                       ├─── useTaskSSE (SSE连接)
                       │
                       ├─── MessageList
                       │      ├─── MessageBubble
                       │      │      └─── MessageContent
                       │      │             ├─── TextMessage
                       │      │             ├─── LayerReportMessage
                       │      │             ├─── DimensionReportStreaming
                       │      │             └─── DimensionRevisedMessage
                       │      └─── LayerReportCard
                       │
                       ├─── ReviewPanel (条件渲染)
                       │      ├─── DimensionSelector
                       │      └─── ActionButtonGroup
                       │
                       └─── ThinkingIndicator
```

### 分层架构

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
│                    Component Layer                           │
│  Layout: UnifiedLayout, Header, HistoryPanel, KnowledgePanel│
│  Chat: ChatPanel, MessageList, ReviewPanel                  │
│  Report: LayerReportCard, DimensionSection                  │
│  Form: VillageInputForm                                      │
│  UI: Card, SegmentedControl                                  │
└─────────────────────────────────────────────────────────────┘
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

## 组件详情

### Layout 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| UnifiedLayout | layout/UnifiedLayout.tsx | 主布局容器：Header + 主内容区 |
| UnifiedContentSwitcher | layout/UnifiedContentSwitcher.tsx | 视图切换器：WELCOME_FORM / SESSION_ACTIVE |
| Header | layout/Header.tsx | 顶部导航栏：Logo + 新建 + 历史 + 知识库 |
| HistoryPanel | layout/HistoryPanel.tsx | 历史记录面板：村庄列表 + 会话列表 |
| KnowledgePanel | layout/KnowledgePanel.tsx | 知识库管理面板 |

### Chat 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| ChatPanel | chat/ChatPanel.tsx | 主聊天面板，协调SSE和状态同步 |
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

### 其他组件

| 组件 | 文件 | 功能 |
|------|------|------|
| MarkdownRenderer | MarkdownRenderer.tsx | Markdown渲染器 |

## Context 状态管理

### UnifiedPlanningContext

**文件**: `contexts/UnifiedPlanningContext.tsx`

```typescript
interface PlanningState {
  // 任务状态
  taskId: string | null;
  projectName: string | null;
  conversationId: string;
  status: Status;  // idle|collecting|planning|paused|reviewing|revising|completed|failed
  
  // 视图状态
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  
  // 审查状态 (直接从后端同步)
  isPaused: boolean;              // = status === 'paused'
  pendingReviewLayer: number | null;  // = previous_layer
  
  // 层级完成状态
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
  
  // 表单数据
  villageFormData: VillageInputData | null;
}
```

### 关键方法

```typescript
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
```

## Hooks

| Hook | 文件 | 功能 |
|------|------|------|
| useTaskSSE | hooks/useTaskSSE.ts | SSE 连接管理，事件处理 |
| useStreamingRender | hooks/useStreamingRender.ts | 流式渲染批处理 |
| useStreamingText | hooks/useStreamingText.ts | 文本流式渲染动画 |

## 消息类型系统

### 基础类型 (`types/message.ts`)

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

### 特定类型 (`types/message-types.ts`)

| 类型 | 说明 | 关键字段 |
|------|------|----------|
| `text` | 普通文本 | content, streamingState, knowledgeReferences |
| `layer_completed` | 层级完成 | layer, fullReportContent, dimensionReports, summary |
| `dimension_report` | 维度报告 | layer, dimensionKey, streamingState, wordCount |
| `dimension_revised` | 维度修复 | layer, dimensionKey, oldContent, newContent, feedback |
| `review_request` | 审查请求 | layer, summary, actions |
| `checkpoint_list` | 检查点列表 | checkpoints, currentCheckpoint, actions |
| `progress` | 进度更新 | progress, currentLayer, taskId |
| `action` | 带操作按钮 | content, actions, taskId |
| `result` | 最终结果 | content, villageName, sessionId, layers |
| `error` | 错误消息 | content, error, recoverable |
| `system` | 系统消息 | content, level |

## API 客户端

**文件**: `lib/api.ts`

```typescript
planningApi: {
  startPlanning(request)           // POST /api/planning/start
  createStream(sessionId, onEvent, onError)  // GET /api/planning/stream (SSE)
  getStatus(sessionId)             // GET /api/planning/status
  reviewAction(sessionId, request) // POST /api/planning/review
  approveReview(sessionId)         // 批准
  rejectReview(sessionId, feedback, dimensions)  // 驳回
  rollbackCheckpoint(sessionId, checkpointId)    // 回退
  deleteSession(sessionId)         // DELETE
  resetProject(projectName)        // POST /api/planning/rate-limit/reset
}

dataApi: {
  listVillages()                   // GET /api/data/villages
  getVillageSessions(villageName)  // GET /api/data/villages/{name}/sessions
  getLayerContent(villageName, layerId, session?, format?)  // GET 层级内容
  getCheckpoints(villageName, session?)  // GET 检查点
  compareCheckpoints(villageName, cp1, cp2)  // GET 比较
  getCombinedPlan(villageName, session?, format?)  // GET 综合规划
}

fileApi: {
  uploadFile(file)                 // POST /api/files/upload
}

knowledgeApi: {
  listDocuments()                  // GET /api/knowledge/documents
  addDocument(file, category?)     // POST /api/knowledge/documents
  deleteDocument(filename)         // DELETE /api/knowledge/documents/{filename}
  getStats()                       // GET /api/knowledge/stats
  syncDocuments()                  // POST /api/knowledge/sync
}
```

## 维度配置

**文件**: `config/dimensions.ts`

```typescript
// 维度名称映射
export const DIMENSION_NAMES: Record<string, string> = {
  // Layer 1: 现状分析
  location: '区位与对外交通分析',
  socio_economic: '社会经济分析',
  villager_wishes: '村民意愿与诉求分析',
  superior_planning: '上位规划与政策导向分析',
  natural_environment: '自然环境分析',
  land_use: '土地利用分析',
  traffic: '道路交通分析',
  public_services: '公共服务设施分析',
  infrastructure: '基础设施分析',
  ecological_green: '生态绿地分析',
  architecture: '建筑分析',
  historical_culture: '历史文化与乡愁保护分析',
  
  // Layer 2: 规划思路
  resource_endowment: '资源禀赋分析',
  planning_positioning: '规划定位分析',
  development_goals: '发展目标分析',
  planning_strategies: '规划策略分析',
  
  // Layer 3: 详细规划
  industry: '产业规划',
  spatial_structure: '空间结构规划',
  land_use_planning: '土地利用规划',
  settlement_planning: '居民点规划',
  traffic_planning: '道路交通规划',
  public_service: '公共服务设施规划',
  infrastructure_planning: '基础设施规划',
  ecological: '生态绿地规划',
  disaster_prevention: '防震减灾规划',
  heritage: '历史文保规划',
  landscape: '村庄风貌指引',
  project_bank: '建设项目库',
};

// 按层级分组
export const DIMENSIONS_BY_LAYER: Record<number, string[]> = {
  1: ['location', 'socio_economic', ...],  // 12个
  2: ['resource_endowment', ...],           // 4个
  3: ['industry', ...],                     // 12个
};

// 辅助函数
export const getDimensionName = (key: string): string;
export const getDimensionIcon = (key: string): string;
export const getDimensionsByLayer = (layer: number): string[];
export const getDimensionConfigsByLayer = (layer: number): Array<{key, name, icon}>;
```

## 条件渲染

```typescript
// 视图模式切换 (UnifiedContentSwitcher)
{viewMode === 'WELCOME_FORM' && <VillageInputForm />}
{viewMode === 'SESSION_ACTIVE' && <ChatPanel />}

// ReviewPanel 显示 (ChatPanel)
{isPaused && pendingReviewLayer && (
  <ReviewPanel 
    layer={pendingReviewLayer}
    onApprove={() => planningApi.approveReview(taskId)}
    onReject={(feedback, dimensions) => 
      planningApi.rejectReview(taskId, feedback, dimensions)
    }
  />
)}

// 消息类型渲染 (MessageContent)
switch (message.type) {
  case 'layer_completed': 
    return <LayerReportMessage message={message} />;
  case 'dimension_report': 
    return <DimensionReportStreaming message={message} />;
  case 'dimension_revised':
    return <DimensionRevisedMessage message={message} />;
  case 'progress':
    return <ProgressMessage message={message} />;
  case 'error':
    return <ErrorMessage message={message} />;
  case 'system':
    return <SystemMessage message={message} />;
  default: 
    return <TextMessage message={message} />;
}

// 维度选择器 (ReviewPanel)
{isRejecting && (
  <DimensionSelector
    layer={layer}
    selectedDimensions={selectedDimensions}
    onChange={setSelectedDimensions}
  />
)}
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `contexts/UnifiedPlanningContext.tsx` | 全局状态管理 |
| `lib/api.ts` | API客户端 |
| `lib/constants.ts` | 常量定义 (LAYER_ID_MAP等) |
| `lib/utils.ts` | 工具函数 (createBaseMessage等) |
| `lib/logger.ts` | 日志工具 |
| `config/dimensions.ts` | 维度配置 (28个维度) |
| `config/planning.ts` | 规划配置 (默认值) |
| `types/message.ts` | 基础消息类型 |
| `types/message-types.ts` | 特定消息类型 |
| `hooks/useTaskSSE.ts` | SSE连接管理 |
| `hooks/useStreamingRender.ts` | 流式渲染 |
| `components/chat/ChatPanel.tsx` | 主界面容器 |
| `components/chat/ReviewPanel.tsx` | 审查面板 |
| `components/chat/LayerReportCard.tsx` | 层级报告卡片 |
| `components/layout/UnifiedLayout.tsx` | 主布局 |
| `styles/globals.css` | 全局样式 + CSS变量 |
