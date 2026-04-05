# 数据和状态流转架构文档

> **相关文档**: [系统架构总览](architecture.md) | [前端实现](frontend.md) | [后端实现](backend_architecture_analysis.md)

## 概述

本文档详细描述 Village Planning Agent 系统从数据生成到前端展示的完整流程，包括状态变化、存储时机、事件发送机制和架构设计。

**核心设计原则**: **SSOT (Single Source of Truth)** - 以 LangGraph Checkpoint 为唯一真实源。

---

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              前端 (Next.js + Zustand)                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │ ChatPanel   │───>│ useSSE      │───>│ usePlanning │───>│ Zustand     │  │
│  │ (UI组件)    │    │ Connection  │    │ Store       │    │ Store       │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│                                                │            │               │
│                                                │            ▼               │
│                                                │    批量事件合并            │
└────────────────────────────────────────────────│────────────────────────────┘
         │                    │                  │
         │ REST API           │ REST API        │ SSE (批量)
         ▼                    ▼                  │
┌─────────────────────────────────────────────────────────────────────────────┐
│                              后端 (FastAPI)                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │ Planning API│───>│ SSEManager  │───>│ SSE Stream  │    │ Status API  │  │
│  │ /start      │    │ (全局状态)   │    │ /stream     │    │ /status     │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│         │                                    ▲                │             │
│         ▼                                    │                ▼             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │ Planning    │───>│ Router      │───>│ SSEPublisher│    │ version     │  │
│  │ Service     │    │ Agent Graph │    │ to Queue    │    │ 字段返回    │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      存储层 (SSOT: Checkpoint 为核心)                         │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │              LangGraph Checkpoint (唯一真实源)                         │  │
│  │  ├── UnifiedPlanningState (完整状态)                                  │  │
│  │  ├── phase, current_wave, reports                                     │  │
│  │  ├── completed_dimensions                                              │  │
│  │  └── dimension_results (Send API 自动合并)                            │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │ SQLite DB   │    │ SSE 内存队列│    │ 文件系统    │                      │
│  │ (业务元数据)│    │ deque(5000) │    │ Markdown    │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1.1 Phase 和 Layer 对应关系

| Phase | `_phase_to_layer()` | 含义 |
|-------|--------------------|------|
| `init` | `0` | 初始状态，未开始 |
| `layer1` | `1` | 正在执行 Layer 1 |
| `layer2` | `2` | 正在执行 Layer 2 |
| `layer3` | `3` | 正在执行 Layer 3 |
| `completed` | `None` | 规划完成 |

---

## 2. Router Agent 架构数据流

### 2.1 核心状态定义

```python
class UnifiedPlanningState(TypedDict):
    """Router Agent 统一状态"""

    # 核心驱动
    messages: Annotated[List[BaseMessage], add_messages]

    # 业务参数
    session_id: str
    project_name: str
    config: PlanningConfig

    # 执行进度
    phase: str                    # init(0)/layer1(1)/layer2(2)/layer3(3)/completed
    current_wave: int             # 当前波次
    reports: Dict[str, Dict[str, str]]  # {layer1: {dim: report}}
    completed_dimensions: Dict[str, List[str]]

    # Send API 自动合并
    dimension_results: Annotated[List[Dict], operator.add]
    sse_events: Annotated[List[Dict], operator.add]

    # 交互控制
    pending_review: bool
    need_revision: bool
    revision_target_dimensions: List[str]
    review_feedback: str

    # Step Mode
    step_mode: bool
    pause_after_step: bool
    previous_layer: int
```

### 2.2 Send API 数据合并

```python
# dimension_results 和 sse_events 使用 operator.add 自动合并
dimension_results: Annotated[List[Dict], operator.add]
sse_events: Annotated[List[Dict], operator.add]

# 每次 Send 返回的结果自动追加
return {
    "dimension_results": [{dimension_key: content}],
    "sse_events": [{"type": "dimension_delta", "delta": "..."}]
}
```

---

## 3. 前端状态管理 (Zustand + Immer)

### 3.1 Store 架构

```typescript
// stores/planningStore.ts
export interface PlanningState {
  conversationId: string;
  taskId: string | null;
  status: Status;
  phase: string;
  currentWave: number;
  reports: Reports;
  completedDimensions: CompletedDimensions;
  messages: Message[];
  dimensionProgress: Record<string, DimensionProgressItem>;
  // ...
}

// 创建 Store
export const usePlanningStore = create<PlanningState>()(
  immer((set, get) => ({
    // 状态
    taskId: null,
    status: 'idle',
    messages: [],

    // Actions
    setTaskId: (id) => set({ taskId: id }),
    addMessage: (msg) => set((state) => {
      state.messages.push(msg);
    }),
    handleSSEEvent: (event) => {
      // Immer 可变式更新
      // ...
    }
  }))
);
```

