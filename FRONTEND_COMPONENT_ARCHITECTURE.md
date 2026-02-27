# 前端组件架构文档

> Next.js 14 组件架构 - 后端状态驱动

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                         Page Layer                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │ page.tsx │  │ /chat/*  │  │ /village │  │ /villages  │  │
│  │ (首页)   │  │ (对话)   │  │ /[taskId] │  │ /new       │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬──────┘  │
└───────┼─────────────┼─────────────┼───────────────┼─────────┘
        │             │             │               │
        └─────────────┴─────────────┴───────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Context Layer                           │
│  ┌─────────────────────────┐  ┌───────────────┐            │
│  │ UnifiedPlanningContext  │  │PlanningContext│            │
│  │ (主状态管理)             │  │ (审查状态)    │            │
│  └───────────┬─────────────┘  └───────────────┘            │
└──────────────┼──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Controller Layer                          │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                    TaskController                       │  │
│  │  REST轮询(2s) + SSE文本流, 后端状态同步                  │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Component Layer                           │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │ Layout/         │  │ chat/           │  │ ui/         │ │
│  │ - UnifiedLayout │  │ - ChatPanel     │  │ - Card      │ │
│  │ - Header        │  │ - MessageList   │  │ - Segmented │ │
│  │ - HistoryPanel  │  │ - MessageBubble │  │   Control   │ │
│  │ - ContentSwitch │  │ - ReviewPanel   │  └─────────────┘ │
│  └─────────────────┘  │ - LayerReport*  │  ┌─────────────┐ │
│  ┌─────────────────┐  │ - Dimension*    │  │ report/     │ │
│  │ 顶级组件        │  │ - StreamingText │  │ - Knowledge │ │
│  │ - VillageInput  │  │ - ThinkingInd   │  │   Reference │ │
│  │ - MarkdownRend  │  └─────────────────┘  └─────────────┘ │
│  └─────────────────┘                                        │
└─────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                      Hooks Layer                             │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────┐ │
│  │useStreamingRender│  │ useStreamingText │  │useTaskSSE │ │
│  │ (批处理渲染)      │  │ (逐字打印效果)   │  │(SSE连接)  │ │
│  └──────────────────┘  └──────────────────┘  └───────────┘ │
└─────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                      Types Layer                             │
│  ┌────────────┐  ┌───────────────┐  ┌───────────────────┐  │
│  │ index.ts   │  │ message.ts    │  │ message-types.ts  │  │
│  │ (统一导出) │  │ (核心消息类型)│  │ (具体消息类型)    │  │
│  └────────────┘  └───────────────┘  └───────────────────┘  │
└─────────────────────────────────────────────────────────────┘
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

### SSE 流式事件

```
TaskController SSE 连接条件:
  !execution_complete && !pause_after_step

事件类型:
  - dimension_delta: 维度增量文本
  - dimension_complete: 维度完成
  - layer_completed: 层级完成
  - pause: 暂停等待审查
  - completed: 执行完成
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
ReviewPanel 消失 (条件渲染)
```

## 页面路由

| 路由 | 文件路径 | 功能描述 |
|------|---------|---------|
| `/` | `app/page.tsx` | 首页，使用 UnifiedPlanningProvider + UnifiedLayout |
| `/chat/[conversationId]` | `app/chat/[conversationId]/page.tsx` | 对话页面 |
| `/chat/new` | `app/chat/new/page.tsx` | 新建对话，自动创建 session 并重定向 |
| `/village/[taskId]` | `app/village/[taskId]/page.tsx` | 规划详情页面 |
| `/villages/new` | `app/villages/new/page.tsx` | 新建规划页面(旧版) |

## 组件详情

### Layout 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| UnifiedLayout | layout/UnifiedLayout.tsx | 主布局容器：Header + 主内容区 + 历史面板模态框 |
| Header | layout/Header.tsx | 顶部导航栏：Logo + 新建按钮 + 历史按钮 |
| HistoryPanel | layout/HistoryPanel.tsx | 历史记录面板：村庄列表 + 会话列表 |
| UnifiedContentSwitcher | layout/UnifiedContentSwitcher.tsx | 内容切换器：根据状态显示表单或聊天界面 |

### Chat 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| ChatPanel | chat/ChatPanel.tsx | **核心聊天面板**，集成消息列表、输入、审查功能 |
| MessageList | chat/MessageList.tsx | 消息列表渲染，支持多种消息类型 |
| MessageBubble | chat/MessageBubble.tsx | 消息气泡，包含操作按钮和知识引用 |
| MessageContent | chat/MessageContent.tsx | 消息内容渲染器，根据类型分发 |
| ReviewPanel | chat/ReviewPanel.tsx | 审查面板：批准按钮 + 聊天框反馈 |
| LayerReportMessage | chat/LayerReportMessage.tsx | 层级完成消息，使用 LayerReportCard |
| LayerReportCard | chat/LayerReportCard.tsx | 层级报告卡片，支持 chat/sidebar 双模式 |
| DimensionSection | chat/DimensionSection.tsx | 单个维度卡片，可折叠 |
| DimensionReportStreaming | chat/DimensionReportStreaming.tsx | 流式维度报告组件 |
| DimensionSelector | chat/DimensionSelector.tsx | 维度选择下拉框 |
| StreamingText | chat/StreamingText.tsx | 流式文本显示，逐字打印效果 |
| ThinkingIndicator | chat/ThinkingIndicator.tsx | 思考状态指示器 |
| ActionButtonGroup | chat/ActionButtonGroup.tsx | 操作按钮组 |
| CodeBlock | chat/CodeBlock.tsx | 代码块渲染 |

### UI 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| Card | ui/Card.tsx | 可复用卡片组件，支持多种变体 |
| SegmentedControl | ui/SegmentedControl.tsx | iOS 风格分段控制器 |

### 报告组件

| 组件 | 文件 | 功能 |
|------|------|------|
| KnowledgeReference | report/KnowledgeReference.tsx | RAG 知识引用显示组件 |

### 顶级组件

| 组件 | 文件 | 功能 |
|------|------|------|
| VillageInputForm | VillageInputForm.tsx | 村庄信息输入表单 |
| MarkdownRenderer | MarkdownRenderer.tsx | Markdown 内容渲染 |
| ConversationManager | ConversationManager.tsx | 对话管理器(旧版) |
| ChatInterface | ChatInterface.tsx | 聊天界面(旧版) |
| ReviewDrawer | ReviewDrawer.tsx | 审查抽屉组件 |
| CheckpointViewer | CheckpointViewer.tsx | 检查点查看器 |
| ViewerSidePanel | ViewerSidePanel.tsx | 侧边栏查看器 |
| RevisionProgress | RevisionProgress.tsx | 修订进度组件 |
| DimensionSelector | DimensionSelector.tsx | 维度选择器(顶级) |

## Context 状态管理

### UnifiedPlanningContext (主要)

**文件**: `contexts/UnifiedPlanningContext.tsx`

```typescript
interface PlanningState {
  // 对话状态
  conversationId: string
  messages: Message[]
  taskId: string | null
  projectName: string | null
  status: Status  // 'idle' | 'collecting' | 'planning' | 'paused' | 'reviewing' | 'revising' | 'completed' | 'failed'

  // 视图状态
  viewMode: ViewMode  // 'WELCOME_FORM' | 'SESSION_ACTIVE'
  viewerVisible: boolean

  // 审查状态 (从后端同步)
  isPaused: boolean
  pendingReviewLayer: number | null

  // 层级完成状态
  completedLayers: { 1: boolean; 2: boolean; 3: boolean }

  // 历史状态
  villages: VillageInfo[]
  selectedVillage: VillageInfo | null
  selectedSession: VillageSession | null

  // 检查点状态
  checkpoints: Checkpoint[]
  currentLayer: number | null
}

// 核心方法
syncBackendState(backendData)  // 同步后端状态
startPlanning(params)          // 启动规划任务
loadHistoricalSession()        // 加载历史会话
approve/reject/rollback        // 审查操作
```

### PlanningContext (审查专用)

**文件**: `contexts/PlanningContext.tsx`

```typescript
interface PlanningState {
  reviewStatus: ReviewStatus  // 'idle' | 'reviewing' | 'revising' | 'completed'
  currentLayer: number
  showReviewButton: boolean
  revisionProgress: RevisionProgress | null
  isReviewDrawerOpen: boolean
}
```

## Hooks

| Hook | 文件 | 功能 |
|------|------|------|
| useStreamingRender | useStreamingRender.ts | 批处理渲染 Hook，使用 requestAnimationFrame 实现 |
| useStreamingText | useStreamingText.ts | 流式文本输出，实现逐字打印效果 |
| useTaskSSE | useTaskSSE.ts | SSE 连接管理，包含重试限制和指数退避 |

**useStreamingRender 特性**:
- 批处理 token 更新
- 防抖内容刷新
- 增量 DOM 更新

**useStreamingText 特性**:
- 可配置速度
- 支持暂停/恢复/跳过
- 进度指示

**useTaskSSE 特性**:
- 最大重试次数限制 (3次)
- 指数退避重连
- 维度级流式事件处理

## Controller 层

### TaskController

**文件**: `controllers/TaskController.tsx`

**核心理念**:
- 后端状态为单一真实源
- Controller 只负责数据搬运，不做业务逻辑判断
- 幂等性保证

**工作流程**:
```
REST 轮询 (/status) --> 同步状态到 Context --> 检查是否停止
         ^                    |
         |                    v
         +------ 2秒间隔 ------+
```

**SSE 连接管理**:
- 仅用于文本流
- 不做业务逻辑判断
- 支持 `pause_after_step` 标志控制

```typescript
const [state, actions] = useTaskController(taskId, callbacks);

// actions
actions.approve()   // 批准审查
actions.reject()    // 驳回审查
actions.rollback()  // 回退检查点
```

## Types 类型定义

### 核心消息类型

```typescript
type Message =
  | TextMessage
  | FileMessage
  | ProgressMessage
  | ActionMessage
  | ResultMessage
  | ErrorMessage
  | SystemMessage
  | DimensionReportMessage
  | LayerCompletedMessage
  | DimensionRevisedMessage

type MessageRole = 'user' | 'assistant' | 'system'
```

### 层级完成消息

```typescript
interface LayerCompletedMessage extends BaseMessage {
  type: 'layer_completed'
  layer: number
  content: string
  summary: {
    word_count: number
    key_points: string[]
    dimension_count?: number
    dimension_names?: string[]
  }
  fullReportContent?: string
  dimensionReports?: Record<string, string>
  actions: ActionButton[]
}
```

### 维度报告消息

```typescript
interface DimensionReportMessage extends BaseMessage {
  type: 'dimension_report'
  layer: number
  dimensionKey: string
  dimensionName: string
  content: string
  streamingState: 'streaming' | 'completed' | 'error'
  wordCount: number
}
```

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

## Config 配置

| 文件 | 功能 |
|------|------|
| `config/dimensions.ts` | 维度配置：名称、图标、描述 |
| `config/planning.ts` | 规划参数默认值 |

## 条件渲染

```typescript
// 视图模式切换
{viewMode === 'WELCOME_FORM' && <VillageInputForm />}
{viewMode === 'SESSION_ACTIVE' && <ChatPanel />}

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
  case 'dimension_report': return <DimensionReportStreaming />;
  default: return <TextMessage />;
}
```

## 关键文件索引

| 文件 | 功能 |
|------|------|
| `contexts/UnifiedPlanningContext.tsx` | 全局状态管理 |
| `contexts/PlanningContext.tsx` | 审查状态管理 |
| `controllers/TaskController.tsx` | REST轮询+SSE管理 |
| `lib/api.ts` | API客户端 |
| `types/message.ts` | 核心消息类型 |
| `types/message-types.ts` | 具体消息类型定义 |
| `types/message-guards.ts` | 类型守卫函数 |
| `types/message-helpers.ts` | 辅助转换函数 |
| `config/dimensions.ts` | 维度配置 |
| `config/planning.ts` | 规划参数 |
| `components/chat/ChatPanel.tsx` | 主界面容器 |
| `components/chat/ReviewPanel.tsx` | 审查面板 |
| `components/chat/MessageList.tsx` | 消息列表 |
| `components/chat/MessageBubble.tsx` | 消息气泡 |
| `components/chat/LayerReportCard.tsx` | 层级报告卡片 |
| `components/chat/DimensionSection.tsx` | 维度内容显示 |
| `components/chat/StreamingText.tsx` | 流式文本 |
| `components/layout/UnifiedLayout.tsx` | 主布局 |
| `components/layout/Header.tsx` | 顶部导航 |
| `components/layout/HistoryPanel.tsx` | 历史面板 |
