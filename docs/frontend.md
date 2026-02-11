# 前端实现文档 (Frontend Implementation)

## 架构概述

本文档说明村庄规划智能体的前端实现细节，包括 Next.js 14 技术栈、组件架构、数据流、类型系统和构建部署。

---

## 目录

- [技术栈](#技术栈)
- [SSE/REST 解耦架构](#sse-rest-解耦架构)
- [数据流与状态管理](#数据流与状态管理)
- [组件架构](#组件架构)
- [类型系统](#类型系统)
- [API 客户端](#api-客户端)
- [构建部署](#构建部署)

---

## 技术栈

### 核心框架

- **Next.js 14** - React 框架 (App Router)
- **TypeScript** - 类型安全开发
- **Tailwind CSS** - 实用优先级 CSS 框架

### 开发工具

- **ESLint** - 代码规范检查
- **Prettier** - 代码格式化
- **TypeScript Compiler** - 类型检查

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
- 仅负责流式文本效果（打字机效果）
- 实时 token 推送
- 维度级增量事件（⭐ NEW）

### 数据流图

```
┌─────────────────────────────────────────────────────┐
│                      前端 (Next.js)                │
│  ┌──────────────────────────────────────────────┐   │
│  │         TaskController (状态管理层)             │   │
│  │  ┌───────────────────────────────────────────────┤   │   │
│  │  │  ├─ REST 轮询 (每 2 秒)                    │   │   │
│  │  │  │  ├─ GET /api/planning/status/{id}          │   │   │
│  │  │  │  ├─ layer_1_completed                   │   │   │
│  │  │  │  ├─ layer_2_completed                   │   │   │
│  │  │  │  ├─ pause_after_step                    │   │   │
│  │  │  │  ├─ waiting_for_review                 │   │   │
│  │  │  │  ├─ execution_complete                  │   │   │
│  │  │  │  └──────────────────────────────────────────────┘ │   │
│  │  └─────────────────────────────────────────────┘ │   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  │         UnifiedPlanningContext (全局状态)         │   │
│  │  │  ├───────────────────────────────────────────────┤   │   │
│  │  │  │  ├─ messages (消息列表)                   │   │   │
│  │  │  │  ├─ status: TaskStatus                      │   │   │
│  │  │  │  ├─ ... (其他状态)                        │   │   │
│  │  │  │  └─────────────────────────────────────────────┘ │   │
│  │  ┌─────────────────────────────────────────────────────┤   │
│  │  │          useStreamingRender Hook (批处理渲染)    │   │
│  │  │  ├───────────────────────────────────────────────┤   │   │
│  │  │  │  ├─ addToken (维度 token 批处理)        │   │   │
│  │  │  │  │  ├─ updateMessages (UI 更新)             │   │   │
│  │  │  │  └──────────────────────────────────────────────┘ │
│  │  ┌─────────────────────────────────────────────────────┐   │
│  │       SSE 连接 (仅流式文本)                 │   │
│  │       ├─ dimension_delta (NEW - 维度增量)      │   │
│  │       ├─ dimension_complete (NEW - 维度完成)      │   │
│  │       ├─ layer_progress (NEW - 层级进度)          │   │
│  │       └─ error (错误通知)                        │   │
└─────────────────────────────────────────────────────┘ │
                    ▼                             ▼
┌─────────────────────────────────────────────────────┐
│              后端 (FastAPI)                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              SQLite 数据库 (单一真实源)      │   │
│  │       ├─ planning_sessions 表                 │   │
│  │       │  ├─ dimension_reports 表              │   │
│  │       │  └─ checkpoints 表                   │   │
│  └─────────────────────────────────────────────────────┘ │
                    ▼                             ▼
┌─────────────────────────────────────────────────────┐
│              StreamingQueueManager (NEW - 后端)    │   │
│  │       ├─ 维度级 token 批处理 (50 tokens 或 100ms)      │   │
│  │       ├─ 线程安全 (Lock 保护)                     │   │
│  │       ├─ flush_callback (SSE 发送维度事件)        │   │
│  │       └─ AsyncStoragePipeline (NEW - 存储)      │   │
│  │           ├─ 维度完成 → Redis (立即)          │   │
│  │           ├─ 层级完成 → SQLite (批量)        │   │
│  │           ├─ 文件写入 (后台任务)                │   │
│  │           └─ Session cleanup (自动清理)           │   │
└─────────────────────────────────────────────────────────────┘
                    ▼                             ▼
```

**关键特性**：
- ✅ **REST 可靠性**: 每 2 秒轮询状态变化
- ✅ **SSE 实时性**: Token → 前端 < 100ms 延迟
- ✅ **维度级流式**: 每个维度独立推送，不等待整体完成
- ✅ **批处理优化**: RAF 批量更新 DOM，防抖内容刷新
- ✅ **异步存储**: 维度完成立即缓存到 Redis，不阻塞流式传输

---

## 数据流与状态管理

### 数据流架构

**1. 维度级流式数据流（⭐ NEW）**

```
LLM Token 生成
    ↓
UnifiedPlannerBase (带 streaming_queue 参数)
    ↓
StreamingQueueManager.add_token()
    ├─ 按 50 tokens 或 100ms 批处理
    ├─ 线程安全 (Lock 保护)
    └─ flush_callback (SSE 事件发射)
    ↓
SSE 事件发射器
    ├─ dimension_delta (NEW - 维度增量)
    ├─ dimension_complete (NEW - 维度完成)
    └─ layer_progress (NEW - 层级进度)
    ↓
后端 SSE 发送 (Server-Sent Events)
    ↓
前端 SSE 接收 (useTaskSSE Hook)
    ↓
useStreamingRender.addToken()
    ├─ RAF 批处理渲染 (减少 DOM 更新)
    ├─ 防抖内容刷新 (100ms)
    └─ updateMessages() (UI 更新)
```

**2. 状态管理流**

```
LangGraph 执行完成
    ↓
数据库更新 (原子操作)
    ├─ layer_X_completed = True
    └─ update_session_state_safe()
    ↓
REST 轮询检测到状态变化
    ├─ TaskController.getStatus()
    ├─ 状态变化: !prevState.layer1Completed && status.layer1Completed
    └─ 触发 onLayerCompleted(1) 回调
    ↓
前端 UI 更新
    ├─ setTaskState(newState)
    └─ 组件重新渲染
```

### 维度级流式事件（⭐ NEW）

**事件类型**：

| 事件类型 | 说明 | 数据结构 | 使用场景 |
|----------|-----------|----------|------------|
| **dimension_delta** | 维度增量事件 | `{"type":"dimension_delta","data":{"dimension_key":"location","dimension_name":"区位分析","layer":1,"chunk":"...","accumulated":"完整内容","timestamp":"..."}}` | LLM 生成新 token 时，立即通过流式队列推送到前端 |
| **dimension_complete** | 维度完成事件 | `{"type":"dimension_complete","data":{"dimension_key":"location","dimension_name":"区位分析","layer":1,"full_content":"完整维度的报告内容...","timestamp":"..."}}` | 维度生成完成时，标记维度为完成状态，返回完整内容 |
| **layer_progress** | 层级进度事件 | `{"type":"layer_progress","data":{"layer":1,"completed":2,"total":12,"percentage":16}}` | 层级内多个维度完成时，发送进度更新事件 |

**前端处理流程**：

```typescript
// useTaskSSE Hook 配置
const callbacks = {
  onDimensionDelta: (dimensionKey, dimensionName, layer, chunk, accumulated) => {
    // 维度增量回调
    useStreamingRender.addToken(dimensionKey, chunk, accumulated);
  },

  onDimensionComplete: (dimensionKey, dimensionName, layer, fullContent) => {
    // 维度完成回调
    useStreamingRender.completeDimension(dimensionKey);

    // 更新 UI 显示
    setDimensionContents(prev => {
      const next = new Map(prev);
      next.set(dimensionKey, fullContent);
      return next;
    });
  }
};

// ChatPanel 组件
export default function ChatPanel() {
  // 使用批处理渲染 Hook
  const { addToken, completeDimension } = useStreamingRender(
    (dimensionKey, content) => {
      // 更新维度内容
      setDimensionContents(prev => {
        const next = new Map(prev);
        next.set(dimensionKey, content);
        return next;
      });
    },
    { batchSize: 10, batchWindow: 50, debounceMs: 100 }
  );

  return (
    <SSEHandler
      taskId={taskId}
      callbacks={callbacks}
    />
  );
}
```

### 批处理渲染机制

**useStreamingRender Hook**（⭐ NEW）：

**功能**：
- **RAF 批处理**: 使用 `requestAnimationFrame` 批量更新 DOM
- **防抖刷新**: 100ms 防抖延迟，减少不必要的 DOM 更新
- **增量更新**: 只更新变化的部分

**配置选项**：
```typescript
interface StreamingRenderOptions {
  batchSize?: number;      // 批处理大小（token数量）
  batchWindow?: number;    // 时间窗口（ms）
  debounceMs?: number;     // 防抖延迟
}

const { addToken, completeDimension } = useStreamingRender(
  (dimensionKey, content) => {
    setDimensionContents(prev => {
      const next = new Map(prev);
      next.set(dimensionKey, content);
      return next;
    });
  },
  { batchSize: 10, batchWindow: 50, debounceMs: 100 }
);
```

**性能优化效果**：
- Token → 前端显示延迟：**< 100ms** (P95 目标)
- DOM 更新次数减少：**> 80%**（批处理优化）
- 内存占用优化：批处理缓冲区，及时清理

---

## 组件架构

### 核心组件列表

| 组件 | 文件路径 | 职责说明 |
|---------|-----------|----------|
| **ChatPanel** | `chat/ChatPanel.tsx` | 主聊天面板，集成 useStreamingRender Hook |
| **MessageList** | `chat/MessageList.tsx` | 消息列表渲染 |
| **TaskController** | `controllers/TaskController.tsx` | 状态管理层，REST 轮询 + SSE 回调 |
| **useTaskSSE** | `hooks/useTaskSSE.ts` | SSE 连接 Hook |
| **useStreamingRender** | `hooks/useStreamingRender.ts` | 批处理渲染 Hook (NEW) |

### 数据管理

**状态管理（TaskController）**：
```typescript
interface TaskState {
  status: TaskStatus;
  currentLayer: number | null;
  layer1Completed: boolean;
  layer2Completed: boolean;
  layer3Completed: boolean;
  progress: number;
  checkpoints: Checkpoint[];
  executionComplete: boolean;
}
```

**维度内容缓存（ChatPanel）**：
```typescript
const [dimensionContents, setDimensionContents] = useState<Map<string, string>>(new Map());

// 更新维度内容
const handleDimensionDelta = (dimensionKey, content) => {
  setDimensionContents(prev => {
    const next = new Map(prev);
    next.set(dimensionKey, content);
    return next;
  });
};

// 维度完成时标记
const handleDimensionComplete = (dimensionKey, fullContent) => {
  completeDimension(dimensionKey);
  setDimensionContents(prev => {
    const next = new Map(prev);
    next.set(dimensionKey, fullContent);
    return next;
  });
};
```

---

## API 客户端

### API 调用

**useTaskSSE Hook**：
```typescript
import { useTaskSSE } from '@/hooks/useTaskSSE';

export default function ChatPanel() {
  const [taskState, { approve, reject, rollback }] = useTaskController(taskId, {
    callbacks: {
      onDimensionDelta: (dimensionKey, chunk, accumulated) => {
        // 维度增量处理
        useStreamingRender.addToken(dimensionKey, chunk, accumulated);
      },

      onDimensionComplete: (dimensionKey, dimensionName, layer, fullContent) => {
        // 维度完成处理
        useStreamingRender.completeDimension(dimensionKey);
      }
    }
  });

  return (
    <SSEHandler
      taskId={taskId}
      callbacks={callbacks}
    />
  );
}
```

### 请求示例

**获取任务状态**：
```typescript
const statusData = await planningApi.getTaskStatus(taskId);
console.log('Status:', statusData);
// 输出:
{
  "layer_1_completed": true,
  "layer_2_completed": false,
  "progress": 33.3,
  "checkpoints": [...]
}
```

**维度增量事件**：
```typescript
// SSE 接收到的事件
{
  "type": "dimension_delta",
  "data": {
    "dimension_key": "location",
    "dimension_name": "区位分析",
    "layer": 1,
    "chunk": "村庄的地理位置...",
    "accumulated": "村庄的地理位置位于...",
    "timestamp": "2024-01-01T12:00:00"
  }
}
```

---

## 类型系统

### 核心接口

**Message 类型**：
```typescript
interface BaseMessage {
  id: string;
  timestamp: Date;
  role: 'user' | 'assistant' | 'system';
  type: 'text' | 'progress' | 'action' | 'layer_report' | 'review_interaction' | 'error';
  content: string;
}
```

---

## 构建部署

### 开发模式

```bash
# 开发模式（热重载）
npm run dev

# 生产构建
npm run build

# 启动生产服务
npm start
```

### 环境变量

**.env.local**：
```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

---

## 性能优化

### 批处理优化

**问题**：
- 频繁的 DOM 更新导致性能问题
- SSE 事件处理过于频繁

**解决方案**：
- 使用 `requestAnimationFrame` 批量更新
- 防抖内容刷新（100ms）
- 减少 > 80% 的 DOM 更新次数

---

## 最新改进 (2025-2026)

### 状态同步死循环修复 (2026-02-11)

**问题描述**：
- 点击"继续"按钮后，不断弹出审查消息，但不进入下一层
- React 警告：`Cannot update a component while rendering a different component`

**根本原因**：
1. **TaskController 同步回调**：在 `setState` 内部直接调用回调函数，触发父组件渲染期间的状态更新
2. **useEffect 循环依赖**：依赖 `messages` 和 `pendingReviewMessage`，两者同时变化时可能触发循环更新
3. **setStatus 副作用**：`setStatus` 直接调用 `setPendingReviewMessage(null)` 作为副作用

**解决方案**：
- ✅ **延迟回调执行**：使用 `queueMicrotask()` 在渲染完成后执行回调
- ✅ **派生状态替代冗余状态**：`pendingReviewMessage` 从 `messages` 派生，而非独立状态
- ✅ **useEffect 处理副作用**：将 `setPendingReviewMessage(null)` 移至 `useEffect`
- ✅ **添加缺失导入**：在 `UnifiedPlanningContext.tsx` 添加 `useEffect` 导入

**文件更新**：
- `frontend/src/controllers/TaskController.tsx` (NEW) - TaskController 状态管理层
- `frontend/src/components/chat/ChatPanel.tsx` - 派生状态，移除冗余 useEffect
- `frontend/src/contexts/UnifiedPlanningContext.tsx` - useEffect 副作用修复

**核心代码示例**：
```typescript
// TaskController.tsx - 延迟回调执行
setState((currentState) => {
  // 计算新状态...

  // 收集需要触发的事件
  const eventsToTrigger: Array<() => void> = [];

  if (shouldTriggerLayerCompleted) {
    eventsToTrigger.push(() => {
      callbacksRef.current.onLayerCompleted?.(layerNum);
    });
  }

  // 延迟执行所有回调，确保在渲染完成后运行
  if (eventsToTrigger.length > 0) {
    queueMicrotask(() => {
      eventsToTrigger.forEach(fn => fn());
    });
  }

  return newState;
});

// ChatPanel.tsx - 派生状态
const pendingReviewMessage = useMemo(() => {
  return messages.findLast(m =>
    isReviewInteractionMessage(m) && m.reviewState === 'pending'
  ) as ReviewInteractionMessage | null;
}, [messages]);

// UnifiedPlanningContext.tsx - useEffect 处理副作用
useEffect(() => {
  if (status === 'planning' || status === 'revising') {
    setPendingReviewMessage(null);
  }
}, [status]);
```

**验证步骤**：
1. 启动规划任务（`step_mode: true`）
2. 等待 Layer 1 完成
3. 验证：仅显示一条 layer_completed 消息
4. 点击"批准继续"
5. 验证：状态变为 'planning'，无重复审查消息
6. 验证：执行继续到 Layer 2

---

### SSE/REST 解耦重构 (2025)

**核心变更**：
- ✅ 移除复杂去重逻辑
- ✅ 分离 SSE 和 REST 职责
- ✅ 简化状态管理流程

**新增功能**：
- ✨ **维度级流式响应**：每个维度独立推送 token
- ✨ **批处理渲染 Hook**：`useStreamingRender` 优化 DOM 更新
- ✨ **异步存储管道**：`AsyncStoragePipeline` 非阻塞存储

**文件更新**：
- `frontend/src/hooks/useStreamingRender.ts` - 批处理渲染 Hook
- `frontend/src/components/chat/ChatPanel.tsx` - 集成维度级流式回调

---

## 相关文档

- **[后端实现文档](backend.md)** - FastAPI 架构、流式队列、异步存储
- **[核心智能体文档](agent.md)** - LangGraph 架构、统一规划器集成
- **[前端组件架构](FRONTEND_COMPONENT_ARCHITECTURE.md)** - 组件设计、状态管理、数据流
- **[前端视觉指南](FRONTEND_VISUAL_GUIDE.md)** - UI/UX 设计规范

---

**最后更新**: 2026-02-11
**维护者**: Village Planning Agent Team
