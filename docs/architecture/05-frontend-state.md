# 前端状态与组件架构

本文档详细说明前端状态管理架构和SSE事件处理机制。

## 目录

- [状态管理架构](#状态管理架构)
- [PlanningState接口](#planningstate接口)
- [useSSEConnectionHook](#usesseconnectionhook)
- [Signal-Fetch模式](#signal-fetch模式)

---

## 状态管理架构

### Zustand + Immer

```typescript
// frontend/src/stores/planningStore.ts
import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';

export const usePlanningStore = create<PlanningState & PlanningActions>()(
  immer((set, get) => ({
    // 状态
    conversationId: '',
    taskId: null,
    projectName: null,
    status: 'idle',

    // Agent状态（SSOT）
    phase: 'init',
    currentWave: 1,
    reports: {},

    // Actions
    setStatus: (status) => set({ status }),
    updateFromSSE: (event) => set((state) => {
      // 根据事件类型更新状态
    }),
  }))
);
```

---

## PlanningState接口

### 核心字段

```typescript
// frontend/src/stores/planningStore.ts
export interface PlanningState {
  // Session
  conversationId: string;
  taskId: string | null;
  projectName: string | null;
  status: Status;

  // Agent State (SSOT)
  phase: string;
  currentWave: number;
  reports: Reports;
  pause_after_step: boolean;
  previous_layer: number;

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
  viewerVisible: boolean;
  toolStatuses: Record<string, ToolStatus>;
}
```

### 状态派生

```typescript
// 从Agent状态派生UI状态
function deriveUIState(state: AgentState): UIState {
  return {
    currentLayer: _phaseToLayer(state.phase),
    completedLayers: {
      1: checkLayerComplete(state, 1),
      2: checkLayerComplete(state, 2),
      3: checkLayerComplete(state, 3),
    },
    isPaused: state.pause_after_step,
    pendingReviewLayer: state.pause_after_step ? state.previous_layer : null,
  };
}
```

---

## useSSEConnectionHook

### SSE连接管理

```typescript
// frontend/src/hooks/planning/useSSEConnection.ts
export function useSSEConnection(sessionId: string | null) {
  const store = usePlanningStore();
  const [lastSeq, setLastSeq] = useState(0);

  useEffect(() => {
    if (!sessionId) return;

    const es = new EventSource(`/api/planning/stream/${sessionId}`);

    // 事件处理
    es.addEventListener('dimension_start', (e) => {
      const event = parseSSEEvent(e);
      store.updateFromSSE(event);
      setLastSeq(event.seq);
    });

    es.addEventListener('dimension_delta', (e) => {
      const event = parseSSEEvent(e);
      store.appendDimensionContent(event);
    });

    es.addEventListener('dimension_complete', (e) => {
      const event = parseSSEEvent(e);
      store.completeDimension(event);
    });

    es.addEventListener('layer_completed', (e) => {
      const event = parseSSEEvent(e);
      store.completeLayer(event);
    });

    // 终止事件处理
    es.addEventListener('pause', (e) => {
      store.setPaused(true);
      es.close();
    });

    es.addEventListener('completed', (e) => {
      store.setStatus('completed');
      es.close();
    });

    return () => es.close();
  }, [sessionId]);
}
```

### 重连处理

```typescript
// 断线重连
async function reconnect(sessionId: string, fromSeq: number) {
  const response = await fetch(
    `/api/planning/stream/${sessionId}/sync?from_seq=${fromSeq}`
  );
  const { events } = await response.json();

  // 处理错过的事件
  for (const event of events) {
    store.updateFromSSE(event);
  }

  // 重新建立SSE连接
  connectSSE(sessionId);
}
```

---

## Signal-Fetch模式

### 概念

SSE发送信号（signal），REST API获取完整数据（fetch）：

```
SSE: dimension_complete信号（仅dimension_key）
    ↓
前端: 检测信号 -> 发送REST请求
    ↓
REST API: 返回完整report内容
    ↓
前端: 更新状态
```

### 实现

```typescript
// SSE事件处理
es.addEventListener('dimension_complete', (e) => {
  const { dimension_key } = parseSSEEvent(e);

  // Signal: 触发完整数据获取
  fetchDimensionReport(sessionId, dimension_key);
});

// REST API获取完整数据
async function fetchDimensionReport(sessionId: string, key: string) {
  const response = await fetch(
    `/api/planning/sessions/${sessionId}/dimensions/${key}`
  );
  const report = await response.json();
  store.setReport(key, report);
}
```

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| 状态管理 | `frontend/src/stores/planningStore.ts` |
| SSE连接 | `frontend/src/hooks/planning/useSSEConnection.ts` |
| API调用 | `frontend/src/lib/api/planning-api.ts` |
| 消息类型 | `frontend/src/types/message/message-types.ts` |

完整文件索引：[file-index.md](./file-index.md)

---

## 相关文档

- [04-backend-api](./04-backend-api.md) - SSE端点设计
- [02-agent-core](./02-agent-core.md) - Agent状态定义
- [terminology](./terminology.md) - SSE事件类型