### 3.2 SSE 批量处理

```typescript
// hooks/planning/useSSEConnection.ts

const BATCH_WINDOW = 50; // ms
const MAX_BATCH_SIZE = 50;

export function useSSEConnection({ taskId }) {
  const batchQueueRef = useRef<BatchEvent[]>([]);
  const batchTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const processBatch = useCallback(() => {
    const events = batchQueueRef.current;
    batchQueueRef.current = [];

    // 合并 dimension_delta 事件
    const merged = mergeDimensionDeltaEvents(events);
    merged.forEach(event => handleSSEEvent(event));
  }, [handleSSEEvent]);

  // 批量处理 SSE 事件
  const enqueueEvent = useCallback((event: BatchEvent) => {
    batchQueueRef.current.push(event);

    if (batchQueueRef.current.length >= MAX_BATCH_SIZE) {
      processBatch();
    } else if (!batchTimeoutRef.current) {
      batchTimeoutRef.current = setTimeout(processBatch, BATCH_WINDOW);
    }
  }, [processBatch]);
}
```

### 3.3 粒度选择器

```typescript
// hooks/planning/usePlanningSelectors.ts

// 性能优化：只订阅需要的状态片段
export function useMessages(): Message[] {
  return usePlanningStore((state) => state.messages);
}

export function useStatus(): Status {
  return usePlanningStore((state) => state.status);
}

export function useDimensionProgressAll(): Record<string, DimensionProgressItem> {
  return usePlanningStore((state) => state.dimensionProgress);
}
```

---

## 4. 后端服务层

### 4.1 服务架构

```
backend/services/
├── planning_service.py      # 规划执行服务
│   ├── build_initial_state()
│   ├── start_planning()
│   ├── execute_graph_background()
│   └── resume_from_checkpoint()
│
├── sse_manager.py           # SSE 连接管理
│   ├── SSEManager (类)
│   ├── subscribe_session()
│   ├── publish_event()
│   └── 全局状态管理
│
├── checkpoint_service.py    # 检查点服务
│   ├── get_checkpoints()
│   ├── rollback_checkpoint()
│   └── get_checkpoint_state()
│
├── session_service.py       # 会话管理
├── review_service.py        # 审查服务
└── rate_limiter.py          # API 限流
```

### 4.2 SSEManager 全局状态

```python
class SSEManager:
    """集中式 SSE 连接和事件管理"""

    # 全局状态
    _sessions: Dict[str, Dict[str, Any]] = {}
    _session_subscribers: Dict[str, Set[asyncio.Queue]] = {}
    _active_executions: Dict[str, bool] = {}
    _stream_states: Dict[str, str] = {}

    # 线程安全锁
    _sessions_lock = Lock()
    _subscribers_lock = Lock()
    _active_executions_lock = Lock()
    _stream_states_lock = Lock()

    @classmethod
    def subscribe_session(cls, session_id: str) -> asyncio.Queue:
        """订阅 SSE 流"""
        queue = asyncio.Queue(maxsize=200)
        with cls._subscribers_lock:
            if session_id not in cls._session_subscribers:
                cls._session_subscribers[session_id] = set()
            cls._session_subscribers[session_id].add(queue)

        # 同步历史事件
        cls._sync_historical_events(session_id, queue)
        return queue

    @classmethod
    def publish_event(cls, session_id: str, event: Dict[str, Any]) -> int:
        """发布事件到所有订阅者"""
        count = 0
        with cls._subscribers_lock:
            subscribers = cls._session_subscribers.get(session_id, set())
            for queue in subscribers:
                try:
                    queue.put_nowait(event)
                    count += 1
                except asyncio.QueueFull:
                    pass
        return count
```

### 4.3 PlanningService 核心逻辑

```python
class PlanningService:
    """规划执行核心服务"""

    @staticmethod
    async def execute_graph_background(
        session_id: str,
        graph,
        initial_state: Dict[str, Any],
        checkpointer
    ):
        """后台执行 LangGraph"""
        config = {"configurable": {"thread_id": session_id}}

        # SSE 事件迭代
        async for event in graph.astream(initial_state, config, stream_mode="values"):
            # 发布 SSE 事件
            sse_event = build_sse_event(event)
            sse_manager.publish_event(session_id, sse_event)

            # 检查暂停状态
            if event.get("pause_after_step"):
                break
```

---

## 5. 事件类型和处理

### 5.1 事件类型汇总

