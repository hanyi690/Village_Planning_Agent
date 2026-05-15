# 前端状态与组件架构

> **更新日期**: 2026-05-15
> **版本**: v4.0 (简化重构版)
> **状态**: ✅ 已完整实现

本文档详细说明前端状态管理架构、三栏工作台布局和 SSE 事件处理机制。

## 目录

- [Feature Module 结构](#feature-module-结构)
- [状态管理架构](#状态管理架构)
- [PlanningState 接口](#planningstate-接口)
- [三栏工作台布局](#三栏工作台布局)
- [组件层级图](#组件层级图)
- [SSE 批处理机制](#sse-批处理机制)
- [关键文件路径](#关键文件路径)

---

## Feature Module 结构

### 目录架构

前端已迁移到 **feature-based 目录架构**，所有规划相关代码集中在 `features/planning/` 模块：

```
frontend/src/features/planning/
├── api/                    # API 客户端和类型定义
│   ├── types.ts            # 统一 API 类型
│   ├── client.ts           # SSE 连接与请求封装
│   └── index.ts            # API 导出
├── components/
│   ├── layout/             # 布局组件
│   │   ├── AppHeader.tsx       # 顶部导航
│   │   ├── LayerNav.tsx        # 左侧维度导航
│   │   ├── FocusArea.tsx       # 中央工作区
│   │   ├── ReportViewer.tsx    # 报告查看器
│   │   └── ProcessPanel.tsx    # 右侧处理面板
│   ├── chat/               # 聊天组件
│   │   ├── MessageList.tsx     # 消息列表
│   │   ├── MessageBubble.tsx   # 消息气泡
│   │   ├── MessageContent.tsx  # 消息内容
│   │   ├── LayerReportMessage.tsx # 层级完成消息
│   │   ├── ProgressPanel.tsx   # 执行进度面板
│   │   ├── ToolStatusPanel.tsx # 工具状态面板
│   │   └── CheckpointMarker.tsx # 检查点标记
│   ├── gis/                # GIS 地图组件
│   │   ├── MapView.tsx
│   │   └── LegendPanel.tsx
│   ├── compare/            # 对比组件
│   │   ├── ReportComparePanel.tsx
│   │   └── ReportCompareModal.tsx
│   └── ui/                 # UI 通用组件
│       ├── MarkdownRenderer.tsx
│       └── KnowledgeReference.tsx
├── store/                  # Zustand 状态管理
│   └── planningStore.ts
├── hooks/                  # 自定义 Hooks
│   ├── useSSE.ts
│   ├── useSelectors.ts
│   └── useHandlers.ts
├── config/                 # 配置
│   └── dimensions.ts
├── constants/              # 常量
│   └── index.ts
├── types/                  # 类型定义
│   └── index.ts
└── utils/                  # 工具函数
    └── index.ts
```

---

## 状态管理架构

### Zustand + Immer

```typescript
// frontend/src/features/planning/store/planningStore.ts
import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';

export const usePlanningStore = create<PlanningState & PlanningActions>()(
  immer((set, get) => ({
    conversationId: '',
    sessionId: null,
    projectName: null,
    status: 'idle',
    phase: 'init',
    currentWave: 1,
    reports: {},
    pause_after_step: false,
    previous_layer: 0,
    step_mode: false,
  }))
);
```

### 状态选择器 Hooks

为优化性能，使用细粒度选择器避免不必要的重渲染：

```typescript
export function useStatus(): Status {
  return usePlanningStore((state) => state.status);
}

export function useCurrentLayer(): number | null {
  return usePlanningStore((state) => state.currentLayer);
}

export function useIsPaused(): boolean {
  return usePlanningStore((state) => state.isPaused);
}

export function useDimensionRagSources(dimKey: string): DimensionRagSource | null {
  return usePlanningStore((state) => state.dimensionRagSources[dimKey] || null);
}
```

---

## PlanningState 接口

### 核心字段

```typescript
export interface PlanningState {
  conversationId: string;

  // Session
  sessionId: string | null;
  projectName: string | null;
  status: Status;

  // Agent State (SSOT)
  phase: string;
  currentWave: number;
  reports: Reports;
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

  // SSE Reconnect
  sseResumeTrigger: number;
  lastProcessedSeq: number;

  // Messages
  messages: Message[];

  // Progress
  dimensionProgress: Record<string, DimensionProgressItem>;
  executingDimensions: string[];
  layerDimensionCount: Record<number, number>;
  layerProgressHistory: { layer1?: LayerProgressSnapshot; ... };

  // RAG & Cascade (Demo System)
  dimensionRagSources: Record<string, DimensionRagSource>;
  cascadeChain: CascadeChain | null;
  dimensionVersions: Record<string, number>;
  streamingContent: Record<string, string>;
  resettingDimensions: string[];
  runningTools: string[];

  // UI State
  viewerVisible: boolean;
  referencedSection?: string;
  viewingFile: FileMessage | null;
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  villageFormData: VillageInputData | null;
  progressPanelVisible: boolean;
  layerReportVisible: boolean;
  activeReportLayer: number;

  // History
  villages: VillageInfo[];
  selectedVillage: VillageInfo | null;
  selectedSession: VillageSession | null;
  historyLoading: boolean;

  // Checkpoints
  checkpoints: Checkpoint[];
  selectedCheckpoint: string | null;

  // Tools
  toolStatuses: Record<string, ToolStatus>;
  gisLayers: Record<string, GISLayerConfig[]>;

  // Three-Panel Layout Navigation State
  selectedNavigationKey: NavigationKey | null;
  isRightPanelExpanded: boolean;
  isLeftNavCollapsed: boolean;
}
```

### 三栏布局相关字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `selectedNavigationKey` | `NavigationKey \| null` | `null` | 当前选中导航键 |
| `isRightPanelExpanded` | `boolean` | `true` | 右侧处理面板展开状态 |
| `processPanelTab` | `ProcessPanelTab` | `'messages'` | 处理面板当前标签页 |

### NavigationKey 类型

```typescript
export const NAV_KEYS = {
  OVERVIEW: 'overview',
  dim: (key: string) => `dim:${key}`,
} as const;

export type NavigationKey = (typeof NAV_KEYS)[keyof typeof NAV_KEYS] | `dim:${string}`;
```

### ProcessPanelTab 类型

```typescript
export type ProcessPanelTab = 'messages' | 'map' | 'history';
```

---

## 三栏工作台布局

### 设计风格

- **配色**: 白色背景 + slate 中性色 + sky 强调色
  - 主背景: `bg-white` / `bg-slate-50`
  - 边框: `border-slate-200`
  - 强调色: `sky-500`/`emerald-500`
- **形状**: 8px-12px `rounded-lg/xl` 圆角
- **字体**: 全局 `text-sm`(14px) / `text-base`(16px) / `text-lg`(18px)
- **响应式**: `lg:` 断点（1024px）区分桌面和移动端

### 布局结构

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Dashboard                                  │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                        AppHeader                              │   │
│  │  [Logo]  [L1 Progress] [L2 Progress] [L3 Progress]  [Actions]│   │
│  └─────────────────────────────────────────────────────────────┘   │
├──────────┬──────────────────────────────────┬──────────────────────┤
│          │                                  │                      │
│ LayerNav │           FocusArea              │    ProcessPanel      │
│ (280px)  │           (flex:1)               │      (320px)         │
│          │                                  │                      │
│ ┌──────┐ │  ┌────────────────────────────┐  │  ┌────────────────┐  │
│ │导航  │ │  │      ReportViewer          │  │  │ [消息][地图][历史]│ │
│ │总览  │ │  │  ┌──────────────────────┐  │  │  ├────────────────┤  │
│ │      │ │  │  │   MarkdownRenderer   │  │  │  │   MessageList   │  │
│ │L1    │ │  │  │   (报告内容)         │  │  │  │                │  │
│ │L2    │ │  │  └──────────────────────┘  │  │  └────────────────┘  │
│ │L3    │ │  │  ┌──────────────────────┐  │  │  ┌────────────────┐  │
│ │      │ │  │  │  [知识来源] (可折叠) │  │  │  │   ChatInput    │  │
│ └──────┘ │  │  └──────────────────────┘  │  │  └────────────────┘  │
│ ┌──────┐ │  └────────────────────────────┘  │                      │
│ │工具  │ │                                  │                      │
│ │状态  │ │                                  │                      │
│ └──────┘ │                                  │                      │
└──────────┴──────────────────────────────────┴──────────────────────┘
```

### 布局尺寸（桌面端 lg:）

| 区域 | 尺寸 | 说明 |
|------|------|------|
| AppHeader | `h-[56px]` | 固定顶部，半透明背景 |
| LayerNav | `w-[280px]` | 左侧导航，可折叠层级 |
| FocusArea | `flex:1` | 中央内容区，`max-w-4xl` |
| ProcessPanel | `w-[320px]` | 右侧处理面板，可调整宽度 |

### 响应式行为

- **桌面端 (lg: 1024px+)**: 三栏并排内联布局
- **移动端 (<lg)**: LayerNav 切换为固定定位 overlay + 半透明 backdrop

### ReportViewer 内容切换

ReportViewer 根据 `selectedNavigationKey` 和 `status` 渲染不同内容：

| 条件 | 渲染组件 |
|------|----------|
| `status === 'idle'` | `VillageInputForm` |
| `selectedNavigationKey?.startsWith('dim:')` | 报告内容 + RAG 知识面板 |
| 默认（总览） | 规划总览 + Layer 摘要 |

### ProcessPanel 标签页

| 标签 | 内容 |
|------|------|
| `messages` | MessageList + ChatInput |
| `map` | MapView GIS 数据 |
| `history` | 历史会话列表 |

---

## 组件层级图

```
Dashboard (主容器)
├── AppHeader (顶部导航)
│   ├── Logo
│   ├── LayerProgressBar (L1/L2/L3 进度)
│   └── ActionButtons
├── <三栏布局>
│   ├── LayerNav (左侧 280px)
│   │   ├── 导航项（总览）
│   │   ├── Layer 展开列表
│   │   │   └── 维度项 + 状态圆点
│   │   └── ToolStatusPanel (底部折叠)
│   ├── FocusArea (中央 flex:1)
│   │   └── ReportViewer
│   │       ├── [idle] VillageInputForm
│   │       ├── [dim:*] 维度详情视图
│   │       │   ├── MarkdownRenderer (报告内容)
│   │       │   ├── RagKnowledgePanel (底部可折叠)
│   │       │   └── KnowledgeDetailDrawer (右侧抽屉)
│   │       └── [默认] 规划总览
│   └── ProcessPanel (右侧 320px)
│       ├── TabNavigation (消息/地图/历史)
│       ├── MessageList
│       └── ChatInput
└── ChatBar (底部输入栏)
```

### 组件使用状态

| 组件 | 文件路径 | 使用状态 |
|------|----------|----------|
| `Dashboard` | `components/Dashboard.tsx` | page.tsx 使用 |
| `AppHeader` | `components/layout/AppHeader.tsx` | Dashboard 使用 |
| `LayerNav` | `components/layout/LayerNav.tsx` | Dashboard 使用 |
| `FocusArea` | `components/layout/FocusArea.tsx` | Dashboard 使用 |
| `ReportViewer` | `components/layout/ReportViewer.tsx` | FocusArea 使用 |
| `ProcessPanel` | `components/layout/ProcessPanel.tsx` | Dashboard 使用 |
| `MessageList` | `components/chat/MessageList.tsx` | ProcessPanel 使用 |
| `MapView` | `components/gis/MapView.tsx` | ProcessPanel 使用 |
| `VillageInputForm` | `components/VillageInputForm.tsx` | ReportViewer 使用 |

---

## SSE 批处理机制

### 批处理参数

```typescript
const BATCH_WINDOW = 50;      // 50ms 批处理窗口
const MAX_BATCH_SIZE = 50;    // 最大队列大小
const MAX_DELTA_PER_KEY = 3;  // 每维度保留最新3个delta
```

### 关键事件类型（跳过队列）

```typescript
const criticalEventTypes = [
  'dimension_start', 'dimension_complete',
  'layer_started', 'layer_completed',
  'tool_started', 'tool_status',
  'rag_query', 'rag_result',
  'cascade_impact', 'cascade_complete',
  'dimension_reset', 'dimension_reset_complete',
  'state_sync', 'layer_paused',
];
```

### Override 机制

当 `dimension_complete` 事件到达时，跳过该维度所有待处理的 `dimension_delta` 事件：

```typescript
const completedDimensionKeysRef = useRef<Set<string>>(new Set());
if (completedKeys.has(key)) continue;
```

### Delta 合并策略

对于同一维度的多个 delta 事件，只保留最新的（包含完整 accumulated 内容）：

```typescript
let deltaList = dimensionDeltaMap.get(key);
if (!deltaList) {
  deltaList = [];
  dimensionDeltaMap.set(key, deltaList);
}
deltaList.push(event);
if (deltaList.length > MAX_DELTA_PER_KEY) deltaList.shift();
```

---

## SSE 事件类型

```typescript
export type PlanningSSEEventType =
  | 'tool_started' | 'tool_status'
  | 'tool_call' | 'tool_progress' | 'tool_result'       // Legacy
  | 'layer_started' | 'layer_completed'
  | 'dimension_start' | 'dimension_complete' | 'dimension_error'
  | 'dimension_delta' | 'dimension_revised'
  | 'dimension_reset' | 'dimension_reset_complete'
  | 'progress' | 'checkpoint_saved'
  | 'pause' | 'resumed' | 'completed' | 'complete' | 'error'
  | 'text_chunk' | 'content_delta'
  | 'ai_response_delta' | 'ai_response_complete'
  | 'thinking_start' | 'thinking' | 'thinking_end' | 'stream_paused'
  | 'review_request'
  | 'rag_query' | 'rag_result' | 'cascade_impact' | 'cascade_complete'
  | 'state_sync' | 'layer_paused' | 'connected';
```

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| 状态管理 | `frontend/src/features/planning/store/planningStore.ts` |
| SSE 连接 | `frontend/src/features/planning/hooks/useSSE.ts` |
| 状态选择器 | `frontend/src/features/planning/hooks/useSelectors.ts` |
| API 类型 | `frontend/src/features/planning/api/types.ts` |
| API 客户端 | `frontend/src/features/planning/api/client.ts` |
| 主布局 | `frontend/src/features/planning/components/Dashboard.tsx` |
| 顶部导航 | `frontend/src/features/planning/components/layout/AppHeader.tsx` |
| 左侧导航 | `frontend/src/features/planning/components/layout/LayerNav.tsx` |
| 中央工作区 | `frontend/src/features/planning/components/layout/FocusArea.tsx` |
| 报告查看器 | `frontend/src/features/planning/components/layout/ReportViewer.tsx` |
| 右侧面板 | `frontend/src/features/planning/components/layout/ProcessPanel.tsx` |
| 常量定义 | `frontend/src/features/planning/constants/index.ts` |
| 维度配置 | `frontend/src/features/planning/config/dimensions.ts` |

---

## 相关文档

- [10-frontend-components](./10-frontend-components.md) - 前端组件架构详解
- [04-backend-api](./04-backend-api.md) - 后端 API 与 SSE 架构
