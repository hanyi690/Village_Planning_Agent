# 前端实现文档

> **相关文档**: [系统架构总览](architecture.md) | [智能体架构](agent.md) | [数据流转](data-flow-architecture.md)
>
> Next.js 14 前端架构 - Zustand 状态管理、SSE 事件驱动

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Page Layer (App Router)                         │
│                        app/page.tsx (首页)                           │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Provider Layer                                  │
│  PlanningProvider (Zustand 薄包装)                                   │
│  ├─ usePlanningStore (状态管理)                                      │
│  ├─ useSSEConnection (SSE 连接)                                      │
│  ├─ useMessagePersistence (消息持久化)                               │
│  └─ useSessionRestore (会话恢复)                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Store Layer (Zustand + Immer)                   │
│  planningStore.ts (单一状态源)                                       │
│  ├─ 状态定义 (PlanningState)                                         │
│  ├─ Actions (setTaskId, addMessage, handleSSEEvent...)              │
│  └─ Selectors (粒度选择器优化渲染性能)                                │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Component Layer                                   │
│  Layout: UnifiedLayout, Header, HistoryPanel, KnowledgePanel        │
│  Chat: ChatPanel, MessageList, ReviewPanel, LayerReportMessage      │
│  Form: VillageInputForm                                              │
│  Layer: LayerSidebar (首页渲染)                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## 页面架构说明

### 首页 (`app/page.tsx`) - 唯一用户交互页面

**功能**：
- 入口页面，用于创建新任务或从历史面板加载会话
- 通过 `HistoryPanel` 加载历史会话时，**不跳转路由**，直接设置 Store 中的 `taskId`
- 通过 `taskId` 和 `status` 状态切换视图（`UnifiedContentSwitcher`）
- **包含 Layer 侧边栏支持**：点击 Layer 按钮时拉取后端最新报告内容并显示

## 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Next.js | 14.2.0 | React 框架 |
| React | 18.3.0 | UI 库 |
| TypeScript | 5.x | 类型安全 |
| Zustand | 5.x | 状态管理 (替代 Context) |
| Immer | 10.x | 不可变状态更新 |
| Tailwind CSS | 4.2.1 | 实用类 |
| Framer Motion | 12.32.0 | 动画库 |
| react-markdown | 9.0.0 | Markdown 渲染 |

## 设计风格

### Gemini 风格暗色主题

前端采用 Gemini 风格的暗色主题设计，主要特点：

- **主色调**：绿色系 (#10b981 emerald-500) 作为强调色
- **背景色**：深灰色系 (#0f0f11, #1a1a1a)
- **文本色**：浅灰色 (#e5e5e5) 和白色
- **动画效果**：流畅的微动画和过渡效果
- **思考指示器**：脉动动画效果，模拟 AI 思考过程

### 维度图标

#### Layer 1: 现状分析 (12维度)

| 图标 | 维度 |
|------|------|
| 📍 | 区位与对外交通分析 |
| 👥 | 社会经济分析 |
| 💭 | 村民意愿与诉求分析 |
| 📋 | 上位规划与政策导向分析 |
| 🌿 | 自然环境分析 |
| 🏗️ | 土地利用分析 |
| 🚗 | 道路交通分析 |
| 🏛️ | 公共服务设施分析 |
| 🔧 | 基础设施分析 |
| 🌳 | 生态绿地分析 |
| 🏠 | 建筑分析 |
| 🏮 | 历史文化与乡愁保护分析 |

#### Layer 2: 规划思路 (4维度)

| 图标 | 维度 |
|------|------|
| 💎 | 资源禀赋分析 |
| 🎯 | 规划定位分析 |
| 📈 | 发展目标分析 |
| 📊 | 规划策略分析 |

#### Layer 3: 详细规划 (12维度)

| 图标 | 维度 |
|------|------|
| 🏭 | 产业规划 |
| 🗺️ | 空间结构规划 |
| 📐 | 土地利用规划 |
| 🏘️ | 居民点规划 |
| 🛣️ | 道路交通规划 |
| 🏥 | 公共服务设施规划 |
| 🔨 | 基础设施规划 |
| 🌲 | 生态绿地规划 |
| 🛡️ | 防震减灾规划 |
| 🏰 | 历史文保规划 |
| 🎨 | 村庄风貌指引 |
| 📦 | 建设项目库 |

## 核心原则

### 单一状态源 (SSOT)

使用 Zustand 作为唯一状态源，替代之前的 Context + useReducer：

```
后端状态 (Checkpointer)        →    Zustand Store 状态
────────────────────────────────────────────────
status: 'paused'               →    isPaused: true
previous_layer: 1              →    pendingReviewLayer: 1
layer_1_completed: true        →    completedLayers[1]: true
version: 102                   →    conversationId + metadata
```

### Signal-Fetch Pattern

SSE 只发送轻量信号，完整数据通过 REST API 获取：

```
后端 SSE 事件                    前端处理
────────────────────────────────────────────────
layer_started: {layer, name}  → 创建空 LayerReportMessage
dimension_delta: {delta}      → 批量更新内容缓存 (50ms 窗口)
layer_completed: {layer, ver} → REST API 获取完整报告
pause: {layer}                → 显示审查面板
stream_paused: {reason}       → 关闭 SSE 连接，等待用户操作
```

## 状态管理 (Zustand + Immer)

### planningStore.ts

```typescript
// stores/planningStore.ts
export interface PlanningState {
  conversationId: string;

  // Session
  taskId: string | null;
  projectName: string | null;
  status: Status;  // idle|collecting|planning|paused|completed|failed

  // Agent State (Single Source of Truth)
  phase: string;
  currentWave: number;
  reports: Reports;  // layer1, layer2, layer3
  pause_after_step: boolean;
  previous_layer: number;
  step_mode: boolean;

  // Derived UI State
  completedDimensions: CompletedDimensions;
  currentLayer: number | null;
  currentPhase: LayerPhase | '修复中';
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  isPaused: boolean;
  pendingReviewLayer: number | null;

  // Messages
  messages: Message[];

  // Progress
  dimensionProgress: Record<string, DimensionProgressItem>;
  executingDimensions: string[];

  // UI State
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  viewerVisible: boolean;
  viewingFile: FileMessage | null;

  // Tool Status
  toolStatuses: Record<string, ToolStatus>;

  // History
  villages: VillageInfo[];
  selectedVillage: VillageInfo | null;
  selectedSession: VillageSession | null;
  checkpoints: Checkpoint[];
  selectedCheckpointId: string | null;
}
```

### 粒度选择器 (Performance Optimization)

```typescript
// hooks/planning/usePlanningSelectors.ts

// ❌ Bad - subscribes to entire state
const state = usePlanningStore();
const messages = state.messages;

// ✅ Good - only re-renders when messages change
const messages = useMessages();

// 导出的选择器
export function useMessages(): Message[];
export function useStatus(): Status;
export function useTaskId(): string | null;
export function useProjectName(): string | null;
export function useCurrentLayer(): number | null;
export function useIsPaused(): boolean;
export function useCompletedLayers(): { 1: boolean; 2: boolean; 3: boolean };
export function useDimensionProgressAll(): Record<string, DimensionProgressItem>;
export function useReports(): Reports;
export function useToolStatuses(): Record<string, ToolStatus>;
export function useCheckpoints(): Checkpoint[];
// ... 更多选择器
```

### SSE 事件处理 (批量优化)

```typescript
// hooks/planning/useSSEConnection.ts

const BATCH_WINDOW = 50; // ms
const MAX_BATCH_SIZE = 50;

export function useSSEConnection({ taskId, enabled, onReconnect }) {
  const batchQueueRef = useRef<BatchEvent[]>([]);
  const batchTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // 批量处理 dimension_delta 事件
  const processBatch = useCallback(() => {
    const events = batchQueueRef.current;
    batchQueueRef.current = [];

    // 合并相同 dimensionKey 的 delta 事件
    const merged = mergeDimensionDeltaEvents(events);
    merged.forEach(event => handleSSEEvent(event));
  }, []);

  // 重连机制 (指数退避)
  const reconnect = useCallback(() => {
    if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
      syncBackendState(); // 先同步状态
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 5000);
      setTimeout(() => createConnection(), delay);
    }
  }, []);
}
```

## 目录结构

```
frontend/src/
├── app/                        # 页面路由
│   ├── page.tsx                # 首页 (唯一用户交互页面)
│   └── layout.tsx              # 根布局
├── stores/                     # ⭐ 状态管理 (新架构)
│   ├── index.ts                # 导出入口
│   ├── planningStore.ts        # Zustand Store (单一状态源)
│   └── planning-context.tsx    # Provider 包装层
├── hooks/                      # ⭐ Hooks 目录重构
│   ├── index.ts                # 总导出入口
│   ├── planning/               # 规划相关 hooks
│   │   ├── index.ts
│   │   ├── usePlanningHandlers.ts    # 规划操作
│   │   ├── usePlanningSelectors.ts   # 粒度选择器 (性能优化)
│   │   ├── useReviewActions.ts       # 审查操作
│   │   ├── useMessagePersistence.ts  # 消息持久化
│   │   ├── useSSEConnection.ts       # SSE 连接管理
│   │   └── useSessionRestore.ts      # 会话恢复
│   ├── ui/                     # UI 相关 hooks
│   │   ├── index.ts
│   │   └── useStreamingText.ts       # 流式文本渲染
│   └── utils/                  # 工具 hooks
│   │   ├── index.ts
│   │   ├── useStreamingRender.ts     # 批处理渲染
│   │   └── useThrottleCallback.ts    # 防抖节流
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
│   │   ├── StreamingText.tsx
│   │   ├── ThinkingIndicator.tsx
│   │   ├── DimensionSection.tsx
│   │   ├── LayerReportCard.tsx
│   │   ├── ReviewPanel.tsx
│   │   ├── LayerReportMessage.tsx
│   │   ├── DimensionReportStreaming.tsx
│   │   ├── DimensionSelector.tsx
│   │   ├── CheckpointMarker.tsx
│   │   ├── ProgressPanel.tsx
│   │   ├── ToolStatusPanel.tsx
│   │   └── FileViewerSidebar.tsx
│   ├── layer/                  # Layer 组件
│   │   └── LayerSidebar.tsx
│   ├── report/                 # 报告组件
│   │   └── KnowledgeReference.tsx
│   ├── ui/                     # 通用UI组件
│   │   ├── Card.tsx
│   │   └── SegmentedControl.tsx
│   ├── MarkdownRenderer.tsx
│   └── VillageInputForm.tsx
├── lib/
│   ├── api/                    # API 客户端 (拆分模块)
│   │   ├── index.ts
│   │   ├── planning-api.ts
│   │   ├── data-api.ts
│   │   └── types.ts
│   ├── logger.ts               # 日志工具
│   ├── constants.ts            # 常量定义
│   └── utils/                  # 工具函数
│       └── index.ts
├── config/
│   ├── dimensions.ts           # 维度配置
│   └── planning.ts             # 规划配置
└── types/                      # ⭐ 类型目录重构
    ├── index.ts                # 总导出入口
    └── message/                # 消息类型模块
        ├── index.ts            # Message 联合类型
        ├── message-types.ts    # 具体消息类型定义
        ├── message-guards.ts   # 类型守卫
        └── message-helpers.ts  # 辅助函数
```

## 消息类型

系统支持 8 种消息类型：

| 类型 | 说明 | 关键字段 |
|------|------|----------|
| `text` | 普通文本 | content, streamingState, knowledgeReferences |
| `file` | 文件上传 | filename, fileContent, fileSize |
| `progress` | 进度更新 | progress, currentLayer, taskId |
| `dimension_report` | 维度报告 | layer, dimensionKey, dimensionName, streamingState |
| `layer_completed` | 层级完成 | layer, content, summary, checkpointId |
| `tool_call` | 工具调用 | toolName, toolCallId, args |
| `tool_progress` | 工具进度 | toolCallId, status, progress, message |
| `tool_result` | 工具结果 | toolCallId, result, status |

```typescript
// types/message/index.ts
export type Message =
  | TextMessage
  | FileMessage
  | ProgressMessage
  | DimensionReportMessage
  | LayerCompletedMessage
  | ToolCallMessage
  | ToolProgressMessage
  | ToolResultMessage;
```

## Hooks 架构

### Planning Hooks (`hooks/planning/`)

| Hook | 功能 | 使用场景 |
|------|------|----------|
| `usePlanningSelectors` | 粒度选择器 | 所有需要访问状态的组件 |
| `usePlanningHandlers` | 规划操作 | 启动规划、层级切换 |
| `useReviewActions` | 审查操作 | 批准/驳回/回滚 |
| `useSSEConnection` | SSE 连接 | Provider 层初始化 |
| `useMessagePersistence` | 消息持久化 | 自动保存到数据库 |
| `useSessionRestore` | 会话恢复 | 加载历史会话 |

### UI Hooks (`hooks/ui/`)

| Hook | 功能 |
|------|------|
| `useStreamingText` | 流式文本渲染动画 |

### Utils Hooks (`hooks/utils/`)

| Hook | 功能 |
|------|------|
| `useStreamingRender` | 批处理流式渲染 (RAF + 防抖) |
| `useThrottleCallback` | 防抖节流回调 |

## API 客户端

```typescript
// lib/api/planning-api.ts

// Planning API
planningApi.startPlanning(request)           // POST /start
planningApi.createStream(sessionId)          // GET /stream (SSE)
planningApi.getStatus(sessionId)             // GET /status
planningApi.getLayerReports(sessionId, layer) // GET /layers/{layer}
planningApi.approveReview(sessionId)         // POST /review (approve)
planningApi.rejectReview(sessionId, feedback, dimensions)  // POST /review (reject)
planningApi.rollbackCheckpoint(sessionId, checkpointId)    // POST /review (rollback)
planningApi.deleteSession(sessionId)         // DELETE /sessions/{id}

// lib/api/data-api.ts
dataApi.listVillages()                       // GET /villages
dataApi.getLayerContent(villageName, layerId) // GET 层级内容
dataApi.getCheckpoints(villageName)          // GET 检查点

// lib/api/knowledge-api.ts (如需)
knowledgeApi.listDocuments()                 // GET /documents
knowledgeApi.addDocument(file)               // POST /documents
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
    onApprove={handleApprove}
    onReject={handleReject}
  />
)}

// 消息类型渲染
switch (message.type) {
  case 'layer_completed': return <LayerReportMessage message={message} />;
  case 'dimension_report': return <DimensionReportStreaming message={message} />;
  case 'tool_call': return <ToolStatusPanel message={message} />;
  case 'tool_progress': return <ToolStatusPanel message={message} />;
  case 'tool_result': return <ToolStatusPanel message={message} />;
  default: return <TextMessage message={message} />;
}
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `stores/planningStore.ts` | Zustand Store (单一状态源，handleSSEEvent 处理) |
| `stores/planning-context.tsx` | Provider 包装层 (SSE + 持久化 + 恢复) |
| `hooks/planning/usePlanningSelectors.ts` | 粒度选择器 (性能优化) |
| `hooks/planning/useSSEConnection.ts` | SSE 连接管理 (批量 + 重连) |
| `hooks/planning/useMessagePersistence.ts` | 消息自动持久化 |
| `hooks/planning/useSessionRestore.ts` | 会话恢复逻辑 |
| `hooks/planning/useReviewActions.ts` | 审查操作封装 |
| `lib/api/planning-api.ts` | Planning API 客户端 |
| `config/dimensions.ts` | 28个维度配置 |
| `types/message/index.ts` | Message 联合类型 |
| `types/message/message-types.ts` | 具体消息类型定义 |
| `types/message/message-guards.ts` | 类型守卫函数 |
| `components/chat/ChatPanel.tsx` | 主界面容器 |
| `components/chat/ReviewPanel.tsx` | 审查面板 |
| `components/chat/CheckpointMarker.tsx` | 检查点时间线标记 |
| `components/chat/ToolStatusPanel.tsx` | 工具状态显示 |
| `components/layout/HistoryPanel.tsx` | 历史记录面板 |

---

## 审查与回滚功能

### 审查面板 (ReviewPanel)

当层级完成并进入暂停状态时，显示审查面板：

```
┌────────────────────────────────────────┐
│ ⏸️ 现状分析 待审查                      │
│                                        │
│ ┌─────────────┐  ┌─────────────┐      │
│ │ ✅ 批准继续  │  │ ✏️ 驳回修改  │      │
│ └─────────────┘  └─────────────┘      │
└────────────────────────────────────────┘
```

### 检查点标记 (CheckpointMarker)

在每个层级完成后，在对话时间线中显示检查点标记：

```
────────────────────────────────────────
│ 📌 Layer 1 完成 · 2024-01-15 10:30   │
│ ──────────────  ───────────────────  │
│                [恢复到此点]           │
────────────────────────────────────────
```

### 历史记录删除 (HistoryPanel)

```
┌────────────────────────────────────┐
│ 📁 某某村 (3条记录)                │
│   ├─ 2024-01-15 10:30    [🗑️]     │
│   ├─ 2024-01-14 14:20    [🗑️]     │
│   └─ 2024-01-13 09:00    [🗑️]     │
└────────────────────────────────────┘
```

---

## 工具状态显示

系统支持工具调用可视化：

```typescript
// ToolStatusPanel 显示工具执行状态
interface ToolStatus {
  toolName: string;
  status: 'running' | 'success' | 'error';
  stage?: string;
  progress?: number;
  message?: string;
  summary?: string;
}

// 工具消息类型
type ToolCallMessage = {
  type: 'tool_call';
  toolName: string;
  toolCallId: string;
  args: Record<string, unknown>;
};

type ToolProgressMessage = {
  type: 'tool_progress';
  toolCallId: string;
  status: 'running' | 'success' | 'error';
  progress?: number;
  message?: string;
};

type ToolResultMessage = {
  type: 'tool_result';
  toolCallId: string;
  result: unknown;
  status: 'success' | 'error';
};
```

---

## 性能优化要点

1. **粒度选择器**: 使用 `useMessages()` 而非 `usePlanningStore().messages`
2. **批量 SSE 处理**: 50ms 窗口合并 `dimension_delta` 事件
3. **Immer 更新**: 可变式语法，不可变结果
4. **memo 组件**: MessageBubble、MessageContent 使用 React.memo
5. **虚拟列表**: MessageList 支持大量消息渲染