| 事件类型 | 方向 | 数据内容 | 处理方式 |
|---------|------|---------|---------|
| `connected` | 后端→前端 | session_id | 日志记录 |
| `layer_started` | 后端→前端 | layer, layer_name | 更新当前层级 |
| `dimension_delta` | 后端→前端 | dimension_key, delta | **批量合并** (50ms) |
| `dimension_complete` | 后端→前端 | dimension_key, full_content | 更新进度 |
| `layer_completed` | 后端→前端 | layer, version | 触发 REST API |
| `pause` | 后端→前端 | layer | 显示审查面板 |
| `tool_call` | 后端→前端 | toolName, args | 显示工具状态 |
| `tool_progress` | 后端→前端 | progress, message | 更新工具进度 |
| `tool_result` | 后端→前端 | result | 完成工具调用 |
| `error` | 后端→前端 | error message | 显示错误 |

### 5.2 事件频率控制

```python
# dimension_delta 事件频率控制
DELTA_MIN_INTERVAL_MS = 500
DELTA_MIN_TOKENS = 50

should_send = (time_elapsed >= 500) or (token_count >= 50)
```

---

## 6. Signal-Fetch Pattern

### 6.1 设计原则

SSE 只发送轻量信号，不传输大型数据：

```python
# layer_completed 事件（轻量信号）
event_data = {
    "type": "layer_completed",
    "layer": layer_num,
    "has_data": len(dimension_reports) > 0,
    "dimension_count": len(dimension_reports),
    # 不包含 report_content
}
```

### 6.2 前端处理

```typescript
// layer_completed 事件触发 REST API
case 'layer_completed':
  const reports = await planningApi.getLayerReports(taskId, event.layer);
  setLayerReports(reports);
  break;
```

---

## 7. 恢复和重连机制

### 7.1 SSE 重连

```typescript
// useSSEConnection.ts
const MAX_RECONNECT_ATTEMPTS = 5;

const handleSSEError = () => {
  if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
    // 先同步状态
    syncBackendState();

    // 指数退避重连
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 5000);
    setTimeout(() => createConnection(), delay);
  }
};
```

### 7.2 会话恢复

```typescript
// hooks/planning/useSessionRestore.ts
export function useSessionRestore({ conversationId }) {
  const restoreSession = useCallback(async () => {
    // 1. 从后端获取会话状态
    const state = await planningApi.getStatus(conversationId);

    // 2. 恢复 Zustand Store
    usePlanningStore.getState().restoreState(state);

    // 3. 重新建立 SSE 连接
    // ...
  }, [conversationId]);
}
```

---

## 8. 关键设计决策

### 8.1 SSOT 架构

| 数据类型 | 存储位置 | 说明 |
|---------|---------|------|
| 完整状态 | LangGraph Checkpoint | 唯一真实源 |
| 业务元数据 | SQLite planning_sessions | status, is_executing |
| SSE 事件 | 内存 deque(maxlen=5000) | 阅后即焚 |

### 8.2 批量处理优化

- 前端：50ms 窗口合并 dimension_delta 事件
- 后端：500ms/50 tokens 频率控制
- Zustand：Immer 可变式更新，不可变结果

### 8.3 粒度选择器

```typescript
// ✅ Good - 只在 messages 变化时重渲染
const messages = useMessages();

// ❌ Bad - 整个状态变化都会重渲染
const state = usePlanningStore();
const messages = state.messages;
```

---

## 9. 调试日志追踪

### 9.1 后端日志点

| 位置 | 日志内容 | 级别 |
|------|---------|------|
| `SSEManager.subscribe_session` | 订阅者数量 | INFO |
| `SSEManager.publish_event` | 事件类型、订阅者数 | INFO |
| `PlanningService.execute_graph_background` | 阶段变化、暂停状态 | INFO |

### 9.2 前端日志点

| 位置 | 日志内容 | 级别 |
|------|---------|------|
| `useSSEConnection.processBatch` | 批量事件数量 | DEBUG |
| `usePlanningStore.handleSSEEvent` | 事件类型 | DEBUG |
| `useSessionRestore.restoreSession` | 恢复状态 | INFO |

---

## 10. 关键文件索引

| 功能 | 文件路径 | 描述 |
|------|---------|------|
| 状态定义 | `src/orchestration/state.py` | UnifiedPlanningState |
| 后端执行 | `backend/services/planning_service.py` | execute_graph_background |
| SSE 管理 | `backend/services/sse_manager.py` | SSEManager |
| 检查点服务 | `backend/services/checkpoint_service.py` | rollback_checkpoint |
| Zustand Store | `frontend/src/stores/planningStore.ts` | 单一状态源 |
| SSE Hook | `frontend/src/hooks/planning/useSSEConnection.ts` | 批量处理 |
| 选择器 | `frontend/src/hooks/planning/usePlanningSelectors.ts` | 粒度选择器 |
| 会话恢复 | `frontend/src/hooks/planning/useSessionRestore.ts` | 恢复逻辑 |