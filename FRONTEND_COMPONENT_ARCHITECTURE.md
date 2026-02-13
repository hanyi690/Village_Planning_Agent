# 前端组件架构文档 (Frontend Component Architecture)

> **村庄规划智能体** - Next.js 前端组件架构详解

## 目录

- [架构概述](#架构概述)
- [维度级流式响应架构](#维度级流式响应架构)
- [数据流管理](#数据流管理)
- [组件层级](#组件层级)
- [类型系统](#类型系统)
- [API 客户端](#api-客户端)

---

## 架构概述

### 技术栈

- **框架**: Next.js 14 (App Router)
- **UI 库**: React 18
- **语言**: TypeScript
- **样式**: Tailwind CSS
- **状态管理**: React Context + Hooks
- **实时通信**: REST 轮询 + Server-Sent Events (SSE)

### 组件架构原则

1. **单一职责**: 每个组件只负责一个功能
2. **自包含**: 组件包含自己的状态和逻辑
3. **可复用**: 通过 props 配置，支持多种使用场景
4. **类型安全**: 使用 TypeScript 接口定义 props

---

## 维度级流式响应架构

### 架构设计原则

**REST 职责**：可靠的状态同步（每 2 秒轮询）
- 完整的状态管理
- 数据库单一真实源
- 层级完成、暂停、审查状态

**SSE 职责**：维度级实时流式推送
- `dimension_delta` - 维度增量 token
- `dimension_complete` - 维度完成
- `layer_progress` - 层级进度

### 完整数据流

```
┌─────────────────────────────────────────────────────┐
│                    前端 (Next.js)             │
│  ┌──────────────────────────────────────────┐      │
│  │         ChatPanel (主界面 - 批处理渲染) │      │
│  │  ┌────────────────────────────────────┐ │      │
│  │  │  useStreamingRender (RAF 批处理)  │ │      │
│  │  └────────────────────────────────────┘ │      │
│  │  ┌────────────────────────────────────┐ │      │
│  │  │  useTaskSSE (维度级回调)        │ │      │
│  └──────────────────────────────────────────┘      │
│  │  ┌────────────────────────────────────┐ │      │
│  │  │  TaskController (REST 轮询)     │ │      │
│  └──────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────┐
│                 后端 (FastAPI)                 │
│  ┌──────────────────────────────────────────┐      │
│  │  异步数据库 (SQLite)                 │      │
│  └──────────────────────────────────────────┘      │
│  ┌──────────────────────────────────────────┐      │
│  │  StreamingQueueManager (维度级批处理) │      │
│  └──────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────┘
```

---

## 数据流管理

### UnifiedPlanningContext

**文件**: `contexts/UnifiedPlanningContext.tsx`

**职责**: 单一真实源，管理所有规划状态

**状态结构**:
```typescript
interface PlanningState {
  // 任务信息
  taskId: string | null;
  sessionId: string | null;
  projectName: string | null;

  // 消息（UI 状态通过 messages 数组表示）
  messages: Message[];

  // 状态
  status: TaskStatus;
  currentLayer: number | null;
  currentCheckpoint: Checkpoint | null;

  // 错误
  error: string | null;
}
```

### TaskController 集成模式

**文件**: `controllers/TaskController.tsx`

**职责**: 无头状态管理，协调 REST 轮询和 SSE 回调

**关键特性**:
- REST 轮询每 2 秒获取状态
- SSE 事件处理（维度级流式）
- 稳定回调引用
- 防止状态同步死循环

### 消息驱动的 UI 状态管理

**核心思想**: 所有 UI 状态通过 messages 数组表示

**消息类型**:
```typescript
type Message =
  | TextMessage              // 文本消息
  | ProgressMessage          // 进度消息
  | ActionMessage           // 操作消息
  | LayerCompletedMessage   // 层级完成消息
  | ReviewInteractionMessage // 审查交互消息
  | ErrorMessage;          // 错误消息
```

---

## 组件层级

### 组件层级树

```
RootLayout (app/layout.tsx)
└── Page (app/page.tsx)
    └── VillageInputForm
        ├── DimensionSelector
        └── SubmitButton

---

VillageLayout (app/village/layout.tsx)
└── VillagePage (app/village/[villageId]/page.tsx)
    └── PlanningContainer
        ├── UnifiedPlanningContext (Provider)
        └── ChatPanel
            ├── MessageList
            │   ├── MessageBubble
            │   ├── MessageContent
            │   │   ├── StreamingText
            │   │   ├── MarkdownRenderer
            │   │   └── CodeBlock
            │   ├── LayerReportCard
            │   ├── DimensionSection
            │   └── ReviewInteractionMessage
            └── ReviewDrawer
                ├── ReviewContent
                ├── CheckpointList
                └── ApprovalButtons
```

### 核心组件列表

**聊天界面组件**:
| 组件 | 文件 | 职责 |
|---------|------|------|
| **ChatPanel** | `components/chat/ChatPanel.tsx` | 主聊天面板，集成批处理渲染 |
| **MessageList** | `components/chat/MessageList.tsx` | 消息列表 |
| **MessageContent** | `components/chat/MessageContent.tsx` | 消息内容 |
| **StreamingText** | `components/chat/StreamingText.tsx` | 流式文本 |
| **LayerReportCard** | `components/chat/LayerReportCard.tsx` | 层级报告 |
| **DimensionSection** | `components/chat/DimensionSection.tsx` | 维度区块 |
| **ReviewInteractionMessage** | `components/chat/ReviewInteractionMessage.tsx` | 审查交互 |

**布局组件**:
| 组件 | 文件 | 职责 |
|---------|------|------|
| **Header** | `components/layout/Header.tsx` | 页头 |
| **HistoryPanel** | `components/layout/HistoryPanel.tsx` | 历史会话 |
| **UnifiedContentSwitcher** | `components/layout/UnifiedContentSwitcher.tsx` | 内容切换器 |

**控制器和 Hooks**:
| 组件/Hook | 文件 | 职责 |
|-------------|------|------|
| **TaskController** | `controllers/TaskController.tsx` | 状态管理层 |
| **UnifiedPlanningContext** | `contexts/UnifiedPlanningContext.tsx` | 统一规划上下文 |
| **useTaskSSE** | `hooks/useTaskSSE.ts` | SSE 连接 Hook |
| **useStreamingRender** | `hooks/useStreamingRender.ts` | 批处理渲染 Hook |

---

## 类型系统

### 类型系统拆分

**文件结构**:
```
frontend/src/lib/types/
├── message-types.ts    # 具体消息类型定义
├── message-guards.ts   # 类型守卫函数
├── message-creators.ts # 消息创建工厂函数
└── index.ts           # 统一导出
```

### 核心类型定义

**message-types.ts**:
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
  | ProgressMessage
  | ActionMessage
  | LayerCompletedMessage
  | ReviewInteractionMessage
  | ErrorMessage;

// 流式状态
export type StreamingState = 'idle' | 'streaming' | 'paused' | 'completed';

// 任务状态
export type TaskStatus =
  | 'idle'
  | 'pending'
  | 'running'
  | 'paused'
  | 'reviewing'
  | 'revising'
  | 'completed'
  | 'failed';
```

---

## API 客户端

### API Client

**文件**: `lib/api.ts`

**职责**: 封装所有后端 API 调用，带重试机制

**核心方法**:
```typescript
class PlanningAPI {
  private baseURL: string;
  private maxRetries: number = 3;
  private retryDelay: number = 1000;

  // 开始规划
  async startPlanning(data: StartPlanningRequest): Promise<StartPlanningResponse>;

  // 获取任务状态 (REST 轮询 - 每 2 秒)
  async getStatus(taskId: string): Promise<TaskStatusResponse>;

  // 审查操作
  async submitReview(taskId: string, action: ReviewAction): Promise<ReviewResponse>;

  // 带指数退避的重试机制
  private async withRetry<T>(fn: () => Promise<T>): Promise<T>;
}

// 单例导出
export const planningApi = new PlanningAPI(process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000');
```

### SSE 事件类型

**文件**: `hooks/useTaskSSE.ts`

```typescript
export interface UseTaskSSECallbacks {
  // 维度级流式回调
  onDimensionDelta?: (
    dimensionKey: string,
    dimensionName: string,
    layer: number,
    chunk: string,
    accumulated: string
  ) => void;

  onDimensionComplete?: (
    dimensionKey: string,
    dimensionName: string,
    layer: number,
    fullContent: string
  ) => void;

  onLayerProgress?: (
    layer: number,
    completed: number,
    total: number
  ) => void;
}
```

---

## 相关文档

- **[前端视觉指南](FRONTEND_VISUAL_GUIDE.md)** - UI/UX 设计规范、色彩系统
- **[前端实现文档](docs/frontend.md)** - Next.js 14 技术栈、维度级流式响应、SSE/REST 解耦
- **[后端实现文档](docs/backend.md)** - FastAPI 架构、异步数据库、流式队列
- **[核心智能体文档](docs/agent.md)** - LangGraph 架构、三层规划系统
- **[README](README.md)** - 项目概述和快速开始

---

**最后更新**: 2026-02-12
**维护者**: Village Planning Agent Team
