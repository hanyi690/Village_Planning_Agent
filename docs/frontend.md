# 前端实现文档 (Frontend Implementation)

> **村庄规划智能体** - Next.js 14 前端实现详解

## 目录

- [技术栈](#技术栈)
- [SSE/REST 解耦架构](#sse-rest-解耦架构)
- [数据流管理](#数据流管理)
- [核心组件](#核心组件)
- [类型系统](#类型系统)
- [API 客户端](#api-客户端)

---

## 技术栈

### 核心框架
- **Next.js 14** - React 框架 (App Router)
- **TypeScript** - 类型安全开发
- **Tailwind CSS** - 实用优先级 CSS 框架

### 构建模式
- **开发模式**: `npm run dev` - 热模块替换（HMR）
- **生产构建**: `npm run build` - 优化打包

---

## SSE/REST 解耦架构

### 架构设计原则

**REST 职责**：
- 可靠的状态同步（每 2 秒轮询）
- 完整的状态管理
- 数据库单一真实源

**SSE 职责**：
- 维度级流式文本推送（打字机效果）
- 实时 token 推送
- 维度级增量事件

### 数据流图

```
┌─────────────────────────────────────────────────────┐
│                      前端 (Next.js)            │
│  ┌──────────────────────────────────────────┐     │
│  │         TaskController (状态管理层)      │     │
│  │  ┌────────────────────────────────────┐ │     │
│  │  │  REST 轮询 (每 2 秒)            │ │     │
│  │  │  ├─ GET /api/planning/status/{id} │ │     │
│  │  │  ├─ layer_1_completed            │ │     │
│  │  │  ├─ pause_after_step             │ │     │
│  │  │  └─ waiting_for_review          │ │     │
│  │  └────────────────────────────────────┘ │     │
│  └──────────────────────────────────────────┘     │
│  ┌──────────────────────────────────────────┐     │
│  │  useStreamingRender (批处理渲染)        │     │
│  │  ├─ addToken(dimensionKey, chunk)      │     │
│  │  └─ RAF 批处理更新                   │     │
│  └──────────────────────────────────────────┘     │
│  ┌──────────────────────────────────────────┐     │
│  │  useTaskSSE (维度级回调)              │     │
│  │  ├─ onDimensionDelta                  │     │
│  │  ├─ onDimensionComplete               │     │
│  │  └─ onLayerProgress                  │     │
│  └──────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────┐
│              后端 (FastAPI)                    │
│  ┌──────────────────────────────────────────┐     │
│  │       异步数据库 (SQLite)              │     │
│  │  └────────────────────────────────────┘ │     │
│  ┌──────────────────────────────────────────┐     │
│  │    StreamingQueueManager (维度级批处理)  │     │
│  └──────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────┘
```

### 维度级 SSE 事件

| 事件类型 | 说明 | 数据结构 |
|----------|-----------|----------|
| **dimension_delta** | 维度增量事件 | `{"dimension_key":"location","dimension_name":"区位分析","layer":1,"chunk":"...","accumulated":"完整内容"}` |
| **dimension_complete** | 维度完成事件 | `{"dimension_key":"location","dimension_name":"区位分析","layer":1,"full_content":"完整维度的报告内容..."}` |
| **layer_progress** | 层级进度事件 | `{"layer":1,"completed":2,"total":12,"percentage":16}` |

---

## 数据流管理

### UnifiedPlanningContext

**文件**: `frontend/src/contexts/UnifiedPlanningContext.tsx`

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

### TaskController

**文件**: `frontend/src/controllers/TaskController.tsx`

**职责**: 无头状态管理，协调 REST 轮询和 SSE 回调

**关键特性**:
- REST 轮询每 2 秒获取状态
- SSE 事件处理（维度级流式）
- 稳定回调引用
- 防止状态同步死循环

### 批处理渲染机制

**useStreamingRender Hook**:
- **RAF 批处理**: 使用 `requestAnimationFrame` 批量更新 DOM
- **防抖刷新**: 100ms 防抖延迟，减少不必要的 DOM 更新
- **增量更新**: 只更新变化的部分

**性能目标**:
- Token → 前端显示延迟：**< 100ms** (P95)
- DOM 更新次数减少：**> 80%**

---

## 核心组件

### 聊天界面组件

| 组件 | 文件路径 | 职责 |
|---------|-----------|------|
| **ChatPanel** | `components/chat/ChatPanel.tsx` | 主聊天面板，集成批处理渲染 |
| **MessageList** | `components/chat/MessageList.tsx` | 消息列表渲染 |
| **MessageContent** | `components/chat/MessageContent.tsx` | 消息内容渲染 |
| **DimensionSection** | `components/chat/DimensionSection.tsx` | 维度区块显示 |
| **LayerReportCard** | `components/chat/LayerReportCard.tsx` | 层级报告卡片 |
| **ReviewInteractionMessage** | `components/chat/ReviewInteractionMessage.tsx` | 审查交互消息 |
| **StreamingText** | `components/chat/StreamingText.tsx` | 流式文本组件 |

### 布局组件

| 组件 | 文件路径 | 职责 |
|---------|-----------|------|
| **MainLayout** | `components/layout/MainLayout.tsx` | 主布局 |
| **Sidebar** | `components/layout/Sidebar.tsx` | 侧边栏 |
| **HistoryPanel** | `components/layout/HistoryPanel.tsx` | 历史会话面板 |

### 控制器和 Hooks

| 组件/Hook | 文件路径 | 职责 |
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

```typescript
// 基础消息接口
export interface BaseMessage {
  id: string;
  timestamp: Date;
  role: 'user' | 'assistant' | 'system';
}

// 文本消息
export interface TextMessage extends BaseMessage {
  type: 'text';
  content: string;
  streamingState?: StreamingState;
  streamingContent?: string;
}

// 层级完成消息
export interface LayerCompletedMessage extends BaseMessage {
  type: 'layer_completed';
  layer: number;
  content: string;
  summary: {
    word_count: number;
    key_points: string[];
  };
  actions: ActionButton[];
}

// 审查交互消息
export interface ReviewInteractionMessage extends BaseMessage {
  type: 'review_interaction';
  layer: number;
  content: string;
  reviewState: 'pending' | 'approved' | 'rejected' | 'rolled_back';
  availableActions: ('approve' | 'reject' | 'rollback')[];
}
```

---

## API 客户端

### API Client

**文件**: `frontend/src/lib/api.ts`

**职责**: 封装所有后端 API 调用，带重试机制

**核心方法**:
```typescript
class PlanningAPI {
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
```

### SSE 事件处理

**文件**: `frontend/src/hooks/useTaskSSE.ts`

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

- **[后端实现文档](backend.md)** - FastAPI 架构、异步数据库、流式队列
- **[核心智能体文档](agent.md)** - LangGraph 架构、三层规划系统
- **[前端组件架构](../FRONTEND_COMPONENT_ARCHITECTURE.md)** - 组件设计、状态管理
- **[前端视觉指南](../FRONTEND_VISUAL_GUIDE.md)** - UI/UX 设计规范
- **[README](../README.md)** - 项目概述和快速开始

---

**最后更新**: 2026-02-12
**维护者**: Village Planning Agent Team
