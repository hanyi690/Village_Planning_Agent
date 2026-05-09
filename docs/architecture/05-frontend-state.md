# 前端状态与组件架构

> **更新日期**: 2026-05-09
> **版本**: v3.0 (Feature-based 重构后)
> **状态**: ✅ 已完整实现

本文档详细说明前端状态管理架构和SSE事件处理机制。

## 目录

- [Feature Module 结构](#feature-module-结构)
- [状态管理架构](#状态管理架构)
- [PlanningState接口](#planningstate接口)
- [SSE批处理机制](#sse批处理机制)
- [Dashboard布局架构](#dashboard布局架构)
- [组件使用状态](#组件使用状态)
- [关键文件路径](#关键文件路径)

---

## Feature Module 结构

### 目录架构

前端已迁移到 **feature-based 目录架构**，所有规划相关代码集中在 `features/planning/` 模块：

```
frontend/src/features/planning/
├── api/                    # API 客户端和类型定义
│   ├── types.ts            # 统一 API 类型（588行）
│   ├── planning-api.ts     # 规划流程 API
│   └── index.ts            # API 导出
├── components/             # UI 组件
│   ├── Dashboard.tsx       # 主布局（Brutalist 风格）
│   ├── DimensionCard.tsx   # 维度状态卡片
│   ├── CascadePanel.tsx    # 级联修复可视化
│   ├── MessagePanel.tsx    # 消息侧边栏
│   ├── ChatInput.tsx       # 简化输入框
│   ├── chat/               # 聊天相关组件
│   ├── gis/                # GIS 组件
│   ├── layout/             # 布局组件（Header 等）
│   └── ui/                 # UI 工具组件
├── hooks/                  # 自定义 Hooks
│   ├── useSSE.ts           # SSE 连接（批处理优化）
│   ├── useSelectors.ts     # 状态选择器
│   ├── useHandlers.ts      # 事件处理器
│   ├── usePersistence.ts   # 消息持久化
│   ├── useSessionRestore.ts # Session 恢复
│   └── index.ts            # Hooks 导出
├── store/                  # 状态管理
│   ├── planningStore.ts    # Zustand Store（~1600行）
│   └── planning-context.tsx # Context Provider
├── types/                  # 类型定义
├── config/                 # 配置
└── utils/                  # 工具函数
```

### 已删除的旧目录

以下旧目录已完全删除：

| 目录 | 原路径 | 说明 |
|------|--------|------|
| stores | `frontend/src/stores/` | 已迁移到 `features/planning/store/` |
| hooks/planning | `frontend/src/hooks/planning/` | 已迁移到 `features/planning/hooks/` |
| components/chat | `frontend/src/components/chat/` | 已迁移到 `features/planning/components/chat/` |

---

## 状态管理架构

### Zustand + Immer

```typescript
// frontend/src/features/planning/store/planningStore.ts
import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';

export const usePlanningStore = create<PlanningState & PlanningActions>()(
  immer((set, get) => ({
    // Session 状态
    conversationId: '',
    taskId: null,
    projectName: null,
    status: 'idle',

    // Agent状态（SSOT）
    phase: 'init',
    currentWave: 1,
    reports: {},
    pause_after_step: false,
    previous_layer: 0,

    // Actions
    setStatus: (status) => set({ status }),
    handleSSEEvent: (event) => set((state) => {
      // 根据事件类型更新状态
    }),
  }))
);
```

### 状态选择器 Hooks

为优化性能，使用细粒度选择器避免不必要的重渲染：

```typescript
// frontend/src/features/planning/hooks/useSelectors.ts
export function useStatus(): Status {
  return usePlanningStore((state) => state.status);
}

export function useCurrentLayer(): number | null {
  return usePlanningStore((state) => state.currentLayer);
}

export function useIsPaused(): boolean {
  return usePlanningStore((state) => state.isPaused);
}

export function useCascadeChain(): CascadeChain | null {
  return usePlanningStore((state) => state.cascadeChain);
}

export function useDimensionProgressAll(): Record<string, DimensionProgressItem> {
  return usePlanningStore((state) => state.dimensionProgress);
}
```

---

## PlanningState接口

### 核心字段

```typescript
// frontend/src/features/planning/store/planningStore.ts
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

  // RAG & Cascade Tracking (Demo System)
  dimensionRagSources: Record<string, KnowledgeSource[]>;  // 维度文档来源
  cascadeChain: CascadeChain | null;                       // 级联修复链
  dimensionVersions: Record<string, number>;               // 维度版本计数

  // Streaming State
  streamingContent: Record<string, string>;                // 流式内容临时存储
  resettingDimensions: string[];                           // 正在重置的维度

  // Simplified Tool Tracking
  runningTools: string[];                                  // 运行工具名称列表

  // UI State
  viewerVisible: boolean;
  gisLayers: Record<string, GISLayerConfig[]>;
}
```

### 新增字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `dimensionRagSources` | `Record<string, KnowledgeSource[]>` | 每个维度的RAG文档来源追踪 |
| `cascadeChain` | `CascadeChain | null` | 级联修复链可视化数据 |
| `dimensionVersions` | `Record<string, number>` | 维度版本计数，修订时递增 |
| `streamingContent` | `Record<string, string>` | 流式内容临时存储 |
| `resettingDimensions` | `string[]` | 正在重置的维度列表 |
| `runningTools` | `string[]` | 简化的运行工具名称列表 |

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

## SSE批处理机制

### 批处理参数

```typescript
const BATCH_WINDOW = 50;      // 50ms 批处理窗口
const MAX_BATCH_SIZE = 50;    // 最大队列大小
const MAX_DELTA_PER_KEY = 3;  // 每维度保留最新3个delta
```

### 关键事件类型（跳过队列）

以下事件类型立即处理，不进入批处理队列：

```typescript
const criticalEventTypes = [
  // Layer & Dimension Events
  'dimension_start',
  'dimension_complete',
  'layer_started',
  'layer_completed',
  // Tool Events (NEW System)
  'tool_started',
  'tool_status',
  // RAG & Cascade Events (Demo System)
  'rag_query',
  'rag_result',
  'cascade_impact',
  'cascade_complete',
  // Reset Events
  'dimension_reset',
  'dimension_reset_complete',
  // State Events
  'state_sync',
  'layer_paused',
];
```

### Override机制

当 `dimension_complete` 事件到达时，跳过该维度所有待处理的 `dimension_delta` 事件：

```typescript
// Track dimensions that have received complete events
const completedDimensionKeysRef = useRef<Set<string>>(new Set());

// Skip delta if dimension already received complete event
if (completedKeys.has(key)) {
  continue;
}
```

### Delta合并策略

对于同一维度的多个delta事件，只保留最新的（包含完整accumulated内容）：

```typescript
// Keep last N events for each dimension key
let deltaList = dimensionDeltaMap.get(key);
if (!deltaList) {
  deltaList = [];
  dimensionDeltaMap.set(key, deltaList);
}
deltaList.push(event);
if (deltaList.length > MAX_DELTA_PER_KEY) {
  deltaList.shift();
}
// 使用 deltaList[deltaList.length - 1] (最新一个)
```

---

## Dashboard布局架构

### Brutalist/Raw 设计风格

- 深色背景: `#0D0D0D`
- 强调色: `#00FFB3`（青绿）、`#FF3D00`（橙红）
- 2px 粗边框，无圆角
- 30/70 分屏布局

### 布局结构

```
┌─────────────────────────────────────────────────────┐
│ Header (60px fixed)                                 │
│   项目名称 | 状态指示器 | 进度条 | 控制按钮          │
├──────────────────┬──────────────────────────────────┤
│ 左面板 (30%)     │ 右面板 (70%)                     │
│ Layer 维度卡片   │ MapView (GIS可视化)              │
│  - Layer 1       │                                  │
│  - Layer 2       │                                  │
│  - Layer 3       │                                  │
├──────────────────┴──────────────────────────────────┤
│ CascadePanel (条件渲染，级联修复时显示)             │
├─────────────────────────────────────────────────────┤
│ ChatInput (60px fixed bottom)                       │
└─────────────────────────────────────────────────────┘
```

### MessagePanel 滑入动画

```typescript
// 右侧滑入动画配置
<motion.div
  className="fixed top-[60px] right-0 bottom-[60px] w-[40%]"
  initial={{ x: '100%' }}
  animate={{ x: 0 }}
  exit={{ x: '100%' }}
  transition={{ duration: 0.3, ease: 'easeOut' }}
>
  <MessagePanel messages={messages} onClose={...} />
</motion.div>
```

---

## 组件使用状态

### 新组件（Dashboard 系统）

| 组件 | 文件路径 | 使用状态 | 说明 |
|------|----------|----------|------|
| `Dashboard` | `components/Dashboard.tsx` | 主页面使用 | Brutalist 风格主布局 |
| `DimensionCard` | `components/DimensionCard.tsx` | Dashboard 使用 | 维度状态卡片 |
| `CascadePanel` | `components/CascadePanel.tsx` | Dashboard 使用 | 级联修复可视化 |
| `MessagePanel` | `components/MessagePanel.tsx` | Dashboard 使用 | 消息侧边栏 |
| `ChatInput` | `components/ChatInput.tsx` | Dashboard 使用 | 简化输入框 |

### 复用组件（chat 子目录）

| 组件 | 文件路径 | 使用状态 | 说明 |
|------|----------|----------|------|
| `MessageBubble` | `components/chat/MessageBubble.tsx` | MessagePanel 使用 | 消息气泡 |
| `MessageList` | `components/chat/MessageList.tsx` | 消息列表渲染 | 消息列表容器 |
| `StreamingText` | `components/chat/StreamingText.tsx` | 流式文本 | 流式内容显示 |
| `ToolStatusCard` | `components/chat/ToolStatusCard.tsx` | 工具状态 | 工具状态卡片 |
| `LayerReportCard` | `components/chat/LayerReportCard.tsx` | 层级报告 | 层级报告卡片 |

### 冗余组件（保留但未使用）

| 组件 | 文件路径 | 状态 | 说明 |
|------|----------|------|------|
| `ChatPanel` | `components/chat/ChatPanel.tsx` | 仅导出 | 旧聊天面板，Dashboard 不使用 |
| `ProgressPanel` | `components/chat/ProgressPanel.tsx` | 仅被 ChatPanel 导入 | 进度面板 |
| `ReviewPanel` | `components/chat/ReviewPanel.tsx` | 仅被 ChatPanel 导入 | 审核面板 |
| `DimensionSelector` | `components/chat/DimensionSelector.tsx` | 仅被 ChatPanel 导入 | 维度选择器 |

---

## SSE事件类型

### 完整事件类型列表

```typescript
// frontend/src/features/planning/api/types.ts
export type PlanningSSEEventType =
  // Tool Events (NEW System)
  | 'tool_started'
  | 'tool_status'
  // Tool Events (Legacy)
  | 'tool_call'
  | 'tool_progress'
  | 'tool_result'
  // Layer & Dimension Events
  | 'layer_started'
  | 'layer_completed'
  | 'dimension_start'
  | 'dimension_complete'
  | 'dimension_error'
  | 'dimension_delta'
  | 'dimension_revised'
  | 'dimension_reset'
  | 'dimension_reset_complete'
  // Progress Events
  | 'progress'
  | 'checkpoint_saved'
  | 'pause'
  | 'resumed'
  | 'completed'
  | 'complete'
  | 'error'
  // Streaming Events
  | 'text_chunk'
  | 'content_delta'
  | 'ai_response_delta'
  | 'ai_response_complete'
  | 'thinking_start'
  | 'thinking'
  | 'thinking_end'
  | 'stream_paused'
  // Review Events
  | 'review_request'
  // RAG & Cascade Events (Demo System)
  | 'rag_query'
  | 'rag_result'
  | 'cascade_impact'
  | 'cascade_complete'
  // State Events
  | 'state_sync'
  | 'layer_paused'
  | 'connected';
```

### 事件数据结构

```typescript
export interface PlanningSSEEvent {
  type: PlanningSSEEventType;
  session_id?: string;
  data: PlanningSSEDataBase;
}

export interface PlanningSSEDataBase {
  progress?: number;
  current_layer?: number;
  layer_number?: number;
  layer_name?: string;
  message?: string;
  error?: string;
  dimension_key?: string;
  layer?: number;
  delta?: string;
  accumulated?: string;
  full_content?: string;
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
| 状态管理 | `frontend/src/features/planning/store/planningStore.ts` |
| Context Provider | `frontend/src/features/planning/store/planning-context.tsx` |
| SSE连接 | `frontend/src/features/planning/hooks/useSSE.ts` |
| 状态选择器 | `frontend/src/features/planning/hooks/useSelectors.ts` |
| API类型 | `frontend/src/features/planning/api/types.ts` |
| API客户端 | `frontend/src/features/planning/api/planning-api.ts` |
| 主布局 | `frontend/src/features/planning/components/Dashboard.tsx` |
| 维度卡片 | `frontend/src/features/planning/components/DimensionCard.tsx` |
| 级联面板 | `frontend/src/features/planning/components/CascadePanel.tsx` |

---

## 页面集成

### page.tsx 使用

```typescript
// frontend/src/app/page.tsx
import { PlanningProvider } from '@/features/planning';
import Dashboard from '@/features/planning/components/Dashboard';

export default function Home() {
  return (
    <PlanningProvider>
      <Dashboard onOpenLayerSidebar={...} />
    </PlanningProvider>
  );
}
```

---

## 相关文档

- [04-backend-api](./04-backend-api.md) - SSE端点设计
- [02-agent-core](./02-agent-core.md) - Agent状态定义
- [terminology](./terminology.md) - SSE事件类型