# 前端组件架构文档

> **村庄规划智能体** - Next.js 前端组件架构详解

## 目录

- [架构概述](#架构概述)
- [核心组件层级](#核心组件层级)
- [组件依赖关系](#组件依赖关系)
- [数据流管理](#数据流管理)
- [SSE 集成](#sse-集成)
- [组件通信](#组件通信)

---

## 架构概述

### 技术栈

- **框架**: Next.js 14 (App Router)
- **UI 库**: React 18
- **语言**: TypeScript
- **样式**: Tailwind CSS
- **状态管理**: React Context + Hooks
- **实时通信**: Server-Sent Events (SSE)

### 组件架构原则

1. **单一职责**: 每个组件只负责一个功能
2. **自包含**: 组件包含自己的状态和逻辑
3. **可复用**: 通过 props 配置，支持多种使用场景
4. **类型安全**: 使用 TypeScript 接口定义 props

---

## 核心组件层级

### 页面层级 (Pages)

```
app/
├── layout.tsx                 # 根布局
├── page.tsx                   # 主页
└── village/                   # 村庄规划相关页面
    ├── layout.tsx             # 村庄页面布局
    └── [villageId]/          # 动态村庄页面
        └── page.tsx
```

### 组件层级树

```
RootLayout (app/layout.tsx)
└── Page (app/page.tsx)
    └── VillageInputForm
        ├── DimensionSelector
        │   └── DimensionCheckbox
        └── SubmitButton

---

VillageLayout (app/village/layout.tsx)
└── VillagePage (app/village/[villageId]/page.tsx)
    └── PlanningContainer
        ├── UnifiedPlanningContext (Provider)
        └── ChatPanel
            ├── MessageList
            │   ├── MessageBubble
            │   │   ├── MessageContent
            │   │   │   ├── StreamingText
            │   │   │   ├── MarkdownRenderer
            │   │   │   ├── CodeBlock
            │   │   │   └── ActionButtonGroup
            │   │   ├── ThinkingIndicator
            │   │   ├── LayerReportCard
            │   │   ├── ReviewInteractionMessage
            │   │   └── DimensionSection
            │   └── WelcomeCard
            ├── ChatInput
            └── ReviewDrawer (审查面板)
                ├── ReviewContent
                ├── CheckpointList
                └── ApprovalButtons
```

---

## 组件依赖关系

### 1. 布局组件

#### RootLayout
**文件**: `app/layout.tsx`

**职责**:
- 全局样式加载
- 元数据配置
- 顶层错误边界

**依赖**:
- 无

#### VillageLayout
**文件**: `app/village/layout.tsx`

**职责**:
- 村庄页面布局
- 侧边栏导航

**依赖**:
- Sidebar components

---

### 2. 表单组件

#### VillageInputForm
**文件**: `components/VillageInputForm.tsx`

**职责**:
- 村庄数据输入表单
- 文件上传处理
- 维度选择管理

**状态**:
```typescript
interface VillageInputFormProps {
  onSubmit: (data: VillageFormData) => void;
  loading?: boolean;
}

interface VillageFormData {
  project_name: string;
  village_data: string;
  task_description?: string;
  constraints?: string;
  dimensions: string[];
  step_mode?: boolean;
}
```

**依赖组件**:
- `DimensionSelector`
- `SubmitButton`

---

#### DimensionSelector
**文件**: `components/DimensionSelector.tsx`

**职责**:
- 维度选择UI
- 批量选择/取消
- 自定义维度支持

**状态**:
```typescript
interface DimensionSelectorProps {
  value: string[];
  onChange: (dimensions: string[]) => void;
  disabled?: boolean;
}
```

**依赖组件**:
- `DimensionCheckbox` (内部)

**预定义维度**:
- 区位与对外交通分析 (`location`)
- 社会经济分析 (`socio_economic`)
- 自然环境与资源分析 (`natural_environment`)
- 村庄用地分析 (`land_use`)
- 道路交通分析 (`traffic`)
- 公共服务设施分析 (`public_services`)
- 基础设施分析 (`infrastructure`)
- 生生系统分析 (`ecological_system`)
- 村庄风貌分析 (`village_style`)
- 历史文化分析 (`historical_cultural`)
- 政策与上位规划分析 (`policy_planning`)
- 上位规划与村民意愿分析 (`villager_wish`)

---

### 3. 聊天界面组件

#### ChatPanel
**文件**: `components/chat/ChatPanel.tsx`

**职责**:
- 主聊天界面
- 消息管理
- SSE 连接管理
- 审查流程处理

**状态**:
```typescript
interface ChatPanelProps {
  taskId: string | null;
  sessionId: string | null;
}

// 内部状态
interface ChatPanelState {
  status: 'idle' | 'planning' | 'paused' | 'completed' | 'error';
  showReviewPanel: boolean;
  currentCheckpoint: Checkpoint | null;
}
```

**Context 使用**:
```typescript
const {
  messages,
  addMessage,
  updateLastMessage,
  clearMessages,
  status,
  setStatus,
  taskId,
  approveReview,
  rejectReview,
  rollbackToCheckpoint,
  reconnectSSE
} = usePlanningContext();
```

**依赖组件**:
- `MessageList`
- `ChatInput`
- `ReviewDrawer`
- `useTaskSSE` (Hook)

**关键方法**:
```typescript
// 批准审查
const handleReviewApprove = useCallback(async () => {
  const response = await planningApi.approveReview(taskId);
  if (response.resumed) {
    reconnectSSE?.();  // 重新创建 SSE 连接
  }
}, [taskId, reconnectSSE]);

// 驳回审查
const handleReviewReject = useCallback(async (feedback: string) => {
  await planningApi.rejectReview(taskId, feedback, dimensions);
}, [taskId, dimensions]);

// 回退到检查点
const handleRollback = useCallback(async (checkpointId: string) => {
  await planningApi.rollbackToCheckpoint(taskId, checkpointId);
}, [taskId]);
```

---

#### MessageList
**文件**: `components/chat/MessageList.tsx`

**职责**:
- 消息列表渲染
- 滚动管理
- 空状态显示

**状态**:
```typescript
interface MessageListProps {
  messages: Message[];
  loading?: boolean;
}

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  type: 'text' | 'system' | 'error' | 'layer_report' | 'review_request' | 'checkpoint';
  content: string;
  timestamp?: string;
  metadata?: Record<string, any>;
}
```

**依赖组件**:
- `MessageBubble`
- `WelcomeCard`

---

#### MessageBubble
**文件**: `components/chat/MessageBubble.tsx`

**职责**:
- 单条消息渲染
- 根据消息类型选择内容组件

**状态**:
```typescript
interface MessageBubbleProps {
  message: Message;
}

// 消息类型映射
type MessageType = Message['type'];

type MessageContentComponent =
  | typeof StreamingText          // text, layer_report
  | typeof MarkdownRenderer       // text, layer_report
  | typeof CodeBlock              // 代码块
  | typeof ThinkingIndicator      // 思考中
  | typeof LayerReportCard        // layer_report
  | typeof ReviewInteractionMessage // review_request
  | typeof DimensionSection       // checkpoint
  | typeof ActionButtonGroup;     // 带操作的消息
```

**依赖组件**:
- `MessageContent`
- `ActionButtonGroup`

---

#### MessageContent
**文件**: `components/chat/MessageContent.tsx`

**职责**:
- 消息内容渲染
- Markdown 解析
- 代码高亮

**特性**:
- 流式文本渲染（`StreamingText`）
- Markdown 渲染（`MarkdownRenderer`）
- 代码块语法高亮（`CodeBlock`）

**依赖组件**:
- `StreamingText`
- `MarkdownRenderer`
- `CodeBlock`
- `ActionButtonGroup`

---

### 4. 实时通信组件

#### useTaskSSE Hook
**文件**: `hooks/useTaskSSE.ts` (221 行) ⭐ 已简化 (2024最新)

**职责**:
- SSE 连接管理
- 事件处理
- 自动重连
- 手动重连

#### 最新改进

1. **接口统一** - 合并 `UseTaskSSEOptions` 和 `SSEHandlerCallbacks`
2. **事件映射** - 使用 `EVENT_HANDLERS` 对象替代复杂 switch
3. **简化引用** - 减少 callbackRefs 复杂性

**状态**:
```typescript
interface UseTaskSSEOptions {
  onProgress?: (data: ProgressData) => void;
  onLayerCompleted?: (data: LayerCompletedData) => void;
  onCheckpointSaved?: (data: CheckpointData) => void;
  onPause?: (data: PauseData) => void;
  onStreamPaused?: () => void;  // ⭐ NEW
  onError?: (error: string) => void;
  onCompleted?: () => void;
}

interface UseTaskSSEReturn {
  isConnected: boolean;
  error: string | null;
  close: () => void;
  reconnect: () => void;  // ⭐ NEW: 手动重连
}
```

**事件处理映射** ⭐ NEW:
```typescript
// 简化的事件处理
const EVENT_HANDLERS = {
  progress: (e) => {
    const data = JSON.parse(e.data);
    onProgress?.(data);
  },

  layer_completed: (e) => {
    const data = JSON.parse(e.data);
    onLayerCompleted?.(data);
  },

  pause: (e) => {
    const data = JSON.parse(e.data);
    onPause?.(data);
  },

  stream_paused: (e) => {
    console.log('[SSE] Stream paused, closing connection');
    eventSourceRef.current?.close();
    onStreamPaused?.();
  },

  error: (e) => {
    const data = JSON.parse(e.data);
    onError?.(data.message || 'SSE error');
  },

  completed: (e) => {
    onCompleted?.();
  }
};

// 注册事件监听器
Object.entries(EVENT_HANDLERS).forEach(([event, handler]) => {
  es.addEventListener(event, handler);
});
```

**重连功能**:
```typescript
const reconnect = useCallback(() => {
  console.log('[useTaskSSE] Manual reconnect requested');
  if (eventSourceRef.current) {
    eventSourceRef.current.close();
  }
  initializingRef.current = false;  // 重置初始化标志
  setIsConnected(false);
}, []);
```

---

### 5. 上下文管理

#### UnifiedPlanningContext
**文件**: `contexts/UnifiedPlanningContext.tsx`

**职责**:
- 全局状态管理
- 消息管理
- 任务状态管理
- 审查流程管理

**状态**:
```typescript
interface PlanningState {
  // 任务信息
  taskId: string | null;
  sessionId: string | null;
  projectName: string | null;

  // 消息
  messages: Message[];

  // 状态
  status: TaskStatus;
  currentLayer: number | null;
  currentCheckpoint: Checkpoint | null;

  // 错误
  error: string | null;
}

type TaskStatus =
  | 'idle'
  | 'pending'
  | 'running'
  | 'paused'
  | 'reviewing'
  | 'revising'
  | 'completed'
  | 'failed';
```

**方法**:
```typescript
interface PlanningContextValue {
  // 状态
  state: PlanningState;

  // 消息管理
  addMessage: (message: Message) => void;
  updateLastMessage: (updates: Partial<Message>) => void;
  clearMessages: () => void;

  // 状态管理
  setStatus: (status: TaskStatus) => void;
  setError: (error: string | null) => void;

  // 审查操作
  approveReview: () => Promise<void>;
  rejectReview: (feedback: string, dimensions?: string[]) => Promise<void>;
  rollbackToCheckpoint: (checkpointId: string) => Promise<void>;

  // SSE 管理
  reconnectSSE: () => void;  // ⭐ NEW
}
```

---

### 6. 审查组件

#### ReviewDrawer
**文件**: `components/review/ReviewDrawer.tsx`

**职责**:
- 审查面板抽屉
- 检查点列表展示
- 批准/驳回操作

**状态**:
```typescript
interface ReviewDrawerProps {
  open: boolean;
  onClose: () => void;
  checkpoint: Checkpoint | null;
  onApprove: () => void;
  onReject: (feedback: string, dimensions?: string[]) => void;
  onRollback?: (checkpointId: string) => void;
}

interface Checkpoint {
  checkpoint_id: string;
  description: string;
  timestamp: string;
  layer: number;
  project_name: string;
  state: Record<string, any>;
}
```

**依赖组件**:
- `ReviewContent`
- `CheckpointList`
- `ApprovalButtons`

---

#### ReviewInteractionMessage
**文件**: `components/chat/ReviewInteractionMessage.tsx`

**职责**:
- 审查请求消息渲染
- 显示审查选项

**状态**:
```typescript
interface ReviewInteractionMessageProps {
  checkpoint: Checkpoint;
  onApprove: () => void;
  onReject: (feedback: string) => void;
  onRollback?: (checkpointId: string) => void;
}
```

---

### 7. 工具组件

#### MarkdownRenderer
**文件**: `components/MarkdownRenderer.tsx`

**职责**:
- Markdown 转 HTML
- 代码块语法高亮
- 表格渲染

**特性**:
- 使用 `react-markdown` 解析
- 使用 `remark-gfm` 支持 GitHub Flavored Markdown
- 使用 `react-syntax-highlighter` 高亮代码

---

#### CodeBlock
**文件**: `components/chat/CodeBlock.tsx`

**职责**:
- 代码块渲染
- 语法高亮
- 代码复制功能

**支持语言**:
- Python
- JavaScript / TypeScript
- Bash
- JSON
- Markdown
- 等 185+ 种语言

---

#### StreamingText
**文件**: `components/chat/StreamingText.tsx`

**职责**:
- 流式文本渲染
- 打字机效果
- 实时更新

**状态**:
```typescript
interface StreamingTextProps {
  content: string;
  isStreaming?: boolean;
  speed?: number;  // 打字机速度（ms/字符）
}
```

---

#### ThinkingIndicator
**文件**: `components/chat/ThinkingIndicator.tsx`

**职责**:
- 显示"思考中"动画
- 等待状态提示

**动画**:
- 三个跳动的圆点
- 渐变透明度
- 循环动画

---

#### LayerReportCard
**文件**: `components/chat/LayerReportCard.tsx`

**职责**:
- 层级报告卡片渲染
- 折叠/展开功能
- 报告摘要显示

**状态**:
```typescript
interface LayerReportCardProps {
  layer: number;
  title: string;
  report: string;
  dimensions?: string[];
  collapsed?: boolean;
  onToggle?: () => void;
}
```

---

#### DimensionSection
**文件**: `components/chat/DimensionSection.tsx`

**职责**:
- 维度报告区块渲染
- 维度图标显示
- 折叠/展开功能

**状态**:
```typescript
interface DimensionSectionProps {
  dimension: string;
  title: string;
  content: string;
  icon?: string;
}
```

**维度图标映射**:
```typescript
const DIMENSION_ICONS: Record<string, string> = {
  location: '📍',
  socio_economic: '👥',
  natural_environment: '🌳',
  land_use: '🏗️',
  traffic: '🚗',
  public_services: '🏥',
  infrastructure: '⚡',
  ecological_system: '🔄',
  village_style: '🏘️',
  historical_cultural: '📜',
  policy_planning: '📋',
  villager_wish: '💭'
};
```

---

## 数据流管理

### 1. 数据流向

```
用户输入
    ↓
VillageInputForm
    ↓
API 调用 (POST /api/planning/start)
    ↓
后端返回 session_id
    ↓
ChatPanel (taskId = session_id)
    ↓
useTaskSSE (建立 SSE 连接)
    ↓
接收 SSE 事件
    ↓
UnifiedPlanningContext (更新状态)
    ↓
MessageList (重新渲染)
```

### 2. SSE 事件流

```
后端发送事件
    ↓
useTaskSSE 监听
    ↓
解析事件数据
    ↓
调用对应的回调函数
    ↓
回调函数更新 Context 状态
    ↓
组件重新渲染
```

### 3. 审查流程数据流

```
Layer 完成
    ↓
后端发送 pause 事件
    ↓
前端显示审查面板
    ↓
用户点击批准
    ↓
调用 approveReview()
    ↓
API 调用 (POST /api/planning/review/{session_id})
    ↓
后端返回 { resumed: true }
    ↓
调用 reconnectSSE()
    ↓
创建新的 SSE 连接
    ↓
继续执行下一层
```

---

## SSE 集成

### SSE 连接生命周期

```
1. 创建连接
   useTaskSSE(taskId)
      ↓
   创建 EventSource
      ↓
   发送 GET /api/planning/stream/{session_id}

2. 接收事件
   progress → 更新进度
   layer_completed → 显示完成消息
   pause → 显示审查面板
   stream_paused → 关闭连接 ⭐
   error → 显示错误

3. 暂停状态
   后端发送 stream_paused
      ↓
   前端关闭 EventSource
      ↓
   连接状态 → disconnected

4. 批准后重连
   用户点击批准
      ↓
   调用 reconnectSSE()
      ↓
   重置初始化标志
      ↓
   创建新的 EventSource
      ↓
   继续执行

5. 完成状态
   后端发送 completed
      ↓
   前端关闭 EventSource
      ↓
   连接状态 → completed
```

### SSE 错误处理

```typescript
// 连接错误
es.addEventListener('error', (e) => {
  console.error('[SSE] Connection error:', e);
  setIsConnected(false);
  setError('SSE connection failed');
});

// 后端返回错误
es.addEventListener('error', (e) => {
  const data = JSON.parse(e.data);
  onError?.(data.message);
});
```

---

## 组件通信

### 1. Props 传递

**单向数据流**:
```
父组件 → props → 子组件
          ↓
       子组件渲染
```

**示例**:
```typescript
// ChatPanel 传递 messages 给 MessageList
<MessageList messages={messages} />

// MessageList 传递 message 给 MessageBubble
{messages.map(msg => (
  <MessageBubble key={msg.id} message={msg} />
))}
```

### 2. Context 共享

**全局状态共享**:
```typescript
// 在 ChatPanel 中使用 Context
const { messages, addMessage, status } = usePlanningContext();

// 在 ReviewDrawer 中使用相同的 Context
const { approveReview, rejectReview } = usePlanningContext();
```

### 3. 回调函数

**子组件通知父组件**:
```typescript
// VillageInputForm 通知父组件表单提交
<VillageInputForm
  onSubmit={(data) => {
    // 处理表单提交
    startPlanning(data);
  }}
/>

// ReviewDrawer 通知父组件用户操作
<ReviewDrawer
  onApprove={() => {
    // 处理批准
    handleApprove();
  }}
  onReject={(feedback) => {
    // 处理驳回
    handleReject(feedback);
  }}
/>
```

### 4. 自定义 Hooks

**逻辑复用**:
```typescript
// SSE 连接管理
const { isConnected, error, close, reconnect } = useTaskSSE(taskId, {
  onProgress: (data) => {
    console.log('Progress:', data);
  },
  onLayerCompleted: (data) => {
    console.log('Layer completed:', data.layer);
  }
});

// 消息管理
const { messages, addMessage, updateLastMessage } = useMessages();
```

---

## 性能优化

### 1. 组件懒加载

```typescript
// 动态导入审查组件
const ReviewDrawer = dynamic(
  () => import('@/components/review/ReviewDrawer'),
  { ssr: false }
);
```

### 2. 虚拟滚动

```typescript
// 使用 react-window 实现虚拟滚动
import { FixedSizeList } from 'react-window';

<FixedSizeList
  height={600}
  itemCount={messages.length}
  itemSize={100}
>
  {({ index, style }) => (
    <MessageBubble
      style={style}
      message={messages[index]}
    />
  )}
</FixedSizeList>
```

### 3. 记忆化

```typescript
// 使用 React.memo 避免不必要的重渲染
const MessageBubble = React.memo(({ message }: MessageBubbleProps) => {
  // ...
}, (prevProps, nextProps) => {
  return prevProps.message.id === nextProps.message.id &&
         prevProps.message.content === nextProps.message.content;
});

// 使用 useMemo 缓存计算结果
const sortedMessages = useMemo(() => {
  return messages.sort((a, b) =>
    new Date(a.timestamp!).getTime() - new Date(b.timestamp!).getTime()
  );
}, [messages]);
```

### 4. 防抖和节流

```typescript
// 防抖输入
const debouncedInput = useMemo(
  () => debounce((value: string) => {
    // 处理输入
  }, 300),
  []
);

// 节流滚动
const throttledScroll = useMemo(
  () => throttle(() => {
    // 处理滚动
  }, 100),
  []
);
```

---

## 类型定义

### 核心类型 - 重构版 ⭐ (2024最新)

**重要变更**: 类型系统已重构为模块化结构

#### 文件结构

**之前**: 单一 `types/message.ts` (395行)

**现在**: 5个专注文件

```
types/
├── message.ts          # 核心类型 (~175 行)
├── message-types.ts    # 具体消息类型 (~150 行)
├── message-guards.ts   # 类型守卫 (~100 行)
├── message-helpers.ts  # 消息辅助 (~80 行)
└── index.ts            # 统一导出
```

#### message.ts - 核心类型

```typescript
// 基础消息接口
export interface BaseMessage {
  id: string;
  timestamp: Date;
  role: 'user' | 'assistant' | 'system';
}

// 消息类型联合
export type Message =
  | TextMessage
  | FileMessage
  | ProgressMessage
  | ActionMessage
  | ResultMessage
  | ErrorMessage
  | SystemMessage
  | LayerCompletedMessage
  | ReviewRequestMessage
  | CheckpointListMessage
  | ReviewInteractionMessage;

// 其他核心类型
export type StreamingState = 'idle' | 'streaming' | 'paused' | 'completed';
export type MessageType = 'text' | 'file' | 'progress' | 'action' |
                        'result' | 'error' | 'system' | 'layer_completed' |
                        'review_request' | 'checkpoint_list' | 'review_interaction';
```

#### message-types.ts - 具体消息类型

```typescript
import type { BaseMessage, ActionButton } from './message';

// 文本消息
export interface TextMessage extends BaseMessage {
  type: 'text';
  content: string;
  streamingState?: StreamingState;
  streamingContent?: string;
  knowledgeReferences?: KnowledgeReference[];
}

// 层级完成消息
export interface LayerCompletedMessage extends BaseMessage {
  type: 'layer_completed';
  layer: number;
  content: string;
  summary: {
    word_count: number;
    key_points: string[];
    dimension_count?: number;
    dimension_names?: string[];
  };
  fullReportContent?: string;
  dimensionReports?: Record<string, string>;
  actions: ActionButton[];
}

// 审查交互消息
export interface ReviewInteractionMessage extends BaseMessage {
  type: 'review_interaction';
  role: 'assistant';
  layer: number;
  content: string;
  reviewState: 'pending' | 'approved' | 'rejected' | 'rolled_back';
  availableActions: ('approve' | 'reject' | 'rollback')[];
  enableDimensionSelection: boolean;
  availableDimensions?: DimensionInfo[];
  enableRollback: boolean;
  checkpoints?: Checkpoint[];
  feedbackPlaceholder: string;
  quickFeedbackOptions?: string[];
  submittedAt?: Date;
  submittedBy?: 'user';
  submissionType?: 'approve' | 'reject' | 'rollback';
  submissionFeedback?: string;
  submissionDimensions?: string[];
}

// ... 其他消息类型
```

#### message-guards.ts - 类型守卫

```typescript
import type { Message } from './message';
import type { TextMessage, LayerCompletedMessage, ReviewInteractionMessage } from './message-types';

// 检查是否为文本消息
export const isTextMessage = (msg: Message): msg is TextMessage =>
  msg.type === 'text';

// 检查是否为层级完成消息
export const isLayerCompletedMessage = (
  msg: Message
): msg is LayerCompletedMessage =>
  msg.type === 'layer_completed';

// 检查是否为审查交互消息
export const isReviewInteractionMessage = (
  msg: Message
): msg is ReviewInteractionMessage =>
  msg.type === 'review_interaction';

// ... 其他类型守卫
```

**使用示例**:
```typescript
function renderMessage(msg: Message) {
  if (isTextMessage(msg)) {
    // TypeScript 自动推断为 TextMessage
    return <StreamingText content={msg.content} />;
  }

  if (isLayerCompletedMessage(msg)) {
    // TypeScript 自动推断为 LayerCompletedMessage
    return <LayerReportCard layer={msg.layer} summary={msg.summary} />;
  }

  if (isReviewInteractionMessage(msg)) {
    // TypeScript 自动推断为 ReviewInteractionMessage
    return <ReviewPanel
      layer={msg.layer}
      reviewState={msg.reviewState}
      availableActions={msg.availableActions}
    />;
  }
}
```

#### message-helpers.ts - 辅助函数

```typescript
import type { Message, SSEEvent } from './message';
import type { ProgressMessage, ActionMessage } from './message-types';

/**
 * 将 SSE 事件转换为前端消息
 */
export function convertSSEToMessage(event: SSEEvent): Message {
  const base = {
    id: `msg-${Date.now()}-${Math.random()}`,
    timestamp: new Date(),
    role: 'assistant' as const,
  };

  // 进度更新
  if (event.status === 'running' && event.progress !== undefined) {
    return {
      ...base,
      type: 'progress',
      content: event.message || '正在处理...',
      progress: event.progress,
      currentLayer: event.current_layer,
      taskId: event.task_id,
    } as ProgressMessage;
  }

  // 暂停状态
  if (event.status === 'paused' || event.event_type === 'pause') {
    return {
      ...base,
      type: 'action',
      content: '当前层级已完成，请审查后继续',
      actions: createActionButtons('pause'),
      taskId: event.task_id,
    } as ActionMessage;
  }

  // ... 其他转换逻辑
}
```

#### index.ts - 统一导出

```typescript
/**
 * Message Types - Unified Exports
 */

// Core types
export * from './message';

// Specific message type definitions
export * from './message-types';

// Type guard functions
export * from './message-guards';

// Helper functions
export * from './message-helpers';
```

**导入方式**:
```typescript
// 从 @/types 导入所有
import { Message, TextMessage, isTextMessage } from '@/types';

// 或从具体文件导入
import { TextMessage } from '@/types/message-types';
```

### API 类型

**文件**: `types/api.ts` (已整合到 lib/api.ts)

```typescript
// API 请求类型
export interface StartPlanningRequest {
  project_name: string;
  village_data: string;
  task_description?: string;
  constraints?: string;
  enable_review?: boolean;
  step_mode?: boolean;
}

// API 响应类型
export interface StartPlanningResponse {
  success: boolean;
  session_id: string;
  status: string;
  message: string;
}

export interface ReviewActionRequest {
  action: 'approve' | 'reject' | 'rollback';
  feedback?: string;
  dimensions?: string[];
  checkpoint_id?: string;
}

export interface ReviewActionResponse {
  success: boolean;
  message: string;
  resumed?: boolean;
  stream_url?: string;
  current_layer?: number;
}

// SSE 事件类型
export interface ProgressData {
  progress: number;
  message: string;
  current_step: string;
}

export interface LayerCompletedData {
  layer: number;
  title: string;
  checkpoint_id: string;
  report_path: string;
}

export interface PauseData {
  session_id: string;
  current_layer: number;
  reason: 'pause_after_step' | 'waiting_for_review';
  checkpoint_id?: string;
}

export interface CheckpointData {
  checkpoint_id: string;
  description: string;
  layer: number;
  project_name: string;
  timestamp: string;
}
```

---

## 测试策略

### 1. 单元测试

```typescript
// 组件测试
describe('MessageBubble', () => {
  it('renders message content correctly', () => {
    const message = {
      id: '1',
      role: 'assistant',
      type: 'text',
      content: 'Hello, World!'
    };

    render(<MessageBubble message={message} />);
    expect(screen.getByText('Hello, World!')).toBeInTheDocument();
  });
});

// Hook 测试
describe('useTaskSSE', () => {
  it('connects to SSE endpoint', () => {
    const { result } = renderHook(() => useTaskSSE('task-123', {}));
    expect(result.current.isConnected).toBe(true);
  });
});
```

### 2. 集成测试

```typescript
// 完整流程测试
describe('Planning Flow', () => {
  it('completes planning workflow', async () => {
    // 1. 提交表单
    fireEvent.click(submitButton);

    // 2. 等待 Layer 1 完成
    await waitFor(() => {
      expect(screen.getByText(/Layer 1 已完成/)).toBeInTheDocument();
    });

    // 3. 批准继续
    fireEvent.click(approveButton);

    // 4. 等待完成
    await waitFor(() => {
      expect(screen.getByText(/规划任务完成/)).toBeInTheDocument();
    });
  });
});
```

### 3. E2E 测试

```typescript
// Playwright E2E 测试
test('full planning workflow', async ({ page }) => {
  await page.goto('http://localhost:3000');

  // 填写表单
  await page.fill('[name="project_name"]', '测试村庄');
  await page.fill('[name="village_data"]', '村庄数据...');
  await page.click('button[type="submit"]');

  // 等待完成
  await page.waitForSelector('[data-testid="layer-completed"]');

  // 批准
  await page.click('[data-testid="approve-button"]');

  // 验证
  await expect(page.locator('[data-testid="completed"]')).toBeVisible();
});
```

---

## 最新改进 (2024-2025年) ⭐

### Pause 事件去重机制 (2025-02-09) ⭐⭐⭐ NEW

**问题**: 审查面板重复显示和批准失败

**修复**: 前端添加 pause 事件二次去重防护

#### ChatPanel 组件修复

**文件**: `components/chat/ChatPanel.tsx`

**核心改动**:

1. **添加 pause 事件追踪 Ref** (Line 71):
```typescript
const processedPauseEventsRef = useRef<Set<number>>(new Set());
```

2. **onPause 处理器去重** (Lines 180-206):
```typescript
onPause: (data) => {
  const layer = currentLayer || 1;

  // ⭐ 去重检查
  if (processedPauseEventsRef.current.has(layer)) {
    console.log(`Pause event for Layer ${layer} already processed, skipping`);
    return;
  }

  // 标记已处理
  processedPauseEventsRef.current.add(layer);

  // 显示审查面板
  addMessage({
    type: 'review_interaction',
    layer: layer,
    reviewState: 'pending',
    ...
  } as ReviewInteractionMessage);
}
```

3. **批准后清除追踪** (Lines 385-387):
```typescript
const handleReviewInteractionApprove = async (message: ReviewInteractionMessage) => {
  const response = await planningApi.approveReview(taskId);

  // ⭐ 清除此 layer 的追踪，允许下一个 layer 的 pause 事件
  const layer = message.layer;
  processedPauseEventsRef.current.delete(layer);

  reconnectSSE?.();
};
```

4. **任务完成清理** (Lines 207-210):
```typescript
onComplete: (data: any) => {
  // ⭐ 清除所有追踪 sets
  completedLayersRef.current.clear();
  processedPauseEventsRef.current.clear();

  addMessage({
    type: 'result',
    content: `🎉 规划任务已完成！`,
  });
};
```

#### 函数调用关系图

```
┌─────────────────────────────────────────────────────────────┐
│                     ChatPanel 组件                            │
└─────────────────────────────────────────────────────────────┘
  │
  ├─> useRef<Set<number>>()  [Line 71]
  │   └─> processedPauseEventsRef.current
  │
  ├─> useTaskSSE(taskId, {  [Line ~200]
  │     onPause: (data) => {...}  [Line 180]
  │   })
  │   │
  │   └─> SSE 'pause' 事件触发
  │       └─> processedPauseEventsRef.current.has(layer)  [Line 187]
  │           ├─> True: return (跳过)  [Line 190]
  │           └─> False:
  │               ├─> processedPauseEventsRef.current.add(layer)  [Line 194]
  │               ├─> addMessage(review_interaction)  [Line 198]
  │               └─> loadCheckpoints()  [Line 217]
  │
  ├─> handleReviewInteractionApprove(message)  [Line 363]
  │   │
  │   ├─> planningApi.approveReview(taskId)  [Line 368]
  │   │   └─> POST /api/planning/review/{taskId}
  │   │       └─> { action: "approve" }
  │   │
  │   ├─> addMessage(reviewState: 'approved')  [Line 370]
  │   │
  │   ├─> processedPauseEventsRef.current.delete(layer)  [Line 386] ⭐
  │   │
  │   └─> reconnectSSE()  [Line 395]
  │
  └─> onComplete(data)  [Line 203]
      ├─> completedLayersRef.current.clear()  [Line 208]
      └─> processedPauseEventsRef.current.clear()  [Line 209] ⭐

┌─────────────────────────────────────────────────────────────┐
│                   UnifiedPlanningContext                     │
└─────────────────────────────────────────────────────────────┘
  │
  ├─> addMessage(message)  [contexts/UnifiedPlanningContext.tsx]
  │   └─> setMessages(prev => [...prev, message])
  │
  ├─> setStatus(status)  [Line 197, 391]
  │   └─> setState(prev => ({ ...prev, status }))
  │
  └─> reconnectSSE()  [Line 395]
      └─> useTaskSSE.reconnect()
          └─> 创建新的 EventSource

┌─────────────────────────────────────────────────────────────┐
│                     useTaskSSE Hook                          │
└─────────────────────────────────────────────────────────────┘
  │
  ├─> EventSource API  [hooks/useTaskSSE.ts]
  │   ├─> new EventSource(`${API_URL}/planning/stream/${taskId}`)
  │   ├─> es.addEventListener('pause', onPause)
  │   └─> es.addEventListener('stream_paused', onStreamPaused)
  │
  └─> reconnect()  [Line 150]
      ├─> eventSourceRef.current?.close()
      ├─> initializingRef.current = false
      └─> setIsConnected(false)
          └─> useEffect 触发重新连接

┌─────────────────────────────────────────────────────────────┐
│                        API Client                            │
└─────────────────────────────────────────────────────────────┘
  │
  ├─> planningApi.approveReview(taskId)  [lib/api.ts]
  │   └─> fetch POST /api/planning/review/{taskId}
  │       ├─> headers: { 'Content-Type': 'application/json' }
  │       ├─> body: JSON.stringify({ action: 'approve' })
  │       └─> return response.json()
  │
  └─> planningApi.getTaskStatus(taskId)
      └─> fetch GET /api/planning/status/{taskId}
          └─> 返回 { status, checkpoints, progress, ... }
```

#### 组件依赖关系

```typescript
// ChatPanel 依赖
ChatPanel.tsx
  ├─> types/message.ts
  │   ├─> Message (联合类型)
  │   ├─> ReviewInteractionMessage (具体类型)
  │   └─> BaseMessage (基础接口)
  │
  ├─> types/message-guards.ts
  │   └─> isReviewInteractionMessage() (类型守卫)
  │
  ├─> contexts/UnifiedPlanningContext.tsx
  │   ├─> usePlanningContext() (Hook)
  │   ├─> addMessage() (方法)
  │   ├─> setStatus() (方法)
  │   └─> reconnectSSE() (方法)
  │
  ├─> hooks/useTaskSSE.ts
  │   ├─> UseTaskSSEOptions (接口)
  │   ├─> onPause (回调)
  │   └─> reconnect (方法)
  │
  ├─> lib/api.ts
  │   ├─> planningApi.approveReview()
  │   └─> planningApi.getTaskStatus()
  │
  └─> lib/logger.ts
      └─> logger.chatPanel.info/warn/error
```

#### 数据流向图

```
┌──────────────┐
│   后端发送    │
│ pause 事件   │
└──────┬───────┘
       │ SSE
       ↓
┌──────────────┐
│ useTaskSSE   │
│ 事件监听     │
└──────┬───────┘
       │
       ↓
┌──────────────┐
│   onPause    │ ◄──────┐
│   处理器     │        │
└──────┬───────┘        │
       │                │
       ├────────────────┤
       │                │
       ↓                │
┌──────────────┐        │
│ 去重检查      │        │
│ has(layer)?  │        │
└──────┬───────┘        │
       │                │
    已处理?             │
       │                │
    ┌──┴──┐          ┌──┴──┐
   Yes    No          │     │
    │      │          │     │
    │      ↓          │     │
    │   ┌─────────┐   │     │
    │   │ 标记     │   │     │
    │   │ 已处理   │   │     │
    │   └────┬────┘   │     │
    │        │        │     │
    │        ↓        │     │
    │   ┌─────────┐   │     │
    │   │ return   │   │     │
    │   └─────────┘   │     │
    │                  │     │
    │                  │     │
    └──────────────────┘     │
             │              │
             ↓              │
       ┌────────────┐       │
       │ addMessage  │       │
       │ review_     │       │
       │ interaction │       │
       └──────┬─────┘       │
              │             │
              ↓             │
       ┌────────────┐       │
       │ MessageList │       │
       │ 渲染审查面板 │       │
       └──────┬─────┘       │
              │             │
              ↓             │
       ┌────────────┐       │
       │ 用户点击    │       │
       │ 批准按钮    │       │
       └──────┬─────┘       │
              │             │
              ↓             │
       ┌────────────┐       │
       │ handleApprove│      │
       └──────┬─────┘       │
              │             │
              ├─────────────┘
              │
              ↓
       ┌────────────┐
       │ 清除追踪    │ ◄───┐
       │ delete(layer)│     │
       └──────┬─────┘     │
              │           │
              ↓           │
       ┌────────────┐     │
       │ reconnectSSE│     │
       └──────┬─────┘     │
              │           │
              ↓           │
       ┌────────────┐     │
       │ 新 SSE 连接 │     │
       │ 继续 Layer 2│     │
       └────────────┘     │
                          │
                          ↓ 等待下一个 pause 事件
```

#### 关键改进点

1. **双重去重防护** ✅
   - 后端：`sent_pause_events` Set 追踪
   - 前端：`processedPauseEventsRef` 追踪
   - 即使某一层失败，另一层也能提供保护

2. **状态一致性** ✅
   - 批准后前后端同步清除追踪
   - 允许下一个 layer 的 pause 事件被处理

3. **清理机制** ✅
   - 批准后：清除当前 layer 的追踪
   - 任务完成：清除所有追踪

**修复效果**:
- ✅ 每个 Layer 只显示一个审查面板
- ✅ 点击批准立即成功，无错误
- ✅ 顺畅的 Layer 1 → 2 → 3 执行流程

---

### 架构简化与代码清理 (2024)

#### 1. 类型系统重构

#### 1. 类型系统重构

**变更**: 将单一 `message.ts` (395行) 拆分为5个专注文件

**新文件结构**:
```
types/
├── message.ts          # 核心类型 (~175 行)
├── message-types.ts    # 具体消息类型 (~150 行)
├── message-guards.ts   # 类型守卫 (~100 行)
├── message-helpers.ts  # 消息辅助 (~80 行)
└── index.ts            # 统一导出
```

**优势**:
- ✅ 更好的组织 - 相关类型集中在专门文件
- ✅ 更容易查找 - 快速定位特定类型定义
- ✅ 清晰的职责 - 每个文件有明确的目的
- ✅ 类型安全 - 类型守卫确保运行时安全
- ✅ 向后兼容 - 通过 index.ts 保持原有导入方式

#### 2. 删除未使用文件

**删除的文件**:
- `frontend/src/config/features.ts` (238 行) - 未被导入
- `frontend/src/components/report/index.ts` (8 行) - 占位符
- `src/subgraphs/concept_subgraph.py.backup` - 备份文件
- `src/subgraphs/detailed_plan_prompts.py.backup` - 备份文件

**净减少**: ~250行代码

#### 3. 代码简化

**useTaskSSE Hook** (221 行):
- ✅ 统一接口定义 (合并 UseTaskSSEOptions 和 SSEHandlerCallbacks)
- ✅ 事件处理器映射对象 (替代复杂 switch 语句)
- ✅ 简化 callbackRefs 引用管理

**api.ts** (487 行):
- ✅ 删除重复的 uploadFile 方法
- ✅ 修复默认导出
- ✅ 统一错误处理模式

**ChatPanel.tsx** (~640 行):
- ✅ 从 1,033 行减少到 ~640 行
- ✅ 提取复杂逻辑到 hooks 和 utils
- ✅ 优化导入路径 (使用 @/types)

#### 4. 新增加常量文件

**创建**: `frontend/src/lib/constants.ts` (~60 行)

**内容**:
- 层级映射常量 (LAYER_ID_MAP, LAYER_LABEL_MAP)
- 文件上传配置 (MIN_FILE_CONTENT_LENGTH, FILE_ACCEPT)
- 辅助函数 (getLayerId, getLayerName, isInputDisabled)

**优势**:
- 消除重复代码
- 统一配置管理
- 提高可维护性

### 代码质量提升 (2024)

#### 验证结果

- ✅ **TypeScript 编译**: PASSED (无类型错误)
- ✅ **生产构建**: PASSED (编译成功)
- ✅ **导入验证**: PASSED (无损坏的导入)

#### 网络影响

- **代码行数**: 净减少 ~400 行
- **文件数量**: +8 (新增) -3 (删除) = +5
- **组织结构**: 显著改善
- **可维护性**: 大幅提升

---

### UI 状态管理优化 (2025) ⭐ NEW

#### ViewMode 计算属性

**新增**: `UnifiedPlanningContext` 中的 ViewMode 系统

**功能**:
- 统一管理视图模式（chat/report/review）
- 自动响应状态变化
- 消除分散的状态管理代码

**实现**:
```typescript
// 计算属性：根据当前状态确定视图模式
const viewMode = useMemo<ViewMode>(() => {
  if (status === 'paused' || status === 'reviewing') {
    return 'review';
  }
  if (currentLayer && currentLayer > 0) {
    return 'report';
  }
  return 'chat';
}, [status, currentLayer]);
```

#### UnifiedContentSwitcher 组件

**新增**: Smart Container 模式内容切换器

**职责**:
- 根据 ViewMode 自动切换显示内容
- 集中管理视图状态逻辑
- 简化组件树结构

**使用方式**:
```tsx
<UnifiedContentSwitcher
  viewMode={viewMode}
  messages={messages}
  currentLayer={currentLayer}
  dimensionReports={dimensionReports}
/>
```

#### 优势

- ✅ **单一真相来源**：所有视图状态集中管理
- ✅ **自动响应**：状态变化自动更新视图
- ✅ **代码简化**：减少条件判断和状态管理代码
- ✅ **易于扩展**：添加新视图模式只需修改一处

---

### 历史会话管理 (2025) ⭐ NEW

#### 功能特性

**会话列表**:
- 查看所有历史村庄会话
- 按时间倒序排列
- 显示会话状态和进度

**会话加载**:
- 从历史会话恢复
- 创建新的 SSE 连接
- 保留所有检查点和消息

**实现**:
```typescript
// 获取会话列表
const sessions = await planningApi.getSessions();

// 加载历史会话
const result = await planningApi.loadSession(sessionId);
```

---

### 组件清理 (2025) ⭐ NEW

#### 删除的组件 (12个)

**布局组件**:
- 删除未使用的布局容器组件
- 简化页面结构

**报告组件**:
- 删除占位符文件
- 整合到聊天流中显示

**净减少**: 约 1000-1500 行代码

#### 保留的核心组件

**聊天界面** (13个组件):
- ChatPanel, MessageList, MessageBubble, MessageContent
- StreamingText, LayerReportCard, DimensionSection
- ReviewInteractionMessage, CodeBlock, ThinkingIndicator
- WelcomeCard, ActionButtonGroup

**布局组件** (3个组件):
- Header, HistoryPanel, UnifiedContentSwitcher ⭐ NEW

**审查组件** (1个组件):
- ReviewPanel

### 使用指南

#### 更新导入方式

**之前** (仍然支持):
```typescript
import { Message, TextMessage } from '@/types/message';
```

**现在** (推荐):
```typescript
import { Message, TextMessage, isTextMessage } from '@/types';
```

**或从具体文件导入**:
```typescript
import { TextMessage } from '@/types/message-types';
import { isTextMessage } from '@/types/message-guards';
```

#### 添加新消息类型

1. 在 `message-types.ts` 中定义接口:
```typescript
export interface CustomMessage extends BaseMessage {
  type: 'custom';
  customField: string;
}
```

2. 在 `message.ts` 的 `Message` 联合类型中添加:
```typescript
export type Message =
  | TextMessage
  | CustomMessage  // 添加这里
  | ProgressMessage
  // ...
```

3. 在 `message-guards.ts` 中添加类型守卫:
```typescript
export const isCustomMessage = (msg: Message): msg is CustomMessage =>
  msg.type === 'custom';
```

4. 在 `MessageContent.tsx` 中添加渲染逻辑:
```typescript
if (isCustomMessage(msg)) {
  return <CustomRenderer message={msg} />;
}
```

---

## 常见问题

### Q: 如何添加新的消息类型？

A: 在 `types/message.ts` 中添加新的 `MessageType`，然后在 `MessageContent.tsx` 中添加对应的渲染逻辑。

### Q: 如何自定义 SSE 事件处理？

A: 在 `useTaskSSE` 中传入自定义的回调函数：
```typescript
useTaskSSE(taskId, {
  onProgress: (data) => { /* 自定义处理 */ },
  onLayerCompleted: (data) => { /* 自定义处理 */ }
});
```

### Q: 如何实现消息持久化？

A: 在 `UnifiedPlanningContext` 中添加 `useEffect`，监听 `messages` 变化并保存到 localStorage：
```typescript
useEffect(() => {
  localStorage.setItem('messages', JSON.stringify(messages));
}, [messages]);
```

---

## 参考资源

- [Next.js 文档](https://nextjs.org/docs)
- [React 文档](https://react.dev/)
- [TypeScript 文档](https://www.typescriptlang.org/docs/)
- [Tailwind CSS 文档](https://tailwindcss.com/docs)
- [MDN: Